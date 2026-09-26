## area
intraday-15min: every use of 15-minute bars or intraday timing (fetch/cache, session normalisation, features, the live candle loop, the order paths, research engines/replays, studies), with an assessment of (a) an intraday entry-timing layer for the daily /3 book and (b) a separate 15-minute tactical sleeve
## how_it_works
1) FETCH. alpaca.fetch_bars (backend/market/alpaca.py:140-172) calls GET /v2/stocks/bars one symbol at a time with timeframe=15Min, feed=iex, adjustment=all, limit=10000, sort=asc and start/end at T00:00:00Z/T23:59:59Z (alpaca.py:153-157). It pages by next_page_token, sleeps 5 s on HTTP 429 (:161-163) and 0.35 s between pages for the 200 requests/min Basic limit (:171). Bars are stamped at the interval start in UTC (IntradayBar :76-85), and the request covers extended hours. The cache is written by the manual CLI backend/cli/market_intraday.py:58-77. It refetches the full history since --since (default 2016-01-01) into one immutable frame per ticker per as-of partition (kind bars_15m, metadata {source: alpaca-iex, since}), with no incremental append, and the adjustment flag is not persisted (intraday_cache.py:16-23). Audited state (docs/research/intraday-comparison-input-audit-2026-09-22.md:43-47): asof=2026-09-20 holds 530 files and 19,871,542 rows, from 2019-01-02 (mostly 2020) to 2026-09-18, including extended hours; SPY/QQQ intraday files are ABSENT. A cross-provider scale audit of 782,568 closes found median |diff| 0.028% but p99 9.83%, with AVGO at a ~10x ratio before its 2024-07-15 split (audit :5-15). Historical scoring on that cache is formally BLOCKED (intraday-price-basis-reconciliation-2026-09-22.md:3-6). Delayed consolidated SIP history is reachable on the same free key by swapping feed=iex->sip (backend/cli/market_pick_audit.py:125-137; 22,616 SIP bars fetched 2026-09-13, pick-timing-audit-2026-09-13.md:93). One approved 1Min SIP probe returned HTTP 200 (extended-hours-source-options-2026-09-25.md:56-79). Latest SIP quotes return 403 (execution_quotes.py:40-45).

2) SESSION NORMALISATION. backend/market/intraday.py places bars on the New York clock, looking up the UTC offset per calendar day (:43-57). It keeps 09:30-16:00 slots 0..25 (:74-79). episodes_from keeps only sessions with exactly 26 unique slots, finite positive closes and no bar-to-bar |log move| > 0.30 (BAD_BAR :27, :104-111), plus the prior close if it is within 4 days (:113-116). The cutoff is a fixed 16:00, so early closes are not modelled here. alpaca.sessions (:205-214) and tape.session_tape (tape.py:36-73; slot-placed, gaps flat, MIN_SLOTS 13) also use 09:30-16:00. Early closes are handled only by calendar.session_close (calendar.py:138-141: 13:00 on published dates, covering 2019-2028 via data/nyse_*json), intraday_inputs.ResearchCalendar (:20-56), intraday_entry._completed_bars (:231) and live_quotes (:63, :100).

3) FEATURES (all research-only). alpaca.session_features (:218-258) computes 10 per-session features: fraction of closes above cumulative typical-price VWAP, log(close/open), first-hour return (closes[3]/opens[0]), last-hour return (closes[-1]/closes[-5]), reversal sign, fraction above the 9-bar EMA (alpha 0.2), EMA9 crosses, range position, first-hour volume share and has_intraday. They reach the model only through the 'intraday' feature layer (model.py:1135-1170) and the tape encoder (model.py:1174-1186, market_sweep.py:147-153). entry_pilot.prefix_features (:94-138) computes prefix range position, log distance to prefix VWAP, relative volume against the 20-session same-slot median, realised vol, body/wicks, time and last-hour return, plus a 14x7 sequence. timing_research.readings (:56-114) computes 15m EMA9/21, 20-bar bands, completed hourly candles anchored at 09:30 with EMA9/21, the prior-day daily EMA21/50 and the prior-day high.

4) LIVE CANDLE LOOP. Host cron runs desk_intraday.sh at `*/15 9-16 * * 1-5` ET (docs/NEXT_SESSION.md:7371-7373) and calls backend/cli/market_balancer.run (:226). live_quotes.quotes (:131-160) fetches today's IEX bars per symbol and keeps only completed regular bars (start+15m <= now, :65-73). It returns None if the 09:30 bar is missing (:74-75) and caches in process with RECHECK_SECONDS=60 (:29). live_technical.with_live_row (:93-147) overwrites or appends today's daily row from the quote (open = first-bar open, high/low so far, adj close = last x prev adj/close ratio). It then re-runs regime, technical and value analysts and the entry triggers (technical_now :208, value_now :238, entry_now :806). The balancer writes desk/intraday.json (ranked 'top_buys', display only) and live.json. It then calls intraday_research.publish (market_balancer.py:322-330), which runs intraday_candidate.calculate: fresh re-grades, a macro exposure budget, risk.desk_targets, entry_evidence.capture and execution_quotes, archived once per candle as desk/intraday-research/decision-<sha(version:session:bar)>.json (intraday_research.py:121-143). It also calls board_paper.observe (a synthetic forward ledger), _green_day_skip and market_event_recovery.run. Freshness gate: a quote is current only if 900 <= now-bar_start < 1800 s on today's 09:30-16:00 clock (desk_freshness.py:9-10, 39-55). valid_until = min(written+900 s, bar+1800 s) (:14-26).

