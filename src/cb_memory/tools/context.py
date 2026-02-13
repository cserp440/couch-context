"""Project context tool — aggregate recent memory for a project."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import EmbeddingProvider
from cb_memory.project import (
    resolve_project_scope,
    resolve_runtime_project_id,
    resolve_scope_overrides,
)
from cb_memory.tools import search

logger = logging.getLogger(__name__)


def _effective_project_id(db: CouchbaseClient, requested_project_id: str) -> str:
    """Resolve default project id to current workspace project when available."""
    return resolve_runtime_project_id(
        requested_project_id=requested_project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    ) or "default"


def _session_project_filter(alias: str = "s") -> str:
    """Filter sessions by project and include legacy default+directory docs."""
    return (
        f"({alias}.project_id = $project_id "
        f"OR ({alias}.project_id = 'default' AND {alias}.directory = $project_id))"
    )


def _session_project_filter_many(alias: str = "s") -> str:
    """Filter sessions by project set and include legacy default+directory docs."""
    return (
        f"({alias}.project_id IN $project_ids "
        f"OR ({alias}.project_id = 'default' AND {alias}.directory IN $project_ids))"
    )


async def memory_project_context(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    project_id: str = "default",
    max_sessions: int = 5,
    max_decisions: int = 10,
    max_bugs: int = 5,
    max_patterns: int = 5,
) -> dict:
    """Get aggregated project context — recent sessions, decisions, patterns.

    This is useful at the start of a new coding session to understand
    the project's history and existing decisions.

    Args:
        project_id: Project to get context for.
        max_sessions: Max recent sessions to include.
        max_decisions: Max decisions to include.
        max_bugs: Max recent bugs to include.
        max_patterns: Max patterns to include.
    """
    project_id = _effective_project_id(db, project_id)
    bucket = db._settings.cb_bucket
    context: dict = {"project_id": project_id}

    # Recent sessions
    try:
        q = (
            f"SELECT s.id, s.title, s.summary, s.tags, s.started_at, s.message_count "
            f"FROM `{bucket}`.conversations.sessions s "
            f"WHERE {_session_project_filter('s')} "
            f"ORDER BY s.created_at DESC "
            f"LIMIT {int(max_sessions)}"
        )
        rows = list(db.cluster.query(q, project_id=project_id))
        context["recent_sessions"] = rows
    except Exception as e:
        logger.warning(f"Failed to fetch sessions: {e}")
        context["recent_sessions"] = []

    # Key decisions
    try:
        q = (
            f"SELECT d.id, d.title, d.description, d.category, d.tags, d.created_at "
            f"FROM `{bucket}`.knowledge.decisions d "
            f"WHERE d.project_id = $project_id "
            f"ORDER BY d.created_at DESC "
            f"LIMIT {int(max_decisions)}"
        )
        rows = list(db.cluster.query(q, project_id=project_id))
        context["decisions"] = rows
    except Exception as e:
        logger.warning(f"Failed to fetch decisions: {e}")
        context["decisions"] = []

    # Recent bugs
    try:
        q = (
            f"SELECT b.id, b.title, b.root_cause, b.fix_description, b.severity, b.created_at "
            f"FROM `{bucket}`.knowledge.bugs b "
            f"WHERE b.project_id = $project_id "
            f"ORDER BY b.created_at DESC "
            f"LIMIT {int(max_bugs)}"
        )
        rows = list(db.cluster.query(q, project_id=project_id))
        context["recent_bugs"] = rows
    except Exception as e:
        logger.warning(f"Failed to fetch bugs: {e}")
        context["recent_bugs"] = []

    # Patterns
    try:
        q = (
            f"SELECT p.id, p.title, p.description, p.`language` AS `language`, p.tags, p.created_at "
            f"FROM `{bucket}`.knowledge.patterns p "
            f"WHERE p.project_id = $project_id "
            f"ORDER BY p.created_at DESC "
            f"LIMIT {int(max_patterns)}"
        )
        rows = list(db.cluster.query(q, project_id=project_id))
        context["patterns"] = rows
    except Exception as e:
        logger.warning(f"Failed to fetch patterns: {e}")
        context["patterns"] = []

    # Recent thoughts
    try:
        q = (
            f"SELECT t.id, t.content, t.category, t.tags, t.created_at "
            f"FROM `{bucket}`.knowledge.thoughts t "
            f"WHERE t.project_id = $project_id "
            f"ORDER BY t.created_at DESC "
            f"LIMIT 5"
        )
        rows = list(db.cluster.query(q, project_id=project_id))
        context["recent_thoughts"] = rows
    except Exception as e:
        logger.warning(f"Failed to fetch thoughts: {e}")
        context["recent_thoughts"] = []

    # Summary stats
    context["stats"] = {}
    for scope_name, coll_name, label in [
        ("conversations", "sessions", "total_sessions"),
        ("knowledge", "decisions", "total_decisions"),
        ("knowledge", "bugs", "total_bugs"),
        ("knowledge", "patterns", "total_patterns"),
        ("knowledge", "thoughts", "total_thoughts"),
    ]:
        try:
            if scope_name == "conversations" and coll_name == "sessions":
                q = (
                    f"SELECT COUNT(*) as cnt "
                    f"FROM `{bucket}`.`{scope_name}`.`{coll_name}` s "
                    f"WHERE {_session_project_filter('s')}"
                )
            else:
                q = (
                    f"SELECT COUNT(*) as cnt "
                    f"FROM `{bucket}`.`{scope_name}`.`{coll_name}` "
                    f"WHERE project_id = $project_id"
                )
            rows = list(db.cluster.query(q, project_id=project_id))
            context["stats"][label] = rows[0]["cnt"] if rows else 0
        except Exception:
            context["stats"][label] = 0

    return context


def _truncate(text: str, max_len: int = 240) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def _looks_like_path(token: str) -> bool:
    return "/" in token or token.endswith((".py", ".js", ".ts", ".tsx", ".go", ".rs", ".java", ".rb", ".md"))


def _extract_paths_from_query(query: str) -> list[str]:
    tokens = [t.strip(" ,:;()[]{}<>\"'") for t in query.split()]
    paths = [t for t in tokens if t and _looks_like_path(t)]
    # Deduplicate while preserving order
    seen = set()
    unique = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    return unique


def _extract_query_terms(query: str) -> list[str]:
    tokens = re.findall(r"[A-Za-z0-9_./:-]+", query.lower())
    stop = {
        "the", "and", "for", "with", "from", "this", "that", "what", "where",
        "when", "how", "why", "tell", "show", "give", "about", "into", "does",
        "did", "are", "was", "were", "has", "have", "had", "project", "context",
        "please", "can", "you",
    }
    terms: list[str] = []
    for t in tokens:
        if len(t) < 3:
            continue
        if t in stop:
            continue
        terms.append(t)
    # Deduplicate while preserving order
    seen = set()
    unique: list[str] = []
    for t in terms:
        if t in seen:
            continue
        seen.add(t)
        unique.append(t)
    return unique[:12]


def _keyword_score(text: str, terms: list[str]) -> float:
    blob = (text or "").lower()
    if not blob or not terms:
        return 0.0
    hits = 0
    for t in terms:
        if t in blob:
            hits += 1
    # small normalization so longer queries don't dominate
    return hits / max(1, len(terms))


def _raw_chat_fallback(
    db: CouchbaseClient,
    query: str,
    project_ids: list[str] | None,
    limit: int,
) -> list[dict]:
    """Fallback retrieval directly from raw chats when FTS/vector recall is sparse."""
    bucket = db._settings.cb_bucket
    terms = _extract_query_terms(query)

    results: list[dict] = []

    if terms:
        like_clause_msg = (
            "ANY t IN $terms SATISFIES "
            "LOWER(m.text_content) LIKE '%' || t || '%' "
            "OR LOWER(TOSTRING(IFMISSINGORNULL(m.tool_calls, []))) LIKE '%' || t || '%' "
            "OR LOWER(TOSTRING(IFMISSINGORNULL(m.tool_results, []))) LIKE '%' || t || '%' "
            "OR LOWER(IFMISSINGORNULL(s.title, '')) LIKE '%' || t || '%' "
            "OR LOWER(IFMISSINGORNULL(s.summary, '')) LIKE '%' || t || '%' "
            "END"
        )
        q_messages = (
            f"SELECT META(m).id AS id, m.*, s.title AS session_title, s.summary AS session_summary, "
            f"s.source AS session_source, s.project_id AS session_project_id, s.directory AS session_directory "
            f"FROM `{bucket}`.conversations.messages m "
            f"JOIN `{bucket}`.conversations.sessions s ON KEYS m.session_id "
            f"WHERE ({like_clause_msg}) "
            f"ORDER BY m.created_at DESC "
            f"LIMIT {int(max(limit * 2, 10))}"
        )
    else:
        q_messages = (
            f"SELECT META(m).id AS id, m.*, s.title AS session_title, s.summary AS session_summary, "
            f"s.source AS session_source, s.project_id AS session_project_id, s.directory AS session_directory "
            f"FROM `{bucket}`.conversations.messages m "
            f"JOIN `{bucket}`.conversations.sessions s ON KEYS m.session_id "
            f"WHERE TRUE "
            f"ORDER BY m.created_at DESC "
            f"LIMIT {int(max(limit * 2, 10))}"
        )
    if project_ids is not None:
        q_messages = q_messages.replace("WHERE ", f"WHERE {_session_project_filter_many('s')} AND ", 1)
    try:
        for row in db.cluster.query(q_messages, terms=terms, project_ids=project_ids):
            row.pop("embedding", None)
            row["_scope"] = "conversations"
            row["_collection"] = "messages"
            row["retrieval_source"] = "raw-chat-fallback"
            score_text = "\n".join(
                [
                    str(row.get("text_content", "")),
                    _tool_signal_text(row.get("tool_calls", []), row.get("tool_results", [])),
                    str(row.get("session_title", "")),
                    str(row.get("session_summary", "")),
                ]
            )
            # Keep fallback below primary semantic scores.
            row["score"] = (0.25 + _keyword_score(score_text, terms)) if terms else 0.05
            results.append(row)
    except Exception as e:
        logger.warning(f"Raw chat message fallback failed: {e}")

    if terms:
        like_clause_sess = (
            "ANY t IN $terms SATISFIES "
            "LOWER(IFMISSINGORNULL(s.title, '')) LIKE '%' || t || '%' "
            "OR LOWER(IFMISSINGORNULL(s.summary, '')) LIKE '%' || t || '%' "
            "END"
        )
        q_sessions = (
            f"SELECT META(s).id AS id, s.* "
            f"FROM `{bucket}`.conversations.sessions s "
            f"WHERE ({like_clause_sess}) "
            f"ORDER BY s.created_at DESC "
            f"LIMIT {int(max(limit, 6))}"
        )
    else:
        q_sessions = (
            f"SELECT META(s).id AS id, s.* "
            f"FROM `{bucket}`.conversations.sessions s "
            f"WHERE TRUE "
            f"ORDER BY s.created_at DESC "
            f"LIMIT {int(max(limit, 6))}"
        )
    if project_ids is not None:
        q_sessions = q_sessions.replace("WHERE ", f"WHERE {_session_project_filter_many('s')} AND ", 1)
    try:
        for row in db.cluster.query(q_sessions, terms=terms, project_ids=project_ids):
            row.pop("embedding", None)
            row["_scope"] = "conversations"
            row["_collection"] = "sessions"
            row["retrieval_source"] = "raw-chat-fallback"
            score_text = "\n".join([str(row.get("title", "")), str(row.get("summary", ""))])
            row["score"] = (0.2 + _keyword_score(score_text, terms)) if terms else 0.05
            results.append(row)
    except Exception as e:
        logger.warning(f"Raw chat session fallback failed: {e}")

    return results


def _dedupe_results(results: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        deduped.append(r)
    return deduped


def _tool_signal_text(tool_calls: list, tool_results: list | None = None) -> str:
    parts: list[str] = []
    for tc in tool_calls or []:
        if not isinstance(tc, dict):
            continue
        name = str(tc.get("name") or "").strip()
        if not name:
            continue
        label = name
        input_data = tc.get("input")
        if isinstance(input_data, dict):
            subagent_type = input_data.get("subagent_type")
            if isinstance(subagent_type, str) and subagent_type.strip():
                label = f"{label}({subagent_type.strip()})"
            if name == "skill":
                skill_name = (
                    input_data.get("name")
                    or input_data.get("skill")
                    or input_data.get("skill_name")
                    or input_data.get("path")
                )
                if isinstance(skill_name, str) and skill_name.strip():
                    label = f"{label}({skill_name.strip()})"
        parts.append(label)

    for tr in tool_results or []:
        if not isinstance(tr, dict):
            continue
        content = tr.get("content")
        if isinstance(content, str) and content.strip():
            parts.append(content.strip()[:120])

    return " | ".join(parts)


def _message_excerpt(message: dict) -> str:
    text = str(message.get("text_content", "") or "").strip()
    if text:
        return _truncate(text)
    tool_text = _tool_signal_text(message.get("tool_calls", []), message.get("tool_results", []))
    if tool_text:
        return _truncate(f"[tool] {tool_text}")
    return ""


def _extract_skill_and_subagent_signals(messages: list[dict]) -> tuple[set[str], set[str], set[str]]:
    tool_names: set[str] = set()
    skills: set[str] = set()
    subagents: set[str] = set()

    for message in messages:
        for tc in message.get("tool_calls", []):
            if not isinstance(tc, dict):
                continue
            name = tc.get("name")
            if isinstance(name, str) and name:
                tool_names.add(name)
            input_data = tc.get("input")
            if not isinstance(input_data, dict):
                continue

            subagent_type = input_data.get("subagent_type")
            if isinstance(subagent_type, str) and subagent_type.strip():
                subagents.add(subagent_type.strip())

            if name == "skill":
                skill_name = (
                    input_data.get("name")
                    or input_data.get("skill")
                    or input_data.get("skill_name")
                    or input_data.get("path")
                )
                if isinstance(skill_name, str) and skill_name.strip():
                    skills.add(skill_name.strip())

    return tool_names, skills, subagents


def _group_results(results: list[dict], per_type_limit: int) -> dict:
    grouped: dict = {
        "sessions": [],
        "messages": [],
        "summaries": [],
        "decisions": [],
        "bugs": [],
        "patterns": [],
        "thoughts": [],
        "other": [],
    }

    for r in results:
        rtype = r.get("type", "")
        target = None
        if rtype == "session":
            target = "sessions"
        elif rtype == "message":
            target = "messages"
        elif rtype == "summary":
            target = "summaries"
        elif rtype == "decision":
            target = "decisions"
        elif rtype == "bug":
            target = "bugs"
        elif rtype == "pattern":
            target = "patterns"
        elif rtype == "thought":
            target = "thoughts"
        else:
            target = "other"

        if len(grouped[target]) < per_type_limit:
            grouped[target].append(r)

    return grouped


def _compact_message(msg: dict) -> dict:
    return {
        "id": msg.get("id"),
        "session_id": msg.get("session_id"),
        "project_id": msg.get("project_id"),
        "session_project_id": msg.get("session_project_id"),
        "session_directory": msg.get("session_directory"),
        "role": msg.get("role"),
        "session_source": msg.get("session_source"),
        "sequence_number": msg.get("sequence_number"),
        "timestamp": msg.get("timestamp"),
        "text_excerpt": _message_excerpt(msg),
        "retrieval_source": msg.get("retrieval_source") or msg.get("source"),
        "tool_calls": msg.get("tool_calls", []),
        "tool_results": msg.get("tool_results", []),
    }


def _compact_session(sess: dict) -> dict:
    return {
        "id": sess.get("id"),
        "title": sess.get("title"),
        "summary": _truncate(sess.get("summary", "")),
        "tags": sess.get("tags", []),
        "project_id": sess.get("project_id"),
        "directory": sess.get("directory"),
        "source": sess.get("source"),
        "retrieval_source": sess.get("retrieval_source") or sess.get("source"),
        "message_count": sess.get("message_count"),
        "started_at": sess.get("started_at"),
        "created_at": sess.get("created_at"),
        "tools_used": sess.get("tools_used", []),
        "files_modified": sess.get("files_modified", []),
    }


def _compact_summary(summary: dict) -> dict:
    return {
        "id": summary.get("id"),
        "session_id": summary.get("session_id"),
        "summary": _truncate(summary.get("summary", "")),
        "key_decisions": summary.get("key_decisions", []),
        "key_files": summary.get("key_files", []),
        "key_topics": summary.get("key_topics", []),
        "outcome": summary.get("outcome", ""),
        "project_id": summary.get("project_id"),
        "created_at": summary.get("created_at"),
    }


def _compact_generic(doc: dict) -> dict:
    compact = {"id": doc.get("id"), "type": doc.get("type")}
    for k in [
        "title",
        "description",
        "content",
        "category",
        "tags",
        "severity",
        "root_cause",
        "fix_description",
        "created_at",
        "project_id",
    ]:
        if k in doc:
            compact[k] = doc.get(k)
    return compact


def _build_context_text(grouped: dict, query: str) -> str:
    lines = []
    lines.append(f"Context for request: {query}")

    if grouped["sessions"]:
        lines.append("")
        lines.append("Relevant sessions:")
        for s in grouped["sessions"]:
            title = s.get("title") or ""
            summary = s.get("summary") or ""
            source = s.get("source") or "unknown"
            lines.append(f"- [{source}] {title} :: {summary}")

    if grouped["summaries"]:
        lines.append("")
        lines.append("Relevant summaries:")
        for s in grouped["summaries"]:
            lines.append(f"- {s.get('summary','')}")

    if grouped["messages"]:
        lines.append("")
        lines.append("Relevant messages:")
        for m in grouped["messages"]:
            source = m.get("session_source") or "unknown"
            lines.append(f"- [{m.get('role')}|{source}] {m.get('text_excerpt','')}")

    if grouped["decisions"]:
        lines.append("")
        lines.append("Relevant decisions:")
        for d in grouped["decisions"]:
            lines.append(f"- {d.get('title','')}: {d.get('description','')}")

    if grouped["bugs"]:
        lines.append("")
        lines.append("Relevant bugs:")
        for b in grouped["bugs"]:
            detail = b.get("root_cause") or b.get("description") or ""
            lines.append(f"- {b.get('title','')}: {detail}")

    if grouped["patterns"]:
        lines.append("")
        lines.append("Relevant patterns:")
        for p in grouped["patterns"]:
            lines.append(f"- {p.get('title','')}: {p.get('description','')}")

    if grouped["thoughts"]:
        lines.append("")
        lines.append("Recent thoughts:")
        for t in grouped["thoughts"]:
            lines.append(f"- {t.get('content','')}")

    return "\n".join(lines)


def _relevance_score(text: str, query_terms: list[str]) -> float:
    if not text:
        return 0.0
    base = _keyword_score(text, query_terms)
    richness = min(len(text) / 400.0, 1.0) * 0.05
    return base + richness


def _build_candidate_evidence(grouped: dict, query_terms: list[str]) -> list[dict]:
    candidates: list[dict] = []

    for s in grouped.get("sessions", []):
        text = f"{s.get('title', '')}\n{s.get('summary', '')}".strip()
        if text:
            candidates.append(
                {
                    "kind": "session",
                    "text": text,
                    "source": s.get("source", "unknown"),
                    "score": _relevance_score(text, query_terms) + 0.04,
                }
            )

    for d in grouped.get("decisions", []):
        text = f"{d.get('title', '')}: {d.get('description', '')}".strip(": ")
        if text:
            candidates.append(
                {
                    "kind": "decision",
                    "text": text,
                    "source": "knowledge",
                    "score": _relevance_score(text, query_terms) + 0.08,
                }
            )

    for b in grouped.get("bugs", []):
        detail = b.get("fix_description") or b.get("root_cause") or b.get("description", "")
        text = f"{b.get('title', '')}: {detail}".strip(": ")
        if text:
            candidates.append(
                {
                    "kind": "bug",
                    "text": text,
                    "source": "knowledge",
                    "score": _relevance_score(text, query_terms) + 0.08,
                }
            )

    for p in grouped.get("patterns", []):
        text = f"{p.get('title', '')}: {p.get('description', '')}".strip(": ")
        if text:
            candidates.append(
                {
                    "kind": "pattern",
                    "text": text,
                    "source": "knowledge",
                    "score": _relevance_score(text, query_terms) + 0.06,
                }
            )

    for m in grouped.get("messages", []):
        text = f"{m.get('role', '')}: {m.get('text_excerpt', '')}".strip(": ")
        if text:
            candidates.append(
                {
                    "kind": "message",
                    "text": text,
                    "source": m.get("session_source", "unknown"),
                    "score": _relevance_score(text, query_terms),
                }
            )

    for t in grouped.get("thoughts", []):
        text = str(t.get("content", "")).strip()
        if text:
            candidates.append(
                {
                    "kind": "thought",
                    "text": text,
                    "source": "knowledge",
                    "score": _relevance_score(text, query_terms),
                }
            )

    return sorted(candidates, key=lambda c: c["score"], reverse=True)


def _heuristic_context_summary(
    query: str,
    grouped: dict,
    context_reasoning_text: str,
    max_context_tokens: int,
) -> str:
    query_terms = _extract_query_terms(query)
    candidates = _build_candidate_evidence(grouped, query_terms)

    lines = [
        "Context reasoning:",
        context_reasoning_text,
        "",
        f"Task: {query}",
        "Most relevant retrieved context:",
    ]

    seen = set()
    for c in candidates:
        signature = f"{c['kind']}::{c['text']}"
        if signature in seen:
            continue
        seen.add(signature)
        lines.append(f"- [{c['kind']}|{c['source']}] {_truncate(c['text'], 220)}")
        assembled = "\n".join(lines)
        if _estimate_tokens(assembled) > max_context_tokens:
            lines.pop()
            break

    if len(lines) <= 5:
        lines.append("- No high-signal retrieved evidence found.")

    return _trim_to_token_budget("\n".join(lines), max_context_tokens)


def _llm_context_summary(
    query: str,
    grouped: dict,
    context_reasoning_text: str,
    max_context_tokens: int,
    openai_api_key: Optional[str],
) -> str:
    """Create focused context from retrieved docs, capped for LLM usage."""
    if not openai_api_key:
        return _heuristic_context_summary(query, grouped, context_reasoning_text, max_context_tokens)

    candidates = _build_candidate_evidence(grouped, _extract_query_terms(query))
    if not candidates:
        return _heuristic_context_summary(query, grouped, context_reasoning_text, max_context_tokens)

    evidence_blob = "\n".join(
        f"- [{c['kind']}|{c['source']}] {_truncate(c['text'], 260)}"
        for c in candidates[:40]
    )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=openai_api_key)
        target_output_tokens = min(1400, max(300, max_context_tokens - 350))
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            max_tokens=target_output_tokens,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize retrieved coding memory for another assistant. "
                        "Select only high-signal facts relevant to the task."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Task:\n{query}\n\n"
                        f"Context reasoning:\n{context_reasoning_text}\n\n"
                        "Retrieved evidence:\n"
                        f"{evidence_blob}\n\n"
                        "Return concise markdown with sections: Key facts, Prior attempts, Relevant tools/files, Risks/gaps."
                    ),
                },
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        if not content:
            return _heuristic_context_summary(query, grouped, context_reasoning_text, max_context_tokens)
        return _trim_to_token_budget(content, max_context_tokens)
    except Exception:
        return _heuristic_context_summary(query, grouped, context_reasoning_text, max_context_tokens)


def _source_breakdown(grouped: dict) -> dict:
    counts: dict[str, int] = {}
    for s in grouped.get("sessions", []):
        source = s.get("source")
        if source:
            counts[source] = counts.get(source, 0) + 1
    for m in grouped.get("messages", []):
        source = m.get("session_source")
        if source:
            counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _project_breakdown(grouped: dict) -> dict:
    counts: dict[str, int] = {}
    for s in grouped.get("sessions", []):
        pid = s.get("project_id")
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    for m in grouped.get("messages", []):
        pid = m.get("session_project_id") or m.get("project_id")
        if pid:
            counts[pid] = counts.get(pid, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: item[0]))


def _top_evidence(grouped: dict, max_items: int = 5) -> list[dict]:
    evidence: list[dict] = []

    for s in grouped.get("sessions", []):
        evidence.append(
            {
                "type": "session",
                "id": s.get("id"),
                "source": s.get("source"),
                "why": _truncate(f"title={s.get('title','')} summary={s.get('summary','')}", 140),
            }
        )
    for m in grouped.get("messages", []):
        evidence.append(
            {
                "type": "message",
                "id": m.get("id"),
                "source": m.get("session_source"),
                "why": _truncate(m.get("text_excerpt", ""), 140),
            }
        )
    for d in grouped.get("decisions", []):
        evidence.append(
            {
                "type": "decision",
                "id": d.get("id"),
                "source": "knowledge",
                "why": _truncate(f"{d.get('title','')}: {d.get('description','')}", 140),
            }
        )
    for b in grouped.get("bugs", []):
        evidence.append(
            {
                "type": "bug",
                "id": b.get("id"),
                "source": "knowledge",
                "why": _truncate(f"{b.get('title','')}: {b.get('description','')}", 140),
            }
        )

    return evidence[:max_items]


def _build_reasoning_text(context_reasoning: dict) -> str:
    hits = context_reasoning.get("hit_counts", {})
    selected = context_reasoning.get("selected_counts", {})
    lines = [
        f"- Effective project: {context_reasoning.get('effective_project_id')}",
        (
            f"- Project scope: {context_reasoning.get('project_scope')} "
            f"({', '.join(context_reasoning.get('scope_project_ids', [])) if context_reasoning.get('scope_project_ids') else 'all projects'})"
        ),
        f"- Retrieval steps: {', '.join(context_reasoning.get('retrieval_steps', []))}",
        (
            "- Hit counts: "
            f"primary={hits.get('primary_semantic_fts', 0)}, "
            f"kv_semantic={hits.get('kv_semantic_fallback', 0)}, "
            f"raw_chat={hits.get('raw_chat_fallback', 0)}"
        ),
        f"- Sources: {', '.join(context_reasoning.get('sources_in_context', [])) or 'none'}",
        f"- Projects in context: {', '.join(context_reasoning.get('projects_in_context', [])) or 'none'}",
        (
            "- Selected: "
            f"sessions={selected.get('sessions', 0)}, "
            f"messages={selected.get('messages', 0)}, "
            f"decisions={selected.get('decisions', 0)}, "
            f"bugs={selected.get('bugs', 0)}, "
            f"patterns={selected.get('patterns', 0)}"
        ),
    ]

    missing = context_reasoning.get("missing_context", [])
    if missing:
        lines.append(f"- Missing context: {', '.join(missing)}")

    top_evidence = context_reasoning.get("top_evidence", [])
    if top_evidence:
        lines.append("- Top evidence:")
        for item in top_evidence:
            lines.append(f"  - [{item.get('type')}|{item.get('source')}] {item.get('why')}")

    return "\n".join(lines)


def _estimate_tokens(text: str) -> int:
    # Rough estimation for planning/token budgeting.
    return max(1, len(text) // 4)


def _trim_to_token_budget(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max_tokens * 4
    if max_chars <= 1:
        return "…"
    return text[: max_chars - 1] + "…"


def _build_context_reasoning(
    query: str,
    requested_project_id: str,
    effective_project_id: str,
    project_scope: str,
    scope_project_ids: list[str] | None,
    primary_hits: int,
    kv_semantic_hits: int,
    raw_fallback_hits: int,
    grouped: dict,
) -> dict:
    sources = set(_source_breakdown(grouped).keys())
    missing_context = []
    for section in ["sessions", "messages", "decisions", "bugs", "patterns"]:
        if not grouped.get(section):
            missing_context.append(section)

    return {
        "query": query,
        "requested_project_id": requested_project_id,
        "effective_project_id": effective_project_id,
        "project_scope": project_scope,
        "scope_project_ids": scope_project_ids,
        "retrieval_steps": [
            "semantic_search",
            "file_path_fts",
            "kv_semantic_fallback",
            "raw_chat_fallback",
        ],
        "hit_counts": {
            "primary_semantic_fts": primary_hits,
            "kv_semantic_fallback": kv_semantic_hits,
            "raw_chat_fallback": raw_fallback_hits,
        },
        "selected_counts": {
            "sessions": len(grouped.get("sessions", [])),
            "messages": len(grouped.get("messages", [])),
            "decisions": len(grouped.get("decisions", [])),
            "bugs": len(grouped.get("bugs", [])),
            "patterns": len(grouped.get("patterns", [])),
            "thoughts": len(grouped.get("thoughts", [])),
        },
        "sources_in_context": sorted(sources),
        "source_breakdown": _source_breakdown(grouped),
        "projects_in_context": sorted(_project_breakdown(grouped).keys()),
        "project_breakdown": _project_breakdown(grouped),
        "top_evidence": _top_evidence(grouped, max_items=5),
        "missing_context": missing_context,
    }


def _doc_matches_projects(doc: dict, project_ids: list[str] | None) -> bool:
    if project_ids is None:
        return True
    if not project_ids:
        return False
    project = doc.get("project_id")
    session_project = doc.get("session_project_id")
    directory = doc.get("directory")
    session_directory = doc.get("session_directory")
    if project in project_ids or session_project in project_ids:
        return True
    # Backward compatibility for old docs imported into "default".
    if project == "default" and directory in project_ids:
        return True
    if session_project == "default" and session_directory in project_ids:
        return True
    return False


async def memory_context_for_request(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    query: str,
    project_id: str = "default",
    related_project_ids: list[str] | None = None,
    include_all_projects: bool | None = None,
    file_paths: list[str] | None = None,
    limit: int = 12,
    per_type_limit: int = 6,
    include_messages: bool = True,
    message_limit: int = 20,
    max_context_tokens: int = 2000,
) -> dict:
    """Build a rich context pack for a specific request."""
    requested_project_id = project_id
    effective_related_project_ids, effective_include_all_projects = resolve_scope_overrides(
        requested_related_project_ids=related_project_ids,
        requested_include_all_projects=include_all_projects,
        default_related_project_ids=getattr(db._settings, "default_related_project_ids", []),
        include_all_projects_by_default=bool(
            getattr(db._settings, "include_all_projects_by_default", False)
        ),
    )
    project_id, scope_project_ids = resolve_project_scope(
        requested_project_id=project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    )
    project_scope = "all" if scope_project_ids is None else ("cross-project" if len(scope_project_ids) > 1 else "project")
    inferred_paths = _extract_paths_from_query(query)
    paths = list(file_paths or []) + inferred_paths

    # Primary semantic search
    primary = await search.memory_search(
        db=db,
        provider=provider,
        query=query,
        project_id=project_id,
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
        limit=limit,
        collections=None,
    )
    results = list(primary.get("results", []))
    primary_hits = len(results)
    kv_semantic_hits = 0

    # Additional file-path focused FTS searches
    for path in paths:
        try:
            file_hits = search._fts_search(db, path, max(3, limit // 2))
            file_hits = [hit for hit in file_hits if _doc_matches_projects(hit, scope_project_ids)]
            results.extend(file_hits)
        except Exception as e:
            logger.warning(f"File path search failed for {path}: {e}")

    # If semantic + file hits are sparse, expand with KV + semantic merge.
    # This helps when vector/FTS indexes are thin or query phrasing is broad.
    if len(results) < max(4, limit // 2):
        try:
            terms = _extract_query_terms(query)
            if terms:
                kv_sem = await search.memory_kv_semantic_search(
                    db=db,
                    provider=provider,
                    terms=terms,
                    project_id=project_id,
                    related_project_ids=effective_related_project_ids,
                    include_all_projects=effective_include_all_projects,
                    limit=max(limit * 2, 12),
                    per_collection_limit=max(6, per_type_limit),
                )
                for r in kv_sem.get("results", []):
                    if "score" not in r:
                        r["score"] = 0.15
                    r.setdefault("source", "kv-semantic-fallback")
                kv_results = list(kv_sem.get("results", []))
                kv_semantic_hits = len(kv_results)
                results.extend(kv_results)
        except Exception as e:
            logger.warning(f"KV+semantic fallback failed: {e}")

    # Fallback: query raw chat docs directly and keyword-rank by request terms.
    # This allows context recall even when vector/FTS indexes are sparse.
    try:
        raw_results = _raw_chat_fallback(db=db, query=query, project_ids=scope_project_ids, limit=limit)
        raw_fallback_hits = len(raw_results)
        results.extend(raw_results)
    except Exception as e:
        logger.warning(f"Raw chat fallback failed: {e}")
        raw_fallback_hits = 0

    results = _dedupe_results(results)
    results = [r for r in results if _doc_matches_projects(r, scope_project_ids)]
    grouped_raw = _group_results(results, per_type_limit)

    # Compact documents for response
    grouped = {
        "sessions": [_compact_session(s) for s in grouped_raw["sessions"]],
        "summaries": [_compact_summary(s) for s in grouped_raw["summaries"]],
        "messages": [_compact_message(m) for m in grouped_raw["messages"]] if include_messages else [],
        "decisions": [_compact_generic(d) for d in grouped_raw["decisions"]],
        "bugs": [_compact_generic(b) for b in grouped_raw["bugs"]],
        "patterns": [_compact_generic(p) for p in grouped_raw["patterns"]],
        "thoughts": [_compact_generic(t) for t in grouped_raw["thoughts"]],
        "other": [_compact_generic(o) for o in grouped_raw["other"]],
    }

    # Trim messages if needed
    if include_messages and len(grouped["messages"]) > message_limit:
        grouped["messages"] = grouped["messages"][:message_limit]

    # Aggregate tool/skill/subagent signals from retrieved messages.
    tool_names, skills, subagents = _extract_skill_and_subagent_signals(grouped["messages"])

    # Attach recent project context (high-level)
    project_context = await memory_project_context(
        db=db,
        provider=provider,
        project_id=project_id,
        max_sessions=5,
        max_decisions=5,
        max_bugs=5,
        max_patterns=5,
    )

    raw_context_text = _build_context_text(grouped, query)
    context_reasoning = _build_context_reasoning(
        query=query,
        requested_project_id=requested_project_id,
        effective_project_id=project_id,
        project_scope=project_scope,
        scope_project_ids=scope_project_ids,
        primary_hits=primary_hits,
        kv_semantic_hits=kv_semantic_hits,
        raw_fallback_hits=raw_fallback_hits,
        grouped=grouped,
    )
    context_reasoning_text = _build_reasoning_text(context_reasoning)

    llm_context = _llm_context_summary(
        query=query,
        grouped=grouped,
        context_reasoning_text=context_reasoning_text,
        max_context_tokens=max_context_tokens,
        openai_api_key=getattr(db._settings, "openai_api_key", None),
    )
    llm_context = _trim_to_token_budget(llm_context, max_context_tokens)
    llm_context_token_estimate = _estimate_tokens(llm_context)
    context_text = _trim_to_token_budget(llm_context, max_context_tokens)
    raw_context_text = _trim_to_token_budget(raw_context_text, max_context_tokens)
    context_text_token_estimate = _estimate_tokens(context_text)

    response_token_estimate = _estimate_tokens(
        json.dumps(
            {
                "context": grouped,
                "context_reasoning": context_reasoning,
                "project_context": project_context,
                "context_text": context_text,
                "raw_context_text": raw_context_text,
            },
            default=str,
        )
    )

    return {
        "query": query,
        "project_id": project_id,
        "requested_project_id": requested_project_id,
        "project_scope": project_scope,
        "scope_project_ids": scope_project_ids,
        "related_project_ids": effective_related_project_ids or [],
        "include_all_projects": effective_include_all_projects,
        "file_paths": paths,
        "tool_calls_in_context": sorted(tool_names),
        "skills_in_context": sorted(skills),
        "subagents_in_context": sorted(subagents),
        "context": grouped,
        "sources_in_context": context_reasoning["sources_in_context"],
        "projects_in_context": context_reasoning.get("projects_in_context", []),
        "context_reasoning": context_reasoning,
        "context_reasoning_text": context_reasoning_text,
        "project_context": project_context,
        "context_text": context_text,
        "raw_context_text": raw_context_text,
        "context_text_token_estimate": context_text_token_estimate,
        "llm_context": llm_context,
        "llm_context_token_estimate": llm_context_token_estimate,
        "response_token_estimate": response_token_estimate,
        "max_context_tokens": max_context_tokens,
    }
