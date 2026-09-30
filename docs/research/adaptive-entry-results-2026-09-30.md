# Adaptive entry results: the dip threshold scaled by the name's own volatility (2026-09-30)

**RECORD, all three. The board keeps buying at the first 15-minute close 1%
under the open, else at the close.**

The registered test ([the plan](adaptive-entry-plan-2026-09-30.md),
committed at `57921bb0` before any code) ran on spark1 at `fe6fa36d` on
2026-09-30 05:25-05:31Z, on the store as of the 2026-09-29 session
(2,952 sessions, 94 names with a cube out of 94, cubes from 2016-01-04),
20 offsets, statistics at offset 10. The payload is
`docs/research/scorecards/adaptive-entry/adaptive_entry.json` (sha256
`f05f4ce3`), the log `adaptive_entry_run.txt`. An independent script
recomputed every number the verdict rests on from the payload's per-order
rows - its own Newey-West and clustered t - and matched the engine to 1e-6
on every window, both fill modes, all three candidates
(`adaptive_entry_check.py`: "independent check: OK").

## The verdicts

At the median offset, model window 2018-01-02..2023-12-29 (1,509 decision
sessions, 1,091 buys: 628 graded A+, 463 A; 242 entries, 525 adds, 324
retries; 18 unpriced), then 2024-2026 (687 sessions, 387 buys, 9 unpriced).
The floor is +2.0 bp of equity a session at Newey-West t ≥ 2.

| Candidate | 1. Model window | 2. Next-bar | 3. 2024-2026 | 4. DSR at N=3 | 5. Drift-adj. | 6. Offsets > 0 | Per re-timed buy | Verdict |
|---|---|---|---|---|---|---|---|---|
| E1 half-sigma dip | **−0.08 bp** (t −0.56) | −0.06 (t −0.46) | −0.14 (t −0.51) | 0.03 | −0.08 (t −0.56) | 3 of 20 | −9.4 bp (t −0.99), 292 of 1,091 | **RECORD** |
| E2 one-sigma dip | **−0.03 bp** (t −0.21) | −0.03 (t −0.19) | −0.39 (t −1.28) | 0.12 | −0.03 (t −0.21) | 1 of 20 | −4.8 bp (t −0.42), 415 of 1,091 | **RECORD** |
| E3 gap guard | **+0.02 bp** (t +1.52) | +0.02 (t +1.52) | +0.00 (t +0.02) | 0.88 | +0.02 (t +1.52) | 18 of 20 | +110.3 bp (t +1.21), 5 of 1,091 | **RECORD** |

Every criterion fails for E1 and E2. E3 passes criteria 3 and 6 only; it
is not "real but immaterial" (that needs a clustered t of 3 on the
re-timed buys; it has 1.2 on five of them). Deflated Sharpe at the
cumulative 457 trials: 0.00 for all three. The cumulative trial count is
457.

The verdict lines, verbatim from the run:

```
RECORD: no candidate clears every criterion; the board keeps the fixed 1% dip_or_close
  E1 (sigma_half): model window -0.1 bp/session (t -0.56); next-bar -0.1 (t -0.46) fails; 2024-2026 -0.1 bp/session; deflated Sharpe +0.03 at N = 3 (+0.00 at 457); drift-adjusted -0.1 (t -0.56); positive at 3 of 20 offsets; per re-timed order -9.4 bp (t -0.99) over 292 of 1091 orders; level reached 42%; oracle capture -2% - RECORD
  E2 (sigma_one): model window -0.0 bp/session (t -0.21); next-bar -0.0 (t -0.19) fails; 2024-2026 -0.4 bp/session; deflated Sharpe +0.12 at N = 3 (+0.00 at 457); drift-adjusted -0.0 (t -0.21); positive at 1 of 20 offsets; per re-timed order -4.8 bp (t -0.42) over 415 of 1091 orders; level reached 18%; oracle capture -2% - RECORD
  E3 (gap_guard): model window +0.0 bp/session (t +1.52); next-bar +0.0 (t +1.52) fails; 2024-2026 +0.0 bp/session; deflated Sharpe +0.88 at N = 3 (+0.00 at 457); drift-adjusted +0.0 (t +1.52); positive at 18 of 20 offsets; per re-timed order +110.3 bp (t +1.21) over 5 of 1091 orders; guard held 1%; oracle capture 0% - RECORD
```

## What the numbers say

- **The fixed 1% is not a bad number for this book.** The control reaches
  its dip on 41.3% of the buys' sessions (443 of 1,073 priced on the
  model window). The half-sigma level is reached on 41.8%, the one-sigma
  level on 18.3%. Scaling the threshold by σ_t moves buys in both
  directions and the two movements cancel to slightly worse than zero.
