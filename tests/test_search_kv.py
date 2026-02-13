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


def test_kv_grep_uses_non_conflicting_any_variable_for_thoughts():
    db = _Db()
    _kv_grep(db, terms=["context", "codex"], project_ids=["/tmp/project"], per_collection_limit=2)

    thoughts_query = next(q for q in db.cluster.queries if ".knowledge.thoughts" in q)
    assert "ANY term IN $terms" in thoughts_query
    assert "ANY t IN $terms" not in thoughts_query

    messages_query = next(q for q in db.cluster.queries if ".conversations.messages" in q)
    assert "TOSTRING(m.tool_calls)" in messages_query
    assert "TOSTRING(m.tool_results)" in messages_query
