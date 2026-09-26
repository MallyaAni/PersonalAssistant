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
