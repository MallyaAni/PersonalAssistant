## scope
Read-only ledger of every trading experiment, strategy test, protocol and material finding recorded 2026-09-22 through 2026-09-25. Sources read in full: every docs/research/*.md dated 2026-09-22 or later (57 files, including the 09-25 options, SEC, fundamentals, extended-hours and UI-wording notes, which were skimmed for strategy content); docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md; docs/research/claude-review-2026-09-23/ (REVIEW.md, day-rotation-2026-09-23.md, engine.py, run3.py, run4.py, run5.py, run3/4/5.csv, repo_simulator_check.py); docs/NEXT_SESSION.md lines 1-4880 (the 09-22 entries run slightly past 4755) plus lines 5680-5704 (the 2026-09-21 'User clarified the actual allocation objective' section). Also read, because in-window docs cite them as binding: portfolio-exposure-objective-2026-09-21.md, portfolio-allocation-protocol-2026-09-21.md and docs/TRADING_ROADMAP.md (2026-09-15). Three pre-window studies (09-15 intraday timing, 09-20 conditional-entry pilot, 09-21 ten-session context) are included and marked PRE-WINDOW REFERENCE. They are the evidence base for the 15-minute entry question. Code was checked only to confirm live policy flags: backend/agents/trading/desk/simulate.py:72-78 (LIVE_POLICY: block_overbought, exit_at_close, green_day_skip, live_midcycle, deferred_buys all True), backend/agents/trading/desk/paper.py:150-169 (ENTRY_BAND_Z=1.10 chosen by a sweep of 0.40-2.00; ENTRY_ADD=0.023; ENTRY_NAME_CAP=0.15; ENTRY_MIN_GRADE A/A+; POLICY_VERSION bumped /2 to /3 in commit 15f1b1d4 on 2026-09-23), paper.py:68 (REBALANCE_EVERY=20) and backend/agents/trading/desk/trend_brake.py (0.97/1.02 on a 200-session QQQ mean, opt-in). No files were modified.
## experiments
--- [0]
## name
Funded vol / vol_trend allocation (GPT), fixed evaluation at 10 bp plus predeclared 25 bp stress
## date
2026-09-22
## source_doc
docs/research/trading-funded-validation-2026-09-22.md:37-70; docs/research/portfolio-allocation-protocol-2026-09-21.md:37-91; docs/NEXT_SESSION.md:4826-4831,4868-4872
## hypothesis
Scaling the desk book to a benchmark-relative volatility budget beats both SPY and QQQ on CAGR with no larger maxDD. Budget B=min(risk SPY, risk QQQ), where risk=max(std20,std60)*sqrt(252). vol adds a residual SPY sleeve; vol_trend adds a SPY/QQQ 200-day trend ceiling taking values 0, 0.5 or 1.
## method
2016-01-04..2026-09-18: 2,693 NAV observations / 2,692 returns. NAV1, close decision with next-open fill, 10 bp per side, zero cash yield, explicit hypothetical SPY eligibility, dividend-inclusive funded SPY/QQQ. No fitting, threshold search or window selection. Predeclared 25 bp stress applied to benchmarks too.
## result_numbers
10 bp CAGR / maxDD / share of rolling 252-session windows meeting both objectives:
- SPY 15.07% / 33.72%
- QQQ 20.07% / 35.12%
- vol 22.01% / 24.59% / 34.08% of 2,441 windows
- vol_trend 16.78% / 15.30% / 26.34%

25 bp:
- SPY 15.06% / 33.72%; QQQ 20.06% / 35.12%
- vol 20.13% / 25.72% / 25.44%
- vol_trend 14.82% / 15.77% / 22.53%

Other:
- vol's margin over QQQ at 25 bp is about 0.08 pt/yr.
- vol average observed exposure is 58.47%. Hindsight constant-exposure SPY/QQQ at that exposure drew down 21.20% / 21.61%.
- Earlier measured policies turned over about 10-11x NAV per year, two-way (NEXT_SESSION.md:4774-4775).
## verdict
closed-negative
## caveats
The doc itself calls it 'a fragile result, not grounds for adoption'. The Claude review (REVIEW.md:11-15,42) says the budget is effectively SPY volatility, so exposure falls to 40-55% and CAGR roughly halves. The code is not wired live: market_daily calls paper.plan without allocation_context. Reused, survivor-biased history.
--- [1]
## name
Zero-cost / midpoint-target rerun of vol and vol_trend
## date
2026-09-22
## source_doc
docs/NEXT_SESSION.md:4779-4800
## hypothesis
At the user's requested zero-cost convention ('forget trading costs try to hit mid price'), vol / vol_trend meet the SPY+QQQ objective.
## method
Same fixed 2016-01-04..2026-09-18 run at 0 bp for candidates and benchmarks. NAV1, next-open proxy (not a verified midpoint fill), zero cash yield, source e71b906.
## result_numbers
CAGR / maxDD:
- vol 23.2805% / 23.8314%
- vol_trend 18.0976% / 14.9875%
- SPY 15.0857% / 33.7173%
- QQQ 20.0853% / 35.1187%

vol meets both full-window objectives and 40.2294% of overlapping 252-session windows. vol_trend fails QQQ's return (rolling 29.4551%).
## verdict
closed-negative
## caveats
This is a next-open proxy, not a midpoint backtest: there is no historical bid/ask. It is superseded by the Claude review, where 'vol' as built gave 17.2% against 31.6% for the incumbent plus deferred buys in the same harness. Not adopted.
--- [2]
## name
Incumbent sizing: live-like hold-20 vs next-session deployment of idle cash (A vs A1/A2), independent proxy backtest
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/REVIEW.md:20-38,49-52; run3.py; run3.csv; engine.py:171-279
## hypothesis
Sells fill at the close while buys are bounded by cash on hand, so proceeds sit idle until the next reset. Deploying them at the next session raises return.
## method
Independent next-open backtester (engine.py), 94-name book, Yahoo adjusted bars through 2026-09-21. Selection is a price-only proxy: rank-average of 120d momentum (skip 5) and 60d range position, plus 0.5 if above the 200d mean. Top decile, inverse-vol weights with a 10% floor, 15% cap, 30% book vol target, 20-session refresh. 10 bp/side, ^IRX T-bill yield on cash. Windows: 2016-26 full, 2016-20, 2021-26.
## result_numbers
Full 2016-26 CAGR / maxDD / Sharpe / average exposure / turnover per year:
- A live-like 26.32% / 33.74% / 1.20 / 61.5% / 9.38
- A1 deferred next-day buy 31.65% / 42.63% / 1.15 / 82.0% / 13.49
- A2 recycle proceeds (upper bound) 31.05% / 42.95% / 1.13 / 83.7% / 13.42

2016-20 CAGR / DD:
- A 21.17% / 20.59%
- A1 25.17% / 33.86%
- QQQ 24.44% / 28.54%

2021-26 CAGR / DD:
- A 32.12% / 35.34%
- A1 32.90% / 42.09%
- QQQ 17.39% / 35.05%
## verdict
adopted
## caveats
Adopted as deferred_buys=True in simulate.LIVE_POLICY (simulate.py:72-78, commit 39fec3bb, 2026-09-23). The paper account already retried deferred orders via paper._deferred_orders. It raises maxDD from 33.7% to 42.6%; the review said 'Decide which you want deliberately'. In 2016-20 the live-like book trails QQQ (21.2% vs 24.4%). The selection is a price-only proxy with no fundamentals or tone, and the book is survivor-selected. repo_simulator_check.py exists to verify the effect in the real simulator, but no output is recorded (INFERRED: not run or not documented).
--- [3]
## name
QQQ 200-session trend brake with hysteresis (0.97/1.02, halve the book, released half to cash) — A3
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/REVIEW.md:33,79-81; day-rotation-2026-09-23.md:53-68; run3.csv; run5.csv; backend/agents/trading/desk/trend_brake.py; docs/research/learned-price-results-2026-09-24.md:23-39
## hypothesis
A regime-scale trend brake keeps most of the return and cuts maxDD by about 10 points.
## method
A1 plus overlay: risk_off below 0.97x the QQQ 200d mean, back on above 1.02x, scale 0.5. Trades only when the scalar moves more than 10% of the book. Same harness as A1. Also run as momentum120_fixed_brake in the 09-24 learned-price study.
## result_numbers
Claude harness:
- A3 full: 29.92% CAGR / 31.64% DD / Sharpe 1.18 / exposure 74.5% / turnover 12.97
- vs A1: 31.65% / 42.63%
- A3 2016-20: 21.97% / 29.66% (QQQ 24.44%)
- A3 2021-26: 32.46% / 31.30%

Learned-price study, 10 bp, 2019-03-26..2026-09-21:
- momentum120_fixed_brake 63.1% / -44.7% / Sharpe 1.32
- momentum120 70.5% / -46.6%
- Holdout return 28.8% for both

At 25 bp: 60.9% / -45.0% vs 68.2% / -47.0%.
## verdict
shadow
## caveats
Implemented as the opt-in simulate.run(trend_brake=True) so it can run as a named shadow with the desk's real grades. No shadow run with real grades is recorded. Bands were 'chosen, not fitted, but read on this history'. Forbidden: 'no retune of the brake bands on 2016–2026' (day-rotation:78-79). In 2016-20 it trails QQQ on CAGR.
--- [4]
## name
Trend brake with the released half parked in QQQ instead of cash — A3q
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/run5.py:18-26; run5.csv; day-rotation-2026-09-23.md:60-64
## hypothesis
Parking the braked half in QQQ keeps the return while still protecting.
## method
Same as A3, but out-of-trend capacity goes to QQQ.
## result_numbers
- A3q full: 31.96% CAGR / 42.66% DD / Sharpe 1.15 / exposure 84.1%
- vs A1: 31.65% / 42.63%
- vs A3 (to cash): 29.92% / 31.64%
- 2016-20: 26.60% / 31.01%
- 2021-26: 33.11% / 39.66%
## verdict
closed-negative
## caveats
'QQQ falls in the same regimes' (day-rotation:57-58). The index is not a defensive substitute for cash.
--- [5]
## name
Volatility cap at 1.25x QQQ volatility on A1 — A4, and GPT vol/vol_trend inside the same proxy harness
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/REVIEW.md:27-36; run3.csv
## hypothesis
Capping book volatility relative to QQQ improves the risk/return trade-off.
## method
Book.overlay='vol_qqq': min(1, 1.25*QQQvol/bookvol), using max(std20, std60). GPT's allocation.decide policies are wrapped with a 20-session composition refresh and daily decide.
## result_numbers
Full 2016-26 CAGR / DD / Sharpe / exposure:
- A4 24.73% / 42.02% / 1.04 / 74.7%
- GPT vol as built 17.22% / 33.58% / 1.03 / 51.3%
- GPT vol_trend as built 14.75% / 23.49% / 1.14 / 40.2%
- SPY 15.33% / 33.72%
- QQQ 20.44% / 35.05%
## verdict
closed-negative
## caveats
A4 cuts CAGR by about 7 points with no drawdown benefit over A1. Vol-targeted allocation roughly halves CAGR.
--- [6]
## name
vol_trend re-parameterised: QQQ-relative budget plus hysteresis
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/run5.py:5-16,34-36; run5.csv; REVIEW.md:78
## hypothesis
Fixing vol_trend's SPY-level budget (budget_reference='qqq', multiplier 1.5 or 2) and adding hysteresis recovers return while keeping the lower drawdown.
## method
alloc.decide with budget_reference/budget_multiplier. Three variants: QQQx1.5 with SPY residual, QQQx2 without residual, and GPT's original min budget with hysteresis.
## result_numbers
Full 2016-26 CAGR / DD / Sharpe / exposure:
- QQQx1.5 + SPY residual 24.85% / 30.67% / 1.11 / 74.9%
- QQQx2, no residual 26.22% / 30.35% / 1.12 / 67.5%
- as built + hysteresis 14.51% / 21.74% / 1.10 / 40.1%

The QQQx2 variant ran 20.38% in 2016-20 (QQQ 24.44%) and 28.94% in 2021-26.
## verdict
inconclusive
## caveats
Dominated on CAGR by A3 (29.9% / 31.6%). The review recommended 'Shelve vol and vol_trend, or re-register them with a QQQ-relative budget and hysteresis'. No re-registration is recorded.
--- [7]
## name
Daily green/red rotation between the volatile book and QQQ (operator idea), plus conditional hit rates
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/day-rotation-2026-09-23.md:12-47,70-79; run4.py; run4.csv
## hypothesis
'hold the volatile book on its green days and rotate into an index on its potential red days; entering the volatile names at the right time and price is the key'.
## method
Hold-20 top-decile momentum book. Each close, decide book vs QQQ for tomorrow from data up to t; trade only on state change; next-open fills, 10 bp, T-bill cash. Variants: follow colour, buy dips, QQQ above its 10d mean, volatility spike, book above +2 sigma stretch, 5-day pullback entry, a combination, and a non-causal oracle.
## result_numbers
Full CAGR / DD / Sharpe / turnover per year:
- QQQ buy-and-hold 20.44% / 35.05%
- always in book 31.10% / 43.02% / 1.13 / 13.4
- green stay, red to QQQ -1.77% / 53.25% / 0.05 / 214.5
- red in, green to QQQ 1.70% / 57.60% / 0.19 / 210.0
- QQQ above 10d mean 18.64% / 39.04% / 0.83 / 75.3
- volatility spike to QQQ 24.84% / 45.31% / 0.97 / 30.6
- book above +2 sigma to QQQ 30.56% / 43.02% / 1.11 / 14.2
- 5-day pullback entry 12.33% / 44.98% / 0.63 / 79.7
- QQQ 10d and not stretched 18.38% / 39.04%
- oracle 112.9% / 22.6% / 3.45 / 209.5 (zero-cost oracle 162.2%)

Conditional P(book beats QQQ next day), 2,693 sessions:
- unconditional 53.9%, +8.7 bp
- after a green day 54.3%, +10.2 bp
- after a red day 53.4%, +6.6 bp
- after a 5-day pullback 54.0%, +9.7 bp
## verdict
closed-negative
## caveats
'No live rule that switches the book on the previous day's colour, no daily index rotation, and no retune of the brake bands on 2016–2026'. Switching costs about 40 points a year at about 200 trades a year and 20 bp per round trip. All causal rows lose to staying in the book in both halves. Survivor book: read only the row differences.
--- [8]
## name
Claude review code findings on the incumbent and GPT's funded path
## date
2026-09-23
## source_doc
docs/research/claude-review-2026-09-23/REVIEW.md:40-83; docs/NEXT_SESSION.md:4031-4037,4682-4690
## hypothesis
Execution and sizing defects cost return or create churn.
## method
Code review plus reproductions.
## result_numbers
Defects found:
- (2) Personal board repeats Buy every 15 minutes, 1.8-7% each, until the 15% cap.
- (3) Whole-share funded path: risk_cut rounds sells up, giving 608 reversals in 250 sessions (funded_execution.py:470/642).
- (4) Idle cash from close-fill sells costs about 5 CAGR points in the proxy.
- (5) Buys need a 0.5% minimum trade but sells have none: exposure 0.886 against a 0.90 target and about 45% more turnover.
- (7) Live quotes lag up to one bar (live_quotes.py:118).
- (8) Early closes hard-coded to 16:00.
- (9) vol_trend 200d ceiling has no hysteresis.
- (10) B-graded names take top-decile slots and then get zero weight (risk.py:158).
- (11) Intraday research has no next-open baseline.
## verdict
adopted
## caveats
Partly addressed:
- (2) Viewing a Buy no longer writes; only a recorded same-session fill or a working order suppresses the next Buy (NEXT_SESSION:4031-4037).
- (4) Addressed by deferred_buys.
- (7) 09:59-to-10:00 stale-cache fix (NEXT_SESSION:4682-4690).
- (8) Reviewed 13:00 closes now handled (microstructure review:139-143).

No fix is recorded for (3), (5) or (10). The funded path is unwired. Cross-session repeat entry and after-fill add-ons are still unconstrained (see the turnover review).
--- [9]
## name
15-minute entry engine reclaim_above_level/1 and its frozen comparison protocol
## date
2026-09-22
## source_doc
docs/research/intraday-entry-contract-2026-09-22.md:24-86,169-196; docs/research/intraday-comparison-protocol-2026-09-22.md:20-113; docs/NEXT_SESSION.md:4624-4638,4711-4753
## hypothesis
Entering after a completed 15-minute bar reclaims a band level following a retest gives a better entry than the incumbent's same-bar Bollinger breakout (ENTRY_BAND_Z=1.10), with fewer repeated signals.
## method
Causal state machine on completed 15-minute bars: setup, entry_ready, invalidated, ambiguous, expired, historical; one setup per session. Levels from the prior 20 adjusted daily closes: level m+2s, entry m+2s*1.10, invalidation m. Comparison uses the incumbent bollinger_z/entry_action on the same inputs, a next-consecutive-bar-open zero-cost proxy, 20-session primary and 5-session secondary horizons, and common opportunity denominators.
## result_numbers
80 tests (39 entry cases). No historical outcomes scored under the full protocol: the earliest archived eligibility (09-08) matures on 2026-10-06, after the 09-18 cache end.
## verdict
frozen-pending
## caveats
'No profitability claim.' Research-only, not wired to production. The rule and levels are locked; no alternate widths may be tried on the same outcomes. Extended hours are excluded. The same rule can fire again each session (see the turnover review).
--- [10]
## name
15-minute cache price-basis compatibility audit and provider reconciliation
## date
2026-09-22
## source_doc
docs/research/intraday-comparison-input-audit-2026-09-22.md:3-60; docs/research/intraday-price-basis-reconciliation-2026-09-22.md:8-75
## hypothesis
Cached Alpaca IEX 15-minute bars (adjustment=all) share a price scale with daily Yahoo adjusted closes and can be used for historical scoring.
## method
Compared 782,568 same-session last regular 15-minute closes against daily adjusted closes across 529 symbols, plus eight bounded free IEX all/raw requests.
## result_numbers
Scale:
- Median absolute difference 0.0280%; 99th percentile 9.8341%.
- AVGO median ratio 9.9964 (max 10.0342)
- WRB median 1.4998 (upper percentile 2.2523)
- APTV median 0.8471
- BNY, FTV and WDC also discrepant.

Cache coverage:
- bars_15m/asof=2026-09-20: 530 files, 19,871,542 rows, 2019-01-02..2026-09-18, extended hours included.
- SPY/QQQ intraday absent. MSTR lacks a daily file.
## verdict
data-blocked
## caveats
Historical cross-provider scale compatibility FAILED. Forbidden: 'Do not fit per-name scale ratios, filter earlier entries using later closing-price disagreements, rescale frozen files'. Any usable path needs a reviewed dated transformation or fresh consistent forward observations.
--- [11]
## name
Fixed single-source conditional entry diagnostic (reclaim vs incumbent)
## date
2026-09-23
## source_doc
docs/research/intraday-single-source-protocol-2026-09-22.md; docs/research/intraday-single-source-results-2026-09-23.md:21-59; docs/NEXT_SESSION.md:4319-4333
## hypothesis
With daily references and entries taken from one fresh IEX adjusted 15-minute snapshot, the reclaim candidate enters better than the incumbent formula.
## method
Cohort AVGO, WRB, WDC, APTV (chosen for adjustment failures) plus SPY and QQQ. Entry sessions 2026-08-03..09-18. Grade A and non-rejecting band assumed at each open for both methods. Zero cost, next-bar-open proxy, 20/5-session horizons. Run once, snapshot SHA256 ae25a49b.
## result_numbers
Coverage:
- 204 opportunities; 170 ready; 34 unavailable (WRB)
- both entered 0; incumbent only 5; candidate only 1; neither 164
- 126 repeated readiness readings deduplicated to 6 events

Incumbent entries (20-session / 5-session return):
- AVGO 08-04 -9.9617% / +1.3151%
- AVGO 08-05 -13.2245% / -1.7956%
- AVGO 08-06 -16.1556% / -1.9377%
- SPY 08-04 -0.4220% / +0.7405%
- SPY 08-05 -1.4780% / -0.5228%
- Mean of 20-session returns -8.2484%

Candidate: SPY 08-07 -0.4574% / +0.3343%.
## verdict
inconclusive
## caveats
'Insufficient evidence to adopt the candidate.' No paired entries, different event sets, selected names. 'Do not rerun unchanged.' No tuning of this sparse diagnostic.
--- [12]
## name
Incumbent 15-minute price-rule parity validation
## date
2026-09-23
## source_doc
docs/research/intraday-incumbent-parity-review-2026-09-23.md:34-97
## hypothesis
The comparison's incumbent formula equals production's live entry_now band and entry_action gate.
## method
26-case differential suite against production helpers.
## result_numbers
26/26 passed; band equal to within 1e-12 at six developing closes. Threshold boundary: raw close 248.6416 gives band 1.10 and fires. Raw and adjusted scale are equivalent.
## verdict
adopted
## caveats
This is a formula-parity finding, not a strategy result. Still unverified: the live intraday re-grade (holdings.live_grades), account and cash name-cap (current=0.0) and executable fills.
--- [13]
## name
Intraday turnover and missed-opportunity acceptance review
## date
2026-09-23
## source_doc
docs/research/intraday-turnover-review-2026-09-23.md:28-96; docs/NEXT_SESSION.md:4305-4317
## hypothesis
Per-session signal deduplication keeps portfolio churn low.
## method
11 synthetic acceptance cases through compare/record_event/replay_session/decision_view.
## result_numbers
- 40 polls of one prefix give 1 event.
- Three consecutive sessions with the same reclaim path give 3 candidate events: cross-session repeat entry is unconstrained.
- The personal Buy aggregate is capped at available cash exactly (3000). Sale proceeds never fund buys. Add-ons after a fill are bounded only by cash and the name cap.
## verdict
inconclusive
## caveats
'A one-event-per-day ledger does not prove low portfolio turnover.' No holding-period or cooldown rule exists. Full strategy turnover is not computed anywhere.
--- [14]
## name
Learned rank and brake kernels (learned_policy.py) as named shadow-only policies
## date
2026-09-23
## source_doc
docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md:3-67; docs/NEXT_SESSION.md:4051-4077
## hypothesis
A purged, monthly-refit boosted ranker plus a 20-session QQQ crash-risk logistic brake beats the incumbent.
## method
Label: SPY-relative log return, next open to open at t+11. Publication-time checks, training-label purge, monthly refits. Brake: 20-session QQQ crash label (>8% drawdown), L2 logistic with 0.45/0.30 hysteresis, scales the book to 0.5. Synthetic future-prefix invariance tests only.
## result_numbers
Adoption table (CAGR, DD, Sharpe, rolling QQQ win, turnover, 10/25 bp, halves): every cell 'Unverified'. Local bar archive has 14 asof vintages, 2026-09-05..2026-09-22.
## verdict
shadow
## caveats
Verified only as causal kernels on synthetic inputs. No historical membership, and older prices are restated. The brake predicts a 20-session drawdown, not the next day (NEXT_SESSION:3239-3242).
--- [15]
## name
OpenCode fc703b0 rank_features / rank_ranker / rank_brake groundwork
## date
2026-09-23
## source_doc
docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md:115-140; docs/NEXT_SESSION.md:3969-3977
## hypothesis
The GBM ranker plus adaptive brake in commit fc703b0 is a valid learned policy.
## method
Independent code review with counterexamples.
## result_numbers
- ATR on a flat adjusted series (10) with raw high/low 101/99 gives 9.1 (price-basis error).
- A pure 10:1 split produces a forward label of -0.9.
- The label is own next-open to D+10 close, not the registered SPY-relative t+11 open.
- The fold helper does not enforce chronology or a purge.
- The brake uses fixed thresholds.
- 60 owned tests pass anyway.
## verdict
closed-negative
## caveats
The commit is kept out of main. These are implementation defects, not evidence that GBM cannot work.
--- [16]
## name
Prospective learned-input capture and causal archive-to-model bridge
## date
2026-09-24
## source_doc
docs/research/TRADING_LEARNED_REVIEW_2026-09-23.md:69-113; docs/NEXT_SESSION.md:3885-3982
## hypothesis
Freezing each nightly's actual features lets a future shadow be judged without look-ahead.
## method
The nightly writes immutable learned_inputs/asof=DATE.json with price, range, momentum, volatility, breadth, regime, as-of filing ratios, analyst rank and tone, and never overwrites. The bridge uses the first mature bar partition for labels.
## result_numbers
- Dry build on the 09-23 record: 95 rows, 95 complete bars, 89 tone records, 82 earnings-yield features.
- Live check 2026-09-24 01:14 UTC: 16 sessions, 15 bar vintages, 0 captures, 0 rank and 0 brake scores (expected: the capture shipped after the 09-23 nightly).
## verdict
shadow
## caveats
Prospective only. It cannot create a 2016-26 history. 'Do not force a historical run to fabricate one.' The first ordinary capture has not been verified in the docs read.
--- [17]
## name
Retrospective price-only HGB learned ranker and learned brake study
## date
2026-09-24
## source_doc
docs/research/learned-price-protocol-2026-09-24.md; docs/research/learned-price-results-2026-09-24.md:1-65; learned-price-results-2026-09-24.json
## hypothesis
A monthly HGB ranker on price features, with or without the learned QQQ brake, beats fixed 120-session momentum and the benchmarks.
## method
Fixed protocol. 94 names from the 09-23 grades plus SPY/QQQ, one snapshot. Features: 5/20/60/120d returns, vol20, distance to 20/60d means, 20d span, raw market features. 750-session minimum training, strict purge. Brake: 1000 sessions, 63-session refits, 0.45/0.30 hysteresis. Top 10, 10% cap, 20-session cadence, NAV1, zero cash yield, 10/25 bp. Holdout 2026-08-03 onward, all later-endpoint labels withheld. The full window FAILED (52 names missing 09-22), so it was mechanically cut to 09-21. Common start 2019-03-26.
## result_numbers
10 bp CAGR / DD / Sharpe / turnover per year / rolling wins vs SPY / vs QQQ / holdout return:
- momentum120 70.5% / -46.6% / 1.35 / 9.33 / 82.6% / 82.2% / 28.8%
- learned_rank 48.7% / -57.9% / 1.10 / 19.48 / 75.2% / 73.5% / 6.0%
- m120 + learned brake 68.9% / -44.6% / 1.38 / 9.50 / 84.5% / 80.4% / 17.3%
- learned_rank + learned brake 47.7% / -53.1% / 1.12 / 18.88 / 75.2% / 70.0% / -1.6%
- m120 + fixed brake 63.1% / -44.7% / 1.32 / 8.86 / 81.8% / 78.8% / 28.8%
- equal weight 39.5% / -38.6% / 1.27 / 0.50 / 82.1% / 83.0% / 9.9%
- SPY 16.2% / -33.7% / 0.87, holdout 3.8%
- QQQ 21.7% / -35.1% / 0.94, holdout 7.9%

25 bp CAGR / DD:
- m120 68.2% / -47.0%
- learned_rank 44.4% / -58.6%
- m120 + learned brake 66.5% / -44.8%
- learned_rank + learned brake 43.6% / -53.9%
- m120 + fixed brake 60.9% / -45.0%
- equal weight 39.5% / -38.8%

2016-20 (available from 2019) CAGR: m120 42.4%, learned_rank 40.1%, equal weight 44.6%, QQQ 37.9%.
2021-26 CAGR: m120 80.4%, learned_rank 51.5%, equal weight 37.9%, QQQ 17.0%.
## verdict
closed-negative
## caveats
'No retuning on this study.' The ranker lost to momentum with deeper drawdown and about 2x turnover. The learned brake cut drawdown modestly but also cut return. This is a survivor-selected price diagnostic, not the live incumbent. Note that price-only momentum120 beat equal weight here (70.5% vs 39.5%), unlike the Claude-harness framing.
--- [18]
## name
Causal regime decomposition of the saved HGB-study curves
## date
2026-09-24
## source_doc
docs/NEXT_SESSION.md:3736-3746
## hypothesis
The learned rank helps in some market regime.
## method
Four prior-close SPY regimes: 200-session mean, and 20d volatility vs its trailing 252-observation median. 1,882 intervals, no refit.
## result_numbers
At 10 bp, learned rank's mean daily log excess over momentum120 is negative in all four bins: -2.13, -2.92, -18.74 and -15.92 bp. The last bin has 37 intervals over 5 months.
## verdict
closed-negative
## caveats
Exploratory, on examined outcomes. No regime selector is promoted.
--- [19]
## name
Frozen nightly neural shadow ledger audit and 09-23 mark reconstruction
## date
2026-09-24
## source_doc
docs/research/learned-price-results-2026-09-24.md:67-85; docs/NEXT_SESSION.md:3814-3826,3858-3869
## hypothesis
The frozen nightly neural net (36->32->16->1, 94 names) is outperforming, so a combination could improve live recommendations.
## method
Read-only replay of six input hashes, predictions and ten accounts (five policies at 10/30 bp). Decision 09-15, fill at the 09-16 close.
## result_numbers
Return through the 09-22 mark, 10 bp / 30 bp:
- neural 15.84% / 15.60%
- valuation rule 12.01% / 11.78%
- momentum20 -0.20% / -0.40%
- SPY 2.46% / 2.26%
- cash 0%

ARM contributed 3.65 pp, GLXY 2.20, CRDO 1.92. The 09-23 reconstruction at 10 bp: neural +14.94%, valuation +10.49%, momentum20 +0.98%, SPY +1.72%.
## verdict
shadow
## caveats
One basket and four or five post-fill intervals. 'Do not fit a scenario selector from four daily returns, switch to the recent winner, or change the frozen neural experiment.' The 09-23 nightly stopped at the identity guard. Next-close execution.
--- [20]
## name
Neural comparison readiness audit: price/share-basis defect in frozen features and prior retrospective numbers
## date
2026-09-24
## source_doc
docs/research/neural-comparison-readiness-2026-09-24.md:37-85
## hypothesis
The frozen neural model can be compared fairly with the live rule.
## method
Read-only audit plus a real features() reproduction.
## result_numbers
Prior retrospective, 2025-01-02..2026-09-11, 10 bp, next close:
- neural +63.7% / DD -49.7%
- momentum20 +419.0% / DD -38.3%
- retrained versioned-fundamentals net +65.0%

Defect: a 10:1 split vintage gives sales yield 0.4 vs 4.0, a ln(10) error in log sales yield.
## verdict
data-blocked
## caveats
A corrected-feature retrain would be a separately named, preregistered study. 2025+ is examined. The frozen model cannot supply out-of-sample 2016-23 results.
--- [21]
## name
Price-only neural ranking substituted into the live rule (neural-price-rule-20260924)
## date
2026-09-24
## source_doc
docs/research/neural-price-study-protocol-2026-09-24.md; docs/research/neural-price-results-2026-09-24.md:12-80; docs/NEXT_SESSION.md:3470-3516
## hypothesis
Replacing only the scheduled ranking with a small price-only neural ranker inside unchanged LIVE_POLICY improves the rule.
## method
Eight price/volume features, 36->32->16->1 tanh net, trained on 2018-23 decisions (every 5th session, 20-session labels ending before 2024; 22,685 examples), seed 0, 10 epochs. Evaluated 2025-01-02..2026-09-18, NAV1, 10/25 bp. The unchanged simulator keeps midcycle entry/exit and FOMC rules.
## result_numbers
10 bp total return / CAGR / DD / Sharpe / annual turnover:
- live-rule reconstruction 399.9% / 157.9% / -31.7% / 2.26 / 16.36x
- neural 242.2% / 106.3% / -37.1% / 1.84 / 20.80x
- equal weight 134.7% / 65.3% / -33.5% / 1.61 / 0.95x
- SPY 31.7% / 17.6% / -18.8%
- QQQ 41.4% / 22.6% / -22.8%

25 bp: live rule 380.4% / 152.0% / -32.2%; neural 226.8% / 100.8% / -37.4%; equal weight 134.1% / 65.0%.

Neural beats the incumbent in 8.7% of 366 overlapping 63-session windows and 0% of 177 252-session windows.

Regime decomposition, candidate minus incumbent log growth (10 bp / 25 bp):
- above mean, high vol (177 intervals): -0.14877 / -0.15078
- above mean, low vol (197): -0.18650 / -0.19308
- below mean, high vol (54): -0.04360 / -0.04156
- below mean, low vol: 0 intervals
## verdict
closed-negative
## caveats
'Do not refit, rescore, change windows or rerun this completed study.' The live-rule reconstruction uses reconstructed grades on current survivors, so the 158% CAGR is not achievable. Raw trade and cash journals were not saved.
--- [22]
## name
Chronological stability of preserved /3 and neural accounts
## date
2026-09-24
## source_doc
docs/research/chronological-stability-2026-09-24.md:1-54
## hypothesis
The /3 advantage over SPY and QQQ is stable across non-overlapping blocks.
## method
Fixed shape before reading: 126 reference, 63 evaluation, 21 label, 5 embargo. Continuous accounts sliced, no refit.
## result_numbers
Incumbent at 10 bp by block, with SPY and QQQ:
- 2025-08-13 -> 11-11: 74.38%; SPY 6.20%, QQQ 7.23%
- 11-11 -> 2026-02-12: 25.84%; SPY 0.04%, QQQ -3.24%
- 02-12 -> 05-14: 46.41%; SPY 10.12%, QQQ 19.99%
- 05-14 -> 08-14: 16.82%; SPY 4.03%, QQQ 1.68%

/3 beats both in 4/4 blocks at both costs. Neural beats the incumbent only in block 4.

Evaluated regimes: 113 above/high, 127 above/low, 12 below/high, 0 below/low.
## verdict
inconclusive
## caveats
Post-hoc and examined. Bearish coverage is thin. 'Do not rerun the completed model, retune the block shape, or present this diagnostic as independent K-fold.'
--- [23]
## name
incumbent-neural-rank-blend/1-research (equal percentile-rank blend of incumbent and price-only neural)
## date
2026-09-24
## source_doc
docs/research/top-tier-strategy-protocol-2026-09-24.md:48-162; docs/NEXT_SESSION.md:3373-3432
## hypothesis
Neural ordering adds incremental information to the rule that already wins. This is an attribution test.
## method
50/50 average of cross-sectional percentile ranks on the common coverage set. All live grades, caps, reset, midcycle, FOMC, funding, deferred buys and execution are unchanged. Forward-only after the protocol; review after 252 completed sessions. Candidate, incumbent, SPY, QQQ and equal weight at 10 and 25 bp on identical sessions. Primary hurdle: higher net total return than incumbent, SPY and QQQ at both costs. Regime attribution with prior-close SPY 200d and 20d vol vs its 252 median.
## result_numbers
None. The code path (backend.market.neural_policy_comparison, neural_study_metrics) is implemented and tested (33 and 85 tests); it does not itself start a run.
## verdict
frozen-pending
## caveats
'Ineligible for adoption by construction.' No regime selector, no trust gate, no feature search. It must not use the defective fundamental/share-unit path. Review is at 252 sessions, with no early stop or date selection.
--- [24]
## name
Fixed 50/50 neural/momentum blend control before any learned scenario selector
## date
2026-09-24
## source_doc
docs/research/learned-price-results-2026-09-24.md:83-87; docs/NEXT_SESSION.md:3866-3869
## hypothesis
A declared fixed blend is the correct control before any learned switcher.
## method
Weights declared before a new forward observation; separate ledger; same execution.
## result_numbers
Not run.
## verdict
planned-not-run
## caveats
A scenario selector needs multiple matured, non-overlapping cohorts. 'Do not ... switch to the recent winner.'
--- [25]
## name
Price-only nested ridge allocation gate (stock basket / SPY / QQQ / cash), frozen market study
## date
2026-09-24
## source_doc
docs/research/nested-market-study-2026-09-24.md; docs/research/nested-market-validation-2026-09-24.md:211-315; docs/research/nested-allocation-runner-2026-09-24.md; docs/NEXT_SESSION.md:2656-2737
## hypothesis
A past-only three-target ridge forecast of five-session gross log-wealth (stock basket, SPY, QQQ; cash is 0) chooses the sleeve well enough to beat the same basket without the gate, /3, SPY, QQQ and equal weight.
## method
22 features (SPY/QQQ 1/5/20/63/126d returns, vol20, log(close/SMA200), log(close/63d max); basket 1/5/20/63d log-wealth, vol, invested fraction). Label: adjusted open t+1 to t+6. Nested: first outer row 1260; outer blocks of 126; three inner blocks of 126; ridge alpha 1 or 100; switch margin 0 or 0.005; minimum 504 rows; selection maximises worst-cost terminal log wealth. Continuous outer account, 2020-01-06..2026-09-18, Sep-18 vintage, NAV1, 10/25 bp. Six accounts.
## result_numbers
10 bp ending wealth / CAGR / closing maxDD / annual gross trading:
- gate 4.0584x / 23.32% / -35.47% / 14.71x
- no-gate adapter 7.9186x / 36.29% / -32.57% / 8.21x
- /3 22.3868x / 59.23% / -37.33% / 13.65x
- SPY 2.5843x / 15.27% / -33.72%
- QQQ 3.4719x / 20.47% / -35.12%
- equal weight 11.2780x / 43.70% / -36.98% / 4.04x

25 bp:
- gate 3.4763x / 20.50% / -36.50%
- no-gate 7.3015x / 34.65% / -33.59%
- /3 19.8579x / 56.40% / -37.58%
- SPY 15.24%; QQQ 20.45%
- equal weight 10.8710x / 42.91% / -37.27%

The gate ends 48.75% / 52.39% below the no-gate adapter.

Fold wins out of 14: vs /3 1; vs no-gate 4 (10 bp) and 3 (25 bp); vs SPY 8; vs QQQ 9; vs equal weight 3 and 2.

252-session window beat rates:
- vs /3: 0.00%
- vs SPY: 59.04% (10 bp), 47.59% (25 bp)
- vs QQQ: 67.27% (10 bp), 59.60% (25 bp)

Regime mean excess vs /3 at 10 bp: -7.03, -11.63, -13.29 and +4.96 bp/day (the last bin has 37 intervals).
## verdict
closed-negative
## caveats
'do not search another model grid on these outcomes and call it an independent test.' The producer was OOM-killed and its root manifest is absent; the result was recovered from verified journals. The gap between /3 (59%) and the no-gate adapter (36%) suggests /3's midcycle entry/exit and funding rules matter, but the two execute differently (INFERRED).
--- [26]
## name
Gate forecast-skill and decision/fill attribution audit
## date
2026-09-25
## source_doc
docs/research/allocation-decision-attribution-2026-09-25.md:52-92,138-143; docs/research/chronological-forecast-diagnostics-2026-09-25.md:72-99
## hypothesis
The gate's forecasts had predictive skill and were undone by execution.
## method
Saved-prediction audit against each target's pre-fit training-label mean over 1,679 overlapping labels. Per-interval intent, fill and return attribution over 1,684 intervals.
## result_numbers
Squared-error skill vs training mean: stock -6.46%, SPY -14.89%, QQQ -15.35%.

Declared modes: 750 stock, 561 QQQ, 348 cash, 25 SPY; 75 switches. Average closing exposure at 10 bp: stocks 30.80%, QQQ 33.06%, SPY 1.14%, cash 35.01%.

Over 348 cash-target intervals: QQQ up 185 / down 163; SPY up 187 / down 159 / tied 2.
## verdict
closed-negative
## caveats
The forecasts had no skill. A next-open sale cannot avoid the overnight gap. 'Do not rerun these diagnostics or retune that gate merely to generate new activity.'
--- [27]
## name
Frozen /3 journal attribution (drawdown exposure and gain concentration)
## date
2026-09-25
## source_doc
docs/research/fixed-strategy-attribution-2026-09-25.md:12-54
## hypothesis
/3 protects on red days by moving to cash or an index.
## method
Independent 50-digit Decimal attribution of the retained /3 10/25 bp journals, 1,684 intervals, 2020-01-06..2026-09-18.
## result_numbers
- Worst closing DD -37.33% / -37.58%: peak 2025-01-23, trough 2025-04-08, recovered 2025-09-05.
- Average exposure in that drawdown: stocks 89.56%, cash 10.44%. SPY 0% throughout; no QQQ position.
- SNDK, DELL, LITE, MU and NVDA supply 66.91% / 68.00% of net gain.
- Largest single-name closing weight: DELL 31.60% / 31.85%.
## verdict
closed-negative
## caveats
'does not demonstrate the user's desired red-day protection through cash or indexes'. Accounting only. 'They are not authorization to optimize repeatedly on this known drawdown.' The 1.10 entry threshold itself was chosen by an in-sample sweep of 0.40-2.00 (paper.py:150-160).
--- [28]
## name
Ex-ante stock-selection plus exposure-selection challenger (operator's clarified objective)
## date
2026-09-24
## source_doc
docs/research/top-tier-strategy-protocol-2026-09-24.md:8-46; docs/NEXT_SESSION.md:3234-3238
## hypothesis
Owning the strongest volatile, fundamentally sound names when conditions favour upside, and moving to cash or an index ahead of deterioration, beats /3, SPY and QQQ.
## method
Specified: select names on expected net upside with sourced point-in-time quality and liquidity. Forecast downside and portfolio outcomes. Compare stocks, SPY, QQQ and cash after switching costs. Fit all preprocessing, calibration and thresholds inside outer-fold training with inner chronological selection and purged endpoints. Compare against selection alone, /3 and funded SPY/QQQ at 10 and 25 bp. Measure missed rallies and false defensive switches.
## result_numbers
Not implemented.
## verdict
planned-not-run
## caveats
'This challenger is not yet implemented or qualified.' It needs a sourced cohort and point-in-time quality data. Indexes are not cash substitutes in a broad selloff.
--- [29]
## name
15-minute microstructure review and a registered-later range/volume entry veto/delay hypothesis
## date
2026-09-25
## source_doc
docs/research/microstructure-15-minute-review-2026-09-25.md:9-155; docs/NEXT_SESSION.md:717-743,854-872
## hypothesis
Keep selection and holding fixed and separately register one completed-bar entry veto/delay using causally normalised range and volume. It could avoid bad entries after costs.
## method
Literature review of TradeFM (arXiv 2602.23784v1) and Mesfin (arXiv 2605.04004v3). The spec requires an unconditional-delay control on the same clock, costs and opportunity set; separate funded accounts carrying their own cash and state; an intraday-capable funded ledger with explicit latency, spread, slippage and missed fills; and the incumbent, SPY and QQQ plus exposure controls.
## result_numbers
- Mesfin: 947 sessions. The London 15-minute control is N=247, +4.09 points, T=4.30. One extra bar of delay gives -2.91 points, T=-2.78. None of 14 signal families passes all gates.
- TradeFM: spread Wasserstein 0.400 vs Hawkes 0.302 vs zero-intelligence 0.375; 15-60 minutes is simulation duration, not a trading horizon.
- Allocation gate losses: 10/14 folds at 10 bp and 11/14 at 25 bp.
## verdict
planned-not-run
## caveats
A signal from the completed 09:30-09:45 bar 'cannot veto a buy already filled at 09:30'; the initial order must be deferred explicitly. Related timing and volume features were already examined in the 09-20 pilot. The rule: 'Do not modify the frozen September 22 reclaim comparison ... the 10-session stock-relative ML specification, or the frozen rank blend.' No threshold or horizon searches.
--- [30]
## name
Intraday baseline-revaluation data scope for funded /3 vs SPY/QQQ at 15-minute marks
## date
2026-09-25
## source_doc
docs/research/microstructure-15-minute-review-2026-09-25.md:138-155; docs/NEXT_SESSION.md:117-131,180-191
## hypothesis
The frozen daily journals can be revalued on 15-minute marks to measure intraday drawdown and entry timing.
## method
Read-only extraction from six verified frozen journals.
## result_numbers
- 77 symbols; 19,316 symbol-session cells; 426 sparse held ranges.
- 2020-01-07..2026-09-18: 500,440 regular-session bars including 12 early closes.
- 481,124 interior cells and 18,901 closing anchors.
- Missing SPY/QQQ account for 3,368 cells.
- Scope file SHA256 7f55f84e...
## verdict
data-blocked
## caveats
'That is not a sufficient challenger dataset.' A challenger also needs causal warm-up, unfilled and skipped opportunities, and prices for holdings outside the incumbent's ranges. None of these has been acquired or qualified. The mixed-provider cache basis check FAILED.
--- [31]
## name
Prospective 10-session stock-relative ML forecast specification
## date
2026-09-22
## source_doc
docs/research/trading-ml-path-2026-09-22.md:90-146
## hypothesis
A stock-relative 10-session forecast improves the existing long-only allocation.
## method
Specification only. Label: next executable open to the open 10 sessions later, minus SPY. Point-in-time data, a locked single model, interval-overlap purge, prospective shadow with a frozen review date, same funded ledger at 10/25 bp, compared against SPY, QQQ, the frozen non-ML allocation and a simple baseline.
## result_numbers
Not run.
## verdict
planned-not-run
## caveats
'do not search 5/10/20 sessions' and 'No model/hyperparameter contest or adaptive best-of selection is authorized.'
--- [32]
## name
Recorded Dip vs incumbent breakout entry-evidence capture (prospective)
## date
2026-09-24
## source_doc
docs/research/entry-evidence-protocol-2026-09-24.md; docs/NEXT_SESSION.md:3688-3701,3631-3636
## hypothesis
A fair future comparison of the research Dip setup (negative stretch / lower band) against the incumbent upper-band breakout.
## method
Each completed 15-minute observation stores the grade, the 20 adjusted closes, band, 21-day EMA stretch and common blockers. Unfunded opinions with a flat position. Later comparison uses 5/20-session horizons at 0/10/25 bp.
## result_numbers
Deployed in aa15c03 (4541 backend tests passed). The first ordinary receipt is UNVERIFIED.
## verdict
frozen-pending
## caveats
Historical personal Buy receipts cannot be reconstructed. Dip is not a Buy instruction, and A+ is not entry timing.
--- [33]
## name
AAOI incident review and current entry-signal census
## date
2026-09-24
## source_doc
docs/NEXT_SESSION.md:3731-3734,3784-3795,2296-2301,2161-2166
## hypothesis
The user's $106 AAOI fill followed a desk Buy.
## method
Read-only source replay and archive audit.
## result_numbers
- Paper fills: 09-11 $107.997097, 09-22 $107.51375, 09-23 $106.70.
- AAOI band 0.08867 on 09-22 and 0.12304 on 09-23, both below the 1.1 threshold even with an assumed A+.
- After repair, entry coverage is 94/95, and all 93 valid readings are below 1.10: zero Buy opportunities at that time.
## verdict
inconclusive
## caveats
The research Dip near $97 is not a funded Buy. 'without dismissing the reported loss or changing rules to fit this one trade'. The incumbent rarely fires (see the paper.py:146-150 note: 61 times a year at 1.25).
--- [34]
## name
Live grade key mismatch and missing held-mark valuation bugs
## date
2026-09-24
## source_doc
docs/NEXT_SESSION.md:3719-3729,3769-3782
## hypothesis
Execution and valuation defects distort live intent and backtests.
## method
Reproduction and fix.
## result_numbers
- decision_view read 'grade' but the key is 'grade_live': six causal upgrade/downgrade cases failed, then fixed.
- A missing held mark produced a false -15.00% loss and a +17.65% rebound (eight failing cases). Now rejected; curves carry the complete-held-marks-v1 tag and older backtest metrics are withheld.
## verdict
adopted
## caveats
Deployed (facbdee / 020ae42). Older published backtest metrics must not be reused.
--- [35]
## name
Expectations-gap historical asof cutoff leakage
## date
2026-09-24
## source_doc
docs/research/expectations-cutoff-2026-09-24.md:41-60,158-173; docs/research/desk-analyst-meaning-2026-09-24.md:219-243
## hypothesis
Reconstructed desk grades (which drive /3's large historical returns) use only data available at each date.
## method
Synthetic future-partition append against the actual desk.run -> challenger.expectations_gap path.
## result_numbers
Under a fixed historical cutoff, appending a later partition changed:
- tone 0.25 -> -0.75
- log P/S 0.530628 -> -0.855666
- market cap 680 -> 1360
- gap close 11 -> 91
All four gap reads received asof=None.
## verdict
adopted
## caveats
Partition selection is fixed (0670fb6). Not fixed: within-vintage revisions, label publication eligibility, dependence on the future calendar or the global-500 cohort, and current membership and sectors. Return inflation for real securities is UNVERIFIED. The finding qualifies the reconstructed /3 returns (59% CAGR 2020-26; 158% CAGR 2025-26) as potentially look-ahead-inflated (INFERRED, per the doc's statement that these gaps 'block qualification of the large reconstructed returns').
--- [36]
## name
Earnings-feature publication timing defect
## date
2026-09-25
## source_doc
docs/NEXT_SESSION.md:1810-1870,1908-1919
## hypothesis
Expectations features precede the release they are meant to forecast.
## method
Actual event mapping plus the EDGAR/_dataset reproduction.
## result_numbers
An 11:00 ET release was assigned to the 16:00 feature row: the feature moved 0.1823215634 -> 0.5877866745 as the target moved 0.2 -> 0.8. The pre-open control stayed at 0.2006706893. Corrected source passes 191 tests.
## verdict
adopted
## caveats
Source only, not deployed. It changes training eligibility, so the old LightGBM expectation results are not comparable.
--- [37]
## name
Expectations naive-baseline unit defect and missing-growth zero-fill
## date
2026-09-25
## source_doc
docs/research/expectations-baseline-scale-2026-09-25.md:3-35; docs/research/expectations-baseline-coverage-2026-09-25.md:10-16
## hypothesis
The historical claim that the LightGBM expectations learner beats a naive baseline is valid.
## method
Synthetic real-path reproduction.
## result_numbers
The naive baseline compared log growth with simple growth: 0.693147 vs 1.0, about 30.685 pp of artificial error. Missing, zero, negative and absent-denominator growth all collapse to feature 0.
## verdict
inconclusive
## caveats
The corrected historical comparison is UNVERIFIED. Old naive-comparison claims are explicitly qualified. The zero-fill still feeds live inputs.
--- [38]
## name
Current SEC source qualification and stale-tag fundamentals
## date
2026-09-25
## source_doc
docs/research/current-sec-qualification-2026-09-25.md:31-111; docs/NEXT_SESSION.md:35-49
## hypothesis
The current desk's F-analyst margins reflect current fiscal periods.
## method
94 company-facts downloads, parser differential and tag trace.
## result_numbers
- 12 of 94 CIKs arrive as padded strings; the old parser refused them.
- 376 cells: 337 finite margins, 39 missing.
- Of the 337 finite margins, 96 reference periods at least 365 days old, 93 at least 730 days and 80 at least 1,825 days.
- AAPL margins reference 2018-06-30. ORCL Revenues ends 2022-05-31 (44 quarters beat 37 current). AMZN gross margin references 2009-09-30.
- All 175,009 rows lack acceptance timestamps.
## verdict
data-blocked
## caveats
'Do not solve this by choosing the newest tag indiscriminately' (AMZN capex definitions differ; ORCL has a duration ambiguity). This is a quality-selection input defect for any 'fundamentally sound' selector.
--- [39]
## name
Connected margin period-date correction (fundamentals-features/2)
## date
2026-09-25
## source_doc
docs/research/live-margin-period-checks-2026-09-25.md; docs/NEXT_SESSION.md:77-115
## hypothesis
Margins must not divide values from different fiscal intervals that share an end date.
## method
Keep start and end intervals and reject unequal or ambiguous spans at the latest shared end.
## result_numbers
238 backend tests and 214 browser cases pass. The old period-mismatch xfail now passes.
## verdict
adopted
## caveats
Source checkpoint ca506e48, not deployed. Old grades and backtests are not corrected. Currency and gapped-annual defects remain strict xfails.
--- [40]
## name
Unit-preserving fundamental sources and period-compatible ratio helper
## date
2026-09-25
## source_doc
docs/research/fundamental-unit-sources-2026-09-25.md; docs/research/fundamental-period-sources-2026-09-25.md
## hypothesis
The legacy unitless versioned facts can be migrated to unit-aware, point-in-time inputs.
## method
Isolated parsers and helpers plus an inventory of retained raw data.
## result_numbers
- A future EUR append erased an earlier USD trailing revenue (460 -> missing).
- ASML: 647 rows (487 EUR, 102 EUR/share, 58 shares).
- Full raw-backed historical reimport FAILED: no raw payloads were retained, and 0 of 4,511 accessions match earnings-event clocks.
## verdict
data-blocked
## caveats
Isolated and unwired. 'Do not relabel unitless caches.'
--- [41]
## name
Historical evidence importer (three-name SEC cohort demonstration)
## date
2026-09-24
## source_doc
docs/research/historical-cohort-2026-09-24.md
## hypothesis
Point-in-time membership, identity and terminal outcomes can be imported from primary sources.
## method
AAPL, SNOW and TWTR over 2020-01-02..2022-11-08 from ten SEC files.
## result_numbers
- 720 sessions and 2,160 rows: 1,975 present, 179 unavailable, 6 absent.
- 0 complete-feature rows: all 8,640 feature cells are unavailable.
- TWTR terminal: $54.20 cash entitlement, unfunded.
## verdict
data-blocked
## caveats
Deliberately selected retrospectively; not training-ready.
--- [42]
## name
Historical opportunity-set coverage audit and fja05680/sp500 membership source qualification
## date
2026-09-25
## source_doc
docs/research/historical-universe-coverage-2026-09-25.md
## hypothesis
Existing or free sources can supply 2015-26 point-in-time membership, identity and delisting outcomes.
## method
Local and Spark inventories, a public-source shortlist (CRSP, Compustat PIT, Norgate at $630/yr, public reconstruction) and a direct fja05680 audit with two S&P primary checks.
## result_numbers
- Spark: 5,556 bar files, 550 stems (the extra 13 are ETFs, not exited stocks); 18,436 dividends and 179 splits; no delisting fields.
- fja05680: 2,720 rows from 1996-01-02 to 2026-08-18. From the 2014-12-24 seed: 771 tickers, 268 absent from today's 503. The 125 add/remove rows for 2019-26 reconcile internally.
- HRS removal on 2019-06-01 contradicts S&P's 06-24 release.
## verdict
data-blocked
## caveats
'Not ready for unbiased historical strategy qualification.' book_panel always calls today's build_universe(). 'Today's discretionary overlay has no historical membership to recover.' 'A mechanical historical eligibility rule would be a separately named, preregistered experiment.'
--- [43]
## name
Legacy allocation RL (market_allocation_rl) policy-gradient cancellation
## date
2026-09-25
## source_doc
docs/research/legacy-allocation-gradient-2026-09-25.md:6-58; docs/NEXT_SESSION.md:1069-1083,1160-1173
## hypothesis
Earlier REINFORCE allocation results were a valid test of learned allocation.
## method
Exact-source autograd check in real Torch.
## result_numbers
The implemented loss L = -A*sum(w.detach()*log p) has gradient dL/dz = 0 (residuals 3.2e-08 in float32, 8.2e-17 in float64). The growth RL pilot was seed-sensitive, lost to momentum controls and lacked QQQ.
## verdict
inconclusive
## caveats
The old RL results cannot count as evidence either way. Any corrected learner needs its own authorized evaluation. /3 is deterministic. LightGBM expectations are live.
--- [44]
## name
Intraday research policy fingerprint omission (regime module)
## date
2026-09-25
## source_doc
docs/research/intraday-policy-fingerprint-2026-09-25.md
## hypothesis
Forward intraday evidence groups correspond to one policy implementation.
## method
Fresh-process variant test.
## result_numbers
Source caps 0.75 and 0.25 gave target weights 0.1125 and 0.0375 under identical policy hashes. The real forward report pooled them.
## verdict
adopted
## caveats
Fixed for new builds only. Whether historical archives contain a mixture is UNVERIFIED.
--- [45]
## name
Extended-hours feed qualification and single historical SIP sample
## date
2026-09-25
## source_doc
docs/research/extended-hours-source-options-2026-09-25.md; docs/research/continuous-price-evidence-2026-09-25.md:293-315
## hypothesis
Existing access supports fresh 04:00-08:00 and 17:00-20:00 ET prices.
## method
Four live SPY probes plus one approved historical SIP request.
## result_numbers
Live probes: SIP 403; IEX 200 with a 0.104 s quote age; BOATS 403; free overnight 200 but over 7 hours old.

SIP sample for 09-24: 3,316 minute bars (bars observed out of 240 premarket and 180 postmarket minutes):
- SPY 893 (228/240, 125/180)
- QQQ 915 (240, 135)
- AAOI 663 (128, 46)
- ORCL 845 (167, 144)

Algo Trader Plus ($99/month) is the documented route to real-time SIP.
## verdict
data-blocked
## caveats
Probe allowances are exhausted. No purchase is authorized. The regular-session strategy is not an extended-hours strategy.
--- [46]
## name
Options OI 'walls' audit
## date
2026-09-25
## source_doc
docs/NEXT_SESSION.md:816-852; docs/research/options-oi-provenance-2026-09-25.md:60-73
## hypothesis
Options OI concentration levels are usable trading inputs.
## method
Offline exact-source reproduction.
## result_numbers
- Raw $100 against adjusted $98 gave -3.061% / +7.143% distances instead of ±5%.
- A 09-01 chain was still accepted on 09-25.
- One malformed expiry reverted two names to evening grades.
- Method: expiries 1-60 days, strikes within ±25%, at least 500 contracts.
## verdict
data-blocked
## caveats
'Keep options out of trading features until source correctness and incremental chronological regime validation qualify them.' These are not gamma exposure.
--- [47]
## name
Research evaluation infrastructure (adapter, journal, nested runner, scorecards, diagnostics)
## date
2026-09-24
## source_doc
docs/research/allocation-adapter-2026-09-24.md; docs/research/accounting-journal-2026-09-24.md; docs/research/nested-allocation-runner-2026-09-24.md; docs/research/archive-buffering-2026-09-24.md; docs/research/chronological-forecast-diagnostics-2026-09-25.md; docs/research/allocation-decision-attribution-2026-09-25.md
## hypothesis
Future challengers need zero-safe stock/SPY/QQQ/cash execution, independently replayable journals, nested fits and fail-closed scorecards.
## method
The adapter (allocation_replay) executes dated instructions: close sizing, next-open fills, no same-batch recycling. The research journal adds an independent replayer. The nested runner does ridge inner/outer selection. neural_study_metrics provides full, rolling and regime scorecards. forecast_diagnostics and allocation_attribution report skill and fills.
## result_numbers
Suites: 526; 292; 674; 1,096; 1,178; and 1,215 tests passing at successive checkpoints.
## verdict
adopted
## caveats
Research-only, with adoption flags fixed at false. There is no real settlement, market-impact or cash-yield model. Do not use harness.evaluate_scores for funded accounting.
--- [48]
## name
PRE-WINDOW REFERENCE: intraday timing (open vs first hour; 15/30/60-minute reversal confirmation)
## date
2026-09-15
## source_doc
docs/research/intraday-timing-2026-09-15.md:69-128
## hypothesis
A better intraday print or confirmation timeframe than the open exists.
## method
1,413 sessions 2021-2026, 93 names, IEX 15-minute bars rescaled to daily adjusted prices. Registered bar: 20 bp with t above 3; reversal bar: +50 bp paired with t above 2.
## result_numbers
Open to later reference (bp): 15-minute close -0.4, 30-minute -0.0, 60-minute -0.6, session close +2.0. Gap-ups fade about 10 bp, not significant.

Reversal confirmation vs open entry (paired):
- 15-minute close above 9-EMA: -0.51% (t -0.8)
- 30-minute: -0.60%
- 60-minute: -1.41% (t -1.7)
- close above prior low: -0.62%
- on meeting days, 60-minute: -2.01% (t -2.1)
## verdict
closed-negative
## caveats
'Decision: the open stays the entry.' The flush cell is degenerate.
--- [49]
## name
PRE-WINDOW REFERENCE: conditional entry-timing pilot (enter / wait 1h / skip; ridge, HGB, GRU)
## date
2026-09-20
## source_doc
docs/research/conditional-entry-pilot-2026-09-20.md:80-122
## hypothesis
Learned intraday entry timing improves five-session outcomes.
## method
Decisions after 10:15-10:30 and 11:15-11:30 bars; top-5 20d momentum names. Validation 2024; test 2025-01-02..2026-09-04; 4,082 opportunities; 10 bp.
## result_numbers
Mean daily improvement vs immediate entry:
- fixed one-hour wait +0.769 bp [-0.278, +1.954]
- ridge +0.012
- trees, 8 inputs -0.189
- trees, 28 inputs +0.234 [-0.289, +0.792]
- GRU +0.142

Allowing skip: trees 60.5% exposure, +192.18%, DD -30.66%; immediate entry +382.29%, DD -35.99%.
## verdict
closed-negative
## caveats
'No robust timing improvement demonstrated.' The skip gains are explained by lower exposure.
--- [50]
## name
PRE-WINDOW REFERENCE: ten-session context experiment (corrected quarterly features for timing)
## date
2026-09-21
## source_doc
docs/research/entry-context-results-2026-09-21.md:1-50
## hypothesis
Point-in-time fundamental context improves entry timing.
## method
Training 2020-23 (63,188 observations); evaluation 2024 and 2025-26; 10 bp.
## result_numbers
Context minus price-only, pooled +0.072 bp/day [-0.130, +0.269]. Skip vs always-enter in the later window: -22.803 bp/day [-40.577, -6.785], at 56.3% vs 86.6% exposure.
## verdict
closed-negative
## caveats
'Do not promote this model, retune on these periods, or escalate to a larger neural model merely because the GPU is available.'
## standing_constraints
Frozen and prohibited items, quoted with source:

1. docs/TRADING_ROADMAP.md (2026-09-15), standing:
- "no tuning on 2024–2026, which every line here has now touched"
- "Any change to the rule runs first as a named shadow beside it for a season, with the gate written before the first session; passing means advancing, and failing means 'insufficient evidence', never a retune on the same sessions."
- "Candidates are welcome as shadows ... None is adopted on a backtest of this universe."
- "no sizing change that cannot be traced to a recorded shadow's untouched sessions; and nothing that reads a private or paid data source."

2. docs/research/claude-review-2026-09-23/day-rotation-2026-09-23.md:78-79: "No live rule that switches the book on the previous day's colour, no daily index rotation, and no retune of the brake bands on 2016–2026."
- REVIEW.md:82: "measure every result against the equal-weighted book, not only SPY and QQQ."

3. docs/research/top-tier-strategy-protocol-2026-09-24.md:
- The price-only neural and GBM rankers "Neither may be retuned, relabelled, or promoted."
- The rank blend: "Review after 252 completed exchange sessions; do not stop or select a date from interim results."
- The primary hurdle is "higher net total return than the unchanged incumbent, SPY, and QQQ at both costs" (10 and 25 bp) on identical sessions. "do not inner join away a missing observation or substitute an uncharged index price series."
- Fit preprocessing, risk forecasts, calibration and thresholds "only within each outer fold's training data, using inner chronological selection and purging actual forward-label endpoints."
- "A signal calculated after the close cannot receive that close's fill"
- "Cash yield must be sourced and dated, or explicitly modelled as zero."
- Regime tables "are attribution tables, not permission to switch strategies by regime."

4. docs/research/microstructure-15-minute-review-2026-09-25.md:107-112:
- "Do not modify the frozen September 22 reclaim comparison (20-session primary / 5-session secondary labels), its separate six-symbol single-source diagnostic, the 10-session stock-relative ML specification, or the frozen rank blend. Examined history cannot become a fresh holdout through more folds. This note does not authorize threshold/horizon searches, new provider calls, fitting, historical reruns, strategy promotion or order placement."
- Any 15-minute entry challenger must include "an unconditional-delay control" and must "explicitly defer the initial order", because "a signal from the completed 09:30–09:45 ET regular-session bar cannot veto a buy already filled at 09:30."

5. docs/research/trading-ml-path-2026-09-22.md:96-112: use "exactly 10 trading sessions ... do not search 5/10/20 sessions"; "No model/hyperparameter contest or adaptive best-of selection is authorized."; "Do not reuse the fixed 2016–2026 comparison as untouched ML evidence."

6. docs/research/intraday-comparison-protocol-2026-09-22.md:13-15,110-113: "No fitting, coefficient search, repeated baseline runs, paid data or UI changes."; "do not shorten the primary horizon to obtain a flattering result."
- intraday-comparison-input-audit-2026-09-22.md:20-22: "Do not fit per-name scale ratios, filter earlier entries using later closing-price disagreements, rescale frozen files".
- intraday-single-source-results-2026-09-23.md:16: "Do not rerun unchanged."

7. Completed studies are frozen:
- learned-price-results-2026-09-24.md:5: "No retuning on this study."
- NEXT_SESSION.md:3506-3507: "Do not refit, rescore, change windows or rerun this completed study" (neural).
- nested-market-validation-2026-09-24.md:313-315: "do not search another model grid on these outcomes and call it an independent test."
- chronological-forecast-diagnostics / NEXT_SESSION.md:1239-1240: do not rerun diagnostics "or retune that gate merely to generate new activity."
- fixed-strategy-attribution-2026-09-25.md:53: "not authorization to optimize repeatedly on this known drawdown."

8. portfolio-exposure-objective-2026-09-21.md:77-93:
- "Historical benchmark drawdowns ... must never enter an earlier decision as a future-informed risk threshold."
- "Distinguish protection from simply holding less risk: include exposure- or risk-matched comparisons. Count false exits, re-entry delay and trading costs."
- "Freeze a small candidate set and its definitions before looking at outcomes; do not mine the reused 2024–2026 sample for winning thresholds."
- Mutual funds such as SWVXX must not be simulated "as an instant-fill ETF".

9. Data and universe:
- historical-universe-coverage-2026-09-25.md:209-212: "Today's discretionary overlay has no historical membership to recover ... A mechanical historical eligibility rule would be a separately named, preregistered experiment."
- current-sec-qualification:180-185: "Do not globally change fa._quarters, learned inputs or frozen studies."
- Legacy unitless caches must not be relabelled (fundamental-unit-sources).
- The FOMC reduction applies only from 2026-06-18 (NEXT_SESSION.md:2926-2928); preserve that policy-era boundary.

10. Operations:
- Deploy only on explicit direction, from Spark via `scripts/deploy.sh --wait-post`, with no gate bypass (NEXT_SESSION.md:1098-1101,2312-2316).
- "Do not run desk_daily.sh manually: it includes paper-account writes" (NEXT_SESSION.md:3878).
- "Do not restart the pending backend" while quote-collector activation is unanswered.
- Authenticated market-data probe allowances are exhausted; no purchase or recurring charge is approved (extended-hours-source-options:100-105).
- The user cannot grant extra laptop or system access (NEXT_SESSION.md:1369).

11. Account separation (NEXT_SESSION.md:4757-4777): paper is its own section; "Never turn paper fills or its rebalance clock into instructions for the user's actual portfolio". "Prefer HOLD when the investment case has not materially changed". "Do not ... choose arbitrary cooldown/band thresholds without validation."

12. Accounting convention for comparisons (trading-ml-path:69-74; top-tier protocol): close decision, next-open execution, NAV1, 10 bp per traded dollar per side plus a predeclared 25 bp stress, zero cash yield unless sourced, funded dividend-inclusive SPY and QQQ, equal weight, and unchanged /3 on identical calendars.
## operator_objectives
Objective history, oldest first:

- 2026-09-14 (desk-rl-readiness-2026-09-14.md:31): "User clarified that maximum cumulative gain, not Sharpe, is the objective." Drawdown and Sharpe are diagnostics; do not add a volatility penalty "that silently changes the user's objective."

- 2026-09-21 (NEXT_SESSION.md:5680-5704, 'User clarified the actual allocation objective'):
  - "defensive allocation during bear markets or unusual shocks (COVID example), including bonds or SWVXX"
  - "Latest user constraint: **SPY and QQQ are the benchmarks for gains and drawdown limits**. Objective: higher net compounded returns with no larger drawdowns than each benchmark separately over identical periods. This replaces the request for an arbitrary 10/15/20% absolute drawdown preference. Do not pick the easier benchmark or a hindsight blend, and never use future benchmark drawdown as a decision input."
  - "User wants stocks at attractive prices, cash/indexes ahead of deteriorating conditions, and prompt participation in recoveries; volatile-stock red days are the key problem. They answered 'I'm not sure' about drawdown tolerance. Do not invent a personal risk limit"
  - "prioritize a shared stock/index/cash exposure layer, including re-entry and execution priority, rather than another small entry-timing model."
  - portfolio-exposure-objective-2026-09-21.md:63-66: "outperform both SPY and QQQ in net compounded returns, with no larger peak-to-trough drawdown than either, on the SAME evaluation window."

- 2026-09-22 (NEXT_SESSION.md):
  - 4781: "forget trading costs try to hit mid price" (the midpoint is a target, not a claimed fill).
  - 4740: "i told you we need precise entries on the 15 min timeframe". Avoiding overtrading means "rejecting weak/repeated signals and unnecessary position churn, NOT replacing 15-minute timing with daily-only entries".
  - 4757-4759: "remember to avoid overtrading, this dashboard will be used by me to make buys in my portfolio. the paper trading is its own section in the dashboard".
  - 4384-4386: the user rejected waiting and asked for the latest tested implementation on the dashboard.

- 2026-09-23:
  - The operator's idea (day-rotation-2026-09-23.md:3-5): "hold the volatile book on its green days and rotate into an index on its potential red days; entering the volatile names at the right time and price is the key."
  - "User uses the board for real decisions" (NEXT_SESSION.md:4302).
  - "prove the entry candidate before adopting it" (NEXT_SESSION.md:4343-4344).

- 2026-09-24:
  - NEXT_SESSION.md:3485-3486: "User clarified the primary objective: maximize total portfolio gain and beat BOTH SPY and QQQ. Drawdown and turnover are diagnostic checks on its quality."
  - top-tier-strategy-protocol-2026-09-24.md:10-13: "own the strongest volatile, fundamentally sound stocks when upside conditions are favorable, and move ahead of deteriorating conditions into cash or an index. This is an **ex-ante allocation problem**, not a hindsight switch between days subsequently labelled green and red."
  - The protocol's evaluation gate: "Total return is the primary objective"; drawdown, turnover and rolling consistency "cannot be hidden by a higher return."
  - NEXT_SESSION.md:3550-3552: the user asked whether other approaches could beat neural or momentum ("neither is established best").
  - The user asked for regime cross-validation, "like cross-validation across regimes" (NEXT_SESSION.md:3828-3834).

- 2026-09-25:
  - NEXT_SESSION.md:854-856: the "user asks about transferring HFT ideas to roughly 15-minute decisions for strong returns with tolerable drawdown, not a latency race."
  - Acceptable peak-to-trough drawdown remains unanswered (NEXT_SESSION.md:238, 479, 871-872): "no answer or guaranteed drawdown limit has been assumed."
  - Two-day target (NEXT_SESSION.md:190-191): "deployment, a qualified baseline report and one testable challenger—not a promise of profitable or best-in-class performance."
  - The user requires overnight, premarket and postmarket prices (display) and cannot grant extra laptop access.

- Current relayed request: improve total return over SPY and QQQ by optimizing entry points and stock choice, like a portfolio balancer plus a 15-minute analogue of an HFT algorithm. Plan first; implement only after a plan of approach.

Net reading: total return versus both SPY and QQQ is primary (09-24), superseding the 09-21 "no larger drawdown" hard constraint. Drawdown stays a reported diagnostic, and the user's tolerance is unknown.
## data_blockers
1. Point-in-time membership:
- No membership_history.csv. book_panel always calls today's build_universe() (historical-universe-coverage:82-92).
- universe.as_of exists but is unused, and its membership file is absent.
- Current constituents: 503 rows dated 2026-09-05, plus a 68-entry overlay.
- The fja05680/sp500 community history qualifies only as a reconstruction seed: it has no announcement clocks, stable IDs or classifications, and it fails a primary-source check (HRS/LHX 2019).
- CRSP, Compustat PIT and Norgate ($630/yr, partial) are unverified and unapproved.
- No delisting returns, successor identities or settlement data.
- The 94-name book is hindsight-picked, with no recoverable history for its overlay.

2. Archived vintages:
- Only 14-16 bar asof vintages exist (2026-09-05..09-24). Older rows are retrospective adjusted restatements.
- The 09-23 snapshot lacks 09-22 for 52 of 96 names.
- Q's 09-22 open is below its low. Q and TYL have OHLC anomalies on 09-18.
- Desk records exist only since 2026-09-04 (13 records). Historical grades are reconstructed, not published.
- learned_inputs captures: 0 as of 2026-09-24 01:14 UTC (prospective only).

3. Intraday (15-minute) data:
- bars_15m/asof=2026-09-20: 530 files, 19.87M rows, 2019-01-02..2026-09-18, extended hours included. IEX single venue, so volume is IEX share only. SPY/QQQ intraday are absent from that partition.
- Cross-provider scale compatibility FAILED (median 0.0280%, p99 9.8341%; AVGO about 10x, WRB 1.5x/2.25x, APTV 0.847).
- No historical quotes, spreads, trade aggressor, depth or queue data. Midpoint fills are unprovable.
- The 15-second collector keeps only latest.json, not an archive.
- Baseline-revaluation scope (500,440 bars, 77 symbols, 3,368 missing SPY/QQQ cells) is not acquired or qualified.
- The funded intraday_evaluation tracks targets but omits scheduled /3 exits. There are no common intraday marks, fills or instructions.

4. Extended hours: SIP and BOATS latest are 403. IEX covers only 08:00-17:00. Overnight quotes are indicative. The one SIP history sample is consumed and probe allowances are exhausted.

5. Fundamentals and tone:
- Legacy versioned facts are unitless, with no raw bytes retained and zero acceptance timestamps across 175,009 rows (filed+1 fallback).
- Longest-history tag selection keeps stale periods: 96 of 337 margins are at least 365 days old (AAPL 2018, ORCL 2022, AMZN 2009).
- Missing growth is zero-filled. Gapped annual periods can derive a false Q4. Currency is lost.
- The neural feature price/share basis is off by ln(10).
- Expectations-gap within-vintage revisions, label-publication eligibility and future-cohort dependence are unfixed.
- Tone is model-generated hindsight with mixed vintages and no immutable release provenance.

6. Consequences for existing results:
- Reconstructed /3 results (59.23% CAGR 2020-26; 157.9% CAGR 2025-26) rest on reconstructed grades with known historical-input leakage. They are "not qualified evidence".
- The nested study producer was OOM-killed and its root manifest is absent.
- Neural-study raw trade and cash journals were not saved.
- Cash yield is zero in the repo harnesses. Only the Claude harness used ^IRX.
- The FOMC overlay applies only from 2026-06-18.

7. Harness discrepancy (INFERRED from the docs; resolve before planning):
- Claude's price-only proxy puts the top-decile hold-20 book at 26-32% CAGR, below equal weight (38-41%).
- The repo's learned-price study puts price-only momentum120 top-10 at 70.5% against equal weight's 39.5% (2019-26). The nested study puts /3 at 59.23% against equal weight's 43.70% (2020-26).
- Conventions differ across the three (universe date, top-N vs decile, vol targeting, caps). So the claim that "equal weight beats every selection rule" is harness-specific, not established.
## open_hypotheses
Recorded as next or promising but not yet tested or finished:

1. QQQ 200-session trend brake (0.97/1.02, halve to cash). Available as the opt-in simulate.run(trend_brake=True) shadow. No shadow run with the desk's real grades is recorded, and the bands may not be retuned.

2. incumbent-neural-rank-blend/1-research. Frozen, forward-only, 252-session review; not started.

3. A fixed 50/50 neural/momentum blend control before any learned scenario selector. Not implemented.

4. Prospective learned rank and brake shadow on captured learned_inputs. Captures were live from 09-24 with the first capture unverified. It needs about 10-20+ sessions of matured labels and minimum training history.

5. Recorded Dip vs incumbent entry-evidence comparison. Capture is deployed; 5- and 20-session outcomes are pending; stress at 0/10/25 bp.

6. The frozen reclaim_above_level/1 candidate. It needs actual dated eligibility, forward observations and enough independent opportunities; the earliest mature primary label is 2026-10-06.

7. Microstructure: one registered completed-bar range/volume entry veto/delay. It needs an unconditional-delay control, an intraday-capable funded ledger with latency, spread and missed fills, and deferral of the initial order. Not launched.

8. A 15, 30 or 60-minute versus daily decision-cadence comparison (a "proposed comparison, not an established optimum"). Cost-aware timing, volatility/liquidity filters and multiscale signals are listed as "feasible research hypotheses" (NEXT_SESSION.md:857-869).

9. Ex-ante stock-selection plus exposure-selection challenger (top-tier protocol). Requires point-in-time quality, downside forecasting, stocks/SPY/QQQ/cash after costs, nested selection, and measurement of missed rallies and false switches.

10. The 10-session stock-relative ML prospective shadow (trading-ml-path spec).

11. vol_trend re-registered with a QQQ-relative budget and hysteresis. Suggested but not registered; run5 gave 24.8-26.2% CAGR at about 30% DD, below A3.

12. A defensive sleeve (cash, money-market such as SWVXX, and bonds) with dealing and settlement modelled, tested against separate abrupt-shock, prolonged-bear, rate-shock and false-alarm scenarios. Contract only.

13. Exposure- and risk-matched controls and a return/downside frontier against both benchmarks. Required by the 09-21 objective and never delivered.

14. A position/holding-period ledger or cooldown for personal guidance, to constrain cross-session repeat entries and add-ons. Identified but not implemented; thresholds must be validated, not chosen arbitrarily.

15. A model-specific trust gate or inverse-uncertainty sizing (Sanderink). Deferred until genuine forward forecast-error history exists.

16. A corrected-input neural retraining (neural_price_basis). A separately named study, not run.

17. A corrected REINFORCE or other learned allocator. Needs its own objective, gradient checks and an authorized leakage-safe evaluation.

18. A mechanical, preregistered historical eligibility rule, plus sourcing PIT membership, identity and delisting data (CRSP, Compustat PIT, Norgate or public reconstruction). Needs an entitlement-specific coverage packet first.

19. A comparable-revenue-concept and current-period selection contract for the live F analyst (stale tags), plus a raw-source retention and reimport path.

20. Cross-stock pooling (Sirignano-Cont) and direct portfolio-objective or implementable-frontier training (Fernandes-Desell; Jensen et al.). Cited as research ideas only.

21. Deciding deliberately between A (lower DD) and A1/deferred buys (higher CAGR, 42.6% DD). This was flagged in the Claude review; deferred_buys is now in LIVE_POLICY. Also check A1 and A3 in the real simulator via repo_simulator_check.py, for which no output is recorded.