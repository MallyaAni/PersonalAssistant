# Universe-widening study: pre-registration — 2026-11-03

Status: **pre-registration**. Written and committed before the first run. This
is the study authorized by the milestone 3 decision of 2026-11-03, taken under
the owner's delegation of next steps. Research only: this note changes no live
rule, order, grade, prompt or risk dial, and prepares no release. Any install
is a separate release-ceremony action requiring the owner's explicit
authorization.

It follows `docs/research/universe-mandate-memo-2026-11-03.md` and milestone 3
of `docs/trading/PROGRAM-DIRECTION.md`. The memo established that the live book
is concentrated (85.1% IT eligible, 93.5% IT selected) while the honest
universe's A/A+ book is diversified (IT 31.0% of 84 names), and that the prior
utilities widening improved return and Sharpe but had a -42.05% worst
drawdown, beyond the -35% mandate. This study measures the installed `/3` on
both the honest universe and the live mandate, and the two candidate controls
the memo named.

## The question

On the honest S&P 500 point-in-time universe and on the live mandate, current
code, 25 bp, 20 start offsets, does the installed `/3` pass the program
objective and the -35% worst-offset risk mandate; do an IT sector cap at 50%
or 35%, or a strengthened volatility target, make it pass; and does widening
the live book with Utilities improve the live mandate enough to justify the
change?

The honest universe is the test. The live book is the mandate. A rule arm that
passes the honest test but whose live-mandate implementation fails the -35%
worst-offset mandate is not installable: it would not fix the book the program
actually runs.

## Fixed arms (no parameter search)

The arms are fixed before the run. There is no parameter search: the cap
levels 50% and 35% are the two levels already registered in the scorecard, and
the risk variant is a single fixed strengthening of the installed volatility
target. No other cap, target, floor, window or strength is tried.

| arm | universe | construction | purpose |
|---|---|---|---|
| H0 | honest S&P 500 PIT | installed `/3`: `leader_ewma_minA_floor50_live` | test reference; reproducibility anchor |
| H50 | honest S&P 500 PIT | `/3` + IT sector cap 50% | memo option 2 |
| H35 | honest S&P 500 PIT | `/3` + IT sector cap 35% | memo option 2 |
| HR | honest S&P 500 PIT | `/3` + volatility target 0.20 (floor 0.50) | memo option 3 |
| L0 | live book (book history) | installed `/3` | live-mandate reference |
| LU | live book + Utilities | installed `/3` | memo option: widen the mandate |

Construction notes:

- **H0** is the scorecard arm `leader_ewma_minA_floor50_live`, which is the
  installed `/3`: the A-or-better held set, equal slots, leader tilt 0.5 over
  63 sessions, EWMA-20 volatility target 0.25 with exposure floor 0.50, 25%
  per-name cap, live ordering, no P/E.
- **H50** and **H35** apply `point_in_time.group_capped_allocator` to the H0
  allocator with the scorecard's `_sectors()` labels and a group cap of 0.50
  or 0.35. The group cap scales the IT group down to the cap share of gross
  and leaves the difference in cash; it does not reallocate to other sectors.
  The 25% per-name cap is retained. This is the installed rule plus one
  concentration control, not the older `ew_graded_leader_25_sector50/35`
  arms, which use the scorecard ordering and a different cap placement.
- **HR** is a local factory that copies the live ordering and passes
  `target=0.20` to `leader.leader_weights`, with `floor=0.50` unchanged. It
  differs from H0 only by the volatility target. The floor is not raised:
  a higher floor works against the drawdown goal, and changing two parameters
  at once would not isolate the effect.
- **L0** is H0's allocator on the broad report restricted to the live book's
  dated membership history (`backend/market/data/membership_history.csv`).
  The live book history has 110 intervals across 109 tickers; the current
  mask at 2026-10-30 is the 94-name eligible book. The 27 book names outside the S&P 500 (ALAB,
  CRWV, TSM, TLN and others) are in the broad panel through the overlay and
  in the book history; they are eligible in L0 and LU.
- **LU** is H0's allocator on the broad report restricted to the book history
  plus the S&P 500 Utilities-sector members not already in the book history.
  The current Utilities sector has 31 members; CEG and VST are in the book
  history, so the widening set is 29 names (30 intervals, because one name
  has two dated intervals). The custom history is the book history rows plus
  the S&P 500 history rows for those 29 names; no ticker has overlapping
  intervals. The widening set is the current Utilities
  sector, not the prior memo's nineteen regulated utilities, whose exact set
  is not enumerated in `book_sides`; the results note that difference.

The custom membership files are built by the study script from the two
committed histories and the universe's current sector labels. They are
research artifacts under `~/dsv41/universe/`, not live data.

## Data and fixed settings

- Store: the read-only 2026-10-30 vintage view
  `/home/animallya96/dsv41/universe/store_2026-10-30`, 2,964 sessions. The
  live store has advanced; the vintage view is the same one the ablation used
  and is required by the reproducibility anchor.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1).
- Honest membership: `~/dsv41/universe/sp500_membership_history.csv` (dated,
  no survivorship).
