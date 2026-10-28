# Spark serving configuration

The model servers are not part of the Compose project. They run directly on the
two DGX Sparks under systemd, because they need host devices (`/dev/infiniband`)
and a memory budget Compose has no way to express.

Until 2026-08-23 these five files existed **only** on the Sparks' own disks -
unreviewed, unversioned, and unrecoverable if a box died. They live here now.
This directory is the source of truth; the copies on the boxes are deployments
of it.

| file | host | installed as |
|---|---|---|
| `ds4-tp2.sh` | **both** | `~/ds4-tp2.sh` |
| `vlm-serve.sh` | spark2 | `~/vlm-serve.sh` |
| `ds4-head.service` | spark1 | `/etc/systemd/system/` |
| `ds4-worker.service` | spark2 | `/etc/systemd/system/` |
| `anios-vlm.service` | spark2 | `/etc/systemd/system/` |
| `systemd/anios-backup.service` | spark1 | `/etc/systemd/system/` |
| `systemd/anios-backup.timer` | spark1 | `/etc/systemd/system/` |

Installing a `.service`/`.timer` change needs `sudo systemctl daemon-reload`
on that box, then `systemctl restart`/`enable` as appropriate — a repo edit
alone changes nothing running. Two changes here are **committed but not yet
applied** and need this on their next maintenance window: the `anios-vlm.service`
ordering (`After=ds4-worker.service`, so a cold boot cannot hang spark2 on
concurrent GPU profiling — see the KV section below), which needs a
`daemon-reload` on spark2; and the backup units, whose install path was never
written down.

A third change was **applied and verified on 2026-09-26**: `ds4-tp2.sh`
re-enables DSpark speculative decode (k=5), adds chunked prefill with
`--long-prefill-token-threshold 1024` and `--async-scheduling`, sets
`--max-cudagraph-capture-size 40`, and lowers `--max-model-len` from 1M to
393216 to make room for the draft layers at the unchanged 0.81 utilisation.
The reasoning is in the script header. Evidence: `scripts/spark-dspark-rollout.sh`
(log `test-results/dspark-rollout-20260926T174931.log`) measured code decode
26.5 -> ~67 tok/s single stream and ~200 tok/s aggregate at 6 streams, with
12,656 of 16,820 draft tokens accepted (75%) and no failure in an 18-request
soak; the routing gate (`scripts/gate.sh`) passed 100/100 and
`benchmark_inference` 5/5 against the live server. Boot now takes ~17 minutes,
not ~6 - weight load plus the draft model and its CUDA-graph capture - which
is inside the units' `TimeoutStartSec`. The engine reports 16.46 GiB of KV
(1.24M tokens), more than the 8.7 GiB estimated above, so 1M context would fit
again; it was left at 393216 because nothing uses it. The acceptance ladder
that was applied, kept for the next change of this kind:

1. Head boots and `/v1/models` answers. If it refuses with a KV-cache-too-small
   error, lower `--max-model-len` to 262144 and retry; do not raise utilisation.
2. `curl -s http://animallya-spark1.local:8000/metrics | grep spec_decode`
   returns non-zero draft/accepted counters after one real request. Empty
   output means speculation is not running and the change did nothing.
3. `backend/cli/benchmark_inference.py` passes its thresholds, and code decode
   is measurably above the pre-change figure (models.json lists 63 tok/s code
   with DSpark; the script had been running without it).
4. The functional suites pass, then a 30-minute soak with four opencode workers
   and iMessage turns live. The documented failure shape is "boots, passes a
   smoke test, dies on the first real request" - that is spec decode's
   allocation, and the response is to remove `--speculative-config`, not to
   raise utilisation.
5. Record the result and the commit SHA in `NEXT_SESSION.md` and update
   `docs/evals/results/models.json` with the measured numbers.

The opencode client (`~/.config/opencode/opencode.jsonc` on the desktop) was
capped at 262144 context in the same change so it compacts around 230k tokens
and a request can never exceed the new server ceiling (opencode issue #50574:
1M-context sessions never compact before the server returns 400).

`ds4-tp2.sh` is byte-identical on both Sparks - the role comes from its
argument (`head` on spark1, `worker` on spark2), not from a different file. Keep
it that way: a divergence between the two copies is a class of bug that shows up
only as a hang during NCCL init.

## DeepSeek-V4.1-Flash-1017 (ds41-*), serving since 2026-10-19 22:56 ET

