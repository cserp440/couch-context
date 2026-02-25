"""Unit tests for KV+semantic search query construction."""

from cb_memory.tools.search import _kv_grep


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
                    "tool_calls": [],
                    "tool_results": [],
                }
            ]
        return []


class _DbWithRows:
    def __init__(self):
        self._settings = _Settings()
        self.cluster = _ClusterWithRows()


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
