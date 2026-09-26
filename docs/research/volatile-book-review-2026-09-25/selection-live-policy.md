## area
selection-live-policy: how the incumbent 'cash-bounded-breakout-rotation/3' picks, enters, exits and rebalances
## how_it_works
ENTRY POINT AND CADENCE. The nightly `backend/cli/market_daily.py:_run` (1486-1609) runs after the close. It refreshes data, calls `trading_desk.run(store, asof)` (1510), then `paper_trade` (1526-1535 -> `_paper_trade` 639-808) under a file lock (`paper.transaction`, paper.py:267-278). Every decision is made once per session on the daily close; the same session cannot be planned twice (paper.py:704-705). Orders are submitted after the close: buys as market-on-open (MOO) for the next session, and ordinary sells as market-on-close (MOC) for the next session (market_daily.py:436-456). FOMC event orders and priority orders go MOO. The only live intraday logic is `backend/cli/market_balancer.py`, which runs every 15 minutes. It cancels a pending MOC sell when the name's first regular-session candle is up on the prior close (the "green-day skip", 124-210 -> `paper.skip_sell` 1088-1115) and recovers missed FOMC reductions. It never initiates a buy.

UNIVERSE. `desk.book_panel` (desk.py:98-105) takes `universe.book_sides` (universe.py:343+). This is the OVERLAY names plus S&P members in the Semiconductor, Semi Equipment, Communications Equipment, Application Software and Systems Software sub-industries. It gives 94 names: 68 tagged 'ai' and 26 tagged 'software' (computed from the committed constituents.csv). Benchmark column SPY (universe.py:68).

