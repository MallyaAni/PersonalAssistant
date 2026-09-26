#!/usr/bin/env bash
# Roll out deploy/spark/ds4-tp2.sh (DSpark re-enable, 2026-09-26) to both
# Sparks, prove it works, and roll back automatically if it does not.
#
# Run from the repo root on a machine that can ssh to both Sparks
# (the desktop's Git Bash or WSL):
#     bash scripts/spark-dspark-rollout.sh            # refuses if opencode is running
#     FORCE=1 bash scripts/spark-dspark-rollout.sh    # restart anyway
#
# Everything is logged to test-results/dspark-rollout-<timestamp>.log so the
# result can be read back without anyone copying terminal output.
# Deploy order and rollback follow deploy/spark/README.md: worker, then head.
set -uo pipefail

S1="${S1:-animallya96@animallya-spark1.local}"
S2="${S2:-animallya96@animallya-spark2.local}"
IMAGE="ghcr.io/anemll/dspark-vllm-gx10:0.1.1"
BOOT_TIMEOUT_S="${BOOT_TIMEOUT_S:-1500}"
mkdir -p test-results

# Plain ssh with key login (ssh-copy-id). Connection sharing was tried and
# removed: Git Bash's ssh on Windows cannot create the control socket.
SSH_OPTS=(-o ConnectTimeout=10)
ssh() { command ssh "${SSH_OPTS[@]}" "$@"; }
scp() { command scp "${SSH_OPTS[@]}" "$@"; }
LOG="test-results/dspark-rollout-$(date +%Y%m%dT%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1

say()  { printf '\n=== %s  [%s]\n' "$*" "$(date +%H:%M:%S)"; }
die()  { say "STOP: $*"; say "RESULT: ABORTED (nothing deployed)"; exit 1; }

# Streams one code prompt and prints ttft and decode rate. Runs on spark1.
PROBE='
import json, time, urllib.request
body = {"model": "deepseek-v4-flash", "stream": True, "max_tokens": 800, "temperature": 0,
        "chat_template_kwargs": {"thinking": False},
        "messages": [{"role": "user", "content": "Write a Python LRU cache class with get, put, full type hints and docstrings."}]}
req = urllib.request.Request("http://localhost:8000/v1/chat/completions", json.dumps(body).encode(),
                             {"Content-Type": "application/json"})
t0 = time.time(); first = None; n = 0
for line in urllib.request.urlopen(req, timeout=900):
    if line.startswith(b"data: {"):
        ch = json.loads(line[6:])["choices"]
        if ch and (ch[0]["delta"].get("content") or ch[0]["delta"].get("reasoning")):
            first = first or time.time(); n += 1
dt = time.time() - first
print(f"PROBE ttft={first-t0:.2f}s chunks={n} rate={n/dt:.1f}/s")
'
probe()   { ssh "$S1" "python3 -c '$PROBE'"; }
metrics() { ssh "$S1" "curl -s localhost:8000/metrics | grep -E '^vllm:spec_decode_num_(accepted_tokens|drafts|draft_tokens)_total' || echo 'spec_decode metrics: NONE'"; }

restart_pair() {
  ssh -t "$S2" 'sudo systemctl restart ds4-worker' || return 1
  sleep 20
  ssh -t "$S1" 'sudo systemctl restart ds4-head' || return 1
}

wait_up() {
  local t=0
  while (( t < BOOT_TIMEOUT_S )); do
    if ssh "$S1" 'curl -sf -m 5 localhost:8000/v1/models >/dev/null'; then say "server up after ${t}s"; return 0; fi
    if ssh "$S1" "journalctl -u ds4-head --since '-40s' --no-pager 2>/dev/null | grep -qE 'KV cache is needed|larger than the available KV|unrecognized arguments|error: argument'"; then
      say "boot failure in head journal:"
      ssh "$S1" "journalctl -u ds4-head --since '-5min' --no-pager | grep -iE 'error|KV cache|unrecognized|Traceback' | tail -20"
      return 1
    fi
    sleep 30; t=$((t+30)); echo "  waiting... ${t}s"
  done
  say "timed out after ${BOOT_TIMEOUT_S}s"; ssh "$S1" "journalctl -u ds4-head -n 40 --no-pager"
  return 1
}

rollback() {
  say "ROLLING BACK to ~/ds4-tp2.sh.pre-dspark"
  ssh "$S1" 'cp ~/ds4-tp2.sh.pre-dspark ~/ds4-tp2.sh'
  ssh "$S2" 'cp ~/ds4-tp2.sh.pre-dspark ~/ds4-tp2.sh'
  restart_pair && wait_up && probe && say "RESULT: ROLLED BACK, old config serving" \
    || say "RESULT: ROLLBACK DID NOT COME UP - needs a person (worker then head, see deploy/spark/README.md)"
  exit 2
}

