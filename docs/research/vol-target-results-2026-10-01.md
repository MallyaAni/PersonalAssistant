# Volatility targeting of the book (B1) results: gross scaled to 20/25/30% a year (2026-10-01)

**RECORD, all three registered targets. The book stays at gross 1.0.**

The registered test ([the plan](vol-target-plan-2026-10-01.md), committed
at `bd814b64` before any code) was built at `d8a38ad6` and ran on spark1
at `d8a38ad6` (clean tree) on 2026-10-01 20:32-21:23Z
(`~/scratch/vt_spark_study.sh`, `~/research-venv`, CPU, nice 19), on the
store as of the 2026-09-30 session, `--graded-cap 0.25`, 20 offsets, costs
10 and 25 bp; the verdict is at 25 bp. The verdict command
(`market_vol_target`) and the independent check ran at 23:09Z on the same
payloads. Control: `ew_graded_cap25` at gross 1.0. Files under
`docs/research/scorecards/vol-target/`:

| File | What | sha256 |
|---|---|---|
| `control.json` | point-in-time scorecard, gross 1.0 (`ew_graded_cap25`) | `9597b211f8aa4917975422c07c7ebb2c34eca379391cc7eb866ec55767507a39` |
| `null.json` | the same through the gross path at σ* = ∞ | `c3b020bf5e64fd73cd77281a08756faf7e2f70a3d935db9fe559304cb9afde94` |
| `vt_vt20.json`, `vt_vt25.json`, `vt_vt30.json` | the three registered targets | `c91516cc…59ea7c1`, `51615c36…2e38e`, `75945c0f…2b2132` |
| `vol_target_verdict.json` | the registered verdict (3 targets against the control) | `cce7d076d9bfb08a40c86fff19f2f50a1c23660344ae4a9221bca491e0e32666` |
| `vol_target_reported.json` | the reported variants through the same verdict code; decides nothing | `39d25844b87684788e4fb27588fd50e9ad9e408666f5cac68956adf0d4153be0` |

Logs: `control.txt`, `null_test.txt`, `null.txt`, `registered.txt`,
`reported_*.txt`, `verdict.txt`, `reported_verdict.txt`, `check.txt`.

**The null test passed.** `null_test.txt`: "null test: the book through the
volatility-target path at an infinite target against the plain path /
lines compared: 24 / verdict: PASS, reproduced to the bit". The
independent check (`vol_target_check.py`, committed with the build)
recomputed every number from the payload curves and per-offset CAGRs, the
gross path from the control's gross-1 curve (matching the recorded path),
re-derived each label, and asserted the σ* = ∞ payload reproduces the
control's rows, paired evidence and curves: "independent check: OK".

## The verdicts

Registered criteria: REPLACES if, at the median of 20 offsets, the worst
drawdown improves ≥ 5 points on both windows with CAGR down ≤ 3 points on
each, **or** Sharpe +0.15 on both windows with drawdown not worse; and the
paired daily difference is not negative at NW t ≤ −2 on either window.
DSR at 474 is reported, does not decide.

| Target | Window | Worst DD (target / control) | DD gain | CAGR (target / control) | CAGR change | Sharpe (target / control) | Paired bp/session (NW t) |
|---|---|---|---|---|---|---|---|
| σ* = 20% | 2016-2023 | −24.6% / −45.5% | +20.9 | +21.7% / +28.0% | −6.3 | 1.09 / 0.98 | −3.3 (−2.18) |
| | 2024-2026 | −23.9% / −25.4% | +1.4 | +23.7% / +45.3% | −21.6 | 1.08 / 1.25 | −6.7 (−2.34) |
| σ* = 25% | 2016-2023 | −30.1% / −45.5% | +15.4 | +24.4% / +28.0% | −3.6 | 1.08 / 0.98 | −2.1 (−1.70) |
| | 2024-2026 | −25.0% / −25.4% | +0.4 | +30.3% / +45.3% | −15.0 | 1.16 / 1.25 | −4.8 (−2.32) |
| σ* = 30% | 2016-2023 | −35.8% / −45.5% | +9.7 | +25.5% / +28.0% | −2.5 | 1.05 / 0.98 | −1.6 (−1.58) |
| | 2024-2026 | −27.0% / −25.4% | −1.6 | +35.1% / +45.3% | −10.2 | 1.17 / 1.25 | −3.4 (−2.43) |

Every target is below the control at 0 of 20 offsets; DSR at 474: 0.01,
0.02, 0.02. Average gross (from the check): 0.790 at 20% (below 1 on 58%
of sessions, lowest 0.163), 0.868 at 25% (46%, 0.203), 0.919 at 30% (33%,
0.244). Each fails all three conditions: the drawdown trade (2024-2026
drawdown barely moves, and CAGR falls more than 3 points on 2024-2026 at
every target), the Sharpe trade (Sharpe falls on 2024-2026), and the
not-negative condition (2024-2026 paired t ≤ −2 at every target).

The verdict lines, verbatim (`verdict.txt`):