- **Why E1 loses: it widens exactly where it hurts.** With σ_t under 2%
  the half-sigma level is *tighter* than 1%: E1 fills a shallower dip
  first, or the same bar as the control (214 of its 449 reached fills are
  the control's own bar, g = 0). Where σ_t is over 2% the level is
  *wider*: on 57 model-window buys the control's 1% was reached and the
  half-sigma level was not, and those buys filled at the close instead,
  **−192 bp each** on average. The 449 reached fills average +18 bp; the 57
  misses cost more than all of them gain.
- **E2 is D0 confined to the session, and it reads as D0 did.** It reaches
  its level on 18% of buys (+90 bp each when it does), and on 255 buys the
  control's dip was reached while the one-sigma level was not (−77 bp
  each). On 2024-2026 it is negative at all 20 offsets (−0.07 to −0.65 bp
  a session, median −0.46; per re-timed buy −28.4 bp, t −1.53), worst on
  the A+ buys (−26.9 bp a buy) and on retries (−31.5).
- **The gap guard almost never fires, and when it fires it is a coin
  flip.** A gap-down of more than 2σ at the open happened on 13 of 1,073
  priced buys on the model window (1.2%) and 2 of 378 on 2024-2026. On 8
  of the 13 the control did not reach its 1% dip either, so both filled
  at the close (g = 0). On the 5 that differ the guard gained +110 bp a
  buy on average, from +390 (PTC 2021-04-28) and +329 (KLAC 2024-07-16)
  to −175 (FTNT 2019-05-02) and −110 (CSCO 2026-08-12): two of the seven
  re-timed buys over the whole run lost. That is +0.016 bp of equity a
  session, a hundredth of the floor, positive at 18 of 20 offsets because
  the same handful of buys sits in every offset's book. Its deflated
  Sharpe of 0.88 at N = 3 is the expected-max hurdle being small (0.85 in
  t units) rather than evidence; at 457 trials it is 0.00.
- **By grade and by leg** (reported): E1 is negative on both A+ (−0.045 bp
  a session, 628 buys) and A (−0.030, 463), and its loss sits in the
  entries (−0.132 bp a session, t −1.05; −27.6 bp a re-timed buy) while
  adds (+0.020, t 1.32) and retries (+0.037, t 1.0) are flat. E2 is the
  same shape: entries −0.092, adds +0.005, retries +0.053. New positions
  are the buys a wider threshold most often leaves to the close.
- **Where the fills land.** The control's dip fills are front-loaded: 119
  of 443 at the first bar, 55 at the second, 43 at the third; 56% in the
  first hour (four bars). E1's are the same shape (109, 56, 35, 39, 26). E2's are
  spread across the day (12, 18, 14, 7, 13, ...), the one-sigma level
  being reached by a slow slide as often as by an opening flush.
- **The oracle.** The lowest bar close of t+1 is 119 bp below the control
  fill on average (130 on 2024-2026); over five sessions, 343 (439). No
  candidate captures any of it: −2%, −2% and 0%.
- **Next-bar** (the robustness run, fills at the following bar's open)
  changes nothing: −0.06, −0.03 and +0.02 bp a session.
- **Drift.** No candidate waits past t+1, so the drift adjustment is
  exactly zero and criterion 5 reads as criterion 1 (7.93 bp a session of
  A/A+ drift on the model window and 18.37 on 2024-2026 are recorded, and
  applied to a wait of 0).

## What it means for the board

- The operator's objection was that a hard-coded 1% cannot be right when
  names move 5-7% on some days. Measured on the book's own buys it is:
  the days a name moves 5% red are the days the 1% dip fills in the
  first bar, and scaling the threshold to the name's volatility gives
  those fills up. The tighter half-sigma threshold on calm names buys the
  same bar or a shallower one.
- Not chasing a gap-down is the one candidate with a mechanism, and it
  fires on 1% of buys with a sample of seven differing fills over ten
  years, two of which lost. Nothing can be decided from that, and the
  criteria say so. It could be re-registered if the book ever trades
  names where 2σ gaps are common; on this universe it is not worth a rule.
- The board's rule stands: a BUY fills in the next session by
  `dip_or_close` at the fixed 1%. No change is proposed.

## Disclosed

- The build (`fe6fa36d`) was committed and the unit gate passed on it
  (8,200 passed, 70 skipped, 6 xfailed, 05:17-05:23Z) before the study
  ran at 05:25Z. No number was read before the run; nothing was tuned
  after it.
- The plan's "conventions in `stage4_labels`" became their own module,
  `backend/market/adaptive_entry.py`, reusing `stage4_labels`' series,
  `cube_scale` and `gain` and `fill_timing`'s level fill rather than
  editing the stage-4 module; `stage4_orders.run_control` and
  `run_offsets` gained an optional `allocator` so the study runs under
  `graded-equal-weight/5` as stage 5 did (policy_v4 stays their default).
- The dip levels are multiples of t+1's own open, so they are compared on
  the raw bars and the fill scaled by `cube_scale`; the gap guard reads
  t+1's open and t's close both on the adjusted basis (a split between t
  and t+1 is no gap, tested).
- The oracle is reported twice: the lowest bar close of session t+1 (what
  a same-session rule could at most capture; the capture shares above
  read against it) and stage 4's five-session one.
- The EDGAR records `market_stage4_decisions.load_inputs` also loads are
  not read by this study.
- Every buy at the median offset, its date, weight, detail and grade, the
  control fill, and per candidate its fill, g (bar-close and next-bar) and
  flags, is in the payload's `rows` block, so any figure above can be
  recomputed; `adaptive_entry_check.py` does so.
