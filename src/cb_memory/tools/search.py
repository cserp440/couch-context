"""Semantic search across all memory collections."""

from __future__ import annotations

import logging

import couchbase.search as search
from couchbase.options import SearchOptions
from couchbase.vector_search import VectorQuery, VectorSearch

from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import EmbeddingProvider
from cb_memory.project import resolve_project_scope, resolve_scope_overrides

logger = logging.getLogger(__name__)

INDEX_NAMES = [
    "coding-memory-conversations-index",
    "coding-memory-knowledge-index",
]


def _resolve_project_scope(
    db: CouchbaseClient,
    project_id: str | None,
    related_project_ids: list[str] | None,
    include_all_projects: bool | None,
) -> tuple[str, list[str] | None]:
    effective_related_project_ids, effective_include_all_projects = resolve_scope_overrides(
        requested_related_project_ids=related_project_ids,
        requested_include_all_projects=include_all_projects,
        default_related_project_ids=getattr(db._settings, "default_related_project_ids", []),
        include_all_projects_by_default=bool(
            getattr(db._settings, "include_all_projects_by_default", False)
        ),
    )
    return resolve_project_scope(
        requested_project_id=project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    )


def _session_project_match_expression_many(alias: str = "s") -> str:
    return (
        f"({alias}.project_id IN $project_ids "
        f"OR ({alias}.project_id = 'default' AND {alias}.directory IN $project_ids))"
    )


def _doc_matches_projects(doc: dict, project_ids: list[str]) -> bool:
    if not project_ids:
        return True
    if doc.get("project_id") in project_ids:
        return True
    if doc.get("session_project_id") in project_ids:
        return True
    if doc.get("project_id") == "default" and doc.get("directory") in project_ids:
        return True
    if doc.get("session_project_id") == "default" and doc.get("session_directory") in project_ids:
        return True
    return False


def _extract_text(doc: dict) -> str:
    for key in (
        "text_content",
        "description",
        "content",
        "context",
        "root_cause",
        "fix_description",
        "code_example",
        "title",
    ):
        value = doc.get(key)
        if value:
            return str(value)
    return ""


async def memory_search(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    query: str,
    project_id: str | None = None,
    related_project_ids: list[str] | None = None,
    include_all_projects: bool | None = None,
    limit: int = 10,
    collections: list[str] | None = None,
    include_full_doc: bool = False,
) -> dict:
    """Semantic search across all memory — vector search + FTS.

    Args:
        query: Natural language search query.
        project_id: Base project for filtering.
        related_project_ids: Optional extra projects for cross-project retrieval.
        include_all_projects: If true, disable project filtering (global).
        limit: Maximum number of results.
        collections: Optionally restrict to specific collections
                     (e.g. ["decisions", "bugs"]).
    """
    effective_related_project_ids, effective_include_all_projects = resolve_scope_overrides(
        requested_related_project_ids=related_project_ids,
        requested_include_all_projects=include_all_projects,
        default_related_project_ids=getattr(db._settings, "default_related_project_ids", []),
        include_all_projects_by_default=bool(
            getattr(db._settings, "include_all_projects_by_default", False)
        ),
    )
    effective_project_id, scope_project_ids = _resolve_project_scope(
        db=db,
        project_id=project_id,
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
    )

    # Generate query embedding
    query_embedding = provider.embed_one(query)

    results = []

    # 1. Vector search across knowledge + summaries
    try:
        vector_results = _vector_search(
            db,
            query_embedding,
            limit,
            collections,
            include_full_doc=include_full_doc,
        )
        results.extend(vector_results)
    except Exception as e:
        logger.warning(f"Vector search failed: {e}")

    # 2. FTS text search on messages and sessions
    try:
        fts_results = _fts_search(db, query, limit, include_full_doc=include_full_doc)
        results.extend(fts_results)
    except Exception as e:
        logger.warning(f"FTS search failed: {e}")

    # Deduplicate by id and sort by score
    seen = set()
    unique_results = []
    for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
        if r["id"] not in seen:
            seen.add(r["id"])
            unique_results.append(r)

    # Filter by project_id if specified
    if scope_project_ids is not None:
        unique_results = [
            r for r in unique_results
            if _doc_matches_projects(r, scope_project_ids)
        ]

    return {
        "query": query,
        "project_id": effective_project_id,
        "scope_project_ids": scope_project_ids,
        "include_all_projects": effective_include_all_projects,
        "result_count": len(unique_results[:limit]),
        "results": unique_results[:limit],
    }


