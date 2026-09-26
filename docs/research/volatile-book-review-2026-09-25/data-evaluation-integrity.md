## area
data-evaluation-integrity
## how_it_works
NIGHTLY END TO END (backend/cli/market_daily.py). The nightly runs on spark1 at 19:30 ET on weekdays (docs/CHANGELOG.md ~3819). The documented cron line is `market_daily --refresh --brief-book --prune-days 30 --llm-url ... --llm-model deepseek-v4-flash` (docs/NEXT_SESSION.md:8934-8943). `--paper-trade` was added later. INFERRED: `--challenger` is also set, because records have carried a challenger block since 2026-09-08 (market_scorecard.py:8-10).
(1) main() reads the git revision once and takes an OS flock on data/market/desk/nightly.lock (market_daily.py:1436-1449, nightly_lock.py:82-110). A second run exits with code 75.
(2) refresh() (market_daily.py:155-208) runs in this order:
  - Bars: Yahoo daily bars for the ~531 research names plus 15 benchmark ETFs plus macro series (^VIX, ^TNX, DX-Y.NYB, CL=F) (bar_tickers :131, macro.py:40-45) go into one as-of partition through snapshot.refresh (snapshot.py:378-424). Each ticker's full history since 2015-01-01 (DEFAULT_START :36) is re-fetched. A response that drops a previously seen session is retried or refused (:109-126).
  - EDGAR events and facts for the research names (market_edgar.refresh).
  - Every filed version of the book's facts (market_fundamentals_asof.refresh, :56-86).
  - The frozen ML observer (opportunity_shadow), placed before tone.
  - LLM release tone for the ~94 book names only, under a 180-minute budget (:84-86, 187-208).
(3) trading_desk.run(store, asof) (desk.py:152-224) does the following:
  - book_panel uses today's build_universe() and book_sides (desk.py:100-105).
  - The analysts are:
    - fundamental: the corrected as-of versions (fundamentals_asof → fundamental_features).
    - technical: including residual_momentum.
    - sentiment: LLM tone.
    - value: levels_pit.point_in_time_levels (desk.py:200).
    - regime.
  - The live input 'expectations-gap' (challenger.expectations_gap: a walk-forward LightGBM expected growth minus the P/S-implied growth) is blended into value (desk.py:204-224).
  - grading.grade assigns A+/A/B/C with a bearish veto (grading.py:231-274). risk.size produces weights (BOOK_CONFIG target vol 0.30, name cap 0.15, top_fraction 0.1; risk.py:48-49).
(4) If a record for the session exists, the run is refused before any trade (:1148-1157, 1523).
(5) paper_trade (:622-808) does the following:
  - It reconciles the broker's fills and plans with paper.plan (/3: 20-session reset, A/A+ entries, band z >= 1.10 mid-cycle adds, rotation out of anything below A, deferred buys).
  - It submits buys as market-on-open and sells as market-on-close for the next session (:436-456).
  - Reference prices are the raw panel close (:656-660).
(6) The evidence blocks come next:
  - the challenger (the plain rule as shadow)
  - fundamentals_shadow (the as-of value analyst against the frozen path)
  - fomc_gate
  - execution_quality
  - the reversal shadows
  - curves() (simulate.run with the LIVE_POLICY plus SPY/QQQ lines)
  - tone revisions
(7) record() writes data/market/desk/asof=<session>/desk.json (:935-1099, save :1202-1212). It refuses to overwrite, and provenance carries the code revision, rule name, data window and fundamentals source.
(8) After the record:
  - learned_inputs.capture archives the inputs the desk actually saw, including panel.tickers (learned_inputs.py:187-191).
  - write_history is run.
  - prune deletes bars/actions/edgar_events/edgar_facts partitions older than N days, keeping the newest (:46, 232-253).
  - The prose step runs under a 45-minute budget, then economics.
record_status flags a missing record after 07:00 NY the next morning (record_status.py:27).

