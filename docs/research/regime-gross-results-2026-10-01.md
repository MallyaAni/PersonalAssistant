# Regime gross (B2) results: the day-type tail probability gating exposure (2026-10-01)

**RECORD, all three registered pairs. The book stays at gross 1.0.**

The registered test ([the plan](regime-gross-plan-2026-10-01.md), committed
at `18c444ce` before any code) was built at `bb5f0e61` and ran on spark1
at `bb5f0e61` (clean tree) on 2026-10-02 00:40-01:08Z (2026-10-01
20:40-21:08 ET; `~/scratch/rg_spark_study.sh`, `~/research-venv`, CPU,
nice 19), on the store as of the 2026-10-01 session, `--graded-cap 0.25`,
20 offsets, costs 10 and 25 bp; the verdict is at 25 bp. The run
committed its logs and verdict at `1f8ecbeb`. Controls: `ew_graded_cap25`
at gross 1.0, and B1's best registered target, σ* = 20% (`vt20`), re-run
on this session's store. Files under `docs/research/scorecards/regime-gross/`:

| File | What | sha256 |
|---|---|---|
| `rg_control.json` | point-in-time scorecard, gross 1.0 (`ew_graded_cap25`) | `50bc8b0953522f9c82cda8747b5f420c5a38d1dd2b8923d68e1bb7818cae0950` |
| `null.json` | the book through the regime path at θ = 1.0 | `e511e49088915c68219cbf6644174077267c789a5d2f78666e946436bf8d43c3` |
| `rg_rg30_g50.json` | θ = 0.3 / g_low = 0.5 | `10ed30f1e6489ae1dd0182ea15733c0e599089a5becd7e3ed38aad5e232caa02` |
| `rg_rg50_g50.json` | θ = 0.5 / g_low = 0.5 | `3e747727d9f6a6b86339bb6aed44a5df5e8f1f64951e8c7de92e5055d2c0904e` |
| `rg_rg50_g00.json` | θ = 0.5 / g_low = 0 | `0c0660352cfb63080e2ebc4e4f78eaf00fa0836fdba0a5f4819590bfdaa4579e` |
| `rg_rg50_g50_vt25.json` | reported: θ = 0.5 / g_low = 0.5 with σ* = 25% (per-session minimum) | `e36cffb83a3fa70e8d164219a446ffdb05cfa39fd005365e0d7266dc8c9c3482` |
| `vt_best.json` | B1's σ* = 20% re-run on this store (the second control) | `c1b43016d8d8249e0e321bb4a5ff74d6d0b09510f4adc783a9480d013579088b` |
| `regime_gross_verdict.json` | the two-control verdict | `9fccf43d8c22126aff35aed185a9be94700b8742214c8cd1bf9b1be1c670028e` |

Logs: `run.txt`, `null_test.txt`, `null.txt`, `registered.txt`,
`reported_vt25.txt`, `vt_best.txt`, `regime_gross_verdict.txt`, `check.txt`.

**The null test passed.** `null_test.txt`: "null test: the book through
the gross path at a rule that never fires (target inf, or regime threshold
1.0) against the plain path / lines compared: 24 / verdict: PASS,
reproduced to the bit". The independent check
(`regime_gross_check.py`, committed with the build) recomputed every
number in the verdict from the payloads' curves and per-offset CAGRs
against both controls, re-derived the gross path from the recorded
p(t−1), re-derived each label from the plan's criteria, and asserted the
θ = 1.0 payload reproduces the control's rows, paired evidence and curves
with gross 1 everywhere and every p below 1: "independent check: OK". The
build's 15 tests passed at the start of the run.

## The probability barely reached the thresholds

This decides the reading of everything below. The walk-forward tail
probability (horizon 1, boosted model, first fit 2018-06-26, refit every
63 sessions; Brier skill +0.004 on this store) is defined on 71% of
sessions and **never exceeded 0.385**. So:

- **θ = 0.5 never fired** (0.0% of sessions). Both θ = 0.5 pairs are the
  control, bit for bit in every number the verdict reads. The plan
  anticipated this: "a pair that fires on none is the control and RECORD".
- **θ = 0.3 fired on 0.5% of sessions** (0% of 2016-2023, 1% of
  2024-2026), about a dozen sessions in all.
- The reported combination with σ* = 25% is therefore σ* = 25% alone: the
  regime half never cut, and its 2016-2023 numbers equal B1's σ* = 25%
  row exactly.

## The verdicts