**Applied and verified.** `scripts/spark-dsv41-cutover.sh` (RESUME=1, log
`test-results/dsv41-cutover-20261019T224234.log`): boot 540 s; three served
names; decode probes sane; vision "Red"; tool call well-formed; forwarder on
spark2:8001 answering; 215,020-token prefill in 113 s (~1,900 tok/s) with the
right answer; MemAvailable low point under it 6.1 GiB (spark1) / 10.5 GiB
(spark2); soak clean at ~126 tok/s aggregate on two streams. Measured after:
96 tok/s code / 48 tok/s prose single stream (0731: 67 / ~30). App gates on
the live model: `benchmark_inference` 5/5 (vision 0.7 s via the forwarder,
was 3.7 s); `scripts/gate.sh` 98/100 - the two misses are below. AniOS-style
requests (top-level `none`, no kwargs) answer in 2 tokens with no reasoning;
opencode-style requests think as asked. opencode's default is now
`dgx-spark/deepseek-v4.1-flash-1017` (effort high; variants low/high/xhigh/
max; 196608/65536; temperature 1.0, top_p 1.0). spark1's web opencode
(code.deepmatter, `~/.config/opencode/opencode.json`) kept naming its
entry `deepseek-v4-flash` after the cutover - that name is a served alias,
so it was already V4.1 with the old label; since 2026-10-20 10:08 ET it
defaults to `spark/deepseek-v4.1-flash-1017` (262144/65536) with the alias
entry kept and relabelled so earlier sessions still resolve. A session
opened before then remembers its own model name until it is switched.

Two earlier attempts the same evening, for the record: 22:11 preflight stop
(the DSpark token list was not yet on spark2); 22:19 a run that rolled back at
22:35 because the post-rsync check compared whole-folder sizes while the rsync
excludes spark1's `.cache` - the copy was complete. Fixed; the rollback's ds4
boot was stopped at 4 minutes and the cutover resumed. A probe f-string also
failed on the Sparks' Python (backslash in an f-string expression); fixed.

**Gate misses (one fixed 2026-10-20):**
`test_diagram_generation_behaviour[class diagram]`: the model wrote generics
(`List<Book>`), which `UNSAFE_MERMAID_PATTERN` rejected as an HTML tag; a
validator limitation the old model never tripped - FIXED in `a6164e3c`; the
real gate file passes (one repetition case flaked once with an empty message
from the provider, then passed 3/3 reruns and 6/6 direct replays). `manage_check_ins` routing
3/4 against a 0.8 floor (one case chose `none`).

The planning text that follows is kept as written before the change.

The next model: `ds41-tp2.sh` + `ds41-serve.sh` (both nodes, byte-identical) and
`ds41-{head,worker}.service`, replacing `ds4-*` (V4-Flash-0731). HeNryous's
EXL3 2.75 bpw build (KLD 0.0201 vs native; code 0.0125) on
`ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v4i`, the sudoingX launcher's
command transcribed into the ds4 systemd shape. Every value that is ours and
why is in the two scripts' headers; the short list:

| | ds4 (0731) | ds41 (1017) |
|---|---|---|
| weights | official FP8/MXFP4, ~90 GiB/rank | EXL3 2.75 bpw, ~93 GiB/rank; Engram 203 GB on NVMe, read at lookup |
| fabric | `rocep1s0f1` + twin, GID 3 | same (recipe default `...f0` is DOWN here) |
| context / seqs / KV | 393216 / 6 / sized by 0.81 | 262144 / 2 / pinned 2.5 GiB (660K tokens) |
| speculation | DSpark k=5 | DSpark k=5, confidence-depth policy |
| vision | Qwen3-VL-8B on spark2:8001 | this model (image:4); the VLM is retired |
| served names | `deepseek-v4-flash` | `deepseek-v4.1-flash-1017`, alias `deepseek-v4-flash` |
| boot | ~17 min | ~6 min with prebuilt JIT kernels |

**Why the VLM goes.** With the V4.1 worker resident, spark2 has ~18 GiB left;
the VLM reserves 11, and the recipe author measured the worker dipping to
4.2 GiB free during long prefills on an otherwise empty node. The server's
watchdog stops it at ~1.5 GiB. So vision moves to the main model
(compose/.env `VISION_*`, `DOCLING_PICTURE_*`), not beside it.

**Why 262K / 2 / 2.5 GiB and not the author's 320K / 4 / 3.75.** spark1
carries the app stack and the embedder, ~5 GiB the author did not have, and
his head node's low point was 3.1 GiB free at a 314K prefill. The base
recipe's defaults are the measured-safe shape; the cutover script records the
MemAvailable low point under a ~200K prefill on both nodes and rolls back
under 3 GiB. Raise the context only against that number.

