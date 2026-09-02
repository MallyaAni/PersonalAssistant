# ML system design

How the models in AniOS are served, retrieved from, and decoded - and why each
setting is what it is. This is the ML systems engineering behind the
architecture: the decisions an ML engineer makes about quantisation, KV
cache, parallelism, context against memory, thresholds, and decoding, each
written as **the decision, the options considered, what was measured, why,
and what would change it**. Everything here was measured on this hardware;
nothing is quoted from a model card. The full numbers and transcripts live in
[MODEL_EVALUATION.md](MODEL_EVALUATION.md) and [DGX_MIGRATION.md](DGX_MIGRATION.md);
the serving scripts themselves are in `deploy/spark/`. The canonical diagram
is [ml-serving-design.svg](diagrams/ml-serving-design.svg).

This document is owned under the rule in [AGENTS.md](../AGENTS.md): any change
to a serving flag, quantisation, model, cache, context, threshold, or token
budget updates it in the same change, with what was tried and rejected.

## 1. The reply model: DeepSeek-V4-Flash on two DGX Sparks

**Decision.** DeepSeek-V4-Flash (284B total, 13B active MoE), the official
**FP8** checkpoint, served by vLLM (`ghcr.io/anemll/dspark-vllm-gx10:0.1.1`,
vLLM 0.25.2) tensor-parallel across spark1 and spark2 (`--tensor-parallel-size
2`, pipeline 1, NCCL over the RoCE fabric), with `--kv-cache-dtype
nvfp4_ds_mla`, `--max-model-len 1048576`, `--gpu-memory-utilization 0.81`,
`--max-num-seqs 6`, `--max-num-batched-tokens 8192`, prefix caching and
chunked prefill on (both vLLM defaults), speculative decoding off, and the
`flashinfer_b12x` MoE backend with DeepGEMM disabled. Every text role runs
here. Where each flag came from is the table at the end of this section.

**Options considered.**

| Candidate | Measured | Why not |
| --- | --- | --- |
| Dense models (e.g. Gemma 4 31B at NVFP4) | 7 tok/s | The GB10 has 273 GB/s of memory bandwidth; a dense model streams every weight per token. "Dense models die here." |
| Qwen3.8-27B BF16 on vLLM 0.17.1 | 4.57 tok/s decode, 71.7 s to first *content* (thinking streams as unrendered `reasoning`), ~166 s per reply with MTP vs ~11 s for DeepSeek; prefill 1,051 tok/s (2x DeepSeek, the one speed it wins) | Quality judged blind: Qwen won 18-9 with 19 ties and 8-0 on grounding categories - "better answers do not survive 50 to 90 second replies against 11". FP8 5.35, NVFP4 6.20-8.15 tok/s did not close the gap either. |
| DeepSeek 2.4-bit (IQ2_XXS, 86.7 GB) on ds4-server, one Spark | 10-19 tok/s decode, ~14.5 mean; MTP acceptance 90.9% on code, 64.3% on prose; disk KV cache 18.5x at 11.7k tokens | `response_format` with a JSON schema was ignored ("Paris" for `{"capital": ...}`). Structured output is an engine property, and three outages traced to it. ds4 is a single-user latency engine; vLLM is a serving engine. |
| NVFP4 weights instead of FP8 | 41.4 vs 41.5 tok/s elsewhere - noise; 166.9 GB vs 168.3 GB on disk, the 4-bit build is *larger* | FP8 is the release format; NVFP4 is a re-quantisation with no measured upside. |

**Measured, deployed configuration.**

| Metric | Value |
| --- | --- |
| Decode: math / prose / code / counting | 40.0 / 29.8 / 63.5 / 79.5 tok/s |
| Aggregate at concurrency 1 / 2 / 4 / 6 | 85.7 / 135.7 / 282.6 / 383.5 tok/s (published reference: 61.0 / 91.7 / 151.1 / 197.3) |
| Time to first token, 11.7k-token prefix, cold / warm | 5,909 ms / ~512 ms |
| Routing call (one native tool decision) | 1.78 s median, 2.27 s worst of three |
| KV pool at 0.81 utilisation | ~8.7 GiB, of which 1M context needs 7.54 GiB |

The MoE backend was the single largest win and cost nothing: forcing
`flashinfer_b12x` (with `VLLM_MOE_USE_DEEP_GEMM=0`, because DeepGEMM otherwise
wins the priority order silently) took code decode from 26.2 to 63.5 tok/s
(2.42x) and prose from 25.9 to 29.8. "A silent kernel fallback costs more
than any model choice on this list, and it never appears as an error" - grep
the boot log for the backend line after every image or driver change.

**Why.** A 13B-active MoE is what 273 GB/s can decode at conversational
speed; ~149 GiB loaded does not fit one 121.7 GiB node beside anything, and
fits two with ~93 GiB left for KV and the vision model. The blind read-off
and the judge harness (section 10) chose DeepSeek over Qwen on the only
axis that survives production: an answer in 11 seconds beats a slightly
better one in 90.

**What would change it.** `nvfp4_ds_mla` carries a documented accuracy
caveat; `fp8_ds_mla` halves the pool to ~700k tokens and removes it - the
first knob if long-context quality ever wobbles. The vLLM 0.21.1 + B12X image
is reportedly 9.2% faster at peak and 29.4% at concurrency 6 because
`torch.compile` works there and not on 0.25.2 - untested here. vLLM #40969
(a silent hang after 5-7 requests with `FULL_AND_PIECEWISE` cudagraphs and
chunked prefill, on exactly this hardware) describes the combination this
engine runs; it has not reproduced in 1,511 requests since the 2026-08-24
boot, and `--enforce-eager` is the fallback at a 20-30% cost if it ever
does. Speculative decoding needs its own load test (section 3).

**Every serving flag, and where it came from.** Three origins are possible:
*measured here* (a number in this repository chose it), *inherited* (taken
from the DSpark reference command for this image, or from someone else's
documented failure, and not re-measured here), or *vLLM default* (not set;
listed because it matters). Inherited is not a criticism - it is a flag
nobody here can yet defend with a number, and the last column says what
number would.