Registered criteria: a pair REPLACES only if, against **both** the gross-1
control **and** B1's best registered target, at the median of 20 offsets
and 25 bp, the worst drawdown improves ≥ 5 points on both windows with
CAGR down ≤ 3 points on each, **or** Sharpe +0.15 on both windows with
the drawdown not worse; and the paired daily difference is not negative
at NW t ≤ −2 on either window against either control. Clearing the
control and not the vol target is "RECORD (does not beat the vol
target)"; anything else is RECORD. B1's best registered target was read
from B1's verdict before any B2 number: none REPLACED, and σ* = 20% had
the largest 2016-2023 drawdown gain (+20.9 points), so it is the second
control.

Median of 20 offsets, 25 bp:

| Line | Window | Worst DD | CAGR | Sharpe | Gross < 1 |
|---|---|---|---|---|---|
| Control, gross 1 (`ew_graded_cap25`) | 2016-2023 | −45.5% | +28.0% | 0.98 | — |
| | 2024-2026 | −26.4% | +46.7% | 1.26 | — |
| B1 σ* = 20% (`vt20`, this store) | 2016-2023 | −24.6% | +21.7% | 1.09 | (58% in B1) |
| | 2024-2026 | −24.3% | +24.8% | 1.12 | |
| θ 0.3 / g_low 0.5 | 2016-2023 | −44.9% | +27.8% | 0.98 | 0% |
| | 2024-2026 | −29.1% | +44.1% | 1.21 | 1% |
| θ 0.5 / g_low 0.5 | both | = control | = control | = control | 0% |
| θ 0.5 / g_low 0 | both | = control | = control | = control | 0% |
| *Reported:* θ 0.5 / 0.5 ∧ σ* 25% | 2016-2023 | −30.1% | +24.4% | 1.08 | 42% |
| | 2024-2026 | −26.1% | +31.2% | 1.19 | 67% |
| SPY | 2016-2023 | −33.7% | +13.2% | 0.76 | |
| | 2024-2026 | −18.8% | +20.3% | 1.27 | |
| QQQ | 2016-2023 | −35.1% | +18.6% | 0.86 | |
| | 2024-2026 | −22.8% | +24.9% | 1.17 | |

Paired daily difference (bp a session, NW t), and offsets above:

| Pair | vs control 2016-2023 | vs control 2024-2026 | above control | vs vt20 2016-2023 | vs vt20 2024-2026 | above vt20 | Label |
|---|---|---|---|---|---|---|---|
| θ 0.3 / 0.5 | −0.1 (−0.75) | −0.7 (−1.34) | 0 of 20 | +3.2 (+2.15) | +5.9 (+1.98) | 20 of 20 | RECORD |
| θ 0.5 / 0.5 | 0.0 (n/a) | 0.0 (n/a) | 0 of 20 | +3.3 (+2.17) | +6.6 (+2.28) | 20 of 20 | RECORD |
| θ 0.5 / 0 | 0.0 (n/a) | 0.0 (n/a) | 0 of 20 | +3.3 (+2.17) | +6.6 (+2.28) | 20 of 20 | RECORD |
| *Reported:* ∧ σ* 25% | −2.1 (−1.70) | −4.7 (−2.28) | 0 of 20 | +1.2 (+2.83) | +1.9 (+1.88) | 20 of 20 | REPORTED |

Against the control, no pair moved the drawdown by 5 points on either
window (θ = 0.3 made 2024-2026 2.7 points *worse*) and none raised the
Sharpe. Against `vt20`, every pair earns more (the positive paired
difference is gross 1 against an under-invested book, not the gate) but
carries a drawdown 2-21 points deeper, so neither trade clears.

The verdict lines, verbatim (`regime_gross_verdict.txt`):

