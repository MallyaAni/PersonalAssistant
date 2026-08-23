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

## The current reply engine, measured rather than assumed (2026-08-22)

Prompted by "is ds4's prefill cache actually better than vLLM's", every number
below was measured against the live server on `animallya-spark1`, not quoted.

**What is actually deployed.** `ds4-server v0.5.6.3` (github.com/Entrpi/ds4,
a fork of DwarfStar, GGML-based, purpose-built for this model family), started
by a **user crontab `@reboot`** entry - not systemd:

```
@reboot sleep 30 && ~/.local/bin/ds4-serve --cuda \
  -m ~/gguf/DeepSeek-V4-Flash-IQ2XXS-w2Q2K-AProjQ8-SExpQ8-OutQ8-chat-v2-imatrix-0731.gguf \
  -c 1000000 --port 8888 --host 0.0.0.0 >> ~/ds4-server.log 2>&1
```

`ds4-serve` is a wrapper that prepends its own defaults (`-c 262144 --port
8000`) and appends yours, so the process command line shows both and the later
values win. Weights 86.7 GB, plus a 7.0 GB `DSpark-drafter` for speculative
decode, both under `~/gguf`. Restoring this setup means that crontab line and
those two files, nothing else.

**Decode speed. The 5.7 tok/s recorded elsewhere in this repository is wrong.**
Measured over three prompt shapes: 10.1, 14.5 and 19.0 tok/s, mean ~14.5, with
the drafter working (`spec_accept_rate` 0.6-0.9, 2.7-4.5 tokens per step). That
matches an independent 2x-Spark writeup's ds4 single-node figure of ~14 tok/s,
so this deployment is normal rather than broken.

**Prefill. ~1095 tok/s** on prompts large enough to measure (the 78-102 tok/s
seen on 13-22 token prompts is startup overhead, not throughput).

**The prefill cache is real, and its value depends entirely on prompt size.**
TTFT, cold versus the same prefix repeated:

| prefix | cold TTFT | cached TTFT | gain |
|---|---|---|---|
| 2.4k tok | 2,229 ms | 2,031 ms | 1.09x |
| 4.4k tok (our median) | 3,236 ms | 1,375 ms | **2.35x** |
| 11.7k tok (our p90) | 8,778 ms | 476 ms | **18.5x** |
| 24k tok | 19,859 ms | 1,443 ms | 13.8x |

At small context the disk KV read costs about what recompute costs; the payoff
arrives around 4k and is enormous by 12k. Our own context accounting over 61
real turns says median 4,356 tokens, p90 11,695, max 16,145 - squarely in the
range where this feature earns its keep. Any engine change has to keep an
equivalent, or TTFT regresses on exactly the turns people notice.

**Capabilities, probed rather than believed.** `/v1/models` advertises
`tools` and `tool_choice`, and the engine has first-class tool machinery
(`--disable-exact-dsml-tool-replay`, `--tool-memory-max-ids`) - so the claim
recorded elsewhere that ds4 "lacks tool calling" is out of date for v0.5.6.3.
But `response_format` with a `json_schema` is still **ignored**: the probe
asked for `{"capital": ...}` and got the bare word `Paris`. Structured output
remains the real gap, and it is what `JSONFallbackWriter` and
`MAIN_LLM_STRUCTURED_OUTPUT=False` exist for.

**ds4 can span both Sparks.** `--role coordinator|worker` with an inclusive
layer slice (`--layers 10:20`) is pipeline-parallel across nodes, so "ds4 is
single-box only" is also untrue.

**What the alternative measures at, on this exact hardware** (from a public
2x-Spark writeup, not measured here): vLLM dual-node TP=2 on the official
checkpoint - ~41 tok/s single-stream decode, ~1,785 tok/s prefill, ~350 tok/s
aggregate at concurrency 32. The official FP8 and NVFP4 checkpoints are both
~160 GB on disk, ~148.66 GiB loaded: too large for one Spark's 121 GB, and
comfortable across two with ~93 GB left for KV.

So the upgrade on offer is roughly **2.8x decode, 1.6x prefill, official
quality instead of a 2-bit quantization, and working structured output** - at
the cost of both boxes, and of ds4's disk KV cache unless vLLM's in-memory
prefix caching covers the same ground. The quality half of that claim is the
one still unmeasured; `evaluate_reply_quality` exists to settle it and needs
both engines up at once.

### MTP is carrying the speed, and it favours code