**Decision 2026-10-19 (owner): the model is the objective; app code may
break.** The deploy checkout on spark1 had diverged from main (10 trading
commits with no upstream equivalent, a Codex session live), so `deploy.sh`
refused bf5f67b3/47915387 and they are NOT deployed. Two zero-code shims keep
the assistant whole meanwhile, both transitional and both to be removed once
the trading session reconciles the checkout and `deploy.sh` ships those two:
`--default-chat-template-kwargs '{"thinking": false}'` on the server (the
roles' top-level "none" is ignored by this image; off-by-default reproduces it,
and opencode asks for thinking explicitly), and a `socat` forwarder on
spark2:8001 -> spark1:8000 plus a served-name alias `qwen3-vl-8b`, because the
deployed compose still names the retired VLM literally (cutover step 5b).

**Engine difference that reaches the app (corrected 2026-10-20).** This
image honours BOTH the top-level OpenAI `reasoning_effort` field and
`chat_template_kwargs` (measured: top-level `high` alone returns a populated
`message.reasoning`; top-level `none` alone returns none), and thinking is ON
by default when neither is sent, which is why the server runs
`--default-chat-template-kwargs '{"thinking": false}'`. The thinking comes
back as `message.reasoning` (streamed as `delta.reasoning`), not
`reasoning_content`. Thinking tokens count against `max_tokens`: at `high`, a
1,200-token design request came back `finish_reason=length` with EMPTY
content and 4.6K characters of reasoning, and a 2,048-token one did the
same. `backend/core/llm.py` and the vision provider send both forms since
`bf5f67b3`, with "none" as `thinking: false`. Also: literal DeepSeek special
tokens in user text become real tokens on this image; the README's defuse
(zero-width space after `<`) is not applied in AniOS yet.

