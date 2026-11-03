# Trading program direction

Status: **binding direction document**. Written 2026-11-03. Last verified
2026-11-03 against main `f2fc27e8` and the live installed state in
`data/market/desk/learned-holding/`. It supersedes the direction and live-state
claims of `docs/research/trading-program-2026-10-28.md`; that note remains the
historical program record. Process rules remain `docs/trading/RULES.md`; the
code map remains `docs/trading/CODE_MAP.md`; the current handoff remains
`docs/NEXT_SESSION.md`.

This is the one document that says where the trading program is going. If a
research note, contract, session note or code comment disagrees with it about
direction or live state, this document wins. If it disagrees with the
implementation, the implementation wins for what is live, and this document is
corrected.

## 1. The objective

The program maximises forward, point-in-time, after-cost CAGR subject to:

- long-only, no leverage, US large caps, one engine;
- median Sharpe at least 1.0 on the honest S&P 500 point-in-time universe;
- median CAGR above SPY on that universe;
- worst drawdown no deeper than about -35%;
- turnover about 2x a year;
- every change pre-registered, measured at 10 and 25 bp, and forward-shadowed.

The measurement standard is fixed: honest S&P 500 point-in-time membership
(dated file, no survivorship), 20 start offsets, medians across offsets,
costs at 10 and 25 bp, paired daily differences at the median offset with a
Newey-West t at lag 20 and a month-block bootstrap (2,000 draws, seed
20261102). The all-window result is the gate; 2016-2023 and 2024-2026 are
reported and never tuned on.

**"Top tier"** is the objective plus CAGR above QQQ, paired statistical
confidence (Newey-West t at least 2.0 and a bootstrap 95% lower bound above
zero), and a 252-session forward record. The program does not currently meet
the objective, let alone the top-tier bar.

**Drawdown reading.** The research gate reads the median across offsets, as
pre-registered. The live risk mandate reads the worst offset, because the
objective says "worst drawdown no deeper than about 35%." The installed joint
passes the median reading narrowly (-34.56%) and fails the live mandate
(-39.24%). That failure is recorded, not remedied by a live change now: the
owner installed the rule and the 252-session forward record is the arbiter.

**Turnover.** About 2x a year is a program constraint, not a slogan. The
scorecard base is 8.61x/year and the live paper's first 37 sessions annualize
to about 30.2x/year gross (15.1x one-way). Neither meets it. Turnover is
milestone 2 below and needs its own pre-registration.

## 2. The live rule

`grade-led-leader-weight/2`, installed 2026-11-02. Entry at A or better, hold
while A, exit below A (`ENTRY_GRADE = 2`, `HOLD_GRADE = 2`, `exit_letter =
"A"`).

| parameter | value |
|---|---|
| analyst votes | value 3, fundamental 1, technical 1, sentiment 1, rotation 0.5 |
| grade boundary | entry A, hold A, exit below A |
| leader tilt | trailing 63 sessions, strength 0.5, multiplier 0.5x-1.5x |
| volatility estimator | EWMA span 20 |
| volatility target | 0.25 annualized |
| exposure floor | 0.5 |
| per-name cap | 0.25 |
| P/E-history tilt | strength 0.5, window 756 sessions, minimum 250 readings |
| minimum trade | 0.01 of equity; exits always trade |
| execution | next open, whole shares, long-only, no leverage, remainder cash |
| annualisation | 252 |
| cost assumption | config 10 bp; scorecards at 10 and 25 bp |

The installed release is `deb96b651f7c7b4440dc7e6f55067475d4323e3c8e46cf24f86bd07874c62961`;
evidence `7a315eb2562886c186a2fcddedaae9dce67bbb9a649594d7d84bccb2e48c6a4a`;
config `2889633c4eeb1e9a17f291bee00d0bfca28532fe585a1414475e8abe70197854`;
deployed commit `15462e00`; admission ADMITTED on host and container;
`.post-deploy-status` "2026-11-02T17:24:07Z 15462e00 ok (cheap)". The install
followed the release ceremony.

**Forward record status.** The verified store's last complete session is
2026-10-30. The installed evidence records
`fresh_ordinary_paper_acceptance: UNVERIFIED; required after installation`.
The first ordinary nightly was scheduled for 2026-11-02 19:30 ET; the verified
store has not recorded its acceptance. Until that acceptance is verified, the
`/2` forward record has zero verified sessions; the paper account's 37
sessions were built under `/1` and are account history, not the `/2` record.
The 252-session review is the out-of-sample arbiter; the B hold is the
fallback.