The boot log shows the continuous MTP path running with the DSpark block
drafter as its draft source, four draft tokens per step:

```
ds4: CONT_MTP_ACCEPT(DSpark) D=4 steps=23 emit=59 accept=64.3% tok/step=2.57
ds4: CONT_MTP_ACCEPT(DSpark) D=4 steps=13 emit=53 accept=90.9% tok/step=4.08
```

`tok/step` is the multiplier over unspeculated decode, so the measured
14.5-19 tok/s rests on a base of roughly **5.6 tok/s**. That is where the
"5.7 tok/s" figure recorded elsewhere came from: it is the rate with
speculation off, not a bad measurement.

Acceptance is **90.9% on a code prompt against 64.3% on prose**, which
matters for where this is going. Speculation pays most on structured,
predictable output, so a coding workload is the case that benefits most -
and the DSpark block drafter is a ds4 asset, not something a different
engine inherits automatically. Any engine comparison has to be run on code
and agentic prompts, not just chat, or it will understate what is being
given up.

### Longer contexts change the answer, in ds4's favour

Coding pushes prompt sizes up, and the prefill-cache table above is steeply
non-linear: 1.09x at 2.4k, 2.35x at 4.4k, 18.5x at 11.7k. A repository-aware
assistant resending the same files across turns is the exact "stable prefix,
long prompt" shape the disk KV cache is built for, and unlike an in-memory
prefix cache it is bounded by disk rather than by the KV pool and survives a
server restart. Before moving engines, measure the replacement's caching at
30k-100k, not at chat sizes.

## The 4B is out of every role but vision (2026-08-23)

Once the reply engine began enforcing JSON schemas, every reason to keep a
second, smaller model disappeared at once. Six roles moved to the main
model - reply, routing, memory proposals, diagram specs, presentations, and
the sweep's judgement calls - and three pieces of machinery that existed
only to work around the old engine were deleted:

- `JSONFallbackWriter` (`backend/core/structured_fallback.py`, 94 lines, plus
  its 107-line test). It asked the strong model first and fell back to the
  grammar-enforcing 4B whenever the JSON did not parse, which meant a
  malformed answer was quietly *replaced* by a weaker model's answer.
- `FallbackInferenceProvider` (86 lines in `backend/core/llm.py`) and the
  `MAIN_LLM_STANDBY_*` settings. The standby existed because the main model
  ran on a host that was not always on. It pointed at a model a third as
  capable, so an outage did not fail - it silently answered worse, with
  nothing in the reply saying which model wrote it. Both Sparks are always
  on now, and a reachability problem should read as one.

`VISION_MODEL` stays on `qwen/qwen3.5-4b`: it is the only vision-language
model available here, and replacing it is a separate decision with its own
memory budget (~27 GB free per Spark after the TP=2 weights).

Verified end to end after the change: a real chat turn routed on the new
model chose `Scheduled tasks | weekdays at 18:00` for "remind me every
weekday at 6pm to stretch", saved it, and confirmed the correct first run.
1,628 structural tests pass.

---

# Choosing the main LLM: the whole decision, 2026-08-22/23

This is the long form of one decision - which model answers AniOS, on what
engine, with which settings - written so the reasoning survives and not just
the result. Every number is measured on this hardware unless it says
otherwise.

## 1. The constraint that decides everything

A DGX Spark has 128 GB of unified memory and **273 GB/s** of bandwidth.
Decode is bandwidth-bound, so that number, not the GPU, sets the ceiling.
Two consequences follow, and they explain every benchmark anyone publishes
for this box:

- **Dense models die here.** Gemma 4 31B at NVFP4 reaches 7 tok/s.
- **Small-active-parameter MoE flies**, because decode only reads the
  experts it activates. DeepSeek V4 Flash is 284B total but activates 13B
  per token.

A corollary that surprises people: quantizing harder does not always help.
4-bit FLUX.2-dev is the *slowest* image model on a Spark (397 s/image),
because the bottleneck is memory traffic rather than arithmetic.

## 2. What we were already running, measured

The starting point was DeepSeek V4 Flash as an `IQ2_XXS` GGUF (~2-bit,
86.7 GB) on one Spark under `ds4-server v0.5.6.3`, a DwarfStar fork built
for this model family.

