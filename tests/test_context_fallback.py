"""Tests for request-context fallback behavior."""

import pytest

from cb_memory.tools.context import _extract_query_terms, _keyword_score, _raw_chat_fallback


class _Cluster:
    def query(self, q, **kwargs):
        if "conversations.messages" in q:
            return [
                {
                    "id": "msg::1",
                    "type": "message",
                    "text_content": "connect codex with couchbase memory",
                    "session_title": "connect this with codex",
                    "session_summary": "",
                }
            ]
        if "conversations.sessions" in q:
            return [
                {
                    "id": "session::1",
                    "type": "session",
                    "title": "connect this with codex and claude code",
                    "summary": "",
                }
            ]
        return []


class _Settings:
    cb_bucket = "coding-memory"


class _Db:
    _settings = _Settings()
    cluster = _Cluster()


def test_extract_query_terms_filters_noise():
    terms = _extract_query_terms("tell me context of this project connect codex with couchbase")
    assert "connect" in terms
    assert "codex" in terms
    assert "project" not in terms


def test_extract_query_terms_can_be_empty_for_generic_query():
    terms = _extract_query_terms("tell me context of this project")
    assert terms == []


def test_raw_chat_fallback_returns_ranked_results_with_terms():
    db = _Db()
    out = _raw_chat_fallback(db, "connect codex memory", ["/Users/ruchit/Downloads/cb-retrival"], 8)
    assert len(out) == 2
    assert any(r.get("retrieval_source") == "raw-chat-fallback" for r in out)
    assert all(r.get("score", 0) > 0 for r in out)


def test_raw_chat_fallback_returns_recent_for_generic_query():
    db = _Db()
    out = _raw_chat_fallback(db, "tell me context of this project", ["/Users/ruchit/Downloads/cb-retrival"], 8)
    assert len(out) == 2
    assert all(r.get("score") == pytest.approx(0.05) for r in out)


def test_raw_chat_fallback_matches_tool_call_signals():
    class _ToolCluster:
        def query(self, q, **kwargs):
            if "conversations.messages" in q:
                return [
                    {
                        "id": "msg::tool",
                        "type": "message",
                        "text_content": "",
                        "tool_calls": [
                            {"name": "Task", "input": {"subagent_type": "Plan"}},
                            {"name": "skill", "input": {"skill_name": "checks"}},
                        ],
                        "tool_results": [],
                        "session_title": "",
                        "session_summary": "",
                    }
                ]
            if "conversations.sessions" in q:
                return []
            return []

    class _ToolDb:
        _settings = _Settings()
        cluster = _ToolCluster()

    out = _raw_chat_fallback(_ToolDb(), "plan checks", ["/Users/ruchit/Downloads/cb-retrival"], 8)
    assert len(out) == 1
    assert out[0]["score"] > 0.25


def test_keyword_score_increases_with_matches():
    terms = ["codex", "memory", "couchbase"]
    low = _keyword_score("codex", terms)
    high = _keyword_score("codex memory couchbase", terms)
    assert high > low