async def memory_kv_semantic_search(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    terms: list[str],
    project_id: str | None = None,
    related_project_ids: list[str] | None = None,
    include_all_projects: bool | None = None,
    limit: int = 20,
    per_collection_limit: int = 10,
) -> dict:
    """Keyword (KV) grep-style search + semantic search.

    Args:
        terms: List of keyword terms to match (case-insensitive).
        project_id: Base project for filtering.
        related_project_ids: Optional extra projects for cross-project retrieval.
        include_all_projects: If true, disable project filtering (global).
        limit: Max results to return after merging.
        per_collection_limit: Max results per collection in KV phase.
    """
    cleaned_terms = [t.strip() for t in terms if t and t.strip()]
    if not cleaned_terms:
        return {"error": "No valid terms provided", "results": []}

    effective_related_project_ids, effective_include_all_projects = resolve_scope_overrides(
        requested_related_project_ids=related_project_ids,
        requested_include_all_projects=include_all_projects,
        default_related_project_ids=getattr(db._settings, "default_related_project_ids", []),
        include_all_projects_by_default=bool(
            getattr(db._settings, "include_all_projects_by_default", False)
        ),
    )
    effective_project_id, scope_project_ids = _resolve_project_scope(
        db=db,
        project_id=project_id,
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
    )

    kv_results = _kv_grep(db, cleaned_terms, scope_project_ids, per_collection_limit)

    # Semantic search using the concatenated terms
    semantic = await memory_search(
        db=db,
        provider=provider,
        query=" ".join(cleaned_terms),
        project_id=effective_project_id,
        related_project_ids=effective_related_project_ids,
        include_all_projects=effective_include_all_projects,
        limit=limit,
        collections=None,
    )

    merged = kv_results + list(semantic.get("results", []))
    merged = _dedupe_results(merged)

    return {
        "terms": cleaned_terms,
        "project_id": effective_project_id,
        "scope_project_ids": scope_project_ids,
        "include_all_projects": effective_include_all_projects,
        "result_count": len(merged[:limit]),
        "results": merged[:limit],
    }