## 3. The current-code honest baseline

All sessions, 25 bp, medians across 20 offsets, 2,964 paired sessions:

| line | CAGR | median drawdown | worst drawdown | Sharpe | above EW PIT | above QQQ |
|---|---:|---:|---:|---:|---:|---:|
| installed joint (`/2` sizing + P/E) | **13.650%** | **-34.560%** | **-39.237%** | **0.837** | 20/20 | 0/20 |
| live ordering, no P/E | 13.280% | -34.390% | -39.425% | 0.816 | 20/20 | 0/20 |
| scorecard floor arm | 13.280% | -34.420% | -39.425% | 0.815 | 20/20 | 0/20 |
| current-code no-floor A cut | 12.954% | -33.818% | -39.425% | 0.806 | — | — |
| SPY | 13.669% | -33.717% | -33.717% | 0.820 | — | — |
| QQQ | 18.476% | -35.119% | -35.119% | 0.884 | — | — |

The installed joint fails the objective on Sharpe and, by 1.8 bp/year, on
CAGR against SPY. It passes the median drawdown reading narrowly and fails the
worst-offset live mandate by 4.24 points. It beats equal-weight PIT in 20 of
20 offsets but QQQ in 0 of 20. The 2016-2023 window carries the failure
(11.73% CAGR, 0.721 Sharpe, 0/20 above QQQ); 2024-2026 is strong (23.22%,
1.391, 18/20) but is not the objective.

**Retired metric.** The published 17.088% A-cut is a 2026-10-21-code
measurement and is not reproducible on current code. The current no-floor arm
is 12.954%, the floor arm 13.284%, and the joint 13.650%. The gap is code/data
drift (-4.134 CAGR points), not the floor (+0.330). The 17.088% and the 17.1%
row must not be cited again. The bound contract and live `evidence.json` still
cite them; they are release sources and are corrected only through the next
authorized contract/release update, never by a silent edit. The correction
record is `docs/research/no-floor-control-results-2026-11-02.md`.

**Historical, not evidence of top tier.** The live 94-name survivor book
measured 37.6% CAGR / -27.7% worst drawdown / 1.46 Sharpe at 10 bp. That is a
hindsight-flattered book, not the honest universe. It must not be quoted as
the system's return.

## 4. The decision ledger

The ledger records what was tried, what it bought, and whether it changed the
live rule. "Installed" means it is in the live path; "closed" means the
question is answered and is not retried without a new pre-registration.

### Installed lineage

| date | change | verdict | evidence |
|---|---|---|---|
| 2026-09-27 | `graded-equal-weight/4`: A/A+ equal weight, 20% cap | installed; beat incumbent `/3` by +13.9 CAGR points in 20/20 offsets, but not distinguishable from equal weight (t 0.52) and -43.3% drawdown | `pit-arms-2026-09-26.md` |
| 2026-09-29 | `graded-equal-weight/5`: 25% cap | installed; cap 20->25 added about +1.2 CAGR points in 2016-23 and +2.3 in 2024-26; the 20->25 step was not separately tested | `cap-sweep-2026-09-27.md` |
| 2026-10-13 | `grade-led-learned-sizing/1` contract | installed; frozen behavior, no performance claim | `grade-led-sizing-contract-2026-10-13.md` |
| 2026-10-21 | `grade-led-leader-weight/1`, revisions 1-6 | installed; open fills, EWMA-20, floor 0.5, A entry/B hold/1% min trade, P/E tilt | `grade-led-leader-weight-contract-2026-10-21.md` |
| 2026-10-22 | value analyst at three votes | installed; honest A cut 15.3% -> 17.1% CAGR, Sharpe 0.91 -> 1.00, drawdown -37.3% -> -34.7% (2026-10-21 code) | `value-weighted-grading-2026-10-22.md` |
| 2026-10-24 | P/E-history tilt, strength 0.5 | installed (revision 6); current-code marginal +0.375 CAGR points, +0.021 Sharpe, paired t 0.39, not significant | `pe-history-tilt-2026-10-24.md`, `installed-joint-configuration-results-2026-11-02.md` |
| 2026-10-28 | FOMC pre-meeting cut retired | installed; full exposure through meetings | `fomc-cut-retirement-2026-10-28.md` |
| 2026-11-02 | `grade-led-leader-weight/2`: entry A, hold A | installed; on the study's 2026-10-21-code table the A hold's point estimate is better than B (+2.76 median CAGR points, +0.13 Sharpe, 3.6 points shallower worst drawdown, 20/20 offsets), but the daily mean is not significant (t 1.02) | `installed-rule-significance-results-2026-11-02.md` |

