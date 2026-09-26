## area
learned-models: the ML, deep-learning and RL research stack, and what it found (repo root /Users/animallya/Desktop/PersonalAssistant)
## how_it_works
There are five separate learned-model families. Each has its own labels, folds and accounting. They are not interchangeable, and results from one are not comparable with another.

A. Cross-sectional ranker sweep (backend/market/model.py, CLIs backend/cli/market_train.py and market_sweep.py)
- Panel: 532-546 names (current S&P 500 plus the AI overlay plus sector ETFs), 2015 onward.
- Label (model.py:203-210): `panel.forward_residual(h)`. This is the log of adj_close[t+h]/adj_close[t] minus 120-session rolling beta (clipped to [0,3], set to 1 when unknown) times SPY (panel.py:107-135). It starts at the decision close, not the next open. Option `label="rank"` converts it to a cross-sectional percentile minus 0.5.
- Inputs: a 20-session window of raw channels (windows.channel_matrices), optionally widened with alpha_features (31), technical (33), edgar (15), tone, intraday (10), calendar or macro layers. Four baseline percentile ranks are appended (momentum_12_1, relative_strength_20, theme_momentum_20, theme_relative_strength_20). The market vector holds the benchmark's channels plus the cross-sectional mean and std of every channel, plus calendar and macro (model.py:144-213).
- Encoders (model.py:400-548): mlp, gru, xsect (GRU then transformer across names), master (market-gated), tape (1-D CNN over 5x26 15-minute bars), lgbm (model.py:814-874) and chart_cnn (the Jiang-Kelly-Xiu 64x60 image, cross-entropy on "above the session median", chart_cnn.py).
- Loss: negative per-session Pearson correlation (model.py:566-573), with sessions batched and padded.
- Normaliser: fitted on the fit range only, z-scores clipped at 5 (model.py:273-311).
- Folds: `harness.walk_forward_folds(n, train=750, test=125, horizon, embargo=5)` (harness.py:227-245). The purge gap is horizon+embargo. `inner_split` (model.py:641-657) holds out the last 10% of the training range for early stopping on validation IC, with a further horizon purge.
- Scoring: `harness.evaluate_scores` (harness.py:159-218). Every `horizon` sessions it takes the rank IC against the beta-adjusted residual and runs an equal-weight long-short book of the top and bottom 20% (min 20 names). Cost is 10 bp per unit of weight traded.
- Wiring: research only. No output reaches the desk (desk.py imports only the data loaders `load_tone_features` and `load_edgar_features` from model.py).

B. Registered learned policy (backend/market/learned_policy.py; historical study learned_research.py; prospective bridge learned_inputs.py and learned_archive.py)
- Label (learned_policy.py:119-133): log of adjusted open[t+11] / adjusted open[t+1], minus SPY over the same endpoints. That is 10 open-to-open sessions starting at the next executable open. Labels are NaN for non-members and for SPY.
- Features are cross-sectional percentile ranks among members (learned_policy.py:137-165). Market features are passed raw via the `rank_features` mask.
- `walk_forward_ranker` (:203-280) refits monthly: sklearn HistGradientBoostingRegressor with squared error on the raw relative label. Training rows are t < start-11 (`eligible_training_sessions`, :169-173), and labels must be published before the fit. It needs 750 sessions with training rows before the first fit. Each fit gets a SHA-256 hash.
- Brake (:283-449): the label is 1 if QQQ falls more than 8% below its running peak from close t within 20 sessions. L2 logistic regression with median imputation plus missing-value indicators, refit every 63 sessions after 1,000 sessions. `brake_scale_path` halves exposure when p ≥ 0.45 and restores it when p < 0.30.
- `policy_targets` and `allocator_for` (:454-546) push scores through `risk.desk_targets`. POLICY_BLEND is a 50/50 midrank blend with the rule score. Retrospective forecasts are blocked from the desk adapter.
- The study (learned_research.py) uses 8 cross-sectionally ranked stock features (return5/20/60/120, vol20, distance to MA20 and MA60, adjusted 20-day span) plus 8 raw market features. It rebuilds the top-10 composition every 20 sessions, capped at 10% per name (`gp.basket`). Execution is next-open, funded through `simulate._Book`; same-open sale proceeds cannot fund buys, and one next-session retry is allowed (:192-299). Holdout: labels ending on or after 2026-08-03 are withheld (:11, :107-116).

C. Nested ridge allocation gate (nested_ridge.py, nested_allocation.py, nested_market_inputs.py, nested_market_study.py, forecast_diagnostics.py)
- 22 features: SPY and QQQ returns over 1/5/20/63/126 sessions, 20-day std, log(close/SMA200) and log(close/max63), plus current-basket wealth proxies.
- Three separate ridge targets: basket, SPY and QQQ gross log returns from open t+1 to open t+6.
- `choose_mode` (nested_allocation.py:227-251) takes the daily argmax over cash (fixed at 0), stock basket, SPY and QQQ, switching only if the best beats the current mode by a margin.
- Nested selection: first outer row 1260, outer blocks of 126, 3 inner blocks of 126, alphas {1, 100}, margins {0, 0.005}. The worst-cost terminal log wealth at 10 and 25 bp picks the parameters.
- Results are reconciled through ResearchJournal and verify_snapshot.

