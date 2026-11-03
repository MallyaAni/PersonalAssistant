# Turnover diagnosis: results — 2026-11-03

Status: **canonical result** for the turnover diagnosis (milestone 2).
Research only: this note changes no live rule, order, grade, prompt or risk
dial. It prepares no fix and no release.

**Verdict: cadence is not the dominant source, and the pre-registered
20-session fix fails the gate. No fix is prepared.** Daily sizing on the
scorecard turns over 15.35x/year, only 1.82 times the 20-session arm (the
dominance rule needs more than 2.0x) and 51% of the live paper's 30.2x/year
(the rule needs at least 80%). The candidate 20-session arm fails the gate:
turnover is not halved (8.44x against the required 7.67x) and its median
drawdown is 7.69 points deeper than the live-like arm (-34.39% against
-26.70%), 6.69 points beyond the 1.00-point tolerance. The live ledger's
largest grouped reason is grade-driven exits and redeploys (27.7% of the
first 37 sessions' filled notional), followed by the initial equal-weight
build (19.9%), early analyst-stance actions (16.9%) and sizing adjustments
(15.1%); FOMC actions are 7.7%. The rule's own position management, not the
cadence alone, is where the live turnover comes from. The next diagnosis or
fix is a separate pre-registration.

This is the result of
`turnover-diagnosis-preregistration-2026-11-03.md`, committed at `f7d93c6a`
before the first run.

## What was run

- Store: a read-only view of `/home/animallya96/deploy/anios/data/market`
  containing only partitions dated on or before 2026-10-30
  (`~/dsv41/universe/store_2026-10-30`). As-of 2026-10-30, 2,964 sessions.
- Report: `market_universe_hindsight_research.broad_report(store)`, regraded
  with the installed analyst votes (`value` 3, `fundamental` 1, `technical` 1,
  `sentiment` 1), restricted to the honest S&P 500 point-in-time membership
  (`~/dsv41/universe/sp500_membership_history.csv`).
- Allocator: the installed `/3` allocator
  (`leader_ewma_minA_floor50_live`), fixed cadences 1, 5, 10, 20 and 63
  sessions, `use_exits=False`.
- Costs: 10 and 25 bp; the gate is 25 bp. Offsets: 20. Seed: 20261102.
  Bootstrap: month-block, 2,000 draws, 95%. HAC: Newey-West, lag 20.
- Code revision: `2c2e404005452369db502b9cabfbddf6e14360fc`. The
  pre-registration was committed at `f7d93c6a`; the two commits between them
  (`076dda4b`, `2c2e4040`) touch only Scout routing files, not the trading
  path, so the study's code is the pre-registered code.
- Payloads: `~/dsv41/universe/turnover_diagnosis_summary.json` (the result);
  the partial checkpoints were removed after the run. The live-store reading
  from the first attempt is preserved as
  `~/dsv41/universe/turnover_diagnosis_current_store_2026-11-02.json`.

## Reproducibility

The first run used the live store, whose last complete session had advanced
to 2026-11-02 (2,965 sessions). The pre-registered `cadence_20` check failed
there (CAGR 0.132168571 against the expected 0.132754248), and the run
stopped before reading any arm; the reading is preserved but is not used for
any decision. The 2026-10-30 view is the same vintage the ablation used.

The first vintage run then reproduced CAGR, both drawdowns and turnover
exactly but reported Sharpe 0.8162 against the expected 0.8160719928, a
1.37e-4 gap. The cause is the Sharpe definition: `simulate.stats()` uses the
population standard deviation (`ddof=0`), while the scorecard's
`window_stats()` uses the sample standard deviation (`ddof=1`). The
pre-registered reference is a scorecard value, so the rerun reads Sharpe from
`scorecard.window_stats(result.returns)`. With that definition `cadence_20`
at 25 bp reproduces all five pre-registered values exactly:

| quantity | expected | actual |
|---|---:|---:|
| median CAGR | 0.13275424766467725 | 0.13275424766467725 |
| median Sharpe | 0.8160719928118282 | 0.8160719928118282 |
| median drawdown | -0.343922645227457 | -0.343922645227457 |
| worst drawdown | -0.3942116034315978 | -0.3942116034315978 |
| turnover at median offset | 8.43752949642906 | 8.43752949642906 |

The check passed before any other arm was read.

## The cadence table, 25 bp

All sessions, medians across the 20 offsets; turnover is read at the median
offset from the simulator's own metric. Performance is descriptive: the
cadence set is not a parameter search, and the best-performing cadence is not
selected.

| arm | CAGR | Sharpe | median drawdown | worst drawdown | turnover |
|---|---:|---:|---:|---:|---:|
| `cadence_1` (live-like daily sizing) | 12.3986% | 0.800810 | -26.7002% | -26.8251% | 15.349946x |
| `cadence_5` | 12.2478% | 0.783710 | -27.5749% | -30.3992% | 13.443758x |
| `cadence_10` | 12.8617% | 0.809507 | -29.7206% | -32.7190% | 10.981351x |
| `cadence_20` (installed reference) | 13.2754% | 0.816072 | -34.3923% | -39.4212% | 8.437529x |
| `cadence_63` | 13.0297% | 0.755333 | -39.4881% | -41.4661% | 5.050562x |

The ordering is not monotone in performance. At 25 bp the 20-session arm has
the highest CAGR; daily sizing has the shallowest drawdown but the lowest
CAGR. The pre-registration fixed the candidate as the 20-session arm, not the
best row in this table.

## The cadence table, 10 bp

| arm | CAGR | Sharpe | median drawdown | worst drawdown | turnover |
|---|---:|---:|---:|---:|---:|
| `cadence_1` | 15.0130% | 0.941697 | -26.6243% | -26.7441% | 15.201776x |
| `cadence_5` | 14.6255% | 0.913659 | -27.4195% | -30.0837% | 13.359822x |
| `cadence_10` | 14.7398% | 0.911340 | -29.5642% | -32.5857% | 10.936306x |
| `cadence_20` | 14.7295% | 0.893041 | -34.2686% | -39.3406% | 8.421114x |
| `cadence_63` | 13.8725% | 0.796277 | -39.4840% | -41.4653% | 5.049384x |

At 10 bp the daily arm has the highest CAGR and Sharpe, which is why the
25 bp gate is the decision and the 10 bp table is reported, not selected on.

## Dominance checks (pre-registered)

The pre-registration declares cadence dominant only if both conditions hold.

| check | measurement | threshold | result |
|---|---|---|---|
| daily turnover more than twice the 20-session arm | 15.349946 / 8.437529 = 1.819 | > 2.0 | **fail** |
| daily turnover at least 80% of the live 30.2x | 15.349946 / 30.2 = 50.8% | >= 80% (24.16x) | **fail** |

`cadence_dominant` is false. The fresh live measurement below is about 32.6x,
whose 80% threshold is 26.1x; the daily arm fails that too, so the conclusion
does not depend on which live figure is used.

## Gate for the candidate fix, 25 bp

The pre-registered gate compares `cadence_20` (the fix) with `cadence_1` (the
live-like arm). It requires every check to pass.

| check | measurement | threshold | result |
|---|---|---|---|
| turnover at least halved | 8.437529 | <= 7.674973 (0.5 x 15.349946) | **fail** |
| median CAGR no more than 0.50 points lower | 13.2754% | >= 11.8986% | pass |
| median Sharpe no more than 0.03 lower | 0.816072 | >= 0.770810 | pass |
| median drawdown no more than 1.00 point deeper | -34.3923% | >= -27.7002% | **fail** (7.69 points deeper) |
| paired HAC t above -2.0 | 0.4235 | > -2.0 | pass |
| paired bootstrap 95% lower above -1.0 bp/day | -0.9973 bp/day | > -1.0 | pass |

The paired daily difference at the median offset (20-session minus
1-session), 2,964 sessions: mean **+0.2327 bp/day**, Newey-West t **0.4235**,
month-block bootstrap **-0.9973 to +1.1780 bp/day**, PSR **0.6807**. The fix's
mean daily difference is positive but not statistically significant; the
turnover and drawdown conditions fail independently of it. Gate pass is
**false**.

At 10 bp, descriptively: turnover 8.421114 against the 7.600888 halving
threshold (fail); CAGR 14.7295% against the 14.5130% floor (pass); Sharpe
0.893041 against 0.911697 (fail); median drawdown -34.2686% against -27.6243%
(fail); paired mean -0.1775 bp/day, HAC t -0.3274, bootstrap -1.3722 to
+0.7589 bp/day, PSR 0.3522 (the bootstrap lower bound also fails the -1.0
threshold). The fix is not non-inferior at 10 bp either.

## The live ledger decomposition

The live side is supporting evidence, not a gate, as pre-registered. The
source is the Alpaca paper account's filled orders (`orders_since` from
2026-08-15), matched to the stated reason in each nightly
`data/market/desk/asof=<date>/desk.json` record. The window is the account's
first 37 sessions, 2026-09-04 through 2026-10-27 on the panel calendar.