| | measured |
|---|---|
| decode | 10.1 / 14.5 / 19.0 tok/s by prompt (mean ~14.5) |
| base without speculation | ~5.6 tok/s |
| MTP + DSpark drafter, D=4 | 2.57-4.08 tokens per step |
| prefill | ~1,095 tok/s |
| spec acceptance | **90.9% on code, 64.3% on prose** |
| `json_schema` | **ignored** - asked for JSON, got bare prose |

**Three things this repository believed turned out to be wrong**, and
finding that out changed the decision:

1. "ds4 does 5.7 tok/s" - that is the *unspeculated* rate. Real is 10-19.
2. "ds4 lacks tool calling" - out of date. v0.5.6.3 advertises `tools` and
   has first-class tool machinery.
3. "ds4 is single-box only" - it has `--role coordinator|worker` with
   inclusive layer slices, i.e. cross-node pipeline parallelism.

Only the structured-output gap was real, and it was the one that mattered.

## 3. The prefill cache, and why prompt size decides its worth

ds4 has a disk KV cache whose value is steeply non-linear in prompt size:

| prefix | cold TTFT | cached TTFT | gain |
|---|---|---|---|
| 2.4k | 2,229 ms | 2,031 ms | 1.09x |
| 4.4k (our median) | 3,236 ms | 1,375 ms | **2.35x** |
| 11.7k (our p90) | 8,778 ms | 476 ms | **18.5x** |
| 24k | 19,859 ms | 1,443 ms | 13.8x |

Our own context accounting over 61 real turns reads median 4,356, p90
11,695, max 16,145 tokens - so this was a feature in daily use, and any
replacement had to keep it. It does: vLLM's prefix caching warms after two
calls and then serves the p90 prefix in ~512 ms against ds4's 476 ms, while
being *faster* cold (5.9 s vs 8.8 s).

Measuring this took two attempts. A two-sample test showed the cached call
*slower* than cold and looked like a regression; five consecutive calls
showed the real shape - 5,909 / 6,383 / 496 / 539 / 516 ms. The cache
commits after the second call.

## 4. Candidates, and why the obvious answer was wrong

The tempting choice was Qwen3.6-35B-A3B-NVFP4: ~25 GB, 218-436 tok/s on a
GB10, 100/100 on Tool-Eval-Bench, and it fits on **one** Spark - leaving the
other free for a VLM and diffusion. It is the better *engineering* answer.

It was the wrong answer here because it scores **32** on the Artificial
Analysis intelligence index against DeepSeek V4 Flash's **52**, and 73.4 on
SWE-bench against 79. The requirement was maximum intelligence, and a
20-point index gap is not something throughput compensates for.

That choice has a cost worth stating plainly: DeepSeek's weights are
~167 GB, which consumes both Sparks, so **image generation has no home on
this hardware**, and vision keeps whatever is left (~27 GB per box).

Precision was not really a choice either. FP8 *is* the release format;
NVFP4 is NVIDIA re-quantizing it. Measured elsewhere at 41.4 vs 41.5 tok/s -
noise - and on disk 166.9 GB against 168.3 GB, so the 4-bit build is
**larger** and buys neither speed nor memory. FP8 wins on all three axes.

## 5. The engine mattered as much as the model

They are built for different things:

- **ds4** is a single-user latency engine: aggressive speculation (D=4), a
  disk KV cache, one stream at a time.
- **vLLM** is a serving engine: continuous batching, paged KV, cross-node
  tensor parallelism.

Speculation's advantage *shrinks* with batch size - measured elsewhere at
1.96x at batch 1 falling to 1.21x at batch 128 - because a busy GPU has no
idle capacity to spend on drafts. So ds4 wins the demo and vLLM wins the
product, and the gap widens with users and with context.

## 6. What deployment actually cost

Nine problems, each of which would have read as something else:

1. **The pre-installed vLLM cannot serve this model.**
   `nvcr.io/nvidia/vllm:26.03` ships 0.17.1, whose registry has DeepSeek
   V2/V3/V3.2 and no V4, while the checkpoint declares `deepseek_v4`.
2. **Newer is slower.** A published head-to-head found 0.21.1 + B12X beats
   0.25.2 by 9.2% peak decode, because `torch.compile` works on the former
   for this model and not the latter.
3. **The QSFP port is two virtual NICs.** Listing one HCA silently halves
   NCCL bandwidth (98 vs 161 Gb/s busbw). Both twins must be addressed, on
   *separate* subnets, and merged with `NCCL_IB_MERGE_NICS=1`.
4. **HF Xet downloads stall silently** at ~1 MB/s while `du` appears to
   advance, because shards are pre-allocated sparse. `HF_HUB_DISABLE_XET=1`.
