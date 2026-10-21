# Does the sizing-and-timing layer earn its place? What the installed artefacts already say

Asked by the owner on 2026-10-21 ("do you need to backtest the sizing and
action model to ensure its a good and reliable system?"). Measured on spark1
from the installed history artefact
`data/market/desk/strategy-model-history/cc490399…` (policy
`grade-led-learned-sizing/1`, replayed 2018-02-01 → 2026-10-19 with the
holding head published 2026-10-04 and the timing heads frozen through
2026-08-17), the store's adjusted closes and `benchmarks.load_benchmark`
(QQQ, SPY, 10 bp). Scripts: `~/dsv41/brief/curve_vs_bench.py`,
`~/dsv41/brief/ew_baseline.py` on spark1; results in
`~/dsv41/brief/curve_vs_bench.json`.

## What was compared

* **policy** - the artefact's own portfolio curve (`manifest.curve`): the
  current grade direction, the learned holding size, the probabilistic
  timing, costs and funding rules, replayed over the past.
* **EW A/A+** - the same grades (the artefact's `grade_rows`, forward-filled),
  no learned layer at all: equal weight across every name graded A or A+ at
  the prior close, rebalanced daily, 10 bp a side on turnover, fully
  invested when any name is eligible. This is the hurdle the sizing and
  timing layers must clear, because it is what the desk would do with the
  grades and nothing else.
* **QQQ, SPY** - funded the way the ledger funds, on the same sessions.

All three use today's 94-name book. That universe was chosen with hindsight;
the point-in-time scorecard of 2026-09-26 put the rule's whole lead over QQQ
down to that choice (rule / point-in-time ≈ QQQ, t -0.28; see
`pit-scorecard-2026-09-26.md`). So the absolute levels below are not
achievable returns; only the *differences between lines on the same
universe* say anything about the layers being tested.

## Result

| window | policy | EW A/A+ | QQQ | SPY |
|---|---|---|---|---|
| 2019-03-04 (first trade) → 2026-10-19 | CAGR 49.6% · DD -48.6% · Sharpe 1.16 | CAGR 47.0% · DD -43.3% · Sharpe 1.24 | 21.2% · -35.1% · 0.92 | 15.9% · -33.7% · 0.86 |
| 2024-01-01 → | 96.6% · -47.9% · 1.55 | 90.3% · -41.9% · 1.70 | 23.8% · -22.8% · 1.13 | 20.4% · -18.8% · 1.28 |
| in-sample, ≤ 2026-08-17 | 45.6% · -48.6% · 1.15 | 48.5% · -43.3% · 1.30 | 19.6% · -35.1% · 0.87 | 14.4% · -33.7% · 0.80 |
| out-of-sample, 2026-08-17 → 2026-10-19 (45 sessions) | total -12.2% · DD -15.2% | total -14.8% · DD -19.2% | -1.5% · -6.6% | -0.6% · -2.5% |

Read plainly:

1. **The learned sizing and timing add nothing measurable over equal weight,
   even on the data they were fitted on.** In-sample the equal-weight line
   has the higher CAGR (48.5% vs 45.6%), the shallower drawdown and the
   higher Sharpe (1.30 vs 1.15). The layers' one visible effect is a deeper
   drawdown. A model that cannot beat equal weight in-sample will not do so
   out of sample.
2. **The only out-of-sample window is 45 sessions and negative for both
   lines** (-12.2% sized, -14.8% equal weight, QQQ -1.5%). The sized line
   lost less than equal weight over those weeks, which is the one point in
   its favour, and it is far too short to mean anything: it is the names the
   grades picked that fell, not the sizing.
3. **The direction rule is the thing that has not been shown to work.** On a
   point-in-time universe the grade rule earns what QQQ earns and trails the
   equal-weight book of the names it could have held by about 7 CAGR points
   a year (2026-09-26 scorecard). Everything above that on the dashboard is
   the hindsight choice of the 94 names.

## What this means for the owner

The system is not yet shown to be good or reliable. The chart replay
validates the plumbing (the same code, no future prices) and now says so
in-sample; it does not validate the models, and the numbers that look
spectacular come from the universe, not from the sizing or the timing. The
honest expectation for the live account is "about QQQ, with more drawdown",
until a test on a point-in-time universe with the models refitted only on
past data says otherwise.

## This agrees with what was already measured on the point-in-time book

`pit-arms-2026-09-26.md` scored the same question on the universe the desk
could actually have held (2016-2023, 25 bp, 20 offsets): equal weight across
every A/A+ name, fully invested (`ew_graded_full`), made 29.9% a year and was
ahead of equal weight of every member in 19 of 20 offsets (t +1.5); the rule
with its sizing layer made 14.4%; QQQ 18.6%. The conclusion there was the
same as here from the other direction: the grade selects a little, the
sizing built on top of it loses, and the learned rankers lose more. The
learned holding and timing heads installed since (October) were not in that
scorecard; the table above is the first look at them, and they do not change
the picture.

## What a real test of the new heads would be, and why it was not run tonight

A walk-forward test refits the holding head and the timing heads at each
month-end on data before that date, trades the next month with those heads,
and rolls - on the point-in-time universe, with the existing funded ledger,
costs and calendar. The timing heads were designed for exactly this
(monthly heads, 504-756 training sessions, ten-session maturity:
`joint-probability-timing-plan-2026-10-05.md`); the holding head's training
path (`market_adaptive_timing_sizing`, the v3 calibrated holding policy)
needs the same treatment. It is a multi-day job on these machines and it
belongs under the research protocol's registration rules
(`ml-forward-evaluation-spec.md`), not in a night. The two measurements
above already say what it would most likely find.

## The point-in-time scorecard, re-run tonight on data through 2026-10-20

`python -m backend.cli.market_pit_scorecard --root ~/deploy/anios/data/market`
for the frozen rule and with `--arm ew_graded_full`; payloads in
`docs/research/pit-scorecard-2026-10-21/`. Point-in-time book, 25 bp,
medians across 20 offsets, Newey-West t at the median offset:

| line | 2016-2023 CAGR | vs EW-PIT (t) | vs QQQ (t) | 2024-2026 | all | worst DD (all) |
|---|---|---|---|---|---|---|
| QQQ, funded | 18.6% | | | 22.9% | 18.9% | -35.1% |
| equal weight, every member (EW-PIT) | 27.7% | — | +3.4 bp/d (+2.72) | 25.9% | 24.8% | -37.9% |
| frozen rule (the desk's sizing layer) | 14.4% | -4.9 bp/d (-2.36) | -1.6 bp/d (-0.80) | 30.2% | 16.5% | -24.6% |
| **A/A+ equal weight, fully invested (`ew_graded_full`)** | **27.8%** | +0.9 bp/d (+0.67) | +4.3 bp/d (+2.25) | 36.0% | 27.2% | -45.8% |

Same shape as 2026-09-26 with three more weeks of data: the sizing layer
loses to the names it is allowed to hold (t -2.36) and does not beat QQQ;
owning every A/A+ name at equal weight is level with the whole book
(t +0.67, not distinguishable) and ahead of QQQ in 20 of 20 offsets
(t +2.25). The one thing the arm costs is drawdown (-45.8% at its worst
against QQQ's -35.1%): it is fully invested in a concentrated sector book.

## Recommendation

Validate the direction, not the sizing. The one arm that has passed its
gate on the point-in-time book is `ew_graded_full`: own every A/A+ name at
equal weight, fully invested, with the operator's hold limit as the only
parameter. Making it the installed sizing is a trading-economics change
that goes through the release approval
(`backend/cli/market_release_admission.py`), and it should be followed by
the same two things any policy needs: the dashboard showing the
point-in-time line beside today's-book line, and the paper account's own
forward record as the only out-of-sample evidence that counts.

## Sizing arms scored by gain against added drawdown (2026-10-21 morning)

The owner asked for the arm with the most gain for the least change in
worst drawdown, and whether equal weight is the best that can be done.
Three sizing families were scored on the same point-in-time book, the
same offsets and 25 bp, all holding every A/A+ name and nothing else:
equal weight (capped at 20%, and uncapped); equal risk (weights inverse
to each names trailing 63-session realised volatility, capped, with

## Sizing arms scored by gain against added drawdown (2026-10-21 morning)

The owner asked for the arm with the most gain for the least change in
worst drawdown, and whether equal weight is the best that can be done.
Three sizing families were scored on the same point-in-time book, the
same offsets and 25 bp, all holding every A/A+ name and nothing else:
equal weight (capped at 20%, and uncapped); equal risk (weights inverse
to each name's trailing 63-session realised volatility, capped, with
the excess in cash); and exposure control (the equal-weight book scaled
to a realised-volatility target of 0.30, 0.25 and 0.20 from the
basket's own trailing 63 sessions, never levered). The arms are
registered in `backend/cli/market_pit_scorecard.py`; results sit in
`~/dsv41/pit/pit_<arm>_20261021.json` on spark1 and are summarised by
`~/dsv41/pit/arms_summary.py`. "Worst DD" is the worst drawdown across
the 20 offsets; CAGR is the median.

| arm | CAGR 2016-23 | worst DD 2016-23 | CAGR all | worst DD all | Sharpe 2016-23 | offsets > QQQ |
|---|---|---|---|---|---|---|
| installed rule (`frozen rule`) | 14.4% | -34.0% | 16.5% | -34.0% | 0.94 | 0 |
| `ew_graded_voltarget_20` (vol target 0.20) | 21.2% | -34.1% | 19.5% | -34.1% | 0.99 | 20 |
| **`ew_graded_voltarget_25` (vol target 0.25)** | **23.3%** | **-35.0%** | **22.0%** | **-35.0%** | 0.96 | 20 |
| `ew_graded_voltarget` (vol target 0.30) | 24.5% | -39.7% | 23.4% | -39.7% | 0.95 | 20 |
| `risk_graded_20` (equal risk, 20% cap) | 24.3% | -45.2% | 23.9% | -45.2% | 0.92 | 20 |
| `risk_graded_full` (equal risk, uncapped) | 26.5% | -47.3% | 25.2% | -47.3% | 0.94 | 20 |
| `ew_graded_20` (equal weight, 20% cap) | 26.2% | -47.7% | 25.9% | -47.7% | 0.93 | 20 |
| `ew_graded_full` (equal weight, uncapped) | 27.8% | -48.8% | 27.2% | -48.8% | 0.95 | 20 |
| QQQ | 18.6% | -35.1% | 18.9% | -35.1% | | |

Read against the installed rule, the gain per point of added drawdown
has a clear knee at the 0.25 target: 0.20 buys +3.0 points of CAGR
(all window) for +0.1 of drawdown, 0.25 buys +5.5 for +1.0, 0.30 then
adds only +1.4 more for +4.7 more drawdown, and the uncapped equal
weight adds +10.7 for +14.8. Equal risk sizes do not help: the A/A+
names move together, so inverse-volatility weights only tilt the same
book and keep its drawdown. By the owner's rule the pick is
**equal weight across every A/A+ name, scaled to a 0.25 realised
volatility target**: within one point of the installed rule's worst
drawdown, a third more CAGR, ahead of QQQ in 20 of 20 offsets, Sharpe
no worse. Its one weak window is 2024-26, where the installed rule
(fitted through 2026-08-17, so in-sample there) returns 30.2% at -22.3%
against the arm's 27.0% at -32.2%; the paper account's forward record
is the only evidence that settles that. Installing it is a
trading-economics change through the release approval.

## Per-name price tilts on the chosen book (2026-10-21, 09:00 ET)

The owner asked whether a name should be bought more or less according
to where its price is. Three tilts were scored on the 0.25-target
equal-weight book (`point_in_time.graded_tilted_allocator`, arms
`ew_graded_<tilt>_25`): each reads the name's own last 63 sessions of
adjusted closes, turns that into a multiplier on the name's equal slot,
and the slots are renormalised, so the tilt reshares the book and
leaves the exposure to the volatility target. Pullback: up to 1.5x at a
full retreat from the window high. Trend: full slot above the window's
mean close, half below. Leader: the trailing-return rank among the held
names, from 1-strength for the weakest to 1+strength for the strongest.
Same scorecard, 25 bp, worst drawdown across 20 offsets.

| arm | CAGR 2016-23 | worst DD 2016-23 | CAGR all | worst DD all | Sharpe 2016-23 | 2024-26 CAGR | offsets > EW 2024-26 |
|---|---|---|---|---|---|---|---|
| `ew_graded_voltarget_25` (no tilt) | 23.3% | -35.0% | 22.0% | -35.0% | 0.96 | 27.0% | 13 |
| `ew_graded_pullback_25` | 23.4% | -35.0% | 22.1% | -35.0% | 0.96 | 27.3% | 13 |
| `ew_graded_trend_25` | 22.9% | -35.2% | 21.9% | -35.2% | 0.95 | 27.2% | 13 |
| `ew_graded_leader_25_s25` (strength 0.25) | 23.9% | -35.0% | 23.0% | -35.0% | 0.97 | 30.7% | 19 |
| **`ew_graded_leader_25` (strength 0.5)** | **24.5%** | **-35.9%** | **24.3%** | **-35.9%** | 0.98 | 31.8% | 20 |
| `ew_graded_leader_25_s100` (strength 1.0) | 24.9% | -42.1% | 24.8% | -42.1% | 0.96 | 37.0% | 20 |
| installed rule | 14.4% | -34.0% | 16.5% | -34.0% | 0.94 | 30.2% | |

Buying more on a pullback or only in an uptrend changes nothing at the
book level: the A/A+ names move together and the tilts wash out. Sizing
the relative leaders does not wash out, and the gain moves with the
strength (22.0 -> 23.0 -> 24.3 -> 24.8 CAGR) while the worst drawdown
stays at the untilted book's level until strength 0.5 and then jumps to
-42.1% at 1.0, where the weakest name gets nothing and the strongest
twice its slot. The knee is at 0.5. By the owner's rule the candidate
is therefore **equal weight across every A/A+ name, tilted 0.5x-1.5x by
trailing 63-session return rank, scaled to a 0.25 realised-volatility
target, never levered**: CAGR 24.3% at worst drawdown -35.9% against
the installed rule's 16.5% at -34.0%, ahead of plain equal weight in
20 of 20 offsets in 2024-26 and of the installed rule in that window
(31.8% vs 30.2%) where the installed rule is in-sample. Three settings
of one parameter are not a fit, but they are not forward evidence
either; the paper account's record after installation is.

Installing it: the admission CLI refuses a policy change by design and
the approval files are owner-written under the paper lock, so the
candidate is prepared as a reviewed patch set with the proposed
config/release/evidence text, for the owner to install by hand as on
2026-10-13.

## The candidate under its own cap, and a sector cap (2026-10-21, 10:50 ET)

Two more arms answer two questions the candidate raised. First, the
leader-tilted book under the installed 25% per-name cap
(`ew_graded_leader_25_cap25`), which is what `grade-led-leader-weight/1`
would actually run: CAGR 23.0% at worst drawdown -35.0% (all window),
2016-23 23.6% at -35.0%, 2024-26 29.7% at -33.2%, Sharpe 0.98, ahead of
QQQ in 20 of 20 offsets. The cap costs 1.3 points of CAGR against the
uncapped arm and gives back 0.9 of drawdown. Those are the numbers the
release evidence cites.

Second, the owner asked whether the approach knows that names in one
sector move together. It does not model sectors; the only places
co-movement enters are the basket's realised volatility (the vol target
cuts the whole book when the names move together) and the leader rank,
which is relative within the book. A GICS sector cap was therefore
scored (`point_in_time.group_capped_allocator`, labels from the
constituent file with overlay names mapped to their theme's sector):
half of the book per sector gives 12.2% at -19.6%, a third gives 8.5% at
-14.1%, both at Sharpe 0.96-0.98, the same as the uncapped book. The A/A+
names are almost all Information Technology, so a sector cap holds
nothing else: it only moves the book into cash, which a lower volatility
target does with one parameter and no classification file. The sector
cap is not adopted.
