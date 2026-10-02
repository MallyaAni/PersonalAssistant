# The T-S1 book gate for A2b (sixth analyst), paired against a control run on
# the same tree and store. Reuses the paired-difference and offset helpers of
# research/vol-target (backend.market.vol_target, e6ff1ee2; run with
# PYTHONPATH=~/scratch/wt-vt), as ts_gate_pair.py did for A1. Read-only.
#
# Usage: a2b_gate_pair.py CONTROL A2B [A1_CONTROL A1_CAND ...]
#
# Gate (llm-statements plan, stance-table-gate.md): +2.00 bp of equity a
# session at 25 bp over the control on 2016-2023 at NW t >= 2 (lag 20); the
# 2024-2026 mean not negative; CAGR above the control at >= 15 of 20 offsets
# (2016-2023); deflated Sharpe at 490 cumulative trials >= 0.95.
#
# Trial variance, fixed here before any A2b number: with one A2b candidate
# there is no across-candidate variance of its own, so the variance is the
# sample variance (ddof 1) of the 2016-2023 paired-difference Sharpes of every
# stance-table book-gate candidate run to date, each against its own control:
# A1-1 change_plus_level and A1-1 change_gated (2026-10-02 00:45Z gate, wt-ts
# at e1a8286e) and A2b. Reported beside it, deciding nothing: the DSR at the
# A1-only variance and the PSR against zero (the DSR with no trial penalty);
# if the PSR is below 0.95 no trial variance can make the DSR pass.
import json
import math
import sys
from pathlib import Path

import numpy as np

from backend.market import candidate_stats, vol_target as vt

TRIALS = 490
load = lambda p: json.loads(Path(p).read_text())  # noqa: E731
control, cand = load(sys.argv[1]), load(sys.argv[2])
a1 = {}
if len(sys.argv) > 3:
    a1_control = load(sys.argv[3])
    a1 = {Path(p).stem: vt.paired(load(p), a1_control, vt.DECIDING) for p in sys.argv[4:]}
pairs = {w: vt.paired(cand, control, w) for w in vt.WINDOWS}
d, r = pairs[vt.DECIDING], pairs[vt.RECENT]
a1_sh = [p["sharpe"] for p in a1.values() if math.isfinite(p["sharpe"])]
pool = a1_sh + ([d["sharpe"]] if math.isfinite(d["sharpe"]) else [])
var = float(np.var(pool, ddof=1)) if len(pool) >= 2 else math.nan
var_a1 = float(np.var(a1_sh, ddof=1)) if len(a1_sh) >= 2 else math.nan
dsr = lambda v: candidate_stats.deflated_sharpe(d["sharpe"], d["length"], d["skew"], d["kurtosis"], TRIALS, v) if math.isfinite(v) and v > 0 else math.nan  # noqa: E731
psr0 = candidate_stats.probabilistic_sharpe(d["sharpe"], d["length"], d["skew"], d["kurtosis"], 0.0)
above, n = vt.offsets_above(cand, control, vt.DECIDING)
above_r, n_r = vt.offsets_above(cand, control, vt.RECENT)
print(f"T-S1 gate, A2b (sixth analyst) against {control.get('arm')} as of {control.get('asof')}, 25 bp, trials {TRIALS}, "
      f"trial variance {var:.3g} (pooled over {len(pool)} stance-gate candidates)")
for k, p in a1.items():
    print(f"  pool: {k} 2016-2023 paired Sharpe {p['sharpe']:+.4f} (mean {p['mean_daily_bp']:+.2f} bp, t {p['hac_t']:+.2f})")
print(f"  pool: A2b 2016-2023 paired Sharpe {d['sharpe']:+.4f}")
D = dsr(var)
print(f"A2b ({cand.get('arm')}): paired 2016-2023 {d['mean_daily_bp']:+.2f} bp/session (t {d['hac_t']:+.2f}, {d['sessions']} sessions); "
      f"2024-2026 {r['mean_daily_bp']:+.2f} (t {r['hac_t']:+.2f}, {r['sessions']}); above the control at {above} of {n} (2024-2026: {above_r} of {n_r}); DSR {D:.2f} at {TRIALS}")
print(f"  reported: DSR at the A1-only variance {var_a1:.3g}: {dsr(var_a1):.2f}; PSR against zero (no trial penalty): {psr0:.2f}")
for w in vt.WINDOWS:
    v = vt.window_reading(cand, control, w)
    print(f"  {w}: CAGR {v['cagr']*100:+.1f}% vs {v['cagr_control']*100:+.1f}%; worst drawdown {v['drawdown']*100:+.1f}% vs {v['drawdown_control']*100:+.1f}%; Sharpe {v['sharpe']:.2f} vs {v['sharpe_control']:.2f}")
tests = {
    "+2 bp at t>=2 (2016-2023)": d["mean_daily_bp"] >= 2.0 and d["hac_t"] >= 2.0,
    "not negative 2024-2026": r["mean_daily_bp"] >= 0.0,
    ">= 15 of 20 offsets": above >= 15,
    "DSR >= 0.95": math.isfinite(D) and D >= 0.95,
}
failed = [t for t, ok in tests.items() if not ok]
print("  GATE HOLDS (proposed as the sixth analyst; operator decides)" if not failed else f"  GATE FAILS ({'; '.join(failed)}) -> RECORD")