### Current-code verdicts

| date | study | verdict | live change | evidence |
|---|---|---|---|---|
| 2026-11-02 | installed joint configuration | **FAIL**: 13.650% / 0.837 / -34.560% / -39.237%; fails Sharpe and CAGR | none | `installed-joint-configuration-results-2026-11-02.md` |
| 2026-11-02 | A hold vs B hold significance | **FAIL**: +0.77 bp/day, Newey-West t 1.02, bootstrap -0.66..+2.18 | none | `installed-rule-significance-results-2026-11-02.md` |
| 2026-11-02 | no-floor control | drift dominant; 17.088% retired; floor +0.330 CAGR, +0.009 Sharpe, -0.605 median drawdown, worst unchanged | none | `no-floor-control-results-2026-11-02.md` |
| 2026-11-02 | sector-flow gate, flow tilt, QQQ brake, joint | **all four FAIL**: best arm 14.042% / 0.844; tilt paired -0.096 bp/day, t -0.47; brake 0/20 offsets; joint worst | none | `sector-flow-overlay-results-2026-11-02.md` |

### Closed experiments

These are answered. Do not retry them without a new pre-registration that
says what changed and why.

- **Timing and entry overlays:** Stage 3, Stage 4, Stage 5, adaptive entry,
  chart judgment, VWAP bounce, 467 registered timing trials, 457
  adaptive-entry trials, 452 Stage 5 trials. All RECORD or FAIL; no live
  change. See `stage3-results-2026-09-29.md`, `stage4-results-2026-09-29.md`,
  `stage5-results-2026-09-29.md`, `adaptive-entry-results-2026-09-30.md`,
  `chart-judgment-results-2026-10-28.md`,
  `vwap-bounce-overlay-results-2026-10-28.md`.
- **Selection overlays:** residual momentum, value-momentum blend, 52-week-high
  proximity, SUE rank-IC, tone surprise, statement reading, event-shock
  continuation, earnings de-risking, chase guard. All FAIL or STOPPED; no
  live change. See the 2026-10-28 and 2026-10-31 result notes in
  `docs/research/`.
- **Risk overlays:** catastrophe stops, trend gates, static sector cap, C5
  sector sleeve, sector-flow gate/tilt, QQQ brake. All FAIL or RECORD; no
  live change. The static sector cap never binds on the honest universe
  (0 of 2,970 sessions; IT plus Communication Services average 16.48%,
  maximum 39.67%). See `catastrophe-stop-2026-09-27.md`,
  `sector-sleeve-results-2026-10-29.md`, `sector-cap-results-2026-10-31.md`,
  `sector-flow-overlay-results-2026-11-02.md`.
- **Learned models and rankers:** ridge, trees, the frozen network, day-type,
  learned holding, conviction and the learned rankers. None beat the rule or
  equal weight on corrected data; no live change. See
  `trading-program-2026-10-28.md` and `top-tier-algorithms-2026-10-28.md`.
- **Execution ablation:** every live option KEEP; the 4.4 CAGR-point gap is
  mid-cycle entries at t 0.5; next-open and the 1% minimum trade remain. See
  `execution-ablation-2026-09-27.md`.
- **FOMC:** the pre-meeting cut is retired; the full-exposure rule is live.
- **Positive-shock drift:** diagnostic only, owner-blocked; not a live rule.

### Open

| question | status | next step |
|---|---|---|
| Does each installed component earn its complexity? | **measured 2026-11-03**; only the P/E tilt is removable (marginal +0.053 bp/day, Newey-West t 0.39, not significant; removal within tolerance and lower turnover). The volatility target, floor and leader tilt are kept because removal breaches a pre-registered tolerance; the cap is a risk limit and is inert on this universe. Candidate: the live ordering without P/E (`leader_ewma_minA_floor50_live`). | install `/3` through the release ceremony, then milestone 2 |
| Why is turnover 8.61x/year on the scorecard and about 30x/year on the live paper, against a 2x target? | not diagnosed | pre-registered turnover study, milestone 2 |
| Should the live book stay AI/software-concentrated or widen? | owner decision; the live book is 80/94 IT and all 8 A/A+ names are IT | universe/mandate memo, milestone 3 |
| Which branches, worktrees and research modules are dead? | audit complete; review pending | code/branch hygiene, milestone 4 |
| Does the live rule work out of sample? | `/2` forward record has zero verified sessions; acceptance pending | 252-session review, milestone 5 |

