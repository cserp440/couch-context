"""Startup sync helpers for automatic history ingestion."""

from __future__ import annotations

import logging
from pathlib import Path
import threading
import time

from cb_memory.importers.claude_code import ClaudeCodeImporter
from cb_memory.importers.codex import CodexImporter

logger = logging.getLogger(__name__)

_query_sync_lock = threading.Lock()
_last_query_sync_monotonic = 0.0
_last_query_sync_result: dict | None = None


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


def maybe_auto_sync_recent(
    db,
    settings,
    project_id: str | None = None,
    *,
    force: bool = False,
    now_monotonic: float | None = None,
    claude_importer_cls=ClaudeCodeImporter,
    codex_importer_cls=CodexImporter,
) -> dict:
    """Auto-sync on query with cooldown to keep memory fresh."""
    global _last_query_sync_monotonic
    global _last_query_sync_result

    if not bool(getattr(settings, "auto_import_on_query", True)):
        return {"status": "disabled", "reason": "auto_import_on_query=false"}

    interval_seconds = max(0, int(getattr(settings, "auto_import_min_interval_seconds", 45)))
    now = now_monotonic if now_monotonic is not None else time.monotonic()

    with _query_sync_lock:
        elapsed = now - _last_query_sync_monotonic
        if not force and _last_query_sync_monotonic > 0 and elapsed < interval_seconds:
            return {
                "status": "skipped",
                "reason": "cooldown",
                "seconds_until_next": max(0, int(interval_seconds - elapsed)),
                "last_sync": _last_query_sync_result,
            }

        claude = auto_sync_claude(
            db=db,
            settings=settings,
            project_id=project_id,
            importer_cls=claude_importer_cls,
        )
        codex = auto_sync_codex(
            db=db,
            settings=settings,
            project_id=project_id,
            importer_cls=codex_importer_cls,
        )
        result = {
            "status": "ok",
            "claude": claude,
            "codex": codex,
            "interval_seconds": interval_seconds,
        }
        _last_query_sync_monotonic = now
        _last_query_sync_result = result
        return result


def _reset_query_sync_state_for_tests() -> None:
    """Reset module sync state for deterministic tests."""
    global _last_query_sync_monotonic
    global _last_query_sync_result
    _last_query_sync_monotonic = 0.0
    _last_query_sync_result = None
