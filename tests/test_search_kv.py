"""Unit tests for KV+semantic search query construction."""

import pytest

from cb_memory.tools.search import _kv_grep, memory_kv_text_search


class _Cluster:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, q, **kwargs):
        self.queries.append(q)
        return []


class _Settings:
    cb_bucket = "coding-memory"


class _Db:
    def __init__(self):
        self._settings = _Settings()
        self.cluster = _Cluster()


class _ClusterWithRows:
    def __init__(self):
        self.queries: list[str] = []

    def query(self, q, **kwargs):
        self.queries.append(q)
        if ".conversations.messages" in q:
            return [
                {
                    "id": "msg::1",
                    "text_content": "matrix_lr_update_mode=legacy was used in run_oldctrl_hyper_tune_vs_baseline.py",
                    "tool_calls": [{"name": "Execute", "input": {"command": "echo hello"}}],
                    "tool_results": [],
                    "raw_content": {"verbose": True},
                }
            ]
        return []


class _DbWithRows:
    def __init__(self):
        self._settings = _Settings()
        self.cluster = _ClusterWithRows()


class _Provider:
    def embed_one(self, query: str):
        return [0.0]


def test_kv_grep_uses_non_conflicting_any_variable_for_thoughts():
    db = _Db()
    _kv_grep(db, terms=["context", "codex"], project_ids=["/tmp/project"], per_collection_limit=2)

    thoughts_query = next(q for q in db.cluster.queries if ".knowledge.thoughts" in q)
    assert "ANY term IN $terms" in thoughts_query
    assert "ANY t IN $terms" not in thoughts_query

    messages_query = next(q for q in db.cluster.queries if ".conversations.messages" in q)
    assert "m.text_content" in messages_query
    assert "m.*" not in messages_query
    assert "TOSTRING(m.tool_calls)" not in messages_query
    assert "TOSTRING(m.tool_results)" not in messages_query


def test_kv_grep_assigns_high_score_to_exact_keyword_hits():
    db = _DbWithRows()
    out = _kv_grep(
        db,
        terms=["matrix_lr_update_mode=legacy", "run_oldctrl_hyper_tune_vs_baseline.py"],
        project_ids=["/tmp/project"],
        per_collection_limit=5,
    )

    assert len(out) == 1
    row = out[0]
    assert row["source"] == "kv"
    assert row["score"] >= 11.0
    assert "matrix_lr_update_mode=legacy" in row["_matched_terms"]
    assert "tool_results" not in row
    assert row["text"].startswith("matrix_lr_update_mode=legacy")


def test_kv_grep_text_only_mode_keeps_tool_calls_and_excludes_non_text_fields():
    db = _DbWithRows()
    out = _kv_grep(
        db,
        terms=["matrix_lr_update_mode=legacy"],
        project_ids=["/tmp/project"],
        per_collection_limit=5,
        text_only=True,
    )

    assert len(out) == 1
    row = out[0]
    assert "tool_calls" in row
    assert row["tool_calls"][0]["name"] == "Execute"
    assert "tool_results" not in row
    assert "raw_content" not in row
    assert "text" not in row


@pytest.mark.asyncio
async def test_memory_kv_text_search_returns_only_text_content_and_command_tool_calls():
    db = _DbWithRows()
    provider = _Provider()

    out = await memory_kv_text_search(
        db=db,
        provider=provider,
        terms=["matrix_lr_update_mode=legacy"],
        include_all_projects=True,
        limit=5,
        per_collection_limit=5,
    )

    assert len(out["results"]) == 1
    assert "scope_project_ids" not in out
    assert "include_all_projects" not in out
    assert "result_count" not in out
    row = out["results"][0]
    assert set(row.keys()) == {"text_content", "tool_calls"}
    assert row["text_content"].startswith("matrix_lr_update_mode=legacy")
    assert row["tool_calls"] == [{"command": "echo hello"}]


@pytest.mark.asyncio
async def test_memory_kv_text_search_with_metadata_keeps_id_and_type_for_internal_flows():
    db = _DbWithRows()
    provider = _Provider()

    out = await memory_kv_text_search(
        db=db,
        provider=provider,
        terms=["matrix_lr_update_mode=legacy"],
        include_all_projects=True,
        limit=5,
        per_collection_limit=5,
        include_metadata=True,
    )

    assert len(out["results"]) == 1
    row = out["results"][0]
    assert row["id"] == "msg::1"
    assert row["type"] == "message"
    assert row["text_content"].startswith("matrix_lr_update_mode=legacy")
    assert row["tool_calls"] == [{"command": "echo hello"}]
