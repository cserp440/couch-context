"""Import conversation history from Factory Droid sessions."""

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


class FactoryImporter(BaseImporter):
    """Import sessions from Factory JSONL session logs."""

    def run(self, path: Optional[str] = None) -> dict:
        if path is None:
            source_path = Path.home() / ".factory" / "sessions"
        else:
            source_path = Path(path)

        if not source_path.exists():
            logger.warning(f"Factory sessions directory not found at {source_path}")
            return {"error": "Factory sessions directory not found", "sessions_imported": 0}

        stats = {
            "sessions_imported": 0,
            "messages_imported": 0,
            "sessions_skipped": 0,
            "files_scanned": 0,
        }

        for session_file in sorted(source_path.rglob("*.jsonl")):
            # Skip settings files
            if session_file.name.endswith(".settings.jsonl"):
                continue
            stats["files_scanned"] += 1
            try:
                imported, message_count = self._import_session_file(session_file)
                if imported:
                    stats["sessions_imported"] += 1
                    stats["messages_imported"] += message_count
                else:
                    stats["sessions_skipped"] += 1
            except Exception as e:
                logger.error(f"Failed to import Factory session {session_file}: {e}")

        logger.info(f"Factory import complete: {stats}")
        return stats

    def _import_session_file(self, session_file: Path) -> tuple[bool, int]:
        session_meta = None
        messages: list[dict] = []

        with open(session_file, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue

                entry_type = entry.get("type")
                if entry_type == "session_start":
                    session_meta = entry
                    continue

                if entry_type == "message":
                    normalized = self._normalize_message(entry)
                    if normalized:
                        messages.append(normalized)

        if not messages:
            return False, 0

        session_token = session_meta.get("id") if session_meta else session_file.stem
        session_id = f"session::factory::{session_token}"

        # Re-sync existing sessions by replacing message set from source of truth.
        self._replace_existing_session_messages(session_id)

        title = self._build_title(messages, session_meta, session_file)
        directory = session_meta.get("cwd", "") if session_meta else ""
        started_at = self._parse_dt(session_meta.get("timestamp")) if session_meta else None
        project_id = derive_project_id(self.project_id, directory)

        session = SessionDoc(
            id=session_id,
            title=title,
            project_id=project_id,
            directory=directory,
            source="factory",
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

    def _normalize_message(self, entry: dict) -> dict | None:
        """Normalize a Factory message entry."""
        msg_data = entry.get("message")
        if not isinstance(msg_data, dict):
            return None

        role = msg_data.get("role")
        if role not in ("user", "assistant", "tool"):
            return None

        content_parts = msg_data.get("content", [])
        if not isinstance(content_parts, list):
            content_parts = [{"type": "text", "text": str(content_parts)}]

        text_parts: list[str] = []
        tool_calls: list[dict] = []
        tool_results: list[dict] = []

        for part in content_parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")

            if part_type == "text":
                text = part.get("text", "")
                if isinstance(text, str) and text.strip():
                    text_parts.append(text.strip())

            elif part_type == "tool_use":
                name = part.get("name", "")
                call_id = part.get("id", "")
                input_data = part.get("input", {})
                tool_calls.append({
                    "name": name,
                    "id": call_id,
                    "input": input_data if isinstance(input_data, dict) else {"value": input_data},
                })
                label = f"{name}"
                if isinstance(input_data, dict):
                    subagent = input_data.get("subagent_type") or input_data.get("description")
                    if subagent:
                        label = f"{name} ({subagent})"
                text_parts.append(f"Tool call: {label}")

            elif part_type == "tool_result":
                tool_use_id = part.get("tool_use_id", "")
                result_content = part.get("content", "")
                if isinstance(result_content, str):
                    summary = result_content.splitlines()[0][:180] if result_content else ""
                else:
                    summary = ""
                tool_results.append({
                    "tool_use_id": tool_use_id,
                    "content": result_content,
                })
                label = f"Tool result for {tool_use_id}"
                if summary:
                    label += f": {summary}"
                text_parts.append(label)

        content = "\n".join(text_parts)
        if not content:
            return None

        return {
            "role": role,
            "content": content,
            "raw_content": msg_data,
            "tool_calls": tool_calls,
            "tool_results": tool_results,
        }

    @staticmethod
    def _build_title(messages: list[dict], session_meta: dict | None, session_file: Path) -> str:
        if session_meta and session_meta.get("title"):
            return session_meta["title"]
        if session_meta and session_meta.get("sessionTitle"):
            return session_meta["sessionTitle"]
        first_user = next((m["content"] for m in messages if m["role"] == "user"), "")
        if first_user:
            first_line = first_user.strip().splitlines()[0][:90]
            return first_line or f"Factory Session {session_file.stem}"
        return f"Factory Session {session_file.stem}"

    @staticmethod
    def _parse_dt(value) -> Optional[datetime]:
        if not isinstance(value, str) or not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None