D. Price-sensitive neural, ridge and tree family, next-close fills (growth_pilot.py, opportunity_learning.py, opportunity_shadow.py, neural_price_basis.py, neural_policy_comparison.py)
- Features: 8 price/volume features plus 10 filed-ratio features with missing-value indicators. Training medians and scales, clip at 5 (opportunity_learning.py:59-75).
- Labels: 100*log(p[t+21]/p[t+1]), a raw 20-session return from the next close. It is not relative to SPY and not ranked (opportunity_learning.py:78-83).
- Model: one fit on 2018-2023 using every fifth session, epoch or model chosen on 2024 wealth, then applied unchanged to 2025-01..2026-09 with no refit.
- Selection: top ten with a positive forecast, 10% cap. Fills at the next close (growth_pilot.py:142-157).
- The frozen 36→32→16→1 tanh bundle runs nightly in NumPy as a 10/30 bp shadow ledger (opportunity_shadow.py).
- The RL arm (market_growth_pilot) is a categorical policy gradient over 7 fixed baskets, with log-NAV reward (growth_objective.py).

E. Other learners, recorded in CLI docstrings
- market_xsect_net: whole-session network with a ranking loss, horizon 20.
- market_weights: ridge on analyst weights, shrunk toward equal.
- market_interactions: learned combiners.
- market_release_eval: embedding ridge and trees.
- market_volatility: 11 volatility models, QLIKE.
- market_allocation_rl (REINFORCE, cross-entropy method), market_offline_rl (critic and AWR contextual bandit), market_intraday_rl (direct-Sharpe GRU, PPO on 15-minute bars), market_execution_rl (direct policy and PPO scheduling a fill over 27 slots).

LIVE learned component: only the expectations-gap LightGBM (backend/cli/market_expectations.py:171-181, 348-358, 878-901). It predicts revenue growth, refitted yearly on labels published before the year (minimum 500 rows and 3 years). The gap (expected growth minus implied growth) is rank-blended into the value analyst (challenger.with_gap, challenger.py:88-107). desk.LIVE_INPUTS = (EXPECTATIONS_GAP,) (desk.py:141, :206-222), so it moves live /3 grades and paper orders.

Why each model lost (from the code and documents):
1. Horizon mismatch. The repo's own positive controls find structure at 1-5 sessions (reversal, eaten by cost) and 60 sessions (theme momentum). At 10 sessions the two cancel (NEXT_SESSION.md:9595-9602). Yet the ranker used 10 while holding for 20 sessions (learned_policy.py:18 vs learned_research.py:218-220).
2. The objective does not match the payoff. Models are chosen on beta-neutral, long-short, whole-cross-section IC, while money is made long-only in a concentrated top 10 that keeps its beta. Momentum reads as "nothing" by IC (CHANGELOG.md:3486) yet top-10 momentum120 made 70.5% CAGR against 39.5% for equal weight.
3. Too few independent observations. There are about 65 independent 20-session periods (market_allocation_rl docstring), 14 folds (nested study), and a 35-interval holdout. Least-squares analyst weights lose to fixed equal weights (0.0382 vs 0.0526 IC).
4. Noisy features and labels. Raw-return mean-squared-error labels are dominated by fat tails and market-level variance.
5. Stale single fits. Family D models never saw 2024-2026.
6. Timing and cash formulations fight positive drift and mean reversion. Forward book returns are higher after every risk-off condition (opportunity-and-cash-2026-09-18.md:48-58).
7. Survivorship. The book equal-weight return is 34.2% a year against 15.6% off-book, about 19 points a year from name choice alone (CHANGELOG.md:3480-3484). Selection rules that concentrate in recent winners are the most exposed to this.
## parameters_and_constants
Registered policy (learned_policy.py), shadow and research only:
- RANKER_HORIZON=10; RANKER_LABEL_END=11; BRAKE_HORIZON=20; RANKER_MIN_SESSIONS=750; BRAKE_MIN_SESSIONS=1000; BRAKE_REFIT_SESSIONS=63 (:18-23).
- HGB: max_iter=200, lr=0.03, max_leaf_nodes=31, min_samples_leaf=200, l2=0, no early stopping, seed 0 (:246-254). Refit monthly (:222-231).
- Crash label: QQQ drawdown below -0.08 within 20 sessions (:296).
- Logistic C=1.0, max_iter=300 (:402).
- Hysteresis: enter at p ≥ 0.45, exit at p < 0.30, exposure 0.5 (:444-447).

learned_research.py, research only:
- HOLDOUT 2026-08-03 (:11).
- Composition every 20 sessions (:218-220). gp.basket top 10 at 10% cap (growth_pilot.py:82-88). Equal weight min(1/N, 0.1) (:161-163).
- Fixed brake is trend_brake.risk_off_path at 0.5 (:184-187).
- Costs 10/25 bp; annualisation 252 (:318-326).

model.py, research only:
- TrainConfig: window 20, horizon 10, momentum 252 skip 21, lookback 20, train 750, test 125, embargo 5, validation fraction 0.1, hidden 128, dropout 0.1, heads 4, lr 1e-3, weight decay 1e-4, epochs 8, batch 8 sessions, patience 3, cnn_max_train_cells 60,000, tape_sessions 5 (:75-105).
- CLIP=5 (:71); MIN_TRAIN_CELLS=500 (:242).
- LightGBM: lr 0.03, num_leaves 63, min_data_in_leaf 200, bagging 0.8, feature_fraction 0.8, lambda_l2 1, 600 rounds, early stopping after 50 (:830-853).

harness.py:
- evaluate_scores defaults: cost_bps 10, top_fraction 0.2, min_names 20, beta_adjusted True (:159-168). Used for model selection and for desk calibration printouts (desk.py:370).

chart_cnn.py: 64x60 image, WINDOW=20, 51 price rows and 12 volume rows (:37-41). Research only.

market_xsect_net.py: HORIZON 20; TRAIN, TEST, EMBARGO = 750, 125, 5; hidden 128; MIN_NAMES 15; 3 seeds; 60 epochs. Research only.