```
volatility target (B1) against ew_graded_cap25 as of 2026-09-30, 20 offsets, 25 bp; trials 474 cumulative, trial variance 0.0000
σ* = 20%: paired 2016-2023 -3.3 bp/session (t -2.18) over 2012 sessions; 2024-2026 -6.7 bp/session (t -2.34); above the control at 0 of 20 offsets; deflated Sharpe +0.01 at 474
  2016-2023: median worst drawdown -24.6% against -45.5% (+20.9 points); CAGR +21.7% against +28.0% (-6.3 points); Sharpe 1.09 against 0.98 (+0.11)
  2024-2026: median worst drawdown -23.9% against -25.4% (+1.4 points); CAGR +23.7% against +45.3% (-21.6 points); Sharpe 1.08 against 1.25 (-0.17)
  RECORD (drawdown trade fails; Sharpe trade fails; paired difference negative at t <= -2)
σ* = 25%: paired 2016-2023 -2.1 bp/session (t -1.70) over 2012 sessions; 2024-2026 -4.8 bp/session (t -2.32); above the control at 0 of 20 offsets; deflated Sharpe +0.02 at 474
  2016-2023: median worst drawdown -30.1% against -45.5% (+15.4 points); CAGR +24.4% against +28.0% (-3.6 points); Sharpe 1.08 against 0.98 (+0.10)
  2024-2026: median worst drawdown -25.0% against -25.4% (+0.4 points); CAGR +30.3% against +45.3% (-15.0 points); Sharpe 1.16 against 1.25 (-0.09)
  RECORD (drawdown trade fails; Sharpe trade fails; paired difference negative at t <= -2)
σ* = 30%: paired 2016-2023 -1.6 bp/session (t -1.58) over 2012 sessions; 2024-2026 -3.4 bp/session (t -2.43); above the control at 0 of 20 offsets; deflated Sharpe +0.02 at 474
  2016-2023: median worst drawdown -35.8% against -45.5% (+9.7 points); CAGR +25.5% against +28.0% (-2.5 points); Sharpe 1.05 against 0.98 (+0.07)
  2024-2026: median worst drawdown -27.0% against -25.4% (-1.6 points); CAGR +35.1% against +45.3% (-10.2 points); Sharpe 1.17 against 1.25 (-0.08)
  RECORD (drawdown trade fails; Sharpe trade fails; paired difference negative at t <= -2)
```

## Reported, deciding nothing

Through the same verdict code against the same control
(`reported_verdict.txt`); not registered, no DSR, labels shown only for
completeness:

| Variant | 2016-2023 DD gain / CAGR change / Sharpe | 2024-2026 DD gain / CAGR change / Sharpe | Paired t (16-23 / 24-26) | Offsets above |
|---|---|---|---|---|
| σ* = 15% | +26.7 / −10.8 / 1.05 | +5.8 / −28.0 / 1.02 | −2.61 / −2.42 | 0 |
| σ* = 25%, 60-session σ̂ | +12.6 / −3.4 / 1.05 | +1.4 / −13.9 / 1.18 | −1.48 / −2.09 | 0 |
| σ* = 25%, return switch | +18.9 / −6.4 / 1.09 | +5.2 / −18.1 / 1.11 | −1.38 / −1.82 | 0 |
| σ* = 25%, intercept switch | +8.8 / −0.0 / 1.10 | −0.9 / −6.8 / 1.27 | −1.26 / −1.87 | 7 |
| σ* = 25%, both switches | +18.9 / −3.1 / 1.15 | +1.6 / −14.4 / 1.13 | −0.94 / −1.76 | 0 |

The intercept switch (no scaling while the trailing risk-return intercept
is negative) is the only variant that keeps the 2016-2023 return whole
(+28.0% against +28.0%, drawdown −36.7% against −45.5%), but it still
gives up 6.8 points of CAGR on 2024-2026 and does not improve that
window's drawdown. It is one of five unregistered variants; reading it
as a finding would be selection. It would need its own registration.

## What it means for the board

Nothing changes: the book keeps gross 1.0 and no sizing rule moves.

In plain numbers, at 25 bp: the incumbent book made +28.0% a year with a
−45.5% worst drawdown on 2016-2023 (SPY +13.2% / −33.7%, QQQ +18.6% /
−35.1%) and +45.3% a year with −25.4% on 2024-2026 (SPY +20.3% / −18.8%,
QQQ +24.8% / −22.8%). The best-looking target, 25%, would have cut the
2016-2023 drawdown to −30.1% (shallower than QQQ's) for 3.6 points of
CAGR, but on 2024-2026 it cuts the return from +45.3% to +30.3% and the
drawdown only from −25.4% to −25.0%. The 2024-2026 drawdown came too fast
for a trailing 20-session (or 60-session) volatility to see; the scaling
then held the book under-invested through the high-volatility recovery.
The cost on the recent window is significant (paired t −2.3), and the
book is below the control at every one of 20 offsets. The plan's prior
(40% that a target clears the drawdown trade) did not hold.

Drawdown control for this book is not solved by book-level volatility
targeting, as it was not by name-level sizing
(`vol-sizing-2026-09-27.md`) or stops (`catastrophe-stop-2026-09-27.md`).
Nothing here is proposed for live.

## Disclosed deviations

- The run script wrote `--output vt.json` for the registered run; the
  scorecard writes one payload per target (`vt_vt20/25/30.json`) and the
  verdict reads those. Same numbers, different names.
- The scorecard also wrote a control payload beside every run
  (`vt_control.json`, `null_control.json`, `vt_vt15_control.json`, …);
  all seven are byte-identical to `control.json` and are not committed.
- The verdict prints "trial variance 0.0000": the across-target variance
  of the per-session paired Sharpes is 3.6e-5 (per-session units). The
  DSR it feeds is reported and decides nothing under the plan.
- The verdict and check ran at 23:09Z, two hours after the scorecards,
  from the same clean tree and payloads; the reported variants were also
  put through the verdict command (`vol_target_reported.json`), which the
  run script did not do.

Trials: 3 registered; cumulative 471 → 474.