| Flag | Value | Origin | Why, and what it trades | What would change it |
| --- | --- | --- | --- | --- |
| `--tensor-parallel-size 2`, `--nnodes 2` | 2 nodes, TP | Measured here | ~149 GiB loaded does not fit one 121.7 GiB node; TP splits every layer so both GB10s stream weights at once. Pipeline parallel would idle one node per stage. | A single node with the memory, or a smaller reply model. |
| `--moe-backend flashinfer_b12x` + `VLLM_MOE_USE_DEEP_GEMM=0` | kernel | Measured here | The FlashInfer CuteDSL fused MoE written for SM12x - the only MoE path that targets this architecture. vLLM's priority order puts the generic DeepGEMM JIT path first, so it must be disabled by env; `VLLM_USE_B12X_MOE=1` alone selects nothing and stays only because it is harmless. 1.12x math, 1.15x prose, 2.42x code over the `DEEPGEMM_MXFP4` fallback. The check is one boot-log line: `Using 'B12X_MXFP4' Mxfp4 MoE backend`. | A newer kernel beating 63.5 tok/s on the code probe, measured in the same harness. |
| `--kv-cache-dtype nvfp4_ds_mla` | 4-bit KV | Inherited, then measured | Stores the MLA latent at 4 bits: 2,291,294 tokens of KV at 0.81. `fp8_ds_mla` halves the pool and removes a documented accuracy caveat. The attention kernel it selects is `FLASHMLA_SPARSE`. | Any long-context quality wobble - `fp8_ds_mla` is the first knob. |
| `--block-size 256` | tokens per KV block | Inherited, not measured | vLLM sets no default (the backend picks); the sparse-MLA kernel works in 64-token blocks and 256 is a multiple of it. A 1M sequence is 4,096 blocks instead of 16,384 (smaller block tables, cheaper scheduling) against coarser prefix-cache hits (a hit needs a whole 256-token block) and at most 255 wasted tokens per sequence - ~20 MB across six. With 87.9% of prompt tokens hitting the cache since boot, granularity is not costing much. | TTFT and decode at 64 versus 256 on the 11.7k-prefix probe. |
| `--max-model-len 1048576` | context | Measured here | Fits: the engine reports 2.19 concurrent 1M requests. Demand is median 4.4k, p90 11.7k, max 16.1k over 61 real turns, so it is kept because it fits. Needs `VLLM_ALLOW_LONG_MAX_MODEL_LEN=1`. | A second GPU tenant on spark2 that needs the KV memory. |
| `--max-num-seqs 6` | sequences per step | Inherited, not measured | vLLM's default is 128. Six is admission control for a household: the KV pool holds ~190 p90-sized conversations and has preempted nothing in 1,511 requests, so memory is not the limit - the foreground chat's latency is. On a bandwidth-bound decoder every extra sequence rides the same weight stream almost free, which is the 85.7 to 383.5 tok/s aggregate at 1 to 6. | Per-stream latency at 8 and 12 concurrent, with a deck running. |
| `--max-num-batched-tokens 8192` | tokens per step | Inherited, not measured | vLLM's default is 2,048. This is the per-step token budget; with chunked prefill on, an 11.7k prompt is prefilled in two chunks between decode steps (5.9 s cold). A larger budget speeds that prefill and lengthens the decode stall for whoever is mid-reply; a smaller one does the reverse. | The foreground stall during a deck's prefill at 4,096 versus 8,192. |
| `--gpu-memory-utilization 0.81` | fraction of 121.69 GiB | Measured here | 0.90 is refused on spark2 (it also hosts the vision model) and the head hangs; 0.78 fit 406,016 tokens; 0.81 fits 1M with ~1.9 GiB of margin on spark2. Section 2. | Trimming the VLM's KV widens the margin; a Spark without the VLM could go higher. |
| `--enable-prefix-caching` | on | vLLM default, measured | 87.9% of prompt tokens served from cache since boot; 512 ms warm against 5,909 ms cold at 11.7k. The prompt is laid out for it (section 3). | Nothing; the layout work is what keeps it earning. |
| chunked prefill | on | vLLM default | Not a flag in the script. Recorded as *off* in this document until 2026-08-25 while the engine ran it on - the boot line `Chunked prefill is enabled with max_num_batched_tokens=8192` is the fact. | vLLM #40969 reproducing here: the engine going quiet after a few requests with nothing in the log. Then `--enforce-eager`. |
| speculative decoding | off | Measured here | Boots, passes a smoke test, dies on the first real request at this utilisation; MTP crashed the Qwen engine outright. Section 3. | Its own load test at 0.81 with the current image. |
| `--generation-config vllm` | sampling source | Inherited | Do *not* load the checkpoint's `generation_config.json`; every request's sampling comes from the caller (temperature 0 for decisions, section 8). With `auto`, DeepSeek's recommended sampling would silently apply to any request that omitted it, and grammar-constrained decisions would drift. | Nothing - the decoding policy depends on it. |
| `--tokenizer-mode`, `--tool-call-parser`, `--reasoning-parser` = `deepseek_v4`, `--enable-auto-tool-choice` | parsers | Required by the model class | Without the reasoning parser the model's thinking streams as content - the Qwen lesson of 71.7 s to first *content*. Native tool calls are how routing decisions come back as JSON. | A model change. |
| `--distributed-executor-backend mp` | executor | Inherited | Multiprocessing workers with `--nnodes`/`--node-rank`; Ray would add a scheduler with nothing to schedule. | More than two nodes. |
| compile and CUDA graphs | `VLLM_COMPILE`, `FULL_AND_PIECEWISE` | vLLM default | Not set; listed because #40969 names this mode and because the 0.21.1 image is reportedly 9-29% faster on `torch.compile` alone. `VLLM_USE_BREAKABLE_CUDAGRAPH=0` is inherited with the image. | The 0.21.1 comparison, run here. |
| node-local JIT caches, `VLLM_ENGINE_READY_TIMEOUT_S=3600`, `TORCH_CUDA_ARCH_LIST=12.1a`, worker before head | boot | Inherited from documented failures | A shared cache races `torch.compile` and half-writes cubins; the first boot JIT-compiles for longer than the default ready timeout; a head started first waits forever at `parallel_state`. Section 12. | Nothing. |

## 2. Memory arithmetic: context, KV cache, and the utilisation ceiling

**Decision.** 1M context at 0.81 utilisation, and the ceiling is decided by
spark2, not spark1.

**The arithmetic.** Weights plus overhead are ~89.9 GiB per node; every
point of utilisation is ~1.2 GiB of KV. At 0.78 the pool was 5.0 GiB and the
engine reported 406,016 as the largest context that fit; at 0.81 it is ~8.7
GiB against the 7.54 GiB that 1M needs. The cache is small in *bytes* because
DeepSeek uses multi-head latent attention with a single KV head and
`nvfp4_ds_mla` stores it at 4 bits: an empty box reports 10.68 GiB =
1,374,118 tokens. Demand is nowhere near it - over 61 real turns the prompt
was median 4.4k, p90 11.7k, max 16.1k tokens. **1M is kept because it fits,
not because it is needed.**

