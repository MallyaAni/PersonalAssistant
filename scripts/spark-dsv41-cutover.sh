#!/usr/bin/env bash
# Replace DeepSeek-V4-Flash-0731 (ds4-*) with DeepSeek-V4.1-Flash-1017 EXL3 (ds41-*)
# on the two Sparks, prove it, and roll back on its own if it does not hold.
#
#   bash scripts/spark-dsv41-cutover.sh            # refuses if an opencode agent is running
#   FORCE=1 bash scripts/spark-dsv41-cutover.sh
#   ROLLBACK=1 bash scripts/spark-dsv41-cutover.sh # just put ds4 + the VLM back
#
# Needs: key ssh to both Sparks; `sudo bash ~/install-ds41.sh` done on both (units +
# the narrow sudoers rule); the model folder complete on spark1 (download_model.sh);
# the image pulled on spark1. Log: test-results/dsv41-cutover-<timestamp>.log
#
# Order of operations and why:
#   1. baseline the old server, so "faster" is measured, not assumed
#   2. stop ds4-head, ds4-worker, anios-vlm (disable, so a reboot does not bring them
#      back beside the new units; the ds41 units declare Conflicts= as a second guard)
#   3. with the GPU pool empty: pull the image on spark2, rsync the model folder to
#      spark2 over the fabric, build the JIT kernels on both - HeNryous: building
#      them next to loaded weights has OOM'd a node and left a stale lock
#   4. enable --now ds41-worker, then ds41-head (units drop the page cache first)
#   5. smoke: both served names listed, decode probe x2, DSpark counters, a vision
#      request, a tool call; then the memory probe: a ~200K-token prefill while
#      sampling MemAvailable on both nodes - the number this deployment lives or
#      dies by, since spark1 carries the app stack and the server's watchdog
#      stops it at ~1.5 GiB free
#   6. anything fails -> rollback(): ds41 down, anios-vlm, ds4-worker, ds4-head up
# The app-side change (vision role -> this model, compose + .env) is NOT here; it
# goes through scripts/deploy.sh afterwards, gated, like any app change.
set -uo pipefail
S1="${S1:-animallya96@172.16.8.3}"; S2="${S2:-animallya96@172.16.8.5}"
MODEL_DIR="/home/animallya96/models/DeepSeek-V4.1-Flash-1017-EXL3-2.75bpw-DGX-Spark"
IMAGE="ghcr.io/henryous/deepseek-v41-1017-dgx-spark:v4i"
BOOT_TIMEOUT_S="${BOOT_TIMEOUT_S:-1500}"
SSH=(-o BatchMode=yes -o ConnectTimeout=10)
mkdir -p test-results
LOG="test-results/dsv41-cutover-$(date +%Y%m%dT%H%M%S).log"
exec > >(tee -a "$LOG") 2>&1
say() { printf '\n=== %s  [%s]\n' "$*" "$(date +%H:%M:%S)"; }
die() { say "STOP: $*"; say "RESULT: ABORTED (old server untouched)"; exit 1; }
s1() { ssh "${SSH[@]}" "$S1" "$@"; }
s2() { ssh "${SSH[@]}" "$S2" "$@"; }

PROBE='
import json, sys, time, urllib.request
model = sys.argv[1]
body = {"model": model, "stream": True, "max_tokens": 800, "temperature": 0,
        "chat_template_kwargs": {"thinking": False},
        "messages": [{"role": "user", "content": "Write a Python LRU cache class with get, put, full type hints and docstrings."}]}
req = urllib.request.Request("http://localhost:8000/v1/chat/completions", json.dumps(body).encode(), {"Content-Type": "application/json"})
t0 = time.time(); first = None; n = 0; text = []
for line in urllib.request.urlopen(req, timeout=900):
    if line.startswith(b"data: {"):
        ch = json.loads(line[6:])["choices"]
        if ch and (ch[0]["delta"].get("content") or ch[0]["delta"].get("reasoning")):
            first = first or time.time(); n += 1; text.append(ch[0]["delta"].get("content") or "")
