# Universe/mandate memo — 2026-11-03

Status: **canonical memo for milestone 3**. This is an owner decision
document, not a pre-registration and not an experiment. It changes no live
rule, order, grade, prompt or risk dial, and prepares no release. The live
mandate changes only through a release ceremony the owner authorizes.

**Decision required: keep the AI/software mandate, widen with a sector cap,
or widen with a risk overlay. The evidence favors widening, but the prior
widening measurement does not meet the -35% drawdown mandate, so widening
alone is not a passing configuration. The program recommends keeping `/3`
live, continuing the forward record, and pre-registering a universe-widening
study before any install.**

## The question

The installed rule is grade-led: it holds A/A+ names and sizes them. On the
honest S&P 500 point-in-time universe that selection is diversified. The live
book is not: it is an AI/software book by decision, defined in
`backend/market/universe.py` by `book_sides`, and its concentration is the
proximate cause of the recent paper-account drawdown. The sector-flow and
QQQ-brake study already established that an overlay on the narrow book cannot
diversify it. The remaining question is the mandate itself.

## The live book

Source: `data/market/desk/asof=2026-10-30/desk.json`, the last complete desk
record before the `/2` and `/3` installs. That record is policy
`grade-led-leader-weight/1`; `/2` changed the hold rule and `/3` removed the
P/E-history tilt, but neither changed the mandate. The first `/3` nightly is
2026-11-03 19:30 ET and the `/3` forward record has zero verified sessions.

| live book measure | value |
|---|---|
| eligible book | 94 names |
| Information Technology | 80 (85.1%) |
| Industrials | 9 (9.6%) |
| Utilities | 2 (2.1%) |
| Communication Services | 2 (2.1%) |
| Consumer Discretionary | 1 (1.1%) |
| Financials, Health Care, Energy, Materials, Real Estate, Consumer Staples | 0 |
| grades | A+ 2, A 6, B 30, C 56 |
| A/A+ names | 8, **all Information Technology** |
| selected target book | 12 names, 50% gross |
| selected target weights | 46.75% IT, 3.25% Industrials (93.5% / 6.5% of the invested book) |
| broker positions | 11 names: 10 IT + GEV (Industrials) |
| broker equity / cash | $84,166.47 / $43,911.58 (52.2% cash) |
| broker position grades | A+ 2, A 5, B 4 |

The concentration appears at every level: the eligible book is 85.1% IT, the
selected target book is 93.5% IT by weight, and the funded account is 10 of
11 names IT. The remaining 82 eligible names carry zero target weight; the
book's breadth is not the book's exposure.

The recent paper account is the concentration, not the regime: 11
concentrated AI-hardware positions, -15.83% over 37 sessions against QQQ's
-3.86%, with a -21.36% maximum drawdown. The policy at the time was `/1`
(`docs/research/sector-flow-overlay-results-2026-11-02.md`).

## The honest universe

Source: the broad report on the 2026-10-30 vintage
(`~/dsv41/universe/store_2026-10-30`), regraded with the installed analyst
votes (`value` 3, `fundamental` 1, `technical` 1, `sentiment` 1), restricted
to the dated S&P 500 point-in-time membership
(`~/dsv41/universe/sp500_membership_history.csv`). This is a report read, not
a new scorecard run.

At 2026-10-30 the membership file has 502 dated members; five (FLT, ILMN, P,
RE, SATS) have no bars in the panel and are excluded, leaving **497 eligible
members across eleven sectors**:

| sector | members |
|---|---:|
| Industrials | 83 |
| Financials | 76 |
| Information Technology | 73 |
| Health Care | 59 |
| Consumer Discretionary | 47 |
| Consumer Staples | 33 |
| Utilities | 31 |
| Real Estate | 30 |
| Materials | 25 |
| Energy | 21 |
| Communication Services | 19 |

Grades: **A+ 15, A 69, B 120, C 293**. There are **84 A/A+ names**, and they
are diversified:

| sector | A/A+ names | share of the A/A+ book |
|---|---:|---:|
| Information Technology | 26 | 31.0% |
| Health Care | 14 | 16.7% |
| Financials | 11 | 13.1% |
| Industrials | 9 | 10.7% |
| Energy | 6 | 7.1% |
| Consumer Staples | 5 | 6.0% |
| Materials | 3 | 3.6% |
| Consumer Discretionary | 3 | 3.6% |
| Communication Services | 3 | 3.6% |
| Utilities | 2 | 2.4% |
| Real Estate | 2 | 2.4% |