**What the engine reports (boot of 2026-08-24), and why it wins.** Available
KV cache memory 14.85 GiB per rank; GPU KV cache size 2,291,294 tokens;
maximum concurrency for 1,048,576 tokens per request 2.19x. That is 6.8 KiB
per token per rank, so a full 1M context costs ~6.6 GiB and two fit with
room, which is exactly the 2.19x it prints. The hand arithmetic above found
8.7 GiB where the engine found 14.85: the 89.9 GiB for weights plus overhead
was taken from an earlier boot, and the ~6 GiB it did not know about is the
margin that keeps 0.81 safe on spark2 - do not spend it. When the estimate
and the boot log disagree, the boot log is the number. It also explains a
gauge that looks broken: `vllm:kv_cache_usage_perc` reads 0.0 while an
11.7k-token conversation is being answered, because 11.7k of 2.29M is 0.5%.

**Utilisation: what 95% means (measured 2026-08-24).** Idle, the GB10 reads
0% and 12.5 W; one stream generating reads 94-95% utilisation, ~35 W, KV
0.0%, 28.6 tok/s. None of that is spare capacity waiting for a flag.
`nvidia-smi` utilisation is the share of the sample window in which *any*
kernel was resident, not how busy the SMs were; a decode step is a chain of
small kernels each waiting on memory, so the counter saturates while the
arithmetic units idle - which is what 35 W says. The bound is the 273 GB/s
LPDDR5x bus: every token streams the 13B active parameters once, ~13 GB at
FP8, half per rank, ~24 ms at full bandwidth, a ceiling near 42 tok/s for a
single stream. Prose and math (29.8, 40.0) sit at 70-95% of it. Code and
counting (63.5, 79.5) exceed it, which the naive roofline cannot explain;
the plausible reason - repetitive text routing to a stable subset of experts
whose weights stay cache-resident - is unmeasured, and a DRAM-throughput
trace would settle it. The only ways to draw more from the box are more
sequences per step, because the weight stream is shared (383.5 tok/s at
six), and speculative decoding, which returns several tokens per stream per
step (off, section 3). For a single conversation there is no knob.

**Why spark2 bounds it.** Utilisation is a fraction of the whole 121.69 GiB
pool and *both* ranks must satisfy it. spark1 has ~116 GiB free; spark2 also
hosts the vision model and has ~105 GiB. 0.90 asks for 109.5 GiB - fine on
spark1, refused on spark2, after which the head hangs at `parallel_state`
waiting for a rank that already died. 0.81 leaves ~1.9 GiB of margin on
spark2, and the way to widen it is to trim the VLM's KV, never to raise
this. The VLM takes its 0.09 from what remains, enforced by unit ordering
(`After=ds4-worker.service`, applied 2026-08-25).

**Two ways this went wrong before.** `--kv-cache-memory-bytes` is a hard cap
that does not scale with utilisation: pinned at 5 GiB it refused 1M at every
utilisation value through four restarts, and is banned on the reply model
(it is the *right* tool on the VLM, section 4). And a comment placed inside
the backslash-continued exec block silently dropped every flag after it -
`--max-model-len`, `--gpu-memory-utilization`, the parsers, the port - so
the server ran vLLM defaults for two hours with nothing in the log saying so.
Commentary lives in the script header now, never in the exec block.

**What would change it.** Any second GPU tenant on either Spark is sized
against the *measured free* number, not the total; over-allocating a GB10
does not OOM cleanly, it hangs the box, and there is no remote console.

## 3. Speculative decoding, batching, and caches

**Speculative decoding: off.** On the Qwen candidate, `--speculative-config
mtp` produced `cudaErrorIllegalAddress` and killed the engine with every
in-flight request, recurring at a single running request; acceptance was a
healthy 2.16-2.31 tokens per step right up to the crash. On DeepSeek under
vLLM a high utilisation plus speculation boots, passes a smoke test, and dies
on the first real request, so it stays off until it gets its own load test.
The ds4 measurements set expectations for when it returns: block size 5 (7
and 10 boot, then crash on every generation), acceptance 90.9% on code
against 64.3% on prose, and below about 1.5 tokens per step the drafter costs
more than it returns.

**Batching.** `--max-num-seqs 6` and `--max-num-batched-tokens 8192` are
inherited from the DSpark reference command, not measured here, against vLLM
defaults of 128 and 2,048 - the flag table in section 1 says why they hold
up (admission control for a household on a decoder where each extra
sequence is nearly free: 85.7 to 383.5 tok/s aggregate at 1 to 6, zero
preemptions in 1,511 requests) and which measurement would move them. Nothing
moves a model between hosts at request time.

**Foreground priority, and its bound.** Redis gives a foreground chat priority
over background work (`MODEL_GATE_*`). Priority with no bound is starvation,
though, and it was: `background()` waited for a moment with *zero* interactive
requests in flight, which is instant on a quiet machine and never on a busy
one. On 2026-09-02 a deck spent 7m09s on one outline call while chat ran at
17-27 calls a minute and this engine reported `Waiting: 0 reqs` at 0.5% KV
usage — nothing was queued, the deck was declining to start. Background work
now yields for `MODEL_GATE_MAX_WAIT_SECONDS` (20 s, a judgement) and then joins
the batch, which is what `--max-num-seqs 6` exists to share.

**What a deck costs the foreground**, measured 2026-09-02 with short chat
probes running throughout, one 6-slide deck per arm:

| Arm | Chat median | Chat p95 | Deck |
| --- | --- | --- | --- |
| No deck running | 0.17 s | 0.24 s | — |
| Deck at concurrency 2 | 0.26 s | 0.39 s | 80.4 s |
| Deck at concurrency 4 | 0.27 s | 0.40 s | 66.5 s |

This is the measurement the flag table asks for at line `--max-num-seqs`
("per-stream latency with a deck running"), taken at 2 and 4 rather than 8 and
12. Two readings decide `PRESENTATION_SLIDE_CONCURRENCY`: almost the whole
foreground cost is a deck running *at all* rather than how wide it is, and
widening from 2 to 4 buys the deck 17% for about 10 ms of chat median. Four of
six sequence slots is what makes this a tradeoff at all, so re-take it if
`--max-num-seqs` moves.

**Prefix caching: on, and the prompt is laid out for it.** At an 11.7k-token
prefix, first token is 5,909 ms cold and ~512 ms warm; the cache commits
after the *second* call (5,909 / 6,383 / 496 / 539 / 516 ms). The win was
being thrown away by the prompt order: per-turn blocks (memory-save notes,
recalled remarks, search results) sat *ahead* of the append-only history,
and one volatile byte early invalidates everything after it. Reordered, the
second turn of a 34k conversation went from 33.1 s to 2.0 s. Placement
matters too: the volatile block after the history as a *user* message gives
8.26x; as a *system* message the chat template hoists it back to the front
and gives 1.05x. The synthetic test had shown 16x while the shipped code
showed nothing - measure what ships.

