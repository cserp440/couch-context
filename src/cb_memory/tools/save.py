"""Knowledge capture tools — save decisions, bugs, thoughts, patterns."""

from __future__ import annotations

from cb_memory.db import CouchbaseClient
from cb_memory.embeddings import EmbeddingProvider
from cb_memory.models import BugDoc, DecisionDoc, PatternDoc, ThoughtDoc
from cb_memory.project import resolve_runtime_project_id


def _embed_text(provider: EmbeddingProvider, text: str) -> list[float]:
    """Generate embedding for a text string."""
    return provider.embed_one(text)


def _effective_project_id(db: CouchbaseClient, project_id: str | None) -> str:
    return resolve_runtime_project_id(
        requested_project_id=project_id,
        current_project_id=getattr(db._settings, "current_project_id", None),
        default_project_id=getattr(db._settings, "default_project_id", "default"),
    ) or "default"


async def memory_save_decision(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    title: str,
    description: str,
    category: str = "",
    context: str = "",
    alternatives: list[str] | None = None,
    consequences: list[str] | None = None,
    tags: list[str] | None = None,
    project_id: str = "default",
    source_session_id: str | None = None,
) -> dict:
    """Record an architectural or coding decision."""
    project_id = _effective_project_id(db, project_id)
    doc = DecisionDoc(
        title=title,
        description=description,
        category=category,
        context=context,
        alternatives=alternatives or [],
        consequences=consequences or [],
        tags=tags or [],
        project_id=project_id,
        source_session_id=source_session_id,
    )
    embed_text = f"{title}\n{description}\n{context}"
    doc.embedding = _embed_text(provider, embed_text)

    db.decisions.upsert(doc.id, doc.model_dump(mode="json"))
    return {"id": doc.id, "status": "saved", "type": "decision"}


async def memory_save_bug(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    title: str,
    description: str,
    root_cause: str = "",
    fix_description: str = "",
    files_affected: list[str] | None = None,
    error_messages: list[str] | None = None,
    severity: str = "medium",
    tags: list[str] | None = None,
    project_id: str = "default",
    source_session_id: str | None = None,
) -> dict:
    """Record a bug and its fix."""
    project_id = _effective_project_id(db, project_id)
    doc = BugDoc(
        title=title,
        description=description,
        root_cause=root_cause,
        fix_description=fix_description,
        files_affected=files_affected or [],
        error_messages=error_messages or [],
        severity=severity,
        tags=tags or [],
        project_id=project_id,
        source_session_id=source_session_id,
    )
    embed_text = f"{title}\n{description}\n{root_cause}\n{fix_description}"
    if error_messages:
        embed_text += "\n" + "\n".join(error_messages)
    doc.embedding = _embed_text(provider, embed_text)

    db.bugs.upsert(doc.id, doc.model_dump(mode="json"))
    return {"id": doc.id, "status": "saved", "type": "bug"}


async def memory_save_thought(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    content: str,
    category: str = "",
    related_files: list[str] | None = None,
    tags: list[str] | None = None,
    project_id: str = "default",
    source_session_id: str | None = None,
) -> dict:
    """Save a developer thought or observation."""
    project_id = _effective_project_id(db, project_id)
    doc = ThoughtDoc(
        content=content,
        category=category,
        related_files=related_files or [],
        tags=tags or [],
        project_id=project_id,
        source_session_id=source_session_id,
    )
    doc.embedding = _embed_text(provider, content)

    db.thoughts.upsert(doc.id, doc.model_dump(mode="json"))
    return {"id": doc.id, "status": "saved", "type": "thought"}


async def memory_save_pattern(
    db: CouchbaseClient,
    provider: EmbeddingProvider,
    title: str,
    description: str,
    code_example: str = "",
    use_cases: list[str] | None = None,
    language: str = "",
    tags: list[str] | None = None,
    project_id: str = "default",
    source_session_id: str | None = None,
) -> dict:
    """Save a recurring code pattern."""
    project_id = _effective_project_id(db, project_id)
    doc = PatternDoc(
        title=title,
        description=description,
        code_example=code_example,
        use_cases=use_cases or [],
        language=language,
        tags=tags or [],
        project_id=project_id,
        source_session_id=source_session_id,
    )
    embed_text = f"{title}\n{description}\n{code_example}"
    doc.embedding = _embed_text(provider, embed_text)

    db.patterns.upsert(doc.id, doc.model_dump(mode="json"))
    return {"id": doc.id, "status": "saved", "type": "pattern"}