Nested gate, research only:
- nested_allocation.py: first_outer 1260, outer 126, inner 126x3, min_train_rows 504, alphas (1, 100), switch_margins (0, 0.005), STOCK_CADENCE 20, COSTS (10, 25) (:28-45).
- nested_market_inputs.py: WARMUP_ROWS 200, LABEL_EXIT_OFFSET 6 (:23-24).

neural_study_metrics.py: ROLLING_WINDOWS (63, 252); TREND 200; VOL 20; VOL_MEDIAN 252; the scorecard accepts only 10 and 25 bp (:18-31, :113-114).

growth_pilot.py (research; also feeds the shadow):
- 8 features (:24-33); decision stride 5; cost 0.001 (:189).
- split_rows horizon 5 (:161).
- Unscheduled FOMC meetings of 2020-03-03 and 2020-03-15 excluded (:67-71).
- Fills at the next close (:142-157).

opportunity_learning.py: 20-session raw next-close label (:78-83). Ridge alpha 10; HGB with 100 iterations, 15 leaves, minimum leaf 100 (market_opportunity_learning.py:171-176). Network 36→32→16→1 tanh, AdamW 1e-3, weight decay 1e-3; epoch picked from {5, 10, 15} on 2024 wealth.

market_neural_price_study.py: training rows 2018-2023, every fifth session, horizon 21 (:116-122); AdamW (:134); one fit dated 2025-01-01 (:196). Research only.

opportunity_shadow.py (live shadow, never trades): POLICIES neural, valuation_rule, momentum20, SPY, USD at 10 and 30 bp; starting cash 100,000; 20-session cadence; fills at the next close (:27, :105-116, :151-172).

Live expectations-gap LightGBM (market_expectations.py): PARAMS objective regression, lr 0.03, num_leaves 15, min_data_in_leaf 40, bagging 0.8/1, feature_fraction 0.8, lambda_l2 5 (:171-181); 300 rounds; NaN filled with 0 (:354-357); min_train_rows 500 and min_train_years 3 (:505-516).

Live sizing that learned scores would pass through: risk.BOOK_CONFIG top_fraction 0.1, target_vol 0.30, name_cap 0.15 (risk.py:48-50). The frozen /3 expectation also has theme cap 0.4, speed 0.5, min trade 0.005 and REBALANCE_EVERY 20 (nested_market_study.py:79-92).

Dead code in the live path: simulate._engine_weights and _steepen (CHANGELOG.md:3606-3610). learned_archive.fit_shadow is never called outside tests. rl_readiness has no importer.
## measured_results
All figures below are retrospective, on today's survivor book, and over already examined periods.

Learned price study (docs/research/learned-price-results-2026-09-24.md:19-30, 45-54). Common prefix 2019-03-26..2026-09-21, 10 bp:

| Policy | CAGR | Max DD | Sharpe | Turnover/yr | Holdout |
|---|---:|---:|---:|---:|---:|
| momentum120 | 70.5% | -46.6% | 1.35 | 9.33 | 28.8% |
| learned_rank (HGB) | 48.7% | -57.9% | 1.10 | 19.48 | 6.0% |
| momentum120 + learned brake | 68.9% | -44.6% | | | 17.3% |
| learned_rank + learned brake | 47.7% | -53.1% | | | -1.6% |
| momentum120 + fixed brake | 63.1% | -44.7% | | | |
| Equal weight | 39.5% | -38.6% | 1.27 | 0.50 | |
| SPY | 16.2% | | | | |
| QQQ | 21.7% | | | | |

At 25 bp, learned_rank falls to 44.4% and momentum120 to 68.2%. The holdout is Aug 3..Sep 21 (35 intervals).

Nested ridge gate (nested-market-validation-2026-09-24.md:227-240, 251-271). 2020-01-06..2026-09-18, 10 bp:

| Account | CAGR | Max DD | Turnover |
|---|---:|---:|---:|
| Ridge gate | 23.32% | -35.47% | 14.71x |
| Same basket, no gate | 36.29% | -32.57% | 8.21x |
| /3 | 59.23% | -37.33% | 13.65x |
| SPY | 15.27% | | |
| QQQ | 20.47% | | |
| Equal weight | 43.70% | -36.98% | |

- The gate ends with 48.75% (10 bp) and 52.39% (25 bp) less wealth than the same basket without it.
- It beats /3 in 1 of 14 folds and the no-gate basket in 4 of 14.
- Out-of-sample squared-error skill against training means: -6.46% stock, -14.89% SPY, -15.35% QQQ, on 1,679 labels (chronological-forecast-diagnostics-2026-09-25.md:94-97).

Neural ranking substituted into /3 (neural-price-results-2026-09-24.md:16-27, 33-35). 2025-01-02..2026-09-18, 10 bp:
- /3: 157.9% CAGR, -31.7% max DD, turnover 16.36x.
- Neural: 106.3% CAGR, -37.1% max DD, turnover 20.80x.
- Equal weight 65.3%; SPY 17.6%; QQQ 22.6%.
- Neural beats /3 in 8.7% of 63-session windows and 0% of 252-session windows. It trails /3 in every regime.

Opportunity learning on as-of fundamentals (opportunity-learning-asof-2026-09-14.md:62-74). 2025-01-02..2026-09-11, 10 bp, total return:
- Neural +65.0% (DD -52.5%); ridge +74.3%; trees +172.4%; valuation rule +150.0%.
- Momentum20 +419.0%; momentum120 +348.1%; equal weight +122.4%; SPY +31.2%.

Growth pilot (growth-pilot-2026-09-14.md:59-71). Same test window, next-close fills:
- Momentum120 396.68%; momentum20 357.27%; equal weight 129.61%.
- Neural seeds 114.75%, 163.09% and 183.59%, with DD between -48% and -53%.
- RL seeds 9.00%, 99.47% and 201.58%.

