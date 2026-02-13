"""Import conversation history from OpenCode."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Optional

from cb_memory.importers.base import BaseImporter
from cb_memory.models import MessageDoc, SessionDoc
from cb_memory.project import derive_project_id

logger = logging.getLogger(__name__)


class OpenCodeImporter(BaseImporter):
    """Import sessions and messages from OpenCode storage."""

    def run(self, path: Optional[str] = None) -> dict:
        """Import all OpenCode sessions from ~/.local/share/opencode/storage/."""
        # Default OpenCode storage location
        if path is None:
            storage_path = Path.home() / ".local/share/opencode/storage"
        else:
            storage_path = Path(path)

        if not storage_path.exists():
            logger.warning(f"OpenCode storage not found at {storage_path}")
            return {"error": "Storage path not found", "sessions_imported": 0}

        session_dir = storage_path / "session"
        message_dir = storage_path / "message"

        if not session_dir.exists():
            logger.warning(f"Session directory not found: {session_dir}")
            return {"error": "Session directory not found", "sessions_imported": 0}

        stats = {
            "sessions_imported": 0,
            "messages_imported": 0,
            "sessions_skipped": 0,
            "files_scanned": 0,
        }

        # Iterate through project hashes
        for project_hash_dir in session_dir.iterdir():
            if not project_hash_dir.is_dir():
                continue

            # Each session is a JSON file
            for session_file in project_hash_dir.glob("*.json"):
                stats["files_scanned"] += 1
                try:
                    imported, message_count = self._import_session(session_file, message_dir)
                    if imported:
                        stats["sessions_imported"] += 1
                        stats["messages_imported"] += message_count
                    else:
                        stats["sessions_skipped"] += 1
                except Exception as e:
                    logger.error(f"Failed to import session {session_file}: {e}")

        logger.info(f"OpenCode import complete: {stats}")
        return stats

    def _import_session(self, session_file: Path, message_dir: Path) -> tuple[bool, int]:
        """Import a single session and its messages."""
        with open(session_file, "r") as f:
            session_data = json.load(f)

        session_id_raw = session_data.get("id", session_file.stem)
        session_id = f"session::{session_id_raw}"
        directory = session_data.get("directory", "")
        project_id = derive_project_id(self.project_id, directory)

        # Re-sync existing sessions by replacing message set from source of truth.
        self._replace_existing_session_messages(session_id)

        # Create SessionDoc
        session = SessionDoc(
            id=session_id,
            title=session_data.get("title", "Untitled Session"),
            project_id=project_id,
            directory=directory,
            source="opencode",
            message_count=0,
            summary=session_data.get("summary", ""),
            tags=session_data.get("tags", []),
        )

        # Import messages
        message_count = 0
        session_msg_dir = message_dir / session_id_raw

        seq = 0
        if session_msg_dir.exists():
            for msg_file in sorted(session_msg_dir.glob("*.json")):
                try:
                    with open(msg_file, "r") as f:
                        msg_data = json.load(f)

                    full_text = msg_data.get("content", "")
                    chunks = self._split_text_chunks(full_text)
                    group_id = f"{session_id.removeprefix('session::')}::{message_count:08d}"
                    for chunk_index, chunk_text in enumerate(chunks):
                        msg = MessageDoc(
                            id=f"msg::{group_id}::{chunk_index:04d}",
                            session_id=session_id,
                            project_id=project_id,
                            role=msg_data.get("role", "user"),
                            text_content=chunk_text,
                            raw_content=msg_data.get("content") if chunk_index == 0 else None,
                            tool_calls=msg_data.get("toolCalls", []) if chunk_index == 0 else [],
                            tool_results=msg_data.get("toolResults", []) if chunk_index == 0 else [],
                            message_group_id=group_id,
                            chunk_index=chunk_index,
                            chunk_count=len(chunks),
                            original_sequence_number=message_count,
                            sequence_number=seq,
                        )
                        self.db.messages.upsert(msg.id, msg.model_dump(mode="json"))
                        seq += 1
                    message_count += 1
                except Exception as e:
                    logger.warning(f"Failed to import message {msg_file}: {e}")

        session.message_count = message_count
        self.db.sessions.upsert(session.id, session.model_dump(mode="json"))
        logger.debug(f"Imported session {session_id} with {message_count} messages")
        return True, message_count
