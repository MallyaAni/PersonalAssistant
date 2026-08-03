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

    # Provider-neutral inference selects a wire adapter independently from each
    # role's endpoint and model. vLLM is the qualified local runtime.
    INFERENCE_ADAPTER: Literal["openai_compatible"] = "openai_compatible"
    INFERENCE_PROVIDER_NAME: str = "vllm"
    LLM_BASE_URL: str = "http://127.0.0.1:8003"
    LLM_MODEL: str = "qwen/qwen3.5-4b"
    LLM_API_KEY: str | None = Field(None, alias="LLM_API_KEY")
    LLM_TIMEOUT_SECONDS: float = 120.0
    LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    # Role-specific models fall back to the legacy LLM settings so existing
    # installations keep working while operators qualify specialized models.
    MAIN_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    MAIN_LLM_BASE_URL: str = ""
    MAIN_LLM_MODEL: str = ""
    MAIN_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    PRESENTATION_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    PRESENTATION_LLM_BASE_URL: str = ""
    PRESENTATION_LLM_MODEL: str = ""
    PRESENTATION_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    DIAGRAM_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    DIAGRAM_LLM_BASE_URL: str = ""
    DIAGRAM_LLM_MODEL: str = ""
    DIAGRAM_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"

    VISION_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    EMBEDDING_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    # Semantic memory embeddings use their own replaceable role configuration.
    EMBEDDING_BASE_URL: str = ""
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
    IMAGE_EDIT_MODEL: str = "flux-2-klein-4b-fp8.safetensors"
    IMAGE_EDIT_TEXT_ENCODER: str = "qwen_3_4b.safetensors"
    IMAGE_EDIT_VAE: str = "flux2-vae.safetensors"
    IMAGE_EDIT_STEPS: int = Field(default=4, ge=1, le=100)
    # Realism steering. HiDream-O1 runs distilled at cfg=1.0, where a negative
    # prompt is inert, so photorealism is driven by appending this to the
    # positive prompt. It is added only when not already present; set it empty to
    # send the user's prompt verbatim.
    # Realism comes from imperfection, not from asking for quality. The previous
    # suffix asked for "sharp focus, high detail, 4k, professional photography",
    # which are the exact terms that produce the glossy retouched stock-photo
    # look people read as AI. Naming a film stock, available light, and explicit
    # flaws produces skin with pores and fine lines, uneven light, and unstyled
    # props instead. Compared side by side on a fixed seed, this suffix was the
    # only one of three that read as a candid photograph.
    # Subject-agnostic only. This is appended to every prompt, so anything
    # naming a body part describes a subject the request may not have asked
    # for: "skin with pores and fine lines, flyaway hair" used to live here and
    # put a person in every image, which is how a request for a car returned a
    # woman leaning out of one. Film stock, lens, light, and framing apply to a
    # car and a face alike; skin and hair do not.
    IMAGE_STYLE_SUFFIX: str = (
        "candid snapshot, shot on 35mm film, Kodak Portra 400, 50mm lens, "
        "available light only, uneven mixed lighting, visible film grain, "
        "slightly off-centre imperfect framing, mild motion blur, "
        "everyday unstyled scene"
    )
    # The human half of the tuned look, added only when the request is about a
    # person. Keeping it out of the global suffix is what stops it inventing
    # subjects; keeping it at all is what preserves the portrait quality it was
    # originally tuned for.
    IMAGE_PORTRAIT_SUFFIX: str = (
        "natural unretouched skin with pores and fine lines, flyaway hair"
    )
    # Steers away from the CGI look without forbidding any subject. Naming
    # "person" here would break every portrait, so it names rendering styles
    # rather than content.
    IMAGE_NEGATIVE_PROMPT: str = (
        "3d render, cgi, illustration, painting, cartoon, anime, plastic, "
        "airbrushed, oversaturated, watermark, text, logo"
    )
    # A single GPU cannot hold the generation model and the diffusion model at
    # once. When enabled, AniOS sleeps local inference for the duration of one
    # image job so the diffusion runtime stops streaming weights from host RAM.
    # Level 1 offloads weights to CPU memory; level 2 discards them entirely.
    #
    # Off because it measured slower, not because it does not work. Sleeping and
    # waking are verified against the shipped runtime, but a full offload/reload
    # round trip per image cost more than it saved: 47/64/42 s with the handoff
    # against 37/35 s without it, because ComfyUI already manages its own
    # residency. Enable it only if a future model makes the two runtimes
    # genuinely unable to share the card, and re-measure before trusting it.
    #
    # It also requires `--enable-sleep-mode`, `VLLM_SERVER_DEV_MODE=1`, and a KV
    # cache dtype other than fp8: an FP8 KV cache cannot be woken on vLLM 0.23.0
    # and strands the engine asleep.
    GPU_HANDOFF_ENABLED: bool = False

    # Ambient discovery egress. This is the first path in AniOS that reaches a
    # third party, and everything before it fails closed inside the machine, so
    # it ships off. Turning it on is an explicit operator decision, not a
    # default someone discovers after messages have already gone out.
    #
    # Apple publishes no server-side iMessage API, so the unpaid path is a Mac
    # signed into Messages exposing a send tool over MCP. AniOS decides whether
    # to send; that machine does the sending.
    DISCOVERY_EGRESS_ENABLED: bool = False
    # A sweep is weekly, so nothing about this loop needs to be prompt. The
    # lease is generous because reading several feeds over the network can
    # legitimately outlive a short one.
    DISCOVERY_POLL_SECONDS: float = Field(default=60.0, gt=0, le=3_600)
    DISCOVERY_RUN_LEASE_SECONDS: float = Field(default=300.0, gt=0, le=3_600)
    DISCOVERY_RUN_HEARTBEAT_SECONDS: float = Field(default=60.0, gt=0, le=600)
    DISCOVERY_IMESSAGE_TOOL: str = "send_message"
    # Which operator-trusted MCP server owns the Apple device that sends.
    DISCOVERY_IMESSAGE_SERVER_ID: str = "imessage"
    # The public base a subscriber's calendar link is built from. Local by
    # default: a link only resolves from wherever the recipient actually is, so
    # leaving this unset keeps delivery useful only on the same network.
    DISCOVERY_CALENDAR_BASE_URL: str = "http://localhost:8000/api/v1/discovery"
    # Reverse geocoding for the "use my location" button. Off unless an operator
    # sets a provider, so a deployment never reaches a third party by default.
    # The coordinate is rounded to roughly a kilometre before it is sent, and
    # only the resulting town label is stored.
    # Search a sweep for happenings no calendar feed publishes. Feeds cover
    # institutions; a trail association's group hike exists only as a page
    # someone wrote. Bounded per sweep, and dates are read from the text rather
    # than inferred, so an undated find stays a link and never a calendar entry.
    DISCOVERY_WEB_SEARCH_ENABLED: bool = True
    DISCOVERY_WEB_QUERIES_PER_SWEEP: int = Field(default=4, ge=1, le=10)
    DISCOVERY_PLACE_RESOLVER: Literal["", "nominatim"] = ""
    DISCOVERY_PLACE_RESOLVER_URL: str = "https://nominatim.openstreetmap.org/reverse"
    DISCOVERY_PLACE_RESOLVER_USER_AGENT: str = "AniOS/1.0 (local personal assistant)"

    GPU_HANDOFF_SLEEP_LEVEL: int = Field(default=1, ge=1, le=2)
    GPU_HANDOFF_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0, le=600)
    IMAGE_PROVIDER_TIMEOUT_SECONDS: float = Field(default=600.0, gt=0, le=3600)
    IMAGE_PROVIDER_POLL_SECONDS: float = Field(default=0.5, ge=0.1, le=10)
    IMAGE_MAX_CONCURRENCY: int = Field(default=1, ge=1, le=4)
    ARTIFACT_STORAGE_ROOT: str = "data/artifacts"
    PRESENTATION_RENDERER_BASE_URL: str = "http://127.0.0.1:8002"
    PRESENTATION_RENDERER_TIMEOUT_SECONDS: float = Field(default=60.0, gt=0, le=600)
    PRESENTATION_MAX_OUTPUT_BYTES: int = Field(
        default=50 * 1024 * 1024,
        ge=1024,
        le=200 * 1024 * 1024,
    )
    PRESENTATION_MAX_TOKENS: int = Field(default=8_192, ge=1_024, le=32_768)
    PRESENTATION_PLAN_MAX_TOKENS: int = Field(default=2_048, ge=1_024, le=8_192)
    PRESENTATION_REVISION_MAX_TOKENS: int = Field(
        default=1_024,
        ge=256,
        le=4_096,
    )
    PRESENTATION_REQUIRE_OFFICE_VALIDATION: bool = False
    PRESENTATION_JOB_POLL_SECONDS: float = Field(default=0.5, ge=0.1, le=30)
    PRESENTATION_JOB_LEASE_SECONDS: float = Field(default=300, ge=30, le=3_600)
    PRESENTATION_JOB_HEARTBEAT_SECONDS: float = Field(default=30, ge=5, le=300)
    # Enrich only the most valuable model-declared slides so default imagery
    # improves the deck without serially generating an image for every slide.
    PRESENTATION_AUTO_IMAGE_MAX: int = Field(default=1, ge=0, le=10)
    # Keep slide imagery sharp without paying the fourfold pixel cost of 2048px
    # generation on the current single-GPU workstation.
    PRESENTATION_AUTO_IMAGE_SIZE: int = Field(default=1_024, ge=512, le=2_048)
    # Ground deck content in one web search per deck so figures come from
    # sources rather than recollection. Independent of chat search, which this
    # must be switchable without disabling: a deck asserting an invented
    # statistic is a different failure from a chat answer being stale.
    PRESENTATION_RESEARCH_ENABLED: bool = True
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    MODEL_GATE_ENABLED: bool = False
    MODEL_GATE_LEASE_SECONDS: float = Field(default=300, ge=30, le=900)
    MODEL_GATE_POLL_SECONDS: float = Field(default=0.1, ge=0.05, le=2)
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
    VISION_LLM_BASE_URL: str = ""
    VISION_MODEL: str = "qwen/qwen3.5-4b"
    VISION_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
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
    # How often the background reconciler embeds any ready image still missing a
    # vector, so a write-time failure never leaves an image permanently
    # unrecallable. It runs once at startup and then on this interval.
    VISION_EMBEDDING_RECONCILE_INTERVAL_SECONDS: float = Field(
        default=900.0, ge=30, le=86_400
    )
    # Image search needs its own threshold. Cross-modal cosine similarity runs
    # an order of magnitude below text-text similarity (the modality gap), so
    # MEMORY_SEMANTIC_MAX_COSINE_DISTANCE would reject every image.
    # Calibrated against real generated images: correct matches landed at
    # 0.91-0.954 while irrelevant queries sat at 0.961+. Relevant queries
    # separate the right image from the wrong one by ~0.05, versus ~0.005 of
    # noise for unrelated queries, so the usable band is narrow and absolute.
    VISION_SEARCH_MAX_COSINE_DISTANCE: float = Field(default=0.96, ge=0, le=2)
    VISION_SEARCH_MAX_RESULTS: int = Field(default=10, ge=1, le=50)
    # Recalled images are the leading cluster: every hit within this distance of
    # the closest one. This returns one match or several near-identical ones (two
    # red cars) without the old best-vs-runner-up margin, which rejected genuine
    # matches once a user owned more than one relevant image. Measured true-match
    # clusters spanned ~0.004 and gapped to the rest by ~0.007+, so 0.006 keeps
    # the real matches together and excludes the field.
    VISION_SEARCH_CLUSTER_DELTA: float = Field(default=0.006, ge=0, le=1)
    # A bounded single-token classifier resolves image references the recall
    # patterns miss ("that thing we made yesterday"). It is gated to plausibly
    # -image queries, so unrelated turns never call it; it reuses the shared
    # classifier model, which is fastest when SEARCH_CLASSIFIER_MODEL is a small
    # model.
    IMAGE_RECALL_CLASSIFIER_ENABLED: bool = True
    IMAGE_RECALL_CLASSIFIER_MAX_TOKENS: int = Field(default=4, ge=1, le=16)

    # Web search. The MCP server prefers Google Grounding and falls back to
    # Tavily; both return untrusted third-party content.
    SEARCH_PROVIDER_NAME: Literal["tavily", "mcp"] = "tavily"
    SEARCH_BASE_URL: str = "https://api.tavily.com"
    # Empty disables search rather than failing startup; callers check is_enabled.
    SEARCH_API_KEY: str | None = Field(None, alias="SEARCH_API_KEY")
    # The shared monthly ceiling every account spends from. Per-account limits
    # bound each caller but say nothing about the sum, so without this enough
    # accounts staying inside their own limits still drain the key. Defaults to
    # Tavily's free plan; raise it only to match a plan actually purchased.
    SEARCH_MONTHLY_CREDITS: int = Field(default=1_000, ge=0, le=1_000_000)
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
    # Deterministic patterns recall only 45.6% of FreshQA questions whose
    # answers change, because volatility is rarely phrased explicitly. A bounded
    # local classifier judges whatever the patterns do not match, raising recall
    # to 91.7% and accuracy to 82.5%. It costs one short model call on unmatched
    # queries only; disable it to fall back to patterns alone.
    SEARCH_CLASSIFIER_ENABLED: bool = True
    SEARCH_CLASSIFIER_MAX_TOKENS: int = Field(default=4, ge=1, le=16)
    # Empty uses LLM_MODEL. Smaller local models were measured on FreshQA and
    # rejected: qwen3-1.7b scored 70.0% accuracy against a 70.0% "always search"
    # baseline, contributing nothing over a constant answer, and qwen3-0.6b
    # reached 70.8%. The 12B chat model reached 81.7% because it is the only
    # candidate that actually discriminated.
    SEARCH_CLASSIFIER_MODEL: str = ""
    # Fixed read-only MCP boundary used after deterministic search routing.
    SEARCH_MCP_SERVER_ID: str = "internet"
    SEARCH_MCP_TOOL_NAME: str = "search_web"
    GOOGLE_API_KEY: str | None = Field(None, alias="GOOGLE_API_KEY")
    GEMINI_API_KEY: str | None = Field(None, alias="GEMINI_API_KEY")
    # Google Search grounding is a paid-tier capability. A key alone does not
    # grant it: verified across three accounts, a single first request with the
    # search tool returns 429 while the same key and model answer normally
    # without it. Left on, every search would pay ~220ms for a call that cannot
    # succeed, so the provider stays off until an operator confirms entitlement.
    GOOGLE_SEARCH_ENABLED: bool = False
    GOOGLE_SEARCH_MODEL: str = "gemini-3.6-flash"
    GOOGLE_SEARCH_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=120)
    # Covers reasoning tokens as well as the answer: gemini-3.6-flash spends
    # roughly 500-700 tokens thinking before it writes, so a 1024 budget
    # leaves a long grounded answer at risk of being truncated to nothing.
    GOOGLE_SEARCH_MAX_OUTPUT_TOKENS: int = Field(default=2_048, ge=128, le=8_192)
    # Bound local Google calls independently of the provider account quota.
    GOOGLE_SEARCH_DAILY_LIMIT: int = Field(default=450, ge=1, le=500)
    # Stores provider/day/count only; no queries or result content are retained.
    GOOGLE_SEARCH_QUOTA_DB_PATH: str = "data/search/google_search_quota.sqlite3"

    # MCP servers, as a JSON array of objects with server_id, command, args,
    # and an operator-assigned risk_classification. Trust is declared here and
    # never read from a server's own description of itself.
    MCP_SERVERS_JSON: str = "[]"
    MCP_LIST_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=300)
    # Tool descriptors are short structured text, so a natural-language query
    # sits further from them than memory text sits from memory text. Measured
    # against a live catalogue, correct matches landed at 0.295-0.437 while
    # unrelated questions sat at 0.477+, so the general memory threshold of
    # 0.35 silently discarded correct tools.
    TOOL_SEARCH_MAX_COSINE_DISTANCE: float = Field(default=0.45, ge=0, le=2)
    # Retrieve a handful rather than the whole catalogue: published results put
    # naive exposure of 100+ tools near random selection.
    TOOL_SEARCH_MAX_RESULTS: int = Field(default=5, ge=1, le=20)

    # OpenTelemetry tracing. Off by default: turning it on never requires a
    # collector to be reachable, since an unreachable OTLP endpoint drops spans
    # in the background rather than failing a request.
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "anios-backend"
    OTEL_EXPORTER: Literal["console", "otlp", "none"] = "console"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = ""

    # Authentication and revocable browser sessions.
    SECRET_KEY: str = Field(..., alias="SECRET_KEY")
    AUTH_REQUIRED: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    AUTH_SESSION_TTL_HOURS: int = Field(default=168, ge=1, le=720)
    AUTH_COOKIE_NAME: str = "anios_session"
    AUTH_COOKIE_SECURE: bool = False
    AUTH_COOKIE_SAMESITE: Literal["lax", "strict"] = "lax"
    AUTH_TRUSTED_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"
    AUTH_LOCAL_USER_ID: str = "ani.mallya"
    AUTH_LOGIN_MAX_FAILURES: int = Field(default=8, ge=2, le=100)
    AUTH_LOGIN_FAILURE_WINDOW_SECONDS: int = Field(default=900, ge=60, le=86_400)
    AUTH_LOGIN_GLOBAL_MAX_ATTEMPTS: int = Field(default=120, ge=10, le=10_000)
    AUTH_LOGIN_GLOBAL_WINDOW_SECONDS: int = Field(default=60, ge=10, le=3_600)

    # Encryption at rest. Opt-in: empty means disabled and all content is stored
    # as plaintext, unchanged from earlier behaviour. Set a urlsafe-base64
    # AES-256 key (see `python -m backend.cli.generate_encryption_key`) to seal
    # conversation, memory, and image content before it reaches disk. This is
    # defence in depth over, not a replacement for, OS full-disk encryption.
    ENCRYPTION_KEY: str = ""

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # type: ignore[call-arg]
