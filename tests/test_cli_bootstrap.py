"""Tests for Docker-free bootstrap CLI behavior."""

from click.testing import CliRunner

from cb_memory.cli.main import cli


class _FakeDb:
    def __init__(self, *_args, **_kwargs):
        self.connected = False

    def connect(self):
        self.connected = True

    def close(self):
        self.connected = False


def test_init_bootstrap_runs_without_docker(monkeypatch):
    monkeypatch.setattr("cb_memory.cli.main.CouchbaseClient", _FakeDb)
    monkeypatch.setattr("cb_memory.cli.main._wait_for_couchbase_rest", lambda **_kwargs: None)
    monkeypatch.setattr("cb_memory.cli.main._provision_schema", lambda *_args, **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "init",
            "--skip-claude",
            "--skip-codex",
            "--skip-opencode",
        ],
    )

    assert result.exit_code == 0
    assert "Checking Couchbase REST API" in result.output
    assert "Complete" in result.output
    assert '"cb_connection_string"' in result.output


def test_replicate_prints_deprecation_and_forwards(monkeypatch):
    monkeypatch.setattr("cb_memory.cli.main.CouchbaseClient", _FakeDb)
    monkeypatch.setattr("cb_memory.cli.main._wait_for_couchbase_rest", lambda **_kwargs: None)
    monkeypatch.setattr("cb_memory.cli.main._provision_schema", lambda *_args, **_kwargs: None)

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "replicate",
            "--skip-claude",
            "--skip-codex",
            "--skip-opencode",
        ],
    )

    assert result.exit_code == 0
    assert "deprecated" in result.output.lower()
    assert "Ignoring deprecated options" in result.output
    assert '"cb_connection_string"' in result.output