5. **Anonymous HF downloads are throttled** - 15 MB/s against a 458 Mbit/s
   link until a token was added, then 24 MB/s.
6. `gpu-memory-utilization 0.78`, not 0.85: speculative decode allocates on
   the *first real request*, so higher values boot, pass a smoke test, and
   then die under traffic.
7. `num_speculative_tokens 5` - the DSpark block size. 7 and 10 boot and
   then crash on every generation.
8. JIT caches must be node-local. Sharing them fails three ways and none of
   the errors name the cache.
9. **The old server holds the memory.** vLLM refused to start with "Free
   memory 1.13/121.69 GiB" until ds4 was stopped - a clean, informative
   failure, and the moment the cutover became irreversible.

## 7. The single biggest win, and it was free

The boot log said:

```
Using 'DEEPGEMM_MXFP4' Mxfp4 MoE backend.
```

That is a fallback. `VLLM_USE_B12X_MOE=1` was set and *is* a real env var,
but it does not drive the choice - a `KernelConfig.moe_backend` field does,
exposed as `--moe-backend`, whose help names this hardware exactly:

> `"flashinfer_b12x"`: Use FlashInfer CuteDSL fused MoE for **SM12x
> (RTX Pro 6000 / DGX Spark)**

Adding `--moe-backend flashinfer_b12x` changed nothing about the model -
same official FP8 weights, `quantization=deepseek_v4_fp8` in both logs -
and produced:

| prompt | DEEPGEMM | B12X | gain |
|---|---|---|---|
| math | 35.7 | 40.0 | 1.12x |
| prose | 25.9 | 29.8 | 1.15x |
| **code** | 26.2 | **63.5** | **2.42x** |
| counting | - | **79.5** | - |

The lesson worth keeping: **a silent kernel fallback costs more than any
model choice on this list, and it never appears as an error.** Grep the boot
log for the backend line after every image or driver change.

## 8. Where it landed

| | ds4, 1 Spark, 2-bit | vLLM TP=2, FP8, B12X |
|---|---|---|
| decode, math | 10.1 | **40.0** |
| decode, prose | 14.5 | **29.8** |
| decode, code | 19.0 | **63.5** |
| decode, counting | - | **79.5** |
| aggregate @ c=6 | n/a (single-stream) | **383.5 tok/s** |
| cold TTFT @ 11.7k | 8,778 ms | 5,909 ms |
| warm TTFT @ 11.7k | 476 ms | ~512 ms |
| `json_schema` | ignored | **enforced** |
| tool calling | partial | **native, correct** |
| weights | 2-bit | **official FP8** |

Concurrency, ours against the best published numbers for 2x Spark:

| c | ours | published |
|---|---|---|
| 1 | **85.7** | 61.0 |
| 2 | **135.7** | 91.7 |
| 4 | **282.6** | 151.1 |
| 6 | **383.5** | 197.3 |

KV pool: `Available KV cache memory: 10.68 GiB` -> **1,374,118 tokens**.
Small in bytes and enormous in tokens, because DeepSeek V4 uses MLA with a
single KV head and `nvfp4_ds_mla` stores it at 4 bits. This is why "the KV
cache looks much bigger than the 1-Spark version" is misleading: in bytes it
is smaller.

## 9. What this unlocked in the application

Schema enforcement was the point, not the speed. Six roles were pinned to a
4B *purely because it enforced grammars*; all of them moved to the main
model, and 287 lines of workaround were deleted: `JSONFallbackWriter` (which
let the weaker model answer whenever the stronger one's JSON failed to
parse) and `FallbackInferenceProvider` (a standby that answered *worse*
instead of failing, with nothing in the reply saying so).

`VISION_MODEL` remains on Qwen 3.5 4B: it is the only VLM available here.

## 10. Open

- ~~**Vision is the last 4B holdout.**~~ Done: Qwen3-VL-8B AWQ serves vision
  on spark2. AWQ rather than NVFP4 - CUTLASS FP4 kernels target sm_120 and
  silently emit wrong output on the Spark's sm_121 (vLLM #50925).
- **Memory is now the binding constraint, and it is measured.** spark2 is
  full (~1.4 GB free; the VLM took ~15.7 GB, not the ~10 budgeted, once
  runtime overhead is counted). spark1 holds the model plus the whole
  application stack and has **~9.9 GB** free. That is what remains for image
  generation: FLUX.2-klein-4B (6.5 GB) fits load-on-demand, klein-9B
  (12 GB) does not - and over-allocating on a GB10 hangs the box rather than
  OOM-killing, so the margin is not negotiable.