dt = time.time() - first
print(f"PROBE model={model} ttft={first-t0:.2f}s chunks={n} rate={n/dt:.1f}/s sane={\"class\" in \"\".join(text)}")
'
probe()   { s1 "python3 -c '$PROBE' ${1:-deepseek-v4-flash}"; }
metrics() { s1 "curl -s localhost:8000/metrics | grep -E '^vllm:spec_decode_num_(accepted_tokens|drafts|draft_tokens)_total' || echo 'spec_decode metrics: NONE'"; }
mem()     { echo "spark1 $(s1 "awk '/MemAvailable/{printf \"avail %.1f GiB\", \$2/1048576}' /proc/meminfo")   spark2 $(s2 "awk '/MemAvailable/{printf \"avail %.1f GiB\", \$2/1048576}' /proc/meminfo")"; }
up()      { s1 'curl -sf -m 5 localhost:8000/v1/models >/dev/null'; }

wait_up() {   # $1 = container name prefix (ds4|ds41)
  local t=0 c=$1
  while (( t < BOOT_TIMEOUT_S )); do
    up && { say "server up after ${t}s"; return 0; }
    for pair in "s1 $c-head" "s2 $c-worker"; do
      set -- $pair
      if [[ "$($1 "docker inspect -f '{{.State.Running}}' $2 2>/dev/null")" != true ]]; then
        sleep 45   # systemd restarts after 30 s; a container that is still gone then has really failed
        [[ "$($1 "docker inspect -f '{{.State.Running}}' $2 2>/dev/null")" == true ]] && continue
        say "$2 is not running; last log lines:"; $1 "journalctl -u $2 -n 40 --no-pager 2>/dev/null | tail -40"; return 1
      fi
    done
    sleep 30; t=$((t+30)); echo "  waiting... ${t}s  ($(mem))"
  done
  say "timed out after ${BOOT_TIMEOUT_S}s"; return 1
}

rollback() {
  say "ROLLING BACK to ds4 + anios-vlm"
  s1 'sudo -n systemctl disable --now ds41-head' ; s2 'sudo -n systemctl disable --now ds41-worker'
  s2 'sudo -n systemctl enable --now ds4-worker'; sleep 20; s1 'sudo -n systemctl enable --now ds4-head'
  s2 'sudo -n systemctl enable --now anios-vlm'
  if wait_up ds4 && probe; then say "RESULT: ROLLED BACK, V4-Flash-0731 serving again"; else say "RESULT: ROLLBACK DID NOT COME UP - needs a person (worker then head, deploy/spark/README.md)"; fi
  exit 2
}
[[ "${ROLLBACK:-0}" == 1 ]] && rollback

say "0. preflight"
s1 true || die "cannot ssh to $S1"; s2 true || die "cannot ssh to $S2"
for h in s1 s2; do $h 'sudo -n /usr/bin/systemctl daemon-reload' 2>/dev/null || die "$h: passwordless sudo for the model units is missing - run: sudo bash ~/install-ds41.sh on both Sparks"; done
for h in s1 s2; do $h 'systemctl cat ds41-head.service ds41-worker.service >/dev/null 2>&1' || die "$h: ds41 units not installed (install-ds41.sh)"; done
for h in s1 s2; do $h "test -x ~/ds41-tp2.sh && test -f ~/ds41-serve.sh && test -f ~/.cache/dsv41-serve/markov_top_tokens.json" || die "$h: ds41-tp2.sh / ds41-serve.sh / markov cache missing in home"; done
[[ "$(s1 'md5sum < ~/ds41-tp2.sh; md5sum < ~/ds41-serve.sh')" == "$(s2 'md5sum < ~/ds41-tp2.sh; md5sum < ~/ds41-serve.sh')" ]] || die "ds41 scripts differ between the Sparks"
busy=$(s1 "pgrep -ax opencode | grep -v ' web '" || true)
[[ -z "$busy" || "${FORCE:-0}" == 1 ]] || { echo "$busy"; die "an opencode agent is running on spark1; FORCE=1 to proceed"; }
s1 "docker image inspect $IMAGE >/dev/null 2>&1" || die "image not pulled on spark1"
n=$(s1 "ls $MODEL_DIR | wc -l"); sz=$(s1 "du -sb $MODEL_DIR | cut -f1")
echo "model folder on spark1: $n files, $((sz/1000000000)) GB"
(( n >= 192 && sz > 395000000000 )) || die "model folder incomplete on spark1 (expect >=192 files, ~402 GB)"
s1 "for f in model-00047-of-00048.safetensors:101535150936 model-00048-of-00048.safetensors:101537926640; do n=\${f%%:*}; w=\${f##*:}; g=\$(stat -c %s $MODEL_DIR/\$n); [ \"\$g\" = \"\$w\" ] && echo \"size ok \$n\" || { echo \"SIZE MISMATCH \$n \$g\"; exit 1; }; done" || die "Engram shard size mismatch"
s1 "test -f $MODEL_DIR/.engram_sha256_ok" || die "Engram shards not sha256-verified yet (prep step writes $MODEL_DIR/.engram_sha256_ok)"
echo "before: $(mem)"; s1 'free -g | sed -n 2,3p'; s2 'free -g | sed -n 2,3p'

