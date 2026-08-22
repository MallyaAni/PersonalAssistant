# Comparing candidate models for AniOS

## Decision, 2026-08-20: DeepSeek stays

Qwen3.8-27B answers better and cannot be served fast enough here to matter.

**Quality: Qwen wins 18-9, with 19 ties**, judged blind and position-swapped
over 46 cases. The wins are concentrated exactly where this application lives -
**8-0 across the grounding categories** (evidence over training, synthesis,
conflicting evidence, no invention, buried evidence). DeepSeek's losses were
fabrications: an invented date asserted as today, an invented currency, and
claiming to have no information about a fire it then quoted. For an assistant
built on search, confident and wrong is the worst failure available.

DeepSeek won on decisiveness - trade-off questions 2-0, where Qwen buried its
recommendation under symmetrical lists, and twice refused a task outright.
Reasoning was effectively a tie, so the fourteen-point HLE gap did not appear.

**Speed: every Qwen quantisation that runs here is far slower.**

| | decode | vs DeepSeek |
|---|---|---|
| Qwen BF16 | 4.57 tok/s | 4.8x slower |
| Qwen FP8 | 5.35 tok/s | 4.1x slower |
| Qwen NVFP4 | 6.20-8.15 tok/s | **2.7x slower** |
| DeepSeek IQ2_XXS | **22.10 tok/s** | - |

NVFP4 is about 4 bits - **less compressed than the 2.4-bit DeepSeek it was
being compared against** - and still could not close the gap. A published
single-Spark run reports 24 tok/s for this model; that used MTP speculative
decoding, which is worth roughly 2x and crashes this build. Even granting it,
NVFP4 would reach about 16 and still lose.

Better answers do not survive 50 to 90 second replies against 11. So the
quality result is real and does not change the decision.

**Revisit when either becomes true:** the vLLM container ships a working MTP
kernel for GB10, or the second Spark arrives and both models can be resident at
once - which is the outcome that actually wants: DeepSeek keeps chat, Qwen
takes the schema-bound callers off the 4B and fills the empty vision slot.

**What is given up by staying:** schema enforcement, and therefore six callers
still pinned to a 4B; and vision, which DeepSeek cannot do at all. Both are
capability gaps, not quality regressions, and both resolve with the second box.

Two builds failed outright and are recorded so they are not retried blindly:
`unsloth/Qwen3.8-27B-NVFP4` is rejected by this vLLM with "Must use group
quantization strategy in order to apply activation ordering";
`Inferact/Qwen3.8-27B-NVFP4` serves correctly and is the one measured above.


How a model swap is decided here, and what was measured the first time it was
done properly. Every number below was observed on this hardware, not taken from
a model card. Where a published figure is quoted it is labelled as one.

The evaluators live in `backend/cli/`; the labelled sets they score live beside
the production code that uses them. This document is the operational record
that the code cannot carry: the traps, the restore paths, and the reasons a
number is what it is.

## Why public benchmarks could not settle it

The question was whether to replace DeepSeek-V4-Flash with Qwen3.8-27B as the
main reply model. Aggregators disagreed with each other and with the models'
own cards. One widely-cited comparison reported Qwen ahead on LiveCodeBench by
35 points; DeepSeek's official figure for the same benchmark is **91.6 against
Qwen's 90.3** — the opposite, and within noise. Relaying that aggregator
without checking would have made the case for a swap out of arithmetic that was
simply wrong.

The head-to-head on the eight benchmarks both models publish, cross-checked
against Qwen's own model card:

| Benchmark | DeepSeek-V4-Flash | Qwen3.8-27B |
|---|---|---|
| HLE (reasoning) | **45.1** | 30.8 |
| Terminal-Bench 2.1 (agentic) | **82.7** | 73.0 |
| DeepSWE | **54.4** | 42.2 |
| NL2Repo-Bench | **54.2** | 42.3 |
| Agents' Last Exam | **25.2** | 20.4 |
| LiveCodeBench | **91.6** | 90.3 |
| GPQA Diamond | 88.1 | **89.2** |
| SWE-Bench Pro (Public) | 52.6 | **61.7** |