- Live-book membership: `backend/market/data/membership_history.csv`.
- Costs: 10 and 25 bp; the gate is 25 bp.
- Offsets: 20. Seed: 20261102. Bootstrap: month-block, 2,000 draws, 95%.
  HAC: Newey-West, lag 20.
- Windows: all sessions is the gate; 2016-2023 and 2024-2026 are reported and
  never tuned on.
- Code revision: the revision at the first run, recorded in the results.

## Reproducibility anchor

H0's all-window, 25 bp median CAGR must equal
`0.13275424766467725` (the `/3` control from
`simplicity-ablation-results-2026-11-03.md`). If it does not, stop and
investigate before reading any arm. The live-store one-session advance and
historical adjusted-close revisions are the known cause of prior mismatches;
the vintage view is used to avoid them.

The L0 and LU arms have no prior payload and no anchor. Their base is the
same allocator on a different membership mask; the anchor is H0.

## The decision rule (pre-registered)

All readings are at 25 bp, all sessions, medians across the 20 offsets. The
paired tests are daily differences at the median offset (offset 10, the
convention of the prior studies), reported as mean bp/day, Newey-West t at
lag 20, and a month-block bootstrap 95% interval.

**Program objective (research gate).** An arm passes the objective if all of:

- median Sharpe at least 1.00;
- median CAGR above SPY's median CAGR on the same sessions and cost;
- median drawdown no deeper than -35.00%.

**Live risk mandate.** An arm passes the live mandate if its worst-offset
drawdown is no deeper than -35.00%. This is the direction doc's resolution:
the research gate reads the median across offsets; the live mandate reads the
worst offset.

**Turnover constraint.** A candidate must not increase turnover against its
reference (H0 for the honest arms, L0 for the live arms). The program's 2x
target is already violated; a candidate that increases turnover is not
installable.

**Passing candidate.** A rule arm is a passing candidate only if:

1. it passes the program objective;
2. it passes the live risk mandate; and
3. its turnover is not higher than H0's.

If no rule arm passes all three, the study verdict is **FAIL**: keep `/3`
live, keep the AI/software mandate, and move to milestone 4 (code and branch
hygiene). If a rule arm passes, the study verdict is **PASS** and the program
prepares that arm for the release ceremony. The install candidate is the
passing rule arm **on the honest universe**; widening the mandate to that
universe is part of the install, because the tested universe is the universe
the rule would run on. The study does not install; the owner authorizes the
release, and the forward record restarts under the new version.

The live arms are descriptive, not candidates: L0 measures the installed
`/3` on the current mandate, and LU measures the partial Utilities widening.
Neither is the honest test, so neither can pass this study's gate. LU is the
memo's partial-widening option: if it passes the live risk mandate while the
honest rule arms fail, the study reports that a mandate-only widening is
available, but the program does not prepare it under this study, because the
honest test still fails. The owner may direct a separate mandate-only
decision.

**What counts as better.** The study is not a horse race. An arm that passes
the objective and the live mandate is a candidate even if its CAGR is lower
than another arm's, because the objective is the gate. A higher-CAGR arm that
fails the -35% worst-offset mandate is not a candidate. The prior utilities
measurement is the precedent: better return and Sharpe, but beyond the
drawdown mandate, so not installable.

## Reported diagnostics

For every arm: median and worst CAGR, drawdown and Sharpe; offsets above SPY,
above QQQ and above equal-weight PIT; turnover; the full objective flags; the
sub-periods. Paired against the reference: mean bp/day, HAC t, bootstrap 95%,
PSR. The deflated Sharpe is descriptive and is not used to rescue a result.
The trial count is six arms; no parameter was searched.

## Limitations

- GICS sector labels are current, not point-in-time, the same limitation as
  the prior sector studies.
- The live book's history is the mandate's membership, not the S&P 500 PIT
  membership. L0 and LU are mandate backtests, not honest-universe results.
- The 27 book names outside the S&P 500 are in the broad panel through the
  overlay; their bars and grades are the broad report's, not the desk book
  panel's. L0 is therefore a broad-panel reproduction of the live mandate,
  not a rerun of the desk book backtest.
- The widening set is the current Utilities sector (29 names not already in
  the book history), not the memo's nineteen regulated utilities. The prior
  measurement is cited as prior evidence and is not re-run.
- The sector cap scales the IT group down and leaves cash; it does not
  reallocate to other sectors. Its effect on CAGR is therefore a cost, and
  its benefit is concentration reduction, which the drawdown and the actual
  portfolio sector weights measure.
- The risk variant is one fixed strengthening (target 0.20), not a search.
  A failure does not prove no risk overlay can pass; it proves this one does
  not.
- The A/A+ equal-weight counts in the memo are not the rule's actual
  portfolio weights. This study measures the rule's actual weights through
  its performance and the sector-cap arms, but it does not report a separate
  time series of portfolio sector weights unless the payload provides one.

## Ledger entry

| date | question | verdict | live change | evidence |
|---|---|---|---|---|
| 2026-11-03 | Does widening the universe, an IT sector cap, or a stronger volatility target pass the objective and the -35% mandate? | **pre-registered; run pending** | none | this note |

## Change log

- **2026-11-03:** created before the first run. Six fixed arms, the objective
  and live-mandate gates, the turnover constraint, the H0 reproducibility
  anchor and the no-parameter-search constraint. No live change.
