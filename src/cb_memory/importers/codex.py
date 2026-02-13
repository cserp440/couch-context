"""Import conversation history from Codex Desktop/CLI sessions."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from cb_memory.importers.base import BaseImporter
from cb_memory.models import MessageDoc, SessionDoc
from cb_memory.project import derive_project_id

logger = logging.getLogger(__name__)


class CodexImporter(BaseImporter):
    """Import sessions from Codex JSONL session logs."""

    def run(self, path: Optional[str] = None) -> dict:
        if path is None:
            source_path = Path.home() / ".codex"
        else:
            source_path = Path(path)

        scan_dirs = self._resolve_scan_dirs(source_path)
        if not scan_dirs:
            logger.warning(f"Codex sessions directory not found at {source_path}")
            return {"error": "Codex sessions directory not found", "sessions_imported": 0}

        stats = {
            "sessions_imported": 0,
            "messages_imported": 0,
            "sessions_skipped": 0,
            "files_scanned": 0,
        }

        for scan_dir in scan_dirs:
            for session_file in sorted(scan_dir.rglob("*.jsonl")):
                stats["files_scanned"] += 1
                try:
                    imported, message_count = self._import_session_file(session_file)
                    if imported:
                        stats["sessions_imported"] += 1
                        stats["messages_imported"] += message_count
                    else:
                        stats["sessions_skipped"] += 1
                except Exception as e:
                    logger.error(f"Failed to import Codex session {session_file}: {e}")

        logger.info(f"Codex import complete: {stats}")
        return stats

    @staticmethod
    def _resolve_scan_dirs(source_path: Path) -> list[Path]:
        if not source_path.exists():
            return []

        # Supports:
        # - ~/.codex (scan sessions + archived_sessions)
        # - ~/.codex/sessions or ~/.codex/archived_sessions
        if source_path.is_dir():
            sessions_dir = source_path / "sessions"
            archived_dir = source_path / "archived_sessions"
            dirs = [d for d in [sessions_dir, archived_dir] if d.exists() and d.is_dir()]
            if dirs:
                return dirs
            return [source_path]
        return []

    def _import_session_file(self, session_file: Path) -> tuple[bool, int]:
        session_meta = None
        messages: list[dict] = []
        tracked_call_ids: set[str] = set()

        with open(session_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if entry.get("type") == "session_meta":
                    payload = entry.get("payload")
                    if isinstance(payload, dict):
                        session_meta = payload
                    continue

                normalized = self._normalize_entry(entry, tracked_call_ids)
                if normalized:
                    messages.extend(normalized)

        if not messages:
            return False, 0

        session_token = self._session_token(session_file, session_meta)
        session_id = f"session::codex::{session_token}"

        # Re-sync existing sessions by replacing message set from source of truth.
        self._replace_existing_session_messages(session_id)

        title = self._build_title(messages, session_file)
        directory = ""
        started_at = None
        if isinstance(session_meta, dict):
            directory = str(session_meta.get("cwd", ""))
            started_at = self._parse_dt(session_meta.get("timestamp"))
        project_id = derive_project_id(self.project_id, directory)

        session = SessionDoc(
            id=session_id,
            title=title,
            project_id=project_id,
            directory=directory,
            source="codex",
            message_count=len(messages),
            started_at=started_at or datetime.now(timezone.utc),
        )

        tools_used = set()
        seq = 0
        for i, msg_data in enumerate(messages):
            chunks = self._split_text_chunks(msg_data["content"])
            group_id = f"{session_id.removeprefix('session::')}::{i:08d}"
            for chunk_index, chunk_text in enumerate(chunks):
                msg = MessageDoc(
                    id=f"msg::{group_id}::{chunk_index:04d}",
                    session_id=session_id,
                    project_id=project_id,
                    role=msg_data["role"],
                    text_content=chunk_text,
                    raw_content=msg_data.get("raw_content") if chunk_index == 0 else None,
                    tool_calls=msg_data.get("tool_calls", []) if chunk_index == 0 else [],
                    tool_results=msg_data.get("tool_results", []) if chunk_index == 0 else [],
                    message_group_id=group_id,
                    chunk_index=chunk_index,
                    chunk_count=len(chunks),
                    original_sequence_number=i,
                    sequence_number=seq,
                )
                self.db.messages.upsert(msg.id, msg.model_dump(mode="json"))
                seq += 1

            for tc in msg_data.get("tool_calls", []):
                if isinstance(tc, dict) and tc.get("name"):
                    tools_used.add(str(tc["name"]))

        session.tools_used = sorted(tools_used)

        self.db.sessions.upsert(session.id, session.model_dump(mode="json"))
        return True, len(messages)

    def _normalize_entry(self, entry: dict, tracked_call_ids: set[str]) -> list[dict]:
        """Normalize one Codex JSONL entry into one or more messages."""
        if entry.get("type") == "event_msg":
            payload = entry.get("payload")
            if not isinstance(payload, dict):
                return []
            msg_type = payload.get("type")
            if msg_type == "user_message":
                raw_message = payload.get("message")
                text = self._normalize_text(raw_message)
                if text:
                    return [{"role": "user", "content": text, "raw_content": raw_message, "tool_calls": [], "tool_results": []}]
            elif msg_type == "agent_message":
                raw_message = payload.get("message")
                text = self._normalize_text(raw_message)
                if text:
                    return [{"role": "assistant", "content": text, "raw_content": raw_message, "tool_calls": [], "tool_results": []}]
            return []

        if entry.get("type") != "response_item":
            return []

        payload = entry.get("payload")
        if not isinstance(payload, dict):
            return []

        payload_type = payload.get("type")
        if payload_type == "function_call":
            name = str(payload.get("name") or "")
            if not name:
                return []
            call_id = str(payload.get("call_id") or "")
            arguments = self._parse_json_value(payload.get("arguments"))
            tool_call = {
                "name": name,
                "id": call_id,
                "input": arguments if isinstance(arguments, (dict, list)) else {"value": arguments},
            }
            if call_id:
                tracked_call_ids.add(call_id)
            label = self._tool_call_label(name, tool_call["input"])
            return [
                {
                    "role": "assistant",
                    "content": f"Tool call: {label}",
                    "raw_content": payload,
                    "tool_calls": [tool_call],
                    "tool_results": [],
                }
            ]

        if payload_type == "function_call_output":
            call_id = str(payload.get("call_id") or "")
            if not call_id:
                return []
            output_text = self._normalize_text(payload.get("output"))
            summary = output_text.splitlines()[0][:180] if output_text else ""
            content = f"Tool result for {call_id}"
            if summary:
                content += f": {summary}"
            return [
                {
                    "role": "tool",
                    "content": content,
                    "raw_content": payload,
                    "tool_calls": [],
                    "tool_results": [{"tool_use_id": call_id, "content": output_text}],
                }
            ]

        return []

    @staticmethod
    def _parse_json_value(value):
        if isinstance(value, (dict, list)):
            return value
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return ""
            try:
                return json.loads(stripped)
            except json.JSONDecodeError:
                return value
        return value

    @staticmethod
    def _tool_call_label(name: str, input_data) -> str:
        if not isinstance(input_data, dict):
            return name
        if name == "Task":
            subagent_type = input_data.get("subagent_type")
            if isinstance(subagent_type, str) and subagent_type:
                return f"{name} ({subagent_type})"
        if name == "skill":
            skill_name = (
                input_data.get("name")
                or input_data.get("skill")
                or input_data.get("skill_name")
                or input_data.get("path")
            )
            if isinstance(skill_name, str) and skill_name:
                return f"{name} ({skill_name})"
        return name

    @staticmethod
    def _is_skill_or_subagent_call(name: str, input_data) -> bool:
        if name in {"Task", "skill"}:
            return True
        if isinstance(input_data, dict):
            if isinstance(input_data.get("subagent_type"), str) and input_data.get("subagent_type"):
                return True
            for key in ("skill", "skill_name", "path"):
                value = input_data.get(key)
                if isinstance(value, str) and value:
                    return True
        return False

    @staticmethod
    def _session_token(session_file: Path, session_meta: Optional[dict]) -> str:
        if isinstance(session_meta, dict):
            sid = session_meta.get("id")
            if sid:
                return str(sid)
        return session_file.stem

    @staticmethod
    def _build_title(messages: list[dict], session_file: Path) -> str:
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        if first_user:
            first_line = first_user.strip().splitlines()[0][:90]
            return first_line or f"Codex Session {session_file.stem}"
        return f"Codex Session {session_file.stem}"

    @staticmethod
    def _normalize_text(value) -> str:
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            parts: list[str] = []
            for item in value:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    text = item.get("text") or item.get("output_text") or item.get("input_text")
                    if isinstance(text, str):
                        parts.append(text)
            normalized = "\n".join(p.strip() for p in parts if p and p.strip())
            if normalized:
                return normalized
            return json.dumps(value, ensure_ascii=False)
        if isinstance(value, dict):
            text = value.get("text") or value.get("output_text") or value.get("input_text")
            if isinstance(text, str) and text.strip():
                return text.strip()
            return json.dumps(value, ensure_ascii=False)
        return ""

    @staticmethod
    def _parse_dt(value) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