def _kv_grep(
    db: CouchbaseClient,
    terms: list[str],
    project_ids: list[str] | None,
    per_collection_limit: int,
) -> list[dict]:
    """Run grep-style LIKE searches across key collections."""
    bucket = db._settings.cb_bucket
    results: list[dict] = []

    # Build a case-insensitive LIKE clause for a field
    def _like_clause(field: str) -> str:
        return f"ANY term IN $terms SATISFIES LOWER({field}) LIKE '%' || LOWER(term) || '%' END"

    # Messages (filter project via parent session for backward compatibility)
    q = (
        f"SELECT META(m).id as id, m.text_content, m.role, m.project_id, m.session_id, m.timestamp, "
        f"s.source AS session_source, "
        f"s.project_id AS session_project_id, s.directory AS session_directory "
        f"FROM `{bucket}`.conversations.messages m "
        f"JOIN `{bucket}`.conversations.sessions s ON KEYS m.session_id "
        f"WHERE ({_like_clause('m.text_content')}) "
    )
    if project_ids is not None:
        q += f"AND {_session_project_match_expression_many('s')} "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "conversations", "messages"))
    except Exception as e:
        logger.warning(f"KV search messages failed: {e}")

    # Sessions
    q = (
        f"SELECT META(s).id as id, s.title, s.project_id, s.directory, s.source, s.created_at "
        f"FROM `{bucket}`.conversations.sessions s "
        f"WHERE ({_like_clause('s.title')}) "
    )
    if project_ids is not None:
        q += f"AND {_session_project_match_expression_many('s')} "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "conversations", "sessions"))
    except Exception as e:
        logger.warning(f"KV search sessions failed: {e}")

    # Knowledge: decisions
    q = (
        f"SELECT META(d).id as id, d.title, d.description, d.context, d.project_id, d.created_at "
        f"FROM `{bucket}`.knowledge.decisions d "
        f"WHERE ({_like_clause('d.title')} OR {_like_clause('d.description')} OR {_like_clause('d.context')}) "
    )
    if project_ids is not None:
        q += "AND d.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "knowledge", "decisions"))
    except Exception as e:
        logger.warning(f"KV search decisions failed: {e}")

    # Knowledge: bugs
    q = (
        f"SELECT META(b).id as id, b.title, b.description, b.root_cause, b.fix_description, b.project_id, b.created_at "
        f"FROM `{bucket}`.knowledge.bugs b "
        f"WHERE ({_like_clause('b.title')} OR {_like_clause('b.description')} OR {_like_clause('b.root_cause')} OR {_like_clause('b.fix_description')}) "
    )
    if project_ids is not None:
        q += "AND b.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "knowledge", "bugs"))
    except Exception as e:
        logger.warning(f"KV search bugs failed: {e}")

    # Knowledge: patterns
    q = (
        f"SELECT META(p).id as id, p.title, p.description, p.code_example, p.project_id, p.created_at "
        f"FROM `{bucket}`.knowledge.patterns p "
        f"WHERE ({_like_clause('p.title')} OR {_like_clause('p.description')} OR {_like_clause('p.code_example')}) "
    )
    if project_ids is not None:
        q += "AND p.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "knowledge", "patterns"))
    except Exception as e:
        logger.warning(f"KV search patterns failed: {e}")

    # Knowledge: thoughts
    q = (
        f"SELECT META(t).id as id, t.content, t.category, t.project_id, t.created_at "
        f"FROM `{bucket}`.knowledge.thoughts t "
        f"WHERE ({_like_clause('t.content')}) "
    )
    if project_ids is not None:
        q += "AND t.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        results.extend(_annotate_kv_rows(rows, terms, "knowledge", "thoughts"))
    except Exception as e:
        logger.warning(f"KV search thoughts failed: {e}")

    return results


def _annotate_kv_rows(
    rows: list[dict],
    terms: list[str],
    scope: str,
    collection: str,
) -> list[dict]:
    out: list[dict] = []
    for row in rows:
        row.pop("embedding", None)
        row.pop("tool_results", None)
        matched_terms = _matched_terms(row, terms)
        # Keep exact keyword hits ahead of semantic-only matches.
        row["score"] = 10.0 + float(len(matched_terms))
        row["source"] = "kv"
        row["text"] = _extract_text(row)
        row["_matched_terms"] = matched_terms
        row["_scope"] = scope
        row["_collection"] = collection
        out.append(row)
    return out


def _matched_terms(row: dict, terms: list[str]) -> list[str]:
    lowered_terms = [t.lower() for t in terms if t and t.strip()]
    if not lowered_terms:
        return []

    fields = [
        row.get("text_content"),
        row.get("title"),
        row.get("description"),
        row.get("context"),
        row.get("root_cause"),
        row.get("fix_description"),
        row.get("code_example"),
        row.get("content"),
    ]
    haystack = " ".join(str(v) for v in fields if v is not None).lower()
    if not haystack:
        return []
    return [t for t in lowered_terms if t in haystack]


def _dedupe_results(results: list[dict]) -> list[dict]:
    seen = set()
    unique_results = []
    for r in sorted(results, key=lambda x: x.get("score", 0), reverse=True):
        rid = r.get("id")
        if not rid or rid in seen:
            continue
        seen.add(rid)
        unique_results.append(r)
    return unique_results


