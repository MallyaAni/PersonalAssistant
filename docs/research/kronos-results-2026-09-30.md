# Kronos results: a pre-trained K-line model on the book's bars (2026-09-30)

**RECORD on K1 (by construction), RECORD on K2 buy, RECORD on K2 sell. K3,
reported: Kronos adds no marginal information to the stage-1 ridge. The
desk keeps its five analysts and `dip_or_close` on both sides.**

The registered test ([the plan](kronos-plan-2026-09-30.md) with its two
addenda: the cutoff fixed at 2024-06-30 before any download, the build
choices and the smoke test before any study forecast) ran as a feature
test: the pre-trained checkpoint only, nothing fine-tuned, nothing tuned
after. The forecasts were made on the RTX 5080 (K1 16:09-18:27 ET, K2
18:27-21:27, the disclosed K1c40 set 21:27-21:40) and evaluated on spark1
at `402a38d8` from 21:41 to 22:06 ET on the store as of the 2026-09-30
session (2,953 sessions, 95 names in the panel, 94 with a cube). The
payloads are `scorecards/kronos/kronos_k1.json`, `kronos_k2.json` and
`kronos_k3.json`, the evaluation log `kronos_eval.txt`. An independent
script with nothing imported from `backend/` recomputed K1's mean IC and t
from the per-period ICs and K2's window means, Newey-West t and per-order
g from the payload's rows, and matched every number the verdicts rest on
(`kronos_check.py`: "independent check: PASS").

The operator's question was whether a specialised open-source model could
solve "when to buy". The plan's prior was 15% that K1 clears the IC floor
and 10% that K2 replaces the fill rule. Neither happened, and the reading
below is that the model reads this book's bars no better than the stage-1
models did and worse than the desk.

## The verdict lines, verbatim from the payloads

K1 (`kronos_k1.json`):

```
K1 criterion K1 return: post-cutoff IC -0.0570 (t -0.85) on 28 periods (needs >= 60, IC >= 0.02, t >= 2.0) - fails
K1 criterion K1 drawdown: post-cutoff IC -0.0777 (t -1.27) on 28 periods (needs >= 60, IC >= 0.02, t >= 2.0) - fails
K1 criterion K1c40 return: post-cutoff IC +0.0129 (t +0.33) on 28 periods (needs >= 60, IC >= 0.02, t >= 2.0) - fails
K1 criterion K1c40 drawdown: post-cutoff IC -0.0217 (t -0.54) on 28 periods (needs >= 60, IC >= 0.02, t >= 2.0) - fails
VERDICT: RECORD - RECORD by construction: fewer than 60 post-cutoff periods
```

K2 (`kronos_k2.json`):

```
RECORD: no Kronos fill candidate clears every criterion on the post-cutoff window; the board keeps dip_or_close on both sides
  K2_buy (kronos_low, buy): post-cutoff model window +0.1 bp/session (t +0.55) over 564 sessions; next-bar +0.1 (t +0.50) fails; contaminated 2018-01..2024-06 +0.0 bp/session (t +0.23); deflated Sharpe +0.50 at N = 2 (+0.01 at 466); drift-adjusted +0.1 (t +0.55); positive at 3 of 20 offsets; per re-timed order +18.8 bp (t +1.03) over 116 of 319 orders; forecast on 100%; mean level ratio 0.9758; level reached 32%; oracle capture 5% - RECORD
  K2_sell (kronos_high, sell): post-cutoff model window -0.2 bp/session (t -0.87) over 564 sessions; next-bar -0.2 (t -0.81) fails; contaminated 2018-01..2024-06 +0.2 bp/session (t +1.37); deflated Sharpe +0.08 at N = 2 (+0.00 at 466); drift-adjusted -0.2 (t -0.87); positive at 0 of 20 offsets; per re-timed order -14.5 bp (t -0.57) over 42 of 116 orders; forecast on 98%; mean level ratio 1.0189; level reached 34%; oracle capture -4% - RECORD
```

K3 (`kronos_k3.json`, reported, no trial):

```
K3 in_window: stage-1 ridge daily IC +0.0054 (t +0.84), ridge + K1 +0.0060 (t +0.94); marginal +0.0006 (t +0.92) over 1061 dates
K3 post_window: stage-1 ridge daily IC +0.0086 (t +1.13), ridge + K1 +0.0076 (t +1.00); marginal -0.0010 (t -1.01) over 525 dates
```

