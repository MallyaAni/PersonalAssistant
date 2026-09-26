## area
portfolio-balancer-execution
## how_it_works
LIVE INCUMBENT: cash-bounded-breakout-rotation/3 (paper.py:169). Deployed source 68edfc0 contains 15f1b1d4, the commit that bumped /2 to /3 and merged the review fixes (verified with git merge-base; deployment itself is taken from NEXT_SESSION.md:1263-1264,1574 and is otherwise UNVERIFIED).

1) TARGET WEIGHTS: the "book", recomputed every night and traded only at resets.
- desk.assemble ranks names by summed analyst conviction. The four analysts carry weight 1.0 and rotation 0.5 (grading.py:82,93-99).
- It then calls risk.size(scores[last], grades[last], panel, view.today()) (desk.py:308). That runs risk.desk_targets (risk.py:160-192):
  (a) Candidates are names whose SIZE_MULTIPLIER is above 0, which means only A+ and A (grading.py:79; _holdable risk.py:135-141). B names no longer take slots (e550dfff).
  (b) top_fraction 0.1 is rescaled by total/graded, so about floor(0.1 x 93) = 9 names are selected (risk.py:179-183).
  (c) sizing.target_weights (sizing.py:264-303):
    - weight = 1/vol, using 60-session realised vol with a 0.10 floor (sizing.py:280-287), normalised to 1;
    - name cap 0.15 and theme cap 0.40, with the excess redistributed and then enforced by apply_limits (sizing.py:79-141, 352-383);
    - volatility target: scale = min(0.30 / the realised 60-session vol of the weighted basket, correlation included, 1) (sizing.py:296-299, book_volatility 310-320);
    - max_gross 1.0.
  (d) Each target is multiplied by the grade multiplier (1) and by regime.exposure: 1.0 normally, 0.75 in a hype phase or while money is tightening (regime.py:49,72,298-316; risk.py:189).
  (e) While tightening, weights are re-tilted by 1/vol^(2-1) and re-capped (risk.py:236-264).
- `held` is never passed (desk.py:308, simulate.py:444). sizing.rebalance's speed 0.5 and min_trade are therefore never applied to the desk book.

2) PAPER PLAN, once per session (paper.plan paper.py:662-835; the sessions_seen guard is at 704-705).
- RESET when sessions_since_rebalance+1 >= 20, on the first session, or when forced (745-749):
  - planner.plan (planner.py:60-87) sizes each name to target x equity at the decision close and skips any move under 0.5% of NAV, on both sides (planner.py:54). Names that leave the book are sold.
  - _rebalance_orders rounds to the nearest whole share, drops legs under MIN_TRADE, and drops buys of band-blocked names (paper.py:484-524).
- MID-CYCLE, between resets (772-829):
  (i) Deferred retry: last session's unpaid buy shares are re-issued once, only for names still A/A+, not being rotated out and not band-blocked, inside the 15% cap and at least 0.5% of NAV (_deferred_orders 558-604).
  (ii) Rotation: held names graded below A are sold (market_daily._downgraded 537-563). The sale value goes pro rata to the other held, unblocked names up to the 15% cap; legs under 0.5% are dropped (_rotation_orders 348-418).
  (iii) Breakout entries: A/A+ names with entry.bollinger_z >= 1.10 on the half-sigma scale, i.e. 2.2 sigma (entry.py:60-68; market_daily._price_entries 566-595). Size = 0.023 x (band/1.25)^2, which is 1.78% at the trigger and about 7.0% at the sqrt(19)/2 ceiling, capped at 15% minus the current weight (paper.py:181-185, 422-475). Entries are paid from cash only.
- CASH BOUND:
  - Buys are funded from cash on hand only, because sells fill at the following close (midcycle_orders 640-648).
  - bound_orders re-caps each buy at 15% of NAV at the decision price and scales all buys to cash using floored shares (842-862; _fund_buys 530-549).
  - Unpaid shares go into state.deferred_buys (834).
- BUY BLOCKER: the exit analyst's signal, (band position >= 0.95 AND a bearish candle) OR (band width rank >= 0.90 AND band position >= 0.80) (exit.py:86-126; bands.py:15-17). It blocks buys and adds only; sells pass.

3) EXECUTION (market_daily._paper_trade 639-808; _submit 389-472). The nightly run is after the close.
- Ordinary sells go out as MOC orders (time_in_force "cls") for the NEXT session's close (market_daily.py:436-448; alpaca_trading.py:279-296).
- Buys, event sells and priority sells go out as market DAY orders queued for the next open. They fill at the first print, not the opening auction; "opg" was dropped on 2026-09-08 (alpaca_trading.py:239-271).
- Orders are refused if the clock is unknown or the market is open.
- The intent is written to state.pending before sending (736-740). Reconciliation runs through settle/apply_settlements (paper.py:926-1072); a rebalance with a dead leg rolls the clock back (1068-1071).
- event_execution.plan (the FOMC cycle: 0.5 exposure for 3 pre-sessions; event_risk.py:17-20) replaces paper.plan whenever state.pending is set, an event is active, or the calendar is unknown (market_daily.py:696-699).
- Sizing prices come from panel.close at the last row, raw (656-660); equity is account.equity.
- Every 15 minutes, market_balancer._green_day_skip_locked (132-211) runs. Between 09:30 and 11:00 ET it cancels pending non-event, non-priority MOC sells when the current 15-minute bar's open is above the record's last close. The candle must be 30 minutes old or less (109-120, 144, 173-175). The cancelled leg is journaled SKIPPED, which counts as done (paper.py:899-902, 1088-1115).

4) COSTS AND CASH
- The simulator charges 10 bp per side on notional (simulate.py:59): buy spend is notional x (1+c) and sale proceeds are notional x (1-c) (_Book._fill 1557-1573).
- Cash yields zero everywhere: simulate _Book, allocation_evaluation.py:61 CASH_INCOME=0.0, allocation_controls.py:21. The Alpaca paper account also pays nothing.
- SPY and QQQ comparators are funded accounts:
  - allocation_controls.constant_exposure(fraction=1) (98-196): decision at close t, fill at the t+1 open, buys bounded by cash, NAV starts at 1;
  - or benchmarks.load_benchmark (133-192): buy once at the first next-open with cost, mark at adjusted closes, no liquidation.
  - Both are run at 10 and 25 bp (nested_allocation.py:29).

