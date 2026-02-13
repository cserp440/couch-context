"""Pydantic models for all document types stored in Couchbase."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field
import ulid


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ulid() -> str:
    if hasattr(ulid, "new"):
        return str(ulid.new())
    # python-ulid exposes ULID class constructor.
    if hasattr(ulid, "ULID"):
        return str(ulid.ULID())
    raise RuntimeError("No ULID generator available")


# ---------------------------------------------------------------------------
# Conversations scope
# ---------------------------------------------------------------------------


class SessionDoc(BaseModel):
    """Metadata for a coding session (conversations.sessions)."""

    id: str = Field(default_factory=lambda: f"session::{_ulid()}")
    title: str = ""
    project_id: str = "default"
    directory: str = ""
    source: str = ""  # e.g. "opencode", "claude-code", "manual"
    message_count: int = 0
    tools_used: list[str] = Field(default_factory=list)
    files_modified: list[str] = Field(default_factory=list)
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=_now)
    ended_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "session"


class MessageDoc(BaseModel):
    """A single message within a session (conversations.messages)."""

    id: str = ""
    session_id: str = ""
    project_id: str = "default"
    role: str = ""  # "user", "assistant", "system", "tool"
    text_content: str = ""
    raw_content: dict | list | str | None = None
    tool_calls: list[dict] = Field(default_factory=list)
    tool_results: list[dict] = Field(default_factory=list)
    message_group_id: str = ""
    chunk_index: int = 0
    chunk_count: int = 1
    original_sequence_number: int = 0
    timestamp: datetime = Field(default_factory=_now)
    sequence_number: int = 0
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "message"

    def generate_id(self) -> str:
        session_part = self.session_id.removeprefix("session::")
        self.id = f"msg::{session_part}::{_ulid()}"
        return self.id


class SummaryDoc(BaseModel):
    """AI-generated summary of a session (conversations.summaries)."""

    id: str = ""
    session_id: str = ""
    summary: str = ""
    key_decisions: list[str] = Field(default_factory=list)
    key_files: list[str] = Field(default_factory=list)
    key_topics: list[str] = Field(default_factory=list)
    outcome: str = ""
    project_id: str = "default"
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "summary"

    def generate_id(self) -> str:
        session_part = self.session_id.removeprefix("session::")
        self.id = f"summary::{session_part}"
        return self.id


# ---------------------------------------------------------------------------
# Knowledge scope
# ---------------------------------------------------------------------------


class DecisionDoc(BaseModel):
    """An architectural or coding decision (knowledge.decisions)."""

    id: str = Field(default_factory=lambda: f"decision::{_ulid()}")
    title: str = ""
    description: str = ""
    category: str = ""  # e.g. "architecture", "library-choice", "api-design"
    context: str = ""
    alternatives: list[str] = Field(default_factory=list)
    consequences: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    project_id: str = "default"
    source_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "decision"


class BugDoc(BaseModel):
    """A bug report and its fix (knowledge.bugs)."""

    id: str = Field(default_factory=lambda: f"bug::{_ulid()}")
    title: str = ""
    description: str = ""
    root_cause: str = ""
    fix_description: str = ""
    files_affected: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    severity: str = "medium"  # "low", "medium", "high", "critical"
    tags: list[str] = Field(default_factory=list)
    project_id: str = "default"
    source_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "bug"


class ThoughtDoc(BaseModel):
    """A developer note or observation (knowledge.thoughts)."""

    id: str = Field(default_factory=lambda: f"thought::{_ulid()}")
    content: str = ""
    category: str = ""  # e.g. "observation", "idea", "concern", "todo"
    related_files: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    project_id: str = "default"
    source_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "thought"


class PatternDoc(BaseModel):
    """A recurring code pattern (knowledge.patterns)."""

    id: str = Field(default_factory=lambda: f"pattern::{_ulid()}")
    title: str = ""
    description: str = ""
    code_example: str = ""
    use_cases: list[str] = Field(default_factory=list)
    language: str = ""
    tags: list[str] = Field(default_factory=list)
    project_id: str = "default"
    source_session_id: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)
    embedding: Optional[list[float]] = None
    type: str = "pattern"