- Filled desk orders in the window: **140**; filled notional
  **470,080.06**.
- Average equity: **98,228.75** from the 33 nightly desk records in the
  window. Four sessions have no desk record (2026-10-12, 10-14, 10-15,
  10-16); the Alpaca portfolio-history average over the same dates is
  97,810.38, and using it gives 32.75x instead of 32.59x.
- Elapsed years: 37/252 = 0.146825.
- Annualized gross turnover: **32.59x/year** (32.75x with the history
  equity). The full ledger through 2026-11-02 is 159 filled orders and
  511,083.26 of filled notional; the reason shares below are similar.

The prior note's live measurement was 430,776.63 of filled notional over an
average equity of 97,239.94 in 0.1468 years, or 30.2x/year. That exact figure
is not reproducible from the current ledger: the fresh window total is
470,080.06, a difference of 39,303.43 (8.4%). The ledger has no missing fills
in the window that explain the gap, and the difference is consistent with a
different query cutoff or price source in the earlier note. The magnitude is
confirmed (32.6x against 30.2x), the pre-registered 30.2x is retained for the
dominance test, and the conclusion is unchanged either way.

Grouped by the reason the desk recorded, first 37 sessions:

| source | filled notional | share | orders |
|---|---:|---:|---:|
| grade-driven exits and redeploys | 130,396.87 | 27.74% | 40 |
| initial equal-weight build (`rebalance to ...`) | 93,391.01 | 19.87% | 18 |
| early analyst-stance actions (`Own:` / `Wait:` / `Avoid:`) | 79,458.45 | 16.90% | 21 |
| leader/learned sizing adjustments | 70,765.26 | 15.05% | 10 |
| FOMC risk reduction and restoration | 36,348.62 | 7.73% | 17 |
| redeploy cash beyond the buffer | 31,388.32 | 6.68% | 11 |
| unmatched or ambiguous | 24,631.81 | 5.24% | 18 |
| deferred buy (cash shortfall) | 2,711.58 | 0.58% | 4 |
| price-entry breakout | 988.14 | 0.21% | 1 |