5) HOW A 15-MINUTE SIGNAL CAN TOUCH AN ORDER (paper account). Ordinary /3 orders are planned once per session after the close (market_daily.py:697-712). Buys are market 'day' orders queued overnight and filled at the first print after 09:30 (alpaca_trading.py:239-271; the opg auction was dropped on 2026-09-08 after 8 of 9 expired). Ordinary sells are 'cls' market-on-close for the NEXT session's close (market_daily.py:435-448, alpaca_trading.py:273-296). _submit refuses every non-event order while the market is open (market_daily.py:428-434). Only three intraday paths act: (i) the green-day skip (market_balancer.py:124-219), which from 09:30-11:00 ET (:144) cancels a pending ordinary MOC sell when the IEX first-bar open > prior close (:173-174) and the candle is at most 1800 s old (:109-121); (ii) FOMC event reduction recovery, regular-session day-order event sells (market_daily.py:421-427, market_event_recovery.py); (iii) nothing else. The personal board shows an intraday 'Buy' when the live band z >= 1.10 (decision_view.entry_action :553-600), but a human executes it. The simulator mirrors live: buys opens[t+1], sells closes[t+1] (exit_at_close), green_day_skip and deferred_buys (simulate.py:72-78, 1216-1219).

6) FILL/LATENCY MODELS (all different):
- intraday_replay.execution_proxy: open of the next consecutive bar at the confirmation instant, zero latency and zero cost, execution_unknown if that bar is missing (:479-565).
- timing_research.evaluate: next bar open, 10 bp per side (:154-207).
- entry_pilot: decision at the end of slot k (k in {3,7}, i.e. 10:30/11:30); fill at the open of slot k+2 (one bar of latency) or k+6 for 'wait' (:11, :207-208).
- market_intraday_timing Study 2: filled AT the confirming bar's own close (zero latency, :260).
- market_execution_rl: bar typical price plus 2 bp; the auctions are free (docstring).
- intraday_evaluation: next candle's IEX last close, flat 10/25 bp (:72-118).
- board_paper: next candle's IEX ask x1.001 / bid x0.999, capped at displayed size (:166-175).
- Paper reality: the AAOI buy filled 09:33:06 at $107.997 against a SIP 09:30 open of $104.49 (pick-timing-audit:66-76).

7) RESEARCH ENGINE STACK (never wired to orders). intraday_entry.evaluate (:520-635) is the reclaim_above_level/1 state machine. Levels come from intraday_comparison.fixed_levels (:225-267): level m+2s, entry m+2s*1.10, invalidation m, over the prior 20 adjusted closes. Only completed bars count; the prefix must be contiguous from 09:30 (:270-287); a one-bar feed gap makes readiness unavailable (:581-589). intraday_comparison.compare (:608-698) pairs it with an intraday 'incumbent' that computes bollinger_z on 19 prior closes plus the live close and applies the entry_action gate. That is an intraday variant, not the /3 decide-at-close/fill-next-open rule. intraday_replay (horizons 20/5 :54-55), intraday_cache (explicit partitions plus hashes), intraday_inputs, intraday_preflight and intraday_single_source (a six-symbol run via a /tmp driver) supply causal replay, provenance and denominators.
## parameters_and_constants
LIVE (paper-order affecting):
- paper.py:68 REBALANCE_EVERY=20; :160 ENTRY_BAND_Z=1.10; :166 ENTRY_ADD=0.023; :167 ENTRY_NAME_CAP=0.15; :168 ENTRY_MIN_GRADE=(A,A+); :169 POLICY_VERSION cash-bounded-breakout-rotation/3; :173 ENTRY_SIZE_REF=1.25 (entry size = 0.023*(band/1.25)^2).
- alpaca_trading.py:263 TIF 'day' for buys and event orders; :292 TIF 'cls' for ordinary sells.
- market_daily.py:428-434 refuse orders while open (except event reductions).
- market_balancer.py:144 green-day window 570-660 min (09:30-11:00 ET), weekdays; :120 candle age <= 1800 s; :174 rule open_px > prior close.
- event_execution.py:122-127 1% opening-price cash allowance for FOMC restoration buys.
- simulate.py:59-60 COST_BPS=10, MIN_TRADE=0.005; :72-78 LIVE_POLICY {block_overbought, exit_at_close, green_day_skip, live_midcycle, deferred_buys} all True; :1216-1219 fill arrays.

LIVE, display or gating inputs:
- alpaca.py:154-156 15Min/iex/adjustment=all/limit 10000; :162 429 back-off 5 s; :171 page sleep 0.35 s.
- live_quotes.py:23 CANDLE_SECONDS=900; :29 RECHECK_SECONDS=60.
- desk_freshness.py:9 SNAPSHOT_SECONDS=900; :10 BAR_SECONDS=1800; :47 09:30-16:00 clock hard-coded (570..960).
- execution_quotes.py:11 MAX_AGE_SECONDS=30; :12 MAX_SPREAD_BPS=25 (a wide IEX spread becomes 'unverified' but still eligible, :97-118).
- session_prices.py:14-15 MAX_AGE 60 s, CACHE 10 s (display only).
- entry.py:27-29 DIP_BELOW_EMA=-0.08, BAND_Z=-1.0, BREAKOUT_RANGE=0.8 (board entry_now triggers; /3 uses only bollinger_z >= 1.10 via market_daily._price_entries :566-595).
- Host cron `*/15 9-16 * * 1-5` intraday and `30 19 * * 1-5` evening (NEXT_SESSION.md:7372).

SHADOW / forward research (runs each candle, no orders):
- intraday_candidate.py:25 VERSION intraday-macro-candidate/2; :44 economics freshness 36 h; :92-94 all names must share one bar.
- board_paper.py:25 SLIPPAGE=0.001; :29 MIN_TRADE=0.005; :175 fill <= displayed ask/bid size.
- intraday_evaluation.py:12 ARMS; start cash 100,000; costs 10/25 bp from forward_evidence.py:260-265; forward_evidence HORIZONS=(5,20), MIN_COHORTS=20 (:18-19).