DeepSeek wins six of eight, including both agentic benchmarks — the dimension
closest to what this application does.

**And none of it describes what is deployed.** See the next section.

## The deployed DeepSeek is a 2-bit quantisation

```
DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-0731.gguf
86.7 GB for roughly 284B parameters  ->  about 2.4 bits per weight
```

Every benchmark above is for the unquantised model. Nobody publishes figures
for this quant. So the published numbers set an upper bound on the incumbent
and say nothing about the gap that actually exists on this machine — which is
the entire reason a local evaluation had to be built rather than argued.

## What the judge harness is, and why it is shaped that way

`python -m backend.cli.evaluate_reply_quality`, cases in
`backend/services/reply_quality_cases.py`.

- **Identical context.** Both candidates answer through `_build_system_prompt`,
  the production assembly, with the same supplied evidence. A difference is the
  model, not the harness.
- **Blind and position-swapped.** Every case is judged twice with A and B
  exchanged. A judge that simply prefers what it reads first splits, and a
  split is recorded as a **tie**, not half a point.
- **Claude as judge**, run headless through the Claude Code binary. Neutral
  because it is neither candidate, so the self-preference effect cannot apply
  to either side. Calibrated before use against a known outcome and a planted
  trap: it preferred a two-word correct answer over a fluent wrong one.
- **Reported per category.** `evaluate_tool_selection` already established that
  two models can tie on the total with opposite failure modes underneath. The
  breakdown is the result; the total is a footnote.
- **Batched.** Per-call overhead is roughly 15k tokens of harness against a few
  hundred of content, so cases are judged in batches. Three cases cost what one
  costs.
- **No string matching anywhere.** Each case carries a `standard` in prose. A
  test asserts no standard quotes a required phrase, because scoring a word is
  the thing this replaces.

46 cases across 22 categories, spanning evidence handling, reasoning, being a
useful correspondent, and the four jobs this application gives the reply model
besides chat. Reasoning was added late and deliberately: the published numbers
put fourteen points between these candidates on reasoning and none on general
knowledge, so a set without reasoning cases would have measured everything
except the axis that separates them.

Every reasoning answer was computed and verified before being written down,
including that the deduction puzzle has exactly one solution. **A labelled set
with a wrong label scores the correct model as failing.**

## Measured, 2026-08-19

### DeepSeek-V4-Flash, IQ2_XXS, on ds4-server

| | |
|---|---|
| TTFT | 1.72 s |
| decode, 800-token generation | **22.1 tok/s** |
| decode, 64-token generation | 8.25 tok/s (TTFT-dominated; not the real figure) |
| prefill | 532 tok/s over 5,476 prompt tokens |
| context launched with | `-c 1000000` |
| native tool calling | 4/4 correct on a small probe |
| tool selection, 52-case set | 36/38 at 1 rep — both misses under-triggering |
| **schema enforcement** | **none** |

Full record in `data/model_evaluations/BASELINE-deepseek.json`.

### Qwen3.8-27B, BF16, on vLLM 0.17.1

Measured with MTP enabled, before it had to be disabled for killing the engine.
Treat the decode figure as the optimistic one: without speculative decoding it
is lower, and re-measuring it is the first row the profile table needs.

| | |
|---|---|
| decode | **9.9 tok/s** |
| tokens per answer, thinking on | ~1,635 for a ~1,380-character reply |
| **wall clock per reply** | **~166 s**, against DeepSeek's ~11 s |
| MTP acceptance length | 2.16–2.31 |
| full-attention layers | 16 of 64 (the rest linear) |
| KV cache | 64 KiB per token |

The ~15× wall-clock gap is two multipliers compounding: 2.2× slower decode and
about 7× more tokens because thinking is on. The decode half was predicted from
memory bandwidth before it was measured and landed almost exactly; the thinking
multiplier was not predicted.

### Qwen3.8-27B, BF16, stable configuration — no MTP