### What the evidence actually says

- The grade-only rule was a large improvement over the prior sizing layer and
  the first rule to show grade selection. It was not top tier: it was level
  with equal weight, had a -43% drawdown, and did not clear the Sharpe
  objective.
- The clearest measured improvement is value x3 grading. The A hold is the
  best point estimate but is not statistically significant. The leader tilt,
  floor and P/E tilt each add small positive point estimates; none is
  significant.
- The installed overlays are not the main cause of the failure. The failure is
  the base selection on the broad honest universe plus the vol-target/floor
  de-levering. The apparent fall from the grade-only 28% to 13.65% is mostly
  the change from the narrow PIT book to the broad honest S&P 500 PIT, not the
  overlays.
- The live book's concentration is a universe/mandate issue. A sector overlay
  cannot diversify it: the flow tilt would add IT when IT leads; the flow gate
  would have nothing to block or would block IT. The 2026-09-04..2026-10-30
  drawdown was sector-specific, not a QQQ trend break.

## 5. Rules of engagement

1. **One live rule.** The installed policy is the only rule that trades. The
   forward record is the arbiter.
2. **Pre-register before the first run.** Question, sample, arms, gate,
   placebo, what passing buys. Commit the pre-registration before any result
   exists. Amend it only before a result exists, and say so in it.
3. **No retries.** A failed idea is written down with its evidence and is not
   retried without a new pre-registration saying what changed and why.
4. **Marginal attribution before adding complexity.** Measure a new component
   against the simpler baseline, one component at a time. A component that
   does not earn its complexity is removed.
5. **The honest universe is the test; the live book is the mandate.** A rule
   that only works on the live 94-name book is not evidence. A rule that only
   works in 2024-2026 is not the objective.
6. **Costs and statistics.** 10 and 25 bp; 20 offsets; medians and worst;
   paired daily differences; Newey-West t at lag 20; month-block bootstrap;
   PSR. No single-number claims.
7. **No stale metrics.** Every cited number carries its date, universe, cost
   and code revision. The 17.088% is retired. The 37.6% survivor-book number
   is historical.
8. **No live change during the forward record** except an owner-authorized
   simplification or a correctness fix. Every live change goes through the
   release ceremony: candidate folder, bound sources, full gate, install
   under the paper lock, deploy, admission ADMITTED, fresh ordinary nightly,
   and the following real session.
9. **Every experiment ends.** It produces a result document, a verdict and a
   ledger entry, or it is closed as abandoned with the reason. No orphan
   experiments.
10. **Docs state their status.** Canonical, superseded or historical, at the
    top. This document is canonical for direction; `RULES.md` for process;
    `CODE_MAP.md` for code; `NEXT_SESSION.md` for the current handoff.
11. **No vibe-coded experiments.** Every experiment has a pre-registration, a
    script, a payload, a result document and a ledger entry. A notebook or a
    chat transcript is not evidence.
12. **The owner decides** live installs, the risk dial, the universe/mandate,
    deployment timing and a forward-record reset. The program decides research
    design, pre-registrations, code, tests and candidate preparation.

## 6. Stop doing

- No more sector, timing or overlay experiments without a written thesis and a
  pre-registration. The sector-flow and QQQ-brake study is closed.
- No parameter searches. The program has enough trials; the multiplicity is
  already large.
- No new complexity until the ablation removes what does not pay.
- No quoting 37.6% (survivor book) or 17.1% (stale code) as the system's
  return.
- No chasing the 2024-2026 window. It is not the objective.
- No experiments on the live 94-name book as if it were the honest universe.
- No "top tier" claim without the forward record.
- No orphan branches, worktrees or experiments.
- No silent edits to bound release sources.

## 7. Next milestones

### Milestone 1: simplicity/ablation audit (now)

