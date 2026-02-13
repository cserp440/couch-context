"""Tests for MCP tools."""

import pytest

from cb_memory.models import DecisionDoc


@pytest.mark.asyncio
async def test_memory_save_decision_structure():
    """Test the structure of a saved decision (unit test, no DB)."""
    doc = DecisionDoc(
        title="Test Decision",
        description="This is a test",
        category="test",
    )
    assert doc.title == "Test Decision"
    assert doc.category == "test"
    assert doc.id.startswith("decision::")


# Integration tests would require a running Couchbase instance
# These can be added later with proper fixtures and setup