5) SIMULATOR (simulate.run 643-1297)
- Ledger of shares plus cash. The decision at close t is sized by planner.plan at the t close (_Book.plan 1468-1493) and filled at the t+1 adjusted open (adjusted_open 315-319).
- LIVE_POLICY (72-78) has five flags:
  - block_overbought: _gated_targets 458-466;
  - exit_at_close: _fill_split 1619-1637 fills opening buys from existing cash, then closing sells at closes[t+1];
  - green_day_skip: sells are held when opens[t+1] > closes[t] (1239-1252);
  - live_midcycle: calls paper.midcycle_orders with whole_shares=False (116-168);
  - deferred_buys: _unpaid_buys 174-186, _deferred_leg 192-218, carry logic 1191-1215.
- The published curve is market_daily.curve_block (1219-1291): use_exits=False, rebalance=20, FOMC lifecycle, **LIVE_POLICY.
- The opt-in trend brake (trend_brake.py:19-21, 0.97/1.02; brake_scale 0.5) sets a per-session minimum with the FOMC path and pauses mid-cycle buys while risk_off (simulate.py:856-861, 1183-1213).

6) FUNDED PATH (research, unwired)
- allocation.decide (allocation.py:383-611):
  - caps names at 15% and at the regime cap; SPY takes the residual only if index_eligible (447-453);
  - portfolio risk = max(std20, std60) x sqrt(252) of the weighted basket (260-266);
  - budget = min(SPY, QQQ) risk x multiplier by default (145-160);
  - scalar = min(budget/risk, ceiling/candidate_sum, 1), where the ceiling is min(regime, event, trend);
  - trend = the fraction of SPY/QQQ above their 200-session mean, with a -3%/+2% hysteresis (274-328).
- funded_execution.plan_funded (649-791):
  - buys come from cash on hand only;
  - one 0.5% min-trade applies on both sides, except full exits and genuine risk cuts (is_risk_cut 390-399; 409-434);
  - whole shares round to nearest with a 0.5+0.01 share no-trade band (541-555);
  - both sides are next-open.
- Reachable only through paper.plan(allocation_context=...) (706-733), and nothing passes one.

7) PERSONAL BOARD (live API): decision_view.build (723-974)
- entry_action (553-615) uses the same trigger and size.
- A Buy is suppressed after a same-day recorded fill or a working order passed as pending_buys (_entries_taken 620-636).
- _personal_midcycle_orders (255-297): covered downgrade exits, and cash-bounded entries with no rotation recycling.
- An optional risk budget caps the add at (budget / support_distance) - current weight (personal_risk.py:120-131).

8) SIMULATOR VS LIVE
Structurally matched since /3: both call risk.desk_targets, planner.plan, paper.midcycle_orders, _deferred_orders and _fund_buys, and both apply the same gates. Remaining differences:
- continuous vs whole shares (simulate.py:139-160 whole_shares=False);
- official open vs first print after the open;
- the green-day rule reads the IEX 9:30 bar open (live) vs the consolidated open (simulator), and in live it applies only if the 15-minute job runs between 09:30 and 11:00;
- the live event path also takes over whenever an order is still pending;
- live rolls the rebalance clock back when an order is refused;
- zero cash yield on both sides;
- the simulator uses reconstructed grades rather than point-in-time grades.
## parameters_and_constants
Status labels: LIVE = in the paper account path; CURVE = the published simulator curve; RESEARCH = unwired; DEAD = never reaches the desk book.

INCUMBENT BOOK (LIVE)
- paper.REBALANCE_EVERY = 20 (paper.py:68).
- paper.MIN_TRADE = 0.005 (paper.py:69); planner.MIN_TRADE = 0.005 (planner.py:25).
- paper.ENTRY_BAND_Z = 1.10 on the half-sigma scale, i.e. 2.2 sigma (paper.py:160).
- ENTRY_ADD = 0.023 (166) and ENTRY_SIZE_REF = 1.25 (173). Size = 0.023 x (band/1.25)^2, from 1.78% up to about 7.0%.
- ENTRY_NAME_CAP = 0.15 (167). It is a buy-time cap only; holdings are not capped.
- ENTRY_MIN_GRADE = (A, A+) (168).
- risk.BOOK_CONFIG: top_fraction 0.1, target_volatility 0.30, name_cap 0.15 (risk.py:48-50).
- SizingConfig: volatility_lookback 60, min_volatility 0.10, theme_cap 0.40, max_gross 1.0 (sizing.py:51-64). SizingConfig.speed 0.5 and min_trade 0.005 are DEAD on the desk path (desk.py:308 and simulate.py:444 pass no `held`).
- TIGHTENING_POWER = 2.0 (risk.py:57).
- SIZE_MULTIPLIER: A+ 1, A 1, B 0, C 0 (grading.py:79).
- ANALYST_WEIGHTS equal, rotation 0.5 (grading.py:82,93-99). RIDGE_WEIGHTS (100-106) is RESEARCH.
- regime HYPE_EXPOSURE 0.75 (regime.py:49) and TIGHTENING_EXPOSURE 0.75 (72).
- FOMC cycle (event_risk.py:17-20): REDUCED 0.5, PRE_SESSIONS 3, GUIDANCE_CHANGE 2026-06-18.
- Buy blocker (exit.py:86-93): NEAR_TOP 0.95, WIDE 0.90, UPPER_FIFTH 0.80. Bands: WINDOW 20, SIGMA 2, WIDTH_HISTORY 250 (bands.py:15-17).

ORDER TYPES AND INTRADAY RULES (LIVE)
- Buys: market DAY order queued for the open (alpaca_trading.py:263).
- Sells: MOC "cls" for the next session's close (292).
- Green-day skip window 09:30-11:00 ET (market_balancer.py:144); the bar must be 1800 s old or less (119).
- live_quotes RECHECK_SECONDS = 60 (live_quotes.py:29).
- execution_quotes MAX_AGE_SECONDS 30 and MAX_SPREAD_BPS 25 (execution_quotes.py:13-14). These are personal and display eligibility.

SIMULATOR (CURVE)
- simulate.REBALANCE 20, REDEPLOY True, COST_BPS 10, MIN_TRADE 0.005, START_EQUITY 1 (simulate.py:55-61).
- LIVE_POLICY flags (72-78).
- The run() defaults are use_exits=True with every LIVE_POLICY flag False (643-675). These are not the live configuration.

TREND BRAKE (RESEARCH/SHADOW, simulate plus learned_research only)
- LOOKBACK 200, ENTER_BELOW 0.97, EXIT_ABOVE 1.02 (trend_brake.py:19-21).
- brake_scale 0.5 (simulate.py:672).