def _vector_search(
    db: CouchbaseClient,
    embedding: list[float],
    limit: int,
    collections: list[str] | None,
    include_full_doc: bool = False,
) -> list[dict]:
    """Run vector search against available FTS indexes."""
    vq = VectorQuery("embedding", embedding, num_candidates=limit * 3)
    req = search.SearchRequest.create(search.MatchAllQuery())
    results = []
    for index_name in INDEX_NAMES:
        try:
            result = db.cluster.search(
                index_name,
                req,
                SearchOptions(
                    limit=limit,
                    vector_search=VectorSearch([vq]),
                ),
            )
        except Exception as e:
            logger.warning(f"Vector search error on {index_name}: {e}")
            continue

        for row in result.rows():
            doc = {
                "id": row.id,
                "score": row.score,
                "source": f"vector:{index_name}",
            }
            projected, full_doc = _fetch_document_text_only(db, row.id)
            if projected:
                doc.update(projected)
            doc["text"] = _extract_text(projected or {})
            if include_full_doc and full_doc:
                doc["_full_doc"] = full_doc
            results.append(doc)

    return results


def _fts_search(
    db: CouchbaseClient,
    query_text: str,
    limit: int,
    include_full_doc: bool = False,
) -> list[dict]:
    """Run full-text search across available FTS indexes."""
    match_query = search.MatchQuery(query_text)
    req = search.SearchRequest.create(match_query)

    results = []
    for index_name in INDEX_NAMES:
        try:
            result = db.cluster.search(
                index_name,
                req,
                SearchOptions(limit=limit),
            )
        except Exception as e:
            logger.warning(f"FTS search error on {index_name}: {e}")
            continue

        for row in result.rows():
            doc = {
                "id": row.id,
                "score": row.score,
                "source": f"fts:{index_name}",
            }
            projected, full_doc = _fetch_document_text_only(db, row.id)
            if projected:
                doc.update(projected)
            doc["text"] = _extract_text(projected or {})
            if include_full_doc and full_doc:
                doc["_full_doc"] = full_doc
            results.append(doc)

    return results


def _fetch_document_text_only(db: CouchbaseClient, doc_id: str) -> tuple[dict | None, dict | None]:
    """Fetch text-first projection directly from Couchbase, with optional full doc fallback."""
    # Determine collection from doc ID prefix
    prefix_map = {
        "session::": ("conversations", "sessions"),
        "msg::": ("conversations", "messages"),
        "summary::": ("conversations", "summaries"),
        "decision::": ("knowledge", "decisions"),
        "bug::": ("knowledge", "bugs"),
        "thought::": ("knowledge", "thoughts"),
        "pattern::": ("knowledge", "patterns"),
    }

    for prefix, (scope, coll) in prefix_map.items():
        if doc_id.startswith(prefix):
            try:
                result = db.collection(scope, coll).get(doc_id)
                data = result.content_as[dict]
                data.pop("embedding", None)
                data.pop("tool_results", None)

                projected: dict = {
                    "_scope": scope,
                    "_collection": coll,
                }

                if scope == "conversations" and coll == "messages":
                    projected.update(
                        {
                            "session_id": data.get("session_id"),
                            "project_id": data.get("project_id"),
                            "role": data.get("role"),
                            "timestamp": data.get("timestamp"),
                            "text_content": data.get("text_content", ""),
                        }
                    )
                    session_id = data.get("session_id")
                    if session_id:
                        try:
                            sres = db.sessions.get(session_id)
                            sdoc = sres.content_as[dict]
                            projected["session_source"] = sdoc.get("source")
                            projected["session_project_id"] = sdoc.get("project_id")
                            projected["session_directory"] = sdoc.get("directory")
                        except Exception:
                            pass
                elif scope == "conversations" and coll == "sessions":
                    projected.update(
                        {
                            "project_id": data.get("project_id"),
                            "directory": data.get("directory"),
                            "session_source": data.get("source"),
                            "title": data.get("title", ""),
                        }
                    )
                elif scope == "conversations" and coll == "summaries":
                    projected.update(
                        {
                            "project_id": data.get("project_id"),
                            "session_id": data.get("session_id"),
                            "text_content": data.get("summary", ""),
                        }
                    )
                else:
                    projected.update(
                        {
                            "project_id": data.get("project_id"),
                            "title": data.get("title", ""),
                            "description": data.get("description", ""),
                            "context": data.get("context", ""),
                            "root_cause": data.get("root_cause", ""),
                            "fix_description": data.get("fix_description", ""),
                            "code_example": data.get("code_example", ""),
                            "content": data.get("content", ""),
                        }
                    )

                return projected, data
            except Exception:
                return None, None

    return None, None