Ranker sweep, 532 names (NEXT_SESSION.md:9555-9577, 9245-9250, 9283-9287, 9087-9090):
- h10 rank IC: momentum 12-1 0.015; mlp raw 0.015; lgbm alpha rank 0.002; master -0.005. Net Sharpe was negative for nearly every model.
- h60: mlp -0.072 (t -1.98), meaning the model is inverted out of sample.
- Beta-adjusted label: lgbm alpha h20 0.008; tape encoder 0.004 and -0.004; chart CNN -0.001, and -0.012 at h5.
- LightGBM on every desk feature: IC 0.006 (t 0.4), against 0.035 (t 2.1) for the grade.
- Positive controls: 5-day reversal IC 0.024 (t 3.16) but Sharpe -0.04 at 10 bp; theme momentum h60 IC 0.054 (NEXT_SESSION.md:9589-9600).

Cross-sectional ladder (market_xsect_net.py:35-43): desk grade 0.0530; network learning the real forward rank 0.0052 (t 0.42); blending that with the grade drops to 0.0395.

Analyst-weight ridge (CHANGELOG.md:3615-3630):
- h20: equal weights 0.0526; shrink 1 0.0536; least squares 0.0382.
- h60: shrink 1 0.0631 against 0.0526 for equal.

Release-text embeddings (CHANGELOG.md:3551-3557): trees 0.0309 against 0.0549 for the desk. Adding the text at 0.5 gives IC 0.0590 but net Sharpe falls from 1.02 to 0.83.

Learned combiners (CHANGELOG.md:3063-3066): best IC +0.040 against +0.055 for the rule.

Volatility forecasting (market_volatility docstring): QLIKE -15.5% against trailing-60, but the book is unchanged (Sharpe 1.85 to 1.82, 31.8% to 31.3% a year).

RL:
- market_allocation_rl: rule +0.611, REINFORCE +0.579, cross-entropy +0.585. The REINFORCE gradient is void (legacy-allocation-gradient-2026-09-25.md).
- Offline AWR: proxy +0.651 (Newey-West t 2.62, non-overlapping t 1.10). Through the full rules it makes 21.7-22.4% a year against the rule's 26.8%, Sharpe 1.52-1.54 against 1.64.
- Intraday RL on the 2026 holdout: every strategy negative at 3 bp.

Execution RL: buys are best at the open. Sells at the close are 24 bp better (t 2.8, 840 sessions) but 2026 reverses that. Waiting 1, 3, 5 or 10 sessions to enter costs -0.29%, -0.57%, -0.72% and -1.43%.

15-minute chart CNN: IC +0.002. The hourly reversal is significant (t 8) but worth 3.8 bp against a 6 bp round trip (CHANGELOG.md:3329-3337).

Live expectations gap (CHANGELOG.md:2797-2800, 3068-3075): +30.3% a year against +25.2% for the plain rule, Sharpe 1.56 against 1.46, from 2018-06, better in 7 of 9 years. The earlier accuracy claim (correlation +0.628 against +0.531 for naive) is qualified: it is not established against a correctly scaled baseline (CHANGELOG.md:3096-3101).

Survivorship: book equal weight +34.2% a year against +15.6% for the off-book control (CHANGELOG.md:3480-3486).

Frozen neural shadow, prospective: +15.84% against momentum20 -0.20% and SPY +2.46%. That covers only 4 daily intervals after one fill and is not meaningful.
## wiring_status
LIVE (moves /3 grades and paper orders):
- Expectations-gap LightGBM. Path: desk.LIVE_INPUTS (desk.py:141) → desk.run (desk.py:206-222) → challenger.expectations_gap (challenger.py:61-85) → market_expectations._carried and _fit_predict. It is blended into the value analyst by challenger.with_gap.
- harness.evaluate_scores is also used for desk calibration statistics (desk.py:370). That is reporting, not trading.

NIGHTLY SHADOW (writes records, never trades):
- opportunity_shadow frozen neural ledger, via observe_ml_forward (market_daily.py:819-857, called at :1500-1506).
- learned_inputs.capture (market_daily.py:1583-1589), which snapshots desk inputs for future learning.
- The challenger block, which is the plain rule as shadow (market_daily.py:864-876).
- neural_study.summary is served read-only by backend/api/v1/market.py:135-157.

RESEARCH-ONLY CLIs:
- learned_research (market_learned_research.py)
- nested_ridge, nested_allocation, nested_market_* and forecast_diagnostics (market_nested_study.py)
- neural_price_basis and neural_policy_comparison (market_neural_price_study.py)
- model.py, chart_cnn and tape (market_train.py, market_sweep.py)
- growth_pilot and growth_objective (market_growth_pilot.py)
- opportunity_learning (market_opportunity_learning.py)
- strategy_bench (market_strategy_bench.py)
- expectations_reporting (market_expectations.py)
- neural_study_metrics (market_chronological_diagnostic.py and the neural and nested studies)
- The xsect_net, weights, interactions, volatility and RL CLIs.

UNWIRED OR TESTS ONLY:
- learned_archive (no importer outside tests; fit_shadow is never scheduled).
- learned_policy.policy_targets and allocator_for (used only by the archive and learned_research).
- rl_readiness (no importer).

