## scope
Read-only ledger of every trading experiment, strategy and finding recorded from the start of the market work (2026-09-03/04) through 2026-09-21. Nothing in the repo was modified. Sources read in full: docs/TRADING_ROADMAP.md; docs/MARKET_SLICE_1_REVIEW.md; every docs/research/*.md dated on or before 2026-09-21: cash-funding-audit-09-13, fomc-window-evaluation-09-13, pick-timing-audit-09-13, desk-forward-evidence-09-14, desk-rl-readiness-09-14, fomc-restoration-09-14, growth-pilot-09-14, growth-gpu-replication-09-14, opportunity-learning-09-14, opportunity-learning-asof-09-14, fomc-gate-09-15, intraday-timing-09-15, post-decision-reversal-09-15, persistence-length-09-16, opportunity-and-cash-09-18, stretch-leg-09-18, fundamental-features-09-20, conditional-entry-pilot-09-20, entry-context-protocol-09-21, entry-context-results-09-21, portfolio-allocation-protocol-09-21 and portfolio-exposure-objective-09-21. Three undated docs were included because their mtimes fall before 2026-09-21: ml-forward-evaluation-spec, retail-decision-workflow and technical-timing-next-evaluation. JSON read: fomc-window-evaluation (all 48 rows), intraday-funded-cadence, fundamentals-asof-audit and pick-timing-audit. docs/NEXT_SESSION.md lines 4700-10180 cover every trading heading from 2026-09-03 to 2026-09-22; the file is newest-first, so line 4755 onward begins at 2026-09-22 and runs backward in time. For exhaustiveness I also read the trading entries of docs/CHANGELOG.md for 2026-09-06 to 2026-09-21 (lines 1097-1180, 1272-1336, 1814-1830, 1992-2019, 2229-2262, 2678-2707, 2773-2846 and 3017-3990). I also read the result docstrings in backend/cli/market_allocation_rl.py:41-64 and backend/cli/market_xsect_net.py:31-50, and the survivorship note in backend/market/universe.py:23-38. DATE NOTE: the line range you set (4755 to end) includes a few 2026-09-22 entries: the zero-cost test, the vol/vol_trend results and the overtrading and midpoint instructions. These are included and labelled 09-22. Lines 4706-4753 (also 09-22: the '15 min precise entries' instruction and the HFT-transfer addendum) sit just above 4755; they are quoted only as operator objectives and constraints. EXCLUDED as later than 2026-09-21: research docs dated 09-22 onward, the claude-review-2026-09-23 folder, and NEXT_SESSION lines 1-4699. Those lines are where cash-bounded-breakout-rotation/3, the QQQ 200-day trend brake with 0.97/1.02 hysteresis, green/red switching into QQQ (~200 turnover a year), the idle-cash next-session deployment proxy (~+5 CAGR) and the 38-41% equal-weight-since-2016 figure appear. The 43.57% vs 22.01% comparison (vol-targeting roughly halving CAGR) is in range and appears below. Some 2026-09-14/20 docs carry 2026-09-25 amendments; these are flagged in caveats. All historical return figures are retrospective, on a survivor-selected universe picked in 2026, and on periods already reused many times.
## experiments
--- [0]
## name
Slice-1 per-ticker neural windows (design review, never trained)
## date
2026-09-04
## source_doc
docs/MARKET_SLICE_1_REVIEW.md:1-143; docs/NEXT_SESSION.md:10034-10093
## hypothesis
A network fed raw 20-day windows (own return, log volume, market-relative) for 23 hand-picked tickers can predict each ticker's 20-day forward return.
## method
Code and design review of b38c64e2 before any training. The Yahoo fetch was never stored successfully (HTTP 429).
## result_numbers
23 tickers x 730 days is about 11,000 overlapping windows. CRWV has about 360 bars. Labels overlap 20:1. 15/15 tests passed. No model was trained.
## verdict
closed-negative
## caveats
Rejected on design grounds: per-ticker regression on near-zero signal-to-noise, survivorship, and open/high/low discarded. The review prescribed cross-sectional ranking, purged walk-forward, baselines (12-1 momentum, 20-day relative strength vs SMH, equal-weight theme momentum) and volatility-targeted sizing. It also suggested Tiingo/Polygon, which conflicts with the later free-data-only rule.
--- [1]
## name
Learned cross-sectional rankers vs 12-1 momentum (full sweep)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9520-9602, 9341-9355
## hypothesis
MLP, GRU, cross-name attention (xsect), MASTER or LightGBM on raw channels or 31 alpha features beat 12-1 momentum on rank IC net of 10bp.
## method
532 names, 2015-01-02 to 2026-09-04. Walk-forward with purged folds, rank IC against residual return, top/bottom 20% long-short, 10bp.
## result_numbers
h10: momentum IC 0.015 (t 0.95, net Sharpe 0.15); mlp raw 0.015 (0.12); gru -0.005 (-0.27); xsect raw 0.012 (-0.36); mlp alpha 0.018 (t 1.30, -0.26); lgbm 0.002 (-0.67); master -0.005 (-0.70); xsect alpha -0.001 (-0.63). h5: momentum 0.020 (0.09); lgbm -0.003 (-0.92); mlp 0.017 (t 1.59, -0.10); xsect 0.013 (-0.30); master 0.012 (-0.44); 3-seed mlp 0.018 (-0.68); 3-seed xsect 0.013 (-0.61). h20: lgbm 0.003 (-0.53); master -0.014 (-0.73); mlp raw -0.006 (-0.51). h60: lgbm 0.018 (-0.03); mlp -0.072 (t -1.98, -0.63); master -0.033 (-0.46).
## verdict
closed-negative
## caveats
At 60 sessions the fits invert out of sample. An earlier masking bug trained on about 96 themed names while momentum used 532; those rows are void. A later beta-label rerun also found nothing.
--- [2]
## name
Positive controls: short-horizon reversal and theme momentum
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9586-9602
## hypothesis
Known effects are visible in the harness and show the right label horizon.
## method
Unfitted controls through the same harness and panel. Sharpe reported at 0bp and 10bp.
## result_numbers
1-day reversal h1: IC 0.016, t 4.65, Sharpe 0.42 / -3.90. 5-day reversal h5: 0.024, t 3.16, 0.66 / -0.04. 10-day reversal h5: 0.018, t 2.40, 0.38 / -0.12. Theme reversal (20d) h10: 0.030, t 2.07, 0.14 / -0.07. Theme momentum (60d) h60: 0.054, t 1.56 over 47 periods, 0.39 / 0.36.
## verdict
closed-negative
## caveats
Reversal is real but cost eats it at full rebalancing. Theme momentum at 60 sessions survives 10bp but is not significant (t 1.56) and was not pursued further. Conclusion recorded: 'Structure exists; the label horizon was wrong.'
--- [3]
## name
EDGAR point-in-time fundamental controls (fundamental blend)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9442-9472
## hypothesis
Point-in-time filing growth and margin features rank the cross-section net of cost.
## method
8-K 2.02 events with acceptance times; XBRL earliest-filed value per period; 532 names; 10bp.
## result_numbers
Post-earnings drift h20: IC 0.002 (t 0.34, net Sharpe -0.10). Revenue yoy: 0.027 (t 2.46, 0.60). Revenue qoq h60: 0.025 (t 2.24, 0.65). Gross margin: 0.020 (t 1.96, 0.53). Blend h20: 0.029 (t 3.07, 0.66). Blend h60: 0.039 (t 2.63, 0.71). Blend IC by subperiod: 0.049 (t 2.94) in 2015-18, 0.041 in 2019-21, -0.002 in 2022-24, 0.007 (t 0.34) in 2025-26.
## verdict
adopted
## caveats
Became the fundamental analyst. Its edge has decayed to about zero since 2022. The frozen path zero-filled missing ratios and used earliest-filed values; this was corrected in the live desk on 2026-09-21. Survivorship applies.
--- [4]
## name
Learned models with filing features
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9435-9440
## hypothesis
Adding EDGAR features lets learned rankers beat the hand-built blend.
## method
Same harness, six configurations.
## result_numbers
Rank IC: lgbm h20 0.013; mlp h20 0.008; xsect h20 -0.008; lgbm h60 -0.044; mlp h60 -0.014; master h60 -0.010.
## verdict
closed-negative
## caveats
'The models keep losing to a hand-built ranking of the same columns.'
--- [5]
## name
Sizing engine on the fundamental blend (inverse-vol, caps, vol target, turnover control)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9474-9489
## hypothesis
Risk-based sizing of the top fraction improves risk-adjusted book returns over the benchmark.
## method
Long-only top fraction, 15% vol target, 10%/40% name/theme caps, 20-session rebalance, 10bp.
## result_numbers
Sharpe 1.02 vs benchmark 0.83; max drawdown -15%; turnover 16% per rebalance. Tighter book (top 10%, 20% target): Sharpe 0.92, drawdown -27%.
## verdict
adopted
## caveats
Two bugs were fixed during the build: a diagonal vol estimate let realised vol reach 39%, and skipping small sales let stale positions reach 2.7x gross. A later finding (09-07) is that weighting is not where risk-adjusted return is decided; selection is.
--- [6]
## name
Trader's toolkit: 33 technical features as rankers
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9357-9376
## hypothesis
EMA, crossover, 52-week, candle and MACD features rank forward returns.
## method
Each feature alone through the harness, 532 names since 2015.
## result_numbers
52-week-low distance: h20 IC 0.041 (t 2.60, net Sharpe 1.05); h60 0.084 (t 3.45, 1.23). Extension above the 21 EMA (fade) h5: -0.022 (t -2.79, -0.94). 9/21 cross-up h5: -0.007 (t -1.79, -2.10). 50/200 golden cross h5: -0.007 (t -2.91, -0.71). 21/50 converging h20: 0.011 (t 0.94, -0.05). Candles, MACD and trend stack: about 0 with negative Sharpe.
## verdict
closed-negative
## caveats
The 52-week-low signal was beta: it fell to 0.005 (t 0.3) under the beta-adjusted label. Crosses lose. EMAs are informative only as levels price returns to.
--- [7]
## name
Composite score (fundamental blend + 52-week-low trend + 21-EMA fade)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9378-9384
## hypothesis
A hand-built composite beats its parts.
## method
market_book --score composite.
## result_numbers
h20 IC 0.047 (t 3.73), hit rate 0.65, net Sharpe 1.06. Book Sharpe 1.08 vs 0.92 benchmark; max drawdown -8%.
## verdict
closed-negative
## caveats
Superseded the same day: its 52-week-low leg was beta, and tone was added after the beta-label correction.
--- [8]
## name
Theme rotation read from filings
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9386-9391
## hypothesis
Each theme's median fundamental blend, used as every member's score, captures rotation better than theme price momentum.
## method
market_rotation over theme baskets.
## result_numbers
h20 IC 0.049 (t 2.39, net Sharpe 0.48). Theme price momentum on the same sessions: -0.036. Revenue growth as of 09-04: memory-storage 35%, networking 32%, ai-compute 29%, software 19%, power-cooling 10%.
## verdict
adopted
## caveats
INFERRED: this is the basis of the rotation analyst, which carries a half vote (retail-decision-workflow.md:82).
--- [9]
## name
DeepSeek release-tone reader (sentiment analyst)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9393-9401, 9276-9279; docs/CHANGELOG.md:3939-3950
## hypothesis
An LLM's reading of outlook, demand and pricing in earnings releases ranks forward returns.
## method
EX-99.1 scored by DeepSeek into bounded fields; point-in-time tone features; harness.
## result_numbers
First reading (about 40-51 names): tone_guidance h20 IC 0.054 (t 3.68, net Sharpe 0.74); guidance change 0.052 (t 3.93); tone blend 0.062 (t 4.24, net Sharpe 1.10). The fundamental blend on the same names: 0.028 (t 1.35). Beta-adjusted: 0.044 (t 3.0) at h20 and 0.076 (t 3.8) at h60. By liquidity third: 0.048 / 0.031 / 0.026. Dropping tone lowers the desk from 0.046 to 0.038 and net Sharpe from 0.79 to 0.51.
## verdict
adopted
## caveats
Tone is not significant at 60 sessions in any liquidity subset. Scores repeated at temperature 0 differ (1.0 vs 0.8), an evidenced xfail. Prompt-version re-scores move grades (PANW) and count as data revisions. Capex and supply fields carry nothing alone.
--- [10]
## name
Beta-adjusted label correction
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9264-9290
## hypothesis
An own-minus-benchmark label pays high-beta names for market drift, so the label should subtract 120-session beta x benchmark.
## method
Beta known at t; re-measure the controls and the composite.
## result_numbers
52-week low: 0.045 (t 2.8) to 0.005 (t 0.3). High vol: 0.037 to -0.017. Fundamental blend: 0.026 to 0.021 (t 2.3). 21-EMA fade: 0.027 to 0.024 (t 1.7). Tone blend: 0.063 to 0.044 (t 3.0) at h20 and 0.076 (t 3.8) at h60. New composite (tone added, 52-week low dropped): IC 0.032 (t 3.1); book Sharpe 1.05 vs 0.84; max drawdown -6.8%.
## verdict
adopted
## caveats
The beta-adjusted label is now the default in evaluate_scores and model labels.
--- [11]
## name
Calendar effects (FOMC, expiries, turn of month)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9292-9297, 7708-7711, 9245-9248
## hypothesis
Scheduled events carry exploitable return patterns.
## method
94 FOMC decisions plus expiry calendars; lgbm with a calendar feature layer.
## result_numbers
Index at day -1: +24bp (t 1.9). High-vol minus low-vol on decision day: +41bp (t 2.4). AI basket: +32bp (t 1.9), then -29bp on day +2 and +32bp on day +3. Quad witching -41bp (t -3.1). Monthly expiry -13bp (t -2.2). Russell day 50% more volatile. Turn of month faint; December/January nothing. lgbm +calendar: h20 0.007, h5 0.005.
## verdict
inconclusive
## caveats
Kept as context only ('regime.py explicitly leaves calendar effects out of position sizing') until the 2026-09-13 FOMC overlay.
--- [12]
## name
Macro state features (VIX, 10-year, dollar, oil)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9298-9301, 9245-9248
## hypothesis
Macro state improves the ranking.
## method
Macro feature layer in LightGBM under the beta label.
## result_numbers
lgbm +macro h20: 0.005 (t < 1).
## verdict
closed-negative
## caveats
The regime still carries a 60-session yield-change rule. Missing yield data is treated as no tightening (retail-decision-workflow.md:102-104), an unresolved gap.
--- [13]
## name
Documented anomaly controls (low vol, low beta, illiquidity, anti-lottery, balance-sheet)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9303-9310, 9249-9252
## hypothesis
Published anomalies hold on this universe.
## method
Controls through the harness, plain then beta-adjusted.
## result_numbers
Low vol and low beta are negative (high vol +0.037 plain, -0.017 beta-adjusted). Illiquidity: +0.015 to +0.021 (t 2.6). Anti-lottery: nothing. Buybacks 0.002. Asset growth -0.015 (t -1.7). Book-to-market 0.007.
## verdict
closed-negative
## caveats
The illiquidity effect is plausibly survivorship. None entered the composite.
--- [14]
## name
15-minute IEX session features and tape encoder as daily ranking inputs
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9312-9319, 9403-9417, 9245-9260
## hypothesis
Intraday tape shape (VWAP trend, bars above the 15-minute 9 EMA, chop) predicts multi-day returns.
## method
Ten session features from Alpaca IEX 15-minute bars (back to 2016). A CNN tape encoder over 26 slots x 5 sessions with cross-name attention.
## result_numbers
Preliminary, 198 names, beta-adjusted h20: bars above the 15-minute 9 EMA IC 0.029 (t 1.6); trending tape 0.026 (t 1.5); calm tape 0.015 (t 1.6, net Sharpe 0.58). At h5 every strength measure is mildly negative. Tape encoder: tape_h5 0.004 (t 0.4), tape_h20 -0.004. On the 90 book names the intraday controls 'measured zero on every session feature'.
## verdict
closed-negative
## caveats
The note states 'the 15-minute layer is closed unless a new idea comes with a number'. IEX is one venue.
--- [15]
## name
Desk grade rule (fundamental/technical/sentiment/value + half-weight rotation; A+/A/B/C)
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9203-9215
## hypothesis
A fixed voting grade orders forward returns.
## method
desk.calibrate on 90 names, beta-adjusted.
## result_numbers
Per 20 sessions: A+ 102bp (t 2.0), A 26, B 24, C 15. At 60 sessions: 283 / 173 / 105 / 59bp (A+ t 1.9). Graded-score IC 0.035 (t 2.3) vs composite 0.025 (t 1.8). Size multipliers 1 / 0.75 / 0.5 / 0.
## verdict
adopted
## caveats
This is the core of the live desk. Grades are not calibrated probabilities.
--- [16]
## name
Regime analyst: correlation novelty and participation gating
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9217-9230
## hypothesis
Signals work only in some participation regimes, and the AI/software co-movement structure shifts.
## method
Correlation of theme residuals; participation (20-day dollar volume vs the year).
## result_numbers
Software/AI residual correlation: +0.19 over the decade, -0.37 in 2026, -0.52 in the latest window; novelty z +4.8. Above vs below median participation: tone IC 0.033 (t 2.2) vs -0.004; AI-vs-software leader 0.086 (t 3.0) vs -0.007; composite 0.049 (t 2.3) vs -0.002. After the top participation quintile the AI basket lags SPY by about 1.2% over 20 sessions; after the bottom it leads by 1.1%.
## verdict
adopted
## caveats
Rule: selection confidence 0.5 below median participation (rotation withheld); exposure 0.75 in the top quintile.
--- [17]
## name
Technical analyst playbook that switches with the AI theme's trend
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9232-9243
## hypothesis
Fade stretch in a falling theme; buy strength in a rising one.
## method
Conditional IC by the AI basket's 60-session return.
## result_numbers
21-EMA fade while the theme falls: IC +0.082 (t 2.5); while rising: -0.006. 52-week-high proximity while rising: +0.042 (t 2.3). Momentum 120/21: +0.074 (t 2.6) in low participation. The first build lost -0.057 on 2024-2026. EMA slope and stack paid only in the 2026 low-correlation regime (+0.066 to +0.072, t 2.0, 35 windows). Buying near the 200 EMA lost in every regime (-0.023; -0.082 on 2024-2026).
## verdict
adopted
## caveats
EMA slope and stack are cited, not scored.
--- [18]
## name
Beta-label model rows and daily chart CNN
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9245-9248
## hypothesis
Learned models with technical, calendar or macro layers beat tone and the composite.
## method
LightGBM and a chart CNN under the beta label.
## result_numbers
lgbm alpha h20 0.008; +technical h20 0.010 and h60 0.016; +calendar 0.007; +macro 0.005; all t < 1. Chart CNN: h20 -0.001, h5 -0.012 (t -2.2).
## verdict
closed-negative
## caveats
'Nothing learned beats the tone.'
--- [19]
## name
Trade location (support/resistance levels) and the bearish-core veto
## date
2026-09-05
## source_doc
docs/NEXT_SESSION.md:9127-9185
## hypothesis
Location between support and resistance, multi-timeframe trend and reward-to-risk improve trade quality among qualified names (operator's objection).
## method
levels.py swing pivots, EMAs as levels; beta-adjusted next 20 sessions with maximum adverse excursion.
## result_numbers
Weekly trend up +1.0% (t 4.2) vs -2.0% flat. Daily trend up +0.9% (t 3.3). Top of the 60-session range +1.3% (t 3.7, hit 0.56) vs -0.5% at the bottom. More than 15% above support earns nothing, with -12% adverse excursion vs -7.6% at support. Reward-to-risk inverts: RR < 1 gives +0.7% (t 2.3). After rebuild: A+ 102bp/20 (t 1.9) and 343bp/60 (t 2.3, from 258); IC 0.031 (t 2.1) at h20 and 0.050 (t 2.3) at h60. Veto (a bearish core analyst caps the grade at B) lifts A from 17 to 53bp/20.
## verdict
adopted
## caveats
The support-distance leg was later found discontinuous and replaced by a band leg (2026-09-18). In 2026 SNDK was A+ every session (+184% held) and CRWV C all year.
--- [20]
## name
Mean-reversion dip-entry claims (below 21 EMA / lower band)
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9080-9086; docs/CHANGELOG.md:3405-3406, 3324-3326
## hypothesis
Deeply stretched qualified names bounce.
## method
Conditional forward returns among qualified names.
## result_numbers
More than 8% below the 21 EMA: +1.2% in 5 sessions (t 3.5, hit 0.58). Below the lower band: +0.9% (t 2.6). Below the band while the AI basket falls: +2.1% (t 4.3, hit 0.62). By 20 sessions the dip edge is gone and more than 8% above the 21 EMA pays +2.0% (t 2.6).
## verdict
inconclusive
## caveats
This is a 5-session effect against the book's 20-session horizon. market_dip (09-07) found no out-of-sample skill after label purging. A dip-signal units bug was fixed 09-12 (band_position <= 0.20 had been <= -0.80). Entry triggers exist, but 'dips are entries, trend is the hold'.
--- [21]
## name
Walk-forward LightGBM on all desk features (and RL declined)
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9086-9092
## hypothesis
A learned model on analyst ranks, levels, stretch, Bollinger, momentum and regime beats the fixed grade.
## method
Walk-forward, out of sample.
## result_numbers
Out-of-sample IC 0.006 (t 0.4) vs the grade's 0.035 (t 2.1) on the same sessions.
## verdict
closed-negative
## caveats
RL was declined: 'one path of 90 correlated names is not many episodes'.
--- [22]
## name
Per-name trade backtest: entry triggers plus price stops
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9094-9107, 9061-9068
## hypothesis
Entering on an A grade plus a dip/breakout trigger and exiting on a support or chandelier stop beats holding.
## method
desk/backtest.py, next-open entry, 10bp per side; 8 names since 2024 and 6 since 2021-06.
## result_numbers
AVGO since 2021: support stop +118%, chandelier 3 ATR +40%, no stop with slow grade exit +173%, hold +214%. NVDA: +104% / +122% / +138% / +265%. PANW: -10% / +10% / +80% / +171%. Hit rates 30-60%. Under the new defaults: AVGO +176% vs hold +214%; MU +182% vs +252%; PANW +40% vs +171%.
## verdict
closed-negative
## caveats
Stops are the worst part. The first A grade arrives late, and positions are out about a third of the time.
--- [23]
## name
Book construction variants (vol target, top fraction, equal weight)
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9109-9120, 9046-9052
## hypothesis
Risk-sized top-ranked books beat equal weight and SPY on a risk basis.
## method
Graded scores through the sizing engine on 90 names, monthly rebalance, no stops, since 2021-06.
## result_numbers
Top 20% @ 15% vol: +16.1%/yr, Sharpe 1.25, DD -16.5%. Top 10% @ 25% vol: +30.9%, 1.55, -20.2%. Equal weight of all 90: +40.9%, 1.28, -38.7%. SPY: +14.3%, 0.85, -24.5%. Daily equal weight of A-or-better +47.3% (Sharpe 1.22) vs C names +42.0% (1.33). New default (top tenth, 25% vol, 15% cap): +31.6%/yr, Sharpe 1.55, DD -24.9%.
## verdict
adopted
## caveats
'The grades barely separate' in raw terms. 'What the desk adds is risk: a third of the drawdown at a similar Sharpe.' Equal weight of the hindsight book wins on raw return.
--- [24]
## name
Defaults re-set from backtests: no price stop, 10-session grade exit, 3-session stance persistence
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9036-9069, 8899-8906
## hypothesis
The measured best rules should be the defaults.
## method
Re-calibration after the changes.
## result_numbers
Per 20 sessions: A+ 77bp (t 1.4), A 85 (t 1.7), B 10, C 18. At 60: 295 / 223 / 88 / 55. IC 0.034 (t 2.3) at h20 and 0.052 (t 2.2) at h60. Persistence cost A+ 102 to 77bp.
## verdict
adopted
## caveats
Paper book rules: rebalance every 20 sessions; between rebalances exit only after 10 sessions below B; no price stop, 'because every stop measured worse than none on every name'; moves under 0.5% of equity skipped.
--- [25]
## name
15-minute fill timing and entry-day structure
## date
2026-09-06
## source_doc
docs/NEXT_SESSION.md:9003-9030
## hypothesis
A pullback to the 15-minute 21 EMA or a later print beats the next-open fill; 15-minute structure predicts outcomes.
## method
9,968 entry days (A-or-better plus dip/breakout trigger), 90 names, Alpaca IEX 15-minute bars.
## result_numbers
Vs session VWAP: open -1.1bp; 10:30 -2.4; pullback to the 15-minute 21 EMA +1.4 (occurs on 83% of days); break of the first bar's high +0.9; close +2.5. On dip days 10:30 is 3bp under the open and the close 19bp over. The 20-session return from every fill is within noise of the open (all t < 1.1; close on dip days t -1.9). Entry day closing above the 15-minute 21 EMA: all +3.49% vs +3.01% (t 1.5); breakouts +3.50% vs +2.91% (t 1.7); dips t 0.0. Dip days closing below the open: +3.99% vs +2.86%. Expected move 3.3% over 20 sessions.
## verdict
closed-negative
## caveats
'The backtest's next-open assumption stands, and a 10:30 entry on dip days is the only thing worth doing differently.' 'The 15-minute layer is closed.'
--- [26]
## name
Desk rules simulated as traded, and the band-exit overlay
## date
2026-09-06
## source_doc
docs/CHANGELOG.md:3895-3937
## hypothesis
A Bollinger band exit, chosen on a per-trade study, improves the book.
## method
desk/simulate.py walks the actual rules; 21 exit triggers screened over 86,209 held sessions.
## result_numbers
Desk rules since 2021-06: 31.6%/yr, Sharpe 1.81, DD -18.3%, vs the sizing engine alone at 31.4% / 1.55 / -23.6%. The band exit overlay costs -3.0%/yr (t -1.99) and lowers Sharpe in 5 of 6 years. Held B-or-better names beat the benchmark by 1.95% over 20 sessions; the 'band wide, price near top' trigger is followed by +3.10%. None of the 21 triggers is followed by a fall. 203 of 287 closes are replacements by a better-ranked name.
## verdict
closed-negative
## caveats
The rebalance is the exit. 2022 is the only year the overlay helped.
--- [27]
## name
Tone tilt toward thin, illiquid names
## date
2026-09-06
## source_doc
docs/CHANGELOG.md:3939-3950
## hypothesis
Tilting the tone signal toward less-traded names improves the desk.
## method
Tone IC within liquidity thirds; tilt at five strengths.
## result_numbers
Tilt moves the desk score from 0.0459 to at best 0.0470 while lowering net Sharpe. The desk across thirds: 0.058 / 0.054 / 0.051.
## verdict
closed-negative
## caveats
Tone was retained unweighted.
--- [28]
## name
Lazy Prices filing-similarity reader
## date
2026-09-06
## source_doc
docs/CHANGELOG.md:3854-3890
## hypothesis
Rewritten 10-K/10-Q text predicts returns (Cohen, Malloy and Nguyen 2020).
## method
2,274 year-over-year comparisons, 93 names since 2019; beta-adjusted, non-overlapping.
## result_numbers
IC +0.026 (t 1.6) at h20 and +0.048 (t 1.5) at h60. As a vote: IC 0.0459 to 0.0492 but net Sharpe 0.79 to 0.58. A first look (-5.05%/120 sessions, t -12.58) was an overlap and beta artefact: non-overlapping t -1.74; beta-adjusted sign +0.38.
## verdict
closed-negative
## caveats
Likely cause: heavily followed large caps.
--- [29]
## name
Better volatility forecast for sizing
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3825-3841, 3586-3605
## hypothesis
A better 20-session volatility forecast improves the book.
## method
11 models, walk-forward, 147,376 name-sessions; the winner put behind the desk's sizing (corrected run, 20 folds, 148,596 name-sessions).
## result_numbers
The QLIKE network beats trailing-60 by 15.5% and HAR by 7.0%. The same network on MSE is 2.9% worse. Book: trailing-60 +31.8%/yr, vol 17.2%, Sharpe 1.85, DD -19.0%, total +389.6%. QLIKE: +31.3%, 17.3%, 1.82, -18.9%, +378.2%. Rank correlation 0.854; the swap moves 8.4% of the book.
## verdict
closed-negative
## caveats
The first run never reached the book (a patching bug). 'The book is not sensitive to this input at the margin.'
--- [30]
## name
Unequal (ridge) analyst weights
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3607-3644, 3412-3432, 3308-3327
## hypothesis
Learned analyst weights beat equal weights.
## method
Five-weight ridge shrunk toward equal, walk-forward with purge; book simulations; then walk-forward weights run through the full rules.
## result_numbers
h20 IC: equal 0.0526 (t 3.30, net Sharpe 1.03); ridge shrink-1 0.0536 (t 3.59, 1.08); least squares 0.0382 (t 2.53, 0.51). h60: 0.0526 (t 1.81, 0.65) / 0.0631 (t 2.25, 0.78) / 0.0402 (t 1.39, 0.54). Weights: value 0.60, fundamental 0.50, sentiment 0.42, technical 0.38, rotation 0.30. Book from 2021-06: equal +31.8%, vol 17.2%, Sharpe 1.85, DD -19.0%; ridge +31.6%, 16.7%, 1.90, -17.8%; sentiment-led +31.6%, 16.8%, 1.88, -19.8%. Walk-forward from 2018-01-31: equal +27.2%, 16.5%, 1.65, -20.4%; fixed ridge (development) +26.2%, 15.7%, 1.67, -17.8%; walk-forward ridge +25.0%, 15.5%, 1.61, -17.7%.
## verdict
closed-negative
## caveats
Adopted on the morning of 09-07 and reverted the same day. RIDGE_WEIGHTS are kept for the forward record.
--- [31]
## name
Intraday sleeve / RL on 15-minute bars (direct-Sharpe policy, PPO, published intraday rules)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3715-3783, 3648-3692
## hypothesis
An intraday strategy, flat at the close, on the 93 book names makes money at retail costs.
## method
69,223 name-sessions; train 2020-24, select 2025, test 2026 once; positions in [-1, 1], flat at the close; rerun after four verified defects (session clock, vol warm-up, baseline spec, loss).
## result_numbers
Corrected held-out results (15,151 sessions), Sharpe at 1 / 3 / 5 / 10bp one-way. Long the session open-to-close (turnover 2.00): 0.12 / -0.27 / -0.67 / -1.64. First-half-hour momentum: -2.38 / -4.86 / -7.34 / -13.55. Hourly reversal (turnover 11.49): -3.23 / -8.48 / -13.95 / -28.74. Direct-Sharpe best seed (0.84): -0.24 / -0.89 / -1.54 / -3.16. Seed average: -0.19 / -0.98 / -1.76 / -3.73. PPO (2.65): -1.01 / -1.52 / -2.02 / -3.24. Open-to-close earned 3.6bp per name-day in 2026 vs a 6bp round trip. PPO validation +1.10 / +1.69 / -0.29, lost on 2026.
## verdict
closed-negative
## caveats
Restated as 'these implementations did not demonstrate an advantage'. It does not rule out 15-minute data as features for the daily desk, or costs below 1bp.
--- [32]
## name
Learned intraday execution schedule (market_execution_rl)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3501-3526
## hypothesis
A schedule other than the open (close, TWAP, VWAP, first/last hour, direct policy, PPO) fills better.
## method
26 fifteen-minute bars, typical-price fills, walk-forward 2022-2026, t clustered by session.
## result_numbers
Pooled bps vs the open, buys / sells: close +5.31 (t 1.15) / -5.31; first hour +3.20 (t 1.73) / +0.80; direct policy +2.40 (t 2.23) / -2.18; PPO +3.17 (t 1.48) / +0.20. On the desk's own 344 orders the drift is about 10x larger; sells in the first hour -41bps (t -2.02, 57 sessions).
## verdict
closed-negative
## caveats
Market-on-open stays for buys. Neither agent found a schedule outside the fixed ones.
--- [33]
## name
Sells at the closing auction
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3492-3499; docs/NEXT_SESSION.md:8247-8268
## hypothesis
Exits fill better at the close than at the open.
## method
The rule re-decided every session: 2,394 entries and exits over 840 sessions.
## result_numbers
Sells at the close are 24bps better than at the open (t -2.77); buys are best at the open. 4 of 5 test years agree; 2026 reads the other way on 325 orders.
## verdict
adopted
## caveats
Not adopted on 09-07. It went live on 09-11, combined with the green-day skip (next entries).
--- [34]
## name
Offline RL over the desk's history (critic and AWR)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3449-3478
## hypothesis
A policy learned from the rule plus 32 perturbed books beats the rule.
## method
Walk-forward over 10 folds with a Sharpe-shaped 20-session reward; naive, Newey-West and every-20th-session t statistics; then run behind the full rules from 2017-12-27.
## result_numbers
Mean reward: rule +0.611. Equal weight, whole book +0.582 (NW t -0.66). Critic +0.562 (NW t -3.49). AWR capped +0.651 (+0.040, NW t +2.62, every-20th +1.09). AWR top names +0.648 (NW +2.58, every-20th +0.57). In the full rules: Sharpe 1.52-1.54 vs the rule's 1.64, with deeper drawdown.
## verdict
closed-negative
## caveats
'Wins the proxy and loses the book': the proxy has no cost, vol target, holding rule or minimum trade.
--- [35]
## name
Survivorship / name-choice measurement
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3480-3490; backend/market/universe.py:23-34
## hypothesis
The hindsight-picked book inflates every backtest.
## method
market_survivorship: equal weight of the book vs the 400 non-book universe names on common sessions.
## result_numbers
Book +34.2%/yr (Sharpe 1.24) vs control +15.6% (0.88): 'nineteen points a year' is name choice before any signal. The technical 20-session edge is book-specific; its 60-session edge is similar on the control; momentum is nothing on either.
## verdict
data-blocked
## caveats
The sentiment and value analysts cannot be measured off the book (no filings, tone or levels stored for those names). No point-in-time membership or delisted prices from free sources.
--- [36]
## name
Allocation RL choosing book weights (REINFORCE, cross-entropy)
## date
2026-09-07
## source_doc
backend/cli/market_allocation_rl.py:41-64; docs/CHANGELOG.md:3579-3580
## hypothesis
An agent choosing weights at the rule's gross beats the rule.
## method
Sharpe-shaped reward, 10 folds, 3 seeds, 2,164 test sessions.
## result_numbers
Rule +0.611. Equal weight, same names +0.605 (NW t -0.46). REINFORCE +0.579 (NW -0.72). Cross-entropy +0.585 (NW -0.79).
## verdict
closed-negative
## caveats
Lesson: 'equal weight on the same names scored the same as the whole sizing apparatus... The selection is.' A 2026-09-25 finding says the REINFORCE loss has a cancelling gradient (desk-rl-readiness-2026-09-14.md:48-54), so that row is not evidence of working learning.
--- [37]
## name
Cross-sectional ranking-loss network ladder (market_xsect_net)
## date
2026-09-07
## source_doc
backend/cli/market_xsect_net.py:31-50
## hypothesis
A whole-session network trained on rank IC beats the fixed grade.
## method
Ladder: A imitates the rule; B targets the forward rank; C uses raw features; D adds attention. 17 folds.
## result_numbers
h20: fixed grade IC 0.0530 (net Sharpe 1.03); step A 0.0537 (t 3.31, 1.00); step B 0.0052 (t 0.42, negative); B blended 0.0395. Step B at h60: 0.0137 (t 0.66). Steps C and D (87 raw features) were negative and not repeated.
## verdict
closed-negative
## caveats
An earlier step-A win came from smoothing; continuous conviction closed that gap.
--- [38]
## name
Chart-image CNN (Jiang-Kelly-Xiu) and model-based sizing/exits
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3340-3353
## hypothesis
Price-chart images predict returns.
## method
1.45M twenty-day images of 531 names; walk-forward over 611,451 cells from 2022; market_position with 4 sizing x 5 exit rules.
## result_numbers
IC -0.003 on the universe and +0.011 on the book; flat decile table. Top-tenth long book Sharpe 0.75. Every exit rule is worse than holding, stops most.
## verdict
closed-negative
## caveats
'There is no chart analyst.'
--- [39]
## name
Chart network on 15-minute bars; hourly reversal
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3329-3338
## hypothesis
The last 20 fifteen-minute bars predict the next hour.
## method
Snapshots at 10:30, 12:30 and 14:30, walk-forward, cross-sectional.
## result_numbers
Network IC +0.002 (0.1bp between best and worst fifth). Plain hourly reversal: t 8 over 3,486 cells, worth 3.8bp between fifths against a 6bp round trip.
## verdict
closed-negative
## caveats
'Predictable and unprofitable'. The 15-minute clock stays a risk layer.
--- [40]
## name
Stop-hunting (trade through the prior 20-session low)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3369-3374
## hypothesis
Wicks through lows are stop hunts followed by reversals.
## method
Universe since 2015, beta-adjusted, next 10 sessions.
## result_numbers
Trade-through and close back above (65,787): -0.03%. Close below (73,169): -0.02%. Wicks are 47% of such days. The same at a 12% trailing level.
## verdict
closed-negative
## caveats
Stops cost because they truncate a right-skewed path. Stop display is off by default.
--- [41]
## name
First-hour day-type reader (market_daytype)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3380-3383
## hypothesis
The first 1-3 hours classify the day (green/red, AI/software).
## method
Walk-forward against naive continuation.
## result_numbers
No reader beats a coin by more than 1-2 points; the most any captures is 3.5bp.
## verdict
closed-negative
## caveats

--- [42]
## name
Trader's dip conditions learner (market_dip)
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3405-3406, 3324-3326
## hypothesis
Learned dip conditions predict bounces.
## method
Walk-forward; rerun after purging label leakage.
## result_numbers
'No skill out of sample'; the rerun gave the same verdict.
## verdict
closed-negative
## caveats
No numeric table recorded in docs.
--- [43]
## name
Entering later than the next open after an A/A+ grade
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3434-3443
## hypothesis
Waiting after a grade upgrade gives a better entry.
## method
1,153 A/A+ arrivals.
## result_numbers
Later entry cost 0.3% one session later, 0.7% five sessions later and 1.4% ten sessions later, more after a run-up. After a 5-session +25% rise nothing predicts the turn; the worst tenth gives back a quarter within 20 sessions.
## verdict
closed-negative
## caveats
'The signal's momentum continues; the desk is not late at the open.'
--- [44]
## name
Release-text embeddings (nomic-embed) vs the five-field reader
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3540-3567
## hypothesis
Full release text carries information beyond the extracted fields.
## method
3,401 releases, 768-d vectors truncated to 2,048 tokens; ridge and trees walk-forward; 160,403 cells.
## result_numbers
h20: ridge IC 0.0133 (t 1.13, net Sharpe 0.31, fresh -0.0012); trees 0.0309 (t 1.79, 0.37, fresh -0.0164); sentiment analyst 0.0310 (t 2.17, 0.55); desk 0.0549 (t 3.37, 1.02); desk + text at 0.5 0.0590 (t 3.59, 0.83). h60 trees 0.0168 (t 0.53).
## verdict
closed-negative
## caveats
Bounded test: the embedder saw about a quarter of each release. A full-text rerun needs VLLM_EMBEDDING_MAX_MODEL_LEN=8192.
--- [45]
## name
Improving technicals (21/50 EMA turn) into earnings
## date
2026-09-07
## source_doc
docs/CHANGELOG.md:3280-3290
## hypothesis
A 21/50 EMA turn two weeks before a report carries through it.
## method
24,371 releases, 526 names, since 2016.
## result_numbers
Universe: -0.17% (t -0.9). Book: -1.38% over 20 sessions (t -2.7) and -0.55% into the print (t -2.8), in 9 of 11 years.
## verdict
closed-negative
## caveats
'The run-up is what gets sold.'
--- [46]
## name
Chart structure: swings and volume breakouts
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3165-3178
## hypothesis
Higher highs/lows and breakouts carry forward return; a volume-breakout add helps.
## method
531 names since 2016; a 3% add inside the book's rules.
## result_numbers
No structure carries return. Thin-volume breakouts fade (t -3.1). Volume breakouts +0.19% at 10 sessions (t 1.6); on the book +0.70% (t 2.4), positive only since 2023. Book Sharpe with the add: 1.78 from cash, 1.80 funded, vs 1.85.
## verdict
closed-negative
## caveats
It adds return only by adding exposure.
--- [47]
## name
Quality snapback
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3180-3195
## hypothesis
A quality name stretched below its short averages is a buy.
## method
Book since 2018.
## result_numbers
Stretched quality names = unstretched (t 0.0). With volume: +0.5%/20 (t 0.8). Stretch x turnover +0.98% (t 2.3), driven by 2022-23. Technical neutral on those cells: +31.2%/1.80 vs +31.8%/1.85 from 2021-06.
## verdict
closed-negative
## caveats
Nagel's stress-dependent reversal appears in the 5-session bounce; short-term momentum does not.
--- [48]
## name
Second valuation analyst (TTM multiples, own history, peers)
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3119-3132
## hypothesis
Richer valuation legs beat the current value analyst.
## method
market_valuation on the book, walk-forward.
## result_numbers
Own history worth nothing; finer peers no better. Growth-adjusted TTM multiple IC +0.049 (t 3.7) in sample; walk-forward +0.037 vs +0.034. Book +33.6% vs +31.8% at higher vol (+33.9% at equal vol).
## verdict
closed-negative
## caveats
The current analyst stands.
--- [49]
## name
Learned analyst combinations (market_interactions)
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3058-3068
## hypothesis
Ridge, pairwise ridge or a small net on the convictions, tape, days since report and expectations gap beats the rule.
## method
Walk-forward by year with purged labels, as tie-break and as whole selection.
## result_numbers
Rule mean IC +0.055 vs best learner +0.040. Every learner earns less in the book.
## verdict
closed-negative
## caveats

--- [50]
## name
Grade veto switched off
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3064-3068, 2798-2803
## hypothesis
Removing the bearish-core cap raises return.
## method
Scorecard.
## result_numbers
+39.5%/yr vs +35.4% (+36.2% at the rule's vol, 5 of 6 years). From 2018-06: veto off +27.4% but DD -26.0%; with the gap as well, +31.5% and -25.5%, both outside the 25% loss limit.
## verdict
closed-negative
## caveats
The veto stays.
--- [51]
## name
Earnings-expectations model and gap valuation leg (became the live rule)
## date
2026-09-08 (promoted 2026-09-10)
## source_doc
docs/CHANGELOG.md:3094-3117, 3070-3075, 2783-2807
## hypothesis
A learned pre-release revenue expectation blended into valuation beats the plain rule.
## method
Walk-forward LightGBM on 13,515 reports, 515 names, 2015-2026; run nightly as a challenger, then swapped live.
## result_numbers
Correlation +0.628 vs naive +0.531 (8 of 9 years). No post-report drift. The cheapest fifth earns +1.23% through the print (t 2.6). Book from 2018: +28.1%/yr (Sharpe 1.56) vs +23.9% (1.46). Scorecard from 2018-06: rule +25.2% (DD -23.4%) vs gap +30.3% (+27.3% at matched vol, Sharpe 1.56 vs 1.46, DD -24.6%, 7 of 9 years). From 2021-06: +38.6% vs +35.4%, a wash at matched vol, 3 of 6 years, top position 28% vs 20%.
## verdict
adopted
## caveats
Promoted on two sessions of forward record; the plain rule became the shadow. 2026-09-25 qualification: the naive accuracy/surprise reports compared log growth with simple-growth targets, so no edge over a correctly scaled baseline is established.
--- [52]
## name
Opening-auction (opg) vs queued day market orders
## date
2026-09-08
## source_doc
docs/CHANGELOG.md:3243-3254; docs/research/pick-timing-audit-2026-09-13.md:57-65
## hypothesis
Auction orders fill at the open.
## method
First live paper orders.
## result_numbers
8 of 9 opg orders expired; only SMCI filled. HPE's 201 shares missed $52.29 to $62.09 (+18.74%, about $1,969.80 gross counterfactual).
## verdict
adopted
## caveats
Switched to day market orders queued after the close.
--- [53]
## name
Selling the dead-cat bounce instead of the break
## date
2026-09-10
## source_doc
docs/CHANGELOG.md:2809-2828
## hypothesis
After a trend break, exit on the bounce.
## method
2 break definitions x 6 bounces, with and without a 10-session deadline, to cash and redeployed, inside the desk simulator.
## result_numbers
Every to-cash variant earns less than the rule. Best redeployed variant: t +1.5 of 56 tries, at double the turnover; it helps in 2022 only. Side measurements: A+ the session before a release +1.7% on the day vs C +0.2%; reaction sign persists 48.6% of the time (3,329 pairs).
## verdict
closed-negative
## caveats

--- [54]
## name
Option walls and gamma proxy (collection only)
## date
2026-09-10
## source_doc
docs/CHANGELOG.md:2830-2846; docs/NEXT_SESSION.md:6399-6406
## hypothesis
Put/call walls carry information over the 20-session horizon.
## method
Nightly Cboe delayed chains, immutable frames; walls summed across expiries to 60 days (09-16).
## result_numbers
First snapshot covered 92 of 93 names. No return test yet.
## verdict
planned-not-run
## caveats
Nothing trades on them. Needs about a quarter of snapshots.
--- [55]
## name
Exit at the close plus green-day skip
## date
2026-09-11
## source_doc
docs/NEXT_SESSION.md:8247-8268
## hypothesis
Selling market-on-close and never into a name's own opening rally beats selling at the open.
## method
Simulator over 11.66 years (2,939 sessions, 94 names).
## result_numbers
Sell at open: CAGR 25.1%, vol 16.5%, Sharpe 1.440, DD -25.7%. Exit at close alone: 24.3% / 16.8% / 1.379 / -25.5%. Exit at close + green-day skip: 36.0% / 25.6% / 1.332 / -28.4%, with 81 fewer trades and turnover 4.44.
## verdict
adopted
## caveats
The operator requested this behaviour (don't sell ETN into its rally). Higher vol and lower Sharpe are 'the honest cost'. On 09-12 the skip was aligned to open vs prior close for parity.
--- [56]
## name
FOMC pre-window selloff backtest (opencode Q1)
## date
2026-09-13
## source_doc
docs/NEXT_SESSION.md:7806-7815
## hypothesis
The book sells off before FOMC under the no-guidance regime.
## method
Book returns in pre-meeting windows.
## result_numbers
2026-07-29 cycle: book pre-window -2.84 / -0.16 / -2.82%, decision day -4.02% (SPY flat pre-window, -1.55% on the day). Sep 8-11: book -0.92% vs SPY -0.22%. 2015-2026 (282 pre-window sessions): book -6.06% annualized vs +26.53% overall.
## verdict
inconclusive
## caveats
'n is too small to wire de-risk'. Superseded by the 48-comparison study and the operator's provisional adoption.
--- [57]
## name
Earnings-release timing (opencode Q2)
## date
2026-09-13
## source_doc
docs/NEXT_SESSION.md:7816-7821
## hypothesis
The edge after bullish releases is front-loaded, so intraday action is needed.
## method
3,402 scored releases, beta-adjusted forward returns.
## result_numbers
Bullish (n=1,746): 1 session +0.14% (t 1.6), 5 sessions +0.37% (t 2.2), 10 sessions +0.67% (t 3.0), 20 sessions +1.27% (t 4.4). Neutral about 0. Bearish (n=107): -0.36% at 1 session.
## verdict
closed-negative
## caveats
The edge is not front-loaded, so intraday earnings trading is not supported. The nightly grade is the hook.
--- [58]
## name
FOMC pre-meeting 50% exposure windows (48 comparisons)
## date
2026-09-13
## source_doc
docs/research/fomc-window-evaluation-2026-09-13.md; fomc-window-evaluation-2026-09-13.json
## hypothesis
Cutting exposure 1/3/5/10 sessions before FOMC, always or only on 5-session SPY weakness, improves the book.
## method
Funded simulator, inceptions 2021-01-01 / 2026-05-22 / 2026-06-18, 10 and 25bp, next-open execution.
## result_numbers
2021 to Sep 11 2026 at 10bp, baseline CAGR 43.39%, DD -33.20% (+670.73%). 1-session always 37.09% / -31.83%; 1 weak 43.30 / -34.39; 3 always 35.40 / -34.65; 3 weak 41.71 / -34.41; 5 always 32.91 / -33.99; 5 weak 38.65 / -34.51; 10 always 32.03 / -31.13; 10 weak 33.64 / -32.36. Turnover 5.6 rises to 7.0-10.8. At 25bp: baseline 42.23 / -33.60; 3 weak 39.99 / -35.35. May 22 to Sep 11 at 10bp: baseline +0.74% (DD 8.44%); 1 always +1.12%; 3 either +1.09% (5.99); 5 +1.13% (6.61); 10 always +1.44% (5.80); 10 weak -1.22% (7.86). At 25bp, 3 weak +0.87% vs +0.62%. June 18 start, 3 weak: +1.70% vs -0.23%, DD 7.45 vs 10.59.
## verdict
closed-negative
## caveats
Every variant reduced 2021-2026 return. The recent gain rests on 2 completed meetings (1 after the guidance change). Different inceptions are not independent.
--- [59]
## name
FOMC 3-session weakness overlay (provisional live policy)
## date
2026-09-13
## source_doc
docs/NEXT_SESSION.md:7515-7549, 7504-7507, 6964-7016, 6516-6527; docs/CHANGELOG.md:2004-2019
## hypothesis
Halving held shares 3 sessions before FOMC when SPY's 5-session return is negative protects the book under the no-guidance regime.
## method
fomc-3-session-weakness/1, later /2: latches through decision day, event orders bypass green-day rules, restore at the open after.
## result_numbers
June 18 inception lifecycle: baseline -0.234% vs +1.522% (10bp); DD 10.591% vs 7.293%; at 25bp -0.359% vs +1.298%. First trigger: Sep 11 SPY -1.1485%, factor 0.5. Paper sold 136 shares (AAOI 15, AMD 4, ANET 19, LITE 1, MDB 4, NTAP 20, NVDA 12, SMCI 60, SNDK 1); cash went from 58.81% to 78.85%. Nine restoration buys were queued for the 09-17 open. Gate preview: the cut was ahead about $203 at the 09-14 close.
## verdict
adopted
## caveats
The operator's explicit choice against the long-history evidence. Judged only by the six-meeting gate. The 09-18 study's prior is that it 'costs money rather than saving it'.
--- [60]
## name
FOMC overlay gate (six meetings)
## date
2026-09-15
## source_doc
docs/research/fomc-gate-2026-09-15.md
## hypothesis
The overlay adds value after costs on untouched meetings.
## method
Exact counterfactual from paper fills. Keep if summed effect after 25bp is positive and live drawdown is not deeper in more than half of meetings.
## result_numbers
Standing: waiting, 0 of 6 at registration. Verdict due about mid-2027.
## verdict
frozen-pending
## caveats
Meetings where the rule did not fire do not count. Any parameter change restarts the count.
--- [61]
## name
A+ pick publication and execution audit
## date
2026-09-13
## source_doc
docs/research/pick-timing-audit-2026-09-13.md:1-89
## hypothesis
A+ picks performed well after publication and were executed well.
## method
Saved grades, publication times, SIP candles and broker receipts, Sep 4-11.
## result_numbers
34 A+ observations, 11 names, 10 scorable. 5 of 10 rose. Equal-weight mean +0.67% before costs, median -0.40%; SPY -0.23%, QQQ -0.39%; HPE +18.74% dominates. 34 orders: 24 filled, 8 expired, 2 probes. AAOI filled at 9:33:06 at $107.997 vs SIP 9:30 open $104.49. Holding NTAP to the close was worth +$356.40, ADBE +$230.54, PANW -$96.04. SMCI re-entry +$254.71 vs +$9.30.
## verdict
inconclusive
## caveats
One week, dependent observations. It led to persisting publication, submission and fill timestamps.
--- [62]
## name
Chart-based EMA/Bollinger entries and exits (single position)
## date
2026-09-13
## source_doc
docs/research/pick-timing-audit-2026-09-13.md:91-144
## hypothesis
Multi-timeframe EMA pullback or breakout-retest entries and structure exits improve per-pick outcomes.
## method
Pre-specified rules on 22,616 SIP bars; next-bar fills; 10bp per side; same 10 picks.
## result_numbers
First open + hold: 10/10 entered, +0.47%. First open + EMA structure exit: -1.31%. Pullback + hold: 4/10, -0.34%. Pullback + structure: -1.50%. Breakout-retest + hold: 2/10, -0.16%. Breakout-retest + structure: -0.57%. The band trim never fired first. HPE's pullback entry came at $58.17 vs the $52.29 open.
## verdict
closed-negative
## caveats
One-week sample; no re-entry or funding modelled.
--- [63]
## name
Cash-at-fill funding correction
## date
2026-09-13
## source_doc
docs/research/cash-funding-audit-2026-09-13.md; docs/research/technical-timing-next-evaluation.md:35-53
## hypothesis
The legacy simulator's returns included unmodelled borrowing.
## method
Replay 2021-01 to 2026-09-11, 72 rebalances; buys bounded by cash at fill.
## result_numbers
Legacy 10bp: +678.54%, CAGR 43.64%, DD 33.20%; negative cash in 220 of 1,429 sessions; max gross 131.79%; minimum cash -1.219944x initial equity. Cash-at-fill 10bp: +552.33%, 39.23%, 30.85%, 0 negative sessions, gross 100%. At 25bp: legacy +643.14% / 42.47% / 33.60% vs cash-at-fill +526.70% / 38.25% / 31.20%. Jun 18 to Sep 11: +2.80% / +2.54%, DD 6.61 / 6.64%.
## verdict
adopted
## caveats
This is an accounting repair, not an edge. Settlement, spread and whole-share effects are still not modelled.
--- [64]
## name
Technical exit plus confirmed re-entry in the funded portfolio (3-arm)
## date
2026-09-13
## source_doc
docs/research/technical-timing-next-evaluation.md
## hypothesis
The EMA structure exit with re-entry on recovery improves the funded strategy after costs.
## method
Pre-registered arms: production baseline; baseline entries + exit/re-entry; pullback entry + exit/re-entry. Fixed EMA periods, 10 and 25bp.
## result_numbers
Not run. No results recorded in any in-scope doc.
## verdict
planned-not-run
## caveats
Prerequisite: cash-at-fill (done). 'Do not search for a better period or profit percentage on these outcomes.'
--- [65]
## name
Daily vs 20-session rebalance cadence (funded proxy)
## date
2026-09-14
## source_doc
docs/research/intraday-funded-cadence-2026-09-14.json; docs/research/retail-decision-workflow.md:55-60
## hypothesis
Re-sizing more often (toward intraday cadence) improves returns.
## method
Funded daily-bar proxy on the reconstructed 2021-2026 universe (5.67 years).
## result_numbers
20-session at 10bp: CAGR 35.79%, Sharpe 1.664, DD -24.50%, turnover 6.10, max weight 23.9%. Daily at 10bp: 29.05%, 1.500, -25.70%, turnover 41.06. At 25bp: 20-session 34.55% / 1.616 / -24.93%; daily 21.21% / 1.153 / -28.71% (turnover 41.18).
## verdict
closed-negative
## caveats
Daily data only; not evidence about intraday or macro timing.
--- [66]
## name
Intraday + macro research candidate (intraday-macro-candidate/1)
## date
2026-09-14
## source_doc
docs/research/retail-decision-workflow.md:26-60; docs/NEXT_SESSION.md:7141-7192, 6386-6393
## hypothesis
Re-computing weights each 15-minute candle from current technical grades, with a DeepSeek inflation plus SPY-trend defensive ceiling (50%), improves outcomes.
## method
Immutable decisions per candle; three target trackers; cash-funded evaluator at 10/25bp filling at the next candle close.
## result_numbers
First fresh decision 2026-09-14 13:45Z: inflation building, SPY daily neutral, weekly positive, base budget 0.5, total targets 23.34%. Evaluation had zero observations at deployment.
## verdict
shadow
## caveats
No historical macro labels were backfilled. The strict whole-set freshness gate flips between available and unavailable (18:30 available, 18:45 not). No promotion path.
--- [67]
## name
Correlation-cap challenger (candidate version 2)
## date
2026-09-14
## source_doc
docs/research/desk-forward-evidence-2026-09-14.md:22-26; docs/NEXT_SESSION.md:6959-6962
## hypothesis
Capping correlated clusters at 30% gross reduces concentrated drawdowns.
## method
60 return observations, at least 40 in common, connected correlation >= 0.8, 30% cluster cap; weights only shrink and released exposure goes to cash.
## result_numbers
No caps binding at the first live-input check. No performance recorded.
## verdict
shadow
## caveats
'These explicit research parameters have not earned adoption.'
--- [68]
## name
FOMC restoration gated by SPY trend
## date
2026-09-14
## source_doc
docs/research/fomc-restoration-2026-09-14.md
## hypothesis
Staying reduced until SPY daily and weekly trends are non-negative times re-entry better.
## method
Funded event-lifecycle simulator, Sep 11 input cut.
## result_numbers
2021 to Sep 11 2026 at 10bp: calendar CAGR 39.86%, DD 24.80% vs trend-gated 42.50%, 27.01%. At 25bp: 38.46% / 25.18% vs 41.19% / 27.36%. Max position weight 17.5% to 24.4%. Jun 18 to Sep 11: identical, +1.52% (10bp) and +1.30% (25bp).
## verdict
closed-negative
## caveats
The return gain comes from changed rebalance timing, not demonstrated re-entry skill. Calendar restoration retained.
--- [69]
## name
Neural scorer and sequential RL allocator growth pilot
## date
2026-09-14
## source_doc
docs/research/growth-pilot-2026-09-14.md; docs/research/growth-gpu-replication-2026-09-14.md
## hypothesis
Supervised NNs or a policy-gradient RL allocator (cash / momentum / equal weight / half exposure) maximising log wealth beat simple baselines.
## method
Train 2018-23, select 2024, test Jan 2 2025 to Sep 11 2026 (423 transitions); next-close fills; 10 and 30bp.
## result_numbers
Total return at 10bp / 30bp / DD. SPY 31.19 / 30.93 / -18.76. Momentum20 357.27 / 291.58 / -38.26. Momentum120 396.68 / 365.76 / -48.13. Equal weight 129.61 / 127.03 / -33.39. NN seeds 114.75 / 79.00 / -48.02; 163.09 / 125.88 / -52.54; 183.59 / 139.92 / -53.01. RL seeds 9.00 / 0.51 / -36.22; 99.47 / 90.41 / -42.28; 201.58 / 187.11 / -22.87. Jun18-Aug27 (10bp): SPY 4.34, mom20 -2.68, mom120 -24.05, EW -0.26, NN -2.05 / -4.98 / -0.10, RL -27.94 / 2.89 / -11.20. Aug31-Sep11: SPY -0.66, mom20 -10.58, mom120 5.46, EW 1.50, NN 13.18 / 6.73 / 7.78, RL 0 / 1.50 / 2.81.
## verdict
closed-negative
## caveats
RL depends heavily on the seed. The GPU replication (bd2816c2) replayed all 12 curves exactly on CPU and CUDA from frozen tensors. The 9 post-Jackson-Hole sessions contain no FOMC decision.
--- [70]
## name
Price-sensitive supervised ML ladder (frozen fundamentals)
## date
2026-09-14
## source_doc
docs/research/opportunity-learning-2026-09-14.md
## hypothesis
Ridge, trees or a small NN on price plus 10 filed-financial ratios beats fixed rules.
## method
20-session decisions, 10% caps, train 2018-23, select 2024, test 2025-01-02 to 2026-09-11.
## result_numbers
Return at 10bp / 30bp / DD. Ridge 61.03 / 53.91 / -45.50. Trees 121.07 / 109.27 / -46.85. Neural (epoch 10) 63.72 / 55.69 / -49.75. Valuation rule 255.52 / 249.25 / -36.54. Mom20 419.01 / 384.46 / -38.31. Mom120 348.10 / 335.74 / -45.87. Equal weight 122.35 / 120.89 / -33.88. SPY 31.19 / 30.93 / -18.76.
## verdict
closed-negative
## caveats
The valuation rule's lead was later mostly shown to be a data artefact.
--- [71]
## name
ML ladder rerun on as-of (versioned) fundamentals
## date
2026-09-14
## source_doc
docs/research/opportunity-learning-asof-2026-09-14.md; fundamentals-asof-audit-2026-09-14.json
## hypothesis
The corrected filing data changes the ranking of the models and rules.
## method
Identical configuration; only the fundamental block changed.
## result_numbers
2024 validation log growth, old to new: neural 0.9083 to 0.9199; ridge 0.8851 to 0.8967; trees 0.5630 to 0.4815; valuation 0.7111 to 0.5122. Test at 10bp, old to new: neural 63.7 to 65.0 (DD -52.5); ridge 61.0 to 74.3 (-49.7); trees 121.1 to 172.4 (-44.4); valuation rule 255.5 to 150.0 (-35.7). Unchanged: mom20 419.0 (turnover 34.4); mom120 348.1; equal weight 122.4 (turnover 3.3); SPY 31.2. Excess vs equal weight: neural -57.3, ridge -48.1, trees +50.1. Audit: 3,856 restated periods; revenue differs on 31,763 of 165,791 sessions.
## verdict
closed-negative
## caveats
No learned model beats equal weight except trees. All trail 20-session momentum.
--- [72]
## name
Valuation increment and price-sensitive sizing tilt
## date
2026-09-15
## source_doc
docs/TRADING_ROADMAP.md:13-26; docs/NEXT_SESSION.md:6624-6626
## hypothesis
Valuation adds information beyond momentum and risk; a price-sensitive sizing tilt helps.
## method
Details not recorded in the in-scope docs (INFERRED: run in the 09-14/15 research branches).
## result_numbers
Valuation increment combined t = 0.05. The price-sensitive sizing candidate was indistinguishable from the rule; tilt = 0.
## verdict
closed-negative
## caveats
'Both lines are closed.'
--- [73]
## name
Post-decision reversal, FOMC meeting form
## date
2026-09-15
## source_doc
docs/research/post-decision-reversal-2026-09-15.md
## hypothesis
The book's worst 5-session decile into an FOMC decision rebounds over the next 10 sessions.
## method
Pre-registered: next-open entry, 10-session hold, beta-adjusted, 30bp bar, 45 meetings 2021-01-27 to 2026-07-29.
## result_numbers
Raw +3.83% (t 2.60, 64% positive). SPY over the same windows +1.10% (t 2.63). Beta-adjusted +1.70% (t 1.56). After 10bp +1.50% (t 1.38). After 30bp +1.10%, median -0.23%, sd 7.32%, 49% positive, t 1.01. Deep subset (18 meetings): +1.60% (t 0.74). Ex-July 2026: +0.76% (t 0.71). By year: 2021 +0.2, 2022 -1.9, 2023 +5.6, 2024 +0.5, 2025 -0.9, 2026 +4.2.
## verdict
closed-negative
## caveats
The forward shadow records from 2026-09-16. A new specification is a new registration.
--- [74]
## name
Post-decision reversal, any-day form
## date
2026-09-15
## source_doc
docs/research/post-decision-reversal-2026-09-15.md:67-132
## hypothesis
Depth, not the meeting, drives the rebound: any day the worst decile is at or below -10% over 5 sessions.
## method
95 non-overlapping episodes since 2021, same bar.
## result_numbers
Raw +3.11% (t 2.74, 61% positive). Beta-adjusted +1.84% (t 1.92). After 10bp +1.64% (t 1.71). After 30bp +1.24%, median +0.40%, sd 9.33%, 52% positive, t 1.30. Ex-July +1.17% (t 1.21). By year: 2021 +1.4, 2022 -0.9, 2023 +1.4, 2024 +1.6, 2025 +2.6, 2026 +2.0.
## verdict
closed-negative
## caveats
'The more promising of the two'. The shadow records forward. Most of the raw return is market and beta.
--- [75]
## name
Intraday timing Study 1: where in the session to trade
## date
2026-09-15
## source_doc
docs/research/intraday-timing-2026-09-15.md:14-100
## hypothesis
A print in the first hour, VWAP or the close beats the official open, unconditionally or by gap.
## method
1,413 sessions 2021-01-04 to 2026-09-04, 93 names, IEX rescaled to daily. Bar: 20bp with t > 3 on at least 200 sessions.
## result_numbers
All sessions (bp vs open at 15-min / 30-min / 60-min / 30-min VWAP / close): -0.4 / -0.0 / -0.6 / -0.1 / +2.0 (t 0.5). Gap down <= -2% (1,010): -2.2 / -0.5 / -11.0 (t -1.3) / -2.9 / -9.2. Within +-2%: -0.6 / -0.2 / -0.6 / -0.4 / +1.9. Gap up >= +2% (1,100): -8.9 (t -1.5) / -9.5 / -11.7 (t -1.4) / -6.7 / +1.4.
## verdict
closed-negative
## caveats
The flush cell (-318bp) was degenerate and discarded. 'The open stays the entry.'
--- [76]
## name
Intraday timing Study 2: which timeframe confirms a reversal entry
## date
2026-09-15
## source_doc
docs/research/intraday-timing-2026-09-15.md:35-135
## hypothesis
Waiting for a 15/30/60-minute close above the 9 EMA, or above the prior low, beats the open on reversal episodes.
## method
95 any-day and 45 meeting episodes, beta-adjusted, 30bp per side, paired vs open. Bar: +50bp paired with t > 2.
## result_numbers
Open: +1.24% any-day, +1.10% meetings. 15-min > 9 EMA: +0.74% (paired -0.51, t -0.8, 77% confirmed); meetings +0.34 (-0.76, t -1.1). 30-min: +0.64 (-0.60, t -0.9, 62%); meetings -0.27 (-1.38, t -1.7). 60-min: -0.17 (-1.41, t -1.7, 41%); meetings -0.91 (-2.01, t -2.1). 15-min above prior low: +0.63 (-0.62, t -0.9, 63%); meetings -0.29 (-1.40, t -1.8).
## verdict
closed-negative
## caveats
'By the time a bar has confirmed a turn, the move that mattered has happened.'
--- [77]
## name
Execution-quality series (drift vs slippage on paper fills)
## date
2026-09-15 / 2026-09-17
## source_doc
docs/CHANGELOG.md:1992-2002, 1272-1335
## hypothesis
Fills lose value to execution.
## method
Split each fill at the first tradable benchmark (open for queued orders, close for MOC, reference bar for intraday event cuts).
## result_numbers
September, 18 of 18 fills split. Total +115.3bp / +$454 = drift +122.2bp / +$482 + slippage -6.9bp / -$27. Buys: drift +243.1bp, slippage -9.0bp. Intraday event sells: drift 0, slippage -4.8bp. Worst slippage SNDK +95.4bp. AAOI's +438.6bp total was a +411.4bp gap.
## verdict
adopted
## caveats
This is a measurement instrument. Most cost is the overnight gap between decision and open, not execution.
--- [78]
## name
Stance persistence length and release-event votes
## date
2026-09-16
## source_doc
docs/research/persistence-length-2026-09-16.md
## hypothesis
Shorter persistence, or voting a new release immediately, beats the 3-session wait.
## method
desk.run + simulate since 2018-06-01. Bar: higher CAGR, drawdown no deeper, turnover not higher.
## result_numbers
3 sessions: CAGR 25.05%, DD -22.08%, Sharpe 1.463, turnover 5.81, 940 grade changes/yr. 2 sessions: 24.57% / -22.31% / 1.428 / 5.83 / 1,299. 1 session: 23.77% / -22.25% / 1.385 / 6.05 / 2,436. 3 + release votes: 24.34% / -22.08% / 1.428 / 5.84 / 965.
## verdict
closed-negative
## caveats
The release-event code stays on branch release-event-vote (36cccb68).
--- [79]
## name
Seven grading-input defect fixes
## date
2026-09-16
## source_doc
docs/CHANGELOG.md:1814-1830
## hypothesis
Correcting split-basis share counts, stretch ordering, benchmark leakage, level basis, gap coverage, margin route and gated rotation changes results.
## method
Plain rule from 2018-06.
## result_numbers
CAGR 25.24% to 25.05%; DD -23.4% to -22.1%; turnover unchanged; latest session DDOG C to B plus four technical stances.
## verdict
adopted
## caveats
A correctness fix, not a strategy change.
--- [80]
## name
Opportunity score as a forecast; the sharpness curve
## date
2026-09-18
## source_doc
docs/research/opportunity-and-cash-2026-09-18.md:11-42
## hypothesis
The displayed 0-10 opportunity score is an independent return signal.
## method
93 names, 2015-01-02 to 2026-09-17, 147 non-overlapping 20-session windows.
## result_numbers
Opportunity IC +0.0408 (t 2.67), quintile spread +1.26%. Without sharpness: +0.0416 (t 2.76), +1.16%. Desk score: +0.0457 (t 3.21), +1.46%. Correlation with the desk score 0.920.
## verdict
closed-negative
## caveats
It is a restatement of the desk score, and weighting both would double-count. SHARPNESS = 2.0 earns nothing.
--- [81]
## name
Cash as an opportunity / risk-off regime conditions
## date
2026-09-18
## source_doc
docs/research/opportunity-and-cash-2026-09-18.md:44-113
## hypothesis
A condition the desk already computes forecasts a bad 20 sessions for the equal-weight book.
## method
Forward 20-session equal-weight book return while each condition fires vs not, over 147 non-overlapping windows.
## result_numbers
Benchmark under a falling 21: +3.57% vs +2.40% (+1.17, t 0.70). Under its 50-day: +3.92 vs +2.29 (+1.63, t 0.94). Breadth < 40%: +3.99 vs +2.09 (+1.90, t 1.25). Top-quartile vol: +3.32 vs +2.54 (+0.78, t 0.38). Benchmark >= 5% off its high: +4.77 vs +1.89 (+2.87, t 1.66). Vol top quartile and under the 21: +2.75 vs +2.71 (t 0.02). Always invested: +2.71%.
## verdict
closed-negative
## caveats
Every risk-off condition preceded above-average returns. Only one sustained drawdown (2022) is in sample. This implies the FOMC overlay likely costs money.
--- [82]
## name
Stretch leg replacement (support distance vs signed vs band vs none)
## date
2026-09-18
## source_doc
docs/research/stretch-leg-2026-09-18.md
## hypothesis
A continuous stretch measure beats the discontinuous support-distance leg.
## method
Desk harness 2018-06 to 2026-09; quiet-session stability on production data.
## result_numbers
Support: CAGR 26.70%, Sharpe 1.448, DD -21.98%. Signed: 27.07% / 1.470 / -19.02%. Band: 26.07% / 1.407 / -20.42%. None: 27.83% / 1.493 / -20.59%. Quiet-session flips > 40 points: support 3.98% (92 of 94 names unstable, p99 66.17), signed 2.61% (89 of 94, 60.56), band 0.83% (17 of 94, 38.55).
## verdict
adopted
## caveats
Band was chosen over the higher-return 'none' for stability and interpretability. 'Signed' was briefly shipped and was wrong.
--- [83]
## name
cash-bounded-breakout-rotation/2 shared planner
## date
2026-09-20
## source_doc
docs/NEXT_SESSION.md:6051-6091, 6120-6126; docs/CHANGELOG.md:1149-1161
## hypothesis
Joint name capacity and cash-only opening buys make the historical, paper and dashboard paths agree.
## method
Shared paper planner reused in the simulator and previews; corrected historical simulation over 2,936 sessions to 2026-09-04.
## result_numbers
No return figures in the in-scope docs (artifact corrected-policy-curve.json is external). The audit reproduced a combined rotation + entry cap breach (14% to 16%). Name weights can drift above the entry cap after fills.
## verdict
adopted
## caveats
Retained the incumbent screened breakout/grade rule. /3 came later and is out of scope.
--- [84]
## name
Conditional entry timing pilot (enter / wait 1h / skip, 5-session hold)
## date
2026-09-20
## source_doc
docs/research/conditional-entry-pilot-2026-09-20.md
## hypothesis
Learned models decide better whether to enter now, wait an hour or skip for multi-day holds.
## method
Top-5 momentum20 names at 10:30 and 11:30 decisions; ridge, trees (8 / 28 inputs) and GRU; train through 2023, select 2024, test 2025 to 2026-09-04 (420 sessions, 4,082 opportunities); IEX bar-open fills.
## result_numbers
Mean daily improvement vs immediate entry at 10bp, with 95% paired block CI. Fixed 1h wait +0.769bp [-0.278, +1.954]. Ridge +0.012 [-0.819, +0.799]. Trees-8 -0.189 [-0.816, +0.426]. Trees-28 +0.234 [-0.289, +0.792]. GRU +0.142 [-0.570, +0.864]. The trees sign flips: 2025 +0.581, 2026 -0.372. Pooled returns: immediate +382.29%, wait +402.25%, trees +388.43%, GRU +386.30%, DD about -36%, exposure about 80%. With skip: trees 60.5% exposure, +192.18%, DD -30.66%; GRU 52.3%, +154.71%, -27.82%.
## verdict
closed-negative
## caveats
The strict CPU replay of the GRU failed (max diff 0.007436). Skip results are confounded by exposure.
--- [85]
## name
Ten-session fundamental context ablation
## date
2026-09-21
## source_doc
docs/research/entry-context-protocol-2026-09-21.md; docs/research/entry-context-results-2026-09-21.md
## hypothesis
Corrected point-in-time quarterly fundamentals add information to the 10-session entry-timing decision.
## method
Paired HistGBR: 28 price features vs +21 quarterly columns (7 features, 7 flags, 7 ages lagged one day); train 2020-23; report 2024 and 2025-on; 5/10/20bp.
## result_numbers
Context minus price-only at 10bp, bp/day: 2024 +0.207 [-0.067, +0.498]; 2025 to end -0.018 [-0.294, +0.262]; pooled +0.072 [-0.130, +0.269]. Vs always-enter +0.130 [-0.238, +0.471]; vs always-wait -0.078 [-0.556, +0.411]. Skip vs always-enter in the later window: -22.803 [-40.577, -6.785], exposure 56.3% vs 86.6%.
## verdict
closed-negative
## caveats
'Do not ... escalate to a larger neural model merely because the GPU is available.'
--- [86]
## name
Live fundamental-analyst input correction (as-of versioned features)
## date
2026-09-15 (shadow stage one) / 2026-09-21 (deployed c36f4a4b)
## source_doc
docs/NEXT_SESSION.md:6617-6626, 5752-5757, 5896-5901; docs/CHANGELOG.md:1130-1147; docs/research/fundamental-features-2026-09-20.md
## hypothesis
Replacing zero-filled, earliest-filed frozen features with versioned as-of features corrects grades.
## method
Nightly as-of shadow block from 09-15; independent current-data comparison on Sep 18.
## result_numbers
Sep 18: 8 grade changes, 7 target changes, one-way target turnover 2.846%; scored names 90 to 88 of 94. Value-shadow Sep 15-18: 4 / 5 / 5 / 6 grades differ; hypothetical turnover 2.98% / 5.38% / 2.99% / 5.53%.
## verdict
adopted
## caveats
A correctness change, not a return claim. 2026-09-25 note: legacy version records omit units, so whole-snapshot unit selection can undermine the temporal guarantees.
--- [87]
## name
Common-window incumbent scorecard vs SPY and QQQ
## date
2026-09-21
## source_doc
docs/NEXT_SESSION.md:5502-5513, 5318-5334, 5536-5539, 5640-5652, 5049-5055
## hypothesis
Baseline: does the incumbent meet 'beat both SPY and QQQ with no deeper drawdown'?
## method
Cached report; NAV 1; next-open; 10bp; 252-session warmup; independent SPY/QQQ accounting.
## result_numbers
2016-01-04 to 2026-09-18: incumbent CAGR 43.57%, DD 34.23%; SPY 15.07% / 33.72%; QQQ 20.07% / 35.12%. Both objectives met in 35.97% of 2,441 overlapping 252-session windows (SPY alone 37.28%, QQQ 48.18%). 2015-01-02 calendar (2,944 sessions): incumbent 44.56% / 32.01%; SPY 13.77% / 33.72%; QQQ 19.03% / 35.12%; max single-name drift 31.74%. Since 2023: incumbent DD 32.01% vs SPY 18.76% and QQQ 22.77%.
## verdict
inconclusive
## caveats
The incumbent fails the SPY drawdown objective on the full window and is far deeper since 2023. Survivor-biased and reused.
--- [88]
## name
Stock/index/cash allocation: vol and vol_trend
## date
2026-09-21 (protocol) / 2026-09-22 (results)
## source_doc
docs/research/portfolio-allocation-protocol-2026-09-21.md; docs/NEXT_SESSION.md:4788-4800, 4826-4831, 4868-4875
## hypothesis
Scaling the stock book to min(SPY, QQQ) risk, with residual SPY and an optional 200-day trend ceiling on SPY/QQQ, beats both benchmarks with less drawdown.
## method
Fixed predeclared rules: risk = max(std20, std60) x sqrt(252); 15% name cap; ceilings by minimum, never multiplied; 2016-01-04 to 2026-09-18; next open; zero cash yield.
## result_numbers
At 10bp: vol CAGR 22.01%, DD 24.59%, meets both full-window objectives but only 34.08% of rolling windows; vol_trend 16.78%, 15.30%. At 25bp: vol 20.13% vs QQQ 20.06%, rolling 25.44%. At 0bp: vol 23.2805% / 23.8314%; vol_trend 18.0976% / 14.9875%; SPY 15.0857% / 33.7173%; QQQ 20.0853% / 35.1187%; vol rolling 40.2294%; vol_trend fails QQQ return (rolling 29.4551%). Incumbent on the same window: 43.57% / 34.23%.
## verdict
closed-negative
## caveats
Not adopted: 'Reused survivor-biased history does not justify adoption.' It roughly halves CAGR vs the incumbent. Exposure-matched controls are unverified. It does not validate 15-minute entries.
## standing_constraints
ROADMAP (docs/TRADING_ROADMAP.md, 2026-09-15):
- Order of work: data correctness, then a nightly that always finishes, then measurement that cannot flatter, then execution measured, then 'Strategy last, and only by the gate'.
- 'Any change to the rule runs first as a named shadow beside it for a season, with the gate written before the first session; passing means advancing, and failing means insufficient evidence, never a retune on the same sessions' (lines 46-51).
- 'Candidates are welcome as shadows ... None is adopted on a backtest of this universe' (57-59).
- 'No new model without a specific hypothesis and an agreed evaluation budget; no tuning on 2024-2026, which every line here has now touched; no sizing change that cannot be traced to a recorded shadow's untouched sessions; and nothing that reads a private or paid data source' (74-77).
- The drawdown limit, vol target and regime exposure are kept 'unless a shadow shows better on untouched sessions' (54-56).

FROZEN GATES AND PROTOCOLS:
- FOMC gate (fomc-gate-2026-09-15.md): six completed meetings from 2026-09-16. 'Until six meetings are complete the standing is waiting ... Any change to the policy's parameters, trigger or window restarts the count at zero. No parameter is tuned on these meetings; a different rule is a new gate.' fomc_gate.py was deliberately left untouched (CHANGELOG 1292-1294).
- Reversal shadows: 'A different specification (a shorter hold, a tighter decile, a confirmation at the open, a news condition) is a new registration, not a retune'. Promotion needs the shadow's own six meetings on untouched sessions.
- ML forward spec: 'Untouched: sessions after 2026-09-11 ... Only these count as prospective.' Frozen checkpoint: 'Do not retrain, add RL, change the live allocation, or promote the network before that record exists' (NEXT_SESSION 6714-6717). A changed model or execution code must use a new ledger directory.
- Technical-timing plan: 'Do not search for a better period or profit percentage on these outcomes ... Any further parameter changes make another development experiment and require fresh forward evidence. No candidate is promoted merely for winning this sample.'
- Pre-registered bars: intraday Study 1 (>= 20bp, t > 3, >= 200 sessions); Study 2 (+50bp paired, t > 2 on both sets, or t > 2.5 on any-day); persistence (higher CAGR, drawdown no deeper, turnover not higher).

EVALUATION RULES (portfolio-exposure-objective-2026-09-21.md):
- 'outperform both SPY and QQQ in net compounded returns, with no larger peak-to-trough drawdown than either, on the SAME evaluation window. Report each comparison separately; do not choose the easier benchmark after observing results or silently average them into a blended benchmark.'
- 'Historical benchmark drawdowns ... must never enter an earlier decision as a future-informed risk threshold.'
- 'Freeze a small candidate set and its definitions before looking at outcomes; do not mine the reused 2024-2026 sample for winning thresholds.'
- Include exposure- or risk-matched comparisons. Count false exits, re-entry delay and costs. Use dividend-inclusive SPY/QQQ, identical calendars and capital. Report rolling and regime windows, worst day/week and recovery. Common evaluation start fixed at panel.dates[252], with no per-candidate start selection (NEXT_SESSION 5546-5549).
- Include a re-entry rule; risk cuts have priority over rotation and sell-deferral. No double-applied exposure cuts: 'Do not count the same rates or FOMC reduction twice.'
- No invented SWVXX or mutual-fund fills; unavailable instruments are marked unavailable.

LEARNING AND RL (desk-rl-readiness-2026-09-14.md):
- Objective is net log equity growth.
- 'Do not add a volatility penalty that silently changes the user's objective. Do not optimize hindsight-perfect entries/exits or use future highs as fill prices.'
- Chronological blocks with overlap purging. 'No live exploration or auto-promotion.'
- Conditional-entry pilot: 'Promotion requires a separate untouched forward record and a repaired production-policy replay.'
- Entry-context results: 'Do not promote this model, retune on these periods, or escalate to a larger neural model merely because the GPU is available.'

15-MINUTE AND PERSONAL-DASHBOARD RULES (NEXT_SESSION, 2026-09-22):
- 'New entry logic stays experimental until compared on identical causal data and user's zero-cost convention, with turnover/repeated signals/missed fills measured. No dashboard changes, live orders, fitting, threshold sweeps or desk.run authorized' (4733-4736).
- 'Do not invent thresholds or infer that 15-minute precision requires frequent trades' (4752-4753).
- Validate causal 15-minute triggers, invalidation, stale signals, repeat alerts and midpoint-fill assumptions before claiming readiness (4749-4752).
- 'Never turn paper fills or its rebalance clock into instructions for the user's actual portfolio' (4764-4765).
- 'Prefer HOLD when the investment case has not materially changed ... Do not copy the experimental daily resizing into personal recommendations or choose arbitrary cooldown/band thresholds without validation. Earlier measured policies turned over roughly 10-11 times NAV annually (two-way); that is a diagnostic concern' (4769-4775).
- Midpoint is a target, not a claimed fill. Measure quote-midpoint limit fills and unfilled orders (4782-4800).
- HFT addendum (4706-4709): 'transfer ordered-path ideas to 15-minute entries, without inferring true order flow from OHLCV or claiming ML/edge already exists ... no training, threshold search, data purchases, live orders or repeated daily backtests.'

MACRO (retail-decision-workflow.md):
- 'The strategy must not depend on beating the initial CPI/PPI announcement reaction.'
- 'A consensus surprise requires a real archived consensus; never fabricate it.'
- Revised histories must not be backfilled into prior decisions.
- Cash is a valid outcome.

REPO RULES:
- CLAUDE.md: 'a change that adds or alters a prompt is not complete until a functional test in backend/tests/functional/ exercises it against the real runtime.'
- Memory: ask before deploying; never bypass deploy gates.
- The frozen research ledgers and immutable desk records are preserved and never rewritten.
- The workflow task itself is read-only; no broker or market-data calls.
## operator_objectives
- 2026-09-04 (MARKET_SLICE_1_REVIEW.md:22-24): the original ask was 'structure-driven buy/sell on CRWV/IREN/SNDK, position sizing, sector rotation'.
- 2026-09-05 (NEXT_SESSION 9193-9196): 'The operator narrowed the book to the AI-infrastructure and software names he watches.'
- 2026-09-05 (NEXT_SESSION 9132-9135): the operator objected that grades ignored technical analysis 'as he practises it: location between support and resistance, multi-timeframe agreement, reward-to-risk.'
- 2026-09-06 (NEXT_SESSION 8973, 9038-9039): 'a printout is not a product'. He also asked: 'have you implemented your best solution given what you've learnt?'
- 2026-09-08 and 09-10 (CHANGELOG 3050-3056, 2798-2803): candidates were scored 'against a loss limit' of 25%. This absolute limit was superseded on 09-21.
- 2026-09-10 (CHANGELOG 2785-2787): 'the dashboard and the paper account carry the best-measured version, not a weaker one with a better-measured shadow beside it.'
- 2026-09-12 (NEXT_SESSION 7983-7985): 'The user chose whichever horizon leads to the best overall gain. Research objective: after-cost compounded returns, preserving current risk limits; compare frozen candidates on unseen periods before changing the live rule.'
- 2026-09-13 (NEXT_SESSION 7472-7473): 'timing should depend on technical structure, not fixed profit numbers.'
- 2026-09-13 (NEXT_SESSION 7610-7611, 7517-7518): 'a selloff can begin any number of days before FOMC.' The operator 'explicitly chose the three-session conditional de-risking policy and asked to judge the post-guidance period separately.'
- 2026-09-14 (desk-rl-readiness-2026-09-14.md:31; NEXT_SESSION 6846): 'maximum cumulative gain, not Sharpe, is the objective.'
- 2026-09-14 (NEXT_SESSION 7254-7256): 'current opportunities, variable share recommendations and manual recording after brokerage execution ... macro/bear-market coverage without competing on submillisecond economic-release reactions.'
- 2026-09-14 (NEXT_SESSION 6901-6902, 6912-6916): 'best current-price opportunity first, GLW as an example, and systematic stock coverage beyond user-supplied names'. He wants one table of every stock, with cash ranked as an allocation.
- 2026-09-15 (fomc-gate:49): 'Six meetings is the smallest sample the operator accepts for a decision.'
- 2026-09-20 (conditional-entry-pilot:3-4): 'entries during the session for positions held several days to a few weeks.'
- 2026-09-21 (portfolio-exposure-objective:3-8):
  - 'maximize returns by owning individual stocks at favorable prices, shifting toward cash or indexes when conditions deteriorate, and participating promptly in recoveries. The immediate concern is large losses in volatile names on bad market days. The user explicitly named SPY and QQQ as the benchmarks for both gains and drawdown limits.'
  - Drawdown tolerance: 'I'm not sure' (NEXT_SESSION 5699-5701).
  - He wants a defensive response to bear markets and unusual shocks such as COVID, including bonds or SWVXX (5682-5688).
- 2026-09-21 (NEXT_SESSION 5869): 'ugh so are we leaving it like this or are we going to make it better?'
- 2026-09-21 (NEXT_SESSION 5406-5411): the user challenged the inference that ML is unhelpful. 'Several-days/weeks objective and both SPY/QQQ benchmarks unchanged.'
- 2026-09-22 (NEXT_SESSION 4740-4741, just above the requested range): 'i told you we need precise entries on the 15 min timeframe'. Avoiding overtrading 'means rejecting weak/repeated signals and unnecessary position churn, NOT replacing 15-minute timing with daily-only entries.'
- 2026-09-22 (NEXT_SESSION 4757-4759): 'remember to avoid overtrading, this dashboard will be used by me to make buys in my portfolio. the paper trading is its own section in the dashboard'.
- 2026-09-22 (NEXT_SESSION 4781): 'forget trading costs try to hit mid price'.
- 2026-09-22 (NEXT_SESSION 4843-4844, 4916-4918): efficiency; no dashboard work before the implementation is established; credit use is a concern ('57% credits consumed and insufficient results').
- Roadmap (TRADING_ROADMAP.md:77): 'nothing that reads a private or paid data source.'
## data_blockers
UNIVERSE AND SURVIVORSHIP
- No point-in-time S&P membership and no delisted names from free sources (backend/market/universe.py:23-34). Book name choice alone is worth about 19 points a year: equal-weight book +34.2% vs the 400-name control +15.6% (CHANGELOG 3480-3490).
- Filings, tone and levels are stored only for the book (~93 names), so the sentiment and value analysts cannot be tested off-book.
- 438 of 531 daily histories lagged at 2026-09-04 (NEXT_SESSION 6811-6813). Several studies' local prices end 2026-09-04.
- QQQ was absent from the cached stock panel; it was built separately (NEXT_SESSION 5437-5443, 5801-5802).

QUOTES, FEEDS AND FILLS
- No SIP entitlement: Alpaca returns 403 for recent SIP. IEX quotes pass the gate labelled as IEX (NEXT_SESSION 6370-6376). 15-minute bars are the IEX venue only; the IEX 9:30 bar is not the consolidated open (intraday-timing:62-65).
- No timestamped bid/ask history, so a midpoint backtest is impossible. The 2026-09-22 zero-cost result is a next-open proxy (NEXT_SESSION 4783-4786).
- Missing IEX execution bars: 89 of 6,592 decisions in 2024-2026, including early-close afternoons (conditional-entry-pilot:160-170).
- No extended-hours prices without SIP (NEXT_SESSION 6354-6355).
- No queue, impact, partial-fill or settlement model. Whole-share paper fills differ from fractional historical fills. Dividend pay dates are unknown (booked as receivables). No merger, spinoff or cash-in-lieu accounting.

FUNDAMENTALS, TONE AND MACRO
- No analyst consensus history.
- The legacy fundamentals path zero-filled missing ratios and used earliest-filed values; corrected in the live desk on 2026-09-21. The 09-25 note says as-of version records omit original units.
- CPI/PPI/PCE: collection-time vintages only; no publication timestamps or archived consensus (retail-decision-workflow:14-20).
- The 2020 FOMC calendar includes unscheduled actions and lacks point-in-time cancellation metadata, so research starts in 2021.
- Earnings reaction date is an earliest bound. Release tone is nondeterministic at temperature 0, and prompt-version re-scores are data revisions.
- The expectations-gap model's naive-baseline scale is qualified as of 09-25.

FORWARD EVIDENCE AND REPRODUCIBILITY
- Option open-interest history starts 2026-09-10 (Cboe delayed).
- The forward log is tiny: 22 observations over one session, zero full point-in-time snapshots (desk-rl-readiness).
- The regime sample has only one sustained book drawdown (2022). Only 1-2 completed FOMC meetings fall under the new guidance regime.
- Cross-device GRU numerical replay failed.
## open_hypotheses
Registered or planned but not yet tested (or still accumulating) as of 2026-09-21/22:

PLANNED, NOT RUN
1. Technical exit plus confirmed re-entry inside the funded portfolio, 3 arms (technical-timing-next-evaluation.md). Its prerequisite, cash-at-fill, is done.
2. An event-conditioned entry study (breakouts, retests, thesis-preserving pullbacks) with the setup and holding/exit alternatives frozen before training (conditional-entry-pilot:148-154; NEXT_SESSION 6128-6131). Position-sizing and sequential exit/RL experiments are 'separate, unperformed work'.
3. Defensive stock/index/cash/money-market (SWVXX)/bond allocation with instrument eligibility, tested on shock, prolonged bear, inflation/rate and false-alarm scenarios, with re-entry (portfolio-exposure-objective). Exposure-matched controls for vol and vol_trend were still UNVERIFIED on 09-22.
4. HFT ordered-path ideas transferred to causal 15-minute entries (intraday_entry.py: completed-bar sequence, evolving daily candle, invalidation, stable signal identity). Not yet evaluated; it must be compared on identical causal data at zero cost, measuring turnover, repeated signals, missed fills and midpoint limit fills (NEXT_SESSION 4706-4753, 4799-4800).
5. A prospective 10-session hypothesis with true point-in-time membership and overlap purging (NEXT_SESSION 4829-4831). ML for distinct stock-relative-return, risk and execution hypotheses given adequate point-in-time data (5406-5410).
6. Roadmap stage-5 shadow candidates: the history reference alone, a sector-neutral value leg, an exit rule. Also: as-of fundamentals stage two for the value analyst; broader-universe grading beyond the 93 (531 tracked); current-price valuation (GLW example).

RECORDING FORWARD (verdict pending)
- The FOMC gate: 0 of 6, due about mid-2027.
- The any-day reversal shadow (t 1.30, positive in 5 of 6 years) and the meeting-form shadow.
- The frozen ML ledger: neural, valuation_rule, momentum20, SPY and USD at 10 and 30bp. Retraining on the as-of path, or exporting it as a second shadow, is the operator's decision.
- Ridge analyst weights kept for the forward record.
- The correlation-cap challenger.
- intraday-macro-candidate/1.
- The board-paper $100k ledger.
- Grade-outcome cohorts (20 non-overlapping cohorts needed).
- Sells at the closing auction, via close_shortfall_bps.
- Option walls over a 20-session horizon (needs about a quarter of snapshots).

NOTED AS PROMISING BUT NOT PURSUED
- Theme momentum at 60 sessions: IC 0.054, t 1.56, positive net of 10bp.
- A 10:30 entry on dip days: the only fill change worth considering (09-06).
- The volume breakout on the book: +0.70%, t 2.4, only since 2023.
- Full-text release embeddings: needs an 8192-token context.
- Tone tie-breaks tone_pricing and tone_supply_constrained (09-05 next task; status not recorded).
- The 17 names the band leg leaves unstable.
- The design of the strict whole-set freshness gate.