RESEARCH-ONLY:
- alpaca.py:55 MIN_BARS_PER_SESSION=8; :234 EMA alpha 0.2.
- intraday.py:25 BARS=26; :27 BAD_BAR=0.30; :28 LONG_WEEKEND_DAYS=4.
- tape.py:24-26 26x5, MIN_SLOTS=13.
- intraday_entry.py:93-102 09:30/16:00/15-min, rule reclaim_above_level/1.
- intraday_comparison.py:56 PRIOR_OBSERVATIONS=20; :59 INCUMBENT_WINDOW=19.
- intraday_replay.py:54-55 PRIMARY_HORIZON=20, SECONDARY=5.
- intraday_preflight.py:62 OBSERVATION_COUNT=26.
- intraday_single_source.py:91 SYMBOLS (AVGO, WRB, WDC, APTV, SPY, QQQ); :94-97 source 2026-06-29..09-18, entries 08-03..09-18; :113-114 assumed grade A, non-rejecting; :117-118 26/14 bars.
- entry_pilot.py:11 SLOTS=(3,7); :12 SEQUENCE=14; :13 BASIC=8; top-5 by 20-session momentum :244-248.
- market_intraday_timing.py:26-32 SINCE 2021-01-04, GAP 0.02, FLUSH -0.02, SLOTS {0,1,3,25}, EMA_SPAN 9, SEED_SESSIONS 3, LAST_ENTRY_SLOT 24; costs 2x30 bp (:267).
- market_intraday_rl.py:138-141 VOL_DAYS 20, COSTS (1,3,5,10), HEADLINE 3 bp.
- timing_research cost 10 bp.

DEAD for trading: market_watch (alert-only trailing stop), options.py/options_evidence.py (nightly Cboe OI, display only).
## measured_results
Execution and timing of the daily book (all in-sample on the hindsight book):

1) Open vs later print, intraday-timing-2026-09-15.md:81-99: 1,413 sessions, 93 names, 2021-01-04..2026-09-04, per-session cross-sectional means. Open to 15m close -0.4 bp (t -0.3); 30m -0.0; 60m -0.6; 30m VWAP -0.1; session close +2.0 (t +0.5). Gap-up >= 2% (1,100 sessions): 15m -8.9 (t -1.5), 60m -11.7 (t -1.4). Gap-down (1,010): 60m -11.0 (t -1.3). Registered bar (20 bp, t > 3) not met.

2) Reversal-entry confirmations, same doc :107-113 (95 any-day / 45 meeting episodes, 30 bp/side). Open +1.24% / +1.10%. 15m EMA9 paired -0.51% (t -0.8) / -0.76% (t -1.1), 77% confirmed. 30m -0.60% / -1.38% (t -1.7). 60m -1.41% (t -1.7) / -2.01% (t -2.1), 41% confirmed. Prior-low -0.62% / -1.40%.

3) Entry-day fills, NEXT_SESSION.md:9005-9030: 9,968 A-grade dip/breakout entry days. Against session VWAP: open -1.1 bp, 10:30 -2.4, pullback to 15m EMA21 +1.4 (occurs on 83% of days), break of first-bar high +0.9, close +2.5. The 20-session return from any fill is within noise of the open (|t| < 1.1; close on dip days t -1.9). Entry-day close above 15m EMA21: breakouts +3.50% vs +2.91% (t 1.7).

4) Execution schedules, market_execution_rl.py docstring, walk-forward 2022-2026, 2 bp per intraday fill. All names, 82,246 order-sessions: buys close +5.31 bp (t 1.15), TWAP +4.93, first hour +3.20 (t 1.73), direct policy +2.40 (t 2.23); positive means worse than the open. Desk's own 344 orders: first-hour buys +36.64 bp (t 1.96), sells -41.24 (t -2.02). Re-decided rule, 2,394 orders over 840 sessions: sells at close -23.62 bp (t -2.77, better), by year 2022 -14, 2023 -34, 2024 -38, 2025 -36, 2026 +15. Entry delay after 1,153 A/A+ arrivals: +1 session -0.29%, +3 -0.57%, +5 -0.72%, +10 -1.43%; after a 10% run-up +5 is -1.37%.

5) Conditional entry pilot, conditional-entry-pilot-2026-09-20.md:92-122: 4,082 opportunities, 2025-01-02..2026-09-04, 10 bp. Mean daily improvement over immediate entry: fixed 1h wait +0.769 bp [-0.278, +1.954]; ridge +0.012; trees(8) -0.189; trees(28) +0.234 [-0.289, +0.792]; GRU +0.142. Pooled returns: immediate +382.29%, wait +402.25%, maxDD about -36%; exposure about 80%. Skip mode: trees +192.18% at 60.5% exposure.

6) Entry context, entry-context-results-2026-09-21.md:24-40: context minus price-only, pooled +0.072 bp/day [-0.130, +0.269].

7) Single-source diagnostic, intraday-single-source-results-2026-09-23.md:21-50: 204 requested, 170 ready, both 0, incumbent-only 5 (mean 20-session -8.25%), candidate-only 1 (-0.46%).

8) Pick audit, pick-timing-audit-2026-09-13.md:118-125 (10 picks): open hold +0.47%, EMA-structure exit -1.31%, confirmed pullback -0.34% (4 of 10 entered). 8 of 9 opg orders expired.

Standalone intraday strategies (flat at the close, 93 book names, 15,151 held-out sessions), market_intraday_rl.py docstring. Sharpe at 3 bp: long session -0.27 (+0.12 at 1 bp); Gao first-half-hour momentum -4.86; hourly reversal -8.48 (turnover 11.49); direct-Sharpe GRU -0.89 best seed; PPO -1.52.

