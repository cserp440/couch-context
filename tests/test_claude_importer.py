"""Tests for Claude Code session importer."""

from __future__ import annotations

import json
from pathlib import Path

from cb_memory.importers.claude_code import ClaudeCodeImporter


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for item in lines:
            f.write(json.dumps(item) + "\n")


def test_claude_importer_imports_and_is_idempotent(tmp_path: Path):
    db = _Db()
    importer = ClaudeCodeImporter(db, _Settings(), project_id="proj")

    project_dir = tmp_path / "my-project"
    session_file = project_dir / "chat-1.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "role": "user",
                "content": [{"type": "text", "text": "Implement retrieval layer"}],
                "timestamp": "2026-02-12T12:00:00Z",
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done"}],
                "timestamp": "2026-02-12T12:01:00Z",
            },
        ],
    )

    first = importer.run(str(tmp_path))
    assert first["sessions_imported"] == 1
    assert first["messages_imported"] == 2
    assert first["sessions_skipped"] == 0
    assert first["files_scanned"] == 1

    second = importer.run(str(tmp_path))
    assert second["sessions_imported"] == 0
    assert second["sessions_skipped"] == 1


def test_claude_importer_persists_tool_calls_and_results(tmp_path: Path):
    db = _Db()
    importer = ClaudeCodeImporter(db, _Settings(), project_id="proj")

    project_dir = tmp_path / "my-project"
    session_file = project_dir / "chat-tools.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "role": "assistant",
                "content": [
                    {"type": "text", "text": "Calling tool"},
                    {"type": "tool_use", "id": "toolu_1", "name": "read_file", "input": {"path": "README.md"}},
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": "toolu_1", "content": "file content"},
                    {"type": "text", "text": "continue"},
                ],
            },
        ],
    )

    out = importer.run(str(tmp_path))
    assert out["sessions_imported"] == 1
    assert out["messages_imported"] == 2

    saved_messages = list(db.messages.docs.values())
    assert len(saved_messages) == 2
    assert saved_messages[0]["tool_calls"] == [
        {"name": "read_file", "id": "toolu_1", "input": {"path": "README.md"}}
    ]
    assert saved_messages[1]["tool_results"] == [
        {"tool_use_id": "toolu_1", "content": "file content"}
    ]


def test_claude_importer_uses_message_cwd_for_project_and_directory(tmp_path: Path):
    db = _Db()
    importer = ClaudeCodeImporter(db, _Settings(), project_id="default")

    session_file = tmp_path / "encoded-project" / "chat-cwd.jsonl"
    expected_cwd = "/Users/ruchit/Downloads/cb-retrival"
    _write_jsonl(
        session_file,
        [
            {
                "role": "user",
                "cwd": expected_cwd,
                "content": [{"type": "text", "text": "hello from cwd"}],
            },
            {
                "role": "assistant",
                "cwd": expected_cwd,
                "content": [{"type": "text", "text": "ack"}],
            },
        ],
    )

    out = importer.run(str(tmp_path))
    assert out["sessions_imported"] == 1
    saved_session = next(iter(db.sessions.docs.values()))
    assert saved_session["directory"] == expected_cwd
    assert saved_session["project_id"] == expected_cwd


def test_claude_importer_skips_meta_records(tmp_path: Path):
    db = _Db()
    importer = ClaudeCodeImporter(db, _Settings(), project_id="default")

    session_file = tmp_path / "meta-project" / "chat-meta.jsonl"
    _write_jsonl(
        session_file,
        [
            {
                "isMeta": True,
                "role": "user",
                "content": [{"type": "text", "text": "meta should be skipped"}],
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": "real message"}],
            },
        ],
    )

    out = importer.run(str(tmp_path))
    assert out["sessions_imported"] == 1
    assert out["messages_imported"] == 1
