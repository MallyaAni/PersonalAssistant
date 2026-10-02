# Peer-cluster exposure cap (R1): limit how much of the book sits in one group of stocks that move together. Pre-registration (2026-10-02)

**Status: registered before any code or number.** Nothing in this note was
chosen after reading a clustering, a cap or a curve on this book. The
method, the three arms, the criteria and the reporting are fixed here; the
build and the run follow on `research/cluster-cap`.

## The question

The book's worst drawdown is the one number no study has moved without
paying for it. At 25 bp, median of 20 offsets, `ew_graded_cap25` (the
`graded-equal-weight/5` arm) has a worst drawdown of −45.5% on 2016-2023
and −26.4% on 2024-2026 (B2's control, store of 2026-10-01):

- B1, volatility targeting of the book (`vol-target-results-2026-10-01.md`,
  `research/vol-target` at `e6ff1ee2`): RECORD at 20/25/30%. It cut the
  2016-2023 drawdown by 10-21 points but gave up 10-22 CAGR points on
  2024-2026 and barely moved that window's drawdown.
- B2, regime gross (`regime-gross-results-2026-10-01.md`, `7ee01cd0`):
  RECORD; the gate barely fired.
- Universe expansion (`universe-expansion-results-2026-09-30.md`) cut the
  drawdown by about 9 points and cost 13-28 CAGR points.

Those rules scale the whole book. The book's risk is not spread evenly: it
concentrates in groups of names that move together (on 2026-10-01 it held
COHR, AAOI, LITE, ANET and CIEN, all optical/AI networking). Does capping
the weight the book puts in any one group of co-moving names, with the
excess moved to names outside the group, lower the worst drawdown without
giving up the return? A cluster cap targets concentration directly; a
book-level volatility scale cannot.

## What is known before this note (disclosed)

- The peer groups (`backend/market/peer_groups.py`, `desk/sector-sells-live`
  at `8c3afd11`, `research/sector-sells-shared` at `ceb95096`; registered in
  `sector-sells-plan-2026-10-01.md`) compute, point in time, each name's 5
  most-correlated book members from 60-session residual-to-SPY returns.
  Their outputs have not been used as a sizing input anywhere. The 09-30
  case named in the question (COHR, AAOI, LITE, CIEN, FN expected to
  cluster) is an expectation from the names' business, not a reading of
  the matrix; no residual correlation on this book has been looked at for
  this note.
- `/5` holds every A/A+ point-in-time member at min(1/count, 25%), spare
  cash in cash (`policy_v5.py`). With four or more names the book is fully
  invested at equal weight, so a cluster's weight is its share of the
  names.
- Name-level volatility sizing lost (`vol-sizing-2026-09-27.md`), stops
  lost (`catastrophe-stop-2026-09-27.md`), B1 and B2 are RECORD. A cap that
  moves weight into other names keeps the book invested, so unlike B1/B2 it
  is not a cash rule except when no name outside the capped clusters has
  room.
- The 2020 and 2022 drawdowns were market-wide; redistributing into other
  names helps only when the capped cluster falls harder than the rest.

## The method, fixed now

At each session t on which the allocator is asked for targets (the
harness's rebalance clock; decided at t's close, filled at t+1's open, as
every arm here):

1. **The policy's targets.** w = the `/5` arm's targets at t
   (`market_pit_scorecard.graded_arm(0.25)`, which `policy_v5` reproduces
   to the bit). The target names are those with w > 0.
2. **The residual-correlation matrix, exactly as `peer_groups.py`.** For
   the target names: daily log returns of the adjusted closes over sessions
   t−59..t (closes t−60..t; `peer_groups.CORR_SESSIONS` = 60), each
   regressed on SPY's with an intercept (`peer_groups.residuals`), and the
   residuals correlated pairwise. A name with any missing return in the
   window, or zero residual variance, has no correlation and is a cluster
   of its own. Nothing after t's close is read; no sector label, theme or
   ticker enters.
3. **The clusters: average linkage cut at ρ\*.** Start with every target
   name its own cluster. Repeatedly merge the two clusters whose average
   pairwise residual correlation (over every pair with one name in each)
   is highest, as long as that average is ≥ ρ\*; ties go to the pair whose
   smallest panel column is smallest. Stop when no pair reaches ρ\*. Every
   merged cluster therefore has an average cross-correlation ≥ ρ\* between
   the two parts it was built from. (Average linkage, not connected
   components of a k-nearest-neighbour graph: components chain one strong
   pair to the next, and a cap on a chain is a cap on whatever the chain
   happened to touch.)
4. **The cap.** A cluster binds when its total weight exceeds C (with a
   tolerance of 1e-9). Then, in passes: every cluster that binds and is not
   yet capped is scaled pro rata to exactly C and marked capped; the weight
   removed, plus whatever an earlier pass could not place, is given to the
   names outside capped clusters, pro rata to their current weights, each
   held at the 25% name cap (a name that reaches 25% takes no more and the
   rest is shared among the others pro rata). A cluster that the added
   weight pushes over C binds in the next pass. The passes stop when no
   uncapped cluster binds. **Whatever cannot be placed goes to cash** (it
   earns nothing, as in every arm here). A cluster that does not bind is
   never touched, and a book on which no cluster binds is the policy's
   targets unchanged, to the bit.
5. Trades from the cap are the rebalance's own trades and pay the same
   cost (10 and 25 bp; the verdict reads 25 bp).

## The arms, fixed now

| Arm | Cap C | Threshold ρ\* |
|---|---|---|
| R1a | 35% | 0.6 |
| R1b | 50% | 0.6 |
| R1c | 35% | 0.5 |

**Null test:** C = 100% at ρ\* = 0.6 goes through the same path (the
matrix and the clusters are computed) and must reproduce the control to
the bit: every line's dates and daily returns, at two offsets and both
costs, and the full 20-offset payload's rows, paired evidence and curves
(the independent check asserts the latter).

## Criteria, fixed now

The control is `ew_graded_cap25` on the same store, sessions, offsets and
costs: the point-in-time rule line at 25 bp, median of 20 offsets.

- **REPLACES** if, on **both** windows (2016-2023 and 2024-2026), the
  median worst drawdown is at least **3 points** shallower than the
  control's **and** the median CAGR is no more than **1 point** below the
  control's (a CAGR gain is fine). This is S1g's drawdown criterion
  (`structure-rules-plan-2026-09-30.md`: 3 points on both windows at a
  CAGR inside 1 point), the cap being a drawdown rule allowed to win on
  drawdown.
- **RECORD: real but immaterial** if it does not replace, but on both
  windows the median worst drawdown is at least **1 point** shallower,
  the CAGR is no more than 1 point below, and the drawdown is shallower
  than the control's at **15 or more of the 20 offsets**.
- Anything else is **RECORD**.

Reported for every arm, deciding nothing: the paired daily difference
against the control at the median offset (mean bp a session, Newey-West t
at lag 20) on both windows; the offsets (of 20) at which the arm's CAGR is
above the control's, and at which its drawdown is shallower; the Sharpe;
the deflated Sharpe at the cumulative trial count with the across-arm
variance of the three registered arms' paired Sharpes; SPY and QQQ's CAGR,
worst drawdown and Sharpe beside the control on both windows.

Also reported, deciding nothing:

- **How often the cap binds**, per window, over every session of the
  point-in-time book (the targets the arm would set if asked that day): the
  share of sessions with a target book on which at least one cluster
  binds, the clusters capped, the weight moved out of capped clusters, the
  cash the cap leaves, the largest cluster's weight before and after, and
  the number of target names in clusters of two or more.
- **The clusters on 2026-09-30**, read only from the live store
  (`~/deploy/anios/data/market` on spark1): the record's `/5` targets for
  that session, the book panel as of that session, the clusters at
  ρ\* = 0.6 and 0.5 with each cluster's average residual correlation, and
  the capped targets of each arm. Sanity check, not a criterion: COHR,
  AAOI, LITE, CIEN and FN, where they are targets, are expected to fall in
  one cluster.

## Trials and prior

Three registered trials; cumulative **485 → 488** (sector sells S2
registered 482 → 485, the newest plan on any branch at this registration;
A4 insider stance 478 → 480 and tone expiry 480 → 482 before it).

Prior: **~20%** that an arm replaces, **~15%** real but immaterial. The
likely finding: the cap binds rarely in 2016-2023, when the A/A+ book is
broad, and often in 2024-2026, when it concentrates in AI/optical names;
the 2020 and 2022 drawdowns, being market-wide, move little; and the 2024-
2026 window, where the concentration earned the return, gives up CAGR.
R1a (35%) is the arm most likely to move the drawdown and the most likely
to cost return; R1b (50%) binds least.

## Order of work

1. This note, committed alone and pushed.
2. Build with tests on `research/cluster-cap` (from GitHub `main`; the
   peer-group module checked out unchanged from `desk/sector-sells-live`):
   the residual-correlation matrix and the clustering
   (`backend/market/cluster_cap.py`), the cap, the capped allocator, the
   scoring of the control and the arms on shared pricing, the null test,
   the verdict, the 09-30 cluster report (`backend/cli/market_cluster_cap.py`),
   and an independent check script. Tests: the clustering is point in time
   (prices changed after t leave t's clusters unchanged), the cap's
   arithmetic and redistribution on synthetic weights (sums, the name cap),
   the null identity, the CLI end to end on a tiny panel.
3. Unit gate on spark1; the run on spark1 (CPU, nice 19, outside market
   hours, `--root ~/deploy/anios/data/market`, 20 offsets): null test
   first, then the control and the arms, the verdict, the independent
   check, the 09-30 clusters.
4. Write-up and report. Nothing here changes the live book; a REPLACES
   would be a separate, registered live change.
