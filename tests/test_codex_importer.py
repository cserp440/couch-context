"""Tests for Codex session importer."""

from __future__ import annotations

import json
from pathlib import Path

from cb_memory.importers.codex import CodexImporter


class _Collection:
    def __init__(self):
        self.docs = {}

    def upsert(self, doc_id, value):
        self.docs[doc_id] = value

    def get(self, doc_id):
        if doc_id not in self.docs:
            raise KeyError(doc_id)
        return self.docs[doc_id]


class _Db:
    def __init__(self):
        self.sessions = _Collection()
        self.messages = _Collection()


class _Settings:
    pass


def _write_jsonl(path: Path, lines: list[dict]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")


def test_codex_importer_imports_session_and_is_idempotent(tmp_path: Path):
    db = _Db()
    importer = CodexImporter(db, _Settings(), project_id="proj")

    session_file = tmp_path / "rollout-1.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "session-abc",
                    "cwd": "/tmp/work",
                    "timestamp": "2026-02-12T12:00:00Z",
                },
            },
            {"type": "event_msg", "payload": {"type": "user_message", "message": "hello"}},
            {"type": "event_msg", "payload": {"type": "agent_message", "message": "hi there"}},
        ],
    )

    first = importer.run(str(tmp_path))
    assert first["sessions_imported"] == 1
    assert first["messages_imported"] == 2

    # Re-importing should skip because session already exists.
    second = importer.run(str(tmp_path))
    assert second["sessions_imported"] == 0
    assert second["sessions_skipped"] == 1


def test_codex_importer_scans_sessions_and_archived_from_codex_home(tmp_path: Path):
    db = _Db()
    importer = CodexImporter(db, _Settings(), project_id="default")

    codex_home = tmp_path / ".codex"
    sessions_dir = codex_home / "sessions"
    archived_dir = codex_home / "archived_sessions"
    sessions_dir.mkdir(parents=True)
    archived_dir.mkdir(parents=True)

    _write_jsonl(
        sessions_dir / "s1.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"id": "s1", "cwd": "/tmp/proj-a", "timestamp": "2026-02-12T12:00:00Z"},
            },
            {"type": "event_msg", "payload": {"type": "user_message", "message": "a"}},
        ],
    )
    _write_jsonl(
        archived_dir / "s2.jsonl",
        [
            {
                "type": "session_meta",
                "payload": {"id": "s2", "cwd": "/tmp/proj-b", "timestamp": "2026-02-12T12:01:00Z"},
            },
            {"type": "event_msg", "payload": {"type": "user_message", "message": "b"}},
        ],
    )

    out = importer.run(str(codex_home))
    assert out["sessions_imported"] == 2
    assert out["messages_imported"] == 2
    assert out["files_scanned"] == 2


def test_codex_importer_persists_skill_and_subagent_tool_calls(tmp_path: Path):
    db = _Db()
    importer = CodexImporter(db, _Settings(), project_id="proj")

    session_file = tmp_path / "skills-subagents.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "type": "session_meta",
                "payload": {
                    "id": "session-tools",
                    "cwd": "/tmp/work",
                    "timestamp": "2026-02-12T12:00:00Z",
                },
            },
            {"type": "event_msg", "payload": {"type": "user_message", "message": "run planning"}},
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "Task",
                    "call_id": "call_subagent",
                    "arguments": "{\"description\":\"plan\",\"subagent_type\":\"Plan\"}",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "skill",
                    "call_id": "call_skill",
                    "arguments": "{\"skill_name\":\"checks\"}",
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call_subagent",
                    "output": "subagent done",
                },
            },
        ],
    )

    out = importer.run(str(tmp_path))
    assert out["sessions_imported"] == 1
    assert out["messages_imported"] == 4

    saved_session = next(iter(db.sessions.docs.values()))
    assert saved_session["tools_used"] == ["Task", "skill"]

    saved_messages = list(db.messages.docs.values())
    task_msg = next(m for m in saved_messages if any(tc.get("name") == "Task" for tc in m.get("tool_calls", [])))
    assert any(tc.get("name") == "Task" for tc in task_msg["tool_calls"])
    task_call = next(tc for tc in task_msg["tool_calls"] if tc.get("name") == "Task")
    assert task_call["input"]["subagent_type"] == "Plan"
    skill_msg = next(m for m in saved_messages if any(tc.get("name") == "skill" for tc in m.get("tool_calls", [])))
    assert any(tc.get("name") == "skill" for tc in skill_msg["tool_calls"])
    skill_call = next(tc for tc in skill_msg["tool_calls"] if tc.get("name") == "skill")
    assert skill_call["input"]["skill_name"] == "checks"

    tool_result_msg = next(m for m in saved_messages if m.get("tool_results"))
    assert tool_result_msg["tool_results"][0]["tool_use_id"] == "call_subagent"