FUNDED ALLOCATION (RESEARCH, no caller of allocation_context)
- allocation: VOL_SHORT 20, VOL_LONG 60, TREND_WINDOW 200, ANNUAL 252 (allocation.py:58-61).
- Budget reference default "min", i.e. min(SPY, QQQ) risk, with multiplier 1.0 (51, 395-396).
- TREND_BELOW -0.03 and TREND_ABOVE +0.02 (274-275).
- funded_execution: SHARE_BAND 0.5 and _BAND_TOL 0.01 (541-542); entry_cap 0.15; min_trade 0.005 (659-660).
- Its stable composition still applies BOOK_CONFIG's 30% volatility target (funded_execution.py:198-223).

EVALUATION (RESEARCH)
- allocation_evaluation (56-63): COMMON_START 2016-01-04, COMMON_END 2026-09-18, COST_BPS 10, CASH_INCOME 0.0, RISK_CUT_POINTS 0.10, RISK_CUT_RECOVER 0.90.
- allocation_controls: COST_BPS 10 and zero cash yield (53-56).
- nested_allocation (29-44): COSTS (10, 25), STOCK_CADENCE 20, first_outer 1260, outer 126, inner 3 x 126, min_train 504, alphas (1, 100), switch margins (0, 0.005).

OTHER
- portfolio_candidate (RESEARCH, intraday candidate only): LOOKBACK 60, MIN_OBSERVATIONS 40, CORRELATION 0.8, CLUSTER_CAP 0.30 (portfolio_candidate.py:5-9).
- board_paper (forward synthetic ledger, active only if desk/board-paper was initialized): SLIPPAGE 0.001 per side beyond bid/ask, MIN_TRADE 0.005 (board_paper.py:25-29).
- backtest.py (RESEARCH, single name): STOP_BUFFER 0.03, PATIENCE 10, ATR 20 x 3 (backtest.py:29-37).
- actions (display only): DELTA_FLOOR 0.005, STOPS (0.08, 0.12, 0.20) (actions.py:42-45).
## measured_results
IN-CODE AND DOC MEASUREMENTS
All of these are on the survivor-biased, hindsight-picked universe.

1) Reset cadence (paper.py:53-56). A 20-session reset beats 120:
- +3.49 CAGR and +0.129 Sharpe at 10 bp;
- +2.17 CAGR at 30 bp;
- better in 12 of 12 start phases.

2) Entries (paper.py:90-106). Upper tail only versus both tails:

| Window | CAGR | Worst phase | Sharpe | DD | Turnover |
|---|---|---|---|---|---|
| From 2021 | 47.43% | 40.52% | 1.354 | -45.33% | 5.49x |
| From 2018 | 34.12% | — | 1.178 | -42.19% | — |

- The calendar book with no entries: 34.38% CAGR, Sharpe 1.468, DD -30.04%.
- Paying entries from cash: +1.3 CAGR (paper.py:117). The account had been 43% invested and 57% idle.

3) Entry trigger (paper.py:127-131):
- The band trigger versus the 15% rule, from 2021: 50.60% vs 48.42% CAGR.
- The band fires after a 14.1% run and captures 2.7% of what follows.
- 1.10 vs 1.25: +2.31 CAGR at 10 bp and +1.55 at 30 bp; deployed share went 72% to 76% (paper.py:152-158).

4) Rotation (paper.py:328-343):
- Rotating instead of holding: +3.42 CAGR at a 20-session reset.
- Selling a downgrade to cash instead: -24 CAGR.

5) Volatility target and tilt (risk.py:36-47; 51-56):
- Raising the target from 0.25 to 0.30: +3.5 / +2.0 CAGR in the two windows.
- 0.40 is rejected: drawdown -43.03% vs -34.89%.
- The tightening tilt: Sharpe 1.47 to 1.65, drawdown -38.3% to -34.6%.

6) Grade ladder (grading.py:39-78):
- Flat vs ladder from 2021: 58.42% vs 51.23% CAGR.
- Dropping B: -0.37 CAGR at 10 bp, +0.18 at 30 bp.

7) Analyst weights (market_weights.py:77-87): equal weights 27.2% vs walk-forward ridge 25.0% from 2018.

8) RL sizing (risk.py:104-107): rule 0.611 vs REINFORCE 0.579. The REINFORCE arm used a zero-gradient loss (legacy-allocation-gradient-2026-09-25.md), so that comparison is invalid.

9) Better volatility forecasts (sizing.py:231-234): Sharpe 1.85 to 1.82, no gain.

10) Exit at close plus green-day skip (NEXT_SESSION.md:8257-8261):

| Variant | CAGR | Vol | Sharpe | DD |
|---|---|---|---|---|
| Sell at open (baseline) | 25.1% | 16.5% | 1.440 | -25.7% |
| Exit at close alone | 24.3% | — | 1.379 | — |
| Exit at close + green-day skip | 36.0% | 25.6% | 1.332 | -28.4% |

The green-day version also made 81 fewer trades.

11) Review proxy (run3.csv), 2016-26, 10 bp, T-bill yield on cash:

| Strategy | CAGR | Max DD | Avg exposure | Turnover |
|---|---|---|---|---|
| SPY | 15.3% | 33.7% | 100% | — |
| QQQ | 20.4% | 35.1% | 100% | — |
| A live-like | 26.3% | 33.7% | 62% | 9.4x |
| A1 + deferred leg | 31.6% | 42.6% | 82% | 13.5x |
| A3 + QQQ 200-day brake | 29.9% | 31.6% | 75% | — |
| A4 vol cap 1.25x QQQ | 24.7% | — | — | — |
| vol (as built) | 17.2% | 33.6% | 51% | — |
| vol_trend (as built) | 14.8% | 23.5% | 40% | — |

12) Review proxy (run5.csv):
- A3q, parking the brake's cut in QQQ: 31.96% CAGR, DD 42.7%, exposure 84%.
- vol_trend with hysteresis, a QQQ x1.5 budget and SPY residual: 24.8% CAGR, DD 30.7%.
- The same with QQQ x2 and no residual: 26.2% CAGR, DD 30.3%.

13) Day rotation (run4.csv): green/red switching returned -1.8% CAGR at 214x turnover.

14) Repo simulator with proxy grades under LIVE_POLICY (commit 08ac4d89):
- 30.1% CAGR, DD 50.1%;
- with the brake, 26.7% CAGR, DD 44.4%.

15) Nested study, 2020-01-06 to 2026-09-18 (nested-market-validation-2026-09-24.md:227-240):

