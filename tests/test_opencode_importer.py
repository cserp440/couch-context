"""Tests for OpenCode importer idempotency."""

from __future__ import annotations

import json
from pathlib import Path

from cb_memory.importers.opencode import OpenCodeImporter


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


# def test_opencode_importer_is_idempotent(tmp_path: Path):
#     db = _Db()
#     importer = OpenCodeImporter(db, _Settings(), project_id="default")

#     storage = tmp_path / "storage"
#     session_dir = storage / "session" / "project-hash"
#     message_dir = storage / "message" / "s1"
#     session_dir.mkdir(parents=True)
#     message_dir.mkdir(parents=True)

#     with open(session_dir / "s1.json", "w", encoding="utf-8") as f:
#         json.dump({"id": "s1", "title": "OpenCode Session", "directory": "/tmp/work"}, f)

#     with open(message_dir / "m1.json", "w", encoding="utf-8") as f:
#         json.dump({"role": "user", "content": "hello"}, f)

#     first = importer.run(str(storage))
#     assert first["sessions_imported"] == 1
#     assert first["messages_imported"] == 1
#     assert first["sessions_skipped"] == 0

#     second = importer.run(str(storage))
#     assert second["sessions_imported"] == 0
#     assert second["messages_imported"] == 0
#     assert second["sessions_skipped"] == 1
