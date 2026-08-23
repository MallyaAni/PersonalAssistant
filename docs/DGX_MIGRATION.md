# Moving AniOS to a DGX Spark

Written from the shipped stack and NVIDIA's own material, not from assumption.
Every claim below that could be checked was checked.

## Use NVIDIA's playbooks, not a hand port

[`NVIDIA/dgx-spark-playbooks`](https://github.com/NVIDIA/dgx-spark-playbooks)
publishes step-by-step setups for GB10, including one for vLLM. Its vLLM playbook
covers the part that is genuinely different on ARM64 — either a prebuilt
container or a source build with custom LLVM/Triton — which is exactly the work
worth not repeating. Treat those guides as the source of truth for Spark-specific
model recipes, parser plugins, and kernel settings, and keep this repository's
Compose file as the composition on top.

## Image architecture: verified, not assumed

Every image the stack pulls was checked with `docker manifest inspect`:

| Image | Architectures |
| --- | --- |
| `pgvector/pgvector:pg16` | `linux/amd64`, `linux/arm64` |
| `redis:7-alpine` | seven, including `linux/arm64` |
| `vllm/vllm-openai` (the pinned digest) | `linux/amd64`, `linux/arm64` |

Our own images build from `python:3.12-slim` and `node:22-bookworm-slim`, both
multi-arch. So no image in the stack blocks the move. That is a better result
than expected and worth knowing before planning around a rebuild.

## The dependency worth checking, and why it is fine

NVIDIA's porting guide flags that `onnxruntime-gpu` publishes no `aarch64` wheels
on PyPI. This project depends on CPU `onnxruntime` for Nomic vision embeddings,
which is a different package: `onnxruntime` 1.28.0 publishes 14 `aarch64`/`arm64`
wheels including `manylinux_2_28_aarch64`. Verified against the PyPI index rather
than inferred from the name.

## What actually has to be requalified

Nothing above proves the stack *performs*. The repository already has the tools
to answer that, and they should be run on the Spark rather than trusted from the
RTX 5080 numbers:

- `backend/cli/benchmark_inference.py` — enforces exit-code thresholds across
  main TTFT/throughput, native tool correctness, structured output, embedding
  latency, and vision;
- `backend/cli/qualify_models.py` — comparative model qualification;
- `bash scripts/verify-migrations.sh` — schema builds from nothing.

The FP8 profile in particular is tuned to a 16 GB discrete card. GB10's 128 GB
unified memory changes the sizing question completely, so
`--gpu-memory-utilization` and the KV cache dtype are settings to re-derive, not
to carry over.

## What does not move

The iMessage bridge stays on the Mac. That is an Apple hardware constraint rather
than an architectural choice: only a Mac signed into Messages can send. Moving
AniOS changes one URL in `MCP_SERVERS_JSON` and nothing else, because the bridge
was written to be reached over the network rather than spawned locally.

Host ComfyUI is the other host-bound piece, and its GPU sizing assumptions are
tied to the same 16 GB card as vLLM's.

## Two-Spark commissioning, verified 2026-08-22

Hostnames and fabric, all measured rather than assumed:

| | animallya-spark1 | animallya-spark2 |
|---|---|---|
| LAN (WiFi `wlP9s9`) | 172.16.8.3 | 172.16.8.5 |
| RoCE rail 1 `enp1s0f1np1` / `rocep1s0f1` | 192.168.100.1/24 | 192.168.100.2/24 |
| RoCE rail 2 `enP2p1s0f1np1` / `roceP2p1s0f1` | 192.168.101.1/24 | 192.168.101.2/24 |

Both rails MTU 9000, verified with `ping -M do -s 8972`. `ib_write_bw -x 3`
measures **108.91 Gb/s on rail 1 and 109.09 Gb/s on rail 2** - real RoCE v2,
not an Ethernet fallback.

**The GB10 QSFP port is two virtual NICs, not one.** Each twin gets x4 PCIe 5.0
lanes and carries ~100G. Listing a single HCA silently runs NCCL at half the
port (98 vs 161 Gb/s busbw, measured by others). So both twins are addressed,
on **separate subnets** - sharing one subnet breaks NCCL autodiscovery - and
NCCL must be given both with `NCCL_IB_MERGE_NICS=1`:

```
NCCL_IB_HCA=rocep1s0f1,roceP2p1s0f1
NCCL_SOCKET_IFNAME=enp1s0f1np1,enP2p1s0f1np1
NCCL_IB_GID_INDEX=3
NCCL_IB_DISABLE=0
GLOO_SOCKET_IFNAME=enp1s0f1np1   # must be set alongside, or rendezvous deadlocks
```

GID index 3 is the RoCE v2 IPv4 entry on both boxes here - confirmed by
reading `/sys/class/infiniband/rocep1s0f1/ports/1/gids/3`. Do not assume it:
others have found the IPv4 RoCEv2 entry at index 4 or 5 after re-cabling, with
NCCL failing on an empty GID.

The addresses above are set with `ip addr add` and do **not** survive a reboot;
`nmcli dev set <iface> managed no` is applied first or NetworkManager wipes
them. A netplan file under `/etc/netplan/` is the durable form and is still to
be written.

### Version state, which matters more than it looks

Both boxes: kernel `6.17.0-1031-nvidia`, Ubuntu 24.04.4 LTS, driver
`580.173.02`, Docker 29.2.1 with CDI. Those are the right pins - driver 590.x
has CUDAGraph deadlocks on GB10 and Ubuntu 25.10 is unsupported and breaks
cross-node MPI.

**The pre-installed `nvcr.io/nvidia/vllm:26.03.post1-py3` cannot serve this
model.** It ships vLLM 0.17.1, whose registry has DeepseekV2/V3/V32 and no V4,
while the checkpoint declares `"model_type": "deepseek_v4"`. Newer is not
automatically better either: a published head-to-head on this hardware found
vLLM 0.21.1 + B12X beats 0.25.2 by 9.2% peak decode and 29.4% at concurrency
6, because `torch.compile` works on the former and not the latter for this
model.

### Settings taken from other people's documented failures

- `--gpu-memory-utilization 0.78`, not 0.85: speculative decode allocates on
  the first real request, so 0.80 boots, passes a smoke test, then dies under
  traffic.
- `num_speculative_tokens: 5`. k=7 and k=10 boot and then crash on every
  generation; the DSpark block size is 5.
- `VLLM_USE_B12X_MOE=1`. Without it the MoE path silently falls back to
  DEEPGEMM_MXFP4 and decode drops from 50-60 to ~29 tok/s with no error.
- JIT/compile caches node-local, never shared: a shared cache produces a
  torch.compile makedirs race, half-written DeepGEMM cubins, and an
  ABI-mismatched FlashInfer `sampling.so` - and none of the errors name the
  cache.
- Start the worker (rank 1, `--headless`) before the head.
- Open bug vLLM #40969: `cudagraph_mode=FULL_AND_PIECEWISE` with chunked
  prefill silently hangs after 5-7 requests on exactly this hardware. Validate
  before trusting it; `--enforce-eager` is the safe fallback at ~20-30% cost.

### Download trap, hit and diagnosed here

`hf download` collapsed to ~1 MB/s with no error and `du` appeared to advance,
because HF Xet pre-allocates sparse shards and stalls silently on these boxes.
`HF_HUB_DISABLE_XET=1` restored it. Anonymous downloads are also rate limited -
WiFi negotiates 458 Mbit/s here while the throttled transfer ran at 15 MB/s.

### LMCache is not viable yet

Both documented attempts on Spark clusters failed: one hit an L1 allocation bug
that made the L2 tier unreachable under real load *and* restored KV that
diverged from computed KV at temperature 0; the other deadlocked permanently at
"Wrapping 170 KV cache tensors for IPC" on a version mismatch. When it worked it
was ~300x on a 32k restore, so it is worth revisiting - but the supported path
today is vLLM's own `--enable-prefix-caching` plus native CPU/filesystem
offload.

## Moving the application stack, 2026-08-23

The last step: everything that was still amd64 on the Windows desktop now runs
on spark1, and the desktop is no longer part of the system.

| moved | to | how |
|---|---|---|
| Postgres (37 tables) | spark1 | writers stopped, `pg_dump`, byte-compared |
| Redis (7,131 keys) | spark1 | RDB copy; the iMessage cursor survived |
| backend, 2 workers, local-capabilities | spark1 | `anios-backend:arm64`, rebuilt from source |
| presentation-renderer, frontend, gateway | spark1 | ARM builds of the same Dockerfiles |
| nomic embeddings | spark1 | the last model on the desktop RTX |
| the Cloudflare tunnel | spark1 | see below |

Verified after cutover, from inside the backend container: 175 conversations,
7,131 Redis keys, 768-dim embeddings, and live replies from both the main model
and the VLM. `deep-matter.com` serves with the desktop powered off.

### The tunnel was a hand-started process

`cloudflared.exe` was not a Windows service or a scheduled task - it was a
console process someone had run. The site was therefore up only while that
machine was awake *and* nobody had closed the window. It is now a compose
service (`--profile tunnel`) targeting `gateway:8080` over the compose network,
so the public origin comes up and goes down with the stack.

The credentials live in `secrets/`, which is gitignored: the tunnel JSON is a
bearer credential for the hostname.

### mDNS does not work inside a container, and fails deceptively

Every service reaches Postgres, Redis and the models through
`animallya-sparkN.local`. That resolves on the Windows and Ubuntu *hosts* and
does not resolve inside a container - Docker's embedded resolver forwards to
the host's upstream nameservers, and the mDNS responder is not one of them.

The failure is worse than a clean `NXDOMAIN`:

```
$ getent hosts animallya-spark1.local     # inside the container
fe80::68b8:42ff:fef0:8a6f   animallya-spark1.local
...eight link-local IPv6 addresses...
$ getent hosts animallya-spark2.local
(nothing)
```

`fe80::/10` is link-local and unroutable without a scope id, so connections
hang or die with "Temporary failure in name resolution" - while `/health` keeps
answering `200 OK`, because it touches no dependency. The stack looked healthy
and could not have served a single real request.

Fixed with one `x-spark-hosts` anchor in `docker-compose.yml` pinning both
Sparks to their LAN addresses, shared by all six services that need it. It also
absorbed the four separate `host.docker.internal` entries that were previously
copied per service.

**The lesson worth keeping: a health endpoint that touches no dependency will
report a completely broken stack as healthy.** Verify a migration by exercising
each dependency from inside the container, not by curling `/health`.

### `vllm-main` is gone

The desktop-RTX generation service was dead code once the Sparks took over -
80 lines of service definition plus three stale comments and a startup-script
line that brought up a service nothing depended on.

### The models now start themselves

The application containers carry `restart: unless-stopped`, so Docker brings
them back after a power cycle. The *models* did not: `~/ds4-tp2.sh` and
`~/vlm-serve.sh` were only ever run by hand, so a reboot produced a fully
running stack with nothing behind it.

Three systemd units fix that, all `enabled`:

| host | unit | runs |
|---|---|---|
| spark1 | `ds4-head.service` | `ds4-tp2.sh head` - serves :8000 |
| spark2 | `ds4-worker.service` | `ds4-tp2.sh worker` - rank 1 |
| spark2 | `anios-vlm.service` | `vlm-serve.sh` - vision on :8001 |

The launch scripts run `docker` in the foreground with `--rm`, so systemd
supervises the container directly and `ExecStop` names the container.

Cross-host ordering cannot be expressed in systemd, and does not need to be:
the head blocks until rank 1 joins, and `VLLM_ENGINE_READY_TIMEOUT_S=3600`
gives spark2 room to finish booting. `TimeoutStartSec` is 3900 on both so
systemd does not kill a startup that is merely slow - loading ~167 GB across
two boxes is not fast.

The application containers will come up before the model is ready and log
connection failures for a few minutes. That is harmless: the backend opens a
connection per request, so it recovers on its own once :8000 answers.

**A powered-off Spark still needs a physical button press** - no BMC, no
Wake-on-LAN. Auto-start covers reboots, not power-on.

## The first real power cycle, 2026-08-23

Everything auto-started: `ds4-head`, `ds4-worker`, `anios-vlm` and all nine
containers came up without a keystroke. Then the head died, and the reason was
not the one the ordering comments predicted.

```
ValueError: To serve at least one request with the model's max seq len
(1048576), 7.54 GiB KV cache is needed, which is larger than the available
KV cache memory (5.09 GiB).
```

**Moving the application stack onto spark1 changed the model's boot budget.**
`--gpu-memory-utilization` is a fraction of the whole pool and the profiler
sizes KV from what it observes *free*, so the model that had 10.68 GiB of KV on
an empty box found 5.09 GiB once the containers and the embedding server were
starting alongside it. `--max-model-len` is 524288 now; it needs ~3.77 GiB and
boots either way. Measured context use is median 4.4k / p90 11.7k / max 16.1k
tokens, so the ceiling is still ~30x the worst real turn.

The second failure was worse, because nothing detected it. systemd restarted the
head 30 seconds later, but the worker on spark2 was still attached to the dead
head's TCPStore:

```
[rank1] Failed to check the "should dump" flag on TCPStore,
(maybe TCPStore server has shut down too early), with error: Broken pipe
```

It logged that and kept running. systemd saw `ActiveState=active
SubState=running` and `NRestarts=0`, so `Restart=on-failure` never fired, and
the new head waited at `parallel_state` init for a rank that was never going to
arrive. Recovery was a manual restart in the documented order - worker, then
head - and six minutes of loading.

`Restart=always` is set on all three units now. It would not have caught this
one: nothing in systemd catches a process that stops working without stopping.
The recognisable symptom is recorded in `deploy/spark/README.md` instead - **a
head sitting at `parallel_state` init for more than a few minutes means the
worker is wedged, not slow.**

Total user-visible outage: about twenty minutes, during which iMessage turns
failed. The application containers came up before Postgres was accepting
connections too (`Connect call failed ('172.16.8.3', 5432)`) and recovered on
their own once it was.

### The serving configuration was not in the repository

`ds4-tp2.sh`, `vlm-serve.sh` and the three unit files existed only on the
Sparks' disks - unreviewed, unversioned, and gone with the box if either drive
failed. They are in `deploy/spark/` now, with the deploy and restart order.
