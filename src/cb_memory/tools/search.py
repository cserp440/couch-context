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


async def memory_search(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    query: str,
    project_id: str | None = None,
    related_project_ids: list[str] | None = None,
    include_all_projects: bool | None = None,
    limit: int = 10,
    collections: list[str] | None = None,
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
        vector_results = _vector_search(db, query_embedding, limit, collections)
        results.extend(vector_results)
    except Exception as e:
        logger.warning(f"Vector search failed: {e}")

    # 2. FTS text search on messages and sessions
    try:
        fts_results = _fts_search(db, query, limit)
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
        f"SELECT META(m).id as id, m.*, s.source AS session_source, "
        f"s.project_id AS session_project_id, s.directory AS session_directory "
        f"FROM `{bucket}`.conversations.messages m "
        f"JOIN `{bucket}`.conversations.sessions s ON KEYS m.session_id "
        f"WHERE ({_like_clause('m.text_content')} "
        f"OR {_like_clause('TOSTRING(m.tool_calls)')} "
        f"OR {_like_clause('TOSTRING(m.tool_results)')}) "
    )
    if project_ids is not None:
        q += f"AND {_session_project_match_expression_many('s')} "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "conversations"
            r["_collection"] = "messages"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search messages failed: {e}")

    # Sessions
    q = (
        f"SELECT META(s).id as id, s.* "
        f"FROM `{bucket}`.conversations.sessions s "
        f"WHERE ({_like_clause('s.title')} OR {_like_clause('s.summary')}) "
    )
    if project_ids is not None:
        q += f"AND {_session_project_match_expression_many('s')} "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "conversations"
            r["_collection"] = "sessions"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search sessions failed: {e}")

    # Knowledge: decisions
    q = (
        f"SELECT META(d).id as id, d.* "
        f"FROM `{bucket}`.knowledge.decisions d "
        f"WHERE ({_like_clause('d.title')} OR {_like_clause('d.description')} OR {_like_clause('d.context')}) "
    )
    if project_ids is not None:
        q += "AND d.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "knowledge"
            r["_collection"] = "decisions"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search decisions failed: {e}")

    # Knowledge: bugs
    q = (
        f"SELECT META(b).id as id, b.* "
        f"FROM `{bucket}`.knowledge.bugs b "
        f"WHERE ({_like_clause('b.title')} OR {_like_clause('b.description')} OR {_like_clause('b.root_cause')} OR {_like_clause('b.fix_description')}) "
    )
    if project_ids is not None:
        q += "AND b.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "knowledge"
            r["_collection"] = "bugs"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search bugs failed: {e}")

    # Knowledge: patterns
    q = (
        f"SELECT META(p).id as id, p.* "
        f"FROM `{bucket}`.knowledge.patterns p "
        f"WHERE ({_like_clause('p.title')} OR {_like_clause('p.description')} OR {_like_clause('p.code_example')}) "
    )
    if project_ids is not None:
        q += "AND p.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "knowledge"
            r["_collection"] = "patterns"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search patterns failed: {e}")

    # Knowledge: thoughts
    q = (
        f"SELECT META(t).id as id, t.* "
        f"FROM `{bucket}`.knowledge.thoughts t "
        f"WHERE ({_like_clause('t.content')}) "
    )
    if project_ids is not None:
        q += "AND t.project_id IN $project_ids "
    q += f"LIMIT {int(per_collection_limit)}"
    try:
        rows = list(db.cluster.query(q, terms=terms, project_ids=project_ids))
        for r in rows:
            r.pop("embedding", None)
            r["_scope"] = "knowledge"
            r["_collection"] = "thoughts"
        results.extend(rows)
    except Exception as e:
        logger.warning(f"KV search thoughts failed: {e}")

    return results


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
                    fields=["*"],
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
                "fields": row.fields if hasattr(row, "fields") else {},
                "source": f"vector:{index_name}",
            }
            # Try to fetch the full document
            full_doc = _fetch_document(db, row.id)
            if full_doc:
                doc.update(full_doc)
            results.append(doc)

    return results


def _fts_search(db: CouchbaseClient, query_text: str, limit: int) -> list[dict]:
    """Run full-text search across available FTS indexes."""
    match_query = search.MatchQuery(query_text)
    req = search.SearchRequest.create(match_query)

    results = []
    for index_name in INDEX_NAMES:
        try:
            result = db.cluster.search(
                index_name,
                req,
                SearchOptions(limit=limit, fields=["*"]),
            )
        except Exception as e:
            logger.warning(f"FTS search error on {index_name}: {e}")
            continue

        for row in result.rows():
            doc = {
                "id": row.id,
                "score": row.score,
                "source": f"fts:{index_name}",
                "fields": row.fields if hasattr(row, "fields") else {},
            }
            full_doc = _fetch_document(db, row.id)
            if full_doc:
                doc.update(full_doc)
            results.append(doc)

    return results


def _fetch_document(db: CouchbaseClient, doc_id: str) -> dict | None:
    """Attempt to fetch a document by ID from the appropriate collection."""
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
                # Remove embedding from response to save tokens
                data.pop("embedding", None)
                if scope == "conversations" and coll == "messages":
                    session_id = data.get("session_id")
                    if session_id:
                        try:
                            sres = db.sessions.get(session_id)
                            sdoc = sres.content_as[dict]
                            data["session_source"] = sdoc.get("source")
                            data["session_project_id"] = sdoc.get("project_id")
                            data["session_directory"] = sdoc.get("directory")
                        except Exception:
                            pass
                data["_scope"] = scope
                data["_collection"] = coll
                return data
            except Exception:
                return None

    return None