- **The 0.21.1 + B12X image** is reportedly faster still than the 0.25.2 we
  run. Untested here.
- **`nvfp4_ds_mla` KV** carries a documented accuracy caveat. `fp8_ds_mla`
  halves the pool to ~700k tokens and removes it - the first knob to turn if
  long-context quality ever wobbles.
- ~~**The stack itself has not moved.**~~ Done 2026-08-23: Postgres, Redis,
  the backend, both workers, local-capabilities, the renderer, the frontend,
  the gateway, the embedding model and the Cloudflare tunnel all run on
  spark1 now, and `deep-matter.com` serves with the desktop powered off. See
  docs/DGX_MIGRATION.md.
- **A blind quality A/B was not run.** Both models cannot be resident at
  once, so it needs a sequential collect-then-judge pass;
  `evaluate_reply_quality` supports exactly that via `--save-a` /
  `--a-answers`.

## The vision model: Qwen3-VL-8B on the Sparks (2026-08-23)

Vision was the last role still on Qwen 3.5 4B, and the only one that could
not simply follow the reply model - it needs a model that actually sees.

**Chosen: `cyankiwi/Qwen3-VL-8B-Instruct-AWQ-4bit`, 7.55 GB.** It wins every
published benchmark that matches what AniOS does with images, and is the
smallest of the serious candidates:

| | Qwen3-VL-8B | Step3-VL-10B | GLM-4.6V-Flash |
|---|---|---|---|
| DocVQA | **96.1** | - | - |
| ScreenSpot | **94.4** | 92.6 | - |
| OCRBench | **89.6** | 86.8 | - |
| MMMU | **78.7** | 78.1 | 71.2 |
| weights | **7.55 GB** | 8.47 GB | 8.86 GB |

Step3-VL-10B is the real alternative and beats it on hard GUI grounding
(ScreenSpot-Pro 51.6); it would be the pick if AniOS drove an interface.
It does not - it reads photos and screenshots.

**Newer is not better here.** Qwen retired the separate `-VL` line; the
modern dense models are natively multimodal. But Qwen3.6 and 3.8 start at
27B (~15 GB at NVFP4, on the ceiling where over-allocation hangs the box),
so the only newer model that fits is Qwen3.5-9B - which is marginally behind
on both comparable benchmarks, 1.5 GB larger, publishes no DocVQA, and
carries four open sm_121 defects including a Gated-DeltaNet kernel gap that
halves throughput. Qwen3.6-27B is the upgrade path if ~4 GB is ever freed.

**AWQ, not NVFP4.** CUTLASS FP4 kernels target sm_120 and silently emit
wrong output on sm_121 (vLLM #50925). On a vision model the failure would
look like bad OCR rather than an error.

### The sizing mistake, and the fix

First launch used `--gpu-memory-utilization 0.10`, expecting ~12 GB of the
121 GB pool. vLLM allocated **7.46 GiB of KV on top of 7.1 GB of weights**
and left the box with **538 MB free**. The fraction is not a cap: the
profiler sizes KV from what it observes free at startup, so on a nearly-full
machine it takes almost everything. That box also runs the reply model's
tensor-parallel worker, and PyTorch does not OOM cleanly on GB10 - it
freezes the machine - so this would have taken the whole assistant down.

The fix is `--kv-cache-memory-bytes`, set explicitly to 3 GiB. It behaves
the way a limit should: asked for 16k context against a 2 GiB cache, it
refused to start and named the number it needed, rather than silently
consuming the host.

Final resident cost ~10 GB of a 17 GB box, KV 21,840 tokens, ~2.4 GB free
and stable under load.

### Measured

Through `/api/v1/vision/analyze`, the same path a phone photo takes:
first request 9.5 s cold, then **0.5-1.1 s warm**. On a test card it read
every line of text verbatim - including a serial number - and correctly
described both shapes and their positions.

`VISION_MODEL` and `VISION_LLM_BASE_URL` now point at spark2:8001, and a
systemd unit starts it at boot. Retiring `vllm-main` also meant removing
four `depends_on` clauses that would otherwise have blocked the whole stack
from starting, and repointing the generic `LLM_BASE_URL` fallback, which
still aimed at the stopped service.
