from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # App Configuration
    APP_NAME: str = "AniOS"
    DEBUG: bool = False
    PORT: int = 8000

    # Database - PostgreSQL with pgvector
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "anios_db"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    DATABASE_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    DATABASE_MAX_OVERFLOW: int = Field(default=5, ge=0, le=50)
    DATABASE_POOL_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=300)
    DATABASE_USE_NULL_POOL: bool = False

    # AI / LLM (LM Studio OpenAI-compatible chat completions API)
    LLM_BASE_URL: str = "http://127.0.0.1:1234"
    LLM_MODEL: str = "google/gemma-4-12b"
    LLM_API_KEY: str | None = Field(None, alias="LLM_API_KEY")
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"

    # Semantic memory embeddings (LM Studio OpenAI-compatible endpoint)
    EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v1.5"
    EMBEDDING_MODEL_VERSION: str = "nomic-embed-text-v1.5"
    EMBEDDING_DIMENSION: int = Field(default=768, ge=1, le=2_000)
    EMBEDDING_MAX_CONCURRENCY: int = Field(default=1, ge=1, le=32)
    MEMORY_SEMANTIC_MAX_COSINE_DISTANCE: float = Field(default=0.35, ge=0, le=2)
    MEMORY_SEMANTIC_MAX_RESULTS: int = Field(default=5, ge=1, le=20)
    MEMORY_SEMANTIC_MAX_CONTENT_CHARS: int = Field(default=4_000, ge=100, le=50_000)
    CONVERSATION_HISTORY_TURNS: int = Field(default=10, ge=0, le=50)
    CONVERSATION_SUMMARY_INTERVAL: int = Field(default=10, ge=2, le=100)

    # Local visual generation and binary artifact storage
    IMAGE_PROVIDER_BASE_URL: str = "http://127.0.0.1:8188"
    IMAGE_PROVIDER_NAME: str = "comfyui"
    IMAGE_MODEL: str = "hidream_o1_image_dev_fp8_scaled.safetensors"
    IMAGE_PROVIDER_TIMEOUT_SECONDS: float = Field(default=600.0, gt=0, le=3600)
    IMAGE_PROVIDER_POLL_SECONDS: float = Field(default=0.5, ge=0.1, le=10)
    IMAGE_MAX_CONCURRENCY: int = Field(default=1, ge=1, le=4)
    ARTIFACT_STORAGE_ROOT: str = "data/artifacts"
    IMAGE_MAX_UPLOAD_BYTES: int = Field(
        default=10 * 1024 * 1024,
        ge=1024,
        le=100 * 1024 * 1024,
    )
    IMAGE_MAX_OUTPUT_BYTES: int = Field(
        default=40 * 1024 * 1024,
        ge=1024,
        le=200 * 1024 * 1024,
    )
    IMAGE_MAX_PIXELS: int = Field(default=20_000_000, ge=4096, le=100_000_000)
    VISION_MODEL: str = "google/gemma-4-12b"
    VISION_MAX_TOKENS: int = Field(default=512, ge=32, le=4096)

    # JWT Authentication
    SECRET_KEY: str = Field(..., alias="SECRET_KEY")
    AUTH_REQUIRED: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