Other intraday signal tests:
- 15m chart CNN, market_charts_intraday.py docstring (310,479 images): rank IC +0.0024 (t 1.03), 0.1 bp. Hourly reversal IC +0.0285 (t 8.09), top-bottom quintile 3.8 bp against a 6 bp round trip.
- Day-type (market_daytype): at most about 3.5 bp, no reader beats a coin flip by more than 1-2 points.
- Tape encoder IC 0.004 (t 0.4) / -0.004 (NEXT_SESSION.md:9248).
- Dip learner pooled net -0.01% (market_dip.py docstring).

Cadence (daily proxy), intraday-funded-cadence-2026-09-14.json: at 10 bp, 20-session rebalancing CAGR 35.79%, Sharpe 1.664, DD -24.5%, turnover 6.10/yr; every session 29.05%, 1.500, -25.7%, turnover 41.06. At 25 bp: 34.55% vs 21.21%.

market_cadence.py (not intraday): every session 27.5% / 1.63 against a 20-session base. Vol target 50% with caps 25/80 gives 42.0% CAGR, Sharpe 1.89, DD -25.5%, against 31.6% / 1.90 / -17.8%.
## wiring_status
LIVE, placing or cancelling paper orders:
- market_daily (evening cron 19:30 ET) plans /3 and submits buys as market day orders for the next open and ordinary sells as MOC at the next close (market_daily.py:435-456).
- The host cron `*/15 9-16 * * 1-5` runs market_balancer. Its only order effects are _green_day_skip (cancelling MOC sells, 09:30-11:00) and market_event_recovery (FOMC event sells in session).
- No 15-minute technical signal creates a buy or sell in the paper account; _submit refuses regular orders while the market is open.

LIVE, display for the personal account (human-executed):
- live_quotes; live_technical (technical_now, value_now, technical_detail, entry_now); decision_view intraday Buy at band z >= 1.10 with the live grade; execution_quotes (IEX latest quote gate); session_prices plus the session_price_collector 15-second display snapshot (latest only, no archive, NEXT_SESSION.md:865).

SHADOW / forward-only, every candle, no orders:
- intraday_research.publish, which builds intraday_candidate (macro-arm targets), entry_evidence (recorded-entry-opinions/1) and execution_quotes, archived per candle.
- board_paper (synthetic account filled at IEX ask/bid +/-10 bp).
- forward_evidence and intraday_evaluation (served by the API: backend/api/v1/market.py:143,154,992-994) compare baseline, technical, macro and correlation target trackers at 10/25 bp. Never promoted.

