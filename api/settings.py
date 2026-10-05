"""
api/settings.py

settings.py is the safe, typed, validated configuration brain of the HealthOS backend.

Application configuration loaded from environment variables.

This module defines the Settings object used by the FastAPI app and by
infrastructure components (database, logging, etc.). It is intentionally kept
small and explicit so configuration remains easy to audit and safe for a
healthcare MVP.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Literal, Optional, Self

from pydantic import Field, computed_field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

OrchestratorCheckpointBackend = Literal["postgres", "memory"]

# FHIR adapter kind (generic HAPI vs the synthetic example EHR bundle)
FhirAdapterKind = Literal["generic", "example"]

# Repo root (parent of `api/`) so `.env` resolves correctly regardless of cwd.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_cors_allow_origins(raw: str) -> List[str]:
    """
    Turn CORS_ALLOW_ORIGINS env text into a list of origin URLs.

    Comma-separated values are typical in .env files; JSON arrays are also accepted
    so production can use machine-friendly structured config without changing code.
    """
    text = raw.strip()
    if not text:
        return ["http://localhost:3000", "http://127.0.0.1:3000"]
    if text.startswith("["):
        parsed = json.loads(text)
        if not isinstance(parsed, list):
            raise ValueError(
                "CORS_ALLOW_ORIGINS must be a JSON array when using JSON syntax"
            )
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in text.split(",") if part.strip()]


class Settings(BaseSettings):
    """
    Central configuration for the HealthOS API.

    Values are loaded from environment variables and optionally from an .env file.
    Instantiation raises ``ValidationError`` if required secrets or DB settings are missing.
    """

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---- App identity ----
    app_name: str = Field(default="HealthOS API", validation_alias="APP_NAME")
    env: str = Field(default="local", validation_alias="ENV")
    service_version: str = Field(default="0.1.0", validation_alias="SERVICE_VERSION")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    # ---- CORS ----
    # Stored as plain str so pydantic-settings does not json.loads() the env value (breaks comma lists).
    cors_allow_origins_env: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias="CORS_ALLOW_ORIGINS",
    )

    @computed_field
    @property
    def cors_allow_origins(self) -> List[str]:
        """
        Origins permitted by CORS middleware, parsed from cors_allow_origins_env.
        """
        return parse_cors_allow_origins(self.cors_allow_origins_env)

    # ---- Database ----
    postgres_host: str = Field(default="localhost", validation_alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, validation_alias="POSTGRES_PORT")
    postgres_db: str = Field(default="healthos", validation_alias="POSTGRES_DB")
    postgres_user: str = Field(default="healthos", validation_alias="POSTGRES_USER")
    postgres_password: Optional[str] = Field(
        default=None, validation_alias="POSTGRES_PASSWORD"
    )

    # Optional: allow a full URL override (useful in Docker/CI)
    database_url: Optional[str] = Field(default=None, validation_alias="DATABASE_URL")

    def get_async_database_url(self) -> str:
        """
        Return the SQLAlchemy async database URL.

        Prefers DATABASE_URL if provided; otherwise builds from POSTGRES_* vars.
        """
        if self.database_url:
            # Caller must ensure it is an async URL (postgresql+asyncpg://...)
            return self.database_url.strip()

        password = self.postgres_password
        assert password is not None and password.strip()
        return (
            "postgresql+asyncpg://"
            f"{self.postgres_user}:{password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    def get_checkpoint_conninfo(self) -> str:
        """
        Connection string for LangGraph ``AsyncPostgresSaver`` (psycopg3 / libpq).

        Async SQLAlchemy uses ``postgresql+asyncpg://``; psycopg expects ``postgresql://``.
        """
        raw = self.get_async_database_url().strip()
        for prefix, replacement in (
            ("postgresql+asyncpg://", "postgresql://"),
            ("postgres+asyncpg://", "postgresql://"),
        ):
            if raw.startswith(prefix):
                return replacement + raw[len(prefix) :]
        if raw.startswith("postgresql://") or raw.startswith("postgres://"):
            return raw
        raise ValueError(
            "DATABASE_URL must be a PostgreSQL URL for checkpoint persistence"
        )

    # ---- Redis (sessions, Celery broker, pub/sub) ----
    redis_url: str = Field(
        default="redis://localhost:6379/0", validation_alias="REDIS_URL"
    )

    #: Secret for signing the session cookie (value is only a session id; payload lives in Redis).
    session_secret_key: str = Field(
        ...,
        min_length=32,
        validation_alias="SESSION_SECRET_KEY",
    )

    #: HS256 signing key for JWT access + refresh tokens (separate from session cookie secret).
    jwt_secret_key: str = Field(..., min_length=32, validation_alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", validation_alias="JWT_ALGORITHM")
    jwt_access_expire_minutes: int = Field(
        default=30, validation_alias="JWT_ACCESS_EXPIRE_MINUTES"
    )
    jwt_refresh_expire_days: int = Field(
        default=7, validation_alias="JWT_REFRESH_EXPIRE_DAYS"
    )

    #: Orchestrator token ceiling per task (Section C — checklist #33).
    orchestrator_token_budget_default: int = Field(
        default=32_000,
        validation_alias="ORCHESTRATOR_TOKEN_BUDGET_DEFAULT",
    )
    #: OpenRouter model ids for primary vs fallback routing.
    orchestrator_llm_primary_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="ORCHESTRATOR_LLM_PRIMARY_MODEL",
    )
    orchestrator_llm_fallback_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="ORCHESTRATOR_LLM_FALLBACK_MODEL",
    )
    #: Transient transport retries before fallback model (#31).
    orchestrator_max_transient_retries: int = Field(
        default=3,
        validation_alias="ORCHESTRATOR_MAX_TRANSIENT_RETRIES",
    )
    #: LangGraph checkpoint store: ``postgres`` for durable resume (production); ``memory`` for CI/pytest.
    orchestrator_checkpoint_backend: OrchestratorCheckpointBackend = Field(
        default="postgres",
        validation_alias="HEALTHOS_ORCHESTRATOR_CHECKPOINTER",
    )

    session_cookie_name: str = Field(
        default="healthos_session", validation_alias="SESSION_COOKIE_NAME"
    )
    session_max_age_seconds: int = Field(
        default=14 * 24 * 60 * 60, validation_alias="SESSION_MAX_AGE_SECONDS"
    )
    session_cookie_path: str = Field(
        default="/", validation_alias="SESSION_COOKIE_PATH"
    )
    session_cookie_same_site: Literal["lax", "strict", "none"] = Field(
        default="lax",
        validation_alias="SESSION_COOKIE_SAMESITE",
    )
    session_cookie_secure: bool = Field(
        default=False, validation_alias="SESSION_COOKIE_SECURE"
    )
    session_cookie_domain: Optional[str] = Field(
        default=None, validation_alias="SESSION_COOKIE_DOMAIN"
    )

    #: Override Celery broker if you use a different Redis DB or host than `redis_url`.
    celery_broker_url: Optional[str] = Field(
        default=None, validation_alias="CELERY_BROKER_URL"
    )
    celery_result_backend: Optional[str] = Field(
        default=None, validation_alias="CELERY_RESULT_BACKEND"
    )

    @computed_field
    @property
    def resolved_celery_broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @computed_field
    @property
    def resolved_celery_result_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    # ---- Weaviate (vector store / RAG) ----
    #: HTTP API host (Compose maps REST to host port 8080 by default).
    weaviate_http_host: str = Field(
        default="localhost", validation_alias="WEAVIATE_HTTP_HOST"
    )
    weaviate_http_port: int = Field(default=8080, validation_alias="WEAVIATE_HTTP_PORT")
    weaviate_http_secure: bool = Field(
        default=False, validation_alias="WEAVIATE_HTTP_SECURE"
    )
    #: gRPC host/port for weaviate-client v4 (Compose should map container 50051 to host 50051).
    weaviate_grpc_host: str = Field(
        default="localhost", validation_alias="WEAVIATE_GRPC_HOST"
    )
    weaviate_grpc_port: int = Field(
        default=50051, validation_alias="WEAVIATE_GRPC_PORT"
    )
    weaviate_grpc_secure: bool = Field(
        default=False, validation_alias="WEAVIATE_GRPC_SECURE"
    )
    #: Dev-only escape hatch if gRPC is blocked; prefer fixing firewall / Compose ports.
    weaviate_skip_init_checks: bool = Field(
        default=False, validation_alias="WEAVIATE_SKIP_INIT_CHECKS"
    )
    weaviate_init_timeout_seconds: int = Field(
        default=30, validation_alias="WEAVIATE_INIT_TIMEOUT_SECONDS"
    )

    # ---- OpenRouter (OpenAI-compatible Chat Completions) ----
    #: Primary secret for OpenRouter — alias ``OPENROUTER_API_KEY``.
    openrouter_api_key: Optional[str] = Field(
        default=None, validation_alias="OPENROUTER_API_KEY"
    )
    xai_api_key: Optional[str] = Field(default=None, validation_alias="XAI_API_KEY")
    #: Base URL without trailing path, e.g. ``https://openrouter.ai/api/v1``
    openrouter_api_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias="OPENROUTER_API_BASE_URL",
    )

    @field_validator("openrouter_api_base_url", mode="before")
    @classmethod
    def normalize_openrouter_api_base_url(cls, v: object) -> object:
        if not isinstance(v, str):
            return v
        value = v.strip()
        if value.endswith("/"):
            value = value.rstrip("/")
        if value in ("https://openrouter.ai", "https://openrouter.ai/"):
            return "https://openrouter.ai/api/v1"
        if value == "https://openrouter.ai/v1":
            return "https://openrouter.ai/api/v1"
        if value.startswith("https://openrouter.ai/v1/"):
            return (
                "https://openrouter.ai/api/v1"
                + value[len("https://openrouter.ai/v1") :]
            )
        return value

    #: Tier → OpenRouter ``model`` parameter (ids depend on your plan; override via env).
    openrouter_model_dev: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="OPENROUTER_MODEL_DEV",
    )
    openrouter_model_production: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="OPENROUTER_MODEL_PRODUCTION",
    )
    openrouter_model_demo: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="OPENROUTER_MODEL_DEMO",
    )

    # ---- Clinical Documentation Agent (Section D) ----
    documentation_max_upload_mb: int = Field(
        default=50,
        validation_alias="DOCUMENTATION_MAX_UPLOAD_MB",
    )
    documentation_soap_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="DOCUMENTATION_SOAP_MODEL",
    )
    documentation_discharge_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="DOCUMENTATION_DISCHARGE_MODEL",
    )
    documentation_referral_model: str = Field(
        default="meta-llama/llama-3.1-8b-instruct",
        validation_alias="DOCUMENTATION_REFERRAL_MODEL",
    )
    documentation_max_completion_tokens: int = Field(
        default=4096,
        validation_alias="DOCUMENTATION_MAX_COMPLETION_TOKENS",
    )
    whisper_model_name: str = Field(
        default="base",
        validation_alias="WHISPER_MODEL_NAME",
    )

    # ---- Langfuse (OSS self-hosted observability; P0#12) ----
    #: Ingestion + UI for self-hosted stack (``docker compose ... docker-compose.langfuse.yml``).
    langfuse_public_key: Optional[str] = Field(
        default=None, validation_alias="LANGFUSE_PUBLIC_KEY"
    )
    langfuse_secret_key: Optional[str] = Field(
        default=None, validation_alias="LANGFUSE_SECRET_KEY"
    )
    langfuse_base_url: str = Field(
        default="http://127.0.0.1:3000",
        validation_alias="LANGFUSE_BASE_URL",
    )

    # ---- FHIR (HAPI / example EHR adapter / SMART) ----
    #: Base URL for FHIR R4 HTTP API (trailing slash optional). Used by ``api/fhir`` integration routes.
    hapi_fhir_base_url: str = Field(
        default="http://localhost:8082/fhir",
        validation_alias="HAPI_FHIR_BASE_URL",
    )
    fhir_adapter_kind: FhirAdapterKind = Field(
        default="generic",
        validation_alias="FHIR_ADAPTER_KIND",
    )
    #: Shared secret for inbound Subscription ``rest-hook`` notifications (optional).
    fhir_webhook_secret: Optional[str] = Field(
        default=None, validation_alias="FHIR_WEBHOOK_SECRET"
    )
    #: Public base URL of this API (no path), used when registering Subscriptions with HAPI.
    healthos_public_base_url: str = Field(
        default="http://127.0.0.1:8000",
        validation_alias="HEALTHOS_PUBLIC_BASE_URL",
    )
    #: SMART on FHIR OAuth2 client (optional until EHR embedding).
    smart_client_id: Optional[str] = Field(
        default=None, validation_alias="SMART_CLIENT_ID"
    )
    smart_client_secret: Optional[str] = Field(
        default=None, validation_alias="SMART_CLIENT_SECRET"
    )
    smart_redirect_uri: Optional[str] = Field(
        default=None, validation_alias="SMART_REDIRECT_URI"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def empty_str_database_url_to_none(cls, v: object) -> object:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator(
        "postgres_password", "session_secret_key", "jwt_secret_key", mode="before"
    )
    @classmethod
    def strip_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @field_validator(
        "orchestrator_llm_primary_model",
        "orchestrator_llm_fallback_model",
        "openrouter_model_dev",
        "openrouter_model_production",
        "openrouter_model_demo",
        "documentation_soap_model",
        "documentation_discharge_model",
        "documentation_referral_model",
        mode="before",
    )
    @classmethod
    def strip_model_whitespace(cls, v: object) -> object:
        if isinstance(v, str):
            return v.strip()
        return v

    @model_validator(mode="after")
    def require_database_credentials(self) -> Self:
        """
        Either ``DATABASE_URL`` must be set, or ``POSTGRES_PASSWORD`` when building URL from parts.
        """
        if self.database_url:
            return self
        pwd = self.postgres_password
        if pwd is None or not str(pwd).strip():
            raise ValueError(
                "Database configuration incomplete: set DATABASE_URL, or set POSTGRES_PASSWORD "
                "(with POSTGRES_HOST/POSTGRES_DB/POSTGRES_USER as needed)."
            )
        return self

    #: When true, allows ``/llm/*`` playground routes even if ``ENV`` is not local/dev.
    llm_playground_enabled: bool = Field(
        default=False, validation_alias="LLM_PLAYGROUND_ENABLED"
    )

    @computed_field
    @property
    def resolved_openrouter_api_key(self) -> Optional[str]:
        """Prefer explicit OpenRouter key; fall back to legacy xAI key."""
        return self.openrouter_api_key or self.xai_api_key

    @computed_field
    @property
    def llm_playground_allowed(self) -> bool:
        """Whether FastAPI should expose ``/llm`` smoke-test routes."""
        if self.llm_playground_enabled:
            return True
        return self.env.lower() in ("local", "dev", "development")

    @computed_field
    @property
    def langfuse_tracing_enabled(self) -> bool:
        """Send LLM observations when both project API keys are set."""
        pub = (self.langfuse_public_key or "").strip()
        sec = (self.langfuse_secret_key or "").strip()
        return bool(pub and sec)
