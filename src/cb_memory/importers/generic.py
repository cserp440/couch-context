"""Generic importer for JSON and Markdown conversation files."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Optional

from cb_memory.importers.base import BaseImporter
from cb_memory.models import MessageDoc, SessionDoc
from cb_memory.project import derive_project_id

logger = logging.getLogger(__name__)


class GenericImporter(BaseImporter):
    """Import from generic JSON or Markdown format."""

    def __init__(self, *args, fmt: str = "json", **kwargs):
        super().__init__(*args, **kwargs)
        self.format = fmt

    def run(self, path: Optional[str] = None) -> dict:
        """Import sessions from the specified path."""
        if path is None:
            raise ValueError("path is required for generic import")

        path_obj = Path(path)
        if not path_obj.exists():
            return {"error": "Path not found", "sessions_imported": 0}

        stats = {"sessions_imported": 0, "messages_imported": 0}

        if path_obj.is_file():
            # Import single file
            try:
                count = self._import_file(path_obj)
                stats["sessions_imported"] = 1
                stats["messages_imported"] = count
            except Exception as e:
                logger.error(f"Failed to import {path_obj}: {e}")
        elif path_obj.is_dir():
            # Import all matching files in directory
            pattern = "*.json" if self.format == "json" else "*.md"
            for file in path_obj.glob(pattern):
                try:
                    count = self._import_file(file)
                    stats["sessions_imported"] += 1
                    stats["messages_imported"] += count
                except Exception as e:
                    logger.error(f"Failed to import {file}: {e}")

        logger.info(f"Generic import complete: {stats}")
        return stats

    def _import_file(self, file: Path) -> int:
        """Import a single file."""
        if self.format == "json":
            return self._import_json(file)
        else:
            return self._import_markdown(file)

    def _import_json(self, file: Path) -> int:
        """Import from JSON format.

        Expected format:
        {
            "title": "Session title",
            "messages": [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
        """
        with open(file, "r") as f:
            data = json.load(f)

        session_id = f"session::{file.stem}"
        messages_data = data.get("messages", [])
        project_id = derive_project_id(self.project_id, str(file.parent))

        session = SessionDoc(
            id=session_id,
            title=data.get("title", file.stem),
            project_id=project_id,
            source="json-import",
            message_count=len(messages_data),
        )

        for i, msg_data in enumerate(messages_data):
            msg = MessageDoc(
                session_id=session_id,
                project_id=project_id,
                role=msg_data.get("role", "user"),
                text_content=msg_data.get("content", ""),
                sequence_number=i,
            )
            msg.generate_id()
            self.db.messages.upsert(msg.id, msg.model_dump(mode="json"))

        self.db.sessions.upsert(session.id, session.model_dump(mode="json"))
        logger.debug(f"Imported JSON session {session_id} with {len(messages_data)} messages")
        return len(messages_data)

    def _import_markdown(self, file: Path) -> int:
        """Import from Markdown format.

        Expected format:
        # Session Title

        ## User
        User message here

        ## Assistant
        Assistant response here
        """
        with open(file, "r") as f:
            content = f.read()

        session_id = f"session::{file.stem}"
        title = "Untitled"
        project_id = derive_project_id(self.project_id, str(file.parent))

        # Extract title from first H1
        title_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()

        # Split into messages by ## headers
        message_pattern = re.compile(r"^##\s+(User|Assistant|System)\s*\n(.*?)(?=^##|\Z)", re.MULTILINE | re.DOTALL)
        messages_data = []

        for match in message_pattern.finditer(content):
            role = match.group(1).lower()
            text = match.group(2).strip()
            messages_data.append({"role": role, "content": text})

        if not messages_data:
            logger.debug(f"No messages found in markdown file {file}")
            return 0

        session = SessionDoc(
            id=session_id,
            title=title,
            project_id=project_id,
            source="markdown-import",
            message_count=len(messages_data),
        )

        for i, msg_data in enumerate(messages_data):
            msg = MessageDoc(
                session_id=session_id,
                project_id=project_id,
                role=msg_data["role"],
                text_content=msg_data["content"],
                sequence_number=i,
            )
            msg.generate_id()
            self.db.messages.upsert(msg.id, msg.model_dump(mode="json"))

        self.db.sessions.upsert(session.id, session.model_dump(mode="json"))
        logger.debug(f"Imported markdown session {session_id} with {len(messages_data)} messages")
        return len(messages_data)
