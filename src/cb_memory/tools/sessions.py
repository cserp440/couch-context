"""Session tools — list, get, ingest sessions and messages."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import EmbeddingProvider
from cb_memory.models import MessageDoc, SessionDoc, SummaryDoc
from cb_memory.project import derive_project_id, resolve_runtime_project_id

logger = logging.getLogger(__name__)

_MESSAGE_CHUNK_SIZE = 8000


def _split_text_chunks(text: str, chunk_size: int = _MESSAGE_CHUNK_SIZE) -> list[str]:
    if not text:
        return [""]
    if len(text) <= chunk_size:
        return [text]
    return [text[i : i + chunk_size] for i in range(0, len(text), chunk_size)]


def _reassemble_chunked_messages(messages: list[dict]) -> list[dict]:
    grouped: dict[str, list[dict]] = {}
    ordered_keys: list[str] = []
    passthrough: list[dict] = []

    for m in messages:
        group_id = m.get("message_group_id")
        if isinstance(group_id, str) and group_id:
            if group_id not in grouped:
                grouped[group_id] = []
                ordered_keys.append(group_id)
            grouped[group_id].append(m)
        else:
            passthrough.append(m)

    rebuilt: list[dict] = []
    for key in ordered_keys:
        chunks = sorted(grouped[key], key=lambda x: int(x.get("chunk_index", 0)))
        first = dict(chunks[0])
        first["text_content"] = "".join(str(c.get("text_content", "")) for c in chunks)
        first["sequence_number"] = int(first.get("original_sequence_number", first.get("sequence_number", 0)))
        first["chunk_index"] = 0
        first["chunk_count"] = len(chunks)
        rebuilt.append(first)

    rebuilt.extend(passthrough)
    rebuilt.sort(key=lambda x: int(x.get("sequence_number", 0)))
    return rebuilt


async def memory_list_sessions(
    db: CouchbaseClient,
    project_id: str | None = None,
    limit: int = 20,
    offset: int = 0,
    sort_by: str = "created_at",
) -> dict:
    """List past coding sessions with pagination.

    Args:
        project_id: Filter by project.
        limit: Max sessions to return.
        offset: Pagination offset.
        sort_by: Sort field (created_at, started_at, message_count).
    """
    bucket = db._settings.cb_bucket
    effective_project_id = resolve_runtime_project_id(
        requested_project_id=project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
        allow_unset=True,
    )

    where_clause = ""
    params: dict = {}
    if effective_project_id:
        where_clause = (
            "WHERE (s.project_id = $project_id "
            "OR (s.project_id = 'default' AND s.directory = $project_id))"
        )
        params["project_id"] = effective_project_id

    allowed_sorts = {"created_at", "started_at", "message_count"}
    if sort_by not in allowed_sorts:
        sort_by = "created_at"

    query = (
        f"SELECT s.* FROM `{bucket}`.conversations.sessions s "
        f"{where_clause} "
        f"ORDER BY s.{sort_by} DESC "
        f"LIMIT {int(limit)} OFFSET {int(offset)}"
    )

    try:
        rows = list(db.cluster.query(query, **params))
    except Exception as e:
        logger.warning(f"List sessions query failed: {e}")
        rows = []

    # Strip embeddings from response
    for r in rows:
        r.pop("embedding", None)

    return {
        "sessions": rows,
        "count": len(rows),
        "offset": offset,
        "limit": limit,
        "project_id": effective_project_id,
    }


async def memory_get_session(
    db: CouchbaseClient,
    session_id: str,
    include_messages: bool = True,
    message_limit: int = 5000,
) -> dict:
    """Get full session detail including messages.

    Args:
        session_id: The session ID (e.g. "session::01ABCDEF...").
        include_messages: Whether to include message contents.
        message_limit: Max messages to return.
    """
    # Fetch session metadata
    try:
        result = db.sessions.get(session_id)
        session_data = result.content_as[dict]
        session_data.pop("embedding", None)
    except Exception as e:
        return {"error": f"Session not found: {e}"}

    response = {"session": session_data}

    if include_messages:
        bucket = db._settings.cb_bucket
        session_part = session_id.removeprefix("session::")
        query = (
            f"SELECT m.* FROM `{bucket}`.conversations.messages m "
            f"WHERE m.session_id = '{session_id}' "
            f"ORDER BY m.sequence_number ASC "
            f"LIMIT {int(message_limit)}"
        )
        try:
            messages = list(db.cluster.query(query))
            for m in messages:
                m.pop("embedding", None)
            reassembled = _reassemble_chunked_messages(messages)
            response["messages"] = reassembled
            response["message_count"] = len(reassembled)
        except Exception as e:
            logger.warning(f"Fetch messages failed: {e}")
            response["messages"] = []
            response["message_count"] = 0

    # Fetch summary if available
    summary_id = f"summary::{session_id.removeprefix('session::')}"
    try:
        result = db.summaries.get(summary_id)
        summary_data = result.content_as[dict]
        summary_data.pop("embedding", None)
        response["summary"] = summary_data
    except Exception:
        response["summary"] = None

    return response


async def memory_ingest_session(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    title: str,
    messages: list[dict],
    project_id: str = "default",
    directory: str = "",
    source: str = "manual",
    tags: list[str] | None = None,
    summary: str = "",
) -> dict:
    """Save a full session (metadata + messages) to memory.

    Args:
        title: Session title/description.
        messages: List of message dicts with keys: role, content.
        project_id: Project identifier.
        directory: Working directory of the session.
        source: Source of the session (e.g. "opencode", "claude-code").
        tags: Optional tags.
        summary: Optional pre-generated summary.
    """
    effective_project_id = derive_project_id(
        configured_project_id=project_id,
        directory=directory or getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    )

    # Create session doc
    session = SessionDoc(
        title=title,
        project_id=effective_project_id,
        directory=directory,
        source=source,
        message_count=len(messages),
        tags=tags or [],
        summary=summary,
    )

    # Embed session title+summary for searchability
    embed_text = f"{title}\n{summary}" if summary else title
    session.embedding = provider.embed_one(embed_text)

    # Save session
    db.sessions.upsert(session.id, session.model_dump(mode="json"))

    # Save messages
    files_modified = set()
    tools_used = set()

    seq = 0
    for i, msg in enumerate(messages):
        chunks = _split_text_chunks(msg.get("content", ""))
        group_id = f"{session.id.removeprefix('session::')}::{i:08d}"
        for chunk_index, chunk_text in enumerate(chunks):
            msg_doc = MessageDoc(
                id=f"msg::{group_id}::{chunk_index:04d}",
                session_id=session.id,
                project_id=effective_project_id,
                role=msg.get("role", "user"),
                text_content=chunk_text,
                raw_content=msg.get("raw_content") if chunk_index == 0 else None,
                tool_calls=msg.get("tool_calls", []) if chunk_index == 0 else [],
                tool_results=msg.get("tool_results", []) if chunk_index == 0 else [],
                message_group_id=group_id,
                chunk_index=chunk_index,
                chunk_count=len(chunks),
                original_sequence_number=i,
                sequence_number=seq,
            )
            db.messages.upsert(msg_doc.id, msg_doc.model_dump(mode="json"))
            seq += 1

        # Collect metadata
        for tc in msg.get("tool_calls", []):
            if isinstance(tc, dict) and "name" in tc:
                tools_used.add(tc["name"])

    # Update session with collected metadata
    session.tools_used = list(tools_used)
    session.files_modified = list(files_modified)
    db.sessions.upsert(session.id, session.model_dump(mode="json"))

    # Generate and save summary
    if summary or len(messages) > 0:
        summary_doc = SummaryDoc(
            session_id=session.id,
            summary=summary or f"Session: {title}",
            project_id=effective_project_id,
        )
        summary_doc.generate_id()
        summary_doc.embedding = provider.embed_one(
            summary_doc.summary
        )
        db.summaries.upsert(summary_doc.id, summary_doc.model_dump(mode="json"))

    return {
        "session_id": session.id,
        "project_id": effective_project_id,
        "message_count": len(messages),
        "status": "ingested",
    }


async def memory_ingest_message(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    session_id: str,
    role: str,
    content: str,
    tool_calls: list[dict] | None = None,
    sequence_number: int = 0,
) -> dict:
    """Save a single message to an existing session.

    Args:
        session_id: Parent session ID.
        role: Message role (user, assistant, system, tool).
        content: Message text content.
        tool_calls: Optional list of tool call dicts.
        sequence_number: Position in conversation.
    """
    project_id = resolve_runtime_project_id(
        requested_project_id="default",
        current_project_id=getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    ) or "default"
    try:
        session_res = db.sessions.get(session_id)
        session_doc = session_res.content_as[dict]
        project_id = session_doc.get("project_id", "default")
    except Exception:
        pass

    msg_doc = MessageDoc(
        session_id=session_id,
        project_id=project_id,
        role=role,
        text_content=content,
        tool_calls=tool_calls or [],
        sequence_number=sequence_number,
    )
    msg_doc.generate_id()

    # Embed message content
    if content:
        msg_doc.embedding = provider.embed_one(content)

    db.messages.upsert(msg_doc.id, msg_doc.model_dump(mode="json"))

    # Update session message count
    try:
        import couchbase.subdocument as SD
        db.sessions.mutate_in(session_id, [
            SD.increment("message_count", 1),
        ])
    except Exception:
        pass  # Session might not exist yet

    return {
        "message_id": msg_doc.id,
        "session_id": session_id,
        "status": "saved",
    }
