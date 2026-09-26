===== ledger-early
- [closed-negative] 2026-09-04 Slice-1 per-ticker neural windows (design review, never trained) :: 23 tickers x 730 days is about 11,000 overlapping windows. CRWV has about 360 bars. Labels overlap 20:1. 15/15 tests passed. No model was trained.
- [closed-negative] 2026-09-05 Learned cross-sectional rankers vs 12-1 momentum (full sweep) :: h10: momentum IC 0.015 (t 0.95, net Sharpe 0.15); mlp raw 0.015 (0.12); gru -0.005 (-0.27); xsect raw 0.012 (-0.36); mlp alpha 0.018 (t 1.30, -0.26); lgbm 0.002 (-0.67); master -0.005 (-0.70); xsect alpha -0.001 (-0.63). h5: momentum 0.020 (0.09); lgbm -0.003 (-0.92); mlp 0.017 (t 1.59, -0.10); xsect 0.013 (-0.30); master 0.012 (-0.44); 3-seed mlp 0.018 (-0.68); 3-seed xsect 0.013 (-0.61). h20: lg
- [closed-negative] 2026-09-05 Positive controls: short-horizon reversal and theme momentum :: 1-day reversal h1: IC 0.016, t 4.65, Sharpe 0.42 / -3.90. 5-day reversal h5: 0.024, t 3.16, 0.66 / -0.04. 10-day reversal h5: 0.018, t 2.40, 0.38 / -0.12. Theme reversal (20d) h10: 0.030, t 2.07, 0.14 / -0.07. Theme momentum (60d) h60: 0.054, t 1.56 over 47 periods, 0.39 / 0.36.
- [adopted] 2026-09-05 EDGAR point-in-time fundamental controls (fundamental blend) :: Post-earnings drift h20: IC 0.002 (t 0.34, net Sharpe -0.10). Revenue yoy: 0.027 (t 2.46, 0.60). Revenue qoq h60: 0.025 (t 2.24, 0.65). Gross margin: 0.020 (t 1.96, 0.53). Blend h20: 0.029 (t 3.07, 0.66). Blend h60: 0.039 (t 2.63, 0.71). Blend IC by subperiod: 0.049 (t 2.94) in 2015-18, 0.041 in 2019-21, -0.002 in 2022-24, 0.007 (t 0.34) in 2025-26.
- [closed-negative] 2026-09-05 Learned models with filing features :: Rank IC: lgbm h20 0.013; mlp h20 0.008; xsect h20 -0.008; lgbm h60 -0.044; mlp h60 -0.014; master h60 -0.010.
- [adopted] 2026-09-05 Sizing engine on the fundamental blend (inverse-vol, caps, vol target, turnover control) :: Sharpe 1.02 vs benchmark 0.83; max drawdown -15%; turnover 16% per rebalance. Tighter book (top 10%, 20% target): Sharpe 0.92, drawdown -27%.
- [closed-negative] 2026-09-05 Trader's toolkit: 33 technical features as rankers :: 52-week-low distance: h20 IC 0.041 (t 2.60, net Sharpe 1.05); h60 0.084 (t 3.45, 1.23). Extension above the 21 EMA (fade) h5: -0.022 (t -2.79, -0.94). 9/21 cross-up h5: -0.007 (t -1.79, -2.10). 50/200 golden cross h5: -0.007 (t -2.91, -0.71). 21/50 converging h20: 0.011 (t 0.94, -0.05). Candles, MACD and trend stack: about 0 with negative Sharpe.
- [closed-negative] 2026-09-05 Composite score (fundamental blend + 52-week-low trend + 21-EMA fade) :: h20 IC 0.047 (t 3.73), hit rate 0.65, net Sharpe 1.06. Book Sharpe 1.08 vs 0.92 benchmark; max drawdown -8%.
- [adopted] 2026-09-05 Theme rotation read from filings :: h20 IC 0.049 (t 2.39, net Sharpe 0.48). Theme price momentum on the same sessions: -0.036. Revenue growth as of 09-04: memory-storage 35%, networking 32%, ai-compute 29%, software 19%, power-cooling 10%.
- [adopted] 2026-09-05 DeepSeek release-tone reader (sentiment analyst) :: First reading (about 40-51 names): tone_guidance h20 IC 0.054 (t 3.68, net Sharpe 0.74); guidance change 0.052 (t 3.93); tone blend 0.062 (t 4.24, net Sharpe 1.10). The fundamental blend on the same names: 0.028 (t 1.35). Beta-adjusted: 0.044 (t 3.0) at h20 and 0.076 (t 3.8) at h60. By liquidity third: 0.048 / 0.031 / 0.026. Dropping tone lowers the desk from 0.046 to 0.038 and net Sharpe from 0.7
- [adopted] 2026-09-05 Beta-adjusted label correction :: 52-week low: 0.045 (t 2.8) to 0.005 (t 0.3). High vol: 0.037 to -0.017. Fundamental blend: 0.026 to 0.021 (t 2.3). 21-EMA fade: 0.027 to 0.024 (t 1.7). Tone blend: 0.063 to 0.044 (t 3.0) at h20 and 0.076 (t 3.8) at h60. New composite (tone added, 52-week low dropped): IC 0.032 (t 3.1); book Sharpe 1.05 vs 0.84; max drawdown -6.8%.
- [inconclusive] 2026-09-05 Calendar effects (FOMC, expiries, turn of month) :: Index at day -1: +24bp (t 1.9). High-vol minus low-vol on decision day: +41bp (t 2.4). AI basket: +32bp (t 1.9), then -29bp on day +2 and +32bp on day +3. Quad witching -41bp (t -3.1). Monthly expiry -13bp (t -2.2). Russell day 50% more volatile. Turn of month faint; December/January nothing. lgbm +calendar: h20 0.007, h5 0.005.
- [closed-negative] 2026-09-05 Macro state features (VIX, 10-year, dollar, oil) :: lgbm +macro h20: 0.005 (t < 1).
- [closed-negative] 2026-09-05 Documented anomaly controls (low vol, low beta, illiquidity, anti-lottery, balance-sheet) :: Low vol and low beta are negative (high vol +0.037 plain, -0.017 beta-adjusted). Illiquidity: +0.015 to +0.021 (t 2.6). Anti-lottery: nothing. Buybacks 0.002. Asset growth -0.015 (t -1.7). Book-to-market 0.007.
- [closed-negative] 2026-09-05 15-minute IEX session features and tape encoder as daily ranking inputs :: Preliminary, 198 names, beta-adjusted h20: bars above the 15-minute 9 EMA IC 0.029 (t 1.6); trending tape 0.026 (t 1.5); calm tape 0.015 (t 1.6, net Sharpe 0.58). At h5 every strength measure is mildly negative. Tape encoder: tape_h5 0.004 (t 0.4), tape_h20 -0.004. On the 90 book names the intraday controls 'measured zero on every session feature'.
- [adopted] 2026-09-05 Desk grade rule (fundamental/technical/sentiment/value + half-weight rotation; A+/A/B/C) :: Per 20 sessions: A+ 102bp (t 2.0), A 26, B 24, C 15. At 60 sessions: 283 / 173 / 105 / 59bp (A+ t 1.9). Graded-score IC 0.035 (t 2.3) vs composite 0.025 (t 1.8). Size multipliers 1 / 0.75 / 0.5 / 0.
- [adopted] 2026-09-05 Regime analyst: correlation novelty and participation gating :: Software/AI residual correlation: +0.19 over the decade, -0.37 in 2026, -0.52 in the latest window; novelty z +4.8. Above vs below median participation: tone IC 0.033 (t 2.2) vs -0.004; AI-vs-software leader 0.086 (t 3.0) vs -0.007; composite 0.049 (t 2.3) vs -0.002. After the top participation quintile the AI basket lags SPY by about 1.2% over 20 sessions; after the bottom it leads by 1.1%.
- [adopted] 2026-09-05 Technical analyst playbook that switches with the AI theme's trend :: 21-EMA fade while the theme falls: IC +0.082 (t 2.5); while rising: -0.006. 52-week-high proximity while rising: +0.042 (t 2.3). Momentum 120/21: +0.074 (t 2.6) in low participation. The first build lost -0.057 on 2024-2026. EMA slope and stack paid only in the 2026 low-correlation regime (+0.066 to +0.072, t 2.0, 35 windows). Buying near the 200 EMA lost in every regime (-0.023; -0.082 on 2024-20
- [closed-negative] 2026-09-05 Beta-label model rows and daily chart CNN :: lgbm alpha h20 0.008; +technical h20 0.010 and h60 0.016; +calendar 0.007; +macro 0.005; all t < 1. Chart CNN: h20 -0.001, h5 -0.012 (t -2.2).
- [adopted] 2026-09-05 Trade location (support/resistance levels) and the bearish-core veto :: Weekly trend up +1.0% (t 4.2) vs -2.0% flat. Daily trend up +0.9% (t 3.3). Top of the 60-session range +1.3% (t 3.7, hit 0.56) vs -0.5% at the bottom. More than 15% above support earns nothing, with -12% adverse excursion vs -7.6% at support. Reward-to-risk inverts: RR < 1 gives +0.7% (t 2.3). After rebuild: A+ 102bp/20 (t 1.9) and 343bp/60 (t 2.3, from 258); IC 0.031 (t 2.1) at h20 and 0.050 (t 2
- [inconclusive] 2026-09-06 Mean-reversion dip-entry claims (below 21 EMA / lower band) :: More than 8% below the 21 EMA: +1.2% in 5 sessions (t 3.5, hit 0.58). Below the lower band: +0.9% (t 2.6). Below the band while the AI basket falls: +2.1% (t 4.3, hit 0.62). By 20 sessions the dip edge is gone and more than 8% above the 21 EMA pays +2.0% (t 2.6).
- [closed-negative] 2026-09-06 Walk-forward LightGBM on all desk features (and RL declined) :: Out-of-sample IC 0.006 (t 0.4) vs the grade's 0.035 (t 2.1) on the same sessions.
- [closed-negative] 2026-09-06 Per-name trade backtest: entry triggers plus price stops :: AVGO since 2021: support stop +118%, chandelier 3 ATR +40%, no stop with slow grade exit +173%, hold +214%. NVDA: +104% / +122% / +138% / +265%. PANW: -10% / +10% / +80% / +171%. Hit rates 30-60%. Under the new defaults: AVGO +176% vs hold +214%; MU +182% vs +252%; PANW +40% vs +171%.
- [adopted] 2026-09-06 Book construction variants (vol target, top fraction, equal weight) :: Top 20% @ 15% vol: +16.1%/yr, Sharpe 1.25, DD -16.5%. Top 10% @ 25% vol: +30.9%, 1.55, -20.2%. Equal weight of all 90: +40.9%, 1.28, -38.7%. SPY: +14.3%, 0.85, -24.5%. Daily equal weight of A-or-better +47.3% (Sharpe 1.22) vs C names +42.0% (1.33). New default (top tenth, 25% vol, 15% cap): +31.6%/yr, Sharpe 1.55, DD -24.9%.
- [adopted] 2026-09-06 Defaults re-set from backtests: no price stop, 10-session grade exit, 3-session stance persistence :: Per 20 sessions: A+ 77bp (t 1.4), A 85 (t 1.7), B 10, C 18. At 60: 295 / 223 / 88 / 55. IC 0.034 (t 2.3) at h20 and 0.052 (t 2.2) at h60. Persistence cost A+ 102 to 77bp.
- [closed-negative] 2026-09-06 15-minute fill timing and entry-day structure :: Vs session VWAP: open -1.1bp; 10:30 -2.4; pullback to the 15-minute 21 EMA +1.4 (occurs on 83% of days); break of the first bar's high +0.9; close +2.5. On dip days 10:30 is 3bp under the open and the close 19bp over. The 20-session return from every fill is within noise of the open (all t < 1.1; close on dip days t -1.9). Entry day closing above the 15-minute 21 EMA: all +3.49% vs +3.01% (t 1.5);
- [closed-negative] 2026-09-06 Desk rules simulated as traded, and the band-exit overlay :: Desk rules since 2021-06: 31.6%/yr, Sharpe 1.81, DD -18.3%, vs the sizing engine alone at 31.4% / 1.55 / -23.6%. The band exit overlay costs -3.0%/yr (t -1.99) and lowers Sharpe in 5 of 6 years. Held B-or-better names beat the benchmark by 1.95% over 20 sessions; the 'band wide, price near top' trigger is followed by +3.10%. None of the 21 triggers is followed by a fall. 203 of 287 closes are repl
- [closed-negative] 2026-09-06 Tone tilt toward thin, illiquid names :: Tilt moves the desk score from 0.0459 to at best 0.0470 while lowering net Sharpe. The desk across thirds: 0.058 / 0.054 / 0.051.
- [closed-negative] 2026-09-06 Lazy Prices filing-similarity reader :: IC +0.026 (t 1.6) at h20 and +0.048 (t 1.5) at h60. As a vote: IC 0.0459 to 0.0492 but net Sharpe 0.79 to 0.58. A first look (-5.05%/120 sessions, t -12.58) was an overlap and beta artefact: non-overlapping t -1.74; beta-adjusted sign +0.38.
- [closed-negative] 2026-09-07 Better volatility forecast for sizing :: The QLIKE network beats trailing-60 by 15.5% and HAR by 7.0%. The same network on MSE is 2.9% worse. Book: trailing-60 +31.8%/yr, vol 17.2%, Sharpe 1.85, DD -19.0%, total +389.6%. QLIKE: +31.3%, 17.3%, 1.82, -18.9%, +378.2%. Rank correlation 0.854; the swap moves 8.4% of the book.
- [closed-negative] 2026-09-07 Unequal (ridge) analyst weights :: h20 IC: equal 0.0526 (t 3.30, net Sharpe 1.03); ridge shrink-1 0.0536 (t 3.59, 1.08); least squares 0.0382 (t 2.53, 0.51). h60: 0.0526 (t 1.81, 0.65) / 0.0631 (t 2.25, 0.78) / 0.0402 (t 1.39, 0.54). Weights: value 0.60, fundamental 0.50, sentiment 0.42, technical 0.38, rotation 0.30. Book from 2021-06: equal +31.8%, vol 17.2%, Sharpe 1.85, DD -19.0%; ridge +31.6%, 16.7%, 1.90, -17.8%; sentiment-le
- [closed-negative] 2026-09-07 Intraday sleeve / RL on 15-minute bars (direct-Sharpe policy, PPO, published intraday rules) :: Corrected held-out results (15,151 sessions), Sharpe at 1 / 3 / 5 / 10bp one-way. Long the session open-to-close (turnover 2.00): 0.12 / -0.27 / -0.67 / -1.64. First-half-hour momentum: -2.38 / -4.86 / -7.34 / -13.55. Hourly reversal (turnover 11.49): -3.23 / -8.48 / -13.95 / -28.74. Direct-Sharpe best seed (0.84): -0.24 / -0.89 / -1.54 / -3.16. Seed average: -0.19 / -0.98 / -1.76 / -3.73. PPO (2.
- [closed-negative] 2026-09-07 Learned intraday execution schedule (market_execution_rl) :: Pooled bps vs the open, buys / sells: close +5.31 (t 1.15) / -5.31; first hour +3.20 (t 1.73) / +0.80; direct policy +2.40 (t 2.23) / -2.18; PPO +3.17 (t 1.48) / +0.20. On the desk's own 344 orders the drift is about 10x larger; sells in the first hour -41bps (t -2.02, 57 sessions).
- [adopted] 2026-09-07 Sells at the closing auction :: Sells at the close are 24bps better than at the open (t -2.77); buys are best at the open. 4 of 5 test years agree; 2026 reads the other way on 325 orders.
- [closed-negative] 2026-09-07 Offline RL over the desk's history (critic and AWR) :: Mean reward: rule +0.611. Equal weight, whole book +0.582 (NW t -0.66). Critic +0.562 (NW t -3.49). AWR capped +0.651 (+0.040, NW t +2.62, every-20th +1.09). AWR top names +0.648 (NW +2.58, every-20th +0.57). In the full rules: Sharpe 1.52-1.54 vs the rule's 1.64, with deeper drawdown.
- [data-blocked] 2026-09-07 Survivorship / name-choice measurement :: Book +34.2%/yr (Sharpe 1.24) vs control +15.6% (0.88): 'nineteen points a year' is name choice before any signal. The technical 20-session edge is book-specific; its 60-session edge is similar on the control; momentum is nothing on either.
- [closed-negative] 2026-09-07 Allocation RL choosing book weights (REINFORCE, cross-entropy) :: Rule +0.611. Equal weight, same names +0.605 (NW t -0.46). REINFORCE +0.579 (NW -0.72). Cross-entropy +0.585 (NW -0.79).
- [closed-negative] 2026-09-07 Cross-sectional ranking-loss network ladder (market_xsect_net) :: h20: fixed grade IC 0.0530 (net Sharpe 1.03); step A 0.0537 (t 3.31, 1.00); step B 0.0052 (t 0.42, negative); B blended 0.0395. Step B at h60: 0.0137 (t 0.66). Steps C and D (87 raw features) were negative and not repeated.
- [closed-negative] 2026-09-07 Chart-image CNN (Jiang-Kelly-Xiu) and model-based sizing/exits :: IC -0.003 on the universe and +0.011 on the book; flat decile table. Top-tenth long book Sharpe 0.75. Every exit rule is worse than holding, stops most.
- [closed-negative] 2026-09-07 Chart network on 15-minute bars; hourly reversal :: Network IC +0.002 (0.1bp between best and worst fifth). Plain hourly reversal: t 8 over 3,486 cells, worth 3.8bp between fifths against a 6bp round trip.
- [closed-negative] 2026-09-07 Stop-hunting (trade through the prior 20-session low) :: Trade-through and close back above (65,787): -0.03%. Close below (73,169): -0.02%. Wicks are 47% of such days. The same at a 12% trailing level.
- [closed-negative] 2026-09-07 First-hour day-type reader (market_daytype) :: No reader beats a coin by more than 1-2 points; the most any captures is 3.5bp.
- [closed-negative] 2026-09-07 Trader's dip conditions learner (market_dip) :: 'No skill out of sample'; the rerun gave the same verdict.
- [closed-negative] 2026-09-07 Entering later than the next open after an A/A+ grade :: Later entry cost 0.3% one session later, 0.7% five sessions later and 1.4% ten sessions later, more after a run-up. After a 5-session +25% rise nothing predicts the turn; the worst tenth gives back a quarter within 20 sessions.
- [closed-negative] 2026-09-07 Release-text embeddings (nomic-embed) vs the five-field reader :: h20: ridge IC 0.0133 (t 1.13, net Sharpe 0.31, fresh -0.0012); trees 0.0309 (t 1.79, 0.37, fresh -0.0164); sentiment analyst 0.0310 (t 2.17, 0.55); desk 0.0549 (t 3.37, 1.02); desk + text at 0.5 0.0590 (t 3.59, 0.83). h60 trees 0.0168 (t 0.53).
- [closed-negative] 2026-09-07 Improving technicals (21/50 EMA turn) into earnings :: Universe: -0.17% (t -0.9). Book: -1.38% over 20 sessions (t -2.7) and -0.55% into the print (t -2.8), in 9 of 11 years.
- [closed-negative] 2026-09-08 Chart structure: swings and volume breakouts :: No structure carries return. Thin-volume breakouts fade (t -3.1). Volume breakouts +0.19% at 10 sessions (t 1.6); on the book +0.70% (t 2.4), positive only since 2023. Book Sharpe with the add: 1.78 from cash, 1.80 funded, vs 1.85.
- [closed-negative] 2026-09-08 Quality snapback :: Stretched quality names = unstretched (t 0.0). With volume: +0.5%/20 (t 0.8). Stretch x turnover +0.98% (t 2.3), driven by 2022-23. Technical neutral on those cells: +31.2%/1.80 vs +31.8%/1.85 from 2021-06.
- [closed-negative] 2026-09-08 Second valuation analyst (TTM multiples, own history, peers) :: Own history worth nothing; finer peers no better. Growth-adjusted TTM multiple IC +0.049 (t 3.7) in sample; walk-forward +0.037 vs +0.034. Book +33.6% vs +31.8% at higher vol (+33.9% at equal vol).
- [closed-negative] 2026-09-08 Learned analyst combinations (market_interactions) :: Rule mean IC +0.055 vs best learner +0.040. Every learner earns less in the book.
- [closed-negative] 2026-09-08 Grade veto switched off :: +39.5%/yr vs +35.4% (+36.2% at the rule's vol, 5 of 6 years). From 2018-06: veto off +27.4% but DD -26.0%; with the gap as well, +31.5% and -25.5%, both outside the 25% loss limit.
- [adopted] 2026-09-08 (promoted 2026-09-10) Earnings-expectations model and gap valuation leg (became the live rule) :: Correlation +0.628 vs naive +0.531 (8 of 9 years). No post-report drift. The cheapest fifth earns +1.23% through the print (t 2.6). Book from 2018: +28.1%/yr (Sharpe 1.56) vs +23.9% (1.46). Scorecard from 2018-06: rule +25.2% (DD -23.4%) vs gap +30.3% (+27.3% at matched vol, Sharpe 1.56 vs 1.46, DD -24.6%, 7 of 9 years). From 2021-06: +38.6% vs +35.4%, a wash at matched vol, 3 of 6 years, top posi
- [adopted] 2026-09-08 Opening-auction (opg) vs queued day market orders :: 8 of 9 opg orders expired; only SMCI filled. HPE's 201 shares missed $52.29 to $62.09 (+18.74%, about $1,969.80 gross counterfactual).
- [closed-negative] 2026-09-10 Selling the dead-cat bounce instead of the break :: Every to-cash variant earns less than the rule. Best redeployed variant: t +1.5 of 56 tries, at double the turnover; it helps in 2022 only. Side measurements: A+ the session before a release +1.7% on the day vs C +0.2%; reaction sign persists 48.6% of the time (3,329 pairs).
- [planned-not-run] 2026-09-10 Option walls and gamma proxy (collection only) :: First snapshot covered 92 of 93 names. No return test yet.
- [adopted] 2026-09-11 Exit at the close plus green-day skip :: Sell at open: CAGR 25.1%, vol 16.5%, Sharpe 1.440, DD -25.7%. Exit at close alone: 24.3% / 16.8% / 1.379 / -25.5%. Exit at close + green-day skip: 36.0% / 25.6% / 1.332 / -28.4%, with 81 fewer trades and turnover 4.44.
- [inconclusive] 2026-09-13 FOMC pre-window selloff backtest (opencode Q1) :: 2026-07-29 cycle: book pre-window -2.84 / -0.16 / -2.82%, decision day -4.02% (SPY flat pre-window, -1.55% on the day). Sep 8-11: book -0.92% vs SPY -0.22%. 2015-2026 (282 pre-window sessions): book -6.06% annualized vs +26.53% overall.
- [closed-negative] 2026-09-13 Earnings-release timing (opencode Q2) :: Bullish (n=1,746): 1 session +0.14% (t 1.6), 5 sessions +0.37% (t 2.2), 10 sessions +0.67% (t 3.0), 20 sessions +1.27% (t 4.4). Neutral about 0. Bearish (n=107): -0.36% at 1 session.
- [closed-negative] 2026-09-13 FOMC pre-meeting 50% exposure windows (48 comparisons) :: 2021 to Sep 11 2026 at 10bp, baseline CAGR 43.39%, DD -33.20% (+670.73%). 1-session always 37.09% / -31.83%; 1 weak 43.30 / -34.39; 3 always 35.40 / -34.65; 3 weak 41.71 / -34.41; 5 always 32.91 / -33.99; 5 weak 38.65 / -34.51; 10 always 32.03 / -31.13; 10 weak 33.64 / -32.36. Turnover 5.6 rises to 7.0-10.8. At 25bp: baseline 42.23 / -33.60; 3 weak 39.99 / -35.35. May 22 to Sep 11 at 10bp: baselin
- [adopted] 2026-09-13 FOMC 3-session weakness overlay (provisional live policy) :: June 18 inception lifecycle: baseline -0.234% vs +1.522% (10bp); DD 10.591% vs 7.293%; at 25bp -0.359% vs +1.298%. First trigger: Sep 11 SPY -1.1485%, factor 0.5. Paper sold 136 shares (AAOI 15, AMD 4, ANET 19, LITE 1, MDB 4, NTAP 20, NVDA 12, SMCI 60, SNDK 1); cash went from 58.81% to 78.85%. Nine restoration buys were queued for the 09-17 open. Gate preview: the cut was ahead about $203 at the 0
- [frozen-pending] 2026-09-15 FOMC overlay gate (six meetings) :: Standing: waiting, 0 of 6 at registration. Verdict due about mid-2027.
- [inconclusive] 2026-09-13 A+ pick publication and execution audit :: 34 A+ observations, 11 names, 10 scorable. 5 of 10 rose. Equal-weight mean +0.67% before costs, median -0.40%; SPY -0.23%, QQQ -0.39%; HPE +18.74% dominates. 34 orders: 24 filled, 8 expired, 2 probes. AAOI filled at 9:33:06 at $107.997 vs SIP 9:30 open $104.49. Holding NTAP to the close was worth +$356.40, ADBE +$230.54, PANW -$96.04. SMCI re-entry +$254.71 vs +$9.30.
- [closed-negative] 2026-09-13 Chart-based EMA/Bollinger entries and exits (single position) :: First open + hold: 10/10 entered, +0.47%. First open + EMA structure exit: -1.31%. Pullback + hold: 4/10, -0.34%. Pullback + structure: -1.50%. Breakout-retest + hold: 2/10, -0.16%. Breakout-retest + structure: -0.57%. The band trim never fired first. HPE's pullback entry came at $58.17 vs the $52.29 open.
- [adopted] 2026-09-13 Cash-at-fill funding correction :: Legacy 10bp: +678.54%, CAGR 43.64%, DD 33.20%; negative cash in 220 of 1,429 sessions; max gross 131.79%; minimum cash -1.219944x initial equity. Cash-at-fill 10bp: +552.33%, 39.23%, 30.85%, 0 negative sessions, gross 100%. At 25bp: legacy +643.14% / 42.47% / 33.60% vs cash-at-fill +526.70% / 38.25% / 31.20%. Jun 18 to Sep 11: +2.80% / +2.54%, DD 6.61 / 6.64%.
- [planned-not-run] 2026-09-13 Technical exit plus confirmed re-entry in the funded portfolio (3-arm) :: Not run. No results recorded in any in-scope doc.
- [closed-negative] 2026-09-14 Daily vs 20-session rebalance cadence (funded proxy) :: 20-session at 10bp: CAGR 35.79%, Sharpe 1.664, DD -24.50%, turnover 6.10, max weight 23.9%. Daily at 10bp: 29.05%, 1.500, -25.70%, turnover 41.06. At 25bp: 20-session 34.55% / 1.616 / -24.93%; daily 21.21% / 1.153 / -28.71% (turnover 41.18).
- [shadow] 2026-09-14 Intraday + macro research candidate (intraday-macro-candidate/1) :: First fresh decision 2026-09-14 13:45Z: inflation building, SPY daily neutral, weekly positive, base budget 0.5, total targets 23.34%. Evaluation had zero observations at deployment.
- [shadow] 2026-09-14 Correlation-cap challenger (candidate version 2) :: No caps binding at the first live-input check. No performance recorded.
- [closed-negative] 2026-09-14 FOMC restoration gated by SPY trend :: 2021 to Sep 11 2026 at 10bp: calendar CAGR 39.86%, DD 24.80% vs trend-gated 42.50%, 27.01%. At 25bp: 38.46% / 25.18% vs 41.19% / 27.36%. Max position weight 17.5% to 24.4%. Jun 18 to Sep 11: identical, +1.52% (10bp) and +1.30% (25bp).
- [closed-negative] 2026-09-14 Neural scorer and sequential RL allocator growth pilot :: Total return at 10bp / 30bp / DD. SPY 31.19 / 30.93 / -18.76. Momentum20 357.27 / 291.58 / -38.26. Momentum120 396.68 / 365.76 / -48.13. Equal weight 129.61 / 127.03 / -33.39. NN seeds 114.75 / 79.00 / -48.02; 163.09 / 125.88 / -52.54; 183.59 / 139.92 / -53.01. RL seeds 9.00 / 0.51 / -36.22; 99.47 / 90.41 / -42.28; 201.58 / 187.11 / -22.87. Jun18-Aug27 (10bp): SPY 4.34, mom20 -2.68, mom120 -24.05,
- [closed-negative] 2026-09-14 Price-sensitive supervised ML ladder (frozen fundamentals) :: Return at 10bp / 30bp / DD. Ridge 61.03 / 53.91 / -45.50. Trees 121.07 / 109.27 / -46.85. Neural (epoch 10) 63.72 / 55.69 / -49.75. Valuation rule 255.52 / 249.25 / -36.54. Mom20 419.01 / 384.46 / -38.31. Mom120 348.10 / 335.74 / -45.87. Equal weight 122.35 / 120.89 / -33.88. SPY 31.19 / 30.93 / -18.76.
- [closed-negative] 2026-09-14 ML ladder rerun on as-of (versioned) fundamentals :: 2024 validation log growth, old to new: neural 0.9083 to 0.9199; ridge 0.8851 to 0.8967; trees 0.5630 to 0.4815; valuation 0.7111 to 0.5122. Test at 10bp, old to new: neural 63.7 to 65.0 (DD -52.5); ridge 61.0 to 74.3 (-49.7); trees 121.1 to 172.4 (-44.4); valuation rule 255.5 to 150.0 (-35.7). Unchanged: mom20 419.0 (turnover 34.4); mom120 348.1; equal weight 122.4 (turnover 3.3); SPY 31.2. Exces
- [closed-negative] 2026-09-15 Valuation increment and price-sensitive sizing tilt :: Valuation increment combined t = 0.05. The price-sensitive sizing candidate was indistinguishable from the rule; tilt = 0.
- [closed-negative] 2026-09-15 Post-decision reversal, FOMC meeting form :: Raw +3.83% (t 2.60, 64% positive). SPY over the same windows +1.10% (t 2.63). Beta-adjusted +1.70% (t 1.56). After 10bp +1.50% (t 1.38). After 30bp +1.10%, median -0.23%, sd 7.32%, 49% positive, t 1.01. Deep subset (18 meetings): +1.60% (t 0.74). Ex-July 2026: +0.76% (t 0.71). By year: 2021 +0.2, 2022 -1.9, 2023 +5.6, 2024 +0.5, 2025 -0.9, 2026 +4.2.
- [closed-negative] 2026-09-15 Post-decision reversal, any-day form :: Raw +3.11% (t 2.74, 61% positive). Beta-adjusted +1.84% (t 1.92). After 10bp +1.64% (t 1.71). After 30bp +1.24%, median +0.40%, sd 9.33%, 52% positive, t 1.30. Ex-July +1.17% (t 1.21). By year: 2021 +1.4, 2022 -0.9, 2023 +1.4, 2024 +1.6, 2025 +2.6, 2026 +2.0.
- [closed-negative] 2026-09-15 Intraday timing Study 1: where in the session to trade :: All sessions (bp vs open at 15-min / 30-min / 60-min / 30-min VWAP / close): -0.4 / -0.0 / -0.6 / -0.1 / +2.0 (t 0.5). Gap down <= -2% (1,010): -2.2 / -0.5 / -11.0 (t -1.3) / -2.9 / -9.2. Within +-2%: -0.6 / -0.2 / -0.6 / -0.4 / +1.9. Gap up >= +2% (1,100): -8.9 (t -1.5) / -9.5 / -11.7 (t -1.4) / -6.7 / +1.4.
- [closed-negative] 2026-09-15 Intraday timing Study 2: which timeframe confirms a reversal entry :: Open: +1.24% any-day, +1.10% meetings. 15-min > 9 EMA: +0.74% (paired -0.51, t -0.8, 77% confirmed); meetings +0.34 (-0.76, t -1.1). 30-min: +0.64 (-0.60, t -0.9, 62%); meetings -0.27 (-1.38, t -1.7). 60-min: -0.17 (-1.41, t -1.7, 41%); meetings -0.91 (-2.01, t -2.1). 15-min above prior low: +0.63 (-0.62, t -0.9, 63%); meetings -0.29 (-1.40, t -1.8).
- [adopted] 2026-09-15 / 2026-09-17 Execution-quality series (drift vs slippage on paper fills) :: September, 18 of 18 fills split. Total +115.3bp / +$454 = drift +122.2bp / +$482 + slippage -6.9bp / -$27. Buys: drift +243.1bp, slippage -9.0bp. Intraday event sells: drift 0, slippage -4.8bp. Worst slippage SNDK +95.4bp. AAOI's +438.6bp total was a +411.4bp gap.
- [closed-negative] 2026-09-16 Stance persistence length and release-event votes :: 3 sessions: CAGR 25.05%, DD -22.08%, Sharpe 1.463, turnover 5.81, 940 grade changes/yr. 2 sessions: 24.57% / -22.31% / 1.428 / 5.83 / 1,299. 1 session: 23.77% / -22.25% / 1.385 / 6.05 / 2,436. 3 + release votes: 24.34% / -22.08% / 1.428 / 5.84 / 965.
- [adopted] 2026-09-16 Seven grading-input defect fixes :: CAGR 25.24% to 25.05%; DD -23.4% to -22.1%; turnover unchanged; latest session DDOG C to B plus four technical stances.
- [closed-negative] 2026-09-18 Opportunity score as a forecast; the sharpness curve :: Opportunity IC +0.0408 (t 2.67), quintile spread +1.26%. Without sharpness: +0.0416 (t 2.76), +1.16%. Desk score: +0.0457 (t 3.21), +1.46%. Correlation with the desk score 0.920.
- [closed-negative] 2026-09-18 Cash as an opportunity / risk-off regime conditions :: Benchmark under a falling 21: +3.57% vs +2.40% (+1.17, t 0.70). Under its 50-day: +3.92 vs +2.29 (+1.63, t 0.94). Breadth < 40%: +3.99 vs +2.09 (+1.90, t 1.25). Top-quartile vol: +3.32 vs +2.54 (+0.78, t 0.38). Benchmark >= 5% off its high: +4.77 vs +1.89 (+2.87, t 1.66). Vol top quartile and under the 21: +2.75 vs +2.71 (t 0.02). Always invested: +2.71%.
- [adopted] 2026-09-18 Stretch leg replacement (support distance vs signed vs band vs none) :: Support: CAGR 26.70%, Sharpe 1.448, DD -21.98%. Signed: 27.07% / 1.470 / -19.02%. Band: 26.07% / 1.407 / -20.42%. None: 27.83% / 1.493 / -20.59%. Quiet-session flips > 40 points: support 3.98% (92 of 94 names unstable, p99 66.17), signed 2.61% (89 of 94, 60.56), band 0.83% (17 of 94, 38.55).
- [adopted] 2026-09-20 cash-bounded-breakout-rotation/2 shared planner :: No return figures in the in-scope docs (artifact corrected-policy-curve.json is external). The audit reproduced a combined rotation + entry cap breach (14% to 16%). Name weights can drift above the entry cap after fills.
- [closed-negative] 2026-09-20 Conditional entry timing pilot (enter / wait 1h / skip, 5-session hold) :: Mean daily improvement vs immediate entry at 10bp, with 95% paired block CI. Fixed 1h wait +0.769bp [-0.278, +1.954]. Ridge +0.012 [-0.819, +0.799]. Trees-8 -0.189 [-0.816, +0.426]. Trees-28 +0.234 [-0.289, +0.792]. GRU +0.142 [-0.570, +0.864]. The trees sign flips: 2025 +0.581, 2026 -0.372. Pooled returns: immediate +382.29%, wait +402.25%, trees +388.43%, GRU +386.30%, DD about -36%, exposure ab
- [closed-negative] 2026-09-21 Ten-session fundamental context ablation :: Context minus price-only at 10bp, bp/day: 2024 +0.207 [-0.067, +0.498]; 2025 to end -0.018 [-0.294, +0.262]; pooled +0.072 [-0.130, +0.269]. Vs always-enter +0.130 [-0.238, +0.471]; vs always-wait -0.078 [-0.556, +0.411]. Skip vs always-enter in the later window: -22.803 [-40.577, -6.785], exposure 56.3% vs 86.6%.
- [adopted] 2026-09-15 (shadow stage one) / 2026-09-21 (deployed c36f4a4b) Live fundamental-analyst input correction (as-of versioned features) :: Sep 18: 8 grade changes, 7 target changes, one-way target turnover 2.846%; scored names 90 to 88 of 94. Value-shadow Sep 15-18: 4 / 5 / 5 / 6 grades differ; hypothetical turnover 2.98% / 5.38% / 2.99% / 5.53%.
- [inconclusive] 2026-09-21 Common-window incumbent scorecard vs SPY and QQQ :: 2016-01-04 to 2026-09-18: incumbent CAGR 43.57%, DD 34.23%; SPY 15.07% / 33.72%; QQQ 20.07% / 35.12%. Both objectives met in 35.97% of 2,441 overlapping 252-session windows (SPY alone 37.28%, QQQ 48.18%). 2015-01-02 calendar (2,944 sessions): incumbent 44.56% / 32.01%; SPY 13.77% / 33.72%; QQQ 19.03% / 35.12%; max single-name drift 31.74%. Since 2023: incumbent DD 32.01% vs SPY 18.76% and QQQ 22.7
- [closed-negative] 2026-09-21 (protocol) / 2026-09-22 (results) Stock/index/cash allocation: vol and vol_trend :: At 10bp: vol CAGR 22.01%, DD 24.59%, meets both full-window objectives but only 34.08% of rolling windows; vol_trend 16.78%, 15.30%. At 25bp: vol 20.13% vs QQQ 20.06%, rolling 25.44%. At 0bp: vol 23.2805% / 23.8314%; vol_trend 18.0976% / 14.9875%; SPY 15.0857% / 33.7173%; QQQ 20.0853% / 35.1187%; vol rolling 40.2294%; vol_trend fails QQQ return (rolling 29.4551%). Incumbent on the same window: 43.
===== ledger-recent
- [closed-negative] 2026-09-22 Funded vol / vol_trend allocation (GPT), fixed evaluation at 10 bp plus predeclared 25 bp stress :: 10 bp CAGR / maxDD / share of rolling 252-session windows meeting both objectives:
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
- vol a
- [closed-negative] 2026-09-22 Zero-cost / midpoint-target rerun of vol and vol_trend :: CAGR / maxDD:
- vol 23.2805% / 23.8314%
- vol_trend 18.0976% / 14.9875%
- SPY 15.0857% / 33.7173%
- QQQ 20.0853% / 35.1187%

vol meets both full-window objectives and 40.2294% of overlapping 252-session windows. vol_trend fails QQQ's return (rolling 29.4551%).
- [adopted] 2026-09-23 Incumbent sizing: live-like hold-20 vs next-session deployment of idle cash (A vs A1/A2), independent proxy backtest :: Full 2016-26 CAGR / maxDD / Sharpe / average exposure / turnover per year:
- A live-like 26.32% / 33.74% / 1.20 / 61.5% / 9.38
- A1 deferred next-day buy 31.65% / 42.63% / 1.15 / 82.0% / 13.49
- A2 recycle proceeds (upper bound) 31.05% / 42.95% / 1.13 / 83.7% / 13.42

2016-20 CAGR / DD:
- A 21.17% / 20.59%
- A1 25.17% / 33.86%
- QQQ 24.44% / 28.54%

2021-26 CAGR / DD:
- A 32.12% / 35.34%
- A1 32.9
- [shadow] 2026-09-23 QQQ 200-session trend brake with hysteresis (0.97/1.02, halve the book, released half to cash) — A3 :: Claude harness:
- A3 full: 29.92% CAGR / 31.64% DD / Sharpe 1.18 / exposure 74.5% / turnover 12.97
- vs A1: 31.65% / 42.63%
- A3 2016-20: 21.97% / 29.66% (QQQ 24.44%)
- A3 2021-26: 32.46% / 31.30%

Learned-price study, 10 bp, 2019-03-26..2026-09-21:
- momentum120_fixed_brake 63.1% / -44.7% / Sharpe 1.32
- momentum120 70.5% / -46.6%
- Holdout return 28.8% for both

At 25 bp: 60.9% / -45.0% vs 68.2%
- [closed-negative] 2026-09-23 Trend brake with the released half parked in QQQ instead of cash — A3q :: - A3q full: 31.96% CAGR / 42.66% DD / Sharpe 1.15 / exposure 84.1%
- vs A1: 31.65% / 42.63%
- vs A3 (to cash): 29.92% / 31.64%
- 2016-20: 26.60% / 31.01%
- 2021-26: 33.11% / 39.66%
- [closed-negative] 2026-09-23 Volatility cap at 1.25x QQQ volatility on A1 — A4, and GPT vol/vol_trend inside the same proxy harness :: Full 2016-26 CAGR / DD / Sharpe / exposure:
- A4 24.73% / 42.02% / 1.04 / 74.7%
- GPT vol as built 17.22% / 33.58% / 1.03 / 51.3%
- GPT vol_trend as built 14.75% / 23.49% / 1.14 / 40.2%
- SPY 15.33% / 33.72%
- QQQ 20.44% / 35.05%
- [inconclusive] 2026-09-23 vol_trend re-parameterised: QQQ-relative budget plus hysteresis :: Full 2016-26 CAGR / DD / Sharpe / exposure:
- QQQx1.5 + SPY residual 24.85% / 30.67% / 1.11 / 74.9%
- QQQx2, no residual 26.22% / 30.35% / 1.12 / 67.5%
- as built + hysteresis 14.51% / 21.74% / 1.10 / 40.1%

The QQQx2 variant ran 20.38% in 2016-20 (QQQ 24.44%) and 28.94% in 2021-26.
- [closed-negative] 2026-09-23 Daily green/red rotation between the volatile book and QQQ (operator idea), plus conditional hit rates :: Full CAGR / DD / Sharpe / turnover per year:
- QQQ buy-and-hold 20.44% / 35.05%
- always in book 31.10% / 43.02% / 1.13 / 13.4
- green stay, red to QQQ -1.77% / 53.25% / 0.05 / 214.5
- red in, green to QQQ 1.70% / 57.60% / 0.19 / 210.0
- QQQ above 10d mean 18.64% / 39.04% / 0.83 / 75.3
- volatility spike to QQQ 24.84% / 45.31% / 0.97 / 30.6
- book above +2 sigma to QQQ 30.56% / 43.02% / 1.11 / 14.
- [adopted] 2026-09-23 Claude review code findings on the incumbent and GPT's funded path :: Defects found:
- (2) Personal board repeats Buy every 15 minutes, 1.8-7% each, until the 15% cap.
- (3) Whole-share funded path: risk_cut rounds sells up, giving 608 reversals in 250 sessions (funded_execution.py:470/642).
- (4) Idle cash from close-fill sells costs about 5 CAGR points in the proxy.
- (5) Buys need a 0.5% minimum trade but sells have none: exposure 0.886 against a 0.90 target and 
- [frozen-pending] 2026-09-22 15-minute entry engine reclaim_above_level/1 and its frozen comparison protocol :: 80 tests (39 entry cases). No historical outcomes scored under the full protocol: the earliest archived eligibility (09-08) matures on 2026-10-06, after the 09-18 cache end.
- [data-blocked] 2026-09-22 15-minute cache price-basis compatibility audit and provider reconciliation :: Scale:
- Median absolute difference 0.0280%; 99th percentile 9.8341%.
- AVGO median ratio 9.9964 (max 10.0342)
- WRB median 1.4998 (upper percentile 2.2523)
- APTV median 0.8471
- BNY, FTV and WDC also discrepant.

Cache coverage:
- bars_15m/asof=2026-09-20: 530 files, 19,871,542 rows, 2019-01-02..2026-09-18, extended hours included.
- SPY/QQQ intraday absent. MSTR lacks a daily file.
- [inconclusive] 2026-09-23 Fixed single-source conditional entry diagnostic (reclaim vs incumbent) :: Coverage:
- 204 opportunities; 170 ready; 34 unavailable (WRB)
- both entered 0; incumbent only 5; candidate only 1; neither 164
- 126 repeated readiness readings deduplicated to 6 events

Incumbent entries (20-session / 5-session return):
- AVGO 08-04 -9.9617% / +1.3151%
- AVGO 08-05 -13.2245% / -1.7956%
- AVGO 08-06 -16.1556% / -1.9377%
- SPY 08-04 -0.4220% / +0.7405%
- SPY 08-05 -1.4780% / -0.5
- [adopted] 2026-09-23 Incumbent 15-minute price-rule parity validation :: 26/26 passed; band equal to within 1e-12 at six developing closes. Threshold boundary: raw close 248.6416 gives band 1.10 and fires. Raw and adjusted scale are equivalent.
- [inconclusive] 2026-09-23 Intraday turnover and missed-opportunity acceptance review :: - 40 polls of one prefix give 1 event.
- Three consecutive sessions with the same reclaim path give 3 candidate events: cross-session repeat entry is unconstrained.
- The personal Buy aggregate is capped at available cash exactly (3000). Sale proceeds never fund buys. Add-ons after a fill are bounded only by cash and the name cap.
- [shadow] 2026-09-23 Learned rank and brake kernels (learned_policy.py) as named shadow-only policies :: Adoption table (CAGR, DD, Sharpe, rolling QQQ win, turnover, 10/25 bp, halves): every cell 'Unverified'. Local bar archive has 14 asof vintages, 2026-09-05..2026-09-22.
- [closed-negative] 2026-09-23 OpenCode fc703b0 rank_features / rank_ranker / rank_brake groundwork :: - ATR on a flat adjusted series (10) with raw high/low 101/99 gives 9.1 (price-basis error).
- A pure 10:1 split produces a forward label of -0.9.
- The label is own next-open to D+10 close, not the registered SPY-relative t+11 open.
- The fold helper does not enforce chronology or a purge.
- The brake uses fixed thresholds.
- 60 owned tests pass anyway.
- [shadow] 2026-09-24 Prospective learned-input capture and causal archive-to-model bridge :: - Dry build on the 09-23 record: 95 rows, 95 complete bars, 89 tone records, 82 earnings-yield features.
- Live check 2026-09-24 01:14 UTC: 16 sessions, 15 bar vintages, 0 captures, 0 rank and 0 brake scores (expected: the capture shipped after the 09-23 nightly).
- [closed-negative] 2026-09-24 Retrospective price-only HGB learned ranker and learned brake study :: 10 bp CAGR / DD / Sharpe / turnover per year / rolling wins vs SPY / vs QQQ / holdout return:
- momentum120 70.5% / -46.6% / 1.35 / 9.33 / 82.6% / 82.2% / 28.8%
- learned_rank 48.7% / -57.9% / 1.10 / 19.48 / 75.2% / 73.5% / 6.0%
- m120 + learned brake 68.9% / -44.6% / 1.38 / 9.50 / 84.5% / 80.4% / 17.3%
- learned_rank + learned brake 47.7% / -53.1% / 1.12 / 18.88 / 75.2% / 70.0% / -1.6%
- m120 + f
- [closed-negative] 2026-09-24 Causal regime decomposition of the saved HGB-study curves :: At 10 bp, learned rank's mean daily log excess over momentum120 is negative in all four bins: -2.13, -2.92, -18.74 and -15.92 bp. The last bin has 37 intervals over 5 months.
- [shadow] 2026-09-24 Frozen nightly neural shadow ledger audit and 09-23 mark reconstruction :: Return through the 09-22 mark, 10 bp / 30 bp:
- neural 15.84% / 15.60%
- valuation rule 12.01% / 11.78%
- momentum20 -0.20% / -0.40%
- SPY 2.46% / 2.26%
- cash 0%

ARM contributed 3.65 pp, GLXY 2.20, CRDO 1.92. The 09-23 reconstruction at 10 bp: neural +14.94%, valuation +10.49%, momentum20 +0.98%, SPY +1.72%.
- [data-blocked] 2026-09-24 Neural comparison readiness audit: price/share-basis defect in frozen features and prior retrospective numbers :: Prior retrospective, 2025-01-02..2026-09-11, 10 bp, next close:
- neural +63.7% / DD -49.7%
- momentum20 +419.0% / DD -38.3%
- retrained versioned-fundamentals net +65.0%

Defect: a 10:1 split vintage gives sales yield 0.4 vs 4.0, a ln(10) error in log sales yield.
- [closed-negative] 2026-09-24 Price-only neural ranking substituted into the live rule (neural-price-rule-20260924) :: 10 bp total return / CAGR / DD / Sharpe / annual turnover:
- live-rule reconstruction 399.9% / 157.9% / -31.7% / 2.26 / 16.36x
- neural 242.2% / 106.3% / -37.1% / 1.84 / 20.80x
- equal weight 134.7% / 65.3% / -33.5% / 1.61 / 0.95x
- SPY 31.7% / 17.6% / -18.8%
- QQQ 41.4% / 22.6% / -22.8%

25 bp: live rule 380.4% / 152.0% / -32.2%; neural 226.8% / 100.8% / -37.4%; equal weight 134.1% / 65.0%.

Neur
- [inconclusive] 2026-09-24 Chronological stability of preserved /3 and neural accounts :: Incumbent at 10 bp by block, with SPY and QQQ:
- 2025-08-13 -> 11-11: 74.38%; SPY 6.20%, QQQ 7.23%
- 11-11 -> 2026-02-12: 25.84%; SPY 0.04%, QQQ -3.24%
- 02-12 -> 05-14: 46.41%; SPY 10.12%, QQQ 19.99%
- 05-14 -> 08-14: 16.82%; SPY 4.03%, QQQ 1.68%

/3 beats both in 4/4 blocks at both costs. Neural beats the incumbent only in block 4.

Evaluated regimes: 113 above/high, 127 above/low, 12 below/high
- [frozen-pending] 2026-09-24 incumbent-neural-rank-blend/1-research (equal percentile-rank blend of incumbent and price-only neural) :: None. The code path (backend.market.neural_policy_comparison, neural_study_metrics) is implemented and tested (33 and 85 tests); it does not itself start a run.
- [planned-not-run] 2026-09-24 Fixed 50/50 neural/momentum blend control before any learned scenario selector :: Not run.
- [closed-negative] 2026-09-24 Price-only nested ridge allocation gate (stock basket / SPY / QQQ / cash), frozen market study :: 10 bp ending wealth / CAGR / closing maxDD / annual gross trading:
- gate 4.0584x / 23.32% / -35.47% / 14.71x
- no-gate adapter 7.9186x / 36.29% / -32.57% / 8.21x
- /3 22.3868x / 59.23% / -37.33% / 13.65x
- SPY 2.5843x / 15.27% / -33.72%
- QQQ 3.4719x / 20.47% / -35.12%
- equal weight 11.2780x / 43.70% / -36.98% / 4.04x

25 bp:
- gate 3.4763x / 20.50% / -36.50%
- no-gate 7.3015x / 34.65% / -33.59%
- [closed-negative] 2026-09-25 Gate forecast-skill and decision/fill attribution audit :: Squared-error skill vs training mean: stock -6.46%, SPY -14.89%, QQQ -15.35%.

Declared modes: 750 stock, 561 QQQ, 348 cash, 25 SPY; 75 switches. Average closing exposure at 10 bp: stocks 30.80%, QQQ 33.06%, SPY 1.14%, cash 35.01%.

Over 348 cash-target intervals: QQQ up 185 / down 163; SPY up 187 / down 159 / tied 2.
- [closed-negative] 2026-09-25 Frozen /3 journal attribution (drawdown exposure and gain concentration) :: - Worst closing DD -37.33% / -37.58%: peak 2025-01-23, trough 2025-04-08, recovered 2025-09-05.
- Average exposure in that drawdown: stocks 89.56%, cash 10.44%. SPY 0% throughout; no QQQ position.
- SNDK, DELL, LITE, MU and NVDA supply 66.91% / 68.00% of net gain.
- Largest single-name closing weight: DELL 31.60% / 31.85%.
- [planned-not-run] 2026-09-24 Ex-ante stock-selection plus exposure-selection challenger (operator's clarified objective) :: Not implemented.
- [planned-not-run] 2026-09-25 15-minute microstructure review and a registered-later range/volume entry veto/delay hypothesis :: - Mesfin: 947 sessions. The London 15-minute control is N=247, +4.09 points, T=4.30. One extra bar of delay gives -2.91 points, T=-2.78. None of 14 signal families passes all gates.
- TradeFM: spread Wasserstein 0.400 vs Hawkes 0.302 vs zero-intelligence 0.375; 15-60 minutes is simulation duration, not a trading horizon.
- Allocation gate losses: 10/14 folds at 10 bp and 11/14 at 25 bp.
- [data-blocked] 2026-09-25 Intraday baseline-revaluation data scope for funded /3 vs SPY/QQQ at 15-minute marks :: - 77 symbols; 19,316 symbol-session cells; 426 sparse held ranges.
- 2020-01-07..2026-09-18: 500,440 regular-session bars including 12 early closes.
- 481,124 interior cells and 18,901 closing anchors.
- Missing SPY/QQQ account for 3,368 cells.
- Scope file SHA256 7f55f84e...
- [planned-not-run] 2026-09-22 Prospective 10-session stock-relative ML forecast specification :: Not run.
- [frozen-pending] 2026-09-24 Recorded Dip vs incumbent breakout entry-evidence capture (prospective) :: Deployed in aa15c03 (4541 backend tests passed). The first ordinary receipt is UNVERIFIED.
- [inconclusive] 2026-09-24 AAOI incident review and current entry-signal census :: - Paper fills: 09-11 $107.997097, 09-22 $107.51375, 09-23 $106.70.
- AAOI band 0.08867 on 09-22 and 0.12304 on 09-23, both below the 1.1 threshold even with an assumed A+.
- After repair, entry coverage is 94/95, and all 93 valid readings are below 1.10: zero Buy opportunities at that time.
- [adopted] 2026-09-24 Live grade key mismatch and missing held-mark valuation bugs :: - decision_view read 'grade' but the key is 'grade_live': six causal upgrade/downgrade cases failed, then fixed.
- A missing held mark produced a false -15.00% loss and a +17.65% rebound (eight failing cases). Now rejected; curves carry the complete-held-marks-v1 tag and older backtest metrics are withheld.
- [adopted] 2026-09-24 Expectations-gap historical asof cutoff leakage :: Under a fixed historical cutoff, appending a later partition changed:
- tone 0.25 -> -0.75
- log P/S 0.530628 -> -0.855666
- market cap 680 -> 1360
- gap close 11 -> 91
All four gap reads received asof=None.
- [adopted] 2026-09-25 Earnings-feature publication timing defect :: An 11:00 ET release was assigned to the 16:00 feature row: the feature moved 0.1823215634 -> 0.5877866745 as the target moved 0.2 -> 0.8. The pre-open control stayed at 0.2006706893. Corrected source passes 191 tests.
- [inconclusive] 2026-09-25 Expectations naive-baseline unit defect and missing-growth zero-fill :: The naive baseline compared log growth with simple growth: 0.693147 vs 1.0, about 30.685 pp of artificial error. Missing, zero, negative and absent-denominator growth all collapse to feature 0.
- [data-blocked] 2026-09-25 Current SEC source qualification and stale-tag fundamentals :: - 12 of 94 CIKs arrive as padded strings; the old parser refused them.
- 376 cells: 337 finite margins, 39 missing.
- Of the 337 finite margins, 96 reference periods at least 365 days old, 93 at least 730 days and 80 at least 1,825 days.
- AAPL margins reference 2018-06-30. ORCL Revenues ends 2022-05-31 (44 quarters beat 37 current). AMZN gross margin references 2009-09-30.
- All 175,009 rows lack
- [adopted] 2026-09-25 Connected margin period-date correction (fundamentals-features/2) :: 238 backend tests and 214 browser cases pass. The old period-mismatch xfail now passes.
- [data-blocked] 2026-09-25 Unit-preserving fundamental sources and period-compatible ratio helper :: - A future EUR append erased an earlier USD trailing revenue (460 -> missing).
- ASML: 647 rows (487 EUR, 102 EUR/share, 58 shares).
- Full raw-backed historical reimport FAILED: no raw payloads were retained, and 0 of 4,511 accessions match earnings-event clocks.
- [data-blocked] 2026-09-24 Historical evidence importer (three-name SEC cohort demonstration) :: - 720 sessions and 2,160 rows: 1,975 present, 179 unavailable, 6 absent.
- 0 complete-feature rows: all 8,640 feature cells are unavailable.
- TWTR terminal: $54.20 cash entitlement, unfunded.
- [data-blocked] 2026-09-25 Historical opportunity-set coverage audit and fja05680/sp500 membership source qualification :: - Spark: 5,556 bar files, 550 stems (the extra 13 are ETFs, not exited stocks); 18,436 dividends and 179 splits; no delisting fields.
- fja05680: 2,720 rows from 1996-01-02 to 2026-08-18. From the 2014-12-24 seed: 771 tickers, 268 absent from today's 503. The 125 add/remove rows for 2019-26 reconcile internally.
- HRS removal on 2019-06-01 contradicts S&P's 06-24 release.
- [inconclusive] 2026-09-25 Legacy allocation RL (market_allocation_rl) policy-gradient cancellation :: The implemented loss L = -A*sum(w.detach()*log p) has gradient dL/dz = 0 (residuals 3.2e-08 in float32, 8.2e-17 in float64). The growth RL pilot was seed-sensitive, lost to momentum controls and lacked QQQ.
- [adopted] 2026-09-25 Intraday research policy fingerprint omission (regime module) :: Source caps 0.75 and 0.25 gave target weights 0.1125 and 0.0375 under identical policy hashes. The real forward report pooled them.
- [data-blocked] 2026-09-25 Extended-hours feed qualification and single historical SIP sample :: Live probes: SIP 403; IEX 200 with a 0.104 s quote age; BOATS 403; free overnight 200 but over 7 hours old.

SIP sample for 09-24: 3,316 minute bars (bars observed out of 240 premarket and 180 postmarket minutes):
- SPY 893 (228/240, 125/180)
- QQQ 915 (240, 135)
- AAOI 663 (128, 46)
- ORCL 845 (167, 144)

Algo Trader Plus ($99/month) is the documented route to real-time SIP.
- [data-blocked] 2026-09-25 Options OI 'walls' audit :: - Raw $100 against adjusted $98 gave -3.061% / +7.143% distances instead of ±5%.
- A 09-01 chain was still accepted on 09-25.
- One malformed expiry reverted two names to evening grades.
- Method: expiries 1-60 days, strikes within ±25%, at least 500 contracts.
- [adopted] 2026-09-24 Research evaluation infrastructure (adapter, journal, nested runner, scorecards, diagnostics) :: Suites: 526; 292; 674; 1,096; 1,178; and 1,215 tests passing at successive checkpoints.
- [closed-negative] 2026-09-15 PRE-WINDOW REFERENCE: intraday timing (open vs first hour; 15/30/60-minute reversal confirmation) :: Open to later reference (bp): 15-minute close -0.4, 30-minute -0.0, 60-minute -0.6, session close +2.0. Gap-ups fade about 10 bp, not significant.

Reversal confirmation vs open entry (paired):
- 15-minute close above 9-EMA: -0.51% (t -0.8)
- 30-minute: -0.60%
- 60-minute: -1.41% (t -1.7)
- close above prior low: -0.62%
- on meeting days, 60-minute: -2.01% (t -2.1)
- [closed-negative] 2026-09-20 PRE-WINDOW REFERENCE: conditional entry-timing pilot (enter / wait 1h / skip; ridge, HGB, GRU) :: Mean daily improvement vs immediate entry:
- fixed one-hour wait +0.769 bp [-0.278, +1.954]
- ridge +0.012
- trees, 8 inputs -0.189
- trees, 28 inputs +0.234 [-0.289, +0.792]
- GRU +0.142

Allowing skip: trees 60.5% exposure, +192.18%, DD -30.66%; immediate entry +382.29%, DD -35.99%.
- [closed-negative] 2026-09-21 PRE-WINDOW REFERENCE: ten-session context experiment (corrected quarterly features for timing) :: Context minus price-only, pooled +0.072 bp/day [-0.130, +0.269]. Skip vs always-enter in the later window: -22.803 bp/day [-40.577, -6.785], at 56.3% vs 86.6% exposure.