**LMCache: rejected.** Both documented Spark attempts failed - an L1
allocation bug that made L2 unreachable under load *and* restored KV that
diverged from computed KV at temperature 0; a permanent deadlock at
"Wrapping 170 KV cache tensors for IPC" on a version mismatch. Where it
worked it was ~300x on a 32k restore, which is why it is worth re-testing
when the pins move; today the supported path is vLLM's own prefix cache.

## 4. Vision: Qwen3-VL-8B, AWQ, on spark2

**Decision.** `cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit` (7.55 GB) at
`--gpu-memory-utilization 0.09` with an explicit `--kv-cache-memory-bytes`
of 3 GiB, 16k context, 4 sequences, at most 4 images per prompt,
`--mm-processor-cache-gb 0`, prefix caching on. Separate from DeepSeek
because that build cannot read pixels.

**Options considered.** Step3-VL-10B (8.47 GB) wins hard GUI grounding
(ScreenSpot-Pro 51.6) "and it would be the pick if AniOS drove an interface.
It does not." GLM-4.6V-Flash (8.86 GB). Qwen3-VL-8B took it on DocVQA 96.1 /
ScreenSpot 94.4 / OCRBench 89.6 / MMMU 78.7 - reading photographs and
documents is the job. **AWQ rather than NVFP4** because the CUTLASS FP4
kernels target sm_120 and silently emit wrong output on sm_121 (vLLM
#50925): on a vision model that failure would look like bad OCR, not an
error.

**Why the explicit KV cap here and never on the reply model.** The profiler
sizes KV from what it observes free at startup: trusting the fraction gave
7.46 GiB of KV on top of 7.1 GB of weights and left the box 538 MB from a
hang. Capped, it behaves the way a limit should - asked for 16k against too
small a cache it refused to start and named the number it needed. The
multimodal processor cache defaults to 4 GiB, a third of the budget, and
nothing warns you.

**Measured.** ~10 GB resident, KV for 21,840 tokens, ~2.4 GB free and stable
under load; through `/api/v1/vision/analyze`, 9.5 s cold then 0.5-1.1 s warm,
reading a serial number verbatim. `VISION_MAX_TOKENS` is 1,536 because two
real photographs came back at 488 tokens against the old 512 - an ordinary
upload sat 24 tokens from truncated JSON and a 502.

## 5. Embeddings and reranking

**Text and image embeddings.** `nomic-embed-text-v1.5` on vLLM (pooling
runner, 2,048 context, 16 sequences, utilisation 0.06 - the weights load in
0.26 GiB and 0.15 had reserved 2.4 GiB nothing used) and
`nomic-embed-vision-v1.5` on CPU (ONNX). They are one **aligned 768-d
space**: one vector column, one distance threshold, and a sentence can find a
picture. That alignment is a constraint as much as a feature - replace the
text model alone and nothing raises; image search becomes noise presented as
an answer ([ADR 0014](adr/0014-embedding-upgrade-brief-detail.md)). So every
stored vector carries a model+scheme signature, retrieval filters on it, and
one idempotent backfill rebuilds a space; a swap degrades to "not yet
rebuilt", never to wrong answers.

**Vector store: pgvector HNSW in Postgres, not FAISS (measured 2026-08-25).**
Every vector column carries an HNSW index with cosine ops - nine of them,
from `conversations` to `tool_descriptors` - inside the same database that
holds the rows, their owners, and their encryption. That is the decision:
nearest-neighbour search is a `WHERE user_id = ? ORDER BY embedding <=> ?`
that the planner joins, filters and transacts like any other query, and a
backup of the database is a backup of the index. The numbers at the scale
this system actually runs: 439 embedded vectors across all tables (217
conversation turns, 89 entities, 88 procedures, 21 pictures, 12 semantic
facts, 10 summaries), a 22 MB database, and a top-10 cosine search over the
conversation store in **0.49-0.65 ms** - so small that the planner chooses a
sequential scan and never touches the index. Pushed to a size this system
has not reached, a synthetic 20,000 x 768-d table built its HNSW index in
1.95 s, took 132 MB, and answered top-10 in **0.13-0.21 ms** through the
index. FAISS would add a second store to keep in step with the rows - no
ownership filter, no transaction, its own persistence and rebuild story,
and a separate process or the backend's memory to live in - to make a
sub-millisecond search faster. *What would change it:* millions of vectors
(pgvector's HNSW build time and RAM grow with the graph; FAISS IVF-PQ
compresses where pgvector does not), GPU-batched retrieval over many queries
at once (FAISS-GPU's case; nothing here issues batches), or a measured
recall problem at `ef_search` that raising it does not fix.

**Web search providers: Brave first, Tavily second (decided 2026-08-25).**
The chain is order, not mixing: one rung answers until its period is spent,
then the next, and only when every rung is spent does the reply say so. The
choice was forced and then measured. Google's Custom Search JSON API - the
obvious free rung at 100 queries a day - is closed to new customers and ends
in January 2027; Gemini grounding, wired as the primary, needs a paid tier
(429 on the search tool while the same key answers normally) and stays off.
Brave's Search plan meters in dollars ($5 per 1,000 requests, $5 of credit a
month) and its headers report the monthly window as `0;w=2678400` - nothing
on the wire stops at the credit's edge - so the stop is local: 900 requests
a month in SQLite beside the Google counter, with the same count kept in
Redis for the pre-flight. What each rung returns, measured on the same
Canggu-events query: Brave gives real event pages (Eventbrite, Meetup) with
198-346-character descriptions; Tavily at `advanced` depth gives extracted
page text up to the 2,500-character cap but at two credits a query, ~500
searches from its free 1,000. Brave leads because the index is broader and
fresher for the questions people here ask and its free volume is twice
Tavily's; Tavily follows because its richer text is worth more once Brave is
out than spent first. Together ~1,400 free searches a month against ~500
before. *What would change it:* a query class where snippets are not enough
(then fetch the top pages rather than reorder), or Brave's free credit
changing - the order is one setting, `SEARCH_PROVIDER_ORDER`.

**Should the embedder be replaced?** No, measured twice (2026-08-23 and
08-25). At ~500 vectors a nearest-neighbour search is dominated by threshold
calibration, not encoder rank; the live 100%-failure cases (NULL vectors)
mattered more than any MTEB delta. The named target at the next hardware
step is the **Qwen3-VL-Embedding + Qwen3-VL-Reranker** pair: one family, one
unified text/image/video space, Matryoshka output that keeps the 768-wide
columns, quantisation-aware, vLLM-servable, the reranker on the same
`/v2/rerank` contract already deployed - and ~10+ GiB that today's boxes do
not have. jina v4/v3 rejected: CC BY-NC, no vLLM support.

**The reranker.** `Qwen3-Reranker-0.6B` on vLLM with the documented
classifier `hf_overrides`, `--max-model-len 2048`, 4 sequences, utilisation
0.03 (1.2 GiB of fp16 weights plus headroom). 2048 is a memory decision: the
attention mask scales O(len^2), and at 4,096 spark1 idled at 3 GiB free -
thinner than a box with no BMC should sit; the trim bought back 2 GiB.
History recall fetches the top 40 by vector and lets the cross-encoder cut
them to 12, fail-soft to cosine order on any error; live, the answer scored
0.987 against 0.293 for a lexical decoy. On this build `/v1/rerank` and
`/rerank` reset the connection and `/v2/rerank` answers - the wire is
measured, not assumed.

**Web results are ordered by the main model, not the 0.6B reranker
(2026-08-25).** They arrived in the providers' order - Brave's index order,
which carries no score at all, or Tavily's own - and neither reads the
question: an Arlington weekend query put a festival at Snowshoe, West
Virginia among the listings. The deployed cross-encoder was tried first and
measured: asked to order four results for that question with "(asked from
Arlington, Virginia)" appended, it ranked the West Virginia festival
**second**, above an Arlington concert, with scores of 0.10-0.25 across the
board - a bi-encoder-sized model reading titles, not a judgement about place
and date. So the model that answers the person orders the results in one
grammar-constrained call (`prompts/search/rank.md`, ~1 s), given the
question, where they asked from, and today's date; the top
`SEARCH_MAX_RESULTS` are kept, the position is recorded on each result for
the trace, and every failure keeps the providers' order. What the ranking
knows about the person: the **place**, as a bias toward the local, never a
filter; and, since the same evening, what the turn already retrieved from
memory - interests, facts - as a **tie-breaker only**, allowed to choose
between results that answer the question equally well and never to lift a
worse one. The reply itself keeps interests out of ordinary answers
(section 7); ordering results that already answer the question is the one
place they cannot do that harm, because the ranker reorders and never adds.
Held on the real model by `test_search_rerank_behaviour.py`: the West
Virginia and the September results sink below every Arlington, on-date
one, and for a person whose interests name salsa, a Saturday salsa night
outranks the Saturday farmers market.

