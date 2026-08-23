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

## Why `--max-model-len` is 512k and not 1M

`--gpu-memory-utilization` is a fraction of the *whole* 121.7 GiB pool, not of
what is free, and it is not a cap - the profiler sizes the KV cache from the
memory it observes free when it starts.

When the model was first deployed it had the box to itself and got 10.68 GiB of
KV. Once the application stack moved onto spark1 it started in parallel with the
model on every boot, and the model profiled against a busy machine instead:

```
ValueError: To serve at least one request with the model's max seq len
(1048576), 7.54 GiB KV cache is needed, which is larger than the available
KV cache memory (5.09 GiB).
```

512k needs ~3.77 GiB, which fits on either a quiet or a busy boot. Measured
context use is median 4.4k, p90 11.7k, max 16.1k tokens, so the ceiling is still
about thirty times the worst real turn.

The alternative - ordering the whole Compose stack behind the model so it
profiles against an empty box - is the more correct fix and is not done here,
because it means the site is down for the six minutes the model takes to load
rather than serving a holding page.