```
regime gross (B2) against ew_graded_cap25 and vt20 as of 2026-10-01, 20 offsets, 25 bp; trials 477 cumulative, trial variance nan
θ = 0.3 / g_low = 0.5: gross below 1 on 2016-2023 0%, 2024-2026 1% of sessions
  against the control (ew_graded_cap25):
  ew_graded_cap25 + rg30_g50: paired 2016-2023 -0.1 bp/session (t -0.75) over 2012 sessions; 2024-2026 -0.7 bp/session (t -1.34); above the control at 0 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -44.9% against -45.5% (+0.6 points); CAGR +27.8% against +28.0% (-0.2 points); Sharpe 0.98 against 0.98 (-0.00)
    2024-2026: median worst drawdown -29.1% against -26.4% (-2.7 points); CAGR +44.1% against +46.7% (-2.6 points); Sharpe 1.21 against 1.26 (-0.05)
    RECORD (drawdown trade fails; Sharpe trade fails)
  against the vol target vt20 (ew_graded_cap25 + vt20):
  ew_graded_cap25 + rg30_g50: paired 2016-2023 +3.2 bp/session (t +2.15) over 2012 sessions; 2024-2026 +5.9 bp/session (t +1.98); above the control at 20 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -44.9% against -24.6% (-20.3 points); CAGR +27.8% against +21.7% (+6.1 points); Sharpe 0.98 against 1.09 (-0.11)
    2024-2026: median worst drawdown -29.1% against -24.3% (-4.7 points); CAGR +44.1% against +24.8% (+19.3 points); Sharpe 1.21 against 1.12 (+0.09)
    RECORD (drawdown trade fails; Sharpe trade fails)
  RECORD
θ = 0.5 / g_low = 0.5: gross below 1 on 2016-2023 0%, 2024-2026 0% of sessions
  against the control (ew_graded_cap25):
  ew_graded_cap25 + rg50_g50: paired 2016-2023 +0.0 bp/session (t n/a) over 2012 sessions; 2024-2026 +0.0 bp/session (t n/a); above the control at 0 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -45.5% against -45.5% (+0.0 points); CAGR +28.0% against +28.0% (+0.0 points); Sharpe 0.98 against 0.98 (+0.00)
    2024-2026: median worst drawdown -26.4% against -26.4% (+0.0 points); CAGR +46.7% against +46.7% (+0.0 points); Sharpe 1.26 against 1.26 (+0.00)
    RECORD (drawdown trade fails; Sharpe trade fails)
  against the vol target vt20 (ew_graded_cap25 + vt20):
  ew_graded_cap25 + rg50_g50: paired 2016-2023 +3.3 bp/session (t +2.17) over 2012 sessions; 2024-2026 +6.6 bp/session (t +2.28); above the control at 20 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -45.5% against -24.6% (-20.9 points); CAGR +28.0% against +21.7% (+6.3 points); Sharpe 0.98 against 1.09 (-0.11)
    2024-2026: median worst drawdown -26.4% against -24.3% (-2.1 points); CAGR +46.7% against +24.8% (+21.9 points); Sharpe 1.26 against 1.12 (+0.14)
    RECORD (drawdown trade fails; Sharpe trade fails)
  RECORD
θ = 0.5 / g_low = 0: gross below 1 on 2016-2023 0%, 2024-2026 0% of sessions
  against the control (ew_graded_cap25):
  ew_graded_cap25 + rg50_g00: paired 2016-2023 +0.0 bp/session (t n/a) over 2012 sessions; 2024-2026 +0.0 bp/session (t n/a); above the control at 0 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -45.5% against -45.5% (+0.0 points); CAGR +28.0% against +28.0% (+0.0 points); Sharpe 0.98 against 0.98 (+0.00)
    2024-2026: median worst drawdown -26.4% against -26.4% (+0.0 points); CAGR +46.7% against +46.7% (+0.0 points); Sharpe 1.26 against 1.26 (+0.00)
    RECORD (drawdown trade fails; Sharpe trade fails)
  against the vol target vt20 (ew_graded_cap25 + vt20):
  ew_graded_cap25 + rg50_g00: paired 2016-2023 +3.3 bp/session (t +2.17) over 2012 sessions; 2024-2026 +6.6 bp/session (t +2.28); above the control at 20 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -45.5% against -24.6% (-20.9 points); CAGR +28.0% against +21.7% (+6.3 points); Sharpe 0.98 against 1.09 (-0.11)
    2024-2026: median worst drawdown -26.4% against -24.3% (-2.1 points); CAGR +46.7% against +24.8% (+21.9 points); Sharpe 1.26 against 1.12 (+0.14)
    RECORD (drawdown trade fails; Sharpe trade fails)
  RECORD
θ = 0.5 / g_low = 0.5 ∧ σ* = 25% (reported): gross below 1 on 2016-2023 42%, 2024-2026 67% of sessions
  against the control (ew_graded_cap25):
  ew_graded_cap25 + rg50_g50_vt25: paired 2016-2023 -2.1 bp/session (t -1.70) over 2012 sessions; 2024-2026 -4.7 bp/session (t -2.28); above the control at 0 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -30.1% against -45.5% (+15.4 points); CAGR +24.4% against +28.0% (-3.7 points); Sharpe 1.08 against 0.98 (+0.10)
    2024-2026: median worst drawdown -26.1% against -26.4% (+0.3 points); CAGR +31.2% against +46.7% (-15.5 points); Sharpe 1.19 against 1.26 (-0.08)
    RECORD (drawdown trade fails; Sharpe trade fails; paired difference negative at t <= -2)
  against the vol target vt20 (ew_graded_cap25 + vt20):
  ew_graded_cap25 + rg50_g50_vt25: paired 2016-2023 +1.2 bp/session (t +2.83) over 2012 sessions; 2024-2026 +1.9 bp/session (t +1.88); above the control at 20 of 20 offsets; deflated Sharpe n/a at 477
    2016-2023: median worst drawdown -30.1% against -24.6% (-5.5 points); CAGR +24.4% against +21.7% (+2.6 points); Sharpe 1.08 against 1.09 (-0.01)
    2024-2026: median worst drawdown -26.1% against -24.3% (-1.8 points); CAGR +31.2% against +24.8% (+6.4 points); Sharpe 1.19 against 1.12 (+0.06)
    RECORD (drawdown trade fails; Sharpe trade fails)
  REPORTED, deciding nothing
```