Information Technology is the largest sector at 31.0% of the equal-weight
A/A+ book; the other ten sectors hold 69.0%. Over the trailing 252 sessions
the picture is stable: an average of 493.3 eligible members and 75.6 A/A+
names per session; the average A/A+ sector weights are IT 27.8%, Industrials
15.5%, Financials 13.5%, Health Care 10.8%, Utilities 7.2%, Energy 6.4%,
Consumer Discretionary 5.7%, Materials 4.7%, Consumer Staples 4.3%, Real
Estate 2.6% and Communication Services 1.5%. The average IT share of the A/A+
set is 27.7%, and **no session in the trailing year had an all-IT A/A+ set**.

## The comparison

| sector | honest A/A+ book (84 names, equal weight) | live eligible book (94 names, by count) | live selected book (50% gross) |
|---|---:|---:|---:|
| Information Technology | 31.0% | 85.1% | 93.5% |
| Health Care | 16.7% | 0 | 0 |
| Financials | 13.1% | 0 | 0 |
| Industrials | 10.7% | 9.6% | 6.5% |
| Energy | 7.1% | 0 | 0 |
| Consumer Staples | 6.0% | 0 | 0 |
| Materials | 3.6% | 0 | 0 |
| Consumer Discretionary | 3.6% | 1.1% | 0 |
| Communication Services | 3.6% | 2.1% | 0 |
| Utilities | 2.4% | 2.1% | 0 |
| Real Estate | 2.4% | 0 | 0 |

The rule is not the source of the concentration. The same grade-led selection
that would hold 84 A/A+ names across eleven sectors on the honest universe
holds 8 A/A+ names, all IT, inside the live mandate. The mandate filters the
selection; it does not diversify it.

## The widening evidence

`backend/market/universe.py`'s `book_sides` records the prior measurement:

> Restoring all nineteen measured better: 38.45% a year at Sharpe 1.247 and
> -42.05% against 34.12% at 1.178 and -42.19% over twenty start phases, and
> 49.80% against 47.43% from 2021 at an unchanged Sharpe for 2.8 points more
> drawdown.

Restoring the nineteen regulated utilities therefore improved full-sample
CAGR by 4.33 points and Sharpe by 0.069, with a worst drawdown 0.14 points
shallower. From 2021 it added 2.37 CAGR points at an unchanged Sharpe for 2.8
points more drawdown. It is better on return and Sharpe, but **both
full-sample worst drawdowns are beyond the -35% live risk mandate**, and the
recent window gives back drawdown. It is a backtest, not a live result, and it
is evidence about return and Sharpe, not a passing configuration. The memo
cites it; it does not re-run it.

The book was deliberately kept AI/software. `book_sides` says the gate runs
before the themes are read, so a power name joins only by being listed by
hand; the six merchant/nuclear power and electrical-equipment names are in,
the nineteen regulated utilities are out. That is a mandate decision, not a
research result, and it is the owner's to change.

## Options

### Option 1 — keep the AI/software mandate

No live change. The `/3` forward record continues and the 252-session review
judges it. The live book remains a deliberate single-sector bet: 85.1% IT
eligible, 93.5% IT selected. The honest-universe scorecard remains the test;
the live book remains the mandate. Cost: the live implementation may fail the
objective for mandate reasons, and the recent drawdown is the evidence.
Benefit: no new complexity, the mandate is deliberate, and the forward record
is the arbiter.

### Option 2 — widen with a sector cap

Widen the eligible book to the honest S&P 500 point-in-time universe (or add
the six missing sectors) and cap Information Technology at 50% or 35% of the
book. This is a universe plus rule change: it needs a pre-registered study on
the honest universe and a release. The scorecard already has sector-cap arms
(`ew_graded_leader_25_sector50`, `ew_graded_leader_25_sector35`). The
direction doc records that the static sector cap never binds on the honest
universe, but this memo's A/A+ counts are equal-weight and do not prove the
rule's actual portfolio weights, so the study must measure them. The cap is
primarily a live-mandate control. Trade-off:
it forces diversification and may lower CAGR; the cap's effect on the widened
live book is untested; the -35% drawdown mandate still needs checking. The
utilities measurement suggests widening improves return and Sharpe but does
not by itself fix the drawdown.