STORAGE FORMAT. MarketStore (store.py) is organised as <root>/<kind>/asof=YYYY-MM-DD/<TICKER>.parquet.
- Partitions are written once and atomically (tmp file then os.replace, :331-334), and a rerun of an existing ticker is a no-op (:81-128).
- Bars carry session_date, open, high, low, close, adjusted_close and volume, with parquet metadata {source, source_time, complete_through, asof}.
- Actions carry action_date, kind (split|dividend) and value.
- write_frame/read_frame hold the generic kinds: edgar_events, edgar_facts, edgar_facts_versions, tone, bars_15m, and forward_actions_*.
- read(ticker, asof) returns the newest partition <= asof (:218-289).
- Yahoo `close` is split-adjusted as of the fetch date, and `adjclose` is split- and dividend-adjusted. There is no unadjusted series (yahoo.py:22-27).
- The Panel aligns the union calendar with no fill (panel.py:157-198). log_returns come from adj_close (:57-59).
- Desk records, prose, history/*.json, strategy_bench.json and the shadow ledgers are JSON under desk/.

POINT-IN-TIME GUARANTEES.
(a) Prices are PIT only when pinned by asof partition. The live desk and every backtest read the latest partition, so history is back-adjusted to today. That is harmless for ratio indicators, but not for price x shares (see defects).
(b) Filings:
  - EarningsEvent.reaction_date is the acceptance date if accepted before 16:00 NY, otherwise the next day (edgar.py:153-158).
  - Legacy facts are visible when filed <= session (non-strict) or filed < session (strict) (edgar.py:581-584). The first-reported value per period end is kept.
  - fundamentals_asof.Version.available is acceptance-based, else filed+1 day (fundamentals_asof.py:81-89). The Spark inventory found every `accepted` blank, so filed+1 always applies (docs/research/historical-universe-coverage-2026-09-25.md).
(c) Signals are decided at close t and filled at the t+1 open. The simulator slices the panel to t for sizing (simulate.py:431-452) and plans at the close, filling at adjusted opens (:1126-1260). Sells fill at the t+1 close under exit_at_close, and a green-open sell is skipped.
(d) Tone timing is PIT by release acceptance, but the scores come from a 2026 LLM, which is hindsight (see defects).
(e) Records are immutable and learned_inputs are captured only on ordinary current runs. The records are the only uncontaminated history.

SURVIVORSHIP. The universe is today's S&P 500 (constituents.csv, dated 2026-09-05, 503 rows) plus a 68-entry hand overlay. The book is 94 names chosen in 2026.
- universe.as_of/membership.members_as_of exist (universe.py:87-93, membership.py:83-92), but data/membership_history.csv does not exist and book_panel never calls them.
- historical_cohort.py is an evidence-archive importer with historical_backtest_ready hard-coded False (:601).
- market_survivorship measured the equal-weight book at +34.2%/yr against +15.6%/yr for the non-book S&P, so about 19 points/yr comes from name choice.

SPY/QQQ COMPARATORS (four conventions).
(1) benchmarks.load_benchmark (benchmarks.py:133-192) is the strict one:
  - It is read independently from the store and must cover every session of the strategy's calendar with adjusted prices, or it is reported unavailable.
  - It starts in cash at NAV 1, buys all capital at the session-1 adjusted open with cost 10 bp as notional*(1+c) (:185-186), holds shares x adjusted_close (total return, dividends reinvested) and is never liquidated.
  - It is used only by market_strategy_bench.py:87-94 at simulate.COST_BPS=10.
(2) market_daily.curve_block, the published page curve:
  - SPY comes from the panel's benchmark column as costless adj close-to-close from the sim's first close (:1253-1263).
  - QQQ comes from scorecard.index_returns (latest partition, costless, NaN set to 0) (:1264-1272).
(3) scorecard.render / _portfolio_block (desk/scorecard.py:63-121, 153-156) uses costless close-to-close from the latest partition, which drops NaN.
(4) allocation_controls.constant_exposure (:98) is a causal funded constant-fraction SPY/QQQ control at 10 bp with next-open fills, used by the nested and neural research at 10/25 bp.
The forward intraday evidence subtracts SPY only (forward_evidence.py:148-172).

COST STRESSES. The simulator uses one-way 10 bp on both legs (simulate.py:59; _fill :1557-1573). The canonical bench and scorecard run 10 bp only. 25 bp exists only in research paths: forward_evidence (:260-264), nested_allocation COSTS=(10,25), neural_study_metrics, market_fomc, chronological diagnostics. The reversal shadow uses 10/30. fomc_gate uses 25. market_entry_context uses 5/10/20. paper.py cites measured slippage of about 6 bp ('30 bp is five times the account's measured slippage', paper.py:~140-145).

CASH YIELD. It is zero everywhere:
- _Book cash never accrues (simulate.py:1320, 1385-1392).
- allocation_controls docstring: 'idle cash earns nothing'.
- research_journal manifest cash_yield 0.0 (:185).
- Sharpe is mean*252/vol with rf=0 (simulate.py:304, strategy_bench.py:78).
No T-bill series is stored; macro holds ^TNX only.

REGISTERING A NEW STRATEGY AS A SHADOW. There are four existing patterns.
(A) Record challenger slot:
  - report.alternate goes into record['challenger'] = {name, book, grades} (market_daily.py:864-875, challenger.record_block :116-135). It has one slot, currently the plain-value rule.
  - It is priced by `market_scorecard --records`. _forward_walk (market_scorecard.py:101-177) walks each strategy's recorded book weights:
    - It sizes with the shared planner at record a's close and fills at record b's adjusted open.
    - It rebalances every 20 records at 10 bp and applies no rotation, mid-cycle entries, deferred buys or FOMC.
  - scorecard.render then prints CAGR, CAGR at the rule's volatility, vol, Sharpe, max drawdown, turnover, top position, within the 25% loss limit, and yearly results against SPY/QQQ.
(B) Standalone ledger shadows written from the nightly (never raising) with a registered doc and gate:
  - reversal.py: VERSION, SHADOW_START 2026-09-16, verdict :169-207.
  - fomc_gate.py: exact counterfactual from fills, MIN_MEETINGS=6, 25 bp column.
  - opportunity_shadow.py: code+bundle SHA-256 identity(), append-only sequence files, POLICIES = neural, valuation_rule, momentum20, SPY, USD.
(C) Intraday research archive:
  - desk/intraday-research/decision-*.json records {version, policy_sha256, as_of, bar, valid_until, grades, entry_states, prices, targets}.
  - It is scored by forward_evidence.report: first daily signal, entry at a later observed 15-minute candle, 5- and 20-session horizons, stock total return minus SPY minus 2x cost, at 10 and 25 bp.
  - intraday_evaluation.evaluate runs funded whole-share target trackers.
(D) The research-only nested/allocation studies, with journal plus independent replay (research_journal(_replay).py).

MINIMUM EVIDENCE.
- The scorecard has none: it renders from 2 records, and the only threshold is the 25% loss limit.
- forward_evidence needs 20 non-overlapping cohorts before an interval is shown (MIN_COHORTS :19). At h=5 that is about 100 sessions; at h=20 it is about 400 sessions.
- The reversal gate needs t > 2, mean > 0 and at least 60% positive at 30 bp (deep subset n >= 8).
- The FOMC gate needs 6 meetings.
- The roadmap asks for 'a season' with the gate written before the first session (docs/TRADING_ROADMAP.md).
- There is no automatic promotion anywhere.

FASTEST HONEST PATH FOR A NEW STRATEGY.
Historical, in days and with caveats:
(i) First fix, or neutralise, the split/market-cap look-ahead below; otherwise any candidate that reads value or the expectations gap inherits it.
(ii) Express the candidate through simulate.run hooks:
  - allocator(report, panel, config, t) for selection/balancer targets on reset days
  - DipRule(signal=(T,N) bool, funded=True) or live_midcycle for entries
  - brake_path_override for exposure
  - funded_allocation for daily decisions
  Run with use_exits=False, rebalance=paper.REBALANCE_EVERY, event_exposure=event_risk.live_path(panel), event_lifecycle=True and **LIVE_POLICY, at cost_bps 10 and 25.
(iii) On the identical calendar, run:
  - the incumbent
  - the calendar-only control
  - an equal-weight-book control, which is the real hurdle because the universe is hindsight-picked
  - load_benchmark SPY/QQQ at 10/25
  - constant_exposure SPY/QQQ at the candidate's mean invested fraction
  Feed all of them into strategy_bench.build for the calendar regimes, plus the multiple start phases the desk already uses.
(iv) Treat everything up to today as examined. Tune nothing on 2024-2026, and report the survivorship, LLM-tone and zero-cash-yield caveats.
Prospective:
(i) Write docs/research/<name>-<date>.md with the rule, its fingerprint, the gate and the costs before the first session.
(ii) Emit the shadow nightly from a guarded hook next to _reversal_shadows (market_daily.py:880-889) into its own append-only ledger (the opportunity_shadow pattern) or a named record block.
(iii) Score it against the incumbent and funded SPY/QQQ from the registration session.
(iv) For 15-minute entry timing, pair every real /3 buy with the candidate's counterfactual fill. A paired per-order difference reaches significance far faster than a portfolio-level comparison (INFERRED arithmetic in improvement_opportunities).
## parameters_and_constants
NIGHTLY / STORE (LIVE):
- market_daily.py:46 PRUNABLE=(bars, actions, edgar_events, edgar_facts). Tone, edgar_facts_versions and desk records are never pruned.
- Documented cron --prune-days 30 (docs/NEXT_SESSION.md:8936, INFERRED still current).
- :84-86 tone budget 180 min.
- :74-80 prose budget 45 min.
- :72 concurrency 4.
- :91 --top 25.
- :1487 asof = datetime.now(UTC).date() (live).
- snapshot.py:36 DEFAULT_START=2015-01-01 (live).
- yahoo.py:46-47 min interval 0.35 s, 4 attempts, backoff 2^n or Retry-After (live).
- edgar.py:52 0.15 s pacing; :133-134 NO_EVENT_SESSIONS=250, NO_FACT_SESSIONS=400 (live).
- universe.py:78 STALE_AFTER_DAYS=7; :74 MARKET_INDICES=(SPY,QQQ); :68 MARKET_BENCHMARK=SPY (live).
- record_status.py:27 DUE=07:00 NY next day (live, API).

POINT-IN-TIME RULES:
- fundamentals_asof.py:81-89 available = acceptance date, +1 day if accepted at or after 16:00 NY, else filed+1 (live via fundamental analyst).
- :92-103 span_kind: quarter 80-100 days, year 350-380, YTD 170-195 or 260-285 (live).
- :255-262 trailing four quarters require consecutive quarter ends 75-105 days apart (live).
- :316 revenue_growth uses 252 sessions back (live).
- edgar.py:153-158 reaction_date cutoff 16:00 (live).
- :581-584 non-strict same-day filed facts visible (live value path); strict excludes them (expectations path).
- levels_pit.py:186 split factor applied only when seen < split <= days[t] (live; defect).
- levels_pit QUARTERS annualisation (live).

GRADING/SIZING (LIVE, affects what is evaluated):
- grading.py:81 SIZE_MULTIPLIER A+=A=1.0, B=C=0.
- :82 ROTATION_WEIGHT=0.5.
- :93-99 equal analyst weights.
- :254-261 thresholds: B at votes >= 0.5; A at votes >= 2, or bullish release and votes >= 1, or fundamental and technical both bullish and votes >= 1.5; A+ at bullish release and votes >= 2.
- :269-273 a bearish core or value stance caps the grade at B.
- risk.py:48-49 BOOK_CONFIG top_fraction 0.1, target_volatility 0.30, name_cap 0.15.
- paper.py:68 REBALANCE_EVERY=20.
- :69 MIN_TRADE=0.005.
- :160 ENTRY_BAND_Z=1.10.
- :166 ENTRY_ADD=0.023.
- :167 ENTRY_NAME_CAP=0.15.
- :168 ENTRY_MIN_GRADE=(A, A+).
- :169 POLICY_VERSION=cash-bounded-breakout-rotation/3.
- :173 ENTRY_SIZE_REF=1.25.
- trend_brake.py LOOKBACK=200, ENTER_BELOW=0.97, EXIT_ABOVE=1.02 (shadow/research, brake_scale 0.5 in simulate.run :672).

SIMULATOR/EVALUATION:
- simulate.py:55 REBALANCE=20; :58 REDEPLOY=True; :59 COST_BPS=10.0; :60 MIN_TRADE=0.005; :61 START_EQUITY=1.0; :62-63 FUNDING_MODEL cash-at-fill-v1 / VALUATION complete-held-marks-v1.
- :72-78 LIVE_POLICY {block_overbought, exit_at_close, green_day_skip, live_midcycle, deferred_buys}=True (live curve, bench).
- :304 Sharpe rf=0.
- benchmarks.py:30-31 START_EQUITY 1.0, DEFAULT_COST_BPS 10 (research bench).
- strategy_bench.py:40-47 REGIMES:
  - Whole sample
  - Pre-COVID bull 2015-01-02..2020-02-19
  - COVID crash ..2020-03-23
  - COVID recovery ..2021-12-31
  - 2022 bear
  - AI boom 2023-01-03..
- :78 Sharpe rf=0; :75 annual only when years > 0.15.
- scorecard.py:126 loss_limit 0.25 (CLI).
- market_scorecard.py:49 --since 2021-06-01; :58-60 REBALANCE 20, COST_BPS 10, MIN_TRADE 0.005 (forward walk, research CLI).
- backtest.py:29 STOP_BUFFER 0.03; :33 PATIENCE 10; :36-37 ATR 20 x 3.0; :56 cost 10 bp (research CLI market_desk).
- forward_evidence.py:18 HORIZONS=(5,20); :19 MIN_COHORTS=20; :172 excess against SPY minus 2 x cost; :260-264 costs (10,25) (shadow/API).
- intraday_evaluation.py:47 start equity 100,000; whole-share floors; fill at next recorded candle price (shadow).
- reversal.py:29-41 SIGNAL 5, HOLD 10, DECILE 0.10, MIN_NAMES 5, WEIGHT 0.10, DEEP -0.10, BETA_LOOKBACK 120, COSTS (10,30), SHADOW_START 2026-09-16 (live shadow ledger).
- fomc_gate.py:32-35 VERSION fomc-gate/1, FIRST_MEETING 2026-09-16, MIN_MEETINGS 6, COST_BP 25 (live shadow).
- allocation_controls.py:52 COST_BPS 10, START_EQUITY 1 (research).
- nested_allocation.py:29-31 COSTS (10,25), MODES cash/stock/SPY/QQQ, STOCK_CADENCE 20 (research).
- harness.py:159 evaluate_scores defaults cost 10, top_fraction 0.2, min_names 20 (research).
- baselines.py:152 residual_momentum length 120, skip 21, beta 120 (LIVE via technical.py:128).
- windows.py window 20 / horizon 10 (research, model.py).
- research_journal.py:185 cash_yield 0.0 (research).
- Cash yield is 0 in every path (simulate._Book, allocation_controls, research_journal) (live and research).
## measured_results
All of these come from the in-repo docstrings and docs. They are in-sample on the hindsight universe unless marked forward.

- market_scorecard.py:17-27 (2026-09-08, from 2018-06, with costs):
  - Rule: +25.2% CAGR, vol 16.3%, Sharpe 1.46, max drawdown -23.4%, turnover 5.8x, top position 19%.
  - expectations-gap: +30.3% (+27.5% at the rule's vol), vol 18.0%, Sharpe 1.56, drawdown -24.6%, turnover 5.6x, top position 23%.
  - The challenger beats the rule in 7/9 years. The rule beats SPY in 7/9 and QQQ in 5/9.
- desk.py:130-139: the promotion of expectations-gap on 2026-09-10 rested on +30.3% against +25.2% and Sharpe 1.56 against 1.46. The forward record was 2 sessions old.
- market_cadence.py:18-42 (from 2021-06-01):

  | Setting | Return | Vol | Sharpe | Max DD |
  |---|---|---|---|---|
  | Rebalance every 1 session | 27.5% | 16.8% | 1.63 | -18.3% |
  | Every 5 | 29.7% | | 1.78 | |
  | Every 10 | 30.3% | | 1.85 | |
  | Every 20 | 31.6% | 16.7% | 1.90 | -17.8% |
  | Every 40 | 32.4% | | 1.88 | -18.8% |
  | Vol 35%, caps 20/70 | 38.8% | | 1.87 | -24.8% |
  | Vol 50%, caps 25/80 | 42.0% | | 1.89 | -25.5% |

  Total return at every 20 is +388%.
- market_daily.py:1229-1234: across start phases, a 20-session reset gives about 38%/yr at Sharpe 1.44 against about 29%/yr at 1.13 for a 120-session reset.
- grading.py:40-80:
  - Flat against ladder sizing, from 2021: 58.42% vs 51.23%, Sharpe 1.449 vs 1.434, drawdown -46.12% vs -42.74%.
  - From 2018: 44.73% vs 39.35%, Sharpe 1.323 vs 1.283.
  - Dropping B at reset 20: dCAGR -0.37%, +0.033 Sharpe, +1.87 points drawdown, better in 6/6 phases.
  - Ridge weights walk-forward from 2018: 25.0%/1.61 against the rule's 27.2%/1.65.
- universe.py:352-358: restoring the 19 utilities gives 38.45%/1.247/-42.05% against 34.12%/1.178/-42.19% over 20 start phases.
- market_survivorship.py:42-66:
  - Equal-weight book: +34.2%/yr, 27.5% vol, Sharpe 1.24.
  - Off-book S&P control: +15.6%/yr, 17.8% vol, 0.88, so about 19 points/yr comes from name choice.
  - Technical IC at h20: book 0.0234 (t 1.31) against control -0.0017.
  - Sentiment IC 0.0372 (t 2.96) and value 0.0377 (t 2.64) are measurable on the book only.
- value.py:5-14: rank IC 0.048 (t 3.6) at 20 sessions and 0.077 (t 3.3) at 60; size-neutral 0.036 (t 2.3); blended with the grade 0.057 (t 4.2). These are contaminated by the split-cap defect below (INFERRED).
- docs/TRADING_ROADMAP.md: on as-of filing versions the valuation rule's retrospective return fell from about +255% to +150%.
- docs/research/fixed-strategy-attribution-2026-09-25.md (/3 journals, 1,684 intervals, 2020-01-06..2026-09-18):
  - Worst drawdown -37.33% at 10 bp and -37.58% at 25 bp, with about 89.6% stock exposure during it.
  - SNDK/DELL/LITE/MU/NVDA account for 66.91% (68.00%) of net gain.
  - Largest single-name weight: DELL at 31.60%, against a 15% cap.
- docs/research/opportunity-and-cash-2026-09-18.md (147 non-overlapping 20-session windows):
  - Opportunity IC 0.0408 (t 2.67); desk score IC 0.0457 (t 3.21), with a 1.46% quintile spread.
  - Every risk-off condition was followed by higher equal-weight book returns. For example, benchmark 5% off its high was followed by +4.77% against +2.71%.
- paper.py:~150-160: ENTRY_BAND_Z 1.10 against 1.25 adds +2.31 CAGR points at 10 bp and +1.55 at 30 bp, in 8/8 phases; deployed share goes from 72% to 76%.
- market_daily.py:541-547: rotation on downgrade adds +3.42 CAGR points at reset 20 against -8.32 at 120, positive in 12/14 phases.
- market_daily.py:690-693: selling the rotation signal to cash costs 24 points of CAGR; the band exit costs 3.0%/yr.
- execution_quality.py:12-17: 9 FOMC restoration buys measured +234 bp against the decision price, split into +243 bp gap and -9 bp trading. paper.py implies measured slippage of about 6 bp.
- docs/research/microstructure-15-minute-review-2026-09-25.md: the allocation gate loses to its matched comparator in 10/14 folds at 10 bp and 11/14 at 25 bp.
- filings.py: lazy-prices IC +0.026 (t 1.6), not adopted.
- docs/research/historical-universe-coverage-2026-09-25.md:
  - 5,556 bar files over 16 snapshots (Sep 5-24).
  - 18,436 dividends and 179 splits.
  - 174,512 versioned fact rows, all with a blank `accepted`.
  - Community S&P history: 268 of 771 tickers since 2014 are absent today.
  - Membership_history.csv is absent.
- No forward (untouched-session) performance number for the rule, the shadows or the paper account is recorded in code or docs.
## wiring_status
LIVE (nightly market_daily):
- store / snapshot / yahoo bar refresh
- edgar events and facts
- fundamentals_asof versions refresh and levels (the fundamental analyst via fundamental_features)
- levels_pit.point_in_time_levels (value analyst, desk.py:200)
- challenger.expectations_gap (live input since 2026-09-10)
- grading
- baselines (percentile_rank, rank_blend, residual_momentum inside the technical analyst)
- universe.build_universe / book_sides
- nightly_lock
- deskrecord (API, card, scorecard)
- record_status (API)
- report_files (atomic writes for fomc_gate, reversal, prose, execution_quality)
- economics (after prose, current runs only)
- learned_inputs.capture
- curve_block (simulate.run with LIVE_POLICY plus costless SPY/QQQ)
- paper_trade (Alpaca PAPER, with --paper-trade)

SHADOW (written nightly, never traded):
- record['challenger'] = plain-value rule (--challenger)
- record['fundamentals_asof'] via fundamentals_shadow (as-of value analyst against the frozen path)
- reversal meeting and any-day ledgers
- fomc_gate (with --paper-trade)
- opportunity_shadow ML forward (frozen bundle)
- intraday research archive (backend/cli/market_intraday_research.py and market_balancer → intraday_research.publish), evaluated read-only by forward_evidence (backend/cli/evaluate_intraday_research.py and the API) and intraday_evaluation
- recommendation_history (API) reads the same archive

RESEARCH-ONLY CLIs, run by hand:
- market_scorecard (history and --records forward walk)
- market_strategy_bench, which writes desk/strategy_bench.json for the page (benchmarks.py is imported only here and by strategy_bench)
- market_cadence
- market_fundamentals_asof --audit
- market_historical_cohort, which imports historical_cohort and membership
- market_desk, the only caller of desk/backtest.py
- desk/scorecard.render, used by market_scorecard and market_interactions
- scorecard.index_returns is also live inside curve_block
- windows (model.py only)
- filings (market_filings CLI only; 'nothing feeds the desk')
- research_journal / research_journal_replay (nested_allocation, nested_market_study, allocation_attribution, market_verify_journal)
- fundamental_unit_sources / fundamental_period_sources (no non-test callers except each other)

DEAD OR UNPOPULATED:
- universe.as_of and membership.members_as_of: the data file is absent and there are no production callers.
- historical_backtest_ready and adoption_eligible are hard False.

CRON STATE (INFERRED, the crontab is not in the repo):
- 19:30 ET weekdays with --refresh --brief-book --prune-days 30 plus --paper-trade.
- --challenger, inferred from challenger blocks in the records.
## defects
--- [0]
## title
Split look-ahead in point-in-time market cap: pre-split sessions use post-split-adjusted prices with pre-split share counts
## location
backend/market/levels_pit.py:153-191 (condition at :186), consumed at backend/market/valuation.py:68, backend/agents/trading/desk/desk.py:200, backend/cli/market_expectations.py:368-408
## severity
high
## evidence
panel.close is Yahoo close split-adjusted to the fetch date (yahoo.py:22-27). split_adjusted_shares multiplies a filing's shares only by splits with seen < day <= days[t] (:186). For every session t before a split that the fetch already reflects, the factor is 1 while the price is divided by the split ratio. So cap = true_cap / ratio. For example, AVGO on 2024-07-12: close 166.93 (split-adjusted, per docs/research/intraday-price-basis-reconciliation) x ~465M pre-split shares = ~$78B, against ~$780B true. Affected names include NVDA (4:1 2021, 10:1 2024), AVGO/SMCI/LRCX (10:1 2024), ANET (4:1 2021 and 2024), GOOGL/AMZN (20:1 2022), PANW, FTNT and AAPL. The code comment at :147-152 intends to avoid 'a tenfold cheapness before it' but does not. The 2026-09-24 audits flagged only the frozen trailing_levels path (neural-comparison-readiness doc).
## effect_on_return_or_risk
Flatters every historical backtest that reads value or the expectations gap. Names that later split (typically after big run-ups, so future winners) look 2-20x cheaper vs their side and have lower P/S-implied growth during exactly the run-up. This inflates the value analyst's IC (0.048, t 3.6), the expectations-gap promotion evidence (+30.3% vs +25.2%), and the /3 curves (~38%/yr). The live last-row value opinion is unaffected. The live expectations LightGBM is trained each year on the distorted log_cap and ps_implied_growth history, so live grades are indirectly affected (INFERRED magnitude).
--- [1]
## title
No point-in-time membership: every historical evaluation runs on today's hand-picked book
## location
backend/agents/trading/desk/desk.py:100-105; backend/market/universe.py:81-93; backend/market/membership.py:83-92
## severity
high
## evidence
book_panel always calls build_universe(). universe.as_of is never called and data/membership_history.csv does not exist. market_survivorship measures EW book +34.2%/yr vs off-book S&P +15.6%/yr.
## effect_on_return_or_risk
Absolute returns against SPY and QQQ are uninformative, with about 19 points/yr of flattering. A selection strategy can 'beat' the benchmarks while adding nothing over equal-weighting the hindsight book (~38-41% CAGR). The off-book control is itself survivor-biased.
--- [2]
## title
Zero cash yield and rf=0 Sharpe in every simulator, bench and journal
## location
backend/agents/trading/desk/simulate.py:1320,1385-1392,304; backend/market/strategy_bench.py:78; backend/market/allocation_controls.py (docstring); backend/market/research_journal.py:185
## severity
medium
## evidence
Cash never accrues and no T-bill series is stored (macro.py:40-45 has ^TNX only). The live book averages ~24% cash (paper.py: deployed share 72%->76%). The trend brake parks half the book in cash while risk-off.
## effect_on_return_or_risk
Understates cash-holding strategies against fully invested SPY/QQQ by roughly cash share x T-bill rate. That is ~0.24 x 4.5-5% = ~1.1 pts/yr in 2023-2026 (INFERRED), and more for defensive overlays. It also overstates the cost of the trend brake (-1.7 CAGR) and of cash-bounded funding. Sharpe comparisons against benchmarks are mis-scaled when rates are high.
--- [3]
## title
Records forward walk is not the live policy and penalises late-starting shadows; it has no statistical gate
## location
backend/cli/market_scorecard.py:101-177, 191-274; backend/agents/trading/desk/scorecard.py:96-121
## severity
medium
## evidence
- The cadence is counted in records, not sessions (:143). There is no rotation, mid-cycle entry, deferred buy or FOMC handling.
- Buys are not cash-bounded, so cash can go negative (:152-166).
- Every track starts at records[0] with cash=1, so a shadow registered later books flat 0% returns until its first decision (:112-124, 169-176).
- A held name with a missing close is valued at 0 for that step (:169-173).
- The benchmark from index_returns loses the first interval (out[0]=NaN), while the strategy series includes it.
- SimResult.stats counts each record step as one session.
- render() needs only 2 records and applies no minimum sample or t-test.
## effect_on_return_or_risk
Forward verdicts between the live rule and a shadow can be biased by start date and simplified execution. A new strategy's untouched-session record understates its CAGR and Sharpe in proportion to its late start. Nothing stops a promotion on a statistically meaningless sample: expectations-gap was promoted after 2 forward sessions.
--- [4]
## title
Inconsistent SPY/QQQ conventions; QQQ absent from forward evidence; 25 bp stress absent from the canonical bench
## location
backend/cli/market_daily.py:1253-1272; backend/agents/trading/desk/scorecard.py:81-91,153-156; backend/cli/market_strategy_bench.py:87-94; backend/market/forward_evidence.py:148-172
## severity
medium
## evidence
- The page curve uses costless close-to-close SPY from the panel and QQQ via index_returns with NaN->0.
- The scorecard is costless.
- The strategy bench is funded at 10 bp only.
- forward_evidence computes excess against SPY only.
- The 10/25 bp funded comparisons exist only in research modules (nested_allocation, neural_study_metrics).
## effect_on_return_or_risk
Numerically small (~10 bp once plus the first overnight gap). The operator's QQQ hurdle is missing from the only prospective intraday evidence, and cost-fragile strategies are not stress-tested in the table the page shows.
--- [5]
## title
As-of fundamentals shadow and frozen ML path use split-unadjusted share counts
## location
backend/market/fundamentals_shadow.py:45-46 → backend/market/fundamentals_asof.py:266-318 (no split handling); backend/market/levels_pit.py:76-126 (trailing_levels); backend/market/opportunity_learning.py:25-44
## severity
medium
## evidence
fa.levels and trailing_levels pass raw filed shares into cap = price x shares. The frozen-path defect was confirmed in docs/research/neural-comparison-readiness-2026-09-24.md: a log sales-yield error of ln(10). The nightly fundamentals_asof block compares this unadjusted value analyst against the split-adjusted production one.
## effect_on_return_or_risk
The nightly 'grades differ' evidence meant to justify the stage-two data switch is partly spurious around splits. The ML shadow's valuation inputs are wrong both before and after splits, so its forward record is not a clean test of the idea.
--- [6]
## title
LLM release-tone scores are hindsight-contaminated for historical sessions
## location
backend/market/model.py:1105-1117 (load_tone_features) → backend/agents/trading/desk/sentiment.py; grading.py:252-261 (A+ requires a bullish release)
## severity
medium
## evidence
Historical releases were scored in 2026 by a local LLM (deepseek). docs/research/historical-universe-coverage-2026-09-25.md calls it 'model-generated hindsight tone'. tone_revisions shows re-scoring under new prompts rewrites history.
## effect_on_return_or_risk
INFERRED: sentiment IC (0.0372, t 2.96) and A+ grades in backtests may embed the model's knowledge of later outcomes, which flatters every historical curve. Only records and learned_inputs captures are free of it.
--- [7]
## title
residual_momentum treats pre-listing sessions as zero own return, creating fake residuals for new listings
## location
backend/market/baselines.py:152-170 (fill at :161); live via backend/agents/trading/desk/technical.py:128
## severity
low
## evidence
own = where(isfinite(returns), returns, 0.0) with beta defaulting to 1, so residual = -market on pre-listing rows. The 120+21-session window then yields a finite, market-driven score for names listed within ~141 sessions. trailing_sum, by contrast, requires complete windows.
## effect_on_return_or_risk
Biases the technical grade of recent IPOs and relistings (CRWV, SNDK, NBIS, ALAB, OKLO, GEV, CORZ) during their first ~7 months: penalised in rising markets, favoured in falling ones. That affects both backtests and live decisions for any new listing.
--- [8]
## title
Pruning destroys the store's advertised forever point-in-time reproducibility
## location
backend/cli/market_daily.py:46,232-253; backend/market/store.py:11-15,227-244
## severity
low
## evidence
The documented cron passes --prune-days 30 (docs/NEXT_SESSION.md:8936). Bars, actions and EDGAR partitions older than 30 days are deleted, except the newest.
## effect_on_return_or_risk
A record older than 30 days cannot be rebuilt from the bars it saw. observed_sessions loses older vintages that guard against dropped sessions. Any 'replay what the desk saw' audit becomes impossible. Storage cost is ~12 MB/day.
--- [9]
## title
As-of partition keyed to the UTC date while the session is the New York date
## location
backend/cli/market_daily.py:1487; backend/market/snapshot.py:178-181
## severity
low
## evidence
In EST, the 19:30 ET run is 00:30 UTC the next day, so asof = D+1. The _repair_sessions check requires exchange session == asof and phase == post-market, so it can never pass.
## effect_on_return_or_risk
INFERRED, depending on the cron timezone: from November to March every bar-gap repair is refused and those tickers fail refresh. Partitions are labelled a day late. Also a latent source of off-by-one errors in any consumer comparing asof to the session.
--- [10]
## title
Reversal forward ledger marks price return, not total return
## location
backend/market/reversal.py:369-386
## severity
low
## evidence
The entry adjusted open is stored on the entry night's basis (factor ~1). Later marks use later-vintage adj_close. A dividend between entry and exit is then lost for the stocks and for SPY.
## effect_on_return_or_risk
Small bias between the forward shadow and its own total-return backtest. It matters only for dividend payers and 10-session holds.
--- [11]
## title
SimResult.stats silently drops NaN returns while strategy_bench rejects them
## location
backend/agents/trading/desk/simulate.py:258; funded path NaN at :1092-1103
## severity
low
## evidence
daily = returns[isfinite]. In the funded_allocation path an unpriced holding sets that day's return and the next to NaN, so the P&L across the gap is dropped.
## effect_on_return_or_risk
The scorecard and cadence tables can flatter or penalise when marks are missing. The strict bench marks the same run unavailable, so the two tables can disagree.
--- [12]
## title
Live paper record has no same-window SPY/QQQ comparator
## location
backend/cli/market_daily.py:1296-1309; frontend/src/components/DeskPanel/DeskPanel.tsx:593-626
## severity
low
## evidence
The paper equity is normalised to its own start, while SPY/QQQ are normalised to the backtest start in 2015. No load_benchmark run starts on the paper start.
## effect_on_return_or_risk
The only genuinely out-of-sample track cannot be read against the benchmarks the user cares about.
--- [13]
## title
Headline parameters were chosen on the full history including 2024-2026
## location
backend/agents/trading/desk/paper.py:~130-160 (ENTRY_BAND_Z sweep over eight start phases), REBALANCE_EVERY comment; grading.py:40-80
## severity
low
## evidence
The sweeps report whole-history start phases. No holdout window is declared in the code.
## effect_on_return_or_risk
The /3 historical curve is development evidence. Its 38%/yr is optimistic even before survivorship and the split bias.
## improvement_opportunities
--- [0]
## idea
Fix the split basis of point-in-time market cap before any new evaluation
## rationale
This is the largest code-level look-ahead found. It inflates value and expectations-gap evidence and every /3 backtest that uses them. Any new selection strategy that reads valuation would inherit it.
## where_it_plugs_in
backend/market/levels_pit.py:153-191. Apply every split with seen < split_day <= price_basis_date, where price_basis_date = history.complete_through (or panel.dates[-1]) of the same partition, instead of <= days[t]. Add the same adjustment to fundamentals_asof.levels and trailing_levels. Add a unit test that economically identical pre- and post-split vintages give identical cap at every t.
## reusable_code
levels_pit._splits(store, ticker, asof); split_adjusted_shares(shares, dates, splits, basis_dates=...); valuation.multiples; backend/tests fixtures from the neural-price-basis review
## expected_effect
No live last-row change. Historical value IC, expectations-gap uplift and /3 CAGR will likely fall, giving the true baseline a new strategy must beat. It also removes a distorted feature from the live expectations learner's training data.
## risks
It changes the live learner's fits, so run it as a named shadow first. Yahoo encodes spin-offs (WDC 2025, 1.323) as splits, so handle those explicitly.
--- [1]
## idea
Add a sourced cash yield and report excess-of-cash Sharpe
## rationale
Cash-bounded and defensive strategies are mechanically penalised against fully invested SPY/QQQ at 4-5% T-bill rates. The top-tier protocol already requires cash yield to be 'sourced and dated, or explicitly modelled as zero'.
## where_it_plugs_in
Add ^IRX (13-week bill, free on Yahoo) to macro.SERIES and bar_tickers, or hold SGOV/BIL as an explicit cash sleeve. Accrue it in simulate._Book (cash *= 1 + r_t/252 at each mark) and in allocation_controls.constant_exposure. Use rf in strategy_bench.stats and SimResult.stats. Keep the zero-yield column alongside, because the Alpaca paper account pays nothing.
## reusable_code
macro.aligned_close(store, symbol, panel, asof); simulate._Book.equity/observe_mark; strategy_bench.METRIC_KEYS
## expected_effect
About +1 pt/yr for the current book in 2023-2026 (INFERRED from ~24% average cash). Trend-brake and cash-overlay candidates are judged fairly.
## risks
It overstates achievable return if the real account does not earn sweep interest. Keep the two columns and never blend them.
--- [2]
## idea
One canonical candidate-evaluation harness: 10/25 bp, funded SPY/QQQ, equal-weight-book control, exposure-matched controls, start phases and an untouched split
## rationale
Today each study builds its own comparators with different conventions. Because the universe is hindsight-picked, the equal-weight book (~38-41% CAGR), not SPY/QQQ, is the hurdle that tells whether a balancer or selection rule adds anything.
## where_it_plugs_in
Extend backend/cli/market_strategy_bench.py:60-94 (candidates dict and benchmarks loop). Take the candidate as an allocator(report, panel, config, t) or a DipRule/brake_path_override. Run cost_bps in (10, 25) for both the strategy and load_benchmark. Add the EW-book allocator and allocation_controls.constant_exposure at the candidate's mean invested fraction. Add an 'untouched since <registration date>' block to strategy_bench.REGIMES.
## reusable_code
simulate.run(... allocator=, dip=DipRule(signal=, funded=True), brake_path_override=, funded_allocation=, **LIVE_POLICY); benchmarks.load_benchmark; allocation_controls.constant_exposure; strategy_bench.build/save; scorecard.matched_at_volatility/yearly
## expected_effect
Any new balancer or entry rule can be screened historically in hours, with honest hurdles and cost fragility visible. This cuts the chance of promoting survivorship artefacts.
## risks
It is still in-sample on a survivor universe, so treat the output as a screen, not evidence. Selecting among many candidates on it is data mining, so cap and register the candidate list.
--- [3]
## idea
Multi-shadow registry with full-policy forward replay, registration-date starts and pre-registered, power-aware gates
## rationale
The records slot holds one shadow, the forward walk is not the /3 execution, and there is no minimum sample. A daily selection change vs SPY with 15% tracking error needs (2 x 0.15 / 0.05)^2 = 36 years for t = 2 on a 5%/yr edge. Paired against the incumbent with ~5% tracking error, it still needs ~4 years (INFERRED arithmetic). The gate must be designed around that.
## where_it_plugs_in
Replace record['challenger'] with record['shadows'][name] = {book, grades, policy_sha256, registered_session}. Emit shadows from a guarded hook next to _reversal_shadows (market_daily.py:880-889). Generalise market_scorecard._book_for/_track_names. Give each shadow a dry PaperState walked with paper.plan (never submitted) so rotation, mid-cycle entries and deferred buys match /3. Start each track at its registration record, and write gates like reversal.verdict.
## reusable_code
opportunity_shadow.identity()/append()/latest() (fingerprinted append-only ledger); reversal.observe/verdict/_stats; fomc_gate counterfactual pattern; paper.plan/PaperState; report_files.write_json; benchmarks.load_benchmark with sessions = the shadow's calendar
## expected_effect
Honest prospective verdicts for balancer changes, and an end to promotions on 2-session records.
## risks
Nightly runtime grows with each shadow. Too many shadows make multiple comparisons, so keep a Bonferroni-style gate. Paper-planner code changes must not silently change shadow behaviour, so include the planner in the fingerprint.
--- [4]
## idea
Paired 15-minute entry-timing shadow on the real /3 orders (the fastest statistically decidable upgrade)
## rationale
Entry-timing variants hold the same names at slightly different prices, so the per-order difference has low variance and each order is a separate observation. With a 20 bp mean improvement and 150 bp per-order standard deviation, t = 2 needs ~(2 x 150 / 20)^2 = 225 entries (INFERRED), a few months at the current order rate. A portfolio comparison would take years. Earlier studies found the open as good as any first-hour print and waiting for pullbacks costly, so misses must be scored.
## where_it_plugs_in
For every /3 buy recorded in paper state (_pending_orders, market_daily.py:476-500), log the candidate's counterfactual fill from live IEX 15-minute bars (next completed bar after the trigger, plus a half-spread proxy and latency of at least one bar). Record a 'no fill' when the deadline passes, and mark its opportunity cost to the same horizon. Score paired bp differences at 10/25 bp in forward_evidence style with non-overlapping cohorts, and add QQQ excess.
## reusable_code
intraday_entry.evaluate (causal completed-bar engine); intraday_comparison/intraday_replay; intraday.py (RTH 26-bar sessions on the NY clock); forward_actions.total_return/apply; forward_evidence.summarize; execution_evidence decision/close shortfall; execution_quality drift/slippage split
## expected_effect
A decisive answer on whether 15-minute entry optimisation beats next-open fills. The docs imply a plausible ceiling of tens of bp per entry.
## risks
IEX-only prints (~2-3% of volume) misstate small-cap intraday prices. Paper fills are simulated. The historical 15-minute cache mixes price bases (intraday-price-basis-reconciliation doc), so do not backfill history from it. Use intraday_single_source or forward-only data.
--- [5]
## idea
Survivorship-resistant controls and point-in-time membership logging from now on
## rationale
Absolute SPY/QQQ beats are uninformative on this universe. Measuring the signal off the book is the only historical check of selection skill.
## where_it_plugs_in
Record the constituents.csv hash and book_sides in record provenance (learned_inputs already stores panel.tickers). Run every selection candidate's price-only form on the non-book S&P members as in market_survivorship. Report the candidate minus the EW book as the primary metric.
## reusable_code
backend/cli/market_survivorship.py pattern; harness.evaluate_scores (beta-adjusted IC, non-overlapping, cost-netted long-short); harness.walk_forward_folds (purged); baselines.rank_blend/percentile_rank
## expected_effect
It separates real selection edge from the ~19 pts/yr of name choice.
## risks
The off-book control is also survivor-biased and lacks filings and tone, so only price legs can be tested there.
--- [6]
## idea
Make residual_momentum require known returns
## rationale
Pre-listing zeros create fake residuals for new listings, which are exactly the high-growth names the book targets.
## where_it_plugs_in
backend/market/baselines.py:159-170. Mask windows with any non-finite own return, as trailing_sum does.
## reusable_code
baselines.trailing_sum known-count logic
## expected_effect
Cleaner technical grades for IPOs and relistings in their first ~7 months, both live and in backtests.
## risks
It changes live grades for recent listings, so run it as a shadow first under the frozen-rule culture.
--- [7]
## idea
Keep point-in-time vintages and key partitions to the NY session
## rationale
Reproducibility of 'what the desk saw' is the foundation of shadow scoring and audits.
## where_it_plugs_in
Drop --prune-days, or keep weekly and month-end vintages of bars/actions (market_daily.prune :232). Set asof from calendar.exchange_status(now)['session'] after the close instead of the UTC date (market_daily.py:1487).
## reusable_code
store.MarketStore partitions; calendar.exchange_status
## expected_effect
Records can be replayed exactly, and winter repair failures disappear.
## risks
Storage is ~4 GB/yr, which is trivial on spark1.
--- [8]
## idea
Benchmark the live paper account against funded SPY/QQQ from its own start
## rationale
It is the only out-of-sample record.
## where_it_plugs_in
In paper_curve_block (market_daily.py:1296-1309), call benchmarks.load_benchmark(store, s, paper sessions, cost_bps=10/25) and chart them rebased to the paper start.
## reusable_code
benchmarks.load_benchmark; strategy_bench.stats
## expected_effect
An honest live scoreboard against the user's stated benchmarks.
## risks
The sample is weeks long, so show the interval and not only the point estimate.
## reuse_inventory
SIMULATION:
- backend/agents/trading/desk/simulate.py:643 `run(report, since=None, config=None, rebalance=20, cost_bps=10.0, use_exits=True, redeploy=True, allocator=None, dip=None, exits=None, grace=..., entry_gate=False, block_overbought=False, band_dip_buy=False, trend_gated_exit=False, trim=1.0, exit_at_close=False, green_day_skip=False, event_exposure=None, event_lifecycle=False, live_midcycle=False, deferred_buys=False, funded_allocation=False, allocation_policy='vol_trend', index_eligible=False, benchmark_prices=None, excluded_symbols_by_session=None, trend_brake=False, brake_scale=0.5, brake_path_override=None, journal=None) -> SimResult`. This is the shares-and-cash ledger with decide-at-close, fill-at-next-open.
- simulate.LIVE_POLICY :72; SimResult.stats() :256 (annual, cagr, volatility, sharpe, drawdown, total, turnover, max_weight, years).
- adjusted_open(panel) :315; DipRule :323; _Book.plan/_fill/settle_split :1468-1637.
- The allocator hook signature is allocator(report, panel, config, t) -> (N,) weights.

BENCHMARKS AND TABLES:
- backend/market/benchmarks.py:133 `load_benchmark(store, symbol, sessions, cost_bps=10.0, start_equity=1.0, asof=None) -> BenchmarkSeries(symbol, available, daily, equity, sessions, reason)`.
- backend/market/allocation_controls.py:98 `constant_exposure(closes, opens, fraction, cost_bps=10, *, journal=None, sessions=None, symbol=None) -> NAV`, the exposure-matched funded control; build_adjusted_opens :297.
- backend/market/strategy_bench.py: stats(daily) :65, build(sessions, series, note='') :143, save/load, REGIMES :40.
- backend/agents/trading/desk/scorecard.py: render(results, store=None, loss_limit=0.25) :126, matched_at_volatility(daily, target_vol) :35, yearly(dates, daily) :19, index_returns(store, ticker, dates) :96.
- backend/cli/market_scorecard.py: from_records(root, store) -> {track: SimResult} :191, _forward_walk(records, closes, opens, book_key) :101.

SIGNAL EVALUATION AND FOLDS:
- backend/market/harness.py:159 `evaluate_scores(scores, panel, horizon, cost_bps=10.0, top_fraction=0.2, min_names=20, exclude=(), beta_adjusted=True) -> HarnessReport` (non-overlapping, residual IC, net long-short).
- harness.py:227 `walk_forward_folds(n_sessions, train_size, test_size, horizon, embargo=0)`, the purged folds.
- backend/market/windows.py:111 `build_windows(panel, window_size=20, horizon=10) -> WindowSet` with label_end_dates for purging.
- nested_ridge.fit and nested_allocation (NestedProtocol) for chronological inner/outer selection with journals.

DATA:
- backend/market/store.py MarketStore: read(ticker, asof), write, read_frame/write_frame(kind, asof, ticker, columns, metadata), latest_asof, observed_sessions, describe.
- backend/market/panel.py:204 `build_panel(store, tickers, benchmark, themes, asof=None, start=None) -> Panel` with log_returns, forward_log_returns(h), forward_residual(h, beta_lookback), rolling_beta, theme_return_matrix.
- backend/agents/trading/desk/desk.py:152 `run(store, asof=None, inputs=LIVE_INPUTS, fundamentals='corrected') -> DeskReport` (panel, sides, opinions, regime, graded, scores, book, alternate); book_panel :96.
- backend/market/baselines.py: trailing_sum, momentum, relative_strength, residual_momentum, theme_momentum, percentile_rank, rank_blend.
- backend/market/fundamentals_asof.py: load_versions(store, panel, asof), levels(panel, versions), levels_for(versions, dates), Version.available.
- backend/market/levels_pit.py: point_in_time_levels(store, panel, asof=None, strict_publication=False), split_adjusted_shares(shares, dates, splits, basis_dates=None) (fix before reuse).
- backend/market/macro.py aligned_close(store, symbol, panel, asof).
- backend/agents/trading/desk/trend_brake.py risk_off_path(qqq, 200, 0.97, 1.02).

SHADOW AND LEDGER PLUMBING:
- backend/market/opportunity_shadow.py: identity(bundle), append(folder, row), latest(folder).
- backend/market/reversal.py: observe/verdict/_stats/write_both.
- backend/market/fomc_gate.py: overlay_difference/meeting_row.
- backend/market/report_files.py: write_json(target, block, label)/read_json.
- backend/market/nightly_lock.py: acquire/release.
- backend/market/deskrecord.py: sessions/load/said/changes.
- backend/market/record_status.py: describe.
- backend/market/research_journal.py ResearchJournal + research_journal_replay.verify_snapshot (independent accounting replay).

FORWARD AND INTRADAY:
- backend/market/forward_evidence.py: outcomes(decisions, cost_bps, corporate_actions, observed_prices), summarize(samples, horizon), report(root).
- backend/market/intraday_evaluation.py:47 evaluate(decisions, cost_bps=10, corporate_actions=None).
- backend/market/forward_actions.py: total_return(symbol, p0, p1, start, end, actions), apply(shares, start, end, actions), load(root, symbols).
- backend/market/intraday.py: RTH 26-bar sessions on the NY clock.
- intraday_entry/intraday_comparison/intraday_replay/intraday_single_source/intraday_preflight: research-only causal 15-minute engines.
- backend/market/alpaca.py: BARS_KIND='bars_15m', IEX feed, adjustment=all.

PROVENANCE:
- backend/market/historical_cohort.py: load_cohort/readiness.
- backend/market/membership.py: MembershipRecord/members_as_of. These are for when a sourced membership file exists.
- backend/market/learned_inputs.py: capture, the nightly frozen inputs including the universe.
## open_questions
1. Is the spark1 crontab still `--prune-days 30`, and does it include `--challenger`? What timezone does the cron run in? The crontab is not in the repo; this decides the winter asof/repair defect.
2. How large is the split-basis flattering? A rerun on the Spark (no local numpy/data) is needed of value IC, the expectations-gap vs plain uplift and the /3 CAGR, with the corrected split basis.
3. Why does market_scorecard's rule drawdown (-23.4%, 2018-06 onward, as of 2026-09-08) differ from the /3 journals' -37.33% (2020-01 to 2026-09-18)? Policy version, as-of data, or window?
4. Does the target real account earn interest on cash? The Alpaca paper account does not (INFERRED). This decides whether a cash-yield column is decision-relevant or informational only.
5. What is the training cutoff of the LLM that scored historical release tone? Does sentiment IC differ before and after it? That tests hindsight leakage.
6. How large are the IEX-feed 15-minute gaps for small, volatile book names (CRWV, IREN, OKLO, NBIS)? Are they large enough to invalidate intraday fill modelling without SIP (SIP returned 403 on 2026-09-14)?
7. Should forward shadows be judged against the equal-weight book as well as SPY/QQQ? What gate (sample size, t, drawdown tolerance) does the operator accept, given that portfolio-level significance needs years?
8. The user's maximum acceptable drawdown is still unstated (microstructure doc). The scorecard hard-codes 25%, and the live /3 journals show -37%.