The numbers to plan from. MTP is disabled because it kills the engine, so the
9.9 tok/s above is unavailable and this is what the model actually does.

| | |
|---|---|
| decode | **4.57 tok/s** — MTP was worth 2.2×, and 4.8× slower than DeepSeek |
| ttft to first token | 0.32 s |
| **ttft to first content** | **71.7 s** — thinking streams as `reasoning`, which the reply path does not render, so this is a blank screen |
| prefill at 36k | **1,051 tok/s** — roughly 2× DeepSeek, the one speed Qwen wins |
| prefix caching | **works: 16× on a repeated 39k prefix** (44.8 s cold, 2.8 s warm) |
| **schema enforcement** | **yes** — the contract DeepSeek violated is honoured exactly |
| vision | **yes** — named three colour bands in a generated image |
| tool selection, 52-case set | **19/38, but confounded — not a capability result. See below.** |

Two things run-to-run variance taught here: the same question spent 1,635
tokens once and 405 another time, and thinking-off is **not** reliably faster —
in one run it wrote a longer answer without the thinking budget and took longer.
Any wall-clock claim from a single sample is noise.

### The tool-selection result is not a verdict

Qwen scored 19/38 with **zero** tool calls in every tool category, which looks
damning and is not. Ruled out one at a time: the parser (forced calls come back
perfectly formed), `tool_choice`, temperature, and the 300-token cap. Given the
real routing prompt and all six tools at 300 tokens it picks correctly —
`search_web` for an election result, `generate_image` for a picture request.

The open hypothesis is that Qwen emits calls whose required argument is empty,
and AniOS deliberately drops those, because an action with nothing to act on
must not take a turn. That would show up as exactly this pattern. It is
untested, and recording 19/38 as a capability score would have been wrong in a
way that decided a migration.

**The lesson generalises: a zero across every category of anything is a
configuration fault until proven otherwise.**

## Serving configuration profile

Throughput is not one number here. It is the decode rate multiplied by how many
tokens the model chooses to spend, and switching thinking on moved the second
factor about seven times further than any serving flag moved the first. So a
configuration is described by the whole row, never by one figure.

Regenerate a row with:

```
python -m backend.cli.measure_inference_profile \
    --base-url http://animallya-spark1.local:8899 --model qwen3.8-27b \
    --label "bf16 mtp3" --append docs/MODEL_EVALUATION.md
```

It issues requests strictly serially. That is how the engine is most stable
here, and a benchmark that parallelised would risk destroying the thing it is
measuring mid-run.

**`MTP accept` stays in the table but reads as `-` on this build**, because
speculative decoding is disabled — see the trap below. When it can be turned
on again, read acceptance before tuning `num_speculative_tokens`: throughput
alone cannot separate a drafter that is working from one being ignored, and
below about 1.5 the drafter costs more than it returns.

**`ttft to content` is the number a person feels**, not `ttft`. Thinking is
streamed as `reasoning` and the reply path renders only `content`, so with
thinking on the user sees nothing at all until the thinking block closes.

| config | decode tok/s | MTP accept | ttft to content | answer tokens on/off | wall clock on/off | prefill tok/s | thinking reply |
|---|---|---|---|---|---|---|---|

### Configurations worth measuring

Each server-level flag needs a restart, roughly six minutes, so the list is
ordered by what is most likely to matter rather than by covering every
combination. Request-level options — thinking on or off, token caps — are swept
within one restart by the tool above.

1. **`bf16 mtp3`** — what was first served here. The baseline every other row
   is read against.
2. **`bf16 no mtp + prefix + chunked`** — `--enable-prefix-caching` and
   `--enable-chunked-prefill` cost no quality and were missing from the first
   configuration. This is the working baseline, because MTP is unusable here.
3. ~~`bf16 mtp5`~~ — **not measurable on this build.** Raising
   `num_speculative_tokens` cannot be evaluated while the engine dies mid
   request at any setting. Revisit when the container is updated.
4. **`bf16 mtp5 + fp8 kv, 262k`** — quantises the cache and not the weights.
   The only way to reach a large context at full weight quality.