## K1: the daily forecast as a stance

`harness.evaluate_scores` at 20 sessions, 10 bp, at least 15 names, on
the graded member cells every arm scores (76,314 cells from 2018-01-02;
K1 forecast 76,019 of them, 295 skipped for fewer than 512 prior daily
rows: CRWV, GLXY, NBIS, SNDK and Q). The arms are the predicted
20-session log return and the predicted path's maximum drawdown (higher
= shallower); the desk's own graded score is measured on the same cells.
In-window is 2018-01-02..2024-06-30, inside the model's training data
and **contaminated**; post-cutoff is 2024-07-01 on and decides.

| Arm | In-window (contaminated): 82 periods, 51,666 cells | Post-cutoff: 28 periods, 24,326 cells |
|---|---|---|
| K1 return (512-bar context) | IC −0.0064 (t −0.23), net Sharpe −0.26; vs desk −0.061 (paired t −1.38) | IC **−0.0570** (t −0.85), net Sharpe −0.60; vs desk −0.127 (paired t −1.24) |
| K1 drawdown | IC −0.0090 (t −0.33), net Sharpe −0.59; vs desk −0.063 (t −1.46) | IC **−0.0777** (t −1.27), net Sharpe −0.91; vs desk −0.147 (t −1.52) |
| K1c40 return (40-bar context, disclosed) | IC +0.0246 (t +0.97), net Sharpe −0.09; vs desk −0.030 (t −0.81) | IC +0.0129 (t +0.33), net Sharpe +0.04; vs desk −0.057 (t −0.90) |
| K1c40 drawdown | IC +0.0363 (t +1.36), net Sharpe −0.32; vs desk −0.018 (t −0.50) | IC −0.0217 (t −0.54), net Sharpe −1.00; vs desk −0.091 (t −1.44) |
| **Desk score, same cells** | IC **+0.0541** (t +2.33), net Sharpe +0.64 | IC **+0.0695** (t +1.78), net Sharpe +1.02 |

The criterion needs at least 60 post-cutoff periods; there are 28
(564 sessions at 20), so K1 is RECORD by construction, as Addendum 1 said
before the run. The numbers are still on record: at the registered 512
bars the model is negative on both windows and both features, and on
the post-cutoff window it is 0.13-0.15 of IC behind the desk on paired
periods. At the paper's own 40-bar look-back it is positive in-window
(+0.025, +0.036, t about 1, inside the contaminated period) and nothing
after the cutoff. The book gate (a sixth analyst through the T-S1
scorecard) was registered as follow-up and not run: its deciding window
is entirely contaminated.

## K2: the intraday path as a fill rule

