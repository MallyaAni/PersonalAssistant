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
`--max-num-seqs 6`, `--max-num-batched-tokens 8192`, prefix caching on,
chunked prefill off, speculative decoding off, and the `flashinfer_b12x` MoE
backend with DeepGEMM disabled. Every text role runs here.

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
`torch.compile` works there and not on 0.25.2 - untested here. Chunked
prefill waits on vLLM #40969 (a silent hang after 5-7 requests with
`FULL_AND_PIECEWISE` cudagraphs on exactly this hardware). Speculative
decoding needs its own load test (section 3).

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

**Batching.** `--max-num-seqs 6` and `--max-num-batched-tokens 8192` for a
household, not a fleet; aggregate throughput at concurrency 6 is 383.5 tok/s.
Redis prioritises a foreground chat over background deck microtasks; nothing
moves a model between hosts at request time.

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
swap: Klein (7.3 GB) and Kontext (6.5 GB) plus their encoders cannot both
stay resident, so a generate followed by an edit pays a cold load; ComfyUI
runs prompts serially, so concurrent requests queue rather than collide. The
fp8 9B was the first choice and is HF-gated; the GGUF is a file-name change,
because both Klein workflows follow the model file name to the loader.

**Editing choices, measured.** Klein 4B as an editor left a picture
unchanged when asked to *add* anything, at 4 and 20 steps, at CFG 3.0, and
under img2img at denoise 0.70 - it is trained to preserve its reference -
so Kontext, trained to follow an instruction, edits. `IMAGE_EDIT_MEGAPIXELS`
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
| Chunked prefill | vLLM #40969 silent hang on this hardware | Off |
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
