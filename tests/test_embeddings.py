"""Tests for embedding generation."""

import pytest

from cb_memory.config import Settings
from cb_memory.embeddings import EmbeddingProvider


@pytest.fixture
def settings_openai():
    """Settings with OpenAI configured."""
    return Settings(
        openai_api_key="test-key",
        cb_connection_string="couchbase://localhost",
        cb_username="admin",
        cb_password="password",
    )


@pytest.fixture
def settings_ollama():
    """Settings with Ollama only."""
    return Settings(
        openai_api_key=None,
        cb_connection_string="couchbase://localhost",
        cb_username="admin",
        cb_password="password",
    )


def test_provider_selection_openai(settings_openai):
    """Test that OpenAI is selected when API key is present."""
    provider = EmbeddingProvider(settings_openai)
    assert provider.provider == "openai"
    assert provider.dims == 1536


def test_provider_selection_ollama(settings_ollama):
    """Test that Ollama is selected when no OpenAI key."""
    provider = EmbeddingProvider(settings_ollama)
    assert provider.provider == "ollama"
    assert provider.dims == 768


# Note: These tests would require actual API calls or mocking
# For now, they demonstrate the test structure