**Why Scout keeps its CPU cross-encoder.** The same service was routed into
Scout's shortlist ranking (probabilities converted back to log-odds so the
attribution margin kept its meaning) and measured by the labelled harness:
attribution **0.25 against 0.50** for the in-process MiniLM. Both are below
the harness's 0.60 floor - the local model's failures are wrong answers, the
service's are all margin-misses - so the default stays local and the swap is
a setting.

**Log-odds, not sigmoid.** The cross-encoder returns raw logits deliberately:
squashed, the gap between a correct attribution and a wrong one was 0.000
versus 0.001; in logit space the same pairs separate 0.29 from 1.49. Scores
run roughly -11 to +3 and are useless as absolutes (a correct Hiking match
scores -9.84; a find that should name nothing, -11.11), so attribution is a
**margin of 1.0 between best and runner-up**: wrong attributions stop at
0.29 and right ones start at 1.49. Interest strength is not reapplied on
this scale - multiplying -9.8 by 3/2 would push a *more* wanted interest
down. Over 21 labelled cases the stage reorders and never admits: no absolute
bar keeps 7 of 7 wanted finds without admitting 9 of 14 unwanted.

## 6. Retrieval thresholds, and how each was derived

Every cosine gate is a property of the embedding model and the store it
guards, and each was set from a measured distribution rather than inherited.
Re-measure all of them after any embedding change.

| Gate | Value | How it was set |
| --- | --- | --- |
| Semantic memory (text-text) | 0.35 | The baseline; explicitly *not* inherited by other spaces. |
| Document passages (knowledge store) | 0.5, top 6, two probes | Measured 2026-09-02 on the operator's itinerary: "whats on evening of day 1?" sat at 0.460 from the Day 1 chunk (0 results at 0.35); the same question naming the document sat at 0.332. Passages are longer and more varied than memory facts, and the reply answers only from the passages it is shown and abstains otherwise, so a looser gate costs a few extra passages, never a wrong answer. Each turn probes twice - the words typed and the follow-up resolver's restatement - and keeps the nearer distance per chunk; a pinned document (a reply to its bubble) scopes the search to that document. Section 13. |
| Passive recall of past turns | 0.45, top 3 | At 0.35 it answered 1 of 5 questions, 0.40 four, 0.45 all five, 0.50 no more while returning twice the turns; useful recalls sit 0.25-0.44 and the curve flattens after 0.45. |
| Active history search | 0.6, top 12 (of 40 reranked) | Looser by design: the person pointed at something not in view. Misses log the nearest rejected distance so this becomes measured. |
| Image recall (cross-modal) | 0.96 ceiling + 0.006 cluster delta | The modality gap puts text-image similarity an order of magnitude below text-text; correct matches landed 0.91-0.954, irrelevant queries 0.961+. True-match clusters span ~0.004 and gap to the rest by ~0.007+; a best-vs-runner-up margin was tried first and rejected genuine matches once a user owned two relevant images. Images live in their own vector column because every unrelated text memory would outrank every matching image (0.73 text-text vs 0.08 text-image). |
| Tool descriptors | 0.45, top 5 | Correct tools landed 0.295-0.437, unrelated questions 0.477+; the 0.35 default silently discarded correct tools. Five, because exposing 100+ tools drops selection accuracy to roughly 13% against ~43% with retrieval. |
| Web result floor | 0.4 | Bimodal over 40 real results: usable hits 0.561-0.923, dictionary noise 0.046-0.346, an empty band between. |
| Search rounds | 2-3 | Asked whether results sufficed, the model said yes 8 of 8 on results naming two options and giving a figure for neither; four wordings moved it between 0/8 and 3/5 with no trend - so the floor is code, not a question. |
| Scout cosine attribution margin | 0.035 | Cosine similarities cluster near 0.6. |
| Scout cross-encoder margin | 1.0 log-odds | Section 5. |

## 7. The prompt: context budget and layout

**Budget observed, not enforced.** `CONTEXT_BUDGET_TOKENS` is 32,768 -
deliberately far below the served window, because a budget that only binds
at the ceiling reports nothing until the day it reports a failure - and
`CONTEXT_BUDGET_ENFORCE` is off: "trimming changes what the model sees, and
no section priority here has been argued against real turn sizes yet."
Reports accumulate on a named volume so the distribution survives rebuilds
and can set floors later. A heavy turn today is five to eight thousand
tokens against a million-token context, "an accident, not a design, and one
that stops being true quietly."

**Priorities**, when enforcement comes: system and query are never
trimmable; then evidence (a turn that searched did so for a reason), past
conversations, tools, history (floor 2 - a follow-up that loses its
antecedent is incoherent rather than thinner), images, recalled remarks,
memory. Trimming drops from the tail of each section's own order and
reports what it dropped; it never summarises.