say "1. baseline on the old server"
up || die "old server is not answering; nothing to baseline"
probe; probe; metrics

say "2. stop ds4-head, ds4-worker, anios-vlm (disabled, not just stopped)"
s1 'sudo -n systemctl disable --now ds4-head' || rollback
s2 'sudo -n systemctl disable --now ds4-worker' || rollback
s2 'sudo -n systemctl disable --now anios-vlm' || rollback
sleep 15; echo "pool empty: $(mem)"

say "3. spark2: image + model; both: JIT kernels"
s2 "docker image inspect $IMAGE >/dev/null 2>&1 || docker pull $IMAGE" || rollback
s2 "mkdir -p $MODEL_DIR ~/.cache/dsv41-serve"
s1 "rsync -a --info=progress2 --exclude .cache -e 'ssh -o BatchMode=yes' $MODEL_DIR/ 192.168.100.2:$MODEL_DIR/" || rollback
[[ "$(s1 "du -sb $MODEL_DIR | cut -f1")" == "$(s2 "du -sb $MODEL_DIR | cut -f1")" ]] || rollback
s1 "cp ~/.cache/dsv41-serve/markov_top_tokens.json /tmp/m.json" && s1 "scp -q -o BatchMode=yes /tmp/m.json 192.168.100.2:.cache/dsv41-serve/markov_top_tokens.json" || rollback
JIT="docker run --rm --gpus all -v \$HOME/.cache/dsv41-serve:/root/.cache -e TORCH_EXTENSIONS_DIR=/root/.cache/torch_extensions -e MAX_JOBS=4 --entrypoint python3 $IMAGE -c 'from vllm_exl3_moe import tf_experts as t; t._ext()'"
s1 "$JIT" || rollback; s2 "$JIT" || rollback

say "4. start ds41-worker, then ds41-head"
s2 'sudo -n systemctl enable --now ds41-worker' || rollback
sleep 20
s1 'sudo -n systemctl enable --now ds41-head' || rollback
wait_up ds41 || rollback

say "5. smoke"
s1 'curl -s localhost:8000/v1/models' | grep -o '"id":"[^"]*"' | tr '\n' ' '; echo
s1 'curl -s localhost:8000/v1/models' | grep -q '"deepseek-v4.1-flash-1017"' || rollback
s1 'curl -s localhost:8000/v1/models' | grep -q '"deepseek-v4-flash"' || rollback
probe deepseek-v4.1-flash-1017 || rollback; probe deepseek-v4.1-flash-1017 || rollback; metrics
echo "after boot: $(mem)"
s1 "python3 - <<'PY'
import json, base64, zlib, struct, urllib.request
def png(w,h,rgb):
    raw=b''.join(b'\x00'+bytes(rgb)*w for _ in range(h))
    def chunk(t,d): return struct.pack('>I',len(d))+t+d+struct.pack('>I',zlib.crc32(t+d)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')
img=base64.b64encode(png(64,64,(255,0,0))).decode()
body={'model':'deepseek-v4.1-flash-1017','max_tokens':40,'temperature':0,'chat_template_kwargs':{'thinking':False},
 'messages':[{'role':'user','content':[{'type':'text','text':'What colour is this image? One word.'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+img}}]}]}