"Grade-driven exits and redeploys" groups `Grade below A; exit`,
`graded B/C; the desk wants the money elsewhere`, `redeploying a downgraded
name` and `leaves the book`. The initial build and the early analyst-stance
actions are one-time: they are the account being put into the book from cash
in the first two weeks, not a recurring turnover source. Excluding them, the
recurring rule-driven sources are grade exits and redeploys (27.7%), sizing
adjustments (15.1%), FOMC actions (7.7%) and cash redeployment (6.7%), about
57% of the window's filled notional. The largest single category is the
grade-driven exit/redeploy group.

Matching and its limits:

- 71 fills matched by exact `client_order_id`; 70 matched by
  `(session, side, symbol)` from a desk record that carried no id; 18
  remained unmatched or ambiguous (4.8% of notional). The ambiguous keys are
  sessions where the desk record had two orders for the same symbol and
  side (2026-09-29 HPE and SWKS; 2026-09-30 AAOI, HPE, MDB and SWKS;
  2026-10-02 HPE, STX and SWKS); no reason was invented for them.
- Early sessions carry no client order ids, and some carry no `planned`
  list; for those the desk record's `actions` field with a non-empty `why`
  is the last-resort reason. That is why the analyst-stance rows appear:
  they are the ledger's stated reason, not a classification chosen here.
- The desk records are nightly snapshots. Four sessions in the window have
  no record, and the broker's fills on the next open are attributed to the
  session encoded in the client order id, not to the fill date.

## What this means

- Cadence is not the dominant source. The scorecard's daily-sizing arm does
  not reproduce the live turnover magnitude, and the 20-session fix fails the
  turnover-halving and drawdown conditions even though its paired mean daily
  difference is positive and not significant.
- The live turnover is spread across the rule's own position management:
  grade-driven exits and redeploys are the largest single group, sizing
  adjustments the next, and FOMC actions and cash redeployment add the rest.
  The initial build is a large one-time block. This is a decomposition, not a
  causal proof: the desk's reasons are self-reported and the window is short.
- The pre-registration says: if cadence is not dominant, the study tests no
  fix, writes the decomposition, names the dominant source and stops; the
  next diagnosis or fix is a separate pre-registration. That is what happens
  here. No fix is prepared, no release is proposed, and the installed `/3`
  is unchanged.

## What this study is not

It is not a search for the best cadence, and it does not claim 20 sessions is
optimal. It does not diagnose the grade-driven redeploy policy, the FOMC
action sizing, the minimum trade or the live book's concentration; each is a
separate pre-registration if the program chooses to pursue it. It does not
treat the 37-session live measurement as a stable estimate: the window is
short, includes the initial build from cash and the crash rebalancing, and
annualizing it is noisy. The scorecard decomposition is the reproducible
evidence; the live ledger is the mandate check.

## Ledger entry

| date | question | verdict | live change | evidence |
|---|---|---|---|---|
| 2026-11-03 | Why is turnover 8.44x/year on the scorecard and about 30x/year live, against a 2x target? | **FAIL / no fix**: cadence is not dominant (daily 1.82x the 20-session arm, 51% of the live 30.2x); the 20-session fix fails the turnover-halving and drawdown gate; the live ledger's largest group is grade-driven exits and redeploys (27.7%) | none | this note |