5. **`bf16 mtp5 + fp8 kv, 1M via YaRN`** — needs `mrope_section`,
   `mrope_interleaved` and `partial_rotary_factor` overrides in `text_config`.
   Matches the context DeepSeek was serving.
6. **`tool-call-parser qwen3_xml`** — the first configuration used
   `qwen3_coder`. A wrong parser makes tool calls fail to parse rather than
   fail loudly, which is the same shape as the `reasoning_effort` defect.

Deliberately not measured: NVFP4 and other weight quantisations. A published
single-Spark run reports 24 tok/s against the 9.9 measured here at BF16, and
essentially all of that gap is the quantisation. That is a real option, but it
trades the thing this evaluation exists to protect, so it stays out until the
quality comparison says what BF16 is worth.

## A small token budget breaks a reasoning model in two different ways

Both engines spend part of a reply budget on thinking that the caller never
asked for and does not render. What happens when that thinking runs out of
budget is where they differ, and neither behaviour is obvious.

**ds4-server puts the truncated reasoning into `content`.** Asked to reply with
one word, at 16 tokens:

```
max_tokens=16   finish=length   content='1. The user asked to "Reply with...'   reasoning_content=''
max_tokens=64   finish=stop     content='alive'                                 reasoning_content=147 chars
```

The caller receives the model's internal monologue as though it were the
answer. It parses, it reads like text, and it is wrong.

**vLLM leaves `content` empty instead.** Same situation, different failure: the
reply is missing rather than fabricated. That is strictly better — a loud
failure beats plausible garbage — and it is an argument for vLLM that has
nothing to do with schema enforcement.

**This has already cost this project once, and was misdiagnosed.**
`get_image_intent_classifier` records that DeepSeek "returned unparseable
content on every upload", which silently disabled edit-intent detection because
the classifier answers False on any failure. That was read as the main model
being unsuited to constrained classification. It is not a model capability
problem at all: `IMAGE_INTENT_MAX_TOKENS` is **16**, which guarantees
truncation, and truncation is what corrupts the answer.

**So it is a precondition of the structured-output migration.** Flipping
`MAIN_LLM_STRUCTURED_OUTPUT=True` moves six callers off the 4B - which does not
reason, and is therefore immune - onto a model that does. Three of them sit in
the truncation zone:

```
IMAGE_INTENT_MAX_TOKENS           =  16
MEMORY_PROPOSAL_MAX_TOKENS        = 256
VISION_SEARCH_DECISION_MAX_TOKENS = 300
routing tool decision             = 300 (hardcoded at the call site)
```

Raise these before moving them, or they fail on the first turn. The reply path
had exactly this defect until it was measured: one reply in six came back
empty at 1,024 tokens.

## Things that cost time and are not visible in the code

**`reasoning_effort="none"` fails every request on vLLM.** ds4-server accepts
it; vLLM accepts only `low`, `medium`, `high` and answers anything else with a
400. `MAIN_LLM_REASONING_EFFORT` defaults to `none` in compose, so pointing the
main role at a vLLM backend would not have degraded — it would have returned
nothing at all. Fixed by omitting the field when it means none;
`backend/tests/test_reasoning_effort_portability.py` holds it.

**A reasoning model with a small token cap returns an empty string.** Qwen with
thinking on and `max_tokens=800` finished with `finish_reason: length`, and
both `content` and `reasoning_content` were empty — it was still inside an
unclosed thinking block. AniOS caps replies at 1,024 by an unnoticed signature
default in `stream_chat`, so on this model every reply would be blank. Thinking
tokens count toward the cap and are not the answer.

**MTP speculative decoding crashes the engine on this build. Do not enable it.**
`--speculative-config mtp` produces `cudaErrorIllegalAddress` and kills
EngineCore, taking every in-flight request with it.

It was first seen with two requests running and recorded here as a concurrency
bug. That was wrong. It recurred with `num_running_reqs=1` — a single request,
nothing else touching the box — so concurrency was a coincidence of the first
occurrence, not the cause. Twice it destroyed a collection run that was midway
through; the second time the harness had incremental saving and lost nothing,
which is why that exists.