**Reply thinking without starving the bounded calls (live since 2026-10-20
08:09 ET).** The reply and the helper calls share one MAIN client, so
`MAIN_LLM_REASONING_EFFORT=high` (set 07:05, after the reply comparison
showed 1017 needs thinking on arithmetic/logic) would also have made the
search planner (200 tokens), document facts (700), the vision reasoner
(1,024) and the digest writer (2,048) think inside budgets that thinking
exhausts. Live now: `.env` has `MAIN_LLM_REASONING_EFFORT=none`,
`MAIN_LLM_BASE_URL=http://172.16.8.3:8899`, `MAIN_LLM_MAX_TOKENS=16384`, and
`reply-effort-shaper.py` (this folder; user unit `reply-effort-shaper.service`
on spark1, port 8899, same TCP-splice design as opencode's `effort-inject.py`)
sets `reasoning_effort=high` on exactly the calls that look like the reply:
`max_tokens >= 4096`, no `tools`, no `response_format`. Everything else
passes through as sent. Verified from inside `anios_backend`: the reply
stream is shaped (`~/.local/state/reply-effort-shaper.log` on spark1 records
every decision), a 200-token `chat` is not, `benchmark_inference` 5/5 through
it. Transitional: the real fix is a reply-only effort in the code (the reply
node gets its own client/effort; bounded calls keep "none"); when that ships,
point `MAIN_LLM_BASE_URL` back at :8000 and disable the unit. Backups of
`.env` before each change: `~/dsv41/env.pre-main-effort-*`,
`~/dsv41/env.pre-shaper-*`.

**Harness bake-off (2026-10-20, one task, both on this model).** opencode
1.18.x (spark1, effort via `effort-inject`) and the DeepSeek Harness `dsh`
0.2.1-rc.2 (installed under `~/dsh` on spark1, headless profile in
`~/dsh/home/profiles/headless/cordis.patch.yml`, run with
`DSH_HOME=~/dsh/home SPARK_API_KEY=local ~/dsh/node_modules/.bin/dsh --profile
headless "task"`) were each given the Mermaid-generics validator miss from
the gate, in separate worktrees, with pytest available and no commit allowed.
opencode: 695 s, 2.37M tokens, correct, 35 tests green, left a new C901.
dsh: 945 s, 3.79M tokens, correct, broader (innermost-first blanking, an
active-element allowlist), 34 tests green, no new lint, found and used the
repo's docker test image on its own. dsh's patch is what landed (`a6164e3c`).
Verdict after round 1: no quality gap on one sample.

**Round 2 (2026-10-20 09:14-09:43 ET, three tasks, both harnesses at
effort max; round 1 had been opencode max vs dsh high).** Worktrees off
`514bd0b7`; task texts and every patch in `~/dsv41/bo2/` on spark1. A: a
behaviour-preserving refactor to clear four lint findings including a C901
(both ruff-clean, 34/34, identical test edits; dsh kept the explanatory
comments beside their code, landed as `af26e31d`). B: the reply-only
reasoning effort from a spec (both: same wiring, no new lint, end-to-end
tests through fakes asserting which client streamed; opencode's None check
is the precise one, landed as `d540458c` + `58e99e2f`). C: a bug
described by symptom only, the diagram retry that never retried an empty
engine message (both found the same cause and made the same one-line move
of the call into the attempt; dsh's test double is parameterised, landed as
`f84d443b`). Wall clock, A sequential / B and C with both harnesses on the
server at once: opencode 162 / 518 / 176 s, dsh 298 / 566 / 397 s; tokens
(A only, counted on the server) opencode 367K prompt + 10K generated, dsh
702K + 18K.

**Round 3 (2026-10-20 15:00-15:27 ET): opencode 1.19.3 vs OpenCode 2.1.1,
same three tasks, same base, one run at a time, both at effort max through
the injector.** 2.1.1 installed side by side under `~/opencode2` (own
XDG config/data/cache/state via `~/opencode2/env.sh`, so the 1.x session
database is untouched). All six patches correct, ruff-clean on what they
touched, tests green (A 34/34 both; B 27 passed + 6 skipped both, five new
tests each, same design as what landed; C the same one-hunk fix as
`f84d443b`, 36/36 both). 1.19.3 also documented the new setting in
DEVELOPMENT_GUIDE.md unasked. Wall clock: 1.19.3 154 / 348 / 150 s,
2.1.1 295 / 452 / 226 s - 2.x was 1.3-1.9x slower for identical outcomes.
2.1.1 also renames the session/event/plugin contracts the watchdog and
web unit read. Decision: code.deepmatter stays on 1.19.3; 2.1.1 stays
installed for a later look, never swapped in place.

**Round 4 (2026-10-28 08:02-08:28 ET): Claude Code 2.1.312 as the harness (the CloudCLI web UI at
code.deep-matter.com runs it), same model through `effort-inject` (Anthropic `/v1/messages`, thinking
on, effort max), same three tasks, same base `514bd0b7`, one run at a time, headless `claude -p`
with `--permission-mode bypassPermissions` and git commit/push/reset denied (`~/dsv41/bo2/driver4.sh`).
Each patch was then graded the same way as opencode 1.19.3's from round 3, on a fresh worktree
(`grade4.sh`, `lintdiff.sh`). All three correct and complete. A: ruff and format clean, 34/34; it also
ran a differential check of the old and new validator on its own. B: same wiring and the same six
files as 1.19.3 (no DEVELOPMENT_GUIDE note), 28 passed + 6 skipped, no new lint. C: the same one-hunk
move of the call into the retry, 36/36, no new lint; its comment names the gate incident, which
AGENTS.md asks comments not to do. Wall clock: Claude Code 401 / 667 / 455 s against 1.19.3's
154 / 348 / 150 s, i.e. 1.9-3.0x slower. Server-wide counters over its runs read 1.19M / 7.09M / 3.78M
prompt tokens and 28K / 50K / 32K generated. A web session was open on the same server at the same time,
so both its wall clock and these counters include any work that session did. Claude Code also
prints `unrecognized_model` for this model id and runs on its defaults for it.
Verdict: no accuracy difference on these tasks, and slower. Its advantages are features rather
than results on these tasks: subagents, plan mode, hooks, skills, per-folder CLAUDE.md.

**Verdict after four tasks:** no accuracy difference. Every run was correct
and complete; dsh was marginally more careful once (round 1, no new lint)
and never worse; opencode was 1.1-2.3x faster on every task at the same
effort. The harness is not where reply quality is decided on this stack -
the model's thinking budget and the review loop are. opencode stays the
daily harness; dsh stays installed (`~/dsh`, profile effort now max) for a
second opinion on validator and parsing work. The next test worth running,
if any: one long multi-file task (a trading-desk feature with a failing
functional test), where the harnesses' context handling would differ more
than on these.

**Apply, in order** (`scripts/spark-dsv41-cutover.sh` does 3-6 and rolls back
on its own):
1. `scripts/download_model.sh` from the HeNryous repo into
   `~/models/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark` on spark1
   (~402 GB; `HF_HUB_DISABLE_XET=1`), then sha256 the two Engram shards with
   `dd iflag=direct` (hashing through the page cache on a serving GB10 node
   has tripped the watchdog) and touch `.engram_sha256_ok`. Pull the image.
2. `sudo bash ~/install-ds41.sh` on BOTH Sparks: installs the units and a
   sudoers rule for exactly the model units and drop_caches.
3. Baseline the old server; `disable --now` ds4-head, ds4-worker, anios-vlm.
4. spark2: pull image, rsync the model folder over the fabric; both: build
   the JIT kernels once (never beside loaded weights).
5. `enable --now` ds41-worker, then ds41-head; smoke (both names, decode,
   DSpark counters, a vision request, a tool call); the memory probe.
6. Flip `.env` on spark1 (`VISION_LLM_BASE_URL`, `VISION_MODEL`,
   `DOCLING_PICTURE_API_URL`, `DOCLING_PICTURE_MODEL`) and
   `docker compose up -d`; `scripts/gate.sh`, `benchmark_inference`, the
   vision suites; opencode's model entry on the desktop.
7. Record the evidence here and in `NEXT_SESSION.md`; update `models.json`.

Rollback at any point: `ROLLBACK=1 bash scripts/spark-dsv41-cutover.sh`
(ds41 down; anios-vlm, ds4-worker, ds4-head up; ~17 min) and the `.env`
lines back. The 0731 weights and scripts stay on both boxes.

## Deploying a change

```sh
scp deploy/spark/ds4-tp2.sh animallya96@animallya-spark1.local:~/ds4-tp2.sh
scp deploy/spark/ds4-tp2.sh animallya96@animallya-spark2.local:~/ds4-tp2.sh
ssh animallya96@animallya-spark1.local 'bash -n ~/ds4-tp2.sh'   # syntax first
```

Then restart **in this order** - worker, then head. The head hosts the
rendezvous store, and restarting it alone leaves the worker attached to a socket
that no longer exists, wedged rather than exited:

```sh
ssh animallya96@animallya-spark2.local 'sudo systemctl restart ds4-worker'
ssh animallya96@animallya-spark1.local 'sudo systemctl restart ds4-head'
```

Expect roughly six minutes before `:8000` answers. Watch it with
`curl -s http://animallya-spark1.local:8000/v1/models`.

Editing a `.service` file needs `sudo systemctl daemon-reload` before the
restart, or systemd keeps running the old definition without saying so.

## Why the units say `Restart=always`

`on-failure` was not enough. Two failure modes were seen on the first real power
cycle:

- The head **exited** cleanly with a non-zero status when it could not fit its
  KV cache. `on-failure` did cover this one.
- The worker **hung** - it logged a broken-pipe error against the head's dead
  TCPStore and then sat there, still "running" as far as systemd was concerned,
  so nothing restarted it and the next head waited forever for a rank that was
  never coming.

`Restart=always` does not fix the second case either; nothing in systemd catches
a process that stops working without stopping. It is recorded here so the next
person recognises the shape: **a head that sits at `parallel_state` init for
more than a few minutes means the worker is wedged, not slow.** Restart the
worker, then the head.

## How `--max-model-len` and `--gpu-memory-utilization` were settled

The script runs **1M context (`--max-model-len 1048576`) at
`--gpu-memory-utilization 0.81`** — read the flags in `ds4-tp2.sh`, not this
prose, if the two ever disagree again. This section explains how those numbers
were reached, because they are not obvious and one earlier draft settled on 512k
before the memory budget was understood.

`--gpu-memory-utilization` is a fraction of the *whole* 121.7 GiB pool, not of
what is free, and it is not a cap — the profiler sizes the KV cache from the
memory it observes free when it starts. It is also bounded by **spark2**, which
also hosts the VLM: 0.81 asks 98.6 GiB against spark2's ~100.5 GiB free, and
raising it is refused there and hangs the head waiting for a rank that died.

At 0.81 the KV pool is ~8.7 GiB, above the 7.54 GiB that 1M context needs, so
1M fits — but only because the VLM now starts *after* the ds4 worker (see
`anios-vlm.service`), leaving that headroom free when the router profiles.
Widen the margin by trimming the VLM's KV on spark2, never by raising the ds4
number. Measured context use is median 4.4k, p90 11.7k, max 16.1k tokens, so
even 512k would be ~30x the worst real turn; 1M is kept because it fits, not
because it is needed.
