"""Embedding generation — OpenAI primary, Ollama fallback."""

from __future__ import annotations

import logging
from typing import Optional

from cb_memory.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Maximum tokens for OpenAI text-embedding-3-small input
_OPENAI_MAX_TOKENS = 8191
_OPENAI_BATCH_SIZE = 100


class EmbeddingProvider:
    """Generates embeddings using OpenAI or Ollama."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._openai_client = None
        self._ollama_client = None

    @property
    def provider(self) -> str:
        return self._settings.embedding_provider

    @property
    def dims(self) -> int:
        return self._settings.embedding_dims

    # -- OpenAI ---------------------------------------------------------------

    def _get_openai(self):
        if self._openai_client is None:
            from openai import OpenAI
            self._openai_client = OpenAI(api_key=self._settings.openai_api_key)
        return self._openai_client

    def _embed_openai(self, texts: list[str]) -> list[list[float]]:
        client = self._get_openai()
        # Truncate texts that are too long (rough char-based approximation)
        truncated = [t[: _OPENAI_MAX_TOKENS * 4] for t in texts]
        results: list[list[float]] = []
        for i in range(0, len(truncated), _OPENAI_BATCH_SIZE):
            batch = truncated[i : i + _OPENAI_BATCH_SIZE]
            resp = client.embeddings.create(
                input=batch,
                model=self._settings.openai_embedding_model,
            )
            results.extend([d.embedding for d in resp.data])
        return results

    # -- Ollama ---------------------------------------------------------------

    def _get_ollama(self):
        if self._ollama_client is None:
            import ollama as _ollama
            self._ollama_client = _ollama.Client(host=self._settings.ollama_host)
        return self._ollama_client

    def _embed_ollama(self, texts: list[str]) -> list[list[float]]:
        client = self._get_ollama()
        results: list[list[float]] = []
        for text in texts:
            resp = client.embed(
                model=self._settings.ollama_embedding_model,
                input=text,
            )
            results.append(resp["embeddings"][0])
        return results

    # -- Public API -----------------------------------------------------------

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of texts.

        Uses OpenAI if OPENAI_API_KEY is set, otherwise falls back to Ollama.
        """
        if not texts:
            return []

        if self.provider == "openai":
            try:
                return self._embed_openai(texts)
            except Exception:
                logger.warning("OpenAI embedding failed, falling back to Ollama")
                return self._embed_ollama(texts)
        else:
            return self._embed_ollama(texts)

    def embed_one(self, text: str) -> list[float]:
        """Generate a single embedding."""
        return self.embed([text])[0]


# Module-level convenience
_provider: Optional[EmbeddingProvider] = None


def get_embedding_provider(settings: Optional[Settings] = None) -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = EmbeddingProvider(settings)
    return _provider