OPERATIONAL (VERIFIED locally by recomputing opportunity_shadow.identity):
- The current code identity is 95a54c5804a2d85610a8f2c069bfd87e6fc5d5a543002d1e57c5dc9c2842a551.
- The last declared migration target is dc1d5fa6... (data/opportunity_shadow_migrations.json).
- Commit df4dc669 (2026-09-25) changed calendar.py, edgar.py and levels_pit.py, all of which are hashed into the identity.
- On the next nightly, initialize() will raise "Frozen experiment changed". observe_if_current catches the error and the ML-forward shadow is skipped.
- The Spark host's checkout and ledger state are UNVERIFIED.
## defects
--- [0]
## title
Model selection metric does not match the return objective (beta-neutral long-short IC vs long-only top-K total return)
## location
backend/market/harness.py:159-218; backend/market/model.py:203-210; backend/market/panel.py:119-125
## severity
high
## evidence
Every sweep model was kept or killed on rank IC and long-short net Sharpe against the beta-adjusted residual, top/bottom 20% of about 532 names. By that metric momentum is 'nothing' on and off the book (CHANGELOG.md:3486; momentum 12-1 h10 IC 0.015). Yet the long-only top-10 momentum120 on the book made 70.5% CAGR against 39.5% for equal weight (learned-price-results:23-28). Beta adjustment removes exactly the market and beta exposure that beats SPY and QQQ in total return.
## effect_on_return_or_risk
Models that could raise top-10 long-only wealth may be rejected, and IC gains that do not reach the top decile are over-credited. Research effort went to the wrong target. INFERRED: part of the 'no model beats the rule' verdict is a measurement artefact.
--- [1]
## title
Ranker label horizon (10 sessions) does not match the 20-session holding cadence and sits where reversal and momentum cancel
## location
backend/market/learned_policy.py:18-19; backend/market/learned_research.py:218-220; model.py TrainConfig horizon=10 (:79)
## severity
high
## evidence
RANKER_HORIZON=10, but compositions reset every 20 sessions (and paper.REBALANCE_EVERY=20). The repo's positive controls put reversal at 1-5 sessions and theme momentum at 60 sessions, and state 'At ten sessions the two cancel, and that is where every model was trained' (NEXT_SESSION.md:9600-9602). trading-ml-path-2026-09-22.md:96-98 then froze 10 sessions to keep the existing ranker's horizon.
## effect_on_return_or_risk
learned_rank made 48.7% against 70.5% for momentum120, with turnover 19.48 against 9.33 and a deeper drawdown (-57.9% vs -46.6%). INFERRED: the model learns short-term reversal that is gone within the 20-session hold.
--- [2]
## title
Squared-error regression on raw, fat-tailed relative returns; no per-date demeaning or rank label
## location
backend/market/learned_policy.py:246-255 (target from :130); opportunity_learning.py:78-83 (raw 100*log return); market_neural_price_study.py raw 21-session label
## severity
medium
## evidence
HGB fits the SPY-relative log return with squared error, and the target is not cross-sectionally centred. Family D fits the raw (not relative) 20-session return and then buys only forecasts above 0. model.py offers label='rank' (CSRankNorm), but the registered policy does not use it.
## effect_on_return_or_risk
Model capacity goes to the date-level book-vs-SPY mean and to tail names such as CRWV and IREN rather than to ordering. INFERRED to contribute to the worse drawdowns (-52% to -58%).
--- [3]
## title
Top-10 selection has no rank buffer or hysteresis
## location
backend/market/growth_pilot.py:82-88 (basket), used by learned_research.py:173 and opportunity_shadow.py:217-219
## severity
medium
## evidence
Hard top-10 cutoff with a 10% cap. Measured turnover: learned_rank 19.48 a year against 9.33 for momentum120. Neural inside /3 had 20.80x against 16.36x for /3.
## effect_on_return_or_risk
Going from 10 bp to 25 bp costs learned_rank 4.3 CAGR points against 2.3 for momentum120. Churn also realises noise.
--- [4]
## title
Single stale fits applied for 20 months, and next-close fills, in family D
## location
backend/cli/market_neural_price_study.py:116-122,196; market_opportunity_learning (train 2018-2023, select 2024); growth_pilot.py:142-157; opportunity_shadow.py:151-157
## severity
medium
## evidence
Training ends 2023-12, and 2025-01..2026-09 is scored with no refit. Execution is at the next close, whereas the desk convention is the next open (ml-forward-evaluation-spec.md:30-33).
## effect_on_return_or_risk
The models never saw the 2024-26 regime, which momentum tracks automatically. The results are not comparable with the next-open ledgers. Neural made +65% against +419% for momentum20.
--- [5]
## title
Market-timing and cash formulations structurally lose return
## location
backend/market/learned_policy.py:283-449 (brake); backend/market/nested_allocation.py:227-251 (argmax gate)
## severity
medium
## evidence
Gate out-of-sample squared-error skill: -6.46% stock, -14.89% SPY, -15.35% QQQ. Gate wealth is 48.75% below the no-gate basket, with turnover 14.71x against 8.21x. The learned brake cuts momentum120 CAGR from 70.5% to 68.9% and the learned_rank holdout from 6.0% to -1.6%. Every risk-off condition precedes higher forward book returns (opportunity-and-cash-2026-09-18.md:48-58).
## effect_on_return_or_risk
Each exit to cash forgoes rebounds, and all-or-nothing switching compounds the costs.
--- [6]
## title
Sweep labels start at the decision close, not the executable next open
## location
backend/market/panel.py:127-135; used by harness.py:178-183 and model.py:203
## severity
medium
## evidence
forward_log_returns is adj_close[t+h]/adj_close[t]. learned_policy corrected this to open t+1 through open t+11, but the sweep, the controls and desk calibration still use close-to-close.
## effect_on_return_or_risk
INFERRED: short-horizon ICs are inflated by the non-executable overnight gap (for example the 1-day reversal at t 4.65). These controls informed the choice of horizon.
--- [7]
## title
Frozen neural shadow will halt at its code-identity guard after df4dc669
## location
backend/market/opportunity_shadow.py:41-47, 85-104; backend/market/data/opportunity_shadow_migrations.json
## severity
medium
## evidence
Recomputed identity 95a54c58... has no declared migration from dc1d5fa6... (last declared 2026-09-24). df4dc669 on 2026-09-25 modified calendar.py, edgar.py and levels_pit.py. levels_pit.trailing_levels is an actual shadow input, so this may be a real input change, not only a hash change.
## effect_on_return_or_risk
The only prospective ML ledger stops collecting untouched evidence, as already happened once on Sep 23. Hashing whole shared modules makes the experiment fragile.
--- [8]
## title
Prospective learned archive cannot produce a forecast for roughly 3-4 years
## location
backend/market/learned_policy.py:21-22 used by learned_archive.fit_shadow (learned_archive.py:448-471)
## severity
medium
## evidence
Captures start 2026-09-23 (TRADING_LEARNED_REVIEW:71-81). The ranker needs 750 captured sessions and the brake 1,000. fit_shadow is not called by any non-test code.
## effect_on_return_or_risk
The causal ML path gives no decision support in any practical horizon. INFERRED earliest rank forecast is around 2029-09.
--- [9]
## title
Live expectations-gap learner fills NaN with 0 before LightGBM, and has open causal-contract findings
## location
backend/cli/market_expectations.py:354-357; NEXT_SESSION.md:2574-2582
## severity
low
## evidence
np.nan_to_num(x, nan=0.0) disables LightGBM's native missing-value splits, so 0 becomes ambiguous for growth and margin features. The audit listed release-session and membership gaps; df4dc669 bounds some of them. The recorded +5.1 points a year has not been re-measured after these fixes.
## effect_on_return_or_risk
The only live ML input may be mis-specified or over-credited. The size of the effect is UNVERIFIED.
--- [10]
## title
Legacy REINFORCE allocation loss has an identically zero gradient
## location
backend/cli/market_allocation_rl.py (_policy_gradient); legacy-allocation-gradient-2026-09-25.md
## severity
low
## evidence
L = -A*sum(w.detach()*log p) has derivative 0 in the logits.
## effect_on_return_or_risk
The 'RL lost to the rule' evidence for policy gradient is void. The cross-entropy and offline results still stand.
--- [11]
## title
Minor research hygiene issues
## location
model.py:843-853 (LightGBM early-stops on L2 while selection uses IC); model.py:1198 (macro NaN filled with 0); learned_policy.py:291-296 (crash window starts at close t while exposure changes at open t+1); _hac_t duplicated in market_allocation_rl.py:285, market_earnings.py:179, market_snapback.py:117, market_bounce.py:203
## severity
low
## evidence
Direct code reading.
## effect_on_return_or_risk
Small bias in model selection and imputation, and a maintenance risk that the duplicated statistics drift apart.
## improvement_opportunities
--- [0]
## idea
Use ML to forecast fundamentals, not returns, and feed the forecasts to the rule as analyst legs (extend the expectations-gap family)
## rationale
This is the only learned component that improved the book: +30.3% a year against +25.2%, Sharpe 1.56 against 1.46, better in 7 of 9 years. Revenue growth is far more predictable than returns (correlation around 0.6, though that claim is now qualified). Tone and fundamentals are also the strongest cross-sectional signals: tone blend IC 0.044 (t 3.0) at h20 and 0.076 at h60; fundamental blend IC 0.029 (t 3.07).
## where_it_plugs_in
backend/cli/market_expectations.py (_dataset, _fit_predict, _carried), then challenger.with_gap into the value analyst. New targets: next-quarter revenue acceleration, gross-margin change, probability of a guidance raise from release text. Each becomes a predicted-minus-implied gap leg.
## reusable_code
market_expectations._training_mask (publication-gated yearly fits), _carried, challenger.expectations_gap and with_gap, edgar.edgar_features(strict_publication=True), language.tone_features, desk scorecard --records, and the market_weights shrink-to-equal combiner.
## expected_effect
INFERRED: +1 to +3 CAGR points if one more leg repeats the gap's effect. Needs matched scorecard runs at 10 and 25 bp.
## risks
Survivor book; current membership and sectors; the gap's own causal fixes are not re-measured; stacking legs can dilute the tone and value signals.
--- [1]
## idea
A top-K-aligned cross-sectional ranker: LambdaRank or top-decile classification on the broad universe, next-open labels over 20 or 60 sessions, not beta-neutralised, used as a rank blend with the rule
## rationale
The current models were trained at the wrong horizon (10) with a squared or IC objective over the whole cross-section. The payoff is long-only top 10 with beta. Structure exists at 60 sessions (theme momentum IC 0.054; analyst-weight shrink 0.0631), and the 532-name universe gives more breadth than 94 correlated names.
## where_it_plugs_in
A new label and objective option in learned_policy.walk_forward_ranker (for example RANKER_HORIZON 20 with RANKER_LABEL_END 21, and a label mode for per-date rank or decile relevance). LightGBM objective='lambdarank' with group=date, or HGB on rank labels. Scores go through POLICY_BLEND (a 50/50 _vector_ranks blend with desk scores) into risk.desk_targets.
## reusable_code
learned_policy.relative_open_labels, cross_sectional_ranks, eligible_training_sessions, walk_forward_ranker, policy_targets/allocator_for; learned_research.replay, metrics and rolling_wins; model.load_extra_features (edgar, tone, technical); baselines.percentile_rank.
## expected_effect
INFERRED: modest, as a tie-break inside /3 rather than a replacement. The evidence ceiling is the desk IC of about 0.053. Success means beating momentum120, /3 and equal weight on funded top-10 wealth at 10 and 25 bp.
## risks
Survivorship: momentum-like learners concentrate in the names that caused their own selection into the book. Pre-register one horizon and do not search 20 vs 60 after viewing results.
--- [2]
## idea
Rank-buffered composition (hysteresis) for any score-driven basket
## rationale
Turnover of 19.5x for learned_rank against 9.3x for momentum, and the 25 bp stress costs learned_rank 4.3 CAGR points.
## where_it_plugs_in
growth_pilot.basket, used by learned_research.composition and opportunity_shadow: keep holdings until they drop below rank 20, and enter only in the top 10.
## reusable_code
growth_pilot.basket(scores, eligible, gross); learned_research.replay for the funded next-open ledger.
## expected_effect
INFERRED: roughly half the turnover, recovering about 1-2 CAGR points at 25 bp for fast signals; close to neutral for momentum120.
## risks
Slower reaction to real rank changes. The buffer width must be fixed before any results are seen.
--- [3]
## idea
Rebuild the evaluation to match the objective
## rationale
Current selection uses close-to-close, beta-neutral, long-short IC. Needed instead: next-open labels, a long-only top-K funded ledger, IC restricted to the book, dependence-aware t statistics, and an off-book survivorship control.
## where_it_plugs_in
harness.evaluate_scores: add label='next_open', beta_adjusted False (or SPY/QQQ-relative), and a long-only top-K mode. Add a mandatory market_survivorship off-book panel run for every ranker.
## reusable_code
harness.walk_forward_folds; learned_policy.relative_open_labels; simulate.adjusted_open; neural_study_metrics.scorecard, regime_scorecard and chronological_fold_scorecard; one shared _hac_t; entry_pilot.paired_interval (block bootstrap).
## expected_effect
No direct return. It stops false negatives and false positives, and it would re-rank past sweep rows (the lgbm +technical h60 0.033 row is a candidate to retest).
## risks
Re-scoring examined history is still not untouched evidence. Label any re-run as development.
--- [4]
## idea
Meta-labelling as a size tilt on /3 entries, never as a veto into cash
## rationale
The primary signal (grade A plus breakout) already carries the edge. A secondary classifier estimating whether an entry beats the equal-weight book over 20 sessions can re-weight within the caps. Measured cautions: vetoes and delays cost (veto off +39.5% vs +35.4%; waiting 1-10 sessions costs 0.29-1.43%).
## where_it_plugs_in
Between the desk grades and risk.desk_targets: weight scaled by 0.5+p within name_cap 0.15 and theme_cap 0.4, keeping gross unchanged. Features: entry context (extension from the 21 EMA, run-up, gap, first-hour 15-minute features from alpaca.intraday_features, days since release, tone recency).
## reusable_code
learned_policy.walk_forward_brake as the template for a purged, quarterly-refit logistic model with missing-value indicators; market_execution_rl's order populations (1,153 A/A+ arrivals, 2,394 entries and exits); simulate.run(allocator=...).
## expected_effect
INFERRED: small, 0 to +2 CAGR points. Allocation experiments show weighting matters less than selection (equal weight on the same names 0.605 vs rule 0.611).
## risks
Only a few thousand correlated events, so overfitting risk is high. It must not reduce gross exposure.
--- [5]
## idea
Deprioritise the ML dead ends and keep 15-minute ML to execution only
## rationale
Recorded negatives: index or cash timing (ridge gate, learned brake, cash conditions); volatility-forecast sizing (QLIKE -15.5% with no book gain; volatility targeting halves CAGR); allocation RL with about 65 independent periods; deep daily or 15-minute OHLCV encoders (IC near 0: tape, chart CNN, MASTER, xsect); intraday RL (negative at 3 bp); execution RL (a few bps, unstable by year).
## where_it_plugs_in
Research roadmap. For 15-minute work, test the rule-based sell-at-close-auction flag against the paper record's close_shortfall_bps rather than a learned scheduler.
## reusable_code
The market_execution_rl fill model and populations; the paper-ledger field close_shortfall_bps.
## expected_effect
Frees effort for selection work, where the return lies.
## risks
This does not rule out order-book-level ML. That needs trade and quote data the free IEX bars do not have.
--- [6]
## idea
Repair the prospective ML plumbing
## rationale
Untouched evidence is the only adoption path. Right now the shadow identity is broken and the archive needs 750-1,000 sessions before any forecast.
## where_it_plugs_in
opportunity_shadow.identity: hash only the functions actually read (trailing_levels, _future_session_offset, features), or declare a migration for df4dc669. learned_archive: add a research-only pooled-universe fit tagged evidence_basis='retrospective-price', and keep the recorded-only adoption gate.
## reusable_code
opportunity_shadow.migration/MIGRATIONS; learned_policy.HistoricalInputs.evidence_basis guard (:462-463).
## expected_effect
Restores prospective collection and yields shadow forecasts within weeks rather than years.
## risks
A retrospective fit must never size live targets. The existing guard enforces this and must be kept.
## reuse_inventory
Folds and purging:
- harness.walk_forward_folds(n_sessions, train_size, test_size, horizon, embargo=0) -> list[(range, range)] (backend/market/harness.py:227)
- learned_policy.eligible_training_sessions(fit_session, horizon_end) -> ndarray (learned_policy.py:169)
- model.inner_split(train, config) -> (fit_range, val_range), which applies a second horizon purge (model.py:641)
- learned_research.training_labels(values, dates, horizon, holdout) freezes holdout labels (learned_research.py:107)
- growth_pilot.split_rows(data, start, stop, horizon) (growth_pilot.py:161)