**Token estimate** is 4.0 chars/token, calibrated against real
`prompt_tokens` from the served models - 4.46 for code on DeepSeek, 4.72 on
Qwen, 6.05 for English prose - with the densest sample as the floor, because
an under-estimate is a failed request rather than a shorter one.

**Layout** follows the cache (section 3): append-only history first, volatile
per-turn material after it as a user message. The conversation digest has a
200-word target and model compression because it once appended verbatim
exchanges forever - a 100-turn conversation carried ~100 KB into every prompt.

## 8. Decoding policy

**Temperature 0 for every decision.** Left at the runtime default, one
unchanged request alternated among search, delegation, and no tool across
repeated calls; a freshness question answered both YES and NO. Anything
parsed as a decision decodes greedily; only prose samples. Incident
reproduction follows the same rule: verbatim turn at temperature 0 first,
one wording attempt.

**A grammar on every parsed reply.** Every boundary that reads model output
as data sends a JSON Schema the runtime decodes as a grammar, derived from
the Pydantic type that validates the reply so the two cannot drift. A
violating field name becomes unrepresentable rather than a retry: the live
`DeckPlan` schema produced neither the invented `optional_` prefixes nor the
null notes that had broken decks. The grammar constrains structure only - it
cannot make Mermaid valid or a slide well argued.

