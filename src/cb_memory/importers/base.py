"""Base importer interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from cb_memory.config import Settings
from cb_memory.db import CouchbaseClient


class BaseImporter(ABC):
    """Base class for all importers."""

    def __init__(
        self,
        db: CouchbaseClient,
        settings: Settings,
        project_id: str = "default",
    ) -> None:
        self.db = db
        self.settings = settings
        self.project_id = project_id

    @abstractmethod
    def run(self, path: Optional[str] = None) -> dict:
        """Run the import process.

        Returns:
            dict with stats: sessions_imported, messages_imported, etc.
        """
        pass

    def _replace_existing_session_messages(self, session_id: str) -> None:
        """Delete existing messages for a session so re-import is idempotent and complete."""
        bucket = self.db._settings.cb_bucket
        query = (
            f"DELETE FROM `{bucket}`.conversations.messages m "
            "WHERE m.session_id = $session_id"
        )
        try:
            self.db.cluster.query(query, session_id=session_id)
        except Exception:
            # Best-effort cleanup. Upserts will still proceed.
            pass

    @staticmethod
    def _split_text_chunks(text: str, chunk_size: int = 8000) -> list[str]:
        if not text:
            return [""]
        if len(text) <= chunk_size:
            return [text]
        return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]
