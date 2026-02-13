"""Import conversation history from Claude Code."""

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


class ClaudeCodeImporter(BaseImporter):
    """Import sessions from Claude Code storage."""

    def run(self, path: Optional[str] = None) -> dict:
        """Import Claude Code sessions from ~/.claude/projects/."""
        if path is None:
            claude_dir = Path.home() / ".claude/projects"
        else:
            claude_dir = Path(path)

        if not claude_dir.exists():
            logger.warning(f"Claude Code directory not found at {claude_dir}")
            return {"error": "Claude directory not found", "sessions_imported": 0}

        stats = {
            "sessions_imported": 0,
            "messages_imported": 0,
            "sessions_skipped": 0,
            "files_scanned": 0,
        }

        # Iterate through project directories
        for project_dir in claude_dir.iterdir():
            if not project_dir.is_dir():
                continue

            # Look for session/conversation files (JSONL format)
            for session_file in project_dir.glob("*.jsonl"):
                stats["files_scanned"] += 1
                try:
                    imported, count = self._import_session(session_file)
                    if imported:
                        stats["sessions_imported"] += 1
                        stats["messages_imported"] += count
                    else:
                        stats["sessions_skipped"] += 1
                except Exception as e:
                    logger.error(f"Failed to import session {session_file}: {e}")

        logger.info(f"Claude Code import complete: {stats}")
        return stats

    def _import_session(self, session_file: Path) -> tuple[bool, int]:
        """Import a single session from JSONL format."""
        session_id = f"session::claude::{session_file.stem}"

        # Parse JSONL file
        messages = []
        with open(session_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        entry = json.loads(line)
                        normalized = self._normalize_message(entry)
                        if normalized:
                            messages.extend(normalized)
                    except json.JSONDecodeError:
                        continue

        if not messages:
            logger.debug(f"No messages found in {session_file}")
            return False, 0

        # Re-sync existing sessions by replacing message set from source of truth.
        self._replace_existing_session_messages(session_id)

        # Create SessionDoc
        directory = self._extract_directory(messages, session_file.parent)
        project_id = derive_project_id(self.project_id, directory)
        session = SessionDoc(
            id=session_id,
            title=self._build_title(messages, session_file.stem),
            project_id=project_id,
            directory=directory,
            source="claude-code",
            message_count=len(messages),
            started_at=self._extract_started_at(messages) or datetime.now(timezone.utc),
        )

        # Import messages
        seq = 0
        for i, msg_data in enumerate(messages):
            full_text = self._extract_text(msg_data.get("content", ""))
            chunks = self._split_text_chunks(full_text)
            group_id = f"{session_id.removeprefix('session::')}::{i:08d}"
            for chunk_index, chunk_text in enumerate(chunks):
                msg = MessageDoc(
                    id=f"msg::{group_id}::{chunk_index:04d}",
                    session_id=session_id,
                    project_id=project_id,
                    role=msg_data.get("role", "user"),
                    text_content=chunk_text,
                    raw_content=msg_data.get("content") if chunk_index == 0 else None,
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

        self.db.sessions.upsert(session.id, session.model_dump(mode="json"))
        logger.debug(f"Imported Claude Code session {session_id} with {len(messages)} messages")
        return True, len(messages)

    def _extract_text(self, content) -> str:
        """Extract text from content (may be string or list of content blocks)."""
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            texts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    texts.append(block.get("text", ""))
                elif isinstance(block, str):
                    texts.append(block)
            if texts:
                return "\n".join(texts)
            return json.dumps(content, ensure_ascii=False)
        elif isinstance(content, dict):
            return json.dumps(content, ensure_ascii=False)
        return ""

    def _normalize_message(self, entry: dict) -> list[dict]:
        """Normalize Claude JSONL entry into one or more message dicts."""
        if not isinstance(entry, dict):
            return []
        if entry.get("isMeta") is True:
            return []

        role = entry.get("role")
        content = entry.get("content")
        cwd = entry.get("cwd")

        if isinstance(entry.get("message"), dict):
            message = entry["message"]
            role = message.get("role", role)
            content = message.get("content", content)
            cwd = message.get("cwd", cwd)

        if role in {"user", "assistant", "system", "tool"}:
            tool_calls, tool_results = self._extract_tools(content)
            return [
                {
                    "role": role,
                    "content": content,
                    "tool_calls": tool_calls,
                    "tool_results": tool_results,
                    "timestamp": entry.get("timestamp"),
                    "cwd": cwd,
                }
            ]

        # Some exports use envelope format with explicit event type and payload.
        payload = entry.get("payload")
        if isinstance(payload, dict):
            role = payload.get("role")
            content = payload.get("content")
            cwd = payload.get("cwd", cwd)
            if role in {"user", "assistant", "system", "tool"}:
                tool_calls, tool_results = self._extract_tools(content)
                return [
                    {
                        "role": role,
                        "content": content,
                        "tool_calls": tool_calls,
                        "tool_results": tool_results,
                        "timestamp": payload.get("timestamp", entry.get("timestamp")),
                        "cwd": cwd,
                    }
                ]

        return []

    def _extract_tools(self, content) -> tuple[list[dict], list[dict]]:
        """Extract tool_call and tool_result blocks from Claude content."""
        if not isinstance(content, list):
            return [], []

        tool_calls: list[dict] = []
        tool_results: list[dict] = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "tool_use":
                tool_calls.append(
                    {
                        "name": block.get("name", ""),
                        "id": block.get("id", ""),
                        "input": block.get("input", {}),
                    }
                )
            elif btype == "tool_result":
                tool_results.append(
                    {
                        "tool_use_id": block.get("tool_use_id", ""),
                        "content": self._extract_text(block.get("content", "")),
                    }
                )

        return tool_calls, tool_results

    def _build_title(self, messages: list[dict], fallback: str) -> str:
        first_user = next((m for m in messages if m.get("role") == "user"), None)
        if first_user:
            text = self._extract_text(first_user.get("content", "")).strip()
            if text:
                return text.splitlines()[0][:90]
        return f"Claude Session {fallback}"

    def _extract_started_at(self, messages: list[dict]):
        for message in messages:
            value = message.get("timestamp")
            if not isinstance(value, str) or not value:
                continue
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            except Exception:
                continue
        return None

    def _extract_directory(self, messages: list[dict], fallback_parent: Path) -> str:
        for message in messages:
            cwd = message.get("cwd")
            if isinstance(cwd, str) and cwd.strip():
                return cwd.strip()
        return str(fallback_parent)