| Account | CAGR at 10 bp | CAGR at 25 bp | Notes |
|---|---|---|---|
| /3 | 59.23% | 56.40% | DD -37.3%, gross trading 13.65x |
| Equal weight | 43.70% | 42.91% | |
| Stock-only adapter | 36.29% | — | |
| Ridge gate | 23.32% | — | rejected |
| QQQ | 20.47% | — | |
| SPY | 15.27% | — | |

16) Chronological blocks: /3 beats SPY and QQQ in all 4 post-2025 blocks (chronological-stability-2026-09-24.md).

17) Attribution (fixed-strategy-attribution-2026-09-25.md):
- 67% of net gain comes from SNDK, DELL, LITE, MU and NVDA.
- The largest closing weight was DELL at 31.6%.
- Stock exposure during the worst drawdown averaged 89.6%.

18) Opportunity and cash (opportunity-and-cash-2026-09-18.md):
- The desk score's rank IC is 0.0457 (t 3.21); the quintile spread is 1.46% per 20 sessions.
- All 6 risk-off conditions were followed by above-average 20-session returns.

19) Intraday timing (intraday-timing-2026-09-15.md):
- The open is as good as any first-hour print; nothing reached 20 bp at t > 3.
- On +2% gap-ups the price fades 9 to 12 bp in the first hour (t about -1.4).
- Every confirmation entry was worse than the open.

MY PROXY COMPUTATIONS (INFERRED)
These ran in memory with python3.7 on docs/research/claude-review-2026-09-23/px.npz, 2016-2026, 94 names. Nothing was written.

1) The 30% book volatility target (proxy: top decile by 6-1 month momentum, inverse vol, 15% cap):
- binds at 59% of 135 rebalances;
- median scale 0.91, mean 0.80, p25 0.62;
- the median top-decile book vol is 33% (p75 48.5%).

2) The min(SPY, QQQ) 60-day vol budget:
- median 12.9%;
- median scale 0.39, which matches the review's finding 1.

3) Overnight vs next-day intraday returns, per-session cross-sectional means:

| Group | Overnight | Next-day intraday |
|---|---|---|
| Top-decile momentum | +21.4 bp (t 6.33) | +4.1 bp (t 0.86) |
| Breakout fires (bz >= 1.10) | +6.9 bp (t 1.97) | +6.2 bp (t 1.10) |
| All names | +10.0 bp (t 4.75) | +4.8 bp (t 1.77) |

4) The wide-band blocker stops 10% of breakout fires. Their 20-session forward return (+2.91%) is no different from unblocked fires (+3.05%). Breakout fires return +3.07% against +2.91% unconditional, a weak per-name edge.
## wiring_status
LIVE NIGHTLY PAPER PATH
market_daily._run → paper_trade → _paper_trade (market_daily.py:639-808).

1) _reconcile (settle/apply_settlements) runs first.

2) Then either event_execution.plan (during an FOMC cycle or while orders are pending) or paper.plan runs, as the incumbent /3 with no allocation_context (market_daily.py:696-714). Its inputs:
- targets = report.book (desk.py:308 via risk.size);
- finished = _downgraded;
- entries = _price_entries;
- entry_blocked = _band_blocked;
- cash = account.cash.

3) _submit sends ordinary sells as MOC orders for the next close and buys as next-open DAY orders.

4) The deferred buy leg (95d14e64) and the B-slot fix (e550dfff) are LIVE in /3, since 15f1b1d4 is in deployed 68edfc0 (NEXT_SESSION.md:1263-1264).

PUBLISHED CURVE
market_daily.curve_block runs simulate.run with LIVE_POLICY, the FOMC lifecycle and rebalance 20 (1219-1291).

LIVE EVERY 15 MINUTES (market_balancer.run 226-346)
- holdings.board top_buys;
- live.json snapshot;
- intraday_research.publish (research targets, never orders);
- board_paper.observe, a synthetic forward ledger that is active only if desk/board-paper was initialized (runtime status UNVERIFIED);
- _green_day_skip, which cancels MOC sells on the paper account;
- market_event_recovery.

LIVE API
- /desk/mine → decision_view.build and apply_personal_account_plan; execution is manual.
- funding.preview (api/v1/market.py).
- execution_quality (display).
- personal_history (encrypted receipts).

SHADOW / RESEARCH ONLY
- allocation.decide, funded_execution, paper_allocation: reachable only via paper.plan(allocation_context=...), and nothing in the repo outside tests passes one.
- trend_brake: simulate.py and learned_research.py only.
- allocation_replay and nested_allocation: market_nested_study.py via nested_market_study.
- allocation_evaluation and allocation_controls: market_allocation_compare and market_strategy_bench.
- allocation_attribution and allocation_view: the latter returns "unavailable" unless allocation_plan exists.
- portfolio_candidate: intraday_candidate only.
- desk/backtest.py: market_desk CLI.
- market_weights, market_position, market_rotation: research CLIs.

DEAD
- decision_view.apply_account_plan (decision_view.py:23-108): no non-test caller.
- intraday_entry.SESSION_CLOSE (intraday_entry.py:97): unused.
- SizingConfig.speed and min_trade on the desk path.

2026-09-23 REVIEW FINDINGS AT HEAD (fix commits dated 2026-09-23, merged in 15f1b1d4)

- F1, volatility budget caps returns: PARTIAL.
  - 7edbe54b added budget_reference and budget_multiplier (allocation.py:47-55, 145-160, 395-396), but the default is still min(SPY, QQQ).
  - The path is unwired, so this is latent. The proxy median exposure scale is still 0.39.
- F2, personal board repeats Buy: FIXED, with a caveat.
  - 8c470f04 added the fix; f8494501 replaced the issued-Buy memory with suppression only after a recorded same-day fill or a working order in pending_buys (decision_view.py:620-646, 814-815).
  - The frontend records last_buy_date (DeskPanel.tsx:224-226) but never sends pending_buys (no match in frontend/src), so a working order the person has not recorded still re-prompts.
- F3, whole-share churn: FIXED.
  - 3469f822: nearest rounding with a half-share band (funded_execution.py:535-584).
  - 981a65ee: genuine risk cut only (390-399).
  - 46e0c72a: labels.
  - The churn test asserts zero reversals over 250 sessions. The path is unwired.
- F4, idle cash from sells-at-close: MOSTLY FIXED and LIVE.
  - 95d14e64 and 39fec3bb added the deferred leg (paper.py:226-233, 552-604, 834; simulate.py:1191-1215).
  - The residual idle cash is covered under defects.
