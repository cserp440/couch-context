"""Tests for Pydantic models."""

import pytest

from cb_memory.models import (
    BugDoc,
    DecisionDoc,
    MessageDoc,
    PatternDoc,
    SessionDoc,
    SummaryDoc,
    ThoughtDoc,
)


def test_session_doc_creation():
    """Test SessionDoc creation and defaults."""
    session = SessionDoc(
        title="Test Session",
        project_id="test-project",
    )
    assert session.title == "Test Session"
    assert session.project_id == "test-project"
    assert session.id.startswith("session::")
    assert session.message_count == 0
    assert session.type == "session"


def test_message_doc_id_generation():
    """Test MessageDoc ID generation."""
    msg = MessageDoc(
        session_id="session::abc123",
        role="user",
        text_content="Hello",
    )
    msg.generate_id()
    assert msg.id.startswith("msg::abc123::")


def test_summary_doc_id_generation():
    """Test SummaryDoc ID generation."""
    summary = SummaryDoc(
        session_id="session::xyz789",
        summary="This was a productive session",
    )
    summary.generate_id()
    assert summary.id == "summary::xyz789"


def test_decision_doc_creation():
    """Test DecisionDoc with all fields."""
    decision = DecisionDoc(
        title="Use PostgreSQL for database",
        description="We need a relational database",
        category="architecture",
        alternatives=["MySQL", "SQLite"],
        consequences=["Need to learn PostgreSQL"],
        project_id="test-project",
    )
    assert decision.id.startswith("decision::")
    assert decision.type == "decision"
    assert len(decision.alternatives) == 2


def test_bug_doc_severity():
    """Test BugDoc default severity."""
    bug = BugDoc(
        title="Null pointer exception",
        description="App crashes on startup",
    )
    assert bug.severity == "medium"
    assert bug.id.startswith("bug::")


def test_thought_doc_creation():
    """Test ThoughtDoc."""
    thought = ThoughtDoc(
        content="This code needs refactoring",
        category="concern",
    )
    assert thought.id.startswith("thought::")
    assert thought.type == "thought"


def test_pattern_doc_creation():
    """Test PatternDoc."""
    pattern = PatternDoc(
        title="Singleton Pattern",
        description="Ensure only one instance",
        language="python",
    )
    assert pattern.id.startswith("pattern::")
    assert pattern.language == "python"
