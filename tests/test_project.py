"""Tests for project ID derivation and runtime resolution."""

from cb_memory.project import (
    derive_project_id,
    normalize_project_path,
    resolve_project_scope,
    resolve_scope_overrides,
)
from cb_memory.tools.context import _effective_project_id


class _Settings:
    def __init__(self, current_project_id=None):
        self.current_project_id = current_project_id


class _Db:
    def __init__(self, current_project_id=None):
        self._settings = _Settings(current_project_id=current_project_id)


def test_derive_project_id_prefers_explicit_override():
    out = derive_project_id("my-project", "/tmp/x")
    assert out == "my-project"


def test_derive_project_id_uses_directory_when_default():
    out = derive_project_id("default", "/tmp/x")
    assert out.endswith("/tmp/x")


def test_normalize_project_path_empty():
    assert normalize_project_path("") == ""


def test_effective_project_id_uses_current_project_for_default():
    db = _Db(current_project_id="/Users/ruchit/Downloads/cb-retrival")
    out = _effective_project_id(db, "default")
    assert out.endswith("/Users/ruchit/Downloads/cb-retrival")


def test_effective_project_id_keeps_requested_specific():
    db = _Db(current_project_id="/Users/ruchit/Downloads/cb-retrival")
    out = _effective_project_id(db, "another-project")
    assert out == "another-project"


def test_resolve_project_scope_defaults_to_single_project():
    effective, scope = resolve_project_scope(
        requested_project_id="default",
        current_project_id="/Users/ruchit/Downloads/cb-retrival",
    )
    assert effective == "/Users/ruchit/Downloads/cb-retrival"
    assert scope == ["/Users/ruchit/Downloads/cb-retrival"]


def test_resolve_project_scope_supports_cross_project():
    effective, scope = resolve_project_scope(
        requested_project_id="default",
        current_project_id="/Users/ruchit/Downloads/cb-retrival",
        related_project_ids=["/Users/ruchit/Downloads/local_agent"],
    )
    assert effective == "/Users/ruchit/Downloads/cb-retrival"
    assert scope == [
        "/Users/ruchit/Downloads/cb-retrival",
        "/Users/ruchit/Downloads/local_agent",
    ]


def test_resolve_project_scope_supports_global():
    effective, scope = resolve_project_scope(
        requested_project_id="default",
        current_project_id="/Users/ruchit/Downloads/cb-retrival",
        include_all_projects=True,
    )
    assert effective == "/Users/ruchit/Downloads/cb-retrival"
    assert scope is None


def test_resolve_scope_overrides_uses_defaults_when_unset():
    related, include_all = resolve_scope_overrides(
        requested_related_project_ids=None,
        requested_include_all_projects=None,
        default_related_project_ids=[
            "/Users/ruchit/Downloads/cb-retrival",
            "/Users/ruchit/Downloads/local_agent",
        ],
        include_all_projects_by_default=True,
    )
    assert related == [
        "/Users/ruchit/Downloads/cb-retrival",
        "/Users/ruchit/Downloads/local_agent",
    ]
    assert include_all is True


def test_resolve_scope_overrides_prefers_explicit_request():
    related, include_all = resolve_scope_overrides(
        requested_related_project_ids=["/tmp/one", "/tmp/two"],
        requested_include_all_projects=False,
        default_related_project_ids=["/tmp/default"],
        include_all_projects_by_default=True,
    )
    assert related == ["/private/tmp/one", "/private/tmp/two"]
    assert include_all is False