- F5, lopsided min-trade thresholds: FIXED in the funded path (981a65ee, funded_execution.py:409-434). The incumbent planner was already symmetric (planner.py:54).
- F6, comparison not like for like: PARTIAL.
  - The nested study now runs /3 through simulate with LIVE_POLICY against funded SPY and QQQ at 10 and 25 bp on common dates.
  - Cash yield is still 0 (allocation_evaluation.py:61).
  - The funded path still targets volatility twice (funded_execution.py:198-223 then allocation.py:519-525).
  - The compare CLI baseline still reads the incumbent from a reference NPZ (allocation_evaluation.py:23-28).
- F7, quote lag: FIXED (b47d8b2a, live_quotes.py:97-126).
- F8, early closes hard-coded to 16:00: FIXED in intraday_entry, intraday_replay, intraday_single_source and live_quotes via calendar.session_close (calendar.py:138-140). Residual hard-codes, low severity, are listed in the defects.
- F9, vol_trend hysteresis: FIXED (4f697d84, allocation.py:274-312).
- F10, B-graded names take slots: FIXED and LIVE (e550dfff, risk.py:135-141, 178-183).
- F11, intraday research: REMAINS. The single-source diagnostic has 0 paired entries, 5 incumbent and 1 candidate (intraday-single-source-results-2026-09-23.md).
- F12, redundancy: PARTIAL.
  - Docstrings were corrected in df24a11f.
  - apply_account_plan is still dead.
  - simulate.run defaults still differ from live; this is now only documented (simulate.py:678-684).