### Option 3 — widen with a risk overlay

Widen the eligible book and keep or strengthen the volatility target and
exposure floor. The current rule already has a 0.25 annualized EWMA-20
volatility target and a 0.50 exposure floor; the ablation kept both because
removing them breached the pre-registered tolerances. The utilities
measurement's -42% drawdown suggests a risk overlay is needed to meet the
-35% mandate. This needs a pre-registered study; the program's rule is that a
new overlay must earn its complexity, and the ablation's lesson is to remove
overlays that do not pay. Trade-off: more complexity, and a wider universe
may change the volatility target's and floor's effect.

## Recommendation

The evidence favors widening the mandate. The honest universe's A/A+ book is
diversified (IT 31.0%, ten other sectors 69.0%), the live book is 85.1% IT
eligible and 93.5% IT selected, and the recent drawdown was in the
concentrated names. But the prior utilities measurement's -42% worst
drawdown is beyond the -35% mandate, so widening alone is not a passing
configuration and must not be installed on that backtest alone.

The program recommends:

1. Keep `/3` live and let the 252-session forward record run. No interim live
   change.
2. Pre-register a universe-widening study that measures both the honest
   universe (the test) and the live mandate (the book): (a) the installed
   `/3` on the honest S&P 500 point-in-time universe, (b) a sector cap at 50%
   and 35% on that universe, (c) a strengthened volatility target/floor
   variant on that universe, (d) the installed `/3` on the 94-name live book,
   and (e) the installed `/3` on the live book widened with the Utilities
   sector, all with the -35% worst-drawdown gate, the full objective and
   turnover reported.
3. Install only if that study passes, through the release ceremony. If it
   does not pass, keep the mandate and record why.

The owner decides whether to authorize the study and, later, the install. The
memo itself makes no live change.

## What this memo does not do

- It does not change the live rule, the live universe or the forward record.
- It does not re-run the utilities measurement or any overlay; the widening
  evidence is the existing `book_sides` measurement.
- It does not claim widening is a passing configuration; the -42% drawdown is
  beyond the -35% mandate.
- It does not treat the 2026-10-30 desk record as `/3`; it is the last `/1`
  record. The `/2` and `/3` installs changed the hold rule and removed the
  P/E tilt, not the mandate. The `/3` forward record has zero verified
  sessions.
- It does not claim GICS sectors are point-in-time; current labels are used,
  the same limitation as the prior sector studies.
- It does not treat the broker snapshot as a stable estimate; it is one
  session's positions at 2026-10-30.
- The honest A/A+ sector weights are equal-weight counts of the graded names;
  the rule's volatility target, exposure floor and leader tilt change the
  actual weights. The comparison is about the selection's breadth, not the
  rule's final sizing. The study must measure the rule's actual portfolio
  sector weights, because a leader tilt toward high-return names can
  concentrate the portfolio more than the A/A+ counts suggest.

## Data and reproducibility

- Payload: `~/dsv41/universe/universe_mandate_memo.json`.
- Script: `~/dsv41/universe/universe_mandate_memo.py`.
- Store: `~/dsv41/universe/store_2026-10-30` (2,964 sessions, as-of
  2026-10-30).
- Membership: `~/dsv41/universe/sp500_membership_history.csv`.
- Votes: `value` 3, `fundamental` 1, `technical` 1, `sentiment` 1.
- Live record: `data/market/desk/asof=2026-10-30/desk.json`.
- Code: `8ef42eb2`; the only change since `c2792219` is a vision test, not
  the trading path. The memo changes no code.
- The honest-universe composition is a report read; no scorecard arm was
  run and no parameter was searched.

## Ledger entry

| date | question | verdict | live change | evidence |
|---|---|---|---|---|
| 2026-11-03 | Should the live book stay AI/software-concentrated or widen? | **memo written; owner decision required**; the honest A/A+ book is diversified (IT 31.0%, ten other sectors 69.0%), the live book is 85.1% IT eligible and 93.5% IT selected, and the prior utilities widening improves return and Sharpe but is -42.05% worst drawdown, beyond the -35% mandate | none | this memo |

## Change log

- **2026-11-03:** created. Records the live-book concentration, the honest
  universe's diversification, the prior utilities widening evidence, the
  three options and the program recommendation. No live change.
