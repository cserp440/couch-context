"""Recall tools — find past decisions and bugs by semantic similarity."""

from __future__ import annotations

import logging

import couchbase.search as search
from couchbase.options import SearchOptions
from couchbase.vector_search import VectorQuery, VectorSearch

from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import EmbeddingProvider
from cb_memory.project import resolve_runtime_project_id

logger = logging.getLogger(__name__)

INDEX_NAMES = [
    "coding-memory-conversations-index",
    "coding-memory-knowledge-index",
]


def _effective_project_id(db: CouchbaseClient, project_id: str | None) -> str | None:
    return resolve_runtime_project_id(
        requested_project_id=project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
        allow_unset=True,
    )


async def memory_recall_decision(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    query: str,
    category: str | None = None,
    project_id: str | None = None,
    limit: int = 5,
) -> dict:
    """Find past architectural/coding decisions by semantic similarity.

    Args:
        query: Natural language description of what you're looking for.
        category: Optional filter (e.g. "architecture", "library-choice").
        project_id: Optional project filter.
        limit: Max results to return.
    """
    project_id = _effective_project_id(db, project_id)
    embedding = provider.embed_one(query)
    results = _vector_recall(
        db, embedding, "knowledge.decisions", limit * 2
    )

    # Apply filters
    filtered = []
    for doc in results:
        if category and doc.get("category", "") != category:
            continue
        if project_id and doc.get("project_id", "default") != project_id:
            continue
        filtered.append(doc)

    return {
        "query": query,
        "category_filter": category,
        "result_count": len(filtered[:limit]),
        "results": filtered[:limit],
    }


async def memory_recall_bug(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    query: str,
    severity: str | None = None,
    project_id: str | None = None,
    limit: int = 5,
) -> dict:
    """Find past bug reports and fixes by semantic similarity.

    Args:
        query: Describe the bug or error you're looking for.
        severity: Optional filter ("low", "medium", "high", "critical").
        project_id: Optional project filter.
        limit: Max results to return.
    """
    project_id = _effective_project_id(db, project_id)
    embedding = provider.embed_one(query)
    results = _vector_recall(db, embedding, "knowledge.bugs", limit * 2)

    # Apply filters
    filtered = []
    for doc in results:
        if severity and doc.get("severity", "") != severity:
            continue
        if project_id and doc.get("project_id", "default") != project_id:
            continue
        filtered.append(doc)

    return {
        "query": query,
        "severity_filter": severity,
        "result_count": len(filtered[:limit]),
        "results": filtered[:limit],
    }


def _vector_recall(
    db: CouchbaseClient,
    embedding: list[float],
    collection_type: str,
    limit: int,
) -> list[dict]:
    """Vector search within a specific collection type mapping."""
    vq = VectorQuery("embedding", embedding, num_candidates=limit * 3)
    req = search.SearchRequest.create(search.MatchAllQuery())

    # Determine the expected prefix from collection_type
    prefix_map = {
        "knowledge.decisions": "decision::",
        "knowledge.bugs": "bug::",
        "knowledge.thoughts": "thought::",
        "knowledge.patterns": "pattern::",
        "conversations.summaries": "summary::",
    }
    expected_prefix = prefix_map.get(collection_type, "")

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
            logger.warning(f"Vector recall error on {index_name}: {e}")
            continue

        for row in result.rows():
            # Filter to only matching collection
            if expected_prefix and not row.id.startswith(expected_prefix):
                continue

            doc = _fetch_and_format(db, row.id, row.score)
            if doc:
                results.append(doc)

    seen = set()
    deduped = []
    for item in sorted(results, key=lambda x: x.get("_score", 0), reverse=True):
        doc_id = item.get("id")
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        deduped.append(item)

    return deduped


def _fetch_and_format(db: CouchbaseClient, doc_id: str, score: float) -> dict | None:
    """Fetch a document and format it for response."""
    prefix_map = {
        "decision::": ("knowledge", "decisions"),
        "bug::": ("knowledge", "bugs"),
        "thought::": ("knowledge", "thoughts"),
        "pattern::": ("knowledge", "patterns"),
        "summary::": ("conversations", "summaries"),
    }

    for prefix, (scope, coll) in prefix_map.items():
        if doc_id.startswith(prefix):
            try:
                result = db.collection(scope, coll).get(doc_id)
                data = result.content_as[dict]
                data.pop("embedding", None)
                data["id"] = doc_id
                data["_score"] = score
                return data
            except Exception:
                return None

    return None