r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/v1/chat/completions',json.dumps(body).encode(),{'Content-Type':'application/json'}),timeout=300)
a=json.loads(r.read())['choices'][0]['message']['content']; print('VISION:',a.strip()[:80]); assert 'red' in a.lower()
body={'model':'deepseek-v4.1-flash-1017','max_tokens':200,'temperature':0,'chat_template_kwargs':{'thinking':False},
 'tools':[{'type':'function','function':{'name':'get_weather','description':'Weather for a city','parameters':{'type':'object','properties':{'city':{'type':'string'}},'required':['city']}}}],
 'messages':[{'role':'user','content':'Use the tool to get the weather in Boston.'}]}
r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/v1/chat/completions',json.dumps(body).encode(),{'Content-Type':'application/json'}),timeout=300)
m=json.loads(r.read())['choices'][0]['message']; tc=m.get('tool_calls') or []; print('TOOLCALL:',[ (t['function']['name'],t['function']['arguments']) for t in tc]); assert tc and tc[0]['function']['name']=='get_weather' and 'Boston' in tc[0]['function']['arguments']
PY" || rollback

say "6. memory probe: ~200K-token prefill, MemAvailable sampled on both nodes"
s1 'rm -f /tmp/memmin1'; s2 'rm -f /tmp/memmin2'
s1 "nohup bash -c 'm=999999999; for i in \$(seq 1 150); do a=\$(awk \"/MemAvailable/{print \\\$2}\" /proc/meminfo); [ \$a -lt \$m ] && m=\$a; echo \$m > /tmp/memmin1; sleep 2; done' >/dev/null 2>&1 &"
s2 "nohup bash -c 'm=999999999; for i in \$(seq 1 150); do a=\$(awk \"/MemAvailable/{print \\\$2}\" /proc/meminfo); [ \$a -lt \$m ] && m=\$a; echo \$m > /tmp/memmin2; sleep 2; done' >/dev/null 2>&1 &"
s1 "python3 - <<'PY'
import json, time, urllib.request
doc=''.join(f'note {i:06d}: the retry policy for subsystem {i} is exponential with base {i%9} s and cap {i%60} min.\n' for i in range(8000))
body={'model':'deepseek-v4.1-flash-1017','max_tokens':32,'temperature':0,'chat_template_kwargs':{'thinking':False},
 'messages':[{'role':'user','content':doc+'\nWhat is the cap for subsystem 007999? Answer with the number only.'}]}
t0=time.time(); r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/v1/chat/completions',json.dumps(body).encode(),{'Content-Type':'application/json'}),timeout=1800)
j=json.loads(r.read()); print('LONGPREFILL prompt_tokens=',j['usage']['prompt_tokens'],'wall=%.0fs'%(time.time()-t0),'answer=',j['choices'][0]['message']['content'].strip()[:40])
PY" || rollback
sleep 10
m1=$(s1 'cat /tmp/memmin1'); m2=$(s2 'cat /tmp/memmin2')
echo "MEMMIN during long prefill: spark1 $((m1/1024)) MiB  spark2 $((m2/1024)) MiB  (watchdog at ~1536 MiB; want >= 3072)"
(( m1 > 3072*1024 && m2 > 3072*1024 )) || { say "memory margin too thin under a long prefill"; rollback; }

say "7. short soak: 2 concurrent probes x 3 rounds"
for r in 1 2 3; do pids=(); for i in 1 2; do probe deepseek-v4.1-flash-1017 & pids+=($!); done; wait "${pids[@]}"; up || { say "server died under concurrency"; rollback; }; done
metrics; echo "end: $(mem)"
say "RESULT: V4.1-FLASH-1017 SERVING ON BOTH SPARKS (log: $LOG). Next: app vision repoint via scripts/deploy.sh, then opencode."
