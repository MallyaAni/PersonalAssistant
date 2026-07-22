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
    # Per-form cap for the display snapshot; the full export path stays unbounded.
    MEMORY_SNAPSHOT_MAX_ITEMS: int = Field(default=500, ge=1, le=10_000)
    # Prior question/answer context and stored size for a coordinator turn budget.
    MEMORY_CONTEXT_MAX_ITEMS: int = Field(default=12, ge=1, le=100)
    MEMORY_CONTEXT_MAX_CHARS: int = Field(default=6_000, ge=500, le=100_000)

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
    # Prior question/answer pairs replayed to the VLM alongside the anchored image.
    VISION_THREAD_CONTEXT_TURNS: int = Field(default=8, ge=1, le=50)
    # Total question/answer pairs retained in one image's stored analysis thread.
    VISION_THREAD_MAX_STORED: int = Field(default=40, ge=1, le=500)

    # Local image embeddings (nomic-embed-vision-v1.5, ONNX, CPU in-process).
    # Aligned to nomic-embed-text-v1.5, so images and text share one 768-dim
    # space, one vector column, and one distance threshold.
    VISION_EMBEDDING_MODEL: str = "nomic-embed-vision-v1.5"
    VISION_EMBEDDING_MODEL_PATH: str = "data/models/nomic-embed-vision-v1.5/model.onnx"
    VISION_EMBEDDING_DIMENSION: int = Field(default=768, ge=1, le=2_000)
    VISION_EMBEDDING_THREADS: int = Field(default=1, ge=1, le=16)
    # Image search needs its own threshold. Cross-modal cosine similarity runs
    # an order of magnitude below text-text similarity (the modality gap), so
    # MEMORY_SEMANTIC_MAX_COSINE_DISTANCE would reject every image.
    # Calibrated against real generated images: correct matches landed at
    # 0.91-0.954 while irrelevant queries sat at 0.961+. Relevant queries
    # separate the right image from the wrong one by ~0.05, versus ~0.005 of
    # noise for unrelated queries, so the usable band is narrow and absolute.
    VISION_SEARCH_MAX_COSINE_DISTANCE: float = Field(default=0.96, ge=0, le=2)
    VISION_SEARCH_MAX_RESULTS: int = Field(default=10, ge=1, le=50)
    # Required gap between the best and second-best hit. Measured over 18
    # labelled queries: relevant queries showed a 0.0211 minimum margin,
    # unrelated ones a 0.0107 maximum, so 0.015 separates them cleanly.
    VISION_SEARCH_MIN_MARGIN: float = Field(default=0.015, ge=0, le=1)

    # Web search (Tavily HTTP API). Results are untrusted third-party content.
    SEARCH_PROVIDER_NAME: str = "tavily"
    SEARCH_BASE_URL: str = "https://api.tavily.com"
    # Empty disables search rather than failing startup; callers check is_enabled.
    SEARCH_API_KEY: str | None = Field(None, alias="SEARCH_API_KEY")
    SEARCH_MAX_RESULTS: int = Field(default=5, ge=1, le=20)
    SEARCH_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0, le=120)
    # Per-result truncation so one verbose page cannot dominate the prompt budget.
    SEARCH_MAX_CONTENT_CHARS: int = Field(default=2_000, ge=200, le=20_000)
    SEARCH_DEPTH: Literal["basic", "advanced"] = "basic"
    # Minimum provider relevance for a result to reach the prompt. Measured
    # across 40 real results the distribution is bimodal: usable hits scored
    # 0.561-0.923 while dictionary-definition noise scored 0.046-0.346, leaving
    # an empty band between. Feeding that noise in is worse than returning
    # nothing, because the prompt tells the model to prefer web results over its
    # own knowledge for time-sensitive facts.
    SEARCH_MIN_SCORE: float = Field(default=0.4, ge=0, le=1)

    # JWT Authentication
    SECRET_KEY: str = Field(..., alias="SECRET_KEY")
    AUTH_REQUIRED: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