## defects
--- [0]
## title
Structural under-investment: the 30% volatility target and the 0.75 regime exposure set reset targets well below the held gross
## location
backend/agents/trading/desk/risk.py:48-50,189; backend/market/sizing.py:296-299; backend/agents/trading/desk/regime.py:49,72; decision_view.py:520-524
## severity
high
## evidence
Targets are the vol-scaled inverse-vol book times the regime exposure. decision_view.py:520-524 records a live night on which the book held 43% of equity against targets summing to 22%. Each 20-session reset trims toward those targets and cash-funded entries then rebuild exposure, a sawtooth. Proxy (INFERRED): the 30% target binds at 59% of rebalances with a mean scale of 0.80, and 0.75 is applied on top in hype or tightening phases. Repo evidence says exposure is what pays in this universe: the deferred leg is worth +5 CAGR (run3 A to A1), the green-day skip took CAGR from 24.3% to 36.0% (NEXT_SESSION.md:8257-8261), and every risk-off condition preceded above-average returns (opportunity-and-cash-2026-09-18.md).
## effect_on_return_or_risk
Average exposure is about 62-82% in the proxies, so the idle 18-38% earns zero against a fully invested SPY/QQQ. INFERRED drag of several CAGR points in exchange for a lower drawdown (A: DD 33.7% at 26.3% CAGR vs A1: DD 42.6% at 31.6%).
--- [1]
## title
Reset trims are cancelled by a noisy intraday coin flip rather than an explicit hold rule, and holdings are not capped
## location
backend/cli/market_balancer.py:132-211 (window at 144, open-vs-close test at 173-175); paper.py:448,584,852 (15% cap applied to buys only); paper.py:899-902 (SKIPPED counts as done)
## severity
medium
## evidence
Any non-priority MOC sell, including reset trims of winners and downgrade rotations, is cancelled when the IEX 9:30 bar opens above the record's last close. The rebalance then counts that leg as done, so the name stays over target until the next reset (20 sessions later) or a downgrade. The reconstruction held DELL at 31.6% of the account (fixed-strategy-attribution-2026-09-25.md). The simulator uses the official open (simulate.py:1242-1248), and live applies the rule only if the 15-minute job runs between 09:30 and 11:00 with a bar at most 30 minutes old (market_balancer.py:109-120).
## effect_on_return_or_risk
This is return-positive in hindsight (+11.7 CAGR measured), but it rests on a random gate: roughly half of trims are skipped depending on the opening tick. That leaves concentration uncontrolled (66.9% of net gain came from 5 names) and creates parity risk between the IEX open and the consolidated open.
--- [2]
## title
The deferred leg retries once, only for names still A-graded and unblocked, then drops the remainder
## location
backend/agents/trading/desk/paper.py:552-604, 743-744, 834
## severity
medium
## evidence
_deferred_orders skips names that are blocked, finished or no longer A. The remainder is cleared after one retry. Rotation proceeds are routed pro rata to existing holdings (paper.py:399-417) and can only be paid the next day. A green-day skip leaves less cash than the plan assumed, so part of the retry goes unfunded and is then dropped.
## effect_on_return_or_risk
Some sale proceeds sit idle until the next breakout or the next reset. INFERRED: a fraction of the roughly 5 CAGR the deferred leg recovers in the proxy is still lost.
--- [3]
## title
The funded volatility budget still defaults to min(SPY, QQQ), which is SPY-level risk
## location
backend/agents/trading/desk/allocation.py:51,145-160,395-396; funded_execution.py:292-293
## severity
medium
## evidence
The default is BUDGET_MIN with multiplier 1.0; 7edbe54b only parameterised it. Proxy (INFERRED): the min(SPY, QQQ) 60-day vol median is 12.9% against a top-decile book vol of 33%, a median scale of 0.39. The stable composition is already scaled to BOOK_CONFIG's 30% target (funded_execution.py:198-223), so volatility is targeted twice.
## effect_on_return_or_risk
It is latent because the path is unwired. Adopted as is it roughly halves CAGR (vol 17.2% and vol_trend 14.8% vs QQQ 20.4%, run3.csv).
--- [4]
## title
Simulator vs live parity gaps remain in the fills
## location
simulate.py:139-160 (whole_shares=False), 1216-1219, 1239-1252; alpaca_trading.py:239-271; market_daily.py:656-660, 696-699, 752-758
## severity
medium
## evidence
Six differences remain: (1) continuous shares in the simulator vs whole shares live; (2) the official open vs the first print of a queued DAY market order on the paper venue; (3) the green-day rule reads the consolidated open in the simulator but the IEX bar open live, and live depends on the 15-minute job running; (4) event_execution takes over whenever state.pending is non-empty; (5) a refused order rolls the rebalance clock back live; (6) the simulator uses reconstructed rather than point-in-time grades. Zero cash yield is shared by both.
## effect_on_return_or_risk
The published curve can overstate what the account achieves. The size of the gap is unmeasured; execution_quality splits drift from slippage but no simulator-vs-account reconciliation exists.
--- [5]
## title
Dead turnover-control knobs on the desk path
## location
backend/agents/trading/desk/desk.py:308; simulate.py:444; risk.py:184; sizing.py:61-63,429-448
## severity
low
## evidence
desk_targets accepts `held` and would apply sizing.rebalance (speed 0.5, min_trade 0.005, full exits), but no caller passes it. BOOK_CONFIG therefore advertises speed 0.5, and the nested study freezes it as config (nested-market-study-2026-09-24.md), yet it has no effect.
## effect_on_return_or_risk
No direct cost, but the config is misleading and an existing partial-rebalance lever that could cut return-destructive trims goes unused.
--- [6]
## title
Dust positions under 0.5% of NAV survive a zero target
## location
backend/agents/trading/desk/planner.py:54-55
## severity
low
## evidence
target_shares returns held_qty when |Δvalue| < min_trade x equity, including when the target is 0. The allocation-adapter doc confirms small stale holdings are retained.
## effect_on_return_or_risk
Negligible return effect; small unmanaged residuals clutter the book.
--- [7]
## title
Residual hard-coded 16:00 closes
## location
backend/market/alpaca.py:211; record_status.py:23; execution_quality.py:50; intraday_preflight.py:65; intraday_entry.py:97 (unused)
## severity
low
## evidence
alpaca.sessions includes bars after 13:00 on early-close days in its 15-minute session features. record_status and execution_quality treat 16:00 as the close.
## effect_on_return_or_risk
Mislabelled freshness and polluted research features on about 3 sessions a year. No order impact found.
--- [8]
## title
The frontend never sends pending_buys
## location
backend/market/decision_view.py:620-636; frontend/src (no pending_buys)
## severity
low
## evidence
Buy suppression works only after the person records a fill (DeskPanel.tsx:224-226).
## effect_on_return_or_risk
A working but unrecorded manual order still shows Buy on the next candle, which risks a double buy in the personal account.
--- [9]
## title
The RL-allocation conclusion in risk.py relies partly on a defective learner
## location
backend/agents/trading/desk/risk.py:90-129
## severity
low
## evidence
The REINFORCE arm (+0.579) used a loss with identically zero gradient (legacy-allocation-gradient-2026-09-25.md). The cross-entropy arm is unaffected.
## effect_on_return_or_risk
The claim that learning the allocation is worth nothing is weaker than stated; it does not by itself imply a better allocator exists.
--- [10]
## title
Zero cash yield in every comparison and ledger
## location
allocation_evaluation.py:61; allocation_controls.py:21; simulate._Book (no interest)
## severity
low
## evidence
The incumbent carries 18-38% cash (proxy) while SPY and QQQ are fully invested. The review proxy used the T-bill yield; the repo does not.
## effect_on_return_or_risk
This understates a real account's return by roughly the idle fraction times the T-bill yield (INFERRED, about 1 CAGR in 2023-26). The paper account itself earns nothing.
## improvement_opportunities
--- [0]
## idea
Benchmark-residual balancer: fill all residual equity with QQQ, or an SPY/QQQ mix, instead of cash, holding the stock picks as active overweights
## rationale
Exposure is the dominant return driver here. Cash never forecast better returns (opportunity-and-cash), the deferred leg alone added +5 CAGR, and parking the brake's cut in QQQ (A3q) beat cash, 31.96% vs 29.92% CAGR (run5.csv). A residual sleeve also makes the book's worst case look like QQQ plus the stock picks' active return, which is the objective against QQQ.
## where_it_plugs_in
Research first. Build allocation_replay AllocationInstruction(stock_scale, spy_weight, qqq_weight, stock_weights, rebalance) from simulate._targets or risk.desk_targets, with qqq_weight = max(0, 1 - sum(stock)). Then add a `residual_index` option to simulate.run after book.plan (simulate.py:1177) and to paper.plan after bound_orders (paper.py:832-834). allocation.decide already supports an SPY residual (allocation.py:447-453) to generalise to QQQ.
## reusable_code
backend/market/allocation_replay.replay(panel, instructions, first=, cost_bps=, journal=); nested_allocation.run(...) for chronological folds; allocation_controls.constant_exposure for the SPY/QQQ controls; research_journal.ResearchJournal plus market_verify_journal for independent checks; benchmarks.load_benchmark.
## expected_effect
INFERRED +2 to +5 CAGR against a cash residual in proxy terms. Average exposure rises from about 62-82% to about 100%; drawdown moves toward A1's 42.6% unless a brake is added.
## risks
Higher drawdown and beta. QQQ overlaps the book (NVDA, AVGO, MU...) and raises concentration. Resizing the sleeve daily adds turnover, so use a ±2-5% band. Funding a stock buy by selling the sleeve depends on Alpaca same-session buying power (margin vs cash account; UNVERIFIED). It must be judged on untouched sessions, and against the equal-weight book as well as SPY and QQQ.
--- [1]
## idea
Decouple risk from gross exposure: keep the 30% volatility target for the stock sleeve but send the scaled-off weight to QQQ; or weight the selected names equally or by rank instead of inverse vol
## rationale
The volatility target binds at 59% of rebalances (proxy mean scale 0.80). Inverse-vol weighting underweights the highest-vol names, which in this universe were the biggest winners. Equal weight on the same names matched the rule's Sharpe (risk.py:104-105), and a flatter grade ladder raised CAGR 7 points (grading.py:47-50).
## where_it_plugs_in
sizing.target_weights (sizing.py:287 weights = 1/vol; 296-299 the vol scale). Expose them as research-only SizingConfig variants and run them through the simulate.run allocator hook (`allocator(report, panel, config, t)`, simulate.py:686-689).
## reusable_code
risk.desk_targets(scores, graded, panel, regime, config, held); sizing.apply_limits; simulate.run(..., allocator=...); the market_allocation_compare scorecard.
## expected_effect
INFERRED +1 to +4 CAGR with a QQQ-like volatility floor. A 1.25x QQQ vol cap without a residual measured worse (A4 24.7% vs A1 31.6%), so the residual is essential.
## risks
Raising the target to 0.40 measured DD -43% vs -34.9% (risk.py:42-47). Concentration in a few high-vol names. Fitting to 2024-26 winners is prohibited by the protocol.
--- [2]
## idea
Replace calendar trims and the green-day coin flip with explicit tolerance bands and a rank buffer
## rationale
Trims are where return leaks: the green-day skip, which cancels about half of sells at random, added +11.7 CAGR (NEXT_SESSION.md:8257-8261). A deterministic version is standard practice (buy/hold rank buffers; Novy-Marx & Velikov 2016). Buy only into the top decile, keep held names while they are in the top quintile and A-graded, trim a winner only above a hard cap (e.g. 20-25%) or a relative band (e.g. above 2x target), and exit immediately on a downgrade.
## where_it_plugs_in
risk.desk_targets: add held-aware candidate hysteresis via `held` (risk.py:160-192). Per-name bands go in planner.target_shares (planner.py:42-56) and paper._rebalance_orders (484-524). Once measured, retire or narrow _green_day_skip (market_balancer.py:132-211).
## reusable_code
sizing.rebalance(held, target, config) already implements speed, min_trade and full exits (sizing.py:429-448) and only needs `held` passed; simulate.run's green_day_skip flag gives the A/B baseline.
## expected_effect
INFERRED: much of the green-day gain with lower variance, turnover below the current 13.65x gross, and explicit concentration control (DELL reached 31.6%).
## risks
A hard cap trims the winners that produced 67% of gains. The band widths are new parameters that must be predeclared and not tuned on 2024-26.
--- [3]
## idea
15-minute close-auction entry: decide on the completed 15:30-15:45 bar and submit MOC buys for the same session's close, capturing the overnight drift
## rationale
Proxy (INFERRED): top-decile momentum names earn +21.4 bp overnight (t 6.3) against +4.1 bp intraday (t 0.9), and breakout fires +6.9 bp (t 2.0), consistent with momentum returns accruing overnight (Lou, Polk & Skouras 2019). Buys currently fill at the first print of t+1 and forgo that gap. Sells already wait for the t+1 close. This is the useful form of an HFT-like 15-minute engine here: execution timing, not intraday round trips, because intraday drift is about zero and every confirmation-based intraday entry measured worse (intraday-timing-2026-09-15.md).
## where_it_plugs_in
The market_balancer candle job at 15:45 ET, gated by calendar.session_close (early closes). Provisional grades and bands come from live_technical.with_live_row and entry.bollinger_z; orders go through alpaca_trading.submit_market_on_close (Alpaca's MOC deadline is roughly 15:50 ET; verify). In the simulator, add a `buy_at_close` flag beside exit_at_close with buy_prices = closes[t] but the decision on the 15:45 IEX bar price (never the 16:00 close) to keep it causal.
## reusable_code
intraday_replay.SessionSchedule and ExecutionProxy (publication-time aware); intraday_entry._completed_bars and evaluate; live_technical.with_live_row(panel, quotes, today); board_paper.transition for a forward 15-minute shadow; execution_quality for measured slippage; execution_evidence.decision_shortfall_bps.
## expected_effect
INFERRED +0.5 to +1.4 CAGR (about 6.8x NAV of buys a year times 7-21 bp), before losses from signals that flip between 15:45 and 16:00.
## risks
IEX-only 15-minute bars (thin, back to 2016); MOC imbalance and paper-venue fill semantics; cash timing (the same session's sells are also at the close); the grade and fundamental read is not final at 15:45. Requires a new frozen protocol and an untouched-session shadow.
--- [4]
## idea
Stronger redeployment: persist deferred buys until filled or superseded, and route rotation proceeds to the top-ranked A names below target (or the QQQ sleeve) instead of pro rata to existing holdings
## rationale
Proceeds currently follow existing position sizes (paper.py:399-417) and are dropped after one retry (paper.py:834).
## where_it_plugs_in
paper._rotation_orders, _deferred_orders and plan (paper.py:348-418, 552-604, 772-834), mirrored in simulate._live_midcycle and _deferred_leg (116-218).
## reusable_code
paper.midcycle_orders, _fund_buys and bound_orders; simulate.LIVE_POLICY (add a versioned flag).
## expected_effect
INFERRED +0.3 to +1 CAGR from fewer idle days.
## risks
More turnover; entries chasing names the blocker would reject.
--- [5]
## idea
Gap-aware opening execution for buys
## rationale
Names gapping up 2% or more fade about 9-12 bp in the first hour (t about -1.4, not significant; intraday-timing-2026-09-15.md), and a queued DAY market order takes the first print on the paper venue.
## where_it_plugs_in
_submit (market_daily.py:436-456). For buys where the pre-open quote shows a gap of +2% or more, use a 30-60 minute TWAP from the 15-minute job, or a limit at the prior close plus a band with a fallback.
## reusable_code
execution_quotes.fetch and describe; execution_quality (drift vs slippage split); live_quotes.
## expected_effect
Small, about 5-10 bp on affected orders (INFERRED); mainly a cost-control and measurement gain.
## risks
Not statistically significant; risk of missing fills on strong breakouts.
--- [6]
## idea
Honest cash accounting: model the T-bill yield in the simulator and comparisons, or hold a T-bill ETF for the residual when a QQQ residual is not used
## rationale
All ledgers assume zero yield (allocation_evaluation.py:61), which understates the incumbent relative to a real account.
## where_it_plugs_in
_Book.equity and mark in simulate.py (1385-1392), allocation_controls.constant_exposure and allocation_replay, driven by ^IRX (already in the review px.npz) or a stored series.
## reusable_code
benchmarks._aligned_prices pattern; allocation_controls.
## expected_effect
About +1 CAGR at 20-30% idle and a 4-5% yield (INFERRED); not an edge over QQQ.
## risks
Needs a point-in-time rate source; the paper account itself earns nothing.
## reuse_inventory
LEDGERS AND SIMULATORS
- simulate.run(report, since=None, config=None, rebalance=20, cost_bps=10, use_exits=True, redeploy=True, allocator=None, dip=None, exits=None, grace=20, entry_gate=False, block_overbought=False, band_dip_buy=False, trend_gated_exit=False, trim=1.0, exit_at_close=False, green_day_skip=False, event_exposure=None, event_lifecycle=False, live_midcycle=False, deferred_buys=False, funded_allocation=False, allocation_policy='vol_trend', index_eligible=False, benchmark_prices=None, excluded_symbols_by_session=None, trend_brake=False, brake_scale=0.5, brake_path_override=None, journal=None) -> SimResult (simulate.py:643).
  - Always pass **simulate.LIVE_POLICY, use_exits=False, rebalance=paper.REBALANCE_EVERY, event_exposure=event_risk.live_path(panel) and event_lifecycle=True to describe the live book (market_daily.py:1233-1240).
  - SimResult.stats() (simulate.py:256-310) returns cagr, drawdown, turnover and max_weight.
- simulate._Book (simulate.py:1303-1683): shares plus cash with _fill(order, prices, recycle_sells), settle_split(order, buy_prices, sell_prices, session, reason, sell_at_close, recycle_sells) and plan(target, prices).
- simulate.adjusted_open(panel) (315-319).
- allocation_replay.replay(panel, instructions, *, first=0, cost_bps=10.0, start_equity=1.0, journal=None) with AllocationInstruction(session, information_through, evidence_id, stock_scale, spy_weight, qqq_weight, stock_weights=None, rebalance=False) (allocation_replay.py:33-44, 247). This is the ready-made stock/SPY/QQQ/cash research ledger.
- nested_allocation.run(panel, regression, stock_weights, *, protocol=NestedProtocol(...)) (412): expanding-window nested chronological selection with one continuous account.
- allocation_controls.constant_exposure(closes, opens, fraction, cost_bps=10, *, journal=None, sessions=None, symbol=None) (98): funded SPY/QQQ controls.
- allocation_controls.adjusted_open(open, close, adj) (79).
- benchmarks.load_benchmark(store, symbol, sessions, cost_bps=10, start_equity=1, asof=None) -> BenchmarkSeries (133).
- research_journal.ResearchJournal (research_journal.py:136) and the market_verify_journal CLI: independently replayable audit journals.
- board_paper.transition(state, decisions, research, now) and observe(root, record, snapshot, research) (board_paper.py:88, 245): a forward 15-minute bid/ask ledger with a two-candle confirmation and no same-candle recycling.

ORDER PLANNING AND SIZING
- planner.plan(targets, held, equity, prices, min_trade=0.005) -> [Order] (planner.py:60).
- paper.plan(session, state, equity, held, prices, targets, grades, finished=None, force_rebalance=False, entry_blocked=None, entries=None, cash=None, allocation_context=None) (paper.py:662).
- paper.midcycle_orders(session, state, equity, held, prices, grades, finished, entries, blocked=None, cash=None, whole_shares=True, unfunded=None) (610).
- paper.bound_orders(orders, held, prices, equity, cash, unfunded=None) (842).
- paper._fund_buys (530), paper._deferred_orders (558), paper.entry_size(band) (181).
- paper.settle / apply_settlements / skip_sell (926, 1009, 1088).
- risk.desk_targets(scores_today, graded_today, panel, regime, config=BOOK_CONFIG, held=None) -> (positions, targets) (risk.py:160).
- sizing.target_weights(scores, volatility, themes, tickers, config, history=None) (sizing.py:264).
- sizing.apply_limits(weights, themes, tickers, name_cap, theme_cap, gross) (112).
- sizing.rebalance(held, target, config) (429).
- sizing.book_volatility (310), sizing.realised_volatility(panel, lookback) (254).
- funded_execution.plan_funded(decision, held, prices, equity, cash, *, cost_bps=10, whole_shares=False, index_eligible=False, entry_cap=0.15, min_trade=0.005) -> FundedPlan (funded_execution.py:649).
- funded_execution.whole_share_gap(gap) (550) and is_risk_cut(decision, held, priced, equity, min_trade) (390).
- allocation.decide(dates, prices, tickers, t, desired, held, regime_cap, event_cap, policy='vol_trend', index_eligible=False, *, budget_reference='min', budget_multiplier=1.0) -> AllocationDecision (allocation.py:383).
- trend_brake.risk_off_path(qqq, lookback=200, enter_below=0.97, exit_above=1.02) and aligned_qqq(panel_dates, benchmark_prices) (trend_brake.py:28, 58).
- portfolio_candidate.calculate(panel, weights), a correlation-cluster cap (portfolio_candidate.py:13).

SIGNALS AND GATES
- entry.bollinger_z(close, window=20) (entry.py:60).
- exit.evidence(panel).signalled() (exit.py:132-150), used as the buy blocker.
- bands.position and width_rank (bands.py:40, 79).
- baselines.momentum, residual_momentum, percentile_rank and rank_blend (baselines.py).

INTRADAY AND EXECUTION
- live_technical.with_live_row(panel, quotes, today) (live_technical.py:93) and entry_now (806).
- intraday_entry.evaluate(...) and session_close_for (intraday_entry.py:520, 641).
- intraday_replay.SessionSchedule and ExecutionProxy (intraday_replay.py:112, 190).
- calendar.session_close(day) (calendar.py:138).
- execution_quality (drift vs slippage split); execution_evidence.decision_shortfall_bps(side, fill, ref) (execution_evidence.py:56); paper.close_shortfall_bps (paper.py:989).
- alpaca_trading.AlpacaTradingClient.submit_market_on_open, submit_market_on_close and cancel_orders (paper endpoint only, alpaca_trading.py:250, 279, 203).
- personal_risk.build(...) (personal_risk.py:36) and funding.preview(rows, equity, cash) (funding.py:24).

WALK-FORWARD
- harness.walk_forward_folds and evaluate_scores, as used by market_weights.
## open_questions
1) Are the reconstructed historical grades point-in-time? /3 returned 59% CAGR in 2020-26 against 43.7% for equal weight; the review's price-only proxy found equal weight beating every selection rule. The fundamental and earnings-tone reconstructions (local LLM tone, as-of EDGAR) are labelled unaudited (nested-market-study, fixed-strategy-attribution). Until this is settled, how much of the edge over equal weight is real is UNVERIFIED.

2) What is the typical live gap between rebalance target gross and held gross? The only data point is a code comment (22% vs 43%, decision_view.py:520-524). The paper state.json and desk records live on Spark and were not read here.