Labels and features:
- learned_policy.relative_open_labels(inputs), next-open SPY-relative (:119)
- learned_policy.cross_sectional_ranks(inputs), membership-aware midranks with rank_features mask (:137)
- learned_policy.future_drawdown_labels(qqq_close) (:285)
- panel.forward_residual(h, beta_lookback=120) and rolling_beta (panel.py:107-125)
- simulate.adjusted_open(panel) (desk/simulate.py:315); allocation_controls.adjusted_open(open, close, adj_close) (:79)
- growth_pilot.dataset(panel) with 8 features and FOMC distances (:48)
- opportunity_learning.features(panel, store, asof) and normalize(values, training, fitted) with missing-value indicators (:52, :59)
- model.build_features(...) (:144) and load_extra_features(store, panel, 'alpha+edgar+tone+technical+intraday+calendar+macro', asof) (:1122)
- alpha.alpha_features(panel) (alpha.py:124); technical.technical_features(panel) (technical.py:262); alpaca.intraday_features(panel, bars) (alpaca.py:263); tape.tape_tensor (tape.py:77)
- baselines.percentile_rank, average_rank, momentum(panel, 252, 21), all_baselines (baselines.py:93, 107, 42, 132)

Learners:
- learned_policy.walk_forward_ranker(inputs, *, first_training_sessions=750, observed_labels=None, labels_recorded_on=None) -> Forecasts (:203), monthly refit with model hashes
- learned_policy.walk_forward_brake(...) (:333) and brake_scale_path(p) (:435)
- model.walk_forward(panel, config, log, extra, tape, market_extra) -> WalkForwardResult (:934); score_today (:1023); session_loss (:566); Normalizer (:273)
- nested_ridge.fit(inputs: RegressionInputs, fit_index, alpha, *, min_train_rows=504) -> RidgeFit, with full receipts (:361)
- market_expectations._training_mask, _expected and _carried (publication-gated yearly LightGBM)

