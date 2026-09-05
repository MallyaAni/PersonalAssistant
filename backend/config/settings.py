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
    # The routing decision's token budget, previously a bare 300 at the call
    # site - the same limit-nobody-chose class as the reply cap that returned
    # one empty reply in six. Covers a tool call plus reasoning-model thinking.
    ROUTING_DECISION_MAX_TOKENS: int = Field(default=1_024, ge=64, le=8_192)
    # The tool catalog (backend/tools/catalog.py): with more tools than
    # ROUTING_TOOL_SEARCH_THRESHOLD, all but the most-used are replaced by a
    # one-line index and fetched on demand through find_tools. Off until it
    # is measured against the labelled cases both ways; the threshold follows
    # Anthropic's own guidance (standard calling under ten tools, search
    # above it, accuracy falling away past thirty to fifty).
    ROUTING_TOOL_SEARCH_ENABLED: bool = False
    # Measured 2026-09-03 on the 108 labelled cases, one pass each way:
    # identical totals (87/96 on the categories both runs covered), four
    # categories better and four worse, which at two to five cases each is
    # noise. So the catalogue neither helps nor hurts at today's twenty-odd
    # tools, and it costs a round trip when it fires. The threshold sits at
    # the bottom of Anthropic's own cliff instead of at their switch-on
    # advice: it should start earning its keep as the list grows, not now.
    ROUTING_TOOL_SEARCH_THRESHOLD: int = Field(default=30, ge=4, le=60)
    ROUTING_TOOL_SEARCH_RESULTS: int = Field(default=5, ge=1, le=20)
    # How long one routing decision is reused for the same message, tools and
    # day. "Try again" and a retry after a failure ask the model the same
    # question a second time, and today it can answer differently: the same
    # case flipped between two measured passes in eight categories. Zero
    # switches it off.
    ROUTING_DECISION_CACHE_SECONDS: float = Field(default=300.0, ge=0, le=3600)
    # How long a server's tool catalogue is held before it is read again.
    # Listing opens a session per call, and for a stdio server that spawns the
    # process. The router resolves two or three live schemas per decision, so
    # without this every turn spawned the internet server two or three times:
    # measured 2026-09-03 at 1.0-1.1s each against a 1.8s routing call, which
    # is most of what choosing a tool cost. Staleness is bounded by this and,
    # at the point of a call, by the fingerprint assertion that already runs.
    # Zero switches it off.
    MCP_TOOL_LIST_CACHE_SECONDS: float = Field(default=300.0, ge=0, le=3600)
    ROUTING_DECISION_CACHE_MAX: int = Field(default=512, ge=16, le=8192)
    # How many tool decisions one turn may make.
    #
    # One was the ceiling on what a request could express, not a design: a
    # message asking to cancel one reminder and set another needs two calls,
    # and a turn that could make only one answered as though it had made both.
    # Ships at 1 - the loop is unreachable until this is raised, so the code
    # deploys before the behaviour changes and reverting is an env var rather
    # than a rebuild.
    #
    # Each extra step is one more routing call. Measured on deepseek-v4-flash
    # across both Sparks: 1.78s median, 2.27s worst of three.
    TURN_MAX_STEPS: int = Field(default=1, ge=1, le=5)
    # Wall clock the extra steps may spend. A bound on time, not on calls,
    # because time is what starves the next sender: imessage_chat answers
    # serially and sends one acknowledgement bubble, then goes quiet.
    TURN_STEP_BUDGET_SECONDS: float = Field(default=45.0, ge=5.0, le=180.0)
    # How many new things one turn may create. One was the first rule and it
    # cut "set reminders for 6pm and 8pm" to a single reminder; two copies
    # of the same reminder are still stopped, by their shared key.
    TURN_MAX_CREATES: int = Field(default=3, ge=1, le=5)
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
    MAIN_LLM_STRUCTURED_OUTPUT: bool = True
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
    # How long a reply may run before the sampler stops it.
    #
    # This was 1,024, and not as a decision - it was the default on
    # `stream_chat`, and the reply path called it with no argument at all. The
    # cost was not truncated answers, it was missing ones: the main model emits
    # its thinking as `reasoning_content`, which the stream reader does not
    # render, so when thinking consumed the budget the stream ended with no
    # content and the turn raised. Measured on the live model at the time,
    # **one reply in six came back empty** on open-ended questions, and none did
    # at 4,096.
    #
    # So this is not a length preference. It is the headroom a reasoning model
    # needs to finish thinking and still answer, and it only ever binds on a
    # runaway - the longest genuine answer measured here spent about 1,600.
    MAIN_LLM_MAX_TOKENS: int = Field(default=4_096, ge=256, le=32_768)
    # Counting what a turn actually costs, before anything acts on the count.
    #
    # Nothing counted until now. The prompt was assembled from whatever each
    # source returned, bounded incidentally by numbers set once and never
    # measured against the window they share. That was survivable only because
    # a heavy turn is five to eight thousand tokens against a million-token
    # context - an accident, not a design, and one that stops being true
    # quietly.
    #
    # Enabled means measure and report. It does **not** mean trim: see
    # CONTEXT_BUDGET_ENFORCE. Measuring first is the same discipline the
    # search-payload fix needed - the numbers decide the floors, rather than
    # floors being chosen and the numbers explaining them afterwards.
    CONTEXT_BUDGET_ENABLED: bool = True
    # Whether the plan is applied or only recorded.
    #
    # Left false deliberately. Trimming changes what the model sees, and no
    # section priority here has been argued against real turn sizes yet.
    # Turning this on without the measurements it is meant to be built from
    # would repeat the mistake it exists to prevent.
    CONTEXT_BUDGET_ENFORCE: bool = False
    # The window the plan is made against. Well below what either served model
    # offers, because the point is to notice growth long before it collides
    # with a hard limit - a budget that only binds at the ceiling reports
    # nothing useful until the day it reports a failure.
    # Where each turn's context measurement is appended, one JSON object per
    # line. On a named volume because docker logs die with every rebuild and
    # this distribution has to accumulate across days to set enforcement
    # floors. Empty disables persistence.
    CONTEXT_REPORT_PATH: str = "data/telemetry/context_reports.jsonl"
    CONTEXT_BUDGET_TOKENS: int = Field(default=32_768, ge=2_048, le=1_000_000)
    # Whether the conversation digest is written by the reply model or by
    # truncation.
    #
    # Truncation keeps the newest words and loses the oldest meaning, which is
    # the wrong thing to lose from a long conversation. Compression is better,
    # but only from a model good enough to compress without inventing: a bad
    # summary enters every later prompt indistinguishable from something the
    # user actually said, whereas truncation drops material honestly.
    #
    # Runs once per MEMORY_SUMMARY_INTERVAL turns, after the reply has been
    # sent, so it never delays an answer. Off leaves the bounded truncation,
    # which is also what every failure path falls back to.
    # Whether this turn's volatile material sits after the history instead of
    # inside the system message.
    #
    # Prefix caching reuses KV blocks for an unchanged prefix, and one volatile
    # byte early invalidates everything after it. The per-turn blocks - the
    # memory-save note, recalled remarks, search results, images, tool output -
    # sat ahead of the history, which is append-only and would otherwise cache
    # perfectly. So every turn paid full prefill on servers configured
    # specifically to avoid that.
    #
    # Measured on the reply model over a 34k-token conversation: a second turn
    # took **33.1 seconds** with the old ordering and **2.0 seconds** with this
    # one. The content is identical and its internal order unchanged; only its
    # position moves. That also places the turn's evidence next to the question
    # it belongs to, rather than in the middle of a long prompt where models
    # attend to it least reliably.
    #
    # False restores the previous arrangement exactly, since this changes prompt
    # structure and prompt structure changes behaviour in ways only a functional
    # test can rule out.
    CONTEXT_CACHE_ORDERING: bool = True
    MEMORY_DIGEST_MODEL_ENABLED: bool = True
    # Prose, so this is a target the prompt states rather than a hard cut. The
    # caller rejects an answer past twice this, on the grounds that ignoring the
    # instruction this badly means the rest is not worth trusting either.
    MEMORY_DIGEST_MAX_WORDS: int = Field(default=200, ge=50, le=1_000)
    # Enough for the words above plus whatever the model spends thinking. Sized
    # from the same measurement as the reply budget: too small a value on a
    # reasoning model returns an empty string, not a short one.
    MEMORY_DIGEST_MAX_TOKENS: int = Field(default=2_048, ge=256, le=8_192)
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
    # 256 was sized for the answer alone. A reasoning model spends part of any
    # budget thinking before it answers, and on ds4-server a truncated
    # generation puts the raw thinking into `content` - parseable-looking
    # garbage - while vLLM returns an empty string. The 4B never reasons, so
    # raising the ceiling costs it nothing: max_tokens is a cap, not a target.
    MEMORY_PROPOSAL_MAX_TOKENS: int = Field(default=1_024, ge=32, le=4_096)

    VISION_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    EMBEDDING_INFERENCE_ADAPTER: Literal["", "openai_compatible"] = ""
    # Semantic memory embeddings use their own replaceable role configuration.
    EMBEDDING_BASE_URL: str = ""
    # Document parsing (docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md). Docling turns
    # a PDF, Word or PowerPoint file into Markdown before it is chunked and
    # embedded. Empty disables document uploads with a clear message rather
    # than a connection error; the parser is bursty and lives where a GPU is.
    DOCLING_BASE_URL: str = ""
    DOCLING_TIMEOUT_SECONDS: int = Field(default=300, ge=10, le=1800)
    # Pictures inside a document, described by the household's own vision
    # model through Docling (an OpenAI-compatible chat endpoint the DESKTOP can
    # reach - the LAN address, not a compose name). Empty leaves pictures as
    # placeholders. Only pictures above the area share are described, so a
    # logo or a thumbnail does not become a paragraph of noise; measured
    # 2026-09-02: one picture, 17 s, on spark2's Qwen3-VL-8B.
    DOCLING_PICTURE_API_URL: str = ""
    DOCLING_PICTURE_MODEL: str = "qwen3-vl-8b"
    DOCLING_PICTURE_AREA_THRESHOLD: float = Field(default=0.05, ge=0, le=1)
    DOCLING_PICTURE_TIMEOUT_SECONDS: int = Field(default=90, ge=10, le=600)
    DOCUMENT_UPLOAD_MAX_BYTES: int = Field(default=25 * 1024 * 1024, ge=1024)
    # Document writing (the mirror of parsing): Gotenberg prints the
    # assistant's words to a PDF. Empty means PDFs are answered as Word files,
    # which need no renderer. Bursty, and it lives on the desktop with Docling.
    GOTENBERG_BASE_URL: str = ""
    GOTENBERG_TIMEOUT_SECONDS: int = Field(default=120, ge=10, le=900)
    # How often the durable parse queue retries documents that arrived while
    # the parser was unreachable. Zero disables the loop.
    DOCUMENT_PARSE_QUEUE_INTERVAL_SECONDS: int = Field(default=60, ge=0, le=3600)
    DOCUMENT_PARSE_MAX_ATTEMPTS: int = Field(default=200, ge=1)
    EMBEDDING_MODEL: str = "text-embedding-nomic-embed-text-v1.5"
    EMBEDDING_MODEL_VERSION: str = "nomic-embed-text-v1.5"
    EMBEDDING_DIMENSION: int = Field(default=768, ge=1, le=2_000)
    EMBEDDING_MAX_CONCURRENCY: int = Field(default=1, ge=1, le=32)
    MEMORY_SEMANTIC_MAX_COSINE_DISTANCE: float = Field(default=0.35, ge=0, le=2)
    # Document passages are longer and more varied than memory facts, so the
    # memory cutoff rejects them: measured 2026-09-02 on the operator's
    # itinerary, "whats on evening of day 1?" sat at 0.460 from the Day 1
    # chunk (0 results at 0.35); named with the document it sat at 0.332.
    # The reply answers only from the passages it is shown and abstains
    # otherwise, so a looser gate here costs nothing but a few extra
    # passages. Precedent: recall turns 0.45, history search 0.6.
    KNOWLEDGE_MAX_COSINE_DISTANCE: float = Field(default=0.5, ge=0, le=2)
    # Retention for document knowledge: a document whose last date (read by
    # the digest step) is this many days past is archived - kept, reachable
    # when nothing current answers or when pinned, out of default retrieval.
    # The file is never deleted on a date. Dated facts saved from a document
    # expire on the same day.
    KNOWLEDGE_ARCHIVE_GRACE_DAYS: int = Field(default=30, ge=0, le=3650)
    KNOWLEDGE_ARCHIVE_INTERVAL_SECONDS: int = Field(default=3600, ge=0, le=86400)
    # Google Drive as a read-only document source (docs/DOCUMENT_KNOWLEDGE_ARCHITECTURE.md,
    # stage 8). A Desktop OAuth client's id and secret, the token file the
    # connect CLI writes, and the folder to watch. Idle unless all are set.
    GOOGLE_OAUTH_CLIENT_ID: str = ""
    GOOGLE_OAUTH_CLIENT_SECRET: str = ""
    GOOGLE_TOKEN_PATH: str = "data/google/token.json"
    GOOGLE_DRIVE_FOLDER_ID: str = ""
    GOOGLE_DRIVE_USER_ID: str = ""
    GOOGLE_DRIVE_SYNC_INTERVAL_SECONDS: int = Field(default=900, ge=0, le=86400)
    MEMORY_SEMANTIC_MAX_RESULTS: int = Field(default=5, ge=1, le=20)
    # Searching the user's own past turns, not only the facts a classifier
    # promoted out of them. An account with fourteen conversations had zero
    # promoted rows, so recall could reach none of what it had been told.
    #
    # Measured before being switched on, against real history: at 0.35 it
    # answered 1 of 5 questions, at 0.40 four, at 0.45 all five, and at 0.50 it
    # answered no more while returning twice the turns. The switch stays so it
    # can be turned off without a redeploy.
    MEMORY_RECALL_TURNS_ENABLED: bool = True
    # A turn is a sentence someone spoke, not a curated fact, so it embeds
    # differently and the 0.35 above does not transfer - measured, useful
    # recalls sit between 0.25 and 0.44 and the curve flattens after 0.45.
    # Re-measure this after any embedding model change; it is a property of
    # that model, not of the feature.
    MEMORY_RECALL_TURNS_MAX_COSINE_DISTANCE: float = Field(default=0.45, ge=0, le=2)
    MEMORY_RECALL_TURNS_MAX_RESULTS: int = Field(default=3, ge=1, le=10)
    # The active form: when the model chooses search_history, it digs wider and
    # deeper than the passive injection above - looser distance, more results -
    # because the person explicitly pointed at something that is not in view.
    HISTORY_SEARCH_MAX_RESULTS: int = Field(default=12, ge=1, le=50)
    HISTORY_SEARCH_MAX_COSINE_DISTANCE: float = Field(default=0.6, ge=0, le=2)
    HISTORY_RERANK_CANDIDATES: int = Field(default=40, ge=1, le=200)
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
    IMAGE_MODEL: str = "flux-2-klein-9b-fp8.safetensors"
    IMAGE_TEXT_ENCODER: str = "qwen_3_8b_fp8mixed.safetensors"
    IMAGE_VAE: str = "flux2-vae.safetensors"
    IMAGE_GENERATION_STEPS: int = Field(default=4, ge=1, le=100)
    IMAGE_EDIT_STEPS: int = Field(default=4, ge=1, le=100)
    # The FLUX.1 Kontext editing stack. Naming a model here replaces the
    # FLUX.2 Klein editor for edits only; generation is untouched, and leaving
    # it empty routes edits through the same Klein model that generates.
    #
    # Klein 4B was measured unable to *add* anything: trained to preserve its
    # reference, it left the picture unchanged at 4 steps and at 20, at CFG
    # 3.0, and under true img2img at denoise 0.70, which is why Kontext was
    # selected on the single-card profile. The 9B does not share that failure
    # (2026-08-25, judged by the vision model on the pixels: an umbrella was
    # added, a wall turned white), and editing with the resident generation
    # model costs ~20 s where a Kontext swap cost ~110 s cold on a 16 GB
    # card - so the deployment leaves this empty, and Kontext is the one-env
    # fallback if a class of edit turns out to need it.
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
    # 2.0 was measured on the RTX 5080 when it ran the whole stack: with vLLM
    # resident and 5,863 MiB free, an edit produced 1440x1440 in 39 seconds
    # and did not run out of memory. The cost is bounded by this number rather
    # than by the source, because the scale node normalises to it either way.
    #
    # Briefly 1.0 on 2026-08-25, when the same card hosted ComfyUI inside a
    # Docker Desktop WSL2 VM capped at the default 15.6 GB of RAM, where an
    # evicted model goes: a 2 MP edit queued behind a Klein generation made
    # ComfyUI exit cleanly mid-job. `.wslconfig memory=24GB` took effect with
    # the desktop's next reboot the same evening (the VM reports 23.47 GiB),
    # and 2.0 was measured again there: generate 54 s then a 2 MP edit in 68 s,
    # both models resident, 7.1 GiB still free, no disconnect. The 1.0 fallback
    # remains the right answer on any host whose VM is back at the default.
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
    # Klein's Qwen3 text encoder letters a picture in whatever script it
    # drifts to when the prompt says nothing about language: a stakeholder
    # value image asked for in English came back lettered in something else
    # (2026-08-25). Worded conditionally - "any writing" - so it names the
    # language of writing that is there without inviting writing into a
    # picture that had none. Checked by the tenth image scenario and by
    # backend/tests/functional/test_image_text_language_behaviour.py, both of
    # which read the sign back through the vision model.
    IMAGE_TEXT_SUFFIX: str = (
        "any writing in the picture is in clear, correctly spelled English"
    )
    # The same instruction, first. FLUX.2 Klein's Qwen3 text encoder weighs
    # the start of the prompt; the suffix alone still lettered pictures in a
    # German-looking script for two people on 2026-08-27. Empty disables it.
    IMAGE_TEXT_PREFIX: str = "English lettering only:"
    # Words the person put in quotes - a sign, a title, a label - are typeset
    # onto the finished picture in a clean face instead of being painted by
    # a 4-step distilled model that cannot spell. The diffusion prompt then
    # asks for the space without the words. Off returns to painted text.
    IMAGE_TEXT_OVERLAY: bool = True
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
    # The bridge's real tool name. This default was "send_message" for months
    # while production only worked because .env overrode it - a wrong default
    # is a landmine for every deployment that trusts defaults.
    DISCOVERY_IMESSAGE_TOOL: str = "send_imessage"
    # Reads thumbs-up and thumbs-down tapbacks off the bubbles already sent.
    # A bridge without this tool simply answers nothing, and no feedback is
    # collected — delivery is unaffected either way.
    DISCOVERY_REACTIONS_TOOL: str = "read_reactions"
    # The conversation over iMessage: inbound texts from allowlisted senders
    # are answered through the same /chat path the browser uses. Off until
    # the bridge's read tool is deployed and both ends are flipped together.
    IMESSAGE_CHAT_ENABLED: bool = False
    # The idle cadence: how often to check for new texts when nothing is
    # happening. A lone message waits on average half this to be noticed. A LAN
    # read that returns nothing is nearly free, so this is kept low; the active
    # cadence below takes over the moment a conversation starts.
    IMESSAGE_CHAT_POLL_SECONDS: float = Field(default=3.0, gt=0, le=300)
    # The active cadence, and how long it lasts after the last answered message.
    # During a back-and-forth the person's next text arrives within seconds of
    # our reply, so for a short window after answering we poll fast and pick it
    # up almost at once, then fall back to the idle cadence so a quiet bridge is
    # not hammered. Fast polling is a tiny read returning nothing, so the cost
    # of the active window is negligible.
    IMESSAGE_CHAT_ACTIVE_POLL_SECONDS: float = Field(default=1.5, gt=0, le=60)
    IMESSAGE_CHAT_ACTIVE_WINDOW_SECONDS: float = Field(default=45.0, ge=0, le=600)
    IMESSAGE_CHAT_READ_TOOL: str = "read_messages"
    # Positive tapbacks are queried only for message GUIDs this worker stored
    # after sending; a bridge without the tool leaves ordinary chat untouched.
    IMESSAGE_CHAT_REACTIONS_TOOL: str = "read_reactions_by_guid"
    # How long after sending a bubble its reactions are still polled for.
    #
    # The ledger keeps bubbles for seven days so a late tapback can still be
    # interpreted; this is the shorter window in which the Mac is *asked*.
    # Without it the worker called the bridge every two to six seconds forever,
    # because the ledger is never empty on an active account - a round trip and
    # a SQLite query on the operator's laptop, all day, to learn nothing.
    # People react within minutes. Zero switches the polling off entirely.
    IMESSAGE_CHAT_REACTION_WINDOW_SECONDS: int = Field(default=3_600, ge=0, le=86_400)
    # Where this worker reaches its own backend. The compose network name by
    # default; a host-run worker overrides it.
    IMESSAGE_CHAT_BASE_URL: str = "http://backend:8000"
    # iMessage has no "new chat" button, so the session boundary is drawn the
    # way texting already works: a lull. After this many hours of silence the
    # next text starts a fresh conversation id; memory and recall carry the
    # continuity, and each conversation stays a readable unit in the web UI.
    IMESSAGE_CHAT_SESSION_IDLE_HOURS: float = Field(default=24.0, gt=0, le=720)
    # A picture stays "in view" for a shorter window than the conversation:
    # hours after a diagram, an unrelated ticket question still carried it as
    # the selected image and the router tilted on a picture nobody was
    # discussing. Renewed on every use, so an active back-and-forth about a
    # picture keeps it; a lull lets it go.
    IMESSAGE_CHAT_IMAGE_IDLE_MINUTES: float = Field(default=60.0, gt=0, le=1440)
    # iMessage cannot stream and shows no typing indicator, so a turn that
    # fans out into search is minutes of silence. A turn that routes to
    # something slow - search, a picture, a diagram, a deck, recall - gets its
    # tool's own line the moment that route is known (a few seconds in);
    # any other turn gets one generic bubble after this long. Lowered from 15 s
    # on 2026-08-27: a search answer took 15-25 s, so the bubble arrived a
    # breath before the answer and reassured nobody.
    IMESSAGE_CHAT_ACK_SECONDS: float = Field(default=6.0, gt=0, le=120)
    # Bursts: people text in fragments, so each addressed fragment is judged
    # by meaning (routing/readiness) before a reply - finished or not, and
    # wanting an answer or not. Off means every message is answered as it
    # arrives, the behaviour before 2026-08-28.
    IMESSAGE_CHAT_READINESS_ENABLED: bool = True
    # The safety cap on "not finished": a fragment judged incomplete that
    # nothing follows is answered after this long anyway.
    # 45 s: a wrong "not finished" costs at most this long (the first live
    # group turn waited the full 90 s on a finished question, 2026-08-28).
    IMESSAGE_CHAT_BURST_CAP_SECONDS: float = Field(default=45.0, gt=0, le=900)
    # A turn that failed because nobody answered (the backend restarting, the
    # database away) is parked and retried every poll for this long, with one
    # "give me a minute" bubble after the notice delay; only then the apology.
    IMESSAGE_CHAT_RETRY_MINUTES: float = Field(default=10.0, gt=0, le=180)
    IMESSAGE_CHAT_RETRY_NOTICE_SECONDS: float = Field(default=60.0, ge=0, le=3600)
    # How far back a turn that failed with a final error is replayed, once,
    # when the worker starts after a deploy - the fix that a failure needed
    # arrives as a deploy, and nobody should have to notice and resend.
    IMESSAGE_CHAT_REPLAY_HOURS: float = Field(default=24.0, ge=0, le=168)
    # Where the operator is told, once a day per chat, that the assistant
    # was added to a group it must stay silent in (a participant is not an
    # approved user). Empty means nobody is told.
    OPERATOR_ALERT_PHONE: str = ""
    # Scheduled tasks: anything a person asked to have done later or on a
    # schedule, run as a chat turn under their identity and delivered on the
    # channel they asked from. The loop shares the discovery worker process.
    SCHEDULED_TASKS_ENABLED: bool = True
    SCHEDULED_TASKS_POLL_SECONDS: float = Field(default=30.0, gt=0, le=600)
    # Longer than a chat turn's own timeout, so a live turn is never reclaimed
    # by a second worker mid-flight.
    SCHEDULED_TASK_LEASE_SECONDS: float = Field(default=900.0, gt=0, le=3_600)
    # How late a slot may be and still be worth firing. A briefing the
    # worker slept through arrives wrong, not late, so a missed slot is
    # skipped rather than delivered at the wrong hour.
    SCHEDULED_TASK_STALE_SECONDS: float = Field(default=3_600.0, gt=0, le=86_400)
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
    # Which cross-encoder scores the shortlist: "local" is the in-process ONNX
    # MiniLM above; "service" is the vLLM reranker the history-recall stage
    # already runs, adapted back to log-odds so the attribution margin keeps
    # its meaning. A swap is judged by evaluate_discovery_ranking, never by
    # eyeballing, which is why both stay selectable.
    DISCOVERY_PLACE_RESOLVER: Literal["", "nominatim"] = ""
    DISCOVERY_PLACE_RESOLVER_URL: str = "https://nominatim.openstreetmap.org/reverse"
    DISCOVERY_PLACE_RESOLVER_USER_AGENT: str = "AniOS/1.0 (local personal assistant)"

    GPU_HANDOFF_SLEEP_LEVEL: int = Field(default=1, ge=1, le=2)
    GPU_HANDOFF_TIMEOUT_SECONDS: float = Field(default=120.0, gt=0, le=600)
    IMAGE_PROVIDER_TIMEOUT_SECONDS: float = Field(default=600.0, gt=0, le=3600)
    # How long a job waits for ComfyUI to come back after it went away mid-run
    # before the job is given up - then it is resubmitted exactly once. On the
    # desktop the process exits cleanly at the VM's memory ceiling and Docker
    # restarts it within seconds; a cold model load after that is ~2 minutes,
    # so the budget covers the restart, not the reload.
    IMAGE_PROVIDER_RESTART_WAIT_SECONDS: float = Field(default=90.0, ge=0.0, le=600.0)
    IMAGE_PROVIDER_POLL_SECONDS: float = Field(default=0.5, ge=0.1, le=10)
    IMAGE_MAX_CONCURRENCY: int = Field(default=1, ge=1, le=4)
    ARTIFACT_STORAGE_ROOT: str = "data/artifacts"
    # Immutable as-of partitions of daily market history (backend/market/store.py).
    MARKET_DATA_ROOT: str = "data/market"
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
    # How many slide calls a progressive deck may have in flight at once.
    #
    # The outline fixes every slide's title, purpose and layout, and each slide
    # call is told what came before from the *outline* rather than from earlier
    # answers, so the calls never depended on each other - they were sequential
    # only because they were written as a loop. One deck measured on 2026-09-02
    # spent 44-64 s per slide with the engine near idle, which is a slide a
    # minute for a deck nobody can use until the last one lands.
    #
    # Each concurrent worker gets its own inference client, because one client
    # serialises its own requests through a per-instance lock (see the comment
    # on PresentationProvider's factory). Raising this spends more of the
    # serving engine's batch on one deck; the ceiling is deliberately low
    # because a deck is background work and chat is not.
    #
    # Measured here 2026-09-02 on the two-Spark DeepSeek deployment, one
    # 6-slide deck per arm, research off: concurrency 1 took 130.65 s, 2 took
    # 75.66 s (1.73x), 4 took 50.30 s (2.60x), 8 took 51.89 s (2.52x). Four is
    # the knee - eight bought nothing and would take more of the batch from
    # chat. Two further 1-vs-4 runs measured 1.86x and 1.46x, so the honest
    # range is 1.5-2.6x with a median near 1.9x; the spread is other traffic on
    # the same deployment. What would change it: a serving change that raises
    # concurrent decode throughput, or an outline pass that stops being serial.
    #
    # Four rather than two because of what it costs the foreground, measured
    # the same day with short chat probes running throughout: no deck, median
    # 0.17 s / p95 0.24 s; a deck at 2, median 0.26 s / p95 0.39 s, deck 80.4 s;
    # a deck at 4, median 0.27 s / p95 0.40 s, deck 66.5 s. Going from two to
    # four costs chat about 10 ms of median and buys the deck 17%. Nearly all
    # of the foreground cost is a deck running *at all*, not how wide it is -
    # which is the number to re-take if `--max-num-seqs` (6) ever changes,
    # since four slots of six is what makes this a real tradeoff.
    PRESENTATION_SLIDE_CONCURRENCY: int = Field(default=4, ge=1, le=8)
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
    # How long background work yields to interactive work before going anyway.
    #
    # Without a bound this is not a priority, it is starvation: `background()`
    # waited for a moment with *zero* interactive requests in flight, and on
    # 2026-09-02 a deck spent 7m09s on its outline call while chat ran at 17-27
    # calls a minute. At that rate the quiet moment never arrives, and the job
    # a person is watching makes no progress at all while the machine looks
    # idle - vLLM reported `Waiting: 0 reqs` and 0.5% KV cache throughout.
    #
    # Yielding is still the common case: a quiet machine acquires on the first
    # poll and nothing changes. This only decides how long a starved background
    # task waits before joining the batch, which the serving engine is
    # configured to handle - see the module docstring in core/model_gate.py.
    #
    # What proceeding anyway costs the foreground, measured 2026-09-02 with
    # short chat probes running throughout: median 0.17 s -> 0.26 s and p95
    # 0.24 s -> 0.39 s while a deck runs. That is the price of a deck making
    # progress at all, and it is paid only while one is running. Twenty seconds
    # is a judgement, not a measurement: long enough that a normal burst of
    # chat still goes first, short enough that a person watching a progress bar
    # sees it move. Lower it if background work still reads as stalled.
    MODEL_GATE_MAX_WAIT_SECONDS: float = Field(default=20.0, ge=0.0, le=600)
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
    VISION_SEARCH_GROUNDING_ENABLED: bool = True
    # Sized for one tool call plus the thinking a reasoning model spends
    # before emitting it; the 4B stops early so the headroom is free.
    VISION_SEARCH_DECISION_MAX_TOKENS: int = Field(default=1_024, ge=32, le=4_096)
    # The answer is ~16 tokens of JSON; the budget is not the answer. At 16 a
    # reasoning model is guaranteed to truncate mid-thought, which on
    # ds4-server surfaced its monologue as `content` - "unparseable content on
    # every upload" - and was misread as a model-capability problem. The
    # schema is still the grammar; the headroom is for thinking.
    IMAGE_INTENT_MAX_TOKENS: int = Field(default=1_024, ge=8, le=4_096)

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
    # How much of each source survives into the prompt, and how much the whole
    # search may carry.
    #
    # These were hardcoded in the internet MCP server - 500 characters per
    # result, 3,500 for the payload - and they silently outranked
    # SEARCH_MAX_CONTENT_CHARS above, which the provider applied and the
    # serializer then discarded. 500 characters is about eighty words: enough
    # for a snippet, not for a benchmark table or a specification, which is why
    # answers kept being assembled from titles. The payload cap exists to stay
    # under MCP_MAX_RESULT_CHARS, since a generic truncation mid-JSON would
    # corrupt the result rather than shorten it.
    SEARCH_RESULT_CHARS: int = Field(default=2_500, ge=200, le=8_000)
    SEARCH_PAYLOAD_CHARS: int = Field(default=24_000, ge=1_000, le=40_000)
    # The bound on any tool result, not only search. Untrusted output reaches
    # the prompt through here, so it stays a deliberate ceiling rather than
    # something a server can raise for itself.
    MCP_MAX_RESULT_CHARS: int = Field(default=32_000, ge=1_000, le=60_000)
    SEARCH_DEPTH: Literal["basic", "advanced"] = "advanced"
    # Brave Search, the first rung of the chain since 2026-08-25: a broad,
    # fresh index on a plan metered in dollars ($5 per 1,000 requests, $5 of
    # credit a month) whose headers promise no stop at the credit's edge -
    # the monthly limit below is the stop, held under the credit so the card
    # is never charged. Google's Custom Search JSON API, the first choice,
    # is closed to new customers. Empty disables the rung.
    BRAVE_SEARCH_API_KEY: str | None = Field(None, alias="BRAVE_SEARCH_API_KEY")
    BRAVE_SEARCH_MONTHLY_LIMIT: int = Field(default=900, ge=0, le=100_000)
    BRAVE_SEARCH_QUOTA_DB_PATH: str = "data/search/brave_search_quota.sqlite3"
    # The chain is order, not mixing: the first rung answers until its period
    # is spent, then the next. Names not configured are skipped.
    SEARCH_PROVIDER_ORDER: str = "brave,google,tavily"
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
    GOOGLE_SEARCH_MODEL: str = "gemini-3.1-flash-lite"
    GOOGLE_SEARCH_TIMEOUT_SECONDS: float = Field(default=30.0, gt=0, le=120)
    # Covers reasoning tokens as well as the answer; a small budget can end a
    # grounded reasoning response before it emits any attributable text.
    GOOGLE_SEARCH_MAX_OUTPUT_TOKENS: int = Field(default=2_048, ge=128, le=8_192)
    # Bound local Google *search queries* independently of the provider account
    # quota. The unit is queries, not prompts: one Gemini 3 prompt may run
    # several separately billed searches, so 450 queries a day is roughly two
    # hundred to four hundred prompts.
    #
    # The floor is the reservation each call holds, not 1. A limit below it
    # refuses every call before it starts, and does so as "budget exhausted"
    # rather than "misconfigured" - a provider silently dead with nothing in
    # the log to say why (found in review, 2026-08-29).
    GOOGLE_SEARCH_DAILY_LIMIT: int = Field(default=450, ge=10, le=500)
    # The month is the ceiling that stands between a mistake and a bill:
    # grounded search is included up to 5,000 queries a month and $14 per
    # thousand after it. It had no field here at all and was read straight from
    # the environment by the search subprocess, so `GOOGLE_SEARCH_MONTHLY_LIMIT=50000`
    # in .env was accepted in silence and would have billed. Bounded here so a
    # value past the included allowance fails at startup instead.
    GOOGLE_SEARCH_MONTHLY_LIMIT: int = Field(default=4_800, ge=10, le=5_000)
    # Stores provider/period/count only; no queries or result content are retained.
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