3) Does the Alpaca paper account run as a margin account, and can proceeds of a same-session sell fund buys? This matters for a QQQ residual sleeve and for close-auction entries. UNVERIFIED.

4) What are Alpaca's MOC submission and cancel cutoffs on the paper venue? The 15:45 entry idea needs them.

5) Does the green-day rule actually fire on the live account on most sessions, given it depends on the 15-minute job running between 09:30 and 11:00 and on IEX vs SIP open prices? It needs a reconciliation between the intraday.log "green-day skipped" lines and the simulator.

6) Is board_paper initialized (a desk/board-paper directory on Spark)? If so, it already holds a 15-minute forward ledger of the research targets.

7) Was a QQQ residual for general idle cash, as opposed to only the brake's cut, ever measured on the repo simulator? No artifact was found.

8) How much of the +11.7 CAGR from the green-day skip survives whole shares, the IEX open, and the post-2021 window alone? The figure was measured on a pre-/3 build (2026-09-11).

9) The proxy overnight/intraday split used Yahoo adjusted OHLC reconstructed from 1 bp log returns on a survivor universe. It needs replication on the store's raw bars and IEX 15-minute bars before any design relies on it.

10) Every improvement needs a predeclared protocol and an untouched-session shadow, per the repo's "no tuning on 2024-2026" rule. The equal-weighted book must be a mandatory comparator alongside funded SPY and QQQ at 10 and 25 bp.