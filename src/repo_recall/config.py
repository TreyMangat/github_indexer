from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

AuthMode = Literal["disabled", "api_token"]


class Settings(BaseSettings):
    """Application settings loaded from env vars / .env.

    Keep this class small and explicit. Add new settings deliberately.

    Notes (PRFactory compatibility):
    - PRFactory defaults to local-friendly `MOCK_MODE=true` and `AUTH_MODE=disabled`.
    - When `AUTH_MODE=api_token`, PRFactory uses the `X-FF-Token` header.
      Repo Recall accepts either `X-FF-Token` or `Authorization: Bearer <token>`.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # --- Core ---
    app_env: str = Field(default="dev", alias="APP_ENV")
    mock_mode: bool = Field(default=False, alias="MOCK_MODE")

    database_url: str = Field(..., alias="DATABASE_URL")

    # --- Embeddings ---
    openai_api_key: Optional[str] = Field(default=None, alias="OPENAI_API_KEY")

    embedding_model: str = Field(default="text-embedding-3-small", alias="EMBEDDING_MODEL")
    # IMPORTANT: DB schema uses vector(1536) by default.
    # If you change EMBEDDING_DIM, you must also update schema.sql accordingly.
    embedding_dim: int = Field(default=1536, alias="EMBEDDING_DIM")

    # --- Indexing ---
    max_file_bytes: int = Field(default=800_000, alias="MAX_FILE_BYTES")
    max_chunk_chars: int = Field(default=8_000, alias="MAX_CHUNK_CHARS")
    chunk_overlap_lines: int = Field(default=20, alias="CHUNK_OVERLAP_LINES")

    repo_cache_dir: str = Field(default=".cache/repos", alias="REPO_CACHE_DIR")

    # --- API auth ---
    auth_mode: AuthMode = Field(default="disabled", alias="AUTH_MODE")
    api_auth_token: Optional[str] = Field(default=None, alias="API_AUTH_TOKEN")

    # --- Service behavior ---
    init_db_on_startup: bool = Field(default=True, alias="INIT_DB_ON_STARTUP")
    enable_ui: bool = Field(default=True, alias="ENABLE_UI")

    # Background job runner for UI-triggered indexing.
    job_workers: int = Field(default=1, alias="JOB_WORKERS")

    # --- Security ---
    enable_secret_redaction: bool = Field(default=True, alias="ENABLE_SECRET_REDACTION")

    # --- GitHub catalog ---
    enable_catalog: bool = Field(default=True, alias="ENABLE_CATALOG")
    github_api_base_url: str = Field(default="https://api.github.com", alias="GITHUB_API_BASE_URL")
    github_webhook_secret: Optional[str] = Field(default=None, alias="GITHUB_WEBHOOK_SECRET")
    github_connect_url_template: str = Field(
        default="/connect/github?actor_id={actor_id}",
        alias="GITHUB_CONNECT_URL_TEMPLATE",
    )
    github_token_broker_url: Optional[str] = Field(
        default=None,
        alias="GITHUB_TOKEN_BROKER_URL",
    )
    github_token_broker_auth_token: Optional[str] = Field(
        default=None,
        alias="GITHUB_TOKEN_BROKER_AUTH_TOKEN",
    )
    catalog_sync_interval_seconds: int = Field(
        default=3600,
        alias="CATALOG_SYNC_INTERVAL_SECONDS",
    )
    catalog_repo_page_size: int = Field(default=100, alias="CATALOG_REPO_PAGE_SIZE")
    catalog_branch_page_size: int = Field(default=100, alias="CATALOG_BRANCH_PAGE_SIZE")
    catalog_request_timeout_seconds: float = Field(
        default=20.0,
        alias="CATALOG_REQUEST_TIMEOUT_SECONDS",
    )
    enable_catalog_dev_endpoints: bool = Field(
        default=False,
        alias="ENABLE_CATALOG_DEV_ENDPOINTS",
    )

    def repo_cache_path(self) -> Path:
        return Path(self.repo_cache_dir).expanduser().resolve()


def get_settings() -> Settings:
    # Settings are populated from environment variables / .env at runtime.
    # Mypy doesn't understand pydantic-settings' env loading, so we ignore the
    # missing required field error here.
    return Settings()  # type: ignore[call-arg]