**Structured output is an engine property, and it decided the engine.**
`MAIN_LLM_STRUCTURED_OUTPUT=True` is "the single fact that decides whether
the reasoning work of this application can follow the main model". Three
outages traced to its absence on ds4-server (the presentation revert, image
recall returning nothing, Scout's place suggester returning an empty tuple);
on vLLM it holds, and flipping it deleted 287 lines of fallback machinery.

**Token budgets are caps sized for thinking, each raised after an incident.**

| Setting | Was -> is | What happened |
| --- | --- | --- |
| Reply | 1,024 -> 4,096 | One reply in six came back empty on open-ended questions; none at 4,096. |
| Memory classification | 256 -> 1,024 | 256 was sized for the answer alone; a reasoning model spends part of any budget thinking first. |
| Deck plan | 2,048 -> 4,096 | A real plan needed ~2,000 tokens and truncated mid-JSON on 2 of 3 attempts. |
| Image intent | 16 -> 1,024 | At 16 the model truncated mid-thought and its monologue surfaced as `content` - "unparseable content on every upload", misread as a capability problem. |
| Routing decision | 300 -> 1,024 | A bare limit nobody chose, in the same class as the empty replies. |

The two truncation shapes are engine-dependent and worth knowing by sight:
ds4-server put the truncated *reasoning* into `content` (it parses, it reads
like text, it is wrong); vLLM leaves `content` empty - a loud failure beats
plausible garbage. `reasoning_effort=none` genuinely suppresses thinking on
ds4-server (3 completion tokens versus 60) and is rejected with a 400 by vLLM,
so it is sent per engine; the first fix dropped it unconditionally and
silently turned reasoning back on everywhere.

## 9. Image generation: the desktop, not the Sparks

**Decision.** FLUX.2 Klein 9B as a Q6_K GGUF with the official 8B encoder,
and FLUX.1 Kontext (GGUF) for instruction edits, in ComfyUI on the desktop's
RTX 5080 (16 GB). Available only while that machine is on, and the assistant
says so.

**Why not the Sparks.** Bandwidth, not memory: the RTX 5080 has roughly 3.5x
the Spark's memory bandwidth, and diffusion is memory traffic - 4-bit
FLUX.2-dev is the *slowest* image model on a Spark at 397 s per image. And
memory anyway: Klein needs 14-18 GB that neither node has while DeepSeek
holds ~97 GiB on each.

**Measured.** 6.0 s warm and 114.5 s cold at 1024x1024 and 4 steps, 13,755
MiB peak of 16,303; from spark1 through the backend's own provider classes,
generate 16.9 s and a Kontext edit 118.6 s. That last number is the model
swap: Klein (7.33 GB) and Kontext (6.46 GB) plus the 8.07 GB encoder cannot
all stay resident, so a generate followed by an edit pays a cold load;
ComfyUI runs prompts serially, so concurrent requests queue rather than
collide. The fp8 9B was the first choice and is HF-gated; the GGUF is a
file-name change, because both Klein workflows follow the model file name to
the loader.

**The ceiling is the VM's RAM, not the card's VRAM.** ComfyUI runs in Docker
Desktop's WSL2 VM, which takes the default half of host memory: the
container sees **15.6 GB of RAM** on a 32 GB host, and that RAM is where an
evicted model goes. Encoder + Klein is 15.40 GB; encoder + Kontext is 14.53
GB; both sit within a few hundred MB of the ceiling before pinned memory and
a 2 MP latent. Measured 2026-08-25: a Klein generation queued back to back
with a Kontext edit at 2 MP made ComfyUI exit cleanly mid-job (`ExitCode 0`,
`OOMKilled false`, no CUDA error - VM memory pressure, not GPU OOM), and
spark1 saw both jobs disconnect. `IMAGE_EDIT_MEGAPIXELS` is now 1.0 (a 1 MP
edit of a 1024x1024 source is not a visible downgrade), and the structural
fix is a `.wslconfig` with `memory=24GB` on the desktop - a host change,
recorded for its next boot. Measured again the same day with no Kontext in
play: six back-to-back generations, the sixth exiting the same way - the
encoder evicted to RAM while Klein loads is the moment a generation alone
crosses the line, so the megapixel knob cannot fix it and only the VM's
memory can. Until that restart, the provider waits for ComfyUI to answer
again and resubmits a dropped job once (never a rejected or timed-out one),
turning the common case into a slower success. **Closed the same evening:**
the desktop rebooted with the `.wslconfig` in place and the VM reports
**23.47 GiB**; measured on it, a generation (54 s) followed by a 2 MP edit
(68 s) left 7.1 GiB free with both models resident and nothing
disconnected, so `IMAGE_EDIT_MEGAPIXELS` is 2.0 again. The resubmit-once
retry stays: it costs nothing when nothing drops.

**Editing choices, measured.** Klein 4B as an editor left a picture
unchanged when asked to *add* anything, at 4 and 20 steps, at CFG 3.0, and
under img2img at denoise 0.70 - it is trained to preserve its reference -
so Kontext, trained to follow an instruction, edited. **The 9B does not
share that failure (measured 2026-08-25, judged by the vision model on the
pixels):** asked to add a yellow umbrella next to the bicycle it did
("Yes, a yellow umbrella is leaning against the brick wall next to the
bicycle"), asked to make the wall white it did - in 20.0 s and 18.3 s with
the model already resident, against Kontext's 109.6 s cold and 43.7 s
warm for the same two edits, which also passed. So the 9B now edits as
well as generates (`IMAGE_EDIT_MODEL` empty): one resident model, no
Klein-Kontext swap, no VM-RAM crash from the swap, and an edit after a
generation in seconds rather than two minutes. Kontext remains one env
var away if a class of edit turns out to need it; the judgement was two
instructions on one picture, not a fidelity benchmark. `IMAGE_EDIT_MEGAPIXELS`
is 2.0 because the output is generated at the scaled size: at 1.0 an edit
returned 1024x1024 however large the source, visibly worse than a phone
photo; 2.0 produced 1440x1440 in 39 s without running out of memory.
`lanczos`, not the template's `nearest-exact`, because nearest drops pixels
and stipples skin and hair.

## 10. How a model choice is made here

Public benchmarks could not settle DeepSeek against Qwen, so the repository
carries its own judge harness (`backend.cli.evaluate_reply_quality`, 46 cases
in 22 categories): identical production context via the real system-prompt
builder; blind and position-swapped, with a split scored as a tie; Claude as
the judge, calibrated first against a known outcome and a planted trap (it
preferred a two-word correct answer over a fluent wrong one); reported per
category, because two models can tie on the total with opposite failure
modes; no string matching anywhere, enforced by a test. The profile harness
issues requests strictly serially, because parallelising would risk
destroying the engine it measures mid-run. Weight quantisations are
deliberately excluded from tuning runs: they trade the thing the evaluation
exists to protect. One 128 GB box holds one large model, so measuring a
challenger means taking the incumbent down - collect before you offload.
Scout's ranking has its own labelled harness with floors
(`evaluate_discovery_ranking`), and both are gates, never proof.

## 11. Tried and rejected

| Tried | Result | Kept instead |
| --- | --- | --- |
| Qwen3.8-27B (BF16, FP8, NVFP4) as the reply model | 4.6-8.2 tok/s, 71.7 s to first content; better answers 18-9, unusable latency | DeepSeek-V4-Flash |
| DeepSeek 2.4-bit on ds4-server, one Spark | 14.5 tok/s, no structured output; three outages | vLLM, TP=2, official FP8 |
| NVFP4 DeepSeek weights | Same speed, larger on disk | FP8 release checkpoint |
| MTP / speculative decoding | Engine crash on Qwen; boots-then-dies at high utilisation on DeepSeek | Off, pending a load test |
| LMCache | L1 bug + KV divergence at temperature 0; IPC deadlock | vLLM prefix caching + prompt layout |
| Disabling chunked prefill for vLLM #40969 | Never applied: the engine ran vLLM's default (on) throughout, and this document said off until 2026-08-25; the hang has not reproduced in 1,511 requests | On, with `--enforce-eager` as the fallback |
| Explaining utilisation from `nvidia-smi` | 95% with 35 W and 28.6 tok/s: the counter measures kernel residency, not work | The bandwidth roofline in section 2; batching and speculation are the only levers |
| 0.90 utilisation | Refused on spark2, head hangs | 0.81, bounded by spark2 |
| `--kv-cache-memory-bytes` on the reply model | Hard cap that ignores utilisation; four failed restarts | Banned there; kept on the VLM |
| NVFP4 vision model | Wrong output on sm_121 (vLLM #50925) | AWQ |
| Served Qwen3 reranker for Scout | Attribution 0.25 vs 0.50 local | In-process MiniLM, swap is a setting |
| Sigmoid cross-encoder scores | 0.000 vs 0.001 separation | Raw log-odds, margin 1.0 |
| Replacing the nomic embedders | Unmeasurable gain at n~500; alignment trap | Keep; Qwen3-VL pair named for the ramp |
| Klein 4B as the editor | Preserves its reference, adds nothing | FLUX.1 Kontext for edits |
| Image generation on a Spark | 397 s/image class, bandwidth-bound | The desktop's RTX 5080 |
| A newer vLLM (0.25.2 vs 0.21.1+B12X) | Newer is 9-29% slower here (`torch.compile` regression) | Recorded; untested swap |
| Enforcing the context budget | No measured floors yet | Observe first |
| Google Custom Search JSON API as a free rung | Closed to new customers, ends January 2027 | Brave, then Tavily |
| DuckDuckGo as a rung | No official web-results API; the HTML endpoint is scraping that breaks without notice | Not built on |
| FAISS as the vector store | 439 vectors in 22 MB; top-10 in 0.5 ms without the index, 0.2 ms at 20k with it; FAISS would duplicate the store without the owner filter or the transaction | pgvector HNSW in the same database (section 5) |
| RAGFlow (the uploaded Specialized-Services stack) as the document store | Its own Elasticsearch/MinIO/Redis/MySQL beside ours, a tenant with no embedding model, a build that crashed the desktop (XMP + a 24 GB WSL), and answers that would have lived outside the owner filter and the encryption | Docling for parsing only; passages in the same pgvector space as memory (section 13) |
| Docling on the Spark | The parser wants a GPU and is bursty; the Spark's memory is spoken for by the reply model | Docling on the desktop, a durable queue on the Spark for the hours it is off |
| One timeout number for the parser client | The desktop drops connection attempts while Docling is stopped, so an upload waited out the kernel's ~2 minutes of retries before saying "queued" | A health probe before the inline parse (8 s at worst) and a 10 s connect timeout beside the 300 s read |
| Embedding distance to collapse two facts from one turn | Two paraphrases of Jen's trivia habit sat at 0.278 apart while an unrelated fact sat at 0.136 - the space cannot make this call | A deterministic predicate key (subject normalised away); one statement, one fact |
| A paragraph or document voice as a memory proposal | The classifier keeps one short first-person sentence and refuses paragraphs and third-person document text | A digest step writes the headline as one first-person sentence; the facts pass reads that |
| Gotenberg's Chromium route for PDFs | `500` on every page: `chrome_crashpad_handler: --database is required` under the desktop's Docker | The Word file built here, printed by Gotenberg's LibreOffice route (measured 2026-09-02) |
| A Microsoft 365 / Graph MCP to write documents | Puts the file in a tenant the household does not have, needs consent and tokens, to answer "send me that as a PDF" | A local writer and the existing artifact store (ADR 0020) |

## 12. Traps specific to serving

Each cost real time; the full operational list is in
[NEXT_SESSION.md](NEXT_SESSION.md).

- A comment inside a backslash-continued command deletes every flag after it.
- `--kv-cache-memory-bytes` does not scale with utilisation; over-allocation
  hangs a GB10 rather than failing, and recovery is a button.
- The MoE kernel falls back silently (`DEEPGEMM_MXFP4` in the boot log is a
  fallback); an env var alone does not select it - the kernel config does.
- JIT caches must be node-local, or torch.compile races and cubins are
  half-written with errors that never mention the cache.
- The QSFP port is two virtual NICs on separate subnets; merge them
  (`NCCL_IB_MERGE_NICS=1`) or collectives run at half the port; set
  `GLOO_SOCKET_IFNAME` or rendezvous deadlocks; the addresses do not survive
  a reboot until netplan is written.
- Driver 590.x deadlocks CUDA graphs on GB10; Ubuntu 25.10 breaks cross-node
  MPI; the pre-installed NVIDIA vLLM container has no DeepSeek-V4 model class.
- HF Xet pre-allocates sparse shards and stalls at ~1 MB/s while `du` appears
  to advance (`HF_HUB_DISABLE_XET=1`); anonymous downloads are throttled to 15
  MB/s, 24 with a token.
- A wedged tensor-parallel rank looks healthy to systemd (`active`, running,
  no restarts); a head sitting at `parallel_state` init for minutes means the
  worker is wedged, not slow.
- The serving script must be byte-identical on both nodes; a divergence
  shows up only as a hang during NCCL init.
- This document drifted from the engine: it said chunked prefill was off
  while the engine ran it on. The boot log's `non-default args` line is the
  effective configuration; diff it against the flag table in section 1, in
  both directions, after every change to the serving script.

## 13. Document knowledge: reading files into retrieval, and writing them back

The retrieval-augmented part of the system, built 2026-09-01/02 after the
uploaded RAG stack was evaluated and retired
([DOCUMENT_KNOWLEDGE_ARCHITECTURE.md](DOCUMENT_KNOWLEDGE_ARCHITECTURE.md)
carries the stage-by-stage design; the canonical diagram is
[document-knowledge.svg](diagrams/document-knowledge.svg)). Each decision
below is the options considered, what was measured, the choice, and what
would change it.

**Where documents live: the same pgvector space as memory, not a second
store.** The candidate was RAGFlow, arriving with its own Elasticsearch,
MinIO, Redis and MySQL, its own tenant model, and no embedding model
configured for that tenant - and a build that took the desktop down
(section 11). A second store would have held passages outside the owner
filter, the field encryption, the backups, and the transaction that every
other vector here sits in (section 5). So a document becomes rows in the
knowledge store: one `knowledge_documents` row per file (title, source URI,
content hash, status), one chunk row per passage with a 768-d nomic vector -
the same model and scheme signature as every memory vector, so a swap
degrades to "not rebuilt" rather than to noise. *What would change it:*
documents at a scale where HNSW build time matters (section 5's FAISS
numbers apply unchanged), or a need for hybrid lexical search that pgvector
does not give.

**Parsing: Docling on the desktop, everything else on the Spark.** The
parser wants a GPU and works in bursts; the Spark's memory is the reply
model's (section 2). Docling runs where the RTX 5080 is, behind
`DOCLING_BASE_URL`, and turns PDF, Word and PowerPoint into Markdown with a
page-break placeholder so every chunk knows its page. Plain text never
leaves the Spark. Because the desktop is off for hours at a time, a document
that arrives then is kept whole in `document_parse_jobs` and parsed when the
parser answers again; each pass probes `/health` first and leaves every job
untouched while it is down, so an overnight desktop burns no attempts, while
a reachable parser that fails on a file three times fails that job with its
own sentence. Measured 2026-09-02: the desktop *drops* connection attempts
while the container is stopped rather than refusing them, so an upload
handed straight to the parser waited out the kernel's ~2 minutes of SYN
retries before "queued" came back; the route now probes first (8 s at
worst, milliseconds when up) and the client connects in 10 s or gives up
while still reading for the configured 300 s.

**Chunking: by page, then by size.** Chunks never cross a page boundary and
carry `{"page": n}`; the reply is told the document and the page it used and
is asked to name both. Dedupe is a content hash per owner (the same bytes
again return the existing row); a new version of the same file (same source
URI, different hash) marks the older copy `superseded` - kept, not searched -
so two versions of one itinerary never mix.

**The gate: 0.5, measured, not inherited.** Section 6 has the row. Memory's
0.35 returned nothing for "whats on evening of day 1?" against the Day 1
chunk at 0.460; the reply answers only from the passages it is shown and
abstains otherwise, which is what makes a looser gate safe. Six passages a
turn, two probes (the typed words and the follow-up resolver's restatement)
merged by nearest distance, scoped to one document when the person replied
to its bubble.

**The share is the referent.** A shared file leaves a line in the
conversation ('shared a document: "<name>"') on every surface - the room
observes it, web and API uploads record it - and with that line in history
the router answers questions about the document from what is on hand rather
than searching the web (measured 3/3 on the three routing cases).
"Forget that document" routes to undo and the ledger returns the newest
*document* receipt rather than the memory receipt its facts pass wrote
seconds later.

**What a document says, into memory, with attribution.** A digest step
(one call, grammar-constrained) writes a first-person headline and the
statements worth keeping, and the ordinary memory-proposal classifier judges
them - because that classifier keeps one short first-person sentence and
refuses paragraphs and document voice (measured; section 11). In a room the
facts go to the speaker's store and the room's, never to another member;
the sharer gets their own copy. Two candidates from one turn with the same
predicate are saved once by a deterministic key, because the embedding space
put paraphrases 0.278 apart and an unrelated fact 0.136 apart.

**Writing back: the Word file here, the PDF printed beside the parser.** The
assistant offered a PDF it could not make (2026-09-02); rather than suppress
the offer, `create_document` makes it true. The body is the Markdown the
assistant writes anyway; a `.docx` is built from the standard library, and a
PDF is that file printed by Gotenberg's LibreOffice route on the desktop -
one source for both formats. Gotenberg's Chromium route was measured first
and cannot start there (section 11). The renderer is probed before a PDF is
attempted; when the desktop is off the person gets the Word file and is told
the PDF returns with it. The file is an artifact of kind `document` in the
same store as pictures (bytes under an opaque key, hash and size on the
row), a card on the web, an attachment under its title in iMessage, and the
bridge lets a PDF or a Word file out proven by its first bytes under the
picture cap. Routing measured 12/12 (three asks, one non-ask, three reps);
the functional test prints a real PDF and reads it back through Docling.
*What would change it:* editing an existing document in place, which is an
MCP question, not a renderer one (ADR 0020).

**Retention: designed, not built.** Documents have no age today: the file
stays until "forget that document" or a newer version. The design (recorded
2026-09-02, unbuilt) treats a document's three lives separately - the file
is never deleted on a date; its weight in retrieval retires after the date
the document is about, plus a grace period, to an `archived` status that
default search skips and a question about the past still reaches; and its
facts split into durable (the hotel, who went) and dated (the 8:30
departure), the latter carrying the memory expiry that already exists.
