"""Tests for startup and query-time auto-sync helpers."""

from __future__ import annotations

from cb_memory.sync import (
    _reset_query_sync_state_for_tests,
    auto_sync_claude,
    auto_sync_codex,
    maybe_auto_sync_recent,
)


class _Settings:
    auto_import_claude_on_start = True
    auto_import_claude_path = "/tmp/claude-projects"
    auto_import_codex_on_start = True
    auto_import_codex_path = "/tmp/codex-sessions"
    auto_import_on_query = True
    auto_import_min_interval_seconds = 60
    default_project_id = "default"


class _DisabledSettings:
    auto_import_claude_on_start = False
    auto_import_claude_path = "/tmp/claude-projects"
    auto_import_codex_on_start = False
    auto_import_codex_path = "/tmp/codex-sessions"
    auto_import_on_query = False
    auto_import_min_interval_seconds = 60
    default_project_id = "default"


class _Importer:
    def __init__(self, db, settings, project_id):
        self.project_id = project_id

    def run(self, path):
        return {"sessions_imported": 2, "messages_imported": 4, "path_used": path}


class _FailingImporter:
    def __init__(self, db, settings, project_id):
        pass

    def run(self, path):
        raise RuntimeError("boom")


def test_auto_sync_claude_disabled():
    out = auto_sync_claude(db=object(), settings=_DisabledSettings(), importer_cls=_Importer)
    assert out["status"] == "disabled"
    assert out["source"] == "claude-code"


def test_auto_sync_claude_runs_importer():
    out = auto_sync_claude(db=object(), settings=_Settings(), importer_cls=_Importer)
    assert out["status"] == "ok"
    assert out["path"] == "/tmp/claude-projects"
    assert out["project_id"] == "default"
    assert out["stats"]["sessions_imported"] == 2


def test_auto_sync_claude_handles_errors():
    out = auto_sync_claude(db=object(), settings=_Settings(), importer_cls=_FailingImporter)
    assert out["status"] == "error"
    assert out["source"] == "claude-code"
    assert "boom" in out["error"]


def test_auto_sync_codex_disabled():
    out = auto_sync_codex(db=object(), settings=_DisabledSettings(), importer_cls=_Importer)
    assert out["status"] == "disabled"
    assert out["source"] == "codex"


def test_auto_sync_codex_runs_importer():
    out = auto_sync_codex(db=object(), settings=_Settings(), importer_cls=_Importer)
    assert out["status"] == "ok"
    assert out["path"] == "/tmp/codex-sessions"
    assert out["project_id"] == "default"
    assert out["stats"]["sessions_imported"] == 2


def test_maybe_auto_sync_recent_disabled():
    _reset_query_sync_state_for_tests()
    out = maybe_auto_sync_recent(db=object(), settings=_DisabledSettings())
    assert out["status"] == "disabled"


def test_maybe_auto_sync_recent_obeys_cooldown():
    _reset_query_sync_state_for_tests()
    settings = _Settings()
    first = maybe_auto_sync_recent(
        db=object(),
        settings=settings,
        now_monotonic=100.0,
        claude_importer_cls=_Importer,
        codex_importer_cls=_Importer,
    )
    assert first["status"] == "ok"
    second = maybe_auto_sync_recent(
        db=object(),
        settings=settings,
        now_monotonic=130.0,
        claude_importer_cls=_Importer,
        codex_importer_cls=_Importer,
    )
    assert second["status"] == "skipped"
    assert second["reason"] == "cooldown"


def test_maybe_auto_sync_recent_force_ignores_cooldown():
    _reset_query_sync_state_for_tests()
    settings = _Settings()
    maybe_auto_sync_recent(
        db=object(),
        settings=settings,
        now_monotonic=100.0,
        claude_importer_cls=_Importer,
        codex_importer_cls=_Importer,
    )
    forced = maybe_auto_sync_recent(
        db=object(),
        settings=settings,
        force=True,
        now_monotonic=120.0,
        claude_importer_cls=_Importer,
        codex_importer_cls=_Importer,
    )
    assert forced["status"] == "ok"
