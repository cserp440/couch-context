"""Configuration loaded from environment variables."""

from __future__ import annotations

import json
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import Field

# Load .env from project root (two levels up from this file)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(_env_path)


class Settings(BaseSettings):
    # Couchbase
    cb_connection_string: str = Field(default="couchbase://localhost")
    cb_username: str = Field(default="Administrator")
    cb_password: str = Field(default="password")
    cb_bucket: str = Field(default="coding-memory")

    # Embeddings
    openai_api_key: str | None = Field(default=None)
    openai_embedding_model: str = Field(default="text-embedding-3-small")
    openai_embedding_dims: int = Field(default=1536)

    ollama_host: str = Field(default="http://localhost:11434")
    ollama_embedding_model: str = Field(default="nomic-embed-text")
    ollama_embedding_dims: int = Field(default=768)

    # General
    default_project_id: str = Field(default="default")
    current_project_id: str | None = Field(default_factory=lambda: str(Path.cwd().resolve()))
    include_all_projects_by_default: bool = Field(default=True)
    default_related_projects: str = Field(default="")
    auto_import_claude_on_start: bool = Field(default=True)
    auto_import_claude_path: str = Field(default_factory=lambda: str(Path.home() / ".claude/projects"))
    auto_import_codex_on_start: bool = Field(default=True)
    auto_import_codex_path: str = Field(default_factory=lambda: str(Path.home() / ".codex"))
    auto_import_factory_on_start: bool = Field(default=True)
    auto_import_factory_path: str = Field(default_factory=lambda: str(Path.home() / ".factory" / "sessions"))
    auto_import_on_query: bool = Field(default=True)
    auto_import_min_interval_seconds: int = Field(default=45)

    model_config = {"env_prefix": "", "case_sensitive": False}

    @property
    def embedding_provider(self) -> str:
        """Return 'openai' if API key is set, else 'ollama'."""
        if self.openai_api_key:
            return "openai"
        return "ollama"

    @property
    def embedding_dims(self) -> int:
        if self.embedding_provider == "openai":
            return self.openai_embedding_dims
        return self.ollama_embedding_dims

    @property
    def default_related_project_ids(self) -> list[str]:
        """Return normalized default related projects from env config.

        Supports either a comma-separated string or a JSON array string.
        """
        raw = (self.default_related_projects or "").strip()
        if not raw:
            return []

        values: list[str]
        if raw.startswith("["):
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    values = [str(v).strip() for v in parsed if str(v).strip()]
                else:
                    values = []
            except Exception:
                values = []
        else:
            values = [part.strip() for part in raw.split(",") if part.strip()]

        if not values:
            return []

        from cb_memory.project import normalize_project_ids

        return normalize_project_ids(values)


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