Adaptive entry's harness on the executed orders of `ew-redeploy` under
`graded-equal-weight/5` against `dip_or_close`, 25 bp, 20 offsets,
statistics at offset 10, Newey-West lag 20. `K2_buy` fills at the first
15-minute close at or below t+1's open × clip(predicted low / predicted
open, 0.97, 0.99), else the close; `K2_sell` is the mirror on the
predicted high in [1.01, 1.03]. The model window is the post-cutoff
sessions, 2024-07-01 on (564 decision sessions; at the median offset 319
buys and 116 sells); the contaminated window 2018-01-02..2024-06-30
(1,633 sessions, 1,185 buys, 398 sells) is reported and reads criterion 3.
The forecast covers 100% of the buys and 98% of the sells (two sells
with no forecast take the control's fill). The floor is +2.0 bp of equity
a session at t ≥ 2.

| Candidate | 1. Model window (post-cutoff) | 2. Next-bar | 3. Contaminated window | 4. DSR at N=2 (at 466) | 5. Drift-adj. | 6. Offsets > 0 | Per re-timed order | Reached | Mean level ratio | Oracle capture | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| K2_buy (predicted low) | **+0.15 bp** (t +0.55), 564 sessions | +0.13 (t +0.50) | +0.03 (t +0.23), 1,633 sessions | 0.50 (0.01) | +0.15 (t +0.55) | 3 of 20 | **+18.8 bp** (t +1.03), 116 of 319 | 32% | 0.9758 | 5% | **RECORD** |
| K2_sell (predicted high) | **−0.23 bp** (t −0.87), 564 sessions | −0.22 (t −0.81) | +0.16 (t +1.37), 1,633 sessions | 0.08 (0.00) | −0.23 (t −0.87) | 0 of 20 | −14.5 bp (t −0.57), 42 of 116 | 34% | 1.0189 | −4% | **RECORD** |

Each candidate passes criterion 3 only (the contaminated window is not
negative) and fails the other five. Neither is "real but immaterial"
(that needs a clustered t of 3 on the re-timed orders). The expected best
null t is 0.52 at the registered two trials and 3.03 at the cumulative
466; nothing here reaches either. No candidate waits past t+1, so the
drift adjustment is zero (14.6 bp a session of A/A+ drift on the model
window, 9.7 on the contaminated window, applied to a wait of 0).

- **The buy level is a deeper dip than the control's.** After the clip
  the level averages 0.976 of t+1's open, a 2.4% dip against the
  control's 1%. It is reached on 32% of the model-window buys; where it
  is reached the fill is lower than the control's, where only the
  control's 1% is reached the buy goes to the close instead. The two
  cancel to +0.15 bp a session.
- **The one positive reading, read as the criteria read it.** The 116
  re-timed buys gain +18.8 bp each on average, t 1.0; the gain sits in the
  entries (+31 bp over 33, t 1.4) and the adds (+17 bp over 65, t 0.6),
  the retries lose (−10 bp over 15). By grade it is +8 bp on A+ (69 buys)
  and +30 bp on A (46). Across the 20 offsets the session mean runs from
  −0.35 to +0.15 bp and is positive at three; offset 10, where the
  statistics are read, is the best of the twenty. That is the shape of
  noise at this sample, and the criteria were written so it reads as
  RECORD.
- **The sell is negative everywhere after the cutoff** (all 20 offsets,
  −0.20 to −0.44 bp a session) and positive on the contaminated window at
  all 20 (+0.11 to +0.24, t 1.4 at the median), which is what a model that
  has seen the bars and then has not would look like. Rotation exits, 84
  of the 116 sells, carry the loss (−13 bp a re-timed sell).
- **Next-bar** changes nothing: +0.13 and −0.22 bp a session.
- **The oracle.** The lowest bar close of t+1 is 136 bp below the control
  fill on the model-window buys; the buy rule captures 5% of it, the sell
  rule −4% of its mirror.

## K3: does Kronos know anything the simple models did not?

K1's two columns appended to the stage-1 dataset's scalars on the 70,493
rows with a forecast (11,119 without), the stage-1 ridge walked forward
with and without them (26 refits), daily IC per window and the paired
difference at Newey-West lag 20:

| Window | Stage-1 ridge | Ridge + K1 | Marginal |
|---|---|---|---|
| In-window (contaminated), 1,061 dates | +0.0054 (t +0.84) | +0.0060 (t +0.94) | **+0.0006** (t +0.92) |
| Post-cutoff, 525 dates | +0.0086 (t +1.13) | +0.0076 (t +1.00) | **−0.0010** (t −1.01) |

Nothing. The ridge reads the model's columns as a thousandth of an IC
either way, inside the contaminated period and after it.

## What it means

- **A pre-trained K-line model reads this book's bars no better than the
  stage-1 models and worse than the desk.** Stage 1's price-only models
  reached an IC of 0.011-0.013 on 2016-2023 and nothing after; Kronos at
  its registered context is negative on both windows, and at the paper's
  short context it reaches +0.025 to +0.036 only inside the period it was
  trained on. The desk's own score on the same cells is +0.054 (t 2.3)
  and +0.070 (t 1.8), and every Kronos arm is behind it on paired periods
  on both windows. Added to the stage-1 ridge the model contributes
  nothing. The plan's expected finding, that the model reads volatility
  and not direction, is consistent with this: the smoke test's uniform
  bearish bias at 512 bars (Addendum 2) is the model reading the context's
  scale, and a bias that scales with each name's trend ranks names
  backwards on a trending book.
- **What the study can say.** On K2 the post-cutoff window is enough to
  decide: 564 sessions put the standard error of the session mean near
  0.26 bp, so the buy rule's +0.15 bp sits inside about −0.4 to +0.7 bp
  and the registered +2 bp floor is ruled out, as is any sell improvement.
  The one positive reading, +18.8 bp on 116 re-timed buys, is t 1.0 at 3
  of 20 offsets, and would need the same sign at fifteen offsets and a t
  of 2 on the session series to be anything. On K1 the study can say the
  model is behind the desk on every window and feature, and that at the
  registered context it is negative.
- **What it cannot say.** The post-cutoff window is 564 sessions, 28
  non-overlapping periods at 20 sessions, under the 60 the K1 criterion
  requires, so K1 is RECORD by construction. The standard error of a
  28-period IC is about 0.07 for the Kronos arms, so the post-cutoff
  window cannot tell an IC of 0.02 from zero and cannot rule out a small
  effect in either direction; even the paired gaps to the desk (−0.13
  and −0.15 for the 512-bar arms, t −1.2 and −1.5) point one way without
  deciding. The in-window numbers, where the period count would suffice,
  are contaminated and never decide. The criterion will have 60
  post-cutoff periods around 2029; nothing in these numbers says the
  wait is worth it.
- **For the desk.** No sixth analyst, no change to the fill rule. The
  operator's question, whether a specialised model is the next best step,
  has the answer the proposing note gave: no. The structure rules of batch
  S1 remain the line of work.

## Trials

Two registered (K1, K2), cumulative 466, the count the K2 deflated Sharpe
was computed at. Addendum 2 added K1c40 as a disclosed extra set before
the run, which makes three and a cumulative 467; both counts are reported
as the addendum asks, and the deflated Sharpe at 466 (0.01 and 0.00)
would not move at 467.

## Disclosed

- **The cutoff** is the paper's (arXiv 2508.02739v1, appendix "Forecasting
  Task Setup": pre-training data through June 2024, test from July 2024),
  recorded in Addendum 1 before any download; the model card states none.
  The post-cutoff window's 28 periods and the RECORD-by-construction
  consequence were written down there too.
- **Weights:** `NeoQuasar/Kronos-base` (model.safetensors 409,264,008
  bytes) and `NeoQuasar/Kronos-Tokenizer-base` (15,842,368 bytes), code
  `shiyu-coder/Kronos` at `67b630e`, the repository's regression tests
  passing on the RTX venv (torch 2.14.0+cu130). **Sampling** as Addendum 2
  fixed it from the README's defaults: T 1.0, top_p 0.9, top_k 0,
  sample_count 1, seed 0 per (name, batch), fp32, no autocast, clip 5,
  context 512 (K1 batch 192, K2 batch 128; K1c40 context 40, batch 512).
  The paper's own Table 6 setting (T 0.6, N 10) was not used.
- **The forecasts** are on spark1 under `~/scratch/kronos/forecasts/`:
  `k1.zip` sha256 `f5f5a7b153c3dca6304d3427556fa3c6be75f0949c95e9bf0eb37ead1ef3b07c`
  (76,019 rows, 8,260 s on the RTX, 9.2 cells/s), `k2.zip`
  `f73eaa2d40b407ad507c4736e58fe42cedae02c64ba0891cf15dd86cfe022434`
  (75,157 rows, 1,157 cells skipped for short 15-minute context, 10,794 s,
  7.0 cells/s), `k1c40.zip`
  `1ecdc8d21f5755d68421d356738ef9816505c45633784c9a9a38599004853fef`
  (76,280 rows, 801 s). The per-file sha256 of the K1 parquets computed
  on the RTX (`k1_rtx.sha`) and after the copy to spark1 (`k1_spark.sha`)
  are identical; each payload records the per-file hashes of the
  forecasts it read.
- **The evaluation** ran on spark1 (`eval.sh`, log `kronos_eval.txt`) from
  21:41:12 to 22:06:22 ET: K1 4.6 minutes, K3 15.8 minutes (the two
  walk-forward ridges), K2 4.7 minutes, then the independent check. The
  worktree was clean at `402a38d8` for every run (`run.revision.dirty:
  false`). No number was read before the three forecast sets were
  complete; nothing was tuned after.
- **The RTX run** (16:09-21:40 ET) overlapped the operator's own session on
  that machine; the log is `E:\AgentWorkspace\rtx-data\kronos\kronos_arms.log`.
  Nothing on the RTX was deleted.
- **Not run:** the K1 book gate (sixth analyst, follow-up); K2 at the
  paper's 160-bar intraday setting (registered follow-up, not run).
- Every K1 per-period IC, every K2 order at the median offset with its
  control and candidate fills, g, level ratio and flags, and the K3
  window statistics are in the payloads, so every figure above can be
  recomputed; `kronos_check.py` does so.