say "0. preflight"
bash -n deploy/spark/ds4-tp2.sh || die "local ds4-tp2.sh has a syntax error"
for h in "$S1" "$S2"; do
  command ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" true 2>/dev/null \
    || echo "NOTE: $h has no key login; each step will ask for a password (fix: ssh-copy-id $h)"
done
ssh "$S1" true || die "cannot ssh to $S1"
ssh "$S2" true || die "cannot ssh to $S2"
# Only an agent mid-task is harmed by a restart. "opencode web" is the idle UI
# server: it holds no model request and reconnects on its own.
# pgrep -x matches the process NAME, so the grep in this pipeline (whose command
# line also contains "opencode") can never match itself.
busy=$(ssh "$S1" "pgrep -ax opencode | grep -v ' web '" || true)
if [[ -n "$busy" && "${FORCE:-0}" != 1 ]]; then echo "$busy"; die "opencode is running on spark1; restart would kill it. Re-run with FORCE=1 to proceed."; fi
# Check the image's own vLLM source for each new setting, without starting vLLM:
# "docker run IMAGE --help=all" returned nothing on 2026-09-26 (vLLM needs a GPU
# just to print help), which read as 0/5 though the recipe runs these flags.
flagcheck=$(ssh "$S1" bash -s <<'REMOTE' 2>&1
docker run --rm --entrypoint bash ghcr.io/anemll/dspark-vllm-gx10:0.1.1 -c '
d=$(python3 -c "import importlib.util as u, os; print(os.path.dirname(u.find_spec(\"vllm\").origin))") || { echo "NO_VLLM_PACKAGE"; exit 3; }
echo "vllm at $d"
for f in speculative_config enable_chunked_prefill long_prefill_token_threshold async_scheduling max_cudagraph_capture_size; do
  if grep -rqs -- "$f" "$d/engine/arg_utils.py"; then echo "OK $f"; else echo "MISSING $f"; fi
done
if grep -rqsi -- "dspark" "$d/config" "$d/config.py" "$d/v1/spec_decode"; then echo "OK dspark_method"; else echo "MISSING dspark_method"; fi
'
REMOTE
)
echo "$flagcheck"
[[ $(grep -c '^OK ' <<<"$flagcheck") == 6 ]] || die "image check did not confirm all 5 flags + dspark (output above)"
ssh "$S2" 'free -g; nvidia-smi --query-gpu=memory.used,memory.total --format=csv'

say "1. baseline (current config)"
probe; probe; metrics

say "2. deploy"
ssh "$S1" 'cp ~/ds4-tp2.sh ~/ds4-tp2.sh.pre-dspark' || die "backup failed on spark1"
ssh "$S2" 'cp ~/ds4-tp2.sh ~/ds4-tp2.sh.pre-dspark' || die "backup failed on spark2"
scp -q deploy/spark/ds4-tp2.sh "$S1:ds4-tp2.sh" && scp -q deploy/spark/ds4-tp2.sh "$S2:ds4-tp2.sh" || rollback
h1=$(ssh "$S1" 'bash -n ~/ds4-tp2.sh && md5sum < ~/ds4-tp2.sh'); h2=$(ssh "$S2" 'bash -n ~/ds4-tp2.sh && md5sum < ~/ds4-tp2.sh')
echo "md5 spark1=$h1 spark2=$h2"
[[ -n "$h1" && "$h1" == "$h2" ]] || rollback

say "3. restart worker then head"
restart_pair || rollback
wait_up || rollback

say "4. verify"
probe || rollback
probe || rollback
metrics
ssh "$S1" "journalctl -u ds4-head --since '-15min' --no-pager | grep -iE 'speculative|dspark|max_seq_len|KV cache|cudagraph' | tail -15"

say "5. short soak: 6 concurrent probes x 3 rounds"
for r in 1 2 3; do
  pids=(); for i in 1 2 3 4 5 6; do probe & pids+=($!); done
  wait "${pids[@]}"   # a bare wait would also wait on the log's tee and never return
  ssh "$S1" 'curl -sf -m 5 localhost:8000/v1/models >/dev/null' || { say "server died under concurrency"; rollback; }
done
metrics
say "RESULT: DEPLOYED AND SERVING WITH NEW CONFIG (log: $LOG)"