THE ANALYSTS (desk.run, desk.py:152-224). Each analyst returns an `Opinion` (opinions.py:41-83) with a (T,N) score.
(1) Fundamental (`fundamental.opine_corrected`, fundamental.py:93-120). It averages the cross-sectional percentile ranks of revenue_yoy, revenue_qoq, gross_margin and revenue_acceleration, needing at least 2 finite legs. Source: as-of filing versions (desk.py:239-285).
(2) Technical (technical.py:122-183). It takes `rank_blend` (baselines.py:123-128, an unweighted mean of percentile ranks, NaN if any leg is NaN) of:
- weekly_trend, ternary {-1,0,1} (levels.py:175-181)
- daily_trend, ternary (levels.py:182-188)
- residual momentum over 120 sessions skipping 21, beta over 120 sessions, divided by residual volatility (`baselines.residual_momentum`, 152-170)
- a fourth leg that switches on the AI basket's 60-session return (regime.py:235). When it is >0, the leg is 60-session range position (levels.py:172-174). Otherwise it is the negative of the 20-day Bollinger band position (STRETCH_LEG="band", technical.py:77, 148-151).
(3) Sentiment (sentiment.py:64-77). It is the `rank_blend` of four LLM earnings-release tone fields (guidance, demand, guidance_change, pricing), each -1/0/1. The value is carried unchanged from the reaction date until the next release (language.py:275-313).
(4) Value (value.py:34-62). Size-neutral cheapness of log P/S against the side median (P/S uses the latest quarter's revenue x4, levels_pit.py). Live, this is blended 50/50 by `nanmean` of ranks with the walk-forward "expectations gap" (challenger.py:94-111; desk.py:140-141, 208-224).
(5) Rotation (regime.py:206-283). Score = (AI residual basket minus software residual basket, 60-session sum) x side sign (+1 for AI, -1 for software), so every name on a side ties. It is blanked on every session where AI participation is below its 2-year median (regime.py:254-256, _judge 299-305).

STANCES AND CONVICTION (opinions.py). A stance is +1 in the top 30% of ranks and -1 in the bottom 30% (STANCE_FRACTION=0.3, line 15). A new stance must repeat for 3 consecutive sessions before it replaces the old one (PERSISTENCE=3, `persist` 87-96). Conviction = sign(2r-1)*|2r-1|^(1/2) (SHARPNESS=2, 102-106), which is continuous and has no persistence.

GRADES (grading.py:231-274). votes = f + t + s + v + 0.5*r (ANALYST_WEIGHTS 93-99, ROTATION_WEIGHT=0.5).
- B: votes >= 0.5.
- A: votes >= 2, OR (sentiment bullish AND votes >= 1), OR (fundamental AND technical bullish AND votes >= 1.5).
- A+: sentiment bullish AND votes >= 2.
- Veto: any bearish stance among fundamental, technical, sentiment or value caps the grade at B (269-273). Rotation cannot veto.
- SIZE_MULTIPLIER is A+=A=1.0 and B=C=0 (line 81). So only A and A+ are holdable, and A+ carries no extra weight.
Rotation tie arithmetic (computed from percentile_rank on 68/26 ties): when AI leads, AI names rank at 0.640 (neutral) and software at 0.134 (bearish). When software leads, software ranks at 0.866 (bullish) and AI at 0.360 (neutral). The rotation vote can therefore never be bullish for an AI-side name.

RANKING AND BOOK (desk.assemble 289-319 -> risk.size -> risk.desk_targets 160-192). Ordering score = the summed conviction (grading.py:263-267 via as_scores 128-131; the `blended` tie-break computed at desk.py:306 is ignored whenever conviction exists).
- Candidates are A/A+ names only (`_holdable` 135-141).
- top_fraction 0.1 is rescaled by total/graded (178-183), so the book is floor(0.1*94) = 9 names, or every A name if there are fewer than about 9.4.
- Sizing (`sizing.target_weights` 264-303) uses BOOK_CONFIG (risk.py:48-50): inverse 60-session volatility (floor 0.10), normalised to 1; name cap 0.15; theme cap 0.40 over overlapping themes (apply_limits 112-141); then scaled by min(1, 0.30 / realised 60-session book vol under the candidate weights) (294-299).
- Then multiplied by regime exposure. Exposure is 1.0, or 0.75 when AI participation is at or above its trailing 2-year 80th percentile (hype), or 0.75 while the 10-year yield has risen more than 10% relative over 60 sessions (tightening). These take the minimum, not the product (regime.py:49, 57-72, 306-317).
- While tightening, inverse vol is squared and caps are re-applied (risk.py:57, 236-264).
INFERRED: the target gross at a reset is roughly 0.30/book-vol x exposure, well below 1. The code says the account ran 43% invested before cash-funded entries (paper.py:118-120) and 72-76% deployed after them (paper.py:156).

PAPER PLAN (paper.plan 662-835), called with targets, grades, `finished`=_downgraded, entries=_price_entries and entry_blocked=_band_blocked (market_daily.py:701-714).

(a) RESET. It runs when sessions_since_rebalance+1 >= REBALANCE_EVERY=20 (paper.py:68, 745-749), on a forced run, or on the first session.
- `planner.plan` (planner.py:60-87) moves every held-or-target name to its target weight, skipping moves under MIN_TRADE=0.5% of equity.
- Held names with no target are sold ("leaves the book"), including A-graded names outside the top 9.
- Buys in `entry_blocked` are skipped (paper.py:494-495) and are not retried.
- Buys are rounded to the nearest share, capped at 15% including holdings, and paid only from existing cash (`bound_orders` 842-862). Sells fill on the next close, so buys they would fund cannot fill at that open.
- The unpaid remainder becomes `deferred_buys`, retried once at the next session's open, only if still graded A and not blocked (558-604, 774-800).
- A reset that is refused or does not fully fill rolls the clock back (paper.py:1068-1071; market_daily.py:752-758).

(b) BETWEEN RESETS (midcycle_orders 610-652), each night:
- Deferred retry first.
- ROTATION (_rotation_orders 348-418). Any held name graded below A (market_daily._downgraded 537-563) is sold MOC. The proceeds are spread across the remaining holdings in proportion to their current market value, capped at 15% of equity. Legs under 0.5% are dropped, and blocked names receive nothing.
- BREAKOUT ENTRIES (_entry_orders 422-475). A name qualifies if it is graded A/A+, is not rotating out, is not blocked, and has entry.bollinger_z = (adj close - SMA20)/(2*population std20) >= ENTRY_BAND_Z=1.10, i.e. 2.2 sigma (market_daily.py:566-595; entry.py:60-68; paper.py:160).
- Entry size is `entry_size` = 0.023*(band/1.25)^2 (paper.py:166, 173, 181-185): 1.78% of equity at the trigger, up to about 7.0% at the band's mathematical maximum sqrt(19)/2 = 2.18, capped at 15% minus the current weight. It is paid from existing cash only and ignores regime exposure and the volatility target.
- All buys are scaled down together if cash is short (_fund_buys 530-549).

(c) BUY BLOCKER. `exit.evidence(panel).signalled()` (exit.py:106-108, market_daily.py:602-616) fires when either (bands.position >= 0.95 AND a shooting-star or bearish-engulfing candle), or (20-day band width rank against its own 250-session history >= 0.90 AND position >= 0.80). A breakout at z >= 1.10 has position (z+1)/2 >= 1.05. So a breakout is blocked whenever the band is in its top width decile or the day printed a bearish candle.

(d) NO PRICE EXITS. There are no stops and no band exits (exit.py:1-74 is retired). The only exits are the grade rotation and the reset.

EVENT GATES.
- FOMC (event_risk.py; VERSION "fomc-3-session-weakness/2"). When the next decision is 1-4 sessions away (PRE_SESSIONS=3, window at distance 1..4) and SPY's 5-session return is below zero, the factor becomes REDUCED=0.5 and stays reduced through the decision session (exposure_path 106-136, decision 75-102).
- market_daily routes the whole night to `event_execution.plan` whenever state.pending is non-empty, an event cycle is active, factor==0.5, or the calendar is unknown (market_daily.py:695-699).
- An event cycle sells 50% of the snapshot shares at the next open. It then restores confirmed sold shares at the open after the decision, cash-limited with a 1% allowance (event_execution.py:29-127).
- During the cycle there are no rotations, entries, deferred retries or resets. The reset clock keeps counting (event_execution.py:114-119).
- `fomc_gate.py` only writes the counterfactual.

TREND BRAKE. The QQQ 200-session state machine (off below 0.97x the mean, back on above 1.02x; trend_brake.py:19-21) exists only as a `simulate.run(trend_brake=True)` option and in learned_research. It is not in the paper path.

BACKTEST = LIVE. `simulate.LIVE_POLICY` (simulate.py:72-78) sets block_overbought, exit_at_close, green_day_skip, live_midcycle and deferred_buys to True. It replays the same paper functions (`_live_midcycle` 116-168 calls paper.midcycle_orders), and resets call the same risk.desk_targets (431-452).
## parameters_and_constants
LIVE (paper account path):
- paper.py:68 REBALANCE_EVERY=20 (also actions.py:41 REBALANCE)
- paper.py:69 MIN_TRADE=0.005; planner.py:25 MIN_TRADE=0.005
- paper.py:160 ENTRY_BAND_Z=1.10 (2.2 sigma)
- paper.py:166 ENTRY_ADD=0.023
- paper.py:173 ENTRY_SIZE_REF=1.25, entry exponent 2 (paper.py:185)
- paper.py:167 ENTRY_NAME_CAP=0.15 (also caps rotation, deferred and rebalance buys)
- paper.py:168 ENTRY_MIN_GRADE=(A, A+)
- paper.py:169 POLICY_VERSION
- grading.py:81 SIZE_MULTIPLIER A+=1, A=1, B=0, C=0
- grading.py:82 ROTATION_WEIGHT=0.5
- grading.py:93-99 ANALYST_WEIGHTS all 1.0 (RIDGE_WEIGHTS 100-106 are research only)
- grading.py:254-261 thresholds: B at votes 0.5; A at votes 2, sentiment-bullish plus 1, or f&t-bullish plus 1.5; A+ at sentiment-bullish plus 2
- grading.py:269-273 veto on a bearish f/t/s/v
- opinions.py:15 STANCE_FRACTION=0.3
- opinions.py:19 PERSISTENCE=3
- opinions.py:38 SHARPNESS=2.0
- technical.py:36-37 MOMENTUM 120/skip 21
- technical.py:77 STRETCH_LEG="band"
- levels.py:34 SWING=5, 35 LEVEL_LOOKBACK=250
- fundamental.py:27 four scored legs, at least 2 required (fundamental.py:111)
- sentiment.py:54 four tone legs
- value.py:28 price_sales, size_neutral=True (value.py:38); expectations gap blended (desk.py:140-141 LIVE_INPUTS)
- regime.py:39-72: PARTICIPATION 20/250, ROTATION_SESSIONS=60, HISTORY_SESSIONS=500, LOW_CONFIDENCE=0.5, HYPE_EXPOSURE=0.75 (at or above the 80th percentile, 306-308), TIGHTENING_RISE=0.10 over 60 sessions, TIGHTENING_EXPOSURE=0.75
- risk.py:48-50 BOOK_CONFIG top_fraction=0.1 (rescaled to about 9 names), target_volatility=0.30, name_cap=0.15; theme_cap=0.40, volatility_lookback=60, min_volatility=0.10, max_gross=1.0 (sizing.py:48-64 defaults)
- risk.py:57 TIGHTENING_POWER=2.0
- exit.py:89 NEAR_TOP=0.95, 92 WIDE=0.90, 93 UPPER_FIFTH=0.80 (used only as the buy blocker); bands.py WINDOW=20, SIGMA=2, WIDTH_HISTORY=250
- event_risk.py:17-20 VERSION, PRE_SESSIONS=3, REDUCED=0.5, 5-session SPY weakness trigger (85-86, 127-132); event_execution.py:123-127 1% cash allowance
- market_daily.py:436-456 sells MOC, buys MOO
- market_balancer green-day skip: first candle at or after 09:30, at most 1800 s old (market_balancer.py:108-121)

LIVE BUT INERT IN THIS PATH:
- SizingConfig.speed=0.5 and rebalance_every (sizing.py:61-62). risk.size is called without `held` (desk.py:308), so speed never applies.
- desk.blended tie-break (desk.py:306) is computed and discarded because conviction always exists (grading.py:130-131).
- fundamental_features staleness (fundamental_features.py:94-105, 176) is computed and never read by fundamental.opine_corrected.

SHADOW / RECORD ONLY:
- Plain-value alternate desk (desk.py:224, market_daily._challenger_block 864).
- fomc_gate VERSION "fomc-gate/1", MIN_MEETINGS=6, COST_BP=25 (fomc_gate.py).
- reversal shadow SIGNAL_SESSIONS=5, HOLD=10, WEIGHT=0.10 (reversal.py).

RESEARCH ONLY:
- trend_brake.py:19-21 LOOKBACK=200, ENTER_BELOW=0.97, EXIT_ABOVE=1.02; simulate brake_scale=0.5.
- entry.py:27-29 DIP_BELOW_EMA=-0.08, BAND_Z=-1.0, BREAKOUT_RANGE=0.8. Only bollinger_z is live.
- exit.py GRACE=20 and should_exit (retired).
- portfolio_candidate CORRELATION=0.8, CLUSTER_CAP=0.30.
- allocation.py vol/vol_trend policies.
- simulate.py:55-60 REBALANCE=20, COST_BPS=10.

DATA CALENDARS (live, fail-closed): fomc_decisions.csv ends 2027-12-08; nyse_holidays.json covers 2026-2028 only (calendar.py:210-219).
## measured_results
All figures come from code comments or docs, on the survivor-biased hindsight universe; most were measured on builds before the final /3.

Headline:
- Incumbent vs benchmarks, 2016-01-04 to 2026-09-18 at 10 bp: CAGR 43.57%, max drawdown -34.23%. SPY 15.07%/-33.72%; QQQ 20.07%/-35.12% (docs/NEXT_SESSION.md:5509, 5053).
- From 2015-01-02: 44.56%/-32.01%. SPY 13.77%, QQQ 19.03%. Largest held-weight drift 31.74% against a 15% cap (NEXT_SESSION.md:5647-5653).
- Frozen journals 2020-01-06 to 2026-09-18 (docs/research/fixed-strategy-attribution-2026-09-25.md):
  - Worst drawdown -37.33% at 10 bp and -37.58% at 25 bp, peak 2025-01-23 to trough 2025-04-08, with average stock exposure 89.56% during it.
  - SNDK, DELL, LITE, MU and NVDA account for 66.91% of net gain.
  - DELL reached a 31.60% weight.
- Four post-hoc blocks, all above SPY and QQQ (chronological-stability-2026-09-24.md): +74.4%, +25.8%, +46.4% and +16.8% at 10 bp.
- Prompt context: equal weight of the whole book is about 38-41% CAGR. Survivorship is measured at about 19 points a year of name choice (universe.py:30-35; paper.py:122-123).

Component results:
- Reset length, 20 vs 120 sessions (paper.py:53-57): +3.49% CAGR / +0.129 Sharpe at 10 bp, +2.17% at 30 bp, 12 of 12 phases. The CAGR spread across start phases is 5.7 points at 20, and 9.6 points at 60 (paper.py:63-67).
- Upper tail only vs both tails (paper.py:90-95):
  - From 2021: 47.43% CAGR, worst phase 40.52%, Sharpe 1.354, drawdown -45.33%, turnover 5.49x/yr (both tails: 43.83%).
  - From 2018: 34.12%, Sharpe 1.178, drawdown -42.19%, turnover 5.02x (both tails: 36.80%).
- Calendar-only book with no entries: 34.38%, Sharpe 1.468, drawdown -30.04% (paper.py:105).
- Band trigger vs the 15%-over-21-day rule (paper.py:127-131):
  - From 2021: band 50.60% / Sharpe 1.458 / -42.74% / 4.69x, against 48.42% for the old rule.
  - From 2018: 37.89% / 1.238 / -36.44%.
  - The band fires after a median prior run of 14.1% (43.0% for the old rule), with 2.7% median next move.
- Band 1.5 sigma: 55.4% CAGR at 30x turnover (paper.py:140-141).
- Band 1.10 vs 1.25 (paper.py:152-159): +2.31 CAGR at 10 bp, +1.55 at 30 bp, -0.017 Sharpe; deployed share 72% to 76%.
- Cash-funded entries: +1.3 CAGR (paper.py:117). Before them the account ran 43% invested and 57% idle (paper.py:118-120).
- Deferred buys: "about five CAGR points" (paper.py:226-230).
- Rotation (paper.py:328-343):
  - Redeploying a downgrade vs selling it to cash: selling to cash costs 24 CAGR points.
  - Rotation minus holding: +3.42 at the 20-session reset (positive in 12 of 14 phases), -8.32 at 120.
  - About 7.3 points shallower drawdown than holding (market_daily.py:540-549).
- Flat vs laddered grade sizes (grading.py:46-51): from 2021 58.42% vs 51.23%; from 2018 44.73% vs 39.35%.
- Dropping B (grading.py:69-72): at a 20-session reset -0.37% CAGR / +0.033 Sharpe / +1.87% drawdown at 10 bp, and +0.18% at 30 bp.
- Veto cap (grading.py:15-18): raises the A grade's return from 17 to 53 bp per 20 sessions.
- Veto off:
  - +39.5% vs +35.4% from 2021-06 (+36.2% at the rule's volatility, 5 of 6 years) (docs/CHANGELOG.md:3066).
  - From 2018-06, +27.4% vs +25.2% with drawdown -26.0% vs -23.4%. It was rejected only on the 25% loss limit (CHANGELOG.md:2798-2803).
- Expectations gap: +30.3% vs +25.2% from 2018-06, Sharpe 1.56 vs 1.46 (desk.py:130-139).
- Volatility target (risk.py:35-47): 0.25 to 0.30 gives +3.5 and +2.0 CAGR. At 0.40 the full-history drawdown is -43.03% vs -34.89%.
- Tightening exposure 0.5 to 0.75: +1.0 CAGR at equal volatility (regime.py:59-72). Tightening de-risking: Sharpe 1.47 to 1.65 (regime.py:50-56).
- Top 10% of names at a 25% volatility target since 2021-06: 31% CAGR, Sharpe 1.55; equal weight 41%, Sharpe 1.28 (risk.py:29-34).
- Reinforcement-learning weights: rule +0.611, equal weight on the same names +0.605, REINFORCE +0.579, cross-entropy +0.585 (risk.py:104-107).
- Better volatility forecast: Sharpe 1.85 to 1.82 (sizing.py:231-234).
- Stretch leg (technical.py:46-50): support 26.70%, signed 27.07%, band 26.07%, none 27.83%.
- Restoring 19 utilities: 38.45% vs 34.12% (universe.py:354-360).
- Band exits cost 3.0% a year. Held names whose band was wide with price near the top beat SPY by +3.10% over 20 sessions (t 14.0); after a downgrade out of A they still beat it by +1.49% (t 4.3); baseline +1.95% (exit.py:28-49).
- FOMC 3-session-weakness overlay, 2021-2026 at 10 bp: CAGR 43.39% to 41.71%, drawdown 33.20% to 34.41% (docs/research/fomc-window-evaluation-2026-09-13.md). Two meetings after the guidance change: +0.35 pp.
- Signal ICs, beta-adjusted, 20 sessions:
  - tone 0.039 (t 3.0) (sentiment.py:12)
  - value 0.048 (t 3.6); size-neutral 0.036 (t 2.3) (value.py:5-14)
  - conviction vs grade 0.038 to 0.047 (opinions.py:24-26)
  - residual momentum 6-1: 0.055 (t 2.2) at 60 sessions vs raw 0.042 (baselines.py:147-150)
  - momentum 12-1 on 532 names at h10: IC 0.015 (t 0.95) (NEXT_SESSION.md:9557)
  - 52-week-low distance 0.041 at h20 (NEXT_SESSION.md:9365), but only 0.005 once beta-adjusted (NEXT_SESSION.md:9273-9277)
  - 52-week-high proximity +0.042 (t 2.3) only while the AI basket is rising (NEXT_SESSION.md:9234)
## wiring_status
LIVE (nightly paper account; market_daily --paper-trade):
- desk.run with corrected fundamentals and the expectations-gap input (desk.py:152-224).
- regime.opine: rotation, hype exposure and tightening from ^TNX (desk.py:117-127, 195).
- grading.grade with the veto; risk.size / desk_targets.
- paper.plan incumbent path: 20-session reset via planner.plan, grade rotation, band entries, one-shot deferred buys, band buy blocker (market_daily.py:694-714).
- event_execution FOMC cycle, which owns the night whenever pending, active or unknown (market_daily.py:695-699).
- MOO buys, MOC sells (market_daily.py:436-456).
- 15-minute market_balancer: green-day skip of pending MOC sells, and recovery of missed FOMC reductions. It publishes intraday ranked buys to intraday.json for the dashboard only; the job itself never submits a buy.

SHADOW / RECORDED ONLY, never traded:
- The plain-value desk as report.alternate and the challenger block (market_daily.py:864).
- fomc_gate.write counterfactual (market_daily.py:1545), execution_quality.write, reversal shadows (market_daily.py:880-887).
- ml_forward observer and learned_inputs capture.
- curve_block backtest curves (market_daily.py:1219+).

AVAILABLE BUT NOT CALLED LIVE:
- paper.plan(allocation_context=...), the funded SPY/QQQ/cash allocation path (paper.py:706-733; paper_allocation.py; allocation.py). market_daily never passes it.
- trend_brake: simulate flag and learned_research only.
- intraday_candidate, portfolio_candidate (correlation-cluster cap), timing_research (hourly and 15-minute causal fills).
- entry.entries dip/breakout triggers. Only bollinger_z is live.
- exit.should_exit (retired), value.opine_v2, grading.RIDGE_WEIGHTS, desk.book_backtest and name_backtest (research CLIs).

The backtest mirrors live through simulate.LIVE_POLICY (simulate.py:72-78) and shared paper functions. One divergence: the simulator's reset calendar is t >= next_rebalance (simulate.py:1127-1129), while live counts planned sessions. A missed nightly run therefore stretches the live reset (INFERRED).
## defects
--- [0]
## title
Selection and sizing tuned for risk-adjusted residual return, not total return: large idle zero-yield cash
## location
backend/market/harness.py:167 (beta_adjusted=True default); backend/agents/trading/desk/desk.py:341 (calibrate on forward_residual); backend/agents/trading/desk/risk.py:48-50 (target_volatility 0.30, inverse-vol); backend/market/sizing.py:294-299; backend/agents/trading/desk/regime.py:49,72
## severity
high
## evidence
Grades and analysts were screened on beta-adjusted residual IC; after that correction high-volatility names and 52-week-low distance lost their IC (NEXT_SESSION.md:9273-9277). The book is inverse-vol weighted, scaled to a 0.30 annual volatility target and multiplied by 0.75 in hype or tightening. The code records 43% invested / 57% idle before cash-funded entries (paper.py:118-120) and 72-76% deployed after them (paper.py:156). Simulated cash earns zero (NEXT_SESSION.md:5651). Raising the target to 0.40 earns more (risk.py:42-47).
## effect_on_return_or_risk
INFERRED: at ~24% average idle cash against QQQ's ~20% CAGR over the window, the forgone beta alone is ~4-5 CAGR points a year, before the extra drawdown it would add. The stated user objective (total return over SPY/QQQ) is not the objective these parameters were chosen for.
--- [1]
## title
Value analyst veto works against momentum and was measured to cost return
## location
backend/agents/trading/desk/grading.py:269-273; backend/agents/trading/desk/value.py:34-62; backend/market/challenger.py:94-111; backend/cli/market_daily.py:537-563
## severity
high
## evidence
Value = size-neutral P/S cheapness against the side median, and it moves daily with price. As a name rallies against peers its rank falls toward the bottom 30%. The resulting bearish value stance caps the grade at B, which triggers the rotation sale. Measured veto-off: +39.5% vs +35.4% from 2021-06 (CHANGELOG.md:3066). From 2018-06: +27.4% vs +25.2%, drawdown -26.0% vs -23.4%, rejected only by the 25% loss limit (CHANGELOG.md:2798-2803). The live incumbent's own drawdown already breaches that limit (-34.23%, NEXT_SESSION.md:5509).
## effect_on_return_or_risk
Measured +2 to +4 CAGR points forgone on older builds. The veto sells the strongest momentum names and excludes the richest-valued 30% from ever being held.
--- [2]
## title
FOMC overlay is live although its only long-history test lost return, and it freezes all other trading during a cycle
## location
backend/cli/market_daily.py:695-699; backend/agents/trading/desk/event_execution.py:29-90; backend/agents/trading/desk/event_risk.py:17-20,106-136
## severity
medium
## evidence
2021-2026 at 10 bp: CAGR 43.39% -> 41.71%, drawdown 33.20% -> 34.41% (fomc-window-evaluation-2026-09-13.md). Adopted on two meetings (+0.35 pp). While a cycle is active, or any order is pending, market_daily routes the whole night to event_execution.plan: no rotation, entries, deferred retry or reset.
## effect_on_return_or_risk
About -1.7 CAGR measured, plus deeper drawdown. Up to 5-6 sessions per triggered meeting in which downgrades are not rotated and breakouts are not entered.
--- [3]
## title
Rotation analyst's vote is structurally one-sided because every name on a side ties
## location
backend/agents/trading/desk/regime.py:242-243; backend/agents/trading/desk/opinions.py:110-116; backend/market/baselines.py:93-119
## severity
medium
## evidence
The score is spread x side sign, so the 68 AI names share one value and the 26 software names another. Average-rank ties give: AI-leads -> AI rank 0.640 (neutral), software 0.134 (bearish). Software-leads -> software 0.866 (bullish), AI 0.360 (neutral). Verified numerically with the same average_rank logic.
## effect_on_return_or_risk
The half-vote can never lift an AI name toward A. It only penalises software when AI leads and rewards software when software leads, which is the opposite of the intended 'follow the leader'. It flips grades at the 1.5/2.0 thresholds and makes software grades flicker (NEXT_SESSION.md:9168 noted CRWD flickering on the rotation half-vote).
--- [4]
## title
Reset sells mid-cycle entries and trims gross back down: a sawtooth, and heavy dependence on reset timing
## location
backend/agents/trading/desk/paper.py:745-771; backend/agents/trading/desk/planner.py:76-86; backend/agents/trading/desk/paper.py:422-475
## severity
medium
## evidence
At every 20-session reset, planner.plan sells any held name without a target, including A-graded breakout entries outside the top 9, and cuts every position back to vol-targeted, exposure-scaled weights. Between resets, entries add 1.78-7% each with no regime or volatility scaling. CAGR spread across start phases is 5.7 points at reset 20 (paper.py:63-66); turnover is 4.7-5.5x a year (paper.py:90-131).
## effect_on_return_or_risk
INFERRED: turnover cost and 'timing luck' noise; winners are sold down to cash at each reset and bought back in chunks. The 5.7-point phase spread is the size of the calendar noise.
--- [5]
## title
The buy blocker suppresses the condition the exit study found strongest, and was never re-measured after band entries
## location
backend/cli/market_daily.py:602-616; backend/agents/trading/desk/exit.py:106-126; backend/agents/trading/desk/paper.py:444
## severity
medium
## evidence
The blocker = (position >= 0.95 AND bearish candle) OR (band width rank >= 0.90 AND position >= 0.80). Every breakout entry has position >= 1.05, so it is blocked whenever the band is in its top width decile. For held names that same wide-band-near-top condition was followed by +3.10% vs benchmark over 20 sessions, t 14.0, the best of 21 triggers (exit.py:43). The blocker was adopted 2026-09-11 (8b5aa25f); band entries came 2026-09-18 to 09-20 (d9c3e399, c1d1b7d2, 5886eef9).
## effect_on_return_or_risk
INFERRED: many high-momentum breakout entries and rotation redeploys are skipped. The net effect of the interaction is unmeasured.
--- [6]
## title
Rotation proceeds sit in cash overnight, and past one retry until the next entry or reset
## location
backend/agents/trading/desk/paper.py:639-652,558-604,842-862; backend/cli/market_daily.py:436-456
## severity
medium
## evidence
Sells are MOC on T+1. Buys are MOO on T+1 and bounded by cash that existed before the sells, so the redeploy fills at the T+2 open. Only one retry is made, and only for A-graded, unblocked names; anything else waits for the next entry or reset. 'About five CAGR points' was recovered by adding that one retry (paper.py:226-230).
## effect_on_return_or_risk
INFERRED: the book forgoes the overnight session on every swap, and some proceeds idle for days. The overnight session carries much of equity drift.
--- [7]
## title
3-session stance persistence delays both entry after earnings and exit on a downgrade
## location
backend/agents/trading/desk/opinions.py:19,87-96
## severity
low
## evidence
A tone change on the reaction date becomes a stance only on the third consecutive session. The grade updates at that close and fills at the next open, about 3 sessions after the market could first react. A downgrade is delayed the same way.
## effect_on_return_or_risk
INFERRED: misses the early part of post-earnings drift, which the literature concentrates in the first days. The magnitude for this book is unmeasured.
--- [8]
## title
Residual momentum for new listings is computed partly on fabricated returns
## location
backend/market/baselines.py:159-162; backend/market/panel.py:107-113; backend/market/levels.py:175-188
## severity
low
## evidence
Missing returns become 0 and an unknown beta becomes 1.0, so a residual before listing equals -SPY. The weekly and daily trend legs become finite after about 110 sessions, while the residual window needs 141 sessions (120+21). Between those points the technical score of a new IPO (CRWV, SNDK, NBIS-type names) includes -SPY pseudo-returns. Missing days of listed names also contribute -beta*SPY.
## effect_on_return_or_risk
Biases technical ranks of young names against their true momentum: down in rising markets, up in falling ones.
--- [9]
## title
Coarse and stale inputs drive the grade gate
## location
backend/agents/trading/desk/sentiment.py:54,64-77; backend/market/language.py:275-313; backend/agents/trading/desk/fundamental.py:106-120; backend/market/fundamental_features.py:94-105,176
## severity
low
## evidence
Tone fields are -1/0/1 and carried with no decay until the next release. Sentiment is decisive: A+ requires it, and sentiment bullish plus votes >= 1 alone gives an A. Fundamental staleness is computed but ignored. Technical has two ternary legs. A+ carries the same weight as A.
## effect_on_return_or_risk
Many names in large tied blocks cross or miss the 30%/70% cutoffs together. A quarter-old reading can keep a name eligible or vetoed.
--- [10]
## title
Held weight drifts to twice the name cap
## location
backend/agents/trading/desk/paper.py:399-417
## severity
low
## evidence
Rotation buys are split pro rata to the current values of existing holdings, so they go to the winners. Nothing is trimmed mid-cycle. Maximum held weight is 31.60-31.74% against a 0.15 cap (fixed-strategy-attribution; NEXT_SESSION.md:5651).
## effect_on_return_or_risk
Risk concentration: five names were 67% of the gain. It helped return in-sample; it is a tail risk forward.
--- [11]
## title
The whole plan halts silently when the FOMC or holiday calendar file runs out
## location
backend/cli/market_daily.py:696; backend/agents/trading/desk/event_execution.py:37-38; backend/market/calendar.py:210-219; backend/market/data/fomc_decisions.csv (last row 2027-12-08); nyse_holidays.json covers 2026-2028
## severity
low
## evidence
If calendar_known is False, every night routes to event_execution, which returns 'FOMC calendar unavailable; exposure changes paused'.
## effect_on_return_or_risk
After the last listed meeting the book stops rotating, entering and rebalancing, without an error.
--- [12]
## title
Selection edge is small and was tuned sequentially on one price path
## location
backend/agents/trading/desk/paper.py:41-173 (decisions dated 2026-09-18 to 09-23 per git log); backend/market/universe.py:23-35
## severity
medium
## evidence
About 10 successive choices (reset, band threshold, entry exponent, upper-tail only, B dropped, rotation, cash funding, deferred buys, tightening 0.75, volatility target) were each scored on 2016-2026 'start phases' of the same path. The incumbent 43.6% is only ~3-5 points above equal weight of the same hindsight-picked book (38-41%). Survivorship is ~19 points a year.
## effect_on_return_or_risk
Forward excess return over equal weight could be close to zero. Any new variant must be judged on untouched sessions or predeclared folds.
--- [13]
## title
Minor dead code and fragility
## location
backend/agents/trading/desk/desk.py:306; backend/agents/trading/desk/planner.py:50-51; backend/market/model.py:1115-1116 with sentiment.py:67
## severity
low
## evidence
The `blended` tie-break is computed and discarded. A held ticker with no panel price keeps its shares forever, because target_shares returns the held quantity. If no tone layer exists, load_tone_features returns None and sentiment.opine(None) raises a TypeError, with no guard in desk.run.
## effect_on_return_or_risk
Negligible return impact. There is a risk of a stranded position or a failed nightly run.
## improvement_opportunities
--- [0]
## idea
Park idle cash in a QQQ (or SPY) sweep sleeve instead of zero-yield cash; sell the sleeve in the same auction to fund entries and rotations
## rationale
The book sits 24-57% in cash by construction (volatility target, regime, cash-bounded funding) while the benchmark is 100% invested. This is the single largest structural gap against a total-return benchmark.
## where_it_plugs_in
paper.plan / midcycle_orders budget and bound_orders (paper.py:610-652, 842-862). market_daily._paper_trade passes targets plus a residual index weight. Simulate via simulate.run(funded_allocation=True, index_eligible=True, benchmark_prices=...) or a new LIVE_POLICY flag.
## reusable_code
allocation.decide(..., index_eligible=True) (allocation.py:383) already selects residual SPY. funded_execution.plan_funded; paper_allocation.plan_funded_paper; simulate._Book ledger; scorecard.render against SPY and QQQ.
## expected_effect
INFERRED +3 to +5 CAGR points versus the zero-cash incumbent over 2016-2026, with drawdown closer to QQQ's in selloffs.
## risks
Higher beta in bear markets (the 2025 drawdown was already at 89.6% stock exposure). Extra turnover on the sleeve. The existing vol/vol_trend allocation tests (22% CAGR) show that scaling stocks down to buy the index loses; only the residual cash should be swept.
--- [1]
## idea
Turn the value veto into a tilt: veto only on fundamental, sentiment or technical, and keep value in votes and conviction
## rationale
Value is price-dependent and sells momentum winners. Veto-off measured +2 to +4 CAGR and was rejected only on a 25% drawdown limit the incumbent itself breaches.
## where_it_plugs_in
grading.grade_stances(veto=...) (grading.py:231-274): add a per-analyst veto set. Wire through desk.assemble (desk.py:298-305).
## reusable_code
grade_stances already has a veto flag. simulate.run(report, **LIVE_POLICY) for the full-rule book; scorecard.render(results, store).
## expected_effect
Measured +4.1 CAGR from 2021-06 and +2.2 from 2018-06 (older builds). Must be re-measured on /3.
## risks
About 2.6 points deeper drawdown. The 'buying richly priced names' failure mode the veto was added for.
--- [2]
## idea
Add the robust momentum family to selection and measure it on total returns: 12-1 total-return momentum, residual 12-1, 52-week-high proximity, and an earnings-announcement-return / PEAD proxy
## rationale
Only 120/21 residual momentum is scored, worth about 1/4 of technical, or ~5% of conviction weight. 52-week-high distance is computed but only cited. Earnings drift uses only the ternary LLM tone. All screening used beta-adjusted IC, which penalises exactly the high-beta winners a total-return book wants.
## where_it_plugs_in
A new 'momentum' Opinion in desk.run (desk.py:196-201) plus a weight in grading.ANALYST_WEIGHTS; or replace the ternary weekly/daily legs in technical.opine (technical.py:155-165). Evaluate with harness.evaluate_scores(beta_adjusted=False) and with simulate.run.
## reusable_code
baselines.momentum(panel, 252, 21); baselines.residual_momentum(panel, length=231, skip=21); technical.technical_features 'high_52w_distance'; levels.level_features 'range_position_60'; fundamental opinion evidence 'sessions_since_earnings' and ToneRecord.reaction_date for a 3-day abnormal reaction window; panel.forward_log_returns.
## expected_effect
INFERRED modest. The literature's 12-1 and 52-week-high effects are well documented, but the in-book 12-1 IC was weak (0.015 at h10 on 532 names, pre-beta fix). Only the 20/60-session book result should decide.
## risks
More search on the same path. A new analyst adds another veto unless explicitly excluded from it. Momentum crashes.
--- [3]
## idea
Add a rank buffer at the reset and stop de-grossing at the reset: keep a held A name while it stays in the top ~15 by conviction, and set reset gross to at least the current deployed gross
## rationale
The reset sells fresh breakout entries and trims the book to the vol-targeted gross, which entries then rebuild. The 5.7-point CAGR spread across start phases shows the calendar injecting noise.
## where_it_plugs_in
risk.desk_targets (risk.py:160-192): pass `held` and add a keep-if-rank<=K2 rule. paper.plan rebalance branch (paper.py:750-771): scale targets to max(target gross, deployed).
## reusable_code
sizing.size_today(held=...) already takes held weights. risk._holdable. planner.plan. simulate.run with LIVE_POLICY for the comparison over 20 start phases.
## expected_effect
INFERRED: lower turnover (currently 4.7-5.5x a year) and less timing luck. Return change unknown, likely small and positive at 25 bp.
## risks
Holds decaying names longer, and the 0.30 volatility target loses force.
--- [4]
## idea
Retire the live FOMC cycle to a shadow, or at minimum let rotation and entries keep running during a cycle
## rationale
Measured -1.68 CAGR and deeper drawdown over 2021-2026. It also blocks every other action while active.
## where_it_plugs_in
market_daily._paper_trade event routing (market_daily.py:695-699). event_risk.decision is kept for the record, and fomc_gate.write already prices the counterfactual.
## reusable_code
fomc_gate.py counterfactual; event_risk.exposure_path; simulate.run(event_exposure=event_risk.live_path(panel), event_lifecycle=True) for the A/B test.
## expected_effect
About +1.7 CAGR from the backtest; restores downgrade and entry responsiveness around meetings.
## risks
Loses a possible edge in the new Fed-guidance regime (2 meetings, +0.35 pp). The operator's predeclared gate expects 6 meetings.
--- [5]
## idea
Fix the rotation analyst so the leader side can vote bullish
## rationale
The tie arithmetic makes the half-vote bullish only for software and never for AI.
## where_it_plugs_in
regime.opine rotation_scores (regime.py:242-243): score each name by its own theme's trailing return relative to the market, or demean per side. Alternatively, drop rotation from votes and keep it in conviction only (grading.py:163-173).
## reusable_code
baselines.theme_momentum(panel, lookback=60); panel.theme_return_matrix; regime.residual_basket.
## expected_effect
INFERRED: A grades become more stable and follow the leader symmetrically. The size of the return effect is unknown.
## risks
Rotation IC (0.040) was measured on the 2-group spread; a new definition is a new signal.
--- [6]
## idea
Swap in the same auction: send rotation and reset buys MOC alongside the MOC sells (or both legs MOO), funded by same-auction proceeds
## rationale
Removes the overnight cash gap and most of the deferred-buy machinery. The deferred retry alone was worth about 5 CAGR, which shows how costly idle proceeds are.
## where_it_plugs_in
market_daily._submit (market_daily.py:436-456): add an MOC buy path. paper.midcycle_orders and bound_orders budget = cash plus same-auction sell proceeds. simulate: settle_split with buys at closes[t+1].
## reusable_code
alpaca_trading client.submit_market_on_close; paper._fund_buys; simulate._Book.settle_split(order, buy_prices, sell_prices, ...).
## expected_effect
INFERRED: +0.5 to +2 CAGR (the overnight premium on swapped capital, plus fewer failed retries).
## risks
Needs margin or buying power at the auction (paper-account setting unknown). Auction imbalance on small caps. The green-day skip can cancel the sell after the buy has already been placed.
--- [7]
## idea
A 15-minute-confirmed entry for breakout entries only (the reset stays MOO): defer the order to the first completed 15-minute bar that holds above the prior close or opening-range high, with a matched unconditional-delay control
## rationale
The user asked for a 15-minute entry optimiser. Breakout entries at the MOO pay the overnight gap. The microstructure review prescribes one predeclared entry veto/delay with an unconditional-delay control. Note an earlier study found the open as good as any first-hour print, so the prior is low.
## where_it_plugs_in
The market_balancer 15-minute loop (market_balancer.py:300-340) submits the deferred entry. paper._entry_orders marks entries for deferred execution. A funded replay uses intraday bars.
## reusable_code
timing_research.hourly and its 15-minute next-bar-open fill; intraday_cache and intraday_replay; live_quotes; desk.entry.bollinger_z; paper.entry_size.
## expected_effect
Unknown; realistically within ±1 CAGR. Its value is avoiding gap-and-fade entries.
## risks
Missed rallies when the confirmation never comes. IEX-only volume. A new ledger is needed (the daily ledger cannot validate it). High risk of overfitting thresholds.
--- [8]
## idea
Use overlapping tranches (e.g. 4 sub-books offset by 5 sessions) in place of one 20-session reset
## rationale
Standard fix for rebalance timing luck. The measured phase spread is 5.7 CAGR points.
## where_it_plugs_in
PaperState (paper.py:188-241): per-tranche clocks. paper.plan rebalance branch plans a quarter of the book each time.
## reusable_code
simulate.run(rebalance=...) can already run each phase. Averaging 4 phase-offset SimResults gives a quick upper bound before any code change.
## expected_effect
Mean CAGR roughly unchanged; much smaller dispersion and smoother turnover (INFERRED).
## risks
More small orders, and more complexity in reconciliation and rollback.
--- [9]
## idea
Replace the volatility target and regime cuts with the QQQ 200-day trend brake as the only drawdown control, and raise or remove the 0.30 stock-sleeve volatility target
## rationale
Known result: the brake cut max drawdown about 10 points for about -1.7 CAGR. The volatility target and regime cuts give up more return in bull runs (a 0.40 target earns more).
## where_it_plugs_in
risk.BOOK_CONFIG target_volatility (risk.py:48-50); regime._judge exposure (regime.py:306-317); simulate.run(trend_brake=True, brake_scale=0.5).
## reusable_code
trend_brake.risk_off_path; trend_brake.aligned_qqq; scorecard.matched_at_volatility.
## expected_effect
INFERRED: higher CAGR in trending markets, with drawdown held near the current level by the brake.
## risks
The brake misses fast V-shaped crashes (2020). Whipsaw at the 0.97/1.02 bands.
## reuse_inventory
All paths are under /Users/animallya/Desktop/PersonalAssistant/backend.

Desk and report:
- agents/trading/desk/desk.py:152 run(store, asof=None, inputs=LIVE_INPUTS, fundamentals="corrected") -> DeskReport(panel, sides, opinions, regime, graded, scores, book, inputs, alternate).
- desk.py:289 assemble(panel, sides, opinions, view, inputs=(), fundamentals_source="").
- desk.py:336 calibrate(report, horizon).
- desk.py:544 book_backtest(report, since), which includes an equal-weight-of-book comparator.

Grading and opinions:
- agents/trading/desk/grading.py:148 grade(fundamental, technical, sentiment, rotation=None, value=None, weights=None, veto=True) -> Graded(grades, votes, stances, conviction).
- grading.py:231 grade_stances(...).
- agents/trading/desk/opinions.py: Opinion(analyst, scores, evidence, meta) with .ranks(), .stances(fraction, persistence), .conviction(sharpness); persist(raw, sessions); conviction_from_ranks.

Sizing:
- agents/trading/desk/risk.py:160 desk_targets(scores_today, graded_today, panel, regime, config=BOOK_CONFIG, held=None) -> (positions, targets).
- risk.py:197 size(...).
- market/sizing.py: SizingConfig; target_weights(scores, volatility, themes, tickers, config, history); apply_limits(weights, themes, tickers, name_cap, theme_cap, gross); realised_volatility(panel, lookback); size_today(scores_today, panel, config, held=None); simulate(scores, panel, config) (score-only book).

Paper execution:
- agents/trading/desk/paper.py:662 plan(session, state, equity, held, prices, targets, grades, finished=None, force_rebalance=False, entry_blocked=None, entries=None, cash=None, allocation_context=None) -> (orders, state, what).
- paper.py:610 midcycle_orders(...); :181 entry_size(band); :530 _fund_buys(orders, budget, prices, whole_shares); :842 bound_orders(orders, held, prices, equity, cash, unfunded=None).
- agents/trading/desk/planner.py:60 plan(targets, held, equity, prices, min_trade).

Simulator (live-equivalent full-rule ledger):
- agents/trading/desk/simulate.py:643 run(report, since=None, config=None, rebalance=20, cost_bps=10, use_exits=True, ..., block_overbought, exit_at_close, green_day_skip, event_exposure, event_lifecycle, live_midcycle, deferred_buys, funded_allocation, allocation_policy, index_eligible, benchmark_prices, trend_brake, brake_scale, journal) -> SimResult(dates, returns, invested, trades, equity, top_weight, risk_off).
- simulate.run(report, use_exits=False, **simulate.LIVE_POLICY) reproduces /3.
- simulate.adjusted_open(panel).

Scorecard and harness:
- agents/trading/desk/scorecard.py: render(results, store, loss_limit); matched_at_volatility(daily, target_vol); yearly(dates, daily); index_returns(store, ticker, dates).
- market/harness.py:159 evaluate_scores(scores, panel, horizon, cost_bps=10, top_fraction=0.2, min_names=20, exclude=(), beta_adjusted=True). Use beta_adjusted=False for total-return screening.
- harness.py:227 walk_forward_folds(n_sessions, train_size, test_size, horizon, embargo).

Signals:
- market/baselines.py: momentum(panel, 252, 21); residual_momentum(panel, length, skip, beta_lookback); relative_strength; theme_momentum; theme_relative_strength; percentile_rank; rank_blend.
- market/technical.py: technical_features(panel) (EMA distances, 52-week high/low, candles, MACD family); ema; sma; _weekly_ema.
- market/levels.py: level_features(panel) (support, band_position, range_position_60, weekly_trend, daily_trend).
- market/bands.py: position, width, width_rank, edges.
- agents/trading/desk/entry.py: bollinger_z(close, window=20); entries(panel).
- agents/trading/desk/exit.py: evidence(panel).signalled().
- market/panel.py: Panel.log_returns, rolling_beta, forward_residual, forward_log_returns, theme_return_matrix.

Regime and overlays:
- agents/trading/desk/regime.py: opine(panel, sides, tightening); tightening_from(yields); residual_basket.
- agents/trading/desk/trend_brake.py: risk_off_path(qqq, 200, 0.97, 1.02); aligned_qqq.
- agents/trading/desk/event_risk.py: exposure_path(panel, decisions, pre_sessions, reduced, require_weakness); live_path(panel).
- market/fomc_gate.py: counterfactual cycles.

Allocation (stock / index / cash):
- agents/trading/desk/allocation.py:383 decide(dates, prices, tickers, t, desired, held, regime_cap, event_cap, policy, index_eligible, budget_reference, budget_multiplier).
- agents/trading/desk/funded_execution.py: plan_funded, daily_decision, stable_composition.
- agents/trading/desk/paper_allocation.py: plan_funded_paper.
- agents/trading/desk/portfolio_candidate.py: calculate(panel, weights) (correlation-cluster cap).

Intraday:
- agents/trading/desk/timing_research.py: hourly(bars) and 15-minute next-bar-open fills.
- cli/market_balancer.py: the 15-minute job loop, with _green_day_skip.
- market/live_technical.py, market/intraday_*.py.

Data:
- market/universe.py: build_universe(), book_sides(), theme_map(); MARKET_INDICES=("SPY","QQQ").
- desk.book_panel(store, asof).
- market/challenger.py: expectations_gap(store, panel, asof), with_gap(opinions, gap).
## open_questions
1. What drawdown will the user accept? The scorecard's 25% loss limit (scorecard.py:126) is what rejected veto-off, the 0.40 volatility target and the combined variants, yet the live incumbent runs -34% to -37%. This decides how far any return-maximising change can go.
2. Is the Alpaca paper account margin-enabled? That determines whether same-auction swaps can be funded from sell proceeds.
3. What are the live typical target gross, vol-target scale, and average cash share by session? They are in the nightly records and paper state on Spark, which are not readable locally. INFERRED: 0.5-0.75 at reset.
4. What share of A grades comes through each route (votes >= 2, sentiment bullish plus 1, f&t plus 1.5)? How many names are vetoed by value alone on a typical day?
5. Do foreign filers (TSM, ASML, ARM, NBIS) ever get fundamental, value and tone views? ASML has no supported monetary projection (current-sec-qualification-2026-09-25.md). If they don't, they are capped near B and can never be held.
6. Was HYPE_EXPOSURE=0.75 ever measured at book level on the current build? Only IC-level evidence is cited (regime.py:9-11).
7. Was block_overbought re-evaluated after the band-entry change on 2026-09-18 to 09-20? Its interaction with ENTRY_BAND_Z=1.10 is not documented.
8. How many sessions a year does the FOMC cycle, or a lingering pending order, displace the regular plan live?
9. Every quoted CAGR is on the hindsight-picked survivor universe, with about 10 sequential choices made on the same 2016-2026 path. Which sessions remain untouched for judging any proposed upgrade? Operator rule: no tuning on 2024-2026.
10. Should selection signals be screened on total or residual forward returns, now that the user's objective is total return against SPY and QQQ?