Policy adapters:
- learned_policy.policy_targets(report, forecasts, t, *, policy, config=None) (:454); allocator_for(forecasts, policy) (:527); _vector_ranks (:510)
- risk.desk_targets(scores_today, graded_today, panel, regime, config=BOOK_CONFIG, held=None) (desk/risk.py:160)
- challenger.with_gap(opinions, gap) (challenger.py:91)
- neural_policy_comparison.candidate_scores and _allocator_for (:108, :128)

Ledgers and accounting:
- simulate.run(report, since, config, rebalance, cost_bps, use_exits, allocator, ..., funded_allocation, trend_brake, brake_path_override, journal) (desk/simulate.py:643); simulate._Book.plan, _fill and equity (:1303-1619)
- learned_research.replay(data, rank, brake, first, policy, cost_bps, *, journal=None) (:192); metrics(path, start, stop) (:303); rolling_wins(path, control) (:337)
- allocation_replay.replay(panel, instructions, *, first, cost_bps, start_equity, journal) and AllocationInstruction (:247, :33)
- allocation_controls.constant_exposure(closes, opens, fraction, cost_bps, *, journal, sessions, symbol) for funded SPY and QQQ (:98)
- growth_pilot.rebalance(holdings, cash, target, cost) (:103) and evaluate(data, rows, chooser, cost, stride) (:189); growth_objective.reward and evaluate

