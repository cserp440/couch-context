"""Tests for startup auto-sync helpers."""

from __future__ import annotations

from cb_memory.sync import auto_sync_claude, auto_sync_codex


class _Settings:
    auto_import_claude_on_start = True
    auto_import_claude_path = "/tmp/claude-projects"
    auto_import_codex_on_start = True
    auto_import_codex_path = "/tmp/codex-sessions"
    default_project_id = "default"


class _DisabledSettings:
    auto_import_claude_on_start = False
    auto_import_claude_path = "/tmp/claude-projects"
    auto_import_codex_on_start = False
    auto_import_codex_path = "/tmp/codex-sessions"
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