RESEARCH-ONLY, CLI or tests (never imported by a live path):
- intraday_entry, intraday_comparison, intraday_replay, intraday_cache, intraday_inputs, intraday_preflight, intraday_single_source. The last is imported by nothing outside tests and was run once via a /tmp driver.
- entry_pilot and entry_context (market_entry_pilot / market_entry_context CLIs, GPU desktop E:/ artifacts).
- timing_research (market_pick_audit only).
- market_intraday_timing, market_charts_intraday, market_intraday_rl, market_execution_rl, market_daytype, market_dip, market_volatility.
- tape and alpaca.intraday_features (model sweep layers 'intraday' and encoder 'tape').
- market_intraday, the manual cache refresh; no scheduled refresh exists.
- market_watch is a standalone alert tool.
- The docs declare the 15-minute layer 'closed' for selection (NEXT_SESSION.md:9029).
## defects
--- [0]
## title
Cron tick coincides with bar end; strict freshness makes whole candles unavailable
## location
docs/NEXT_SESSION.md:7372 (cron */15 9-16); backend/market/live_quotes.py:29,48,74-75,131-160; backend/market/desk_freshness.py:39-55,75-78; backend/agents/trading/desk/intraday_candidate.py:81-94
## severity
medium
## evidence
The cron fires at :00/:15/:30/:45, the same instant a bar ends. RECHECK_SECONDS only helps inside a long-lived process, and the cron process exits after each run. If the just-closed bar is not yet published when a symbol is fetched, its quote carries the previous bar, whose start is about 1800 s old. quote_status requires 900 <= age < 1800, so that symbol is stale. intraday_candidate then refuses the whole allocation unless every graded name is fresh and all share one bar ('Synchronized completed bars required'). The ~95 symbols are fetched sequentially, one HTTP call each with a 60 s timeout, so symbol order decides which ones race.
## effect_on_return_or_risk
Lost or partial candles for the shadow research allocation and the board_paper forward ledger. Any future intraday execution layer built on this loop would silently skip decisions. The frequency is not measured (INFERRED); it can be counted from the 'unavailable' reasons in desk/intraday-research/latest.json history.
--- [1]
## title
IEX-only bars: thin names lose whole sessions and bias every sample toward liquid name-days
## location
backend/market/live_quotes.py:74-75; backend/market/intraday_entry.py:270-287; backend/market/intraday.py:104; backend/cli/market_intraday_timing.py:240-244
## severity
medium
## evidence
IEX emits no bar for a slot with no IEX trade (tape.py:31-35 acknowledges this). A missing 09:30 IEX bar means no live quote for the entire session. Any gap makes the reclaim engine's prefix invalid, so both methods are unavailable. intraday.episodes keeps only sessions with all 26 bars. In Study 2, a name without a complete IEX session on the entry day is scored as 0% (cash) for every confirmation variant but at its real return for the open.
## effect_on_return_or_risk
Research conclusions are conditioned on liquid name-days, and the confirmation variants are mechanically handicapped. In live use, one thin book name (e.g. a recent IPO) blocks the synchronized-bar gate for the day. Delayed SIP bars would remove most gaps.
--- [2]
## title
Study 2 accounting: costs and beta hedge are charged on uninvested capital, and fills happen at the signal bar's own close
## location
backend/cli/market_intraday_timing.py:256-267 (costs/hedge), :260 (entry at confirming close)
## severity
medium
## evidence
Unconfirmed names append 0.0 to the basket mean. The episode return is then raw - beta*spy_ret - 2*30bp, with the full basket's costs and full beta hedge even when only 41-77% was invested. The cost term alone biases the 15m/30m/60m variants by about 14/23/35 bp per episode against the open ((1 - confirmed share) x 60 bp). The fill is the close of the bar that produced the confirmation (zero latency), which biases in the opposite, optimistic direction.
## effect_on_return_or_risk
The reported paired deficits (-51 to -141 bp) have unclean magnitudes. The qualitative 'open is best' conclusion is corroborated elsewhere (market_execution_rl, the 9,968 entry-day fill study), so the decision likely stands, but these numbers should not be reused as effect sizes.
--- [3]
## title
Entry pilot execution prices mix an adjusted IEX cache with a Yahoo adjustment factor and never check scale
## location
backend/market/entry_pilot.py:206-209; backend/market/alpaca.py:154; docs/research/intraday-comparison-input-audit-2026-09-22.md:10-15
## severity
medium
## evidence
execution = bars[d,[k+2,k+6],0] * (adj_close/close). The cache was requested with adjustment=all, so dividends are applied twice. The audit found cached/daily-adjusted ratios with median 9.9964 for AVGO (a book name) before 2024-07-15 and p99 9.83% overall. There is no guard comparing intraday prices to the daily close before labels are built.
## effect_on_return_or_risk
The immediate-entry labels y[:,0] and all funded NAVs (+382%, and the skip-mode results) can be contaminated for affected name-days. The enter/wait choice depends only on y[:,1], which is scale-free within a session, so the 'no timing edge' result is probably robust. INFERRED: whether the desktop E: cache had the same scale defect was not verified.
--- [4]
## title
Early-close sessions are not handled in the core session slicers
## location
backend/market/alpaca.py:205-214; backend/market/intraday.py:74-79,104; backend/market/tape.py:44-48
## severity
low
## evidence
All three use a fixed 09:30-16:00 window. On a 13:00 early close, IEX post-close bars from 13:00 to 16:00 land in regular slots 14..25. A liquid name can then pass the 26-bar completeness check with an after-hours 'close_day' (slot 25). calendar.session_close already knows the dates (2019-2028).
## effect_on_return_or_risk
About 3 sessions a year of contaminated features and labels. The effect is small but violates the anti-look-ahead and clean-session contract.
--- [5]
## title
Session features are indexed by position, not time slot
## location
backend/market/alpaca.py:237-245
## severity
low
## evidence
The first hour uses closes[3]/opens[0], the last hour closes[-1]/closes[-5], and volume front-load uses volumes[:4]. With IEX gaps (sessions need only 8 bars) these span arbitrary clock windows.
## effect_on_return_or_risk
The 'intraday' model layer measured roughly zero, possibly partly because of noise; research only.
--- [6]
## title
The green-day skip reads the IEX first print, not the consolidated open the backtest uses
## location
backend/cli/market_balancer.py:109-121,173-174 vs backend/agents/trading/desk/simulate.py:1233+ (green_day_skip on opens[t+1] > closes[t])
## severity
medium
## evidence
Live compares quote.open (the first IEX trade in the 09:30-09:45 bar) with the Yahoo raw last_close. The simulation uses the official open. A missing 09:30 IEX bar leaves no quote, so the sell proceeds live while the simulation may hold it.
## effect_on_return_or_risk
Divergence between the live and simulated sell/hold decision on names near a flat open. It is unmeasured, and the published /3 curve assumes a rule that live implements differently.
--- [7]
## title
Simulation assumes the official open; paper fills after the first print, and slippage against the open is not recorded
## location
backend/agents/trading/desk/simulate.py:1216; backend/market/alpaca_trading.py:239-271; backend/agents/trading/desk/execution_evidence.py:57-66; docs/research/pick-timing-audit-2026-09-13.md:66-76
## severity
medium
## evidence
Market day orders fill after the open. For example, AAOI filled 09:33:06 at $107.997 against a SIP 09:30 open of $104.49 (+3.36%). execution_evidence measures shortfall only against the decision close, not against the open the backtest assumes. The audit's instrumentation items 1-2 remain unimplemented.
## effect_on_return_or_risk
The live-versus-backtest execution gap on buys is unmeasured. For high-gap AI names it could exceed the bp-scale edges being debated. Anything else built on the next-open assumption inherits this blind spot.
--- [8]
## title
Research cache is stale, non-incremental and lacks the benchmarks
## location
backend/cli/market_intraday.py:58-77; docs/research/intraday-comparison-input-audit-2026-09-22.md:43-47
## severity
low
## evidence
Refreshes are manual and refetch full history per as-of partition. The last audited partition ends 2026-09-18. SPY/QQQ intraday files are absent. The fetch URL hard-codes feed=iex (alpaca.py:154).
## effect_on_return_or_risk
No intraday SPY/QQQ research is possible without new provider calls, and any forward intraday study lacks recent bars.
--- [9]
## title
Shadow ledgers use three different fill models
## location
backend/market/intraday_evaluation.py:72-118; backend/market/board_paper.py:160-176; backend/market/intraday_replay.py:479-565
## severity
low
## evidence
intraday_evaluation fills at the next candle's IEX last close with flat bp. board_paper fills at IEX ask/bid +/-10 bp, capped at the single-venue displayed size. The replay uses the zero-latency next-bar open. None models the declared latency and spread that the microstructure review requires (microstructure-15-minute-review-2026-09-25.md:92-99).
## effect_on_return_or_risk
The forward shadow results are not comparable with each other or with a funded /3-vs-SPY/QQQ ledger, and could mislead a promotion decision.
--- [10]
## title
The reclaim 'incumbent' is not the live /3 rule, and nothing limits repeat entries across sessions
## location
backend/market/intraday_comparison.py:271-308,382-496; docs/research/intraday-turnover-review-2026-09-23.md:36-44
## severity
low
## evidence
The comparison's incumbent fires intraday on 19 prior closes plus the live close. /3 decides at the close and fills at the next open. The ledger dedupes only per (method, symbol, session); three sessions in a row produced three entries.
## effect_on_return_or_risk
The single-source result does not answer 'should /3 buys wait', and a promoted reclaim rule could churn.
## improvement_opportunities
--- [0]
## idea
Re-acquire a qualified delayed-SIP 15-minute (and optionally 5-minute) history, including SPY/QQQ, as a new provenance-tagged frame kind with incremental daily append
## rationale
IEX-only data causes most of the defects above: volume share only, thin-name gaps, a first print that is not the official open, and cross-provider scale failures that block all historical scoring. Delayed SIP history works on the existing free key (22,616 SIP bars fetched 2026-09-13; an approved 1Min probe returned HTTP 200).
## where_it_plugs_in
backend/market/alpaca.fetch_bars gains a feed parameter (URL at :153-157); new BARS_KIND e.g. 'bars_15m_sip' with metadata {feed, adjustment, fetched_at}; market_intraday gains an --append mode; intraday.py/tape.py read the new kind.
## reusable_code
backend/cli/market_pick_audit.py:125-137 _historical_transport (feed swap); alpaca.parse_bars_page/bars_frame; MarketStore.write_frame; intraday_cache provenance/sha256 pattern; the scale audit script pattern (intraday vs daily adjusted close) as an acceptance gate.
## expected_effect
Unblocks every intraday study (entry timing for /3, an SPY/QQQ sleeve, stocks-in-play filters) on consolidated volume and prices, and removes the session-completeness selection bias. It makes no direct return claim.
## risks
Needs the user's explicit approval for provider calls. Entitlement is verified for only one sample and could change. Delayed SIP is always at least 15 minutes old, so a live signal on the latest bar still needs IEX (one bar ahead) or a $99/month Algo Trader Plus plan (extended-hours doc :97-103). Terms limit use to personal, non-redistributed data.
--- [1]
## idea
Same-session funding of rotation buys: pair them with the MOC sells (MOC buys), or bridge them intraday so they fill at the t+1 open while the sells still execute at the t+1 close
## rationale
Ordinary sells fill at the next close while buys fill at the next open, so rotation buys are cash-bounded and deferred to t+2 (paper.py deferred_buys comment). The idle-cash proxy is worth about +5 CAGR. Entering one session later costs -0.29% on average after A-grade arrivals, and -0.34% after a run-up. Sells at the close earn about 24 bp (t 2.8). Keep the good sell timing and remove the funding lag.
## where_it_plugs_in
simulate.py:1216-1219: a per-order buy price (closes[t+1] for MOC-paired buys, or opens[t+1] with an intraday cash overdraft bounded by same-day MOC sell proceeds) plus a new LIVE_POLICY flag. Also paper.plan deferred_buys, market_daily._submit (submit_market_on_close for paired buys) and alpaca_trading.
## reusable_code
simulate.run and its LIVE_POLICY switch, the funding model cash-at-fill-v1, paper.bound_orders, alpaca_trading.submit_market_on_close, event_execution._cash_limit (the 1% price allowance pattern).
## expected_effect
Recovers part of the idle-cash drag on rotation legs. The upper bound is the share of the ~+5 CAGR proxy attributable to rotation deferrals; the MOC variant gains only the overnight return, the bridge gains a full session. It must be measured in simulate.run at 10/25 bp with the frozen protocol.
## risks
Alpaca may reject cls buys or oversized day buys for lack of buying power. The bridge relies on margin, and a failed or cancelled MOC sell (for example a green-day skip) would leave an overnight debit, so the green-day skip must be disabled for bridged legs. PDT rules and account type were not verified (INFERRED). Changes the live policy version.
--- [2]
## idea
Execution-quality instrumentation first: record open-referenced slippage for every fill, then test marketable-limit opening orders
## rationale
The whole /3 track record assumes fills at the official open. The paper account fills after the first print (AAOI +3.36% vs the SIP open), and nobody measures that gap. With turnover about 6.1x a year, 10 bp of systematic opening slippage is about 0.3% CAGR (INFERRED arithmetic), larger than any measured intraday timing edge.
## where_it_plugs_in
execution_evidence: add open_shortfall_bps against the SIP 09:30 bar open fetched after 09:45 by the balancer. alpaca_trading: add submit_limit(symbol, qty, side, limit, tif) for a capped marketable limit such as prior close x (1 + k*ATR) or the first-bar VWAP.
## reusable_code
execution_evidence.decision_shortfall_bps; market_pick_audit SIP fetch; alpaca_trading._call; desk/execution.json journal.
## expected_effect
Quantifies a hidden return leak and bounds adverse opening fills on gap-up names. Direct return improvement is unknown until measured.
## risks
Limit orders can miss winners, as the HPE opg miss shows (+18.7% missed), so an unfilled-order control is needed. Paper fills are not real fills.
--- [3]
## idea
Harden the candle loop: offset the cron by 60-120 s, fetch many symbols per request, and degrade per name instead of per candle
## rationale
This fixes the tick/bar race and thin-name blocking (defects 1-2), which is a prerequisite for any 15-minute entry layer or sleeve.
## where_it_plugs_in
Host crontab (e.g. a sleep of 75 s in desk_intraday.sh). alpaca.fetch_bars: a comma-separated symbols= request (parse_bars_page already reads per-symbol keys). desk_freshness.quote_status: allow a one-bar lag per name. intraday_candidate.calculate:92-94: synchronized bars for traded names only, with the rest marked stale.
## reusable_code
live_quotes._expected_bar, alpaca.parse_bars_page(payload, symbol), desk_freshness.grade_expiries.
## expected_effect
Near-complete candle coverage and lower refresh latency (roughly 1 request per 100 names instead of 100). No direct return effect, but it enables the rest.
## risks
The shadow policy hash changes, and the forward archive grouping resets (intraday-policy-fingerprint doc).
--- [4]
## idea
A registered /3 entry-delay challenger with an unconditional-delay control, as a full account replay rather than a deletion of journal rows
## rationale
No study has conditioned on the actual /3 trigger (closing band z >= 1.10 with A/A+ grades) using intraday fills. The 9,968-day study used the older dip/breakout triggers, and the microstructure review already specifies the design (:83-99, :119-156). Prior evidence caps the value at a few bp per buy, so this closes a question rather than chasing alpha.
## where_it_plugs_in
simulate.run gains a buy fill-price override array per (t+1, j): the 10:00 bar open, first-hour VWAP, or a range/volume veto that defers to the next bar. The 500,440-bar scope for 77 symbols (microstructure doc :138-145) needs the SIP re-acquisition first.
## reusable_code
entry_pilot.bar_grid(root, ticker, dates) -> (T,26,5); entry_pilot.prefix_features; intraday_inputs.load_calendar and ResearchCalendar.close_time for early closes; entry_pilot.paired_interval (20-session block bootstrap); intraday_replay.summarize (common denominators).
## expected_effect
Likely null to +/-0.1-0.3% CAGR. Buy-side timing is worth about 2-8 bp at turnover about 6x (INFERRED sizing from the market_execution_rl and funded-cadence numbers).
## risks
Multiple testing on already-examined 2024-2026 data must be reported as retrospective, not a holdout. Waiting can miss gap-and-go winners, as measured. It consumes a protocol slot.
--- [5]
## idea
A separate 15-minute tactical sleeve on the book's idle cash: SPY/QQQ intraday momentum (noise-area/VWAP trailing-stop family), flat at the close
## rationale
The book averages about 72-76% deployed (paper.py:156), so 24-28% is idle cash. An intraday-only index sleeve does not compete with overnight book funding. The Gao test here ran on 93 volatile single names and lost at every cost, but index-level intraday momentum (the literature's actual domain) was never tested because SPY/QQQ intraday files are absent. INFERRED from outside literature (Gao et al. 2018; Zarattini, Aziz and Barbon 2024) that SPY intraday momentum can survive about 1 bp ETF costs; not verified here.
## where_it_plugs_in
New research module, e.g. backend/market/intraday_sleeve.py, plus a CLI. Funded ledger: generalise intraday_evaluation.evaluate to take historical candle 'decisions' (weights and prices per bar, with a declared one-bar latency). Report against funded SPY and QQQ accounts at 10/25 bp and 1/3 bp ETF-specific costs.
## reusable_code
intraday_evaluation.evaluate(decisions, cost_bps, corporate_actions) for the cash-bounded whole-share candle ledger; intraday.local_minutes/sessions_from; calendar.session_close; market_intraday_rl's corrected Gao implementation (gap-inclusive signal, full last half hour) as baseline; entry_pilot.paired_interval.
## expected_effect
Uncertain. If it works it adds return uncorrelated with the book on otherwise idle cash; if the repo's single-name results transfer, it is negative. It needs a registered protocol with train 2016-2021 and 2022-2026 labelled as examined.
## risks
It needs regular-session intraday order submission, which does not exist and is explicitly refused (market_daily.py:428-434), plus a separate ledger and lock (paper.transaction). IEX real-time data only. Tail risk exists on halt or flash days, and costs dominate at 15-minute resolution.
--- [6]
## idea
A stocks-in-play 15-minute opening-range breakout on the S&P cross-section, with consolidated relative volume
## rationale
The repo's 'first-half-hour momentum' test lacked the stocks-in-play filter (top relative volume or news or earnings), which is the element the ORB literature relies on (INFERRED from Zarattini, Barbon and Aziz 2024). Consolidated RVOL needs SIP data; IEX RVOL is a venue-share ratio.
## where_it_plugs_in
Same sleeve ledger as above. The universe is S&P members plus the book, with earnings dates from the existing tone/earnings store as a catalyst flag.
## reusable_code
entry_pilot.prefix_features relative-volume block (20-session same-slot median, :94-116); intraday_entry completed-bar gating pattern (:209-243); the market_intraday_rl turnover and cost harness.
## expected_effect
Speculative. The strongest published ORB results use 5-minute bars, and 15-minute ranges lose much of that. Keep it as a second-priority sleeve hypothesis.
## risks
The S&P membership is survivorship-biased (current members only) and inflates any stock-selection result. The data volume is large (about 500 names at 26 bars a day). Capacity at the open is fine for a small paper account.
--- [7]
## idea
Session-slicing hygiene before any new study: early-close-aware slots and slot-indexed features
## rationale
This fixes defects 5-6, so new studies do not inherit after-hours prints or misaligned 'first hour' windows.
## where_it_plugs_in
alpaca.sessions (:205-214), intraday.sessions_from (:74) and tape.session_tape (:44-48) all switch to calendar.session_close(day); alpaca.session_features switches to slot-based windows.
## reusable_code
calendar.session_close / reviewed_sessions; intraday_inputs.ResearchCalendar; intraday_single_source EARLY_CLOSE_BARS=14 convention.
## expected_effect
Correctness only.
## risks
Changes the historical feature values, which the frozen studies do not use; version the feature layer.
## reuse_inventory
Data and clock:
- backend/market/alpaca.py: fetch_bars(symbol, start, end, transport=alpaca_transport, headers=None, sleep=time.sleep) -> list[IntradayBar] (:140); parse_bars_page(payload, symbol) -> (bars, next_token) (:113); bars_frame / bars_from_frame (:176, :189); sessions(bars) -> {date: bars} (:205); session_features (:218); intraday_features(panel, bars_by_ticker) (:263).
- backend/cli/market_pick_audit.py:126 _historical_transport(feed, url, headers), the IEX-to-SIP swap.
- backend/market/intraday.py: local_minutes(start) (:43); sessions_from(columns) -> (day, slot, fields, last_close) (:70); episodes_from(...) -> (days, close, high, low, volume, open0, prev) (:96).
- backend/market/calendar.py: session_close(day) (:138); exchange_status(now) (:165); reviewed_sessions() (:99); publication_session(instant, before) (:144).
- backend/market/intraday_inputs.py: load_calendar() -> ResearchCalendar(.close_time, .offset, .sessions) (:60); prior_daily(history, session, calendar) (:96); recorded_eligibility(records, as_of, calendar) (:131).
- backend/market/intraday_cache.py: load_intraday(symbol, partition_dir, *, price_basis) and load_daily(...) with sha256 provenance (:322, :359).
- backend/market/intraday_preflight.py: session_schedule_from_calendar(calendar) -> SessionSchedule (:125).

Causal engines:
- backend/market/intraday_entry.py: _completed_bars(bars, session, as_of, close=None) (:209), which enforces completed, contiguous prefixes; evaluate(symbol, session, bars, levels, as_of=None) -> EntrySignal (:520).
- backend/agents/trading/desk/timing_research.py: hourly(bars) (:26); readings(bars, history) (:56); evaluate(bars, rows, published, entry_kind, exit_kind, cost_bps=10) (:154).
- backend/market/tape.py: session_tape(bars) (:36), gap-filled 26x5.

Labels and ledgers:
- backend/market/intraday_replay.py: execution_proxy(bars, event) (:479); endpoint_label (:650); excursion (:815); summarize (:1178), which keeps common denominators.
- backend/market/entry_pilot.py: bar_grid(root, ticker, dates) -> (T,26,5) (:142); prefix_features(bars, k, previous_close, historical_volume) (:94); evaluate(data, mask, action, cost_bps) funded cohort ledger (:275); paired_interval(result, baseline, block=20, repetitions=1000) (:349).
- backend/market/intraday_evaluation.py: evaluate(decisions, cost_bps=10, corporate_actions=None), a candle-cadence cash-bounded whole-share target tracker with sells-before-buys and dividends (:46).
- backend/market/board_paper.py: transition(state, decisions, research, now), a quote-based forward ledger (:88).
- backend/agents/trading/desk/simulate.py: run(..., **LIVE_POLICY) with fill arrays at :1216-1219.
- backend/cli/market_intraday_timing.py: _stats(values) (:45).

Live and broker:
- backend/market/live_quotes.py: quotes(symbols, session=None, fetch=alpaca.fetch_bars, now, clock, headers) -> {sym: Quote} (:131); quote_from_bars (:57); _expected_bar (:97).
- backend/market/live_technical.py: with_live_row(panel, quotes, today) -> Panel (:93).
- backend/market/execution_quotes.py: fetch(symbols) (:26); describe(raw, feed, market_open, now) (:64).
- backend/market/session_prices.py: session_window(now) (:32).
- backend/market/alpaca_trading.py: AlpacaTradingClient.submit_market_on_open (:250), submit_market_on_close (:279), cancel_orders, clock; client_from_env is paper-only (:300).
- backend/agents/trading/desk/paper.py: transaction(root) file lock; entry_size(band).
- backend/agents/trading/desk/execution_evidence.py: broker_evidence, decision_shortfall_bps(side, filled_price, reference) (:57).
- backend/market/forward_evidence.py: day-cohort summarize, MIN_COHORTS=20.
## open_questions
1) Bar publication latency. How often does the */15 cron tick see the just-closed IEX bar? This can be counted from the history of desk/intraday-research/latest.json and board-paper rows, without provider calls.
2) Did the GPU desktop cache (E:/) used by entry_pilot and entry_context carry the same AVGO ~10x or WRB 1.5x scale breaks found on the Spark partition? This determines whether the pilot's absolute NAVs and skip results are valid.
3) Paper account type and buying power. Would Alpaca accept MOC buys funded by same-close MOC sells, or day buys above cash (margin bridge)? Are PDT or overnight-debit rules relevant? This is unverified.
4) Exact /3 turnover and the share of buys that are rotation-deferred. These are needed to convert bp-per-fill findings into CAGR; the only figure found is the 6.10x/yr proxy in intraday-funded-cadence-2026-09-14.json.
5) Is delayed-SIP historical entitlement durable for this key? One probe and one audit succeeded. Any new fetch needs the user's explicit approval (strict rules forbid provider calls in this review).
6) Frequency of green-day skip live/backtest divergence (IEX first print vs official open, missing 09:30 IEX bar). It is not logged against the consolidated open.
7) The user's acceptable drawdown is still unanswered (NEXT_SESSION.md:870-871). It decides whether the exposure lever outranks any intraday idea. That lever is outside this area: market_cadence shows vol target 50% with caps 25/80 at 42.0% CAGR / DD -25.5% against 31.6% / -17.8%.
8) Whether a regular-session order path for a tactical sleeve is acceptable at all. It would reverse the explicit market-open refusal in market_daily._submit and needs a separate ledger, lock and kill-switch design.
9) Whether the 15-second display collector should become a real quote archive (it overwrites latest.json today). Without one there is no historical spread or queue evidence for any HFT-style execution claim.