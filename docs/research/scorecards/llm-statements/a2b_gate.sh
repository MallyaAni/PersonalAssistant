#!/bin/bash
# A2b book gate (stance-table-gate.md), sixth mode, on research/llm-statements-a2b
# with desk/stance-table merged. CPU, nice 19, store read-only. Never runs a
# step inside 19:20-19:55 ET (the live nightly): it waits until 19:55.
# Aborts if the null test fails or no table row lands on the panel.
set -u
cd ~/scratch/wt-a2b || exit 1
export PYTHONPATH=$PWD CUDA_VISIBLE_DEVICES= SECRET_KEY=a2b-research-only
PY=~/research-venv/bin/python
ROOT=~/deploy/anios/data/market
OUT=docs/research/scorecards/llm-statements
TABLE=$OUT/stances/A2b.parquet
LOG=$OUT/gate_run.txt
et() { TZ=America/New_York date +%H%M | sed "s/^0*//"; }
quiet() { while n=$(et); [ "${n:-0}" -ge 1920 ] && [ "${n:-0}" -lt 1955 ]; do echo "$(date -u +%FT%TZ) waiting out the nightly window" >> "$LOG"; sleep 60; done; }
fp() { find "$ROOT" -maxdepth 2 -type f -newermt "$1" 2>/dev/null | wc -l; }
sc() { nice -n 19 $PY -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 "$@"; }
START=$(date -u +%FT%TZ)
echo "start $START rev $(git rev-parse HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) table sha256 $(sha256sum "$TABLE" | cut -c1-64)" > "$LOG"
echo "deploy/nightly running at start: $(pgrep -f '[s]cripts/deploy.sh|[b]ackend.cli.market_daily' | wc -l)" >> "$LOG"
quiet
sc --stance-table "$TABLE" --null-test > "$OUT/gate_null_A2b.txt" 2>&1
rc=$?
rows=$(grep -E "rows, [0-9]+ on the panel" "$OUT/gate_null_A2b.txt")
used=$(echo "$rows" | sed -E 's/.* ([0-9]+) on the panel.*/\1/')
echo "null exit $rc $(date -u +%FT%TZ): $rows | $(grep -E 'verdict' "$OUT/gate_null_A2b.txt" | tr '\n' ' ')" >> "$LOG"
[ $rc -eq 0 ] || { echo "ABORT: null test failed" >> "$LOG"; exit 1; }
[ "${used:-0}" -gt 0 ] || { echo "ABORT: no table row on the panel (rows_used 0)" >> "$LOG"; exit 1; }
quiet
sc --rank-ic --output "$OUT/pit_scorecard_control.json" > "$OUT/gate_control.txt" 2>&1
echo "control exit $? $(date -u +%FT%TZ)" >> "$LOG"
quiet
sc --rank-ic --stance-table "$TABLE" --stance-mode sixth --output "$OUT/pit_scorecard_A2b.json" > "$OUT/gate_A2b.txt" 2>&1
echo "A2b exit $? $(date -u +%FT%TZ)" >> "$LOG"
echo "store files changed during the run: $(fp "$START")" >> "$LOG"
TS=~/scratch/wt-ts/docs/research/scorecards/text-surprise
PYTHONPATH=~/scratch/wt-vt nice -n 19 $PY $OUT/a2b_gate_pair.py "$OUT/pit_scorecard_control.json" "$OUT/pit_scorecard_A2b.json" \
  "$TS/pit_scorecard_control.json" "$TS/pit_scorecard_A1-1_change_plus_level.json" "$TS/pit_scorecard_A1-1_change_gated.json" > "$OUT/gate_verdict.txt" 2>&1
echo "pair exit $? $(date -u +%FT%TZ)" >> "$LOG"
cat "$OUT/gate_verdict.txt" >> "$LOG"
echo "done $(date -u +%FT%TZ)" >> "$LOG"