Pre-register a six-arm chain on the honest universe at 25 bp, 20 offsets:
grade-only; +volatility target; +25% cap; +exposure floor; +leader tilt; +P/E
tilt (the installed joint). Measure each component's marginal. Remove a
component only if its marginal is not statistically significant and its
removal is within the pre-registered tolerance (median CAGR no more than 0.50
points lower, median Sharpe no more than 0.03 lower, median worst drawdown no
more than 1.00 point deeper, paired HAC t above -2.0, bootstrap lower above
-1.0 bp/day). If the simplest non-inferior arm is simpler than `/2`, prepare
and install it through the release ceremony and restart the forward record.
If no simpler arm qualifies, keep `/2` and close the ablation.

Gate: the pre-registered non-inferiority rule. Owner: program for the study;
owner for the install (conditional authorization recorded 2026-11-02).

**Status 2026-11-03: complete.** The P/E tilt is removed. The candidate is
`leader_ewma_minA_floor50_live` (live ordering, no P/E): 13.28% CAGR, -34.39%
median drawdown, -39.42% worst drawdown, 0.816 Sharpe and 8.44x turnover,
against the installed joint's 13.65%, -34.56%, -39.24%, 0.837 and 8.61x. It is
within every pre-registered tolerance and does not increase turnover. The
volatility target is kept because removing it deepens median drawdown beyond
tolerance; the floor and leader tilt are kept because removing them breaches
the CAGR tolerance; the cap is a risk limit and is inert on the honest
universe. The candidate still fails the objective (Sharpe, CAGR versus SPY,
and the worst-offset drawdown), so the next focus after the install decision
is the universe/mandate. Result:
`docs/research/simplicity-ablation-results-2026-11-03.md`.

### Milestone 2: turnover diagnosis

Pre-register a study of the 8.61x/year scorecard and about 30.2x/year live
paper turnover. Decompose by rebalance cadence, leader-tilt rank changes,
volatility-target changes, P/E changes, floor/cap and minimum trade. Identify
the dominant source and propose a fix that reduces turnover without a material
performance loss. No live change without a separate release.

Gate: dominant source identified; candidate fix measured at 10 and 25 bp with
turnover and performance. Owner: program.

### Milestone 3: universe/mandate memo

Owner decision. The live book is 94 names, 80 IT, all 8 A/A+ names IT; there
are no Financials, Health Care, Energy, Materials, Real Estate or Consumer
Staples names. The honest universe is diversified. The prior utilities
measurement (38.45% CAGR, 1.247 Sharpe, -42.05% worst drawdown against 34.12%,
1.178, -42.19% over twenty start phases) is better on return and Sharpe but
deeper than the -35% limit; it is evidence about return, not a passing
configuration. Options: keep the AI/software mandate, widen with a sector cap,
or widen with a risk overlay. The owner decides; no live change without a
release.

Gate: owner decision recorded with the evidence. Owner: owner.

### Milestone 4: code and branch hygiene

Produce `docs/trading/CODE_HYGIENE.md` (or a section here) with the live path,
the research path, dead/experimental code, branches and worktrees, stale docs
and a safe archive/delete list. Archive stale branches with tags and delete
only after the owner reviews the list. No `git reset --hard`, no
`git clean -fd`, no force push. Run the full gate after deletions and confirm
admission is unchanged.

Gate: every branch merged or archived; dead-code list reviewed; full gate
passes. Owner: program; owner for deletion approval.

### Milestone 5: 252-session forward record review

The arbiter. Pre-register the review criteria before the record ends: forward
Sharpe, drawdown, CAGR against SPY and QQQ, turnover, and whether the
installed simplification is working. The B hold remains the fallback. No
interim live changes except the conditional simplification or a correctness
fix.

Gate: the pre-registered review. Owner: owner and program.

## 8. Decision rights

| decision | owner |
|---|---|
| live install, policy version, risk dial | owner |
| universe/mandate, sector concentration | owner |
| deployment timing, forward-record reset | owner |
| research design, pre-registration, arms, gates | program |
| code, tests, candidate preparation | program |
| interpreting a result | program, with the pre-registered rule |

## 9. Change log

- **2026-11-03:** created. Supersedes the direction and live-state claims of
  `trading-program-2026-10-28.md`. Records `/2` as live, the current-code
  baseline, the retired 17.088%, the decision ledger, the rules of engagement,
  the stop-doing list and the five milestones.
- **2026-11-03:** milestone 1 complete. The ablation removes only the P/E
  tilt; the candidate is `leader_ewma_minA_floor50_live`. The direction doc's
  ledger and milestone status are updated; the install decision follows the
  release ceremony.
