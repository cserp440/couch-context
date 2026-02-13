"""Tests for context reasoning helpers and token budgeting."""

from cb_memory.tools.context import (
    _build_context_reasoning,
    _build_reasoning_text,
    _extract_skill_and_subagent_signals,
    _llm_context_summary,
    _trim_to_token_budget,
)


def test_context_reasoning_includes_source_breakdown():
    grouped = {
        "sessions": [{"id": "session::1", "source": "codex", "title": "session"}],
        "messages": [{"id": "msg::1", "session_source": "claude-code", "text_excerpt": "hello"}],
        "decisions": [],
        "bugs": [],
        "patterns": [],
        "thoughts": [],
    }
    reasoning = _build_context_reasoning(
        query="test query",
        requested_project_id="default",
        effective_project_id="/Users/ruchit/Downloads/cb-retrival",
        project_scope="project",
        scope_project_ids=["/Users/ruchit/Downloads/cb-retrival"],
        primary_hits=2,
        kv_semantic_hits=1,
        raw_fallback_hits=0,
        grouped=grouped,
    )
    assert reasoning["source_breakdown"] == {"claude-code": 1, "codex": 1}
    assert "sessions" in reasoning["selected_counts"]
    rendered = _build_reasoning_text(reasoning)
    assert "Effective project" in rendered
    assert "Sources:" in rendered


def test_trim_to_token_budget_shrinks_text():
    long_text = "x" * 12000
    trimmed = _trim_to_token_budget(long_text, max_tokens=2000)
    assert len(trimmed) < len(long_text)
    assert trimmed.endswith("…")


def test_llm_context_summary_fallback_is_focused_and_bounded():
    grouped = {
        "sessions": [{"id": "session::1", "source": "codex", "title": "wire retrieval", "summary": "added fallback"}],
        "messages": [{"id": "msg::1", "session_source": "claude-code", "role": "assistant", "text_excerpt": "use memory_kv_semantic_search"}],
        "decisions": [{"id": "decision::1", "type": "decision", "title": "Use fallback", "description": "When sparse use KV"}],
        "bugs": [],
        "patterns": [],
        "thoughts": [],
    }
    out = _llm_context_summary(
        query="add context fallback in middle of chat",
        grouped=grouped,
        context_reasoning_text="- Effective project: /tmp/project",
        max_context_tokens=80,
        openai_api_key=None,
    )
    assert "Most relevant retrieved context" in out
    assert "fallback" in out.lower()
    assert len(out) <= (80 * 4)


def test_extract_skill_and_subagent_signals_from_tool_calls():
    tool_names, skills, subagents = _extract_skill_and_subagent_signals(
        [
            {
                "tool_calls": [
                    {"name": "Task", "input": {"subagent_type": "Plan"}},
                    {"name": "skill", "input": {"skill_name": "checks"}},
                ]
            }
        ]
    )
    assert tool_names == {"Task", "skill"}
    assert skills == {"checks"}
    assert subagents == {"Plan"}
