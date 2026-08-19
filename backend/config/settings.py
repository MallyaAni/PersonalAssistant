import os
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
    # Blank means MainActionSelector's tool-calling decision rides the same
    # model as the conversational reply (MAIN_LLM_*), same as before this
    # setting existed. Set only when the two need to differ - e.g. a main
    # model swap for reply quality that should not also inherit that model's
    # untested (or known-weaker) native tool-calling behavior. Evaluated
    # 2026-08-14 specifically for that scenario; see ROADMAP.md Milestone 9.
    ROUTING_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    ROUTING_LLM_BASE_URL: str = ""
    ROUTING_LLM_MODEL: str = ""
    ROUTING_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    # Whether the main model's serving engine actually enforces a JSON schema
    # it is handed, rather than accepting one and answering in whatever shape it
    # likes.
    #
    # This is the single fact that decides whether the reasoning work of this
    # application can follow the main model. It is a property of the *engine*,
    # not the model: DeepSeek-V4-Flash reasons about an utterance better than
    # the 4B classifier does — asked to extract a locality and interests it gets
    # both right — but `ds4-server` returns `"locality": "Raleigh, NC"` where the
    # contract requires `{label, region}`, so the answer is discarded. vLLM
    # enforces the grammar and does not have this problem.
    #
    # Three separate outages traced to it before it was named: the presentation
    # revert on 2026-08-14, image recall returning nothing, and Scout's place
    # suggester returning an empty tuple. Each was fixed by moving one call site
    # to Qwen, which is why the fix kept having to be repeated. Set this true
    # when the main model is served by an engine that honours schemas, and every
    # structured caller follows the main model at once.
    MAIN_LLM_STRUCTURED_OUTPUT: bool = False
    # When the reply model's training data ends, as YYYY-MM.
    #
    # Knowing today's date tells a model when "now" is. Knowing this tells it
    # what it cannot possibly know, which is the more useful fact: everything
    # between this month and today has to come from a search, and a model that
    # does not know the boundary answers confidently from the wrong side of it.
    # Asked which models to host, the assistant recommended ones superseded
    # months earlier - a release from 2026-08-11 was four months past the
    # configured cutoff and could not have been in training at all.
    #
    # Measure it, do not look it up. 2026-04 was set here from a secondhand
    # figure and was wrong by about two years, which is worse than leaving it
    # empty: it told a model its knowledge was current when it was not, so it
    # answered from memory where it should have deferred to a search.
    #
    # Asked directly, the model serving MAIN_LLM_* named Qwen2.5 as the newest
    # Qwen family it knows, did not recognise a model released this month, and
    # said it believed the year to be 2024. Behaviour agrees with its own
    # report, so 2024-07 is what is configured.
    #
    # To re-measure after a model change, ask it three things: the newest
    # release it knows of in a fast-moving family, whether it recognises
    # something released recently, and what year it believes it is.
    MAIN_LLM_TRAINING_CUTOFF: str = "2024-07"
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
    MEMORY_PROPOSAL_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    MEMORY_PROPOSAL_LLM_BASE_URL: str = ""
    MEMORY_PROPOSAL_LLM_MODEL: str = ""
    MEMORY_PROPOSAL_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    MEMORY_PROPOSAL_MAX_TOKENS: int = Field(default=256, ge=32, le=512)

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
    # Searching the user's own past turns, not only the facts a classifier
    # promoted out of them. An account with fourteen conversations had zero
    # promoted rows, so recall could reach none of what it had been told.
    #
    # Off by default until the distance below is measured on real turns: this
    # is the switch that makes the change reversible without a redeploy.
    MEMORY_RECALL_TURNS_ENABLED: bool = False
    # A turn is a sentence someone spoke, not a curated fact, so it embeds
    # differently and the 0.35 above does not transfer. Deliberately tighter
    # than a guess would be: a wrong recall costs prompt budget and reads as
    # the assistant misremembering, which is worse than recalling nothing.
    MEMORY_RECALL_TURNS_MAX_COSINE_DISTANCE: float = Field(
        default=0.30, ge=0, le=2
    )
    MEMORY_RECALL_TURNS_MAX_RESULTS: int = Field(default=3, ge=1, le=10)
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
    IMAGE_MODEL: str = "flux-2-klein-4b-fp8.safetensors"
    IMAGE_TEXT_ENCODER: str = "qwen_3_4b.safetensors"
    IMAGE_VAE: str = "flux2-vae.safetensors"
    IMAGE_GENERATION_STEPS: int = Field(default=4, ge=1, le=100)
    IMAGE_EDIT_STEPS: int = Field(default=4, ge=1, le=100)
    # The FLUX.1 Kontext editing stack. Naming a model here replaces the
    # FLUX.2 Klein editor for edits only; generation is untouched, and leaving
    # it empty restores the previous behaviour exactly.
    #
    # Klein is a distilled generation model with the source attached as a
    # reference, and it is trained to preserve that reference: an instruction
    # requiring anything to be added left the picture unchanged at 4 steps and
    # at 20, at CFG 3.0, and under true img2img at denoise 0.70. Kontext is
    # trained to follow an editing instruction instead.
    IMAGE_EDIT_MODEL: str = ""
    IMAGE_EDIT_CLIP: str = "clip_l.safetensors"
    IMAGE_EDIT_T5: str = "t5xxl_fp8_e4m3fn_scaled.safetensors"
    IMAGE_EDIT_VAE: str = "ae.safetensors"
    # Kept apart from IMAGE_EDIT_STEPS because the two editors want different
    # numbers: four is Klein's operating point and far too few for Kontext,
    # and one shared value would silently be wrong for whichever is not
    # selected.
    IMAGE_EDIT_KONTEXT_STEPS: int = Field(default=20, ge=1, le=100)
    # How strongly the instruction is applied. FLUX.1 is guidance-distilled and
    # takes this on the conditioning rather than as a CFG scale.
    IMAGE_EDIT_GUIDANCE: float = Field(default=2.5, ge=0.0, le=10.0)
    # What the source is resampled to before editing, and how.
    #
    # Both were inherited from ComfyUI's own FLUX.2 Klein template and neither
    # suits a photograph. `nearest-exact` drops pixels rather than averaging
    # them, which is the worst filter available for downscaling: it aliases
    # edges and stipples skin and hair. `lanczos` is what the same node offers
    # for photographic downscale.
    #
    # The megapixel budget is the ceiling on what comes back, because the output
    # is generated at the scaled size. At 1.0 an edit returned 1024x1024 however
    # large the source was, which is why editing a phone photo produced something
    # visibly worse than the original.
    #
    # 2.0 was measured on this card rather than assumed: with vLLM resident and
    # 5,863 MiB free, an edit produced 1440x1440 in 39 seconds and did not run
    # out of memory. The cost is bounded by this number rather than by the source,
    # because the scale node normalises to it either way.
    IMAGE_EDIT_MEGAPIXELS: float = Field(default=2.0, ge=0.25, le=4.0)
    IMAGE_EDIT_SCALE_METHOD: str = "lanczos"
    # Realism steering is driven by appending this to the positive prompt. It is
    # added only when not already present; set it empty to send prompts verbatim.
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
    #
    # Retested 2026-08-17 against the current image, because generation had
    # slowed to 88-112 s while a warm run takes 6.2 s and ComfyUI's log showed
    # it swapping weights every job - exactly what this was built to stop. It
    # cannot be used: with every documented precondition satisfied
    # (`--enable-sleep-mode`, dev mode on, `--kv-cache-dtype auto`),
    # `POST /sleep?level=1` hangs past 120 s, frees no GPU memory, and leaves
    # EngineCore dead - every later request answers `EngineDeadError` until the
    # container is restarted, which takes about 150 s. Reproduced twice.
    # So the slow generations are not a missing handoff; do not turn this on
    # hoping to recover them. The card genuinely holding both runtimes at once
    # is the only fix available here.
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
    # Reads thumbs-up and thumbs-down tapbacks off the bubbles already sent.
    # A bridge without this tool simply answers nothing, and no feedback is
    # collected — delivery is unaffected either way.
    DISCOVERY_REACTIONS_TOOL: str = "read_reactions"
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
    # How long being away lasts before Scout looks around home again. Long
    # enough to cover an ordinary trip, short enough that forgetting to say you
    # came back costs a couple of digests rather than every digest from now on.
    DISCOVERY_TRIP_DAYS: int = Field(default=14, ge=1, le=180)
    # Whether a sweep hides what it has already shown. On by default, because
    # "never show the same thing twice" is what stops a weekly digest becoming
    # the same list every week. Turning it off makes every sweep report
    # everything it finds, which is what you want while judging output quality
    # and not what you want on a schedule.
    DISCOVERY_NOVELTY_ENABLED: bool = True
    # Whether a sweep aims its searches at the person rather than at the topic.
    # On, the local model turns each approved interest plus what memory knows
    # into the subject of a query and the vector candidates are scored against;
    # off, both are the bare interest label, which is what every sweep before
    # this did. Kept switchable because search is metered: a worse subject
    # spends real budget, so the two must be comparable across real sweeps.
    DISCOVERY_PERSONAL_QUERIES_ENABLED: bool = True
    # Whether the model reorders the qualified shortlist against approved
    # memory. It can never admit a find deterministic ranking rejected — only
    # reorder what qualified, and drop one whose own text states a restriction
    # an approved fact contradicts.
    DISCOVERY_MEMORY_RERANK_ENABLED: bool = True
    # A local cross-encoder that reads an interest and a candidate as one
    # sequence, used to order the shortlist embeddings admitted. It runs
    # in-process on CPU because the card is fully committed to generation and
    # image work, and because a weekly batch of a few hundred short pairs does
    # not need a GPU. Missing weights disable it and the embedding order stands.
    DISCOVERY_CROSS_ENCODER_ENABLED: bool = True
    DISCOVERY_CROSS_ENCODER_MODEL_PATH: str = (
        "data/models/ms-marco-minilm-l6-v2/model.onnx"
    )
    DISCOVERY_CROSS_ENCODER_TOKENIZER_PATH: str = (
        "data/models/ms-marco-minilm-l6-v2/tokenizer.json"
    )
    DISCOVERY_CROSS_ENCODER_THREADS: int = Field(default=2, ge=1, le=16)
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
    # Measured 2026-08-14: a real "detailed... capabilities and where to use
    # it" prompt produced a plan that needed ~2,000 tokens, close enough to
    # the old 2,048 default that it truncated mid-JSON on 2 of 3 identical
    # attempts - a real, pre-existing reliability gap, not a fluke. Doubled
    # for headroom rather than tuned to the exact failure.
    PRESENTATION_PLAN_MAX_TOKENS: int = Field(default=4_096, ge=1_024, le=8_192)
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
    # Sized from measurement, not habit. This budget used to carry one
    # description; it now carries a single-pass inspection - observation,
    # the user's answer, grounding, a search query and any identifications -
    # and the responsibility grew without the ceiling moving. Two real
    # photographs came back at 488 completion tokens against the old 512, so
    # an ordinary upload sat 24 tokens from truncated JSON, which fails the
    # strict schema and answers a valid upload with a 502.
    VISION_MAX_TOKENS: int = Field(default=1536, ge=32, le=4096)
    # Optional stronger VLM used once only when the primary sees diagnostic
    # evidence but cannot interpret it. Missing pixels and safety-sensitive
    # identification never spend this fallback.
    VISION_ESCALATION_LLM_BASE_URL: str = ""
    VISION_ESCALATION_MODEL: str = ""
    VISION_ESCALATION_LLM_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    # Prior question/answer pairs replayed to the VLM alongside the anchored image.
    VISION_THREAD_CONTEXT_TURNS: int = Field(default=8, ge=1, le=50)
    # Total question/answer pairs retained in one image's stored analysis thread.
    VISION_THREAD_MAX_STORED: int = Field(default=40, ge=1, le=500)
    # Whether an image question is answered by the main model reasoning over
    # what the VLM saw, instead of by the VLM itself. The VLM is chosen for
    # describing pixels, not for judgement, so questions that need comparison or
    # inference were previously answered at its reasoning ability rather than
    # the strongest configured model's. Off restores the VLM-only answer exactly.
    VISION_REASONING_ENABLED: bool = True
    # Larger than VISION_MAX_TOKENS because this budget carries a reasoned
    # answer, not a description, and the reply is what the user actually reads.
    VISION_REASONING_MAX_TOKENS: int = Field(default=1024, ge=64, le=8192)
    # Whether an image question may search the web to identify what was seen.
    # Both models can describe an object correctly and still not know what it
    # is - and the main model will name a recent device confidently and wrongly
    # from stale memory - so identification is grounded in a real search. The
    # decision to search is a native tool call by the routing model, never a
    # keyword test against the answer.
    # Where the main model's work goes when its host cannot be reached at all.
    # The main model runs on a separate machine that is not always powered on;
    # unset, every reply and routing decision simply raises while it is off,
    # which takes the whole assistant down rather than degrading it. Empty
    # disables the standby and restores the previous all-or-nothing behaviour.
    MAIN_LLM_STANDBY_BASE_URL: str = ""
    MAIN_LLM_STANDBY_MODEL: str = ""
    MAIN_LLM_STANDBY_REASONING_EFFORT: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    VISION_SEARCH_GROUNDING_ENABLED: bool = True
    # Room for one search_web tool call and its query, nothing more.
    VISION_SEARCH_DECISION_MAX_TOKENS: int = Field(default=300, ge=32, le=2048)
    # Room for {"intent":"edit"} and nothing else; the schema is the grammar.
    IMAGE_INTENT_MAX_TOKENS: int = Field(default=16, ge=8, le=64)

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
    SEARCH_MAX_RESULTS: int = Field(default=8, ge=1, le=20)
    SEARCH_TIMEOUT_SECONDS: float = Field(default=15.0, gt=0, le=120)
    # Per-result truncation so one verbose page cannot dominate the prompt budget.
    SEARCH_MAX_CONTENT_CHARS: int = Field(default=6_000, ge=200, le=20_000)
    SEARCH_DEPTH: Literal["basic", "advanced"] = "advanced"
    # Minimum provider relevance for a result to reach the prompt. Measured
    # across 40 real results the distribution is bimodal: usable hits scored
    # 0.561-0.923 while dictionary-definition noise scored 0.046-0.346, leaving
    # an empty band between. Feeding that noise in is worse than returning
    # nothing, because the prompt tells the model to prefer web results over its
    # own knowledge for time-sensitive facts.
    SEARCH_MIN_SCORE: float = Field(default=0.4, ge=0, le=1)
    # How many searches one turn may make. One was the ceiling on how good an
    # answer could be: results that are about the subject but never state the
    # answer look identical to results that do, and nothing could try again.
    # Each extra round costs a search and a model call, so this is small.
    SEARCH_MAX_ROUNDS: int = Field(default=3, ge=1, le=5)
    # How many of those rounds happen without asking the model first.
    #
    # Asked whether results were sufficient, it said yes 8 times out of 8
    # on results naming two options and giving a figure for neither, and
    # four wordings of the question moved the rate between 0/8 and 3/5
    # with no trend. A second look is cheaper than a wrong answer built
    # from memory, so it is taken rather than requested. Set to 1 to make
    # every round conditional again.
    SEARCH_MIN_ROUNDS: int = Field(default=2, ge=1, le=3)
    # Fixed read-only MCP boundary the turn's action selection calls into.
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

    # The deployed stack's `.env`, except under test.
    #
    # Settings are built once at import, so whatever `.env` says governs every
    # test run on a machine that has one - and this repository's sets
    # AUTH_REQUIRED=true, which made any test touching a protected route pass
    # on a clean checkout and fail on a real workstation. The failure looked
    # like the feature under test rather than like configuration, and cost two
    # separate investigations. Under test the file is ignored outright, so a
    # test's environment is the defaults plus what the test itself sets, and
    # nothing a developer keeps locally can change a result.
    model_config = SettingsConfigDict(
        env_file=None if os.getenv("ANIOS_TEST_MODE") else ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()  # type: ignore[call-arg]
