#!/bin/bash
# A1 book gate (stance-table-gate.md), replace:sentiment for the two
# replacement candidates. Waits for 2026-10-02T00:45Z (20:45 ET). nice 19.
set -u
cd ~/scratch/wt-ts || exit 1
export PYTHONPATH=$PWD CUDA_VISIBLE_DEVICES= SECRET_KEY=ts-research-only
PY=~/research-venv/bin/python
ROOT=~/deploy/anios/data/market
OUT=docs/research/scorecards/text-surprise
LOG=~/scratch/ts_logs/gate.txt
ARMS="A1-1_change_plus_level A1-1_change_gated"
fp() { find "$ROOT" -maxdepth 2 -type f -newermt "$1" 2>/dev/null | wc -l; }
echo "gate queued $(date -u +%FT%TZ)" > "$LOG"
while [ "$(date -u +%s)" -lt "$(date -u -d 2026-10-02T00:45:00Z +%s)" ]; do sleep 30; done
START=$(date -u +%FT%TZ)
echo "start $START rev $(git rev-parse HEAD) dirty $(git status --porcelain --untracked-files=no | wc -l) store-newest $(find "$ROOT" -maxdepth 2 -type f -printf '%T@ %p\n' 2>/dev/null | sort -n | tail -1)" >> "$LOG"
sc() { nice -n 19 $PY -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 "$@"; }
for a in $ARMS; do
  sc --stance-table "$OUT/stances/$a.parquet" --null-test > "$OUT/gate_null_$a.txt" 2>&1
  rc=$?; echo "null $a exit $rc $(date -u +%FT%TZ): $(grep -E 'verdict|rows_used' "$OUT/gate_null_$a.txt" | tr '\n' ' ')" >> "$LOG"
  [ $rc -eq 0 ] || { echo "ABORT: null test failed for $a" >> "$LOG"; exit 1; }
done
sc --rank-ic --output "$OUT/pit_scorecard_control.json" > "$OUT/gate_control.txt" 2>&1
echo "control exit $? $(date -u +%FT%TZ)" >> "$LOG"
for a in $ARMS; do
  sc --rank-ic --stance-table "$OUT/stances/$a.parquet" --stance-mode replace:sentiment --output "$OUT/pit_scorecard_$a.json" > "$OUT/gate_$a.txt" 2>&1
  echo "$a exit $? $(date -u +%FT%TZ)" >> "$LOG"
done
echo "store files changed during the run: $(fp "$START")" >> "$LOG"
PYTHONPATH=~/scratch/wt-vt nice -n 19 $PY ~/scratch/ts_gate_pair.py "$OUT/pit_scorecard_control.json" $(for a in $ARMS; do echo "$OUT/pit_scorecard_$a.json"; done) > "$OUT/gate_verdict.txt" 2>&1
echo "pair exit $? $(date -u +%FT%TZ)" >> "$LOG"
cat "$OUT/gate_verdict.txt" >> "$LOG"
echo "done $(date -u +%FT%TZ)" >> "$LOG"