## What it means for the board

Nothing changes: the book keeps gross 1.0, no sizing rule moves, and
nothing is proposed for live.

In plain numbers, at 25 bp: the incumbent book made +28.0% a year with a
−45.5% worst drawdown on 2016-2023 (SPY +13.2% / −33.7%, QQQ +18.6% /
−35.1%) and +46.7% a year with −26.4% on 2024-2026 (SPY +20.3% / −18.8%,
QQQ +24.9% / −22.8%). The regime gate did not get a fair chance to do
anything: the day-type model never once called a session even 4× its
~10% base rate, so at θ = 0.5 it never cut, and at θ = 0.3 it cut on a
dozen sessions, cost 2.6 points of 2024-2026 CAGR and made that window's
drawdown 2.7 points worse. That is what a probability with no skill over
climatology (Brier skill +0.004) does as a switch: it cannot separate a
storm from an ordinary volatile week.

Against B1's best target the picture is unchanged from B1: σ* = 20%
roughly halves the 2016-2023 drawdown (−24.6% against −45.5%) for 6.3
points of CAGR there, but costs 21.9 points of CAGR on 2024-2026 for 2
points of drawdown. Neither the gate nor the volatility target is a
drawdown fix for this book. The plan's prior (20% that a pair clears the
drawdown trade against the control) did not hold, and its "likely
finding" (the gate fires rarely at θ = 0.5) held more strongly than
written: it never fired.

A useful regime gate would need a probability that actually moves (a
model with skill, or a threshold set relative to the model's own
distribution, e.g. its top decile) - that is a new question and would
need its own registration; reading it from this run would be selection.

## Disclosed deviations and notes

- **B1's control moved by one session.** B1 ran on the 2026-09-30 store
  (control 2024-2026: −25.4% / +45.3%); B2 ran on the 2026-10-01 store
  (−26.4% / +46.7%). The run script detected this and re-ran σ* = 20% on
  this store as the second control (`vt_best.json`: 2024-2026 −24.3% /
  +24.8% against B1's −23.9% / +23.7%; 2016-2023 identical). The check
  asserted the regime run's control equals the re-run's control.
- **The tail probability's Brier skill reproduced at +0.004**, against
  −0.001 in the 09-26 study, on a store a few sessions longer; both are
  no skill.
- **Deflated Sharpe "n/a at 477", trial variance "nan".** Two of the
  three registered pairs are identical to the control (paired difference
  exactly 0, t undefined), so the across-trial variance is undefined. DSR
  is reported and decides nothing under the plan.
- **The store changed during the run, not in anything it read.** The A4
  insider fetch wrote 82 `edgar_insiders` frames and zips into
  `data/market` at 01:02-01:05Z, inside this run's window; no price,
  panel or desk file changed between 00:40 and 01:12Z (checked by mtime).
- **Payloads committed with this note**, as B1's were: `rg_control.json`,
  `null.json`, the four `rg_*.json`, `vt_best.json`. The scorecard also
  wrote `null_control.json`, `rg_rg50_g50_vt25_control.json` and
  `vt_best_control.json`; all three are byte-identical to
  `rg_control.json` (sha256 above) and are not committed.
- The check's "median-offset CAGR" lines are the stored offset-10 curve
  checked against that offset's own CAGR; the verdict's figures are the
  medians across 20 offsets. They are different statistics and both
  matched.
- Runtime warnings (empty-slice means in `regime.py` and `levels.py`) are
  from the early, thin part of the panel, as in every scorecard run.

Trials: 3 registered; cumulative 474 → 477.
