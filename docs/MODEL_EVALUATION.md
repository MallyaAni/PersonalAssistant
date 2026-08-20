# Comparing candidate models for AniOS

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

### Qwen3.8-27B, BF16, on vLLM 0.17.1 with MTP

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

**MTP speculative decoding crashes the engine under concurrency.** Two
simultaneous requests with `--speculative-config mtp` produced
`cudaErrorIllegalAddress` and killed EngineCore on this GB10 build. Fine for a
serial evaluation, not fine for production with concurrent users. It is worth
having — acceptance length above 2 roughly doubles throughput — but not until
the build is updated.

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