The acceptance figures are real (2.16–2.31, roughly doubling decode) and it is
worth revisiting when the container is updated. Until then the throughput it
offers is not worth an engine that dies without warning.

Answers produced before and after disabling it were compared on three cases
with verifiable answers. Both configurations got all three right; the text
differed only as two samples at non-zero temperature always do. So MTP was
producing correct output right up until it stopped producing any.

**1M context does not fit at BF16.** At 64 KiB/token, 1M tokens is 61 GB of KV
beside 56 GB of weights against 121 GB total. 512k fits comfortably; 1M needs
`--kv-cache-dtype fp8`, which quantises the cache and not the weights.

| context | KV | + weights |
|---|---|---|
| 65,536 | 4 GB | 60 GB |
| 262,144 | 16 GB | 72 GB |
| 524,288 | 32 GB | 88 GB |
| 1,000,000 | 61 GB | **117 GB — will OOM** |

**The bandwidth limit is internal, not the network.** GB10 reads at ~273 GB/s
and every token requires reading every active weight. Moving AniOS onto the
Spark saves a LAN round trip measured in milliseconds against answers measured
in minutes. It does not change decode speed at all.

**Do not move ComfyUI to the Spark.** Diffusion is bandwidth-bound for the same
reason. The RTX 5080 has roughly 3.5× the Spark's memory bandwidth, so image
generation would get slower. The correct split is LLM and VLM on the Spark,
diffusion on the 5080.

## Operating the Spark

SSH as `animallya96` with `~/.ssh/id_ed25519_spark`.

```
hostname   animallya-spark1.local     (mDNS - can resolve to an IPv6 link-local
                                 address, which ssh then cannot use)
address    172.16.8.3
MAC        F8-3D-C6-F1-23-64
```

**Record the address, not just the name.** This box was reached only ever by
mDNS name, so when it powered off there was no IP and no MAC retained anywhere,
no Wake-on-LAN was possible, and a DGX Spark has no BMC or IPMI. It needed a
physical press of the power button. Prefer the address when the name will not
resolve; mDNS is also slow to come back after a boot.

**Wake-on-LAN is not set up.** `ethtool` is not installed, so whether the NIC
supports it is unverified. Until that is done, "off" means someone has to walk
to it.

**Powering it off is not recoverable from here, so do not schedule one.** See
the rule in `AGENTS.md`. When it does come back, `@reboot` starts `ds4-server`
by itself - verified: four minutes after a cold boot, port 8888 was listening
and answering with no intervention.

**`ds4-server` has no systemd unit.** It is a `@reboot` cron job, so the
ordinary `systemctl` mental model leaves it stopped with no obvious way back.
The restore command is:

```
/home/animallya96/.local/bin/ds4-serve --cuda \
  -m /home/animallya96/gguf/DeepSeek-V4-Flash-IQ2XXS-...-0731.gguf \
  -c 1000000 --port 8888 --host 0.0.0.0 >> /home/animallya96/ds4-server.log 2>&1
```

**`pkill -f "ds4-server"` kills the shell running it**, because `-f` matches
full command lines and the SSH command string contains the pattern. Use
`pkill -f "[d]s4-serv"`.

**NVIDIA's vLLM container is already on the box** (`nvcr.io/nvidia/vllm`), and
`--gpus all` works. No source build with custom LLVM/Triton is needed, which is
what `DGX_MIGRATION.md` predicted.

**Collect before you offload.** One 128 GB box holds one large model, so
measuring a challenger means taking the incumbent down. Everything that dies
with a model — answers, throughput, schema behaviour, tool selection — has to
be captured while it is still up. The harness separates collection from judging
for exactly this, and resumes from a saved file so growing the case set costs
only the new cases.

| bf16, no mtp, prefix cache | 4.57 | - | 71.7 | 405 / 758 | 89.2 / 166.3 | 363.9 / 1051.0 | ok |
