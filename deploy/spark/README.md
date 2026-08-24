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
