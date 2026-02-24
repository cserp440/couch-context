"""Tests for installer wizard helpers."""

from pathlib import Path

from cb_memory.cli.installer import (
    build_server_env,
    install_ide_configs,
    parse_ide_selection,
    write_env_file,
)


def test_parse_ide_selection_accepts_indexes_and_ids():
    parsed = parse_ide_selection("1,copilot-vscode,3")
    assert parsed == ["factory", "copilot-vscode", "copilot-jetbrains"]


def test_build_server_env_uses_openai_when_provided():
    env = build_server_env(
        cb_connection_string="couchbase://localhost",
        cb_username="Administrator",
        cb_password="secret",
        cb_bucket="coding-memory",
        project_id="/tmp/project",
        openai_api_key="sk-test",
        ollama_host="http://localhost:11434",
        ollama_embedding_model="nomic-embed-text",
    )
    assert env["OPENAI_API_KEY"] == "sk-test"
    assert env["CURRENT_PROJECT_ID"] == "/tmp/project"
    assert env["DEFAULT_PROJECT_ID"] == "default"
    assert env["INCLUDE_ALL_PROJECTS_BY_DEFAULT"] == "true"
    assert env["AUTO_IMPORT_CLAUDE_ON_START"] == "true"
    assert env["AUTO_IMPORT_CODEX_ON_START"] == "true"


def test_write_env_file_upserts_without_removing_existing(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING_KEY=present\n", encoding="utf-8")

    changed = write_env_file(
        env_path=env_file,
        values={"CB_USERNAME": "Administrator", "CB_PASSWORD": "password"},
    )

    assert changed is True
    content = env_file.read_text(encoding="utf-8")
    assert "EXISTING_KEY=present" in content
    assert "CB_USERNAME=Administrator" in content


def test_install_ide_configs_writes_project_files(tmp_path: Path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir(parents=True)
    monkeypatch.setattr("cb_memory.cli.installer.Path.home", lambda: fake_home)

    env = {"CB_CONNECTION_STRING": "couchbase://localhost", "CB_USERNAME": "Administrator"}
    results = install_ide_configs(
        ide_ids=["factory", "copilot-vscode", "claude-code", "codex"],
        project_root=tmp_path,
        env=env,
    )

    assert len(results) == 4
    factory_file = fake_home / ".factory" / "mcp.json"
    vscode_file = tmp_path / ".vscode" / "mcp.json"
    claude_file = fake_home / ".claude" / "settings.json"
    codex_file = fake_home / ".codex" / "config.toml"
    assert factory_file.exists()
    assert vscode_file.exists()
    assert claude_file.exists()
    assert codex_file.exists()

    factory_content = factory_file.read_text(encoding="utf-8")
    assert '"type": "stdio"' in factory_content
    assert '"disabled": false' in factory_content

    codex_content = codex_file.read_text(encoding="utf-8")
    assert "[mcp_servers.coding-memory]" in codex_content
    assert 'command = "python"' in codex_content
    assert 'args = ["-m", "cb_memory.server"]' in codex_content