Receipts and verification:
- research_journal.ResearchJournal (:136); research_journal_replay.verify_snapshot and verify_archive (:770, :795)
- nested_market_study.archive and _evidence_digest
- forecast_diagnostics.diagnose(regression, outer_folds, *, first_decision, stop_decision, evaluated_on) (:494)

Scorecards and statistics:
- neural_study_metrics.Curve, from_simulation, scorecard(curves, *, cost_bps), regime_scorecard(curves, *, cost_bps, evidence), chronological_fold_scorecard(curves_by_cost, *, evidence, train_size, test_size, horizon, embargo) (:35, 55, 230, 429, 563)
- harness.evaluate_scores (:159) and rank_correlation (:126)
- strategy_bench.build(sessions, series, note) (:143)
- _hac_t(diff, lag) (market_allocation_rl.py:285; duplicated in 3 other CLIs)
- entry_pilot.paired_interval(result, baseline, block=20, repetitions=1000) (entry_pilot.py:349)
## open_questions
1. The task context says equal weight "beats every selection rule tested". The repository's own recorded results contradict that:
   - momentum120 70.5% vs equal weight 39.5% (2019-2026, learned-price study)
   - /3 59.2% vs equal weight 43.7% (2020-2026, nested study)
   - /3 157.9% vs equal weight 65.3% (2025-26)
   - momentum20/120 +348-419% vs equal weight +122% (2025-26)
   Which comparison, convention and window is the ~38-41% claim from?
2. Is the momentum and /3 edge over equal weight real, or book selection bias? Momentum is "nothing" on the 400-name off-book control (CHANGELOG.md:3486). No learned ranker or momentum top-10 has been run on the off-book panel with the funded long-only ledger.
3. The planned "alpha+edgar+technical+tone" LightGBM/MLP/xsect rows at h20 under the beta label (NEXT_SESSION.md:9424-9427) have no recorded result. Did they run?
4. Does the expectations-gap improvement (+5.1 points a year) survive the causal fixes in df4dc669 and the qualification of the naive baseline? It has not been re-measured.
5. Does the Spark nightly checkout include df4dc669? If so, the frozen neural ML-forward ledger is currently halted (identity 95a54c58... has no migration). What is the ledger's latest sequence on the host?
6. Is it acceptable to re-register the ranker horizon (20 or 60 instead of 10), given the frozen spec in trading-ml-path-2026-09-22.md:96-98 forbids a horizon search after results? A single pre-declared change, justified by the positive-control evidence, seems defensible, but it needs operator sign-off.
7. How many effective independent observations would a 532-name broad-universe ranker have, after accounting for theme correlation? No dependence-adjusted power calculation exists for any learned candidate.