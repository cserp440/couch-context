"""Startup sync helpers for automatic history ingestion."""

from __future__ import annotations

import logging
from pathlib import Path

from cb_memory.importers.claude_code import ClaudeCodeImporter
from cb_memory.importers.codex import CodexImporter

logger = logging.getLogger(__name__)


def _run_sync(
    db,
    settings,
    *,
    source: str,
    enabled: bool,
    path_value: str,
    project_id: str | None,
    importer_cls,
) -> dict:
    if not enabled:
        return {"status": "disabled", "source": source}

    sync_project_id = project_id or settings.default_project_id
    path = str(Path(path_value).expanduser())

    try:
        importer = importer_cls(db, settings, sync_project_id)
        stats = importer.run(path=path)
        return {
            "status": "ok",
            "source": source,
            "path": path,
            "project_id": sync_project_id,
            "stats": stats,
        }
    except Exception as e:
        logger.warning(f"{source} auto-sync failed: {e}")
        return {
            "status": "error",
            "source": source,
            "path": path,
            "project_id": sync_project_id,
            "error": str(e),
        }


def auto_sync_claude(
    db,
    settings,
    project_id: str | None = None,
    importer_cls=ClaudeCodeImporter,
) -> dict:
    """Auto-import Claude Code chat history on server startup."""
    return _run_sync(
        db=db,
        settings=settings,
        source="claude-code",
        enabled=bool(getattr(settings, "auto_import_claude_on_start", True)),
        path_value=getattr(settings, "auto_import_claude_path", str(Path.home() / ".claude/projects")),
        project_id=project_id,
        importer_cls=importer_cls,
    )


def auto_sync_codex(
    db,
    settings,
    project_id: str | None = None,
    importer_cls=CodexImporter,
) -> dict:
    """Auto-import Codex chat history on server startup."""
    return _run_sync(
        db=db,
        settings=settings,
        source="codex",
        enabled=bool(getattr(settings, "auto_import_codex_on_start", True)),
        path_value=getattr(settings, "auto_import_codex_path", str(Path.home() / ".codex/sessions")),
        project_id=project_id,
        importer_cls=importer_cls,
    )
