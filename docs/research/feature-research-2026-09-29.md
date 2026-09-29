# Feature and training research for the retrain (2026-09-29)

Research only: no feature code, no model trained, no live change. This is the
input to the pre-registration of the retrain the operator asked for after the
2026-09-27/28 deep-learning trials. It answers four questions, in order: what
did the models actually see (section 0); what do day traders use and what does
the published evidence say about it (sections 1 and 2); what exactly should be
computed, when it is known, and which decision it can inform (section 3); and
what to predict and how to train and judge it so that a result means something
(sections 4 and 5). Section 6 gives the priors, including the ones the operator
will not like.

Branch `research/feature-catalogue`, from `main` `8c918c4a`.

## How to read this

- **Evidence grades.** **A** = peer-reviewed, with out-of-sample or
  post-publication evidence that survives realistic costs in a relevant market
  and horizon (for volatility inputs: out-of-sample forecast gains). **B** =
  mixed: peer-reviewed but in-sample only, before costs, in another asset class
  (FX, futures, index), only in small or illiquid stocks, or contested by later
  work; also strong unpublished working papers. **C** = practitioner folklore:
  definitions in trading books and education sites, vendor or educator
  backtests (including unreviewed SSRN papers written by trading-education
  authors), no independent out-of-sample evidence.
- **↓** marks evidence that the effect decayed after publication or disappeared
  after costs.
- **Decisions.** E = entry fill timing, X = exit or trim fill timing, S =
  selection across names, Z = sizing, R = regime or exposure.
- Repo numbers are cited by file or document. Unless a document says
  otherwise they are in-sample or on the survivor universe, and are quoted as
  leads, not evidence.

---

## 0. Summary

1. **The operator is right about the deep sequence models, and it is
   checkable in the code.** The 2026-09-27/28 CNN and PatchTST could not see
   levels at all. Overnight gaps were dropped from the 60-session bar sequence:
   slot 0 is anchored on the session open
   (`backend/market/session_anatomy.py:113-118`), so 59 of 60 overnight moves
   are missing and no price path or level can be rebuilt from the inputs.
   Volume entered only as a share of its own session, so relative volume was
   invisible. The CNN's receptive field is 29 bars, about 1.1 sessions, and is
   followed by global mean and max pooling, which removes position. PatchTST
   averages its embeddings across channels
   (`backend/market/deep_intraday_patchtst.py:95`), so it could not form the
   name's return minus SMH's. There was no time-of-day normalization, although
   the first bar carries 22-26% of the day's variance. Training was fixed: 20
   epochs, no early stopping, one seed. Details are in §0.1.
2. **He is wrong that the daily technicals were never tried.** The 33-column
   technical set was already fed to learners in early September: EMAs
   9/21/50/200, SMA200, slopes, stack, crosses, weekly EMAs, 52-week high and
   low, candles and MACD, together with the 11 level features. LightGBM and MLP
   sweeps reached rank IC 0.010-0.019 at 20 sessions, t < 1.2. A replica of the
   Jiang-Kelly-Xiu chart CNN scored -0.001 at 20 sessions and -0.012 at 5 (t
   -2.2). `hgb_desk` returned 17.0% against 27.7% for equal weight of every
   point-in-time member. A 28-feature intraday entry pilot, with VWAP distance,
   relative volume, bands and EMAs, gained +0.23 bp a day with a confidence
   interval spanning zero. Missing inputs do not explain those failures.
3. **Technical trading rules on indices stopped working after the 1980s.** The
   best of 7,846 rules was significant on 1897-1986 and not on 1987-1996
   ([STW 1999](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)).
   No rule showed positive performance on 1962-2011 even at zero cost
   ([Bajgrowicz-Scaillet 2012](https://access.archive-ouverte.unige.ch/access/metadata/c0c2aa38-f0bf-430e-b994-dbe8bb53fb13/download)).
   The Bollinger buy-minus-sell daily return spread fell from 0.454% before
   1983 to 0.002% after 2002
   ([Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)).
   Candlestick rules added nothing on DJIA stocks
   ([Marshall-Young-Rose 2006](https://mro.massey.ac.nz/bitstreams/cf13fcfc-21d5-4e4b-89b6-d4f8cf347a84/download)).
4. **Technical information does survive in the cross-section, at 1-12 month
   horizons.** The documented cases are momentum
   ([JT 1993](https://econpapers.repec.org/RePEc:bla:jfinan:v:48:y:1993:i:1:p:65-91)),
   residual momentum
   ([Blitz-Huij-Martens 2011](https://econpapers.repec.org/RePEc:eee:empfin:v:18:y:2011:i:3:p:506-521)),
   the 52-week high
   ([George-Hwang 2004](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html)),
   moving-average distance (about 9% value-weighted alpha that survives
   institutional costs,
   [Avramov-Kaplanski-Subrahmanyam 2021](https://econpapers.repec.org/RePEc:wly:revfec:v:39:y:2021:i:2:p:127-145)),
   the trend factor
   ([Han-Zhou-Zhu 2016](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html)),
   and ML on the price path, which is strong among the largest 500 stocks
   ([Murray-Xia-Xiao 2024](https://ideas.repec.org/a/eee/jfinec/v153y2024ics0304405x2400014x.html)).
   That supports selection. It does not support intraday timing.
5. **Chart CNNs work mostly in small stocks and rotate most of the portfolio
   each month.** Jiang, Kelly and Xiu's 20-day model has an equal-weight
   long-short Sharpe of 2.16 but only 0.49 value-weighted, with 173-181% monthly
   turnover. It was trained with Adam at 1e-5, batch 128, early stopping after
   two epochs without improvement and a five-network ensemble
   ([JKX 2023](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf)).
   The repo's replica departed from that recipe on every one of those points
   (§2.2).
6. **Intraday predictability in large caps exists but lasts minutes, not 15-minute bars.** In the S&P 100, returns
   were predictable only over the next ~3 minutes, and a 10 ms delay cut R²
   from 14% to 2.5%
   ([Aït-Sahalia et al. 2022](https://www.nber.org/system/files/working_papers/w30366/w30366.pdf)).
   One-minute cross-stock predictors are sparse and short-lived
   ([Chinco-Clark-Joseph-Ye 2019](https://ideas.repec.org/a/bla/jfinan/v74y2019i1p449-492.html)).
   Half-hour periodicity loses money after spreads
   ([Heston-Korajczyk-Sadka 2010](https://www.bauer.uh.edu/departments/finance/documents/Heston-Korajczyk-Sadka-jf-2010-01-07.pdf)).
7. **The one intraday effect with peer-reviewed support is market-level
   late-day momentum.** For SPY 1993-2013 the slope is t 4.08 with an
   out-of-sample R² of 1.4%
   ([Gao-Han-Li-Zhou 2018](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf)).
   Across 60+ futures in 1974-2020 it is present only when dealers are short
   gamma
   ([Baltussen et al. 2021](https://academicweb.nd.edu/~zda/intramom.pdf)). An
   unreviewed practitioner measurement finds it flat on 2022-2026 SPX
   ([firmtape](https://dev.to/firmtape/intraday-momentum-is-dead-in-the-0dte-era-we-measured-it-on-1085-spx-sessions-43g0)).
   Re-measure it on our own SPY SIP bars before registering anything on it.
8. **The day-trading staples have no peer-reviewed evidence on large-cap single
   names.** That covers opening-range breakouts (ORB), VWAP, floor and
   Camarilla pivots, volume profile, "market structure" and TICK. The ORB and
   VWAP papers are unreviewed SSRN work by a trading educator's group. In the
   ORB paper the edge came from relative-volume stock selection across 7,000
   names: unfiltered ORB returned 29% in total at Sharpe 0.48
   ([summary](https://danfin.net/opening-range-breakout-research),
   [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)).
   Retail day-trading outcomes are uniformly bad. Fewer than 1% of Taiwanese
   day traders were predictably profitable
   ([Barber et al. 2014](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html)).
   97% of persistent Brazilian day traders lost money
   ([Chague et al.](https://ideas.repec.org/p/spa/wpaper/2019wpecon47.html)).
   The FTC settled with Warrior Trading
   ([FTC](https://www.ftc.gov/news-events/news/press-releases/2022/04/federal-trade-commission-cracks-down-warrior-trading-misleading-consumers-false-investment-promises)).
9. **The entry-timing floor can hardly be reached by timing alone.** The `/4`
   book placed 758 orders in the 2,012 sessions of 2016-2023, 0.38 a session,
   at about 5-9% of NAV each (`docs/research/scorecards/ml_entry_level.json`).
   To add +2 bp a day over `dip_or_close`, a timing model must gain 59-106 bp
   on every order in 2016-2023 and 85-152 bp in 2024-2026. That is a third to
   two thirds of the 186-235 bp session standard deviation. The measured dip
   fill earned -8.7 and +36 bp per filled dip. Register a per-fill diagnostic
   next to the book floor (§5.3).
10. **Selection needs roughly doubled information.** At 8-10% cross-sectional
    dispersion over 20 sessions and a top-12-of-60 selection intensity of 1.4,
    +2 bp a session needs an incremental 20-session rank IC of about 0.03-0.04
    after turnover. The grade measured about 0.035 in-sample; trees on
    technicals reached 0.010-0.019.
11. **Build first**, for the entry and exit switch: gap-aware, level-relative
    intraday state. That means distance to VWAP, prior-day high/low/close and
    the opening range; relative volume by slot; returns normalized by slot; the
    name against its sector; and SPY's first and 12th half-hours.
12. **For selection**, add the slow cross-sectional features that are
    A-graded and missing today: MAD 21/200, the trend-factor moving-average
    set, capital-gains overhang, the overnight/intraday split and "tug of war",
    MAX, 12-1 residual momentum, realized semivariance and skewness, and a
    connected-firm momentum proxy.
13. **Targets are in the decision's own units.** For entry: close price against
    trigger price on sessions where the trigger fires. For the late-day switch:
    close against the 15:30 price. For selection: 20-session open-to-open
    return against the point-in-time equal weight, rank-normalized per date.
    Bounce-or-break at a level is a diagnostic, not a decision test.
14. **Protocol.** LightGBM is the primary baseline (8-config grid, early
    stopping, 5-seed ensemble). The JKX CNN is run exactly as published (2
    configs, 5-seed ensemble). A sequence model with the §0.1 defects fixed
    gets 8 configs, early stopping and 5 seeds. Walk forward on an expanding
    window, purge equal to the label horizon, embargo 5 sessions, and nest the
    validation on the last 252 sessions of each training window. **44 trials
    are registered.** The deflated Sharpe is reported at N = 44 and at the book's
    cumulative ~274, where the expected best null t is about 2.9.
15. **Honest prior: the likeliest outcome is RECORD again.** P(the selection
    overlay passes its gate) is about 10%. P(the entry switch passes the book
    floor) is about 3%. P(any honest pass) is about 12-15%. The information
    that moved this book's results so far came from filings and release tone,
    not from charts (NEXT_SESSION 2026-09-05: tone blend IC 0.044, t 3.0).

### 0.1 Premise audit: what every learner on this book actually saw

| Date | Study (where recorded) | Model | Inputs | Target | Universe | Result |
|---|---|---|---|---|---|---|
| 09-05 | Trader's toolkit, one feature at a time (`docs/NEXT_SESSION.md` 2026-09-05 afternoon) | none (feature as the ranking) | the 33 columns of `technical.technical_features` | 5/20/60-session residual return | 532 names since 2015 (survivors) | 52-week-low distance IC 0.041 at 20 sessions, 0.005 beta-adjusted; 21-EMA stretch fade -0.022 at 5 sessions (t -2.79); 9/21 cross -0.007, golden cross -0.007; candles, MACD, stack about 0 |
| 09-05 | Model sweep (same entry, `sweep_beta.tsv`) | LightGBM, MLP, cross-sectional net | 31 `alpha.alpha_features` + 33 technical (+ EDGAR, calendar, macro) | residual rank, 5/10/20/60 | 503-532 names | LightGBM +technical 0.019 at 20 sessions (t 1.12), 0.033 at 60 (t 1.22); with the beta label 0.010 and 0.016, t < 1 |
| 09-05 | Chart CNN (`backend/market/chart_cnn.py`) | JKX 20-day image CNN | 64×60 OHLC + MA + volume images | above-median residual return | same | IC -0.001 at 20 sessions, -0.012 at 5 (t -2.2) |
| 09-05 | Tape encoder (`backend/market/tape.py`) | 1-D conv over 5 sessions × 26 slots + daily MLP | IEX 15-minute bars | beta residual, 5 and 20 sessions | same | 0.004 (t 0.4) and -0.004 |
| 09-05/06 | IEX session features (`alpaca.session_features`) | none | VWAP trend, first/last hour, reversal, bars above 15-min EMA9, EMA crosses, range position, volume front-load | 20 sessions | 90 names | "measured zero on every session feature"; close above the 15-min EMA21 on an entry day, t 1.5-1.7 |
| 09-20 | Conditional entry pilot (`docs/research/conditional-entry-pilot-2026-09-20.md`) | ridge, histogram GBM on 8 and 28 features, GRU | 28 inputs incl. `distance_vwap`, `relative_volume`, band width and position, EMA distances, wicks, time (`backend/market/entry_pilot.py`) | enter now vs wait one hour, 5-session hold | 94 current names (survivors), IEX | trees (28) +0.234 bp/d [-0.289, +0.792]; GRU +0.142 [-0.570, +0.864]; "no robust timing improvement" |
| 09-24 | Learned price study (`learned-price-results-2026-09-24.md`) | gradient-boosted ranker | price features | ranking | current book (survivors) | lost to momentum120 at twice the turnover |
| 09-26 | Point-in-time arms (`pit-arms-2026-09-26.md`) | `hgb_rank`, `hgb_desk` | price features; desk evidence incl. MA distances and slopes, range position, trend states, reward-to-risk (`learned_arm.py`) + alpha + regime, all ranked per date | top 10 at 10% | point-in-time book | 12.6% (t -3.2 vs EW) and 17.0% (t -1.75), against EW-PIT 27.7% and every A/A+ at equal weight 29.9%. The top-10 construction itself trails holding every member, so this mixes signal with construction |
| 09-27 | Deep stage 1 (`deep-intraday-stage1-2026-09-27.md`) | ridge, TCN, PatchTST, Chronos + ridge | 5 sessions × 26 bars × (return, volume share, range) + gap, 20-session return and volatility | next-session open-to-close rank; next-session variance | point-in-time, SIP | IC 0.011-0.015 on 2016-2023, ≤ 0 on 2024-2026 for 3 of 4; volatility R² 0.27 (CNN) |
| 09-27 | Deep stage 2 (`deep-stage2-2026-09-27.md`) | TCN, PatchTST, pretrained PatchTST + probe | 60 × 26 × (name 3 channels + SPY/QQQ/SMH returns) + 20 scalars | rank, downgrade20, drawdown20, vol20 | point-in-time, SIP | drawdown20 IC 0.09-0.15 (t 5-9); downgrade AUC 0.58-0.63; decision tests -1.6 to -2.3 bp/session |
| 09-27/28 | Vol sizing, profit taking, ML entry level | the CNN forecasts as inputs to rules | — | — | point-in-time | every variant RECORD |

**Structural blind spots of the 2026-09-27/28 deep models**, each checked in
the code:

1. **No overnight gaps in the sequence.** `bar_returns` anchors slot 0 on the
   session's own open (`backend/market/session_anatomy.py:113-118`), and the
   exports stack those per session (`backend/market/deep_intraday.py:328-358`,
   `backend/market/deep_stage2.py:314-322`). Only session t's gap is a scalar
   (`deep_intraday.SCALARS`, `deep_stage2.FIXED_SCALARS`). A cumulative sum of
   the sequence is therefore not the price path. That matters here because
   the book's 2024-2026 return came overnight: +7.6 bp gap against -0.4 bp
   open-to-close per session (`session-anatomy-2026-09-27.md`).
2. **No relative volume.** Volume entered as its share of the session
   (`deep_intraday.CHANNELS = ("bar_return", "volume_share", "range")`), which
   sums to 1 every day. A session at three times normal volume looks the same
   as a quiet one.
3. **No price levels.** Every input is a return. The only level-relative input
   in stage 2 was `band_z`. Nothing measured distance to VWAP, the prior day's
   high/low/close, the opening range, an EMA, a swing level or the 52-week high.
4. **The CNN had no position information.** The TCN uses kernel 5 with
   dilations 1, 2, 4, a receptive field of 1 + 4·(1+2+4) = 29 steps, then mean
   and max pooling over all 1,560 steps (`backend/market/deep_intraday_cnn.py:92`).
   It cannot tell whether a pattern happened in the last hour or 50 sessions
   ago, and cannot compare today's close with any multi-session level.
5. **PatchTST lost channel identity.** Patches are channel-independent and the
   embedding is averaged over patches and then over channels
   (`deep_intraday_patchtst.py:95`). Name-minus-SMH relative strength cannot be
   formed.
6. **No time-of-day normalization.** Each channel was standardized globally over
   all steps (`deep_intraday_cnn._standardizer`), while the 09:30 bar carries
   22-26% of the day's squared returns (session anatomy, table A). The opening
   bar dominates the loss. Intraday periodicity has to be removed before
   modelling
   ([Andersen-Bollerslev 1997](https://www.sciencedirect.com/science/article/abs/pii/S0927539897000042)).
7. **Context stopped at 60 sessions.** The 200-day average, 52-week range,
   weekly EMA21 and 120-session momentum reached stage 2 only through the desk
   scalars.
8. **Training was fixed.** Adam 1e-3, 20 epochs, no validation set, no early
   stopping, one seed (`deep_stage2_nn.py` docstring). The same seed gave IC
   0.0081 to 0.0125 across reruns (`deep-intraday-stage1-2026-09-27.md`).
9. **Stage 1's primary target is never traded.** The next-session open-to-close
   rank is not a quantity the policy trades: it holds about 20 sessions and
   fills by dip-or-close.

**What this means.** The operator's diagnosis holds for the deep sequence
models. They never had a fair chance at levels, gaps, relative volume or
multi-timeframe context. It does not hold as an explanation of the whole
record. Tree models and a JKX-style CNN were given the daily EMAs, Bollinger
position, weekly trend, 52-week high and low, swing levels and MACD. An
intraday pilot was given VWAP distance and relative volume. None found a
tradable edge. The retrain therefore has to *test* the hypothesis that
level-relative, gap-aware, relative-volume inputs add decision value. It cannot
assume it.

---

## 1. Day-trading and swing strategy survey

The context that decides relevance:

- **Universe.** 94 point-in-time names: large and mid-cap semiconductor,
  software and AI infrastructure.
- **Book.** Long only, about 11-12 names at about 9% each.
- **Orders.** About 0.3-0.4 a session.
- **Data.** 15-minute SIP bars covering the regular session and the closing
  auction, with no pre-market.
- **Live board.** Timing shows only when BUY lights: on a completed 15-minute
  bar closing at least 1% under the open, otherwise at the close
  (NEXT_SESSION 2026-09-28).

### 1.1 Opening-range breakout (ORB)

- **Technicals.** The opening range is the high and low of the first N minutes:
  5 in Zarattini-Barbon-Aziz, 15/30/60 in common use
  ([Crabel 1990](https://openlibrary.org/books/OL1611959M/Day_trading_with_short_term_price_patterns_and_opening_range_breakout)).
  Crabel's book also defines the NR7 compression day, a range narrower than
  each of the previous six
  ([Oxford Strat](https://oxfordstrat.com/trading-strategies/nr7/)).
  Entry is a stop order beyond the range, the stop at the opposite side or 10%
  of ATR14, and the exit at the close. The "stocks in play" filter is opening
  relative volume of at least 100% above normal, the top 20 by relative volume,
  price above $5 and ATR above $0.50
  ([summary](https://danfin.net/opening-range-breakout-research),
  [QuantConnect](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)).
- **Evidence.**
  - Zarattini-Barbon-Aziz (SSRN 2024, not peer reviewed): 7,000+ US stocks,
    2016-2023; the top 20 stocks in play reached 1,637% total, Sharpe 2.81,
    36% annual alpha ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)).
    Base ORB without the relative-volume filter returned 29% in total at Sharpe
    0.48. The edge is the selection, not the breakout
    ([summary](https://danfin.net/opening-range-breakout-research)).
  - A QuantConnect reimplementation reached Sharpe 2.40 on 2016 with no cost
    analysis ([QuantConnect](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/)).
  - The QQQ ORB paper enters on the first candle's direction rather than a
    breakout: 676% total, Sharpe 1.13, 24% win rate, assuming no slippage and 4×
    leverage ([summary](https://danfin.net/opening-range-breakout-research)).
  - Peer-reviewed: crude-oil futures 1983-2011 with a 61-62% success rate at
    the 1% threshold
    ([Holmberg-Lönnbark-Lundström 2013](http://www.econ.umu.se/ueslpnr/ues845.pdf)).
- **Repo.** Not built. With 15-minute bars the finest opening range is 15
  minutes.
- **Verdict.** C for large-cap single names (B for commodity futures).
  Relevance to this book is the relative-volume conditioning variable, not ORB
  as a strategy: a fixed 94-name list rarely contains "stocks in play".

### 1.2 VWAP reversion and VWAP trend (and anchored VWAP)

- **Technicals.** Session VWAP = cumulative(volume × typical price) /
  cumulative(volume) from 09:30, typical price = (H+L+C)/3
  ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap)).
  The trend version goes long above VWAP and short below. The reversion version
  fades stretches beyond VWAP ± kσ. Anchored VWAP starts from an event such as
  earnings (same page).
- **Evidence.**
  - Zarattini-Aziz (SSRN 2023, not peer reviewed): QQQ January 2018 to
    September 2023, long above and short below VWAP, 671% total, Sharpe 2.1,
    maximum drawdown 9.4%
    ([Concretum](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/)).
  - VWAP's academic role is as an execution benchmark
    ([Berkowitz-Logue-Noser 1988](https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1988.tb02591.x)).
    Madhavan documents how it can be gamed and what it costs in missed
    opportunity
    ([Madhavan 2002](https://www.smallake.kr/wp-content/uploads/2014/07/TP_Spring_2002_Madhavan.pdf)).
  - No peer-reviewed out-of-sample test of VWAP distance predicting
    single-stock returns net of costs was found.
- **Repo.** Session anatomy: first-hour VWAP within 1 bp of the open, session
  VWAP +2.2 bp. `distance_vwap` was in the entry pilot's trees on IEX data
  (no edge). The IEX "VWAP trend" session feature measured zero.
- **Verdict.** C. Keep distance to VWAP in σ units as a location feature for the
  entry switch.

### 1.3 Gap-and-go and gap fade

- **Technicals.** Gap = open / prior close − 1. Warrior Trading's gap-and-go
  wants a gap above 4%, low float, a catalyst and pre-market volume; it trades
  09:30-10:00 on a break of the pre-market flag or the first 1-minute high, with
  the stop at that candle's low
  ([Warrior Trading](https://www.warriortrading.com/gap-go/)). A gap fade bets
  on the gap filling.
- **Evidence.**
  - On US indices 1928-2018, prices continue in the gap's direction on gap days
    and the gap-fill idea is "a myth"
    ([Plastun et al.](https://ideas.repec.org/p/pre/wpaper/201963.html)).
  - Positive overnight returns reverse during the day in high-attention retail
    stocks, because the opening price is high relative to the day. Buying at the
    open costs more than the effective half spread
    ([Berkman et al. 2012](https://bearworks.missouristate.edu/articles-cob/576/)).
  - S&P futures 1987-2002: reversals after large opening moves are significant,
    but their significance is "sharply reduced" after spreads and costs
    ([Grant-Wolf-Yu 2005](https://digitalcommons.montclair.edu/acctg-finance-facpubs/70/)).
  - Momentum profits are earned overnight and reversal profits intraday
    ([Lou-Polk-Skouras 2019](https://econpapers.repec.org/RePEc:eee:jfinec:v:134:y:2019:i:1:p:192-213)).
    A more frequent "positive night, negative day" tug of war predicts higher
    future returns
    ([Akbas et al. 2022](https://ink.library.smu.edu.sg/lkcsb_research/7712/)).
  - The index overnight drift has waned since the 2008-2015 papers
    ([Elm Wealth](https://elmwealth.com/night-moves-overnight-drift/)).
- **Repo.** The first 30 minutes do not predict the rest of the day (slope
  +0.024, t 0.2). The book's gap averaged +3.9 bp a session on 2016-2023 and
  +7.6 bp on 2024-2026 (session anatomy).
- **Verdict.** Gap-and-go is C: a strategy for small, low-float names, the
  wrong universe. Gap continuation is B, at index level. The attention-gap
  reversal and the overnight/intraday split are A. They inform both entry (do
  not pay the open after an attention gap) and selection.

### 1.4 Momentum ignition and relative-volume breakouts

- **Terminology.** In regulation, "momentum ignition" is an HFT tactic: submit
  and cancel many orders to trigger other algorithms and ignite a move
  ([SEC concept release, via Lexology](https://www.lexology.com/library/detail.aspx?g=cb81a662-37a9-4e9c-a31d-a9c3fc636d7f)).
  Retail usage means breakouts on relative volume (RVOL = volume so far /
  average volume to the same time, thresholds 2-5×).
- **Evidence.**
  - Stocks with unusually high volume over a day or a week rise over the
    following month
    ([Gervais-Kaniel-Mingelgrin 2001](https://sites.duke.edu/sgervais/?p=64)).
  - Intense attention-driven retail buying predicts -4.7% abnormal return over
    20 days
    ([Barber et al. 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190)).
  - The one-minute predictors found by LASSO are tied to news
    ([Chinco et al. 2019](https://ideas.repec.org/a/bla/jfinan/v74y2019i1p449-492.html)).
- **Repo.** Daily `volume_ratio_20/60` in `alpha.py`. IEX `relative_volume` in
  the entry pilot. Absent from the deep models.
- **Verdict.** The monthly high-volume premium is A. Intraday RVOL breakouts
  are C. RVOL by slot is a required conditioning variable for any intraday
  target. Moves with information drift and moves without it reverse
  ([Savor 2012](https://econpapers.repec.org/article/eeejfinec/v_3a106_3ay_3a2012_3ai_3a3_3ap_3a635-659.htm)),
  and abnormal volume, together with the 8-K clock, is the proxy for
  information we can actually observe on bars.

### 1.5 EMA pullbacks (9/20/21) and EMA crossovers

- **Technicals.** A pullback to a rising 20/21 EMA in an uptrend, on 5-15
  minute or daily bars. Raschke and Connors' "Holy Grail": ADX(14) above 30 and
  rising, a retrace to the 20-period average, a buy stop above the touching
  bar's high
  ([Trading Setups Review](https://www.tradingsetupsreview.com/the-holy-grail-trading-setup/)).
  Crossovers: 9/21, and the 50/200 golden or death cross.
- **Evidence.**
  - Moving-average and trading-range-break rules on the DJIA 1897-1986: buy
    signals earn more than sell signals
    ([Brock-Lakonishok-LeBaron 1992](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html)).
  - After a reality check over 7,846 rules, the best rule is not significant on
    1987-1996 (p ≈ 0.12). On S&P futures the p-values are 0.91 and 0.99
    ([STW 1999](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)).
  - No positive performance over 1962-2011 even without costs
    ([Bajgrowicz-Scaillet 2012](https://access.archive-ouverte.unige.ch/access/metadata/c0c2aa38-f0bf-430e-b994-dbe8bb53fb13/download)).
  - Of 95 modern studies, 56 are positive, with testing problems throughout;
    profits are documented at least until the early 1990s
    ([Park-Irwin 2007](https://experts.illinois.edu/en/publications/what-do-we-know-about-the-profitability-of-technical-analysis/)).
  - MA(10) timing on volatility-decile portfolios earns 9-22% a year in CAPM
    alpha. Break-even costs are at least 28.8 bp, and it is strongest in
    recessions
    ([Han-Yang-Zhou 2013](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf)).
  - The Holy Grail has no published test.
- **Repo.** Crosses lose (9/21 and 50/200 about -0.007 at 5 sessions). The
  21-EMA stretch *fade* is -0.022 at 5 sessions. Buying near the 200 EMA lost in
  every regime: -0.023, and -0.082 on 2024-2026 (NEXT_SESSION 2026-09-05).
- **Verdict.** Crossovers are C↓. EMA distance as a cross-sectional or
  portfolio feature is A/B. Pullback setups are C.

### 1.6 Bollinger squeeze and breakout, band mean reversion (and Keltner squeeze)

- **Technicals.** Bollinger Bands (20, 2σ): z, %b, bandwidth 4σ/SMA20. A
  "squeeze" is bandwidth at a 6-month low, or the bands inside the Keltner
  channel. A close above the upper band is a breakout; a close below the lower
  band is a mean-reversion buy.
- **Evidence.**
  - Across 14 markets the buy-minus-sell daily return spread was 0.454%
    before 1983, 0.296% in 1983-2001 and 0.002% since 2002. The breakout
    (trend) version beat the contrarian one
    ([Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf),
    [JPM](https://jpm.pm-research.com/content/43/4/152)).
  - Short-term reversal is liquidity provision, and its payoff scales with VIX
    ([Nagel 2012](https://www.nber.org/papers/w17653)).
  - Moves without fundamental news reverse; moves with news do not
    ([Da-Liu-Schaumburg 2014](https://econpapers.repec.org/article/inmormnsc/v_3a60_3ay_3a2014_3ai_3a3_3ap_3a658-674.htm)).
- **Repo.** Below the lower band: +0.9% over 5 sessions, and +2.1% while the AI
  basket falls (`backend/agents/trading/desk/entry.py`, in-sample). The trim at
  z > 3 lost (profit-taking). `band_z` was a stage-2 input.
- **Verdict.** B↓. Keep z and bandwidth percentile as features, conditioned on
  news and VIX.

### 1.7 RSI and stochastics: overbought/oversold and divergence

- **Technicals.** RSI(14) with Wilder smoothing, 70/30 or 80/20; RSI(2) for
  short-term trading
  ([StockCharts RSI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi)).
  Connors' RSI(2) buys under 5-10 in an uptrend above SMA200
  ([Trading Setups Review](https://www.tradingsetupsreview.com/trade-2-period-rsi/)).
  Stochastic %K(14), %D(3), 80/20, plus divergences
  ([StockCharts stochastic](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full)).
- **Evidence.** Across five OECD indices 1976-2002, MACD(12,26,0) and RSI(21,50)
  are significant in Milan and Toronto, RSI(14,30/70) in the DJIA, and nothing
  in the Nikkei
  ([Chong-Ng-Liew 2014](https://mpra.ub.uni-muenchen.de/54149/1/MPRA_paper_54149.pdf)).
  No peer-reviewed test of divergence was found. RSI(2) rests on book
  backtests.
- **Repo.** `backend/market/profit_taking.py:rsi` (14). The RSI > 80 half-trim
  lost: -0.1 bp/d, 0 of 20 offsets.
- **Verdict.** Index-level RSI rules are B− (old, mixed). Divergence and RSI(2)
  are C.

### 1.8 MACD

- **Technicals.** MACD = EMA12 − EMA26, signal = EMA9, histogram, zero-line
  cross. The normalized multi-scale version (8/24, 16/48, 32/96, divided by
  63-day price volatility and then by its own 252-day volatility) comes from Baz
  et al.
  ([SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2695101)).
- **Evidence.** Mixed on indices (Chong et al. above). It is a standard input
  in deep-momentum work that optimizes Sharpe directly; that work beats
  classical time-series momentum up to 2-3 bp of cost
  ([Lim-Zohren-Roberts 2019](https://arxiv.org/abs/1904.04912)). A
  learning-to-rank model with MACD inputs roughly tripled Sharpe without costs
  ([Poh et al. 2021](https://arxiv.org/pdf/2012.07149)).
- **Repo.** `technical.py` computes the Baz family; about 0 alone.
- **Verdict.** B as a trend summary, C as a crossover signal.

### 1.9 ADX and trend strength

- **Technicals.** Wilder's +DI, −DI and ADX(14). ADX above 20-25 means a trend,
  with heavy smoothing lag
  ([StockCharts ADX](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx)).
- **Evidence.** No peer-reviewed out-of-sample test on equities was found. It is
  used as a regime gate in practitioner setups (Holy Grail above).
- **Repo.** Missing.
- **Verdict.** C. A cheap trend-versus-chop state feature, nothing more.

### 1.10 Keltner, ATR and Donchian channels

- **Technicals.** Keltner = EMA20 ± 2·ATR10, Raschke's ATR version of
  Keltner's 1960 rule
  ([StockCharts KC](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels)).
  Donchian breakouts use 20/55-day highs.
- **Evidence.** Channel rules sat inside the 7,846-rule universe that failed
  out of sample (STW 1999). Trend following on futures has a century-long record
  ([Hurst-Ooi-Pedersen 2017](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing);
  [Moskowitz-Ooi-Pedersen 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)).
  Its time-series predictability is disputed
  ([Huang-Li-Wang-Zhou 2020](https://down.aefweb.net/WorkingPapers/w717.pdf)).
- **Repo.** `levels.range_position_60`, `alpha.close_over_max/min_20/60`.
  Keltner and ATR are missing. The top of the 60-session range showed +1.3%
  over 20 sessions (t 3.7, in-sample, qualified names; technical analyst
  docstring).
- **Verdict.** Keltner is C. Range position and breakout are B as
  cross-sectional features.

### 1.11 Pivot points (floor, Camarilla) and prior-day high/low/close

- **Technicals.** Floor: P = (H+L+C)/3, R1 = 2P−L, S1 = 2P−H, R2 = P+(H−L), S2 =
  P−(H−L), from the prior day for intraday charts
  ([StockCharts pivots](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/pivot-points)).
  Camarilla levels are C ± (H−L)·1.1/12, /6, /4 and /2
  ([mypivots](https://www.mypivots.com/dictionary/definition/42/camarilla-pivot-points)).
- **Evidence.**
  - Published FX support and resistance levels: prices bounced 60.8% of the
    time against 56.2% at arbitrary levels, still after five days
    ([Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html)).
  - Take-profit orders cluster at round numbers, which explains reversals.
    Stop-losses cluster just beyond them, which explains acceleration
    ([Osler 2003](https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html)).
  - Support and resistance coincide with peaks in NYSE limit-order-book depth
    ([Kavajecz-Odders-White 2004](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html)).
  - No peer-reviewed test of floor or Camarilla pivots on equities was found.
- **Repo.** Missing. Prior-day high/low/close are trivially available from the
  panel.
- **Verdict.** Pivots are C. "Reference levels where orders cluster" is B
  (FX, NYSE depth). Build the prior-day high/low/close distances in ATR units.

### 1.12 Volume profile (POC, value area, high- and low-volume nodes)

- **Technicals.** Steidlmayer's Market Profile (CBOT, 1985): the point of
  control is the price with the most activity, the value area the central 70%,
  the initial balance the first hour's range
  ([Wikipedia](https://en.wikipedia.org/wiki/Market_profile)).
- **Evidence.** No peer-reviewed predictive test was found. The closest
  academic object is the turnover-weighted reference price (capital-gains
  overhang). Its gap to price predicts returns, and in its sample it subsumes
  momentum (coefficient t 7.79)
  ([Grinblatt-Han 2005](https://www-2.rotman.utoronto.ca/facbios/file/momentum_JFE.pdf)).
- **Repo.** Missing.
- **Verdict.** POC and value area are C. The overhang analog is A, at monthly
  horizon.

### 1.13 Market structure (higher highs/lows, break of structure)

- **Technicals.** Swing points from k-bar fractals. An uptrend is a sequence of
  higher highs and higher lows; a break of structure is a close below the last
  higher low.
- **Evidence.**
  - Kernel-detected patterns change conditional return distributions,
    especially on Nasdaq 1962-1996, but "informativeness does not guarantee a
    profitable trading strategy"
    ([Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf)).
  - Head-and-shoulders predicts relative declines: 5-7% a year risk-adjusted in
    the Russell 2000, not standalone profitable in the S&P 500
    ([Savin-Weller-Zvingelis 2007](https://www.biz.uiowa.edu/faculty/gsavin/papers/hsrevision_paw_10%2019%2006.pdf)).
- **Repo.** `levels.swing_points` (5-bar, stamped at confirmation). No
  higher-high/lower-low sequence feature.
- **Verdict.** B− for patterns, weak in large caps. C for break-of-structure
  vocabulary.

### 1.14 Support and resistance, multi-timeframe confluence

- **Technicals.** Swing highs and lows, round numbers, daily MA50/200, weekly
  EMA21, prior highs; confluence counts agreeing levels.
- **Evidence.** The order-clustering evidence of §1.11. Excess buying one cent
  below round numbers moves 24-hour returns
  ([Bhattacharya-Holden-Jacobsen 2012](https://econpapers.repec.org/RePEc:inm:ormnsc:v:58:y:2012:i:2:p:413-431)).
  The 52-week high is an anchor (George-Hwang). No test of confluence as such.
- **Repo.** `levels.level_features` and `level_identity`. Reward-to-risk
  *inverts* on these names: resistance overhead means a breakout. At support the
  worst drawdown is -7.6% against -12%, with no higher return (technical
  analyst docstring).
- **Verdict.** B for levels as order-clustering reference points. C for
  confluence scores.

### 1.15 Multi-timeframe trend alignment

- **Technicals.** Elder's triple screen: weekly trend (MACD, DMI, 13/30-week
  MAs), a daily oscillator pullback, an intraday trigger
  ([elearnmarkets](https://blog.elearnmarkets.com/triple-screen-trading-method-alexander-elder-way-trading/)).
- **Evidence.** Information across horizons is real. The trend factor doubles
  the Sharpe of the short-term reversal, momentum and long-term reversal
  factors
  ([Han-Zhou-Zhu 2016](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html)).
  Time-series momentum persists 1-12 months
  ([MOP 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)).
  Alignment rules as such are untested.
- **Repo.** `levels.weekly_trend` and `daily_trend`. Weekly trend up: +1.0%
  against -2.0% (t 4.2, in-sample, qualified names). It is already a leg of the
  grade.
- **Verdict.** B as features. C as rules.

### 1.16 Relative strength against the index or sector

- **Technicals.** Name return minus SPY/SMH/IGV over 5/20/60 days; RS-line new
  highs; intraday relative strength since the open.
- **Evidence.**
  - Industry momentum accounts for much of stock momentum
    ([Moskowitz-Grinblatt 1999](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:4:p:1249-1290)).
  - Residual momentum doubles risk-adjusted profits
    ([Blitz et al. 2011](https://econpapers.repec.org/RePEc:eee:empfin:v:18:y:2011:i:3:p:506-521)).
  - Connected-firm momentum: 1.68% a month, t 9.67
    ([Ali-Hirshleifer 2020](https://ideas.repec.org/a/eee/jfinec/v136y2020i3p649-675.html)).
  - Customer-to-supplier momentum: 1.55% a month, t 3.60, 1981-2004
    ([Cohen-Frazzini 2008](https://pages.stern.nyu.edu/~afrazzin/pdf/Economic%20Links%20and%20Predictable%20Returns%20-%20Cohen%20and%20Frazzini.pdf)).
    It is directly relevant to a semiconductor supply chain, and decay after
    publication should be expected (§2.11).
- **Repo.** `alpha` `rel_mkt_*` and `rel_theme_*`,
  `baselines.residual_momentum(120, 21)`.
- **Verdict.** A at monthly horizon in the cross-section. C intraday.

### 1.17 Market internals (breadth, TICK, ADD)

- **Technicals.** NYSE TICK = NYSE stocks on an uptick minus on a downtick;
  ±1000 are extremes
  ([TradingSim](https://www.tradingsim.com/blog/tick-index)). ADD = advancers
  minus decliners; the A/D line is its running total, read for confirmation
  and divergence
  ([Fidelity](https://www.fidelity.com/learning-center/trading-investing/advance-decline)).
- **Evidence.** Sentiment measures of this kind have "little predictive power"
  for near-term returns
  ([Brown-Cliff 2004](https://www.sciencedirect.com/science/article/abs/pii/S0927539803000422)).
  Monthly breadth predicts country and industry index returns (long-short 1.68%
  a month across 64 countries)
  ([Zaremba et al. 2020](https://www.sciencedirect.com/science/article/pii/S0264999319312982)).
  No peer-reviewed test of TICK was found.
- **Repo.** `deep_stage2.breadth`, `day_type` `breadth_above_20/50`, regime
  participation.
- **Verdict.** B for monthly breadth. C for TICK. Build a 94-name intraday
  breadth proxy for context.

### 1.18 Time-of-day effects (open drive, lunch, power hour, last half hour)

- **Evidence.**
  - Volume and volatility are U-shaped and periodic; the periodicity must be
    removed before modelling
    ([Andersen-Bollerslev 1997](https://www.sciencedirect.com/science/article/abs/pii/S0927539897000042)).
  - SPY's first half-hour, measured from the prior close, predicts its last
    half-hour: slope 6.94 (×100), t 4.08, R² 1.6% (1.4% out of sample). The
    timing strategy earns 6.67% a year at Sharpe 1.08, and is stronger on
    high-volatility, high-volume, recession and news days
    ([Gao et al. 2018](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf)).
  - In equity futures the rest of the day predicts the last 30 minutes (t
    7.29, out-of-sample R² 2.88%), but only when dealers are short gamma: slope
    6.63 against 0.82
    ([Baltussen et al. 2021](https://academicweb.nd.edu/~zda/intramom.pdf)).
  - The same half-hour on later days continues for 40 days (3.01 bp decile
    spread) but loses money after spreads
    ([HKS 2010](https://www.bauer.uh.edu/departments/finance/documents/Heston-Korajczyk-Sadka-jf-2010-01-07.pdf)).
  - Practitioner measurement: the coefficient is +0.006 (t 0.6) on 2022-2026
    SPX, and +0.055 (t 3.1) only on short-gamma closes
    ([firmtape, C](https://dev.to/firmtape/intraday-momentum-is-dead-in-the-0dte-era-we-measured-it-on-1085-spx-sessions-43g0)).
  - An independent replication of the SPY "noise area" strategy finds Sharpe
    1.11 on 2020-2024 and about 0 on 2025-2026
    ([GitHub, C](https://github.com/codecat-ops/zarattini-2024-momentum-spy)).
- **Repo.** The book's first bar carries 22-26% of variance. SPY sets its high
  in the last slot on 19.7% of days (session anatomy).
- **Verdict.** A for the historical index effect, with a live ↓ risk. A for
  periodicity as normalization. C for lunch and power-hour rules on single
  names.

### 1.19 News and earnings gaps

- **Evidence.**
  - Post-earnings drift has been "non-existent since 2006" for large stocks
    ([Martineau 2022](https://econpapers.repec.org/article/nowjnlcfr/104.00000122.htm)).
    Claims of a revival rest on microcaps
    ([UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)).
  - Price shocks with information drift; those without reverse
    ([Savor 2012](https://econpapers.repec.org/article/eeejfinec/v_3a106_3ay_3a2012_3ai_3a3_3ap_3a635-659.htm)).
- **Repo.** `edgar.py`: 8-K item 2.02 events with acceptance timestamps and the
  reaction-window residual. `language.py`: release tone, the strongest signal on
  record (NEXT_SESSION 2026-09-05: tone blend IC 0.044, t 3.0 at 20 sessions,
  beta-adjusted).
- **Verdict.** PEAD-style drift in large caps is B↓. News versus no-news
  conditioning is A: use it to condition every dip feature.

### 1.20 Short interest and float

- **Evidence.** Aggregate short interest is "arguably the strongest known
  predictor" of market returns: annual out-of-sample R² 13.24%
  ([Rapach-Ringgenberg-Zhou 2016](https://ideas.repec.org/a/eee/jfinec/v121y2016i1p46-65.html)).
  Days-to-cover long-short earns 1.2% a month (NBER working paper)
  ([Hong et al.](https://www.nber.org/system/files/working_papers/w21166/w21166.pdf)).
  Float filters are small-cap day-trading lore.
- **Repo.** No short-interest data.
- **Verdict.** A in aggregate, B in the cross-section. Low priority for a
  large-cap book; it is a data gap.

### 1.21 Candlestick patterns (the repo computes them)

- **Evidence.** DJIA stocks 1992-2002: "no evidence" that candlestick trading
  beats the market
  ([Marshall-Young-Rose 2006](https://mro.massey.ac.nz/bitstreams/cf13fcfc-21d5-4e4b-89b6-d4f8cf347a84/download)).
- **Repo.** About 0.
- **Verdict.** C↓. Keep only as a negative control.

### 1.22 Survey table

| Strategy | Core technicals and parameters | Best evidence | Grade | Relevance to this book |
|---|---|---|---|---|
| ORB | first 5-30 min high/low; stop 10% ATR14; relative volume ≥ 2× | unreviewed; edge from relative-volume selection; crude-oil ORB peer-reviewed | C (B futures) | relative volume as conditioning only |
| VWAP trend/reversion | session VWAP from 09:30, (H+L+C)/3 weights; ±kσ | unreviewed QQQ paper; VWAP is an execution benchmark | C | location feature |
| Gap-and-go / fade | gap > 4%, catalyst, float; gap fill | gap continuation (index) B; attention-gap reversal A | C / B / A | avoid paying the open after attention gaps |
| Relative-volume breakouts | RVOL 2-5× by time of day | high-volume premium (monthly) A | B | conditioning variable |
| EMA pullbacks and crosses | 9/20/21 pullbacks; 9/21, 50/200 crosses; Holy Grail ADX > 30 | index rules failed after 1987; volatility-portfolio MA timing A | C↓ (crosses) / B (distance) | distance features for selection |
| Bollinger | 20, 2σ; z, bandwidth, squeeze | profits gone after popularization | B↓ | z and bandwidth features |
| RSI / stochastic | RSI 14 (70/30), RSI 2; %K14/%D3 | mixed index evidence; divergence untested | B− / C | minor features |
| MACD | 12/26/9; Baz multi-scale | mixed; used in deep-momentum work | B | trend summary |
| ADX | 14, threshold 20-25 | none | C | state feature |
| Keltner / Donchian | EMA20 ± 2 ATR10; 20/55-day breakouts | futures trend following A; channels in failed rule set | C / B | range position |
| Pivots, prior-day levels | floor, Camarilla; prior-day H/L/C | FX support/resistance and order clustering | C / B | prior-day level distances |
| Volume profile | POC, 70% value area | none; capital-gains overhang analog A | C (A analog) | overhang for selection |
| Market structure | higher highs/lows, break of structure | pattern informativeness, weak profits | B− / C | minor |
| Support/resistance and confluence | swing, round numbers, MAs | order clustering, round numbers B | B / C | level features |
| Multi-timeframe alignment | weekly/daily/intraday agreement | trend factor A; alignment rules untested | B / C | already in the grade |
| Relative strength | vs SPY/SMH/IGV; peer momentum | industry, residual and connected-firm momentum A | A (monthly) | selection |
| Internals | TICK ±1000, ADD, breadth | breadth monthly B; TICK none | B / C | context |
| Time of day | first/last half hour | index late-day momentum A↓; periodicity A | A↓ | 15:30-vs-close switch |
| News/earnings gaps | 8-K, gap, reaction | PEAD dead in large caps; news conditioning A | B↓ / A | conditioning |
| Short interest / float | SI/float, days to cover | aggregate A; cross-section B | A / B | data gap |
| Candles | hammer, engulfing | tested: no value on DJIA stocks | C↓ | negative control |

---

## 2. Academic ML-for-trading evidence

### 2.1 Gu, Kelly and Xiu (2020), Empirical Asset Pricing via Machine Learning

Source: [paper](https://dachxiu.chicagobooth.edu/download/ML.pdf),
[RFS](https://academic.oup.com/rfs/article/33/5/2223/5758276).

- **Setup.** About 30,000 US stocks, 1957-2016. Inputs: 94 stock
  characteristics (61 annual, 13 quarterly, 20 monthly), 74 industry dummies, 8
  macro predictors, and interactions, for 920 features. Training 1957-1974,
  validation 1975-1986, test 1987-2016, refit annually with a rolling
  validation window.
- **Models.** OLS, elastic net, PCR, PLS, GLM with group lasso, random forest,
  GBRT, and neural nets NN1-NN5 (32 to 32-16-8-4-2 neurons, ReLU). The nets are
  regularized with an L1 penalty, early stopping, batch normalization and an
  ensemble over random initializations. Huber loss is an option. Tuning is on
  the validation window.
- **Results.**
  - Monthly out-of-sample R²: NN3 0.40%, GBRT+H 0.34%, RF 0.33%, OLS-3 0.16%,
    full OLS -3.46%.
  - NN3 decile long-short Sharpe: 1.35 value-weighted, 2.45 equal-weighted.
  - NN3 reaches 0.52-0.70% monthly R² among the top 1,000 stocks.
  - The dominant predictors are price trends (stock momentum, industry
    momentum, short-term reversal), then liquidity, then volatility.
- **Implications here.** At monthly horizon, trees and shallow nets are within
  a few hundredths of an R² point of each other. The gain comes from
  regularization, early stopping and ensembling, not depth. The informative
  inputs are trend and reversal features, which the repo computes.

### 2.2 Jiang, Kelly and Xiu (2023), (Re-)Imag(in)ing Price Trends

Source: [paper](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf),
[JF](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13268).

- **Images.** 5-, 20- and 60-day OHLC bars, 3 pixels a day, with a moving
  average whose window equals the image length and volume bars in the bottom
  fifth. Sizes are 32×15, 64×60 and 96×180. Each image is scaled so the path's
  maximum and minimum touch its top and bottom, which makes it level-relative
  by construction.
- **Labels and split.** Label = 1 if the subsequent 5/20/60-day return is
  positive. CRSP 1993-2019. Training on 1993-2000 with a random 70/30
  train/validation split, then out of sample on 2001-2019 with no refit.
- **Network.** 2/3/4 blocks of (5×3 convolution, batch norm, leaky ReLU, 2×1
  max-pool) with 64, 128, 256 and 512 filters; 50% dropout on the fully
  connected layer; Xavier initialization. **Adam at 1e-5, batch 128, early
  stopping after two epochs without validation improvement, five independently
  trained networks averaged.**
- **Results.**
  - I20/R20: equal-weight long-short Sharpe 2.16 but value-weight 0.49, turnover
    173-181% a month.
  - I5/R5: weekly equal-weight Sharpe 6.75.
  - Accuracy 53.3%.
  - At most 12% of the CNN signal is explained by standard characteristics. The
    main learned pattern: "when a stock closes on the low end of its recent
    high-low range, future returns tend to be high".
  - Transferring the US model abroad raises the Sharpe from 0.3 to 0.7.
- **Replication.** An independent GitHub replication reproduces the US pattern
  at slightly lower Sharpe (5.89 against 6.75 weekly equal-weight), with
  592-696% turnover
  ([GitHub](https://github.com/George-hardworking/reimaging-price-trends-replication-and-extension)).
- **How the repo's replica differed** (`backend/market/chart_cnn.py`):
  - Adam at **1e-4** (JKX 1e-5).
  - **At most 5 epochs** with patience 2 (JKX: until early stopping).
  - **One seed** (JKX: five-network ensemble).
  - **Above-median residual** labels (JKX: sign of the raw return).
  - Walk-forward folds on 532 survivor names (JKX: all CRSP, one fit).
- **Implications here.** The replica was not a faithful test, but a faithful
  one is not promising either. The published edge is a small-cap, high-turnover,
  mostly short-horizon reversal effect that value weighting removes
  (0.49 Sharpe). It is worth one faithful run on selection (§5), because the
  image's level-relative scaling is the operator's point in its purest form.

### 2.3 Machine learning on price paths in large caps, and the "complexity" debate

- ML forecasts from past price paths "strongly predict" the cross-section,
  including "among the largest 500 stocks". They are stable, nonlinear and
  distinct from momentum, reversal and known technical signals
  ([Murray-Xia-Xiao 2024](https://ideas.repec.org/a/eee/jfinec/v153y2024ics0304405x2400014x.html)).
  This is the best peer-reviewed support for a large-cap technical *selection*
  model at monthly horizon.
- Kelly, Malamud and Zhou argue that heavily over-parameterized ridge
  regressions time the market better
  ([JF 2024](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13298)).
  Nagel shows that with short windows the method collapses into a
  volatility-timed momentum strategy that "happened to perform well"
  ([Nagel 2025](https://ideas.repec.org/p/nbr/nberwo/34104.html)). Capacity does
  not substitute for signal, which matches the repo's stage-1 note: "the
  information is not in the model class".

### 2.4 Intraday momentum

- **Gao-Han-Li-Zhou (2018).** SPY 1993-2013. The first half-hour, from the
  prior close to 10:00, predicts the last half-hour (15:30-16:00): t 4.08,
  in-sample R² 1.6%, out-of-sample 1.4%. With the 12th half-hour the R² is 2.0%.
  It is stronger on volatile, high-volume, recession and FOMC-minutes days
  (R² 11.0%). The timing strategy earns 6.67% a year at Sharpe 1.08
  ([paper](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf),
  [JFE](https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351)).
- **Baltussen-Da-Lammers-Martens (2021).** 60+ futures, 1974-2020. The
  effect is present in both halves of the sample, and "only present when option
  market makers are net short gamma". Strategy Sharpe runs 0.87-1.73, positive
  net of a one-tick cost in S&P futures
  ([paper](https://academicweb.nd.edu/~zda/intramom.pdf)).
- **Heston-Korajczyk-Sadka (2010).** Cross-section of NYSE stocks, 2001-2005.
  Return continuation at exact multiples of a day lasts at least 40 days, a
  3.01 bp decile spread, and loses money after spreads
  ([paper](https://www.bauer.uh.edu/departments/finance/documents/Heston-Korajczyk-Sadka-jf-2010-01-07.pdf)).
- **Zarattini-Aziz-Barbon "noise area" on SPY** (SSRN, unreviewed): 1,985%
  over 2007-2024. An independent frozen-protocol replication finds Sharpe 1.11
  on 2020-2024 and about 0 on 2025-2026, "not allocable today"
  ([SSRN](https://ssrn.com/abstract=4824172),
  [replication](https://github.com/codecat-ops/zarattini-2024-momentum-spy)).
- **Intraday predictability of the market from 15-minute factor returns.** On
  1996-2020, with the test period 2004-2020, the best out-of-sample R² is
  0.212%. A cost-adjusted intraday Sharpe of 1.37 on SPY is driven by
  liquidity and turnover factors
  ([Aleti-Bollerslev-Siggaard](https://public.econ.duke.edu/~boller/Papers/MS_2025.pdf)).
- **Implications here.** The only intraday *direction* signal with a record is
  at index level and conditional on dealer gamma, which the repo cannot observe
  historically. It is the right candidate for a 15:30-versus-MOC switch (§4). It
  is not a stock-selection signal.

### 2.5 Opening range and VWAP papers

See §1.1-1.2. All four Zarattini/Aziz papers are SSRN working papers from a
fund and trading-education group. None is marked as journal-published
([Concretum list](https://concretumgroup.com/papers/)). Treat them as C-grade
backtests, informative about which *conditioning variables* matter (relative
volume), not as evidence of a large-cap edge.

### 2.6 Technical-analysis foundations

| Paper | What it found | Grade and relevance |
|---|---|---|
| [Brock-Lakonishok-LeBaron 1992](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html) | MA and range-break rules on DJIA 1897-1986; buy signals beat sell signals; not explained by AR(1), GARCH-M, EGARCH nulls | B↓ (index, pre-1987) |
| [Sullivan-Timmermann-White 1999](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf) | Reality check over 7,846 rules: best rule significant in-sample, p ≈ 0.12 on 1987-1996; futures p 0.91/0.99; break-even 0.27% per trade | the multiplicity lesson |
| [Bajgrowicz-Scaillet 2012](https://access.archive-ouverte.unige.ch/access/metadata/c0c2aa38-f0bf-430e-b994-dbe8bb53fb13/download) | FDR on the same 7,846 rules, DJIA 1897-2011: no positive performance 1962-2011 even at zero cost; picking future winners possible only ex post | ↓ |
| [Park-Irwin 2007](https://experts.illinois.edu/en/publications/what-do-we-know-about-the-profitability-of-technical-analysis/) | 56 of 95 modern studies positive, profits at least until the early 1990s, pervasive data snooping | survey |
| [Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf) | 10 kernel-detected patterns carry incremental information (especially Nasdaq, 1962-1996); information is not profit | B |
| [Han-Yang-Zhou 2013](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf) | MA(10) timing of volatility-decile portfolios: 9.3-21.8% CAPM alpha a year; break-even costs ≥ 28.8 bp; low correlation with momentum; strongest in recessions | A (portfolio-level timing) |
| [Han-Zhou-Zhu 2016](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html) | trend factor from MAs over short, intermediate and long horizons doubles the Sharpe of reversal and momentum factors; +0.75%/month in 2008 | A (monthly, all stocks) |
| [Avramov-Kaplanski-Subrahmanyam 2021](https://econpapers.repec.org/RePEc:wly:revfec:v:39:y:2021:i:2:p:127-145) | MAD (21/200) predicts the cross-section; ~9% value-weighted alpha a year, beyond momentum and the 52-week high; survives institutional costs; stronger on the long side | A (fits a long-only book) |
| [Neely-Rapach-Tu-Zhou 2014](https://ideas.repec.org/a/inm/ormnsc/v60y2014i7p1772-1791.html) | technical indicators forecast the equity premium in and out of sample, matching macro variables; they catch declines near cycle peaks | A (market timing, monthly) |
| [Moskowitz-Ooi-Pedersen 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) / [Huang et al. 2020](https://down.aefweb.net/WorkingPapers/w717.pdf) | TSMOM in 58 futures, Sharpe > 1 / asset-by-asset evidence weak; profits similar to a sample-mean strategy | B (contested) |
| [George-Hwang 2004](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html) | nearness to the 52-week high explains much of momentum and does not reverse; a later working paper finds it subsumed by momentum value-weighted over 1927-2019 ([Wang](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/576995/Haoxu-Wang-paper_NZFM.pdf)) | A with a ↓ caveat |
| [Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html), [2003](https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html) | published FX support and resistance predicts bounces; order clustering at round numbers | B (FX) |
| [Kavajecz-Odders-White 2004](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html) | support and resistance coincide with limit-order-book depth peaks | B (mechanism) |
| [Grinblatt-Han 2005](https://www-2.rotman.utoronto.ca/facbios/file/momentum_JFE.pdf) | turnover-weighted reference price; the capital-gains overhang subsumes momentum | A |
| [Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf) | Bollinger profits vanish after popularization | ↓ |

### 2.7 Realized volatility and intraday features

- High-frequency data turned volatility measurement into realized variance.
  Simple long-memory models of log realized volatility forecast well
  ([Andersen-Bollerslev-Diebold-Labys 2003](https://econpapers.repec.org/RePEc:ecm:emetrp:v:71:y:2003:i:2:p:579-625)).
  The HAR cascade (1, 5, 22 days) is the standard baseline
  ([Corsi 2009](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738)).
- Future volatility depends more on past negative-return variance. Negative
  jumps raise it and positive jumps lower it; semivariance models forecast
  better out of sample
  ([Patton-Sheppard 2015](https://econpapers.repec.org/RePEc:tpr:restat:v:97:y:2015:i:2:p:683-697)).
- The normalized good-minus-bad volatility predicts the cross-section of returns
  ([Bollerslev-Li-Zhao 2020](https://ideas.repec.org/a/cup/jfinqa/v55y2020i3p751-781_2.html)).
  Low minus high realized-skewness deciles earn 19 bp the next week (t 3.70),
  while realized volatility itself does not predict
  ([Amaya et al. 2015](https://ideas.repec.org/a/eee/jfinec/v118y2015i1p135-167.html)).
- ML beats the HAR lineage on Dow constituents with minimal tuning, more so at
  longer horizons
  ([Christensen-Siggaard-Veliyev 2023](https://econpapers.repec.org/article/oupjfinec/v_3a21_3ay_3a2023_3ai_3a5_3ap_3a1680-1727..htm)).
  The repo's CNN volatility head (R² 0.27 against trailing volatility) agrees.
- Daily range estimators are 4.9-7.4 times more efficient than close-to-close:
  Parkinson (h−l)²/(4 ln 2), Garman-Klass 0.5(h−l)² − (2 ln 2 − 1)c², and
  Rogers-Satchell h(h−c) + l(l−c)
  ([Molnár](http://mmquant.net/wp-content/uploads/2016/09/range_based_estimators.pdf)).
- **Implications here.** Volatility and drawdown are forecastable, which the
  repo has reproduced, but using them to size or trim this book lost
  (`vol-sizing-2026-09-27.md`, `profit-taking-2026-09-27.md`). Their proper use
  in the retrain is normalization and conditioning (§3.3), plus semivariance and
  skewness as selection features.

### 2.8 High-frequency and intraday ML without an order book

- S&P 100 in 2019-2020: 5-second returns have a median out-of-sample R² near
  10% and 30-second returns about 4%. Returns are "only predictable over the
  next 3 minutes". The key inputs are trade and order-book imbalances
  ([Aït-Sahalia-Fan-Xue-Zhou 2022](https://www.nber.org/system/files/working_papers/w30366/w30366.pdf)).
- LASSO on the full cross-section of lagged one-minute returns: predictors are
  "unexpected, short-lived, and sparse", and linked to news
  ([Chinco-Clark-Joseph-Ye 2019](https://ideas.repec.org/a/bla/jfinan/v74y2019i1p449-492.html)).
- Around 900 million intraday observations: predictability is concentrated
  mid-day and in less liquid firms. Sharpe ratios of 4 after costs are claimed
  in an SSRN working paper
  ([Liu-Stentoft](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4496917)).
- **Implications here.** In large caps, bar-based direction signals decay
  within minutes and need order-book data we do not have. At 15-minute
  granularity, the literature expects what stage 1/2 found: volatility yes,
  direction about 0.01 IC.

### 2.9 Daily ML on large caps: the costs problem

- An ensemble of a DNN, GBT and RF on S&P 500 constituents earned 0.45% a day
  before costs over 1992-2015, with profits declining in recent years
  ([Krauss-Do-Huck 2017](https://econpapers.repec.org/article/eeeejores/v_3a259_3ay_3a2017_3ai_3a2_3ap_3a689-702.htm)).
  An LSTM earned 0.46% a day before costs, but "as of 2010, excess returns
  seem to have been arbitraged away". The stocks it traded were
  high-volatility short-term reversals
  ([Fischer-Krauss 2018](https://www.sciencedirect.com/science/article/abs/pii/S0377221717310652)).
- Deep-learning signals "extract profitability from difficult-to-arbitrage
  stocks". Excluding microcaps, distressed firms or volatile periods, and
  paying realistic costs, reduces profitability
  ([Avramov-Cheng-Metzker 2023](https://econpapers.repec.org/RePEc:inm:ormnsc:v:69:y:2023:i:5:p:2587-2619)).
- One-month-horizon ML alpha is close to zero net of costs after 2004.
  Models trained on 3-12 month horizons trade less and stay positive net
  ([Blitz-Hanauer-Hoogteijling-Howard 2023](https://www.robeco.com/en-int/insights/2023/07/the-term-structure-of-machine-learning-alpha)).
  This is the strongest argument for a 20-60 session selection target over a
  next-session target.
- **Implications here.** This is the same result as `hgb_rank` and `hgb_desk`.
  A learned top-10 book concentrated in names that had already run, with more
  turnover, and lost to holding every graded name (`pit-arms-2026-09-26.md`).

### 2.10 Gradient-boosted trees against deep nets on tabular data

- On 45 medium-sized tabular datasets (around 10k samples), with 20,000 compute
  hours of tuning, trees remain state of the art. Nets struggle with
  uninformative features, rotation invariance and irregular target functions
  ([Grinsztajn-Oyallon-Varoquaux 2022](https://arxiv.org/abs/2207.08815)).
  GKX's NN3 beat GBRT by 0.06 percentage points of monthly R² (0.40%
  against 0.34%) on 920 features and 60 years (§2.1).
- **Implications here.** The feature catalogue is tabular: 100-150 columns,
  strongly heterogeneous, many uninformative. The primary baseline
  should be trees. Nets earn a place only on the raw sequence or image
  representation, and only if they beat the tree on the same target and the
  same decision test.

### 2.11 Replication and decay

- **Published anomalies shrink.** Returns are 26% lower out of sample and 58%
  lower after publication, across 97 predictors. The decay is fastest for
  clean, short-horizon patterns
  ([McLean-Pontiff 2016, CFA digest](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary);
  [JF](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365)).
- **Most do not replicate.** With microcaps mitigated, 65% of 452 anomalies fail
  |t| ≥ 1.96, including 96% of trading-friction anomalies, and 82% fail at 2.78
  ([Hou-Xue-Zhang 2020](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html)).
  A new factor needs t > 3.0
  ([Harvey-Liu-Zhu 2016](https://www.nber.org/papers/w20592)).
- **Turnover decides survival.** Anomalies with one-sided monthly turnover
  under 50% mostly survive costs; few above it do
  ([Novy-Marx-Velikov 2016](https://ideas.repec.org/p/nbr/nberwo/20721.html)).
- **Protocol.** Keep track of every trial, define the test sample ex ante, and
  treat iterated out-of-sample as in-sample
  ([Arnott-Harvey-Markowitz 2019](https://people.duke.edu/~charvey/Research/Published_Papers/P138_A_backtesting_protocol.pdf)).

### 2.12 Retail day-trading outcomes

- **Taiwan.** Fewer than 1% of day traders earn predictably positive returns
  net of fees
  ([Barber-Lee-Liu-Odean 2014](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html)).
- **Brazil.** 97% of those who persisted 300+ days lost money, 0.4% earned more
  than a bank teller, and there was no learning
  ([Chague-De-Losso-Giovannetti](https://ideas.repec.org/p/spa/wpaper/2019wpecon47.html)).
- **FTC v. Warrior Trading.** "The vast majority of customer accounts actually
  lost money"; $3 million in redress
  ([FTC](https://www.ftc.gov/news-events/news/press-releases/2022/04/federal-trade-commission-cracks-down-warrior-trading-misleading-consumers-false-investment-promises)).
- **Implications here.** The prior on single-name intraday technical edges for
  a retail account is low before any data is looked at. This is not a reason to
  skip the test. It is a reason to require t ≥ 3-grade evidence before the board
  changes.

---

## 3. The feature catalogue

### 3.1 Conventions

- **Slots.** Slot k = 0..25 is the 15-minute bar closing at 09:45 + 15k ET.
  O_0 is the session's first print, C_{t−1} the prior official close, and
  prices are on the session's raw basis (`sip_cube`).
- **Earliest point-in-time moment (PIT).**
  - `k+`: at the close of slot k.
  - Live, prices come from the IEX quote in real time. A feature that needs
    consolidated (SIP) volume is usable one slot later, because the free SIP
    plan refuses requests ending within 15 minutes (AGENTS.md, 2026-09-28).
    *Train with that one-slot lag.* IEX carries about 2.5% of volume, so
    IEX-derived volume features would differ between training and live use
    (`claude-review-2026-09-26-ml-balancer.md`, S11).
  - `C15:30`: at the board's close cutoff, computed on the live row
    (`live_technical.with_live_row`). Every daily feature feeding the
    close-auction decision must be recomputed this way in training too.
  - `Ct`: after session t's close, usable from t+1.
  - `Wt`: at the Friday close. Mid-week rows carry the last completed week
    (`technical._weekly_ema`).
  - `8-K`: EDGAR acceptance time; after 16:00 counts for the next session
    (`edgar.py`).
- **ATR14** = Wilder average true range over 14 sessions, as a fraction of
  close. **σ_open→k** = trailing 60-session standard deviation of log(C_k/O_0)
  for the same k. **σ_slot(k)** = √(mean over the trailing 60 sessions of
  r_{·,k}²).
- **CS rank** = per-date rank-Gauss (Φ⁻¹((rank − 0.5)/n)) over the day's
  point-in-time eligible names.

### 3.2 Catalogue

**Family I — intraday session state (15-minute SIP bars).**

| ID | Feature | Definition (parameters) | TF | PIT | Grade | Repo today | Decisions | Normalization |
|---|---|---|---|---|---|---|---|---|
| I01 | Gap | g = log(O_0/C_{t−1}) | 15m/daily | 09:30 | B continuation ([Plastun](https://ideas.repec.org/p/pre/wpaper/201963.html)); A attention reversal ([BKTZ12](https://bearworks.missouristate.edu/articles-cob/576/)) | `session_anatomy.gap`; stage-1/2 scalar | E, X, S | g/σ_gap (60 sessions); CS rank |
| I02 | Return since open | log(C_k/O_0) | 15m | k+ | C (repo: first half-hour to rest of day slope 0.02, t 0.2) | derivable from `sip_cube` | E | ÷ σ_open→k |
| I03 | Slot-normalized bar return | z_k = r_k/σ_slot(k), r_0 from O_0 | 15m | k+ | A as normalization ([AB97](https://www.sciencedirect.com/science/article/abs/pii/S0927539897000042)) | MISSING (deep models used global z) | every sequence input | as defined |
| I04 | Opening range | OR_hi/OR_lo = max H / min L of the first m bars, m ∈ {1, 2}; position (C_k − OR_lo)/(OR_hi − OR_lo); first close above OR_hi or below OR_lo; width log(OR_hi/OR_lo) | 15m | m+, then k+ | C large caps ([ZBA](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284)); B futures ([HLL13](http://www.econ.umu.se/ueslpnr/ues845.pdf)) | MISSING | E | width ÷ ATR14 |
| I05 | VWAP distance | VWAP_k = Σ_{j≤k} TP_j·V_j / Σ V_j, TP = (H+L+C)/3 (15m proxy); d = log(C_k/VWAP_k); share of bars above VWAP; VWAP crosses so far | 15m | k+1 live | C ([ZA](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/)) | `entry_pilot.distance_vwap` (IEX); `fill_timing` proxy | E, X | d ÷ σ_open→k |
| I06 | Relative volume by slot | RVOL_k = Σ_{j≤k} V_j / mean over the prior 20 sessions of the same cumulative sum; opening RVOL (k = 0, 1) | 15m | k+1 live | B: A monthly ([GKM01](https://sites.duke.edu/sgervais/?p=64)); C intraday | `entry_pilot.relative_volume` (IEX); not in deep models | E, S | log; CS rank |
| I07 | Prior-day levels | log(C_k/PDH), log(C_k/PDL), log(C_k/PDC); first-cross flags | 15m vs daily | k+ | B ([Osler00](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html), [KOW04](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html)) | MISSING | E, X | ÷ ATR14 |
| I08 | Floor pivots | P = (H+L+C)/3 of the prior session; R1 = 2P−L; S1 = 2P−H; R2 = P+(H−L); S2 = P−(H−L); signed distances | 15m vs daily | k+ | C ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/pivot-points)) | MISSING | E | ÷ ATR14 |
| I09 | Camarilla | H3/L3 = C ± 1.1(H−L)/4; H4/L4 = C ± 1.1(H−L)/2 (prior session) | 15m vs daily | k+ | C ([mypivots](https://www.mypivots.com/dictionary/definition/42/camarilla-pivot-points)) | MISSING | E | ÷ ATR14 |
| I10 | Drawdown and run-up | dd_k = log(min_{j≤k} L_j/O_0); ru_k = log(max_{j≤k} H_j/O_0); intraday range position | 15m | k+ | C (repo: −2% by 11:30 continues, −3.4 bp, t −2.5) | `session_anatomy`; `alpaca` (IEX) | E | ÷ σ_open→k |
| I11 | 15-minute EMAs | log(C_k/EMA9), log(C_k/EMA21) on 15m closes seeded on the prior 3 sessions; 3-bar slope; EMA9 crosses so far | 15m | k+ | C (repo IEX: IC 0.029, t 1.6) | `alpaca.session_features` (IEX) | E | ÷ σ |
| I12 | Intraday realized measures | RV_k = Σ z_j²; RS−_k, RS+_k (squares of negative/positive r); max \|z\| | 15m | k+ | A for volatility ([PS15](https://econpapers.repec.org/RePEc:tpr:restat:v:97:y:2015:i:2:p:683-697)); B for returns ([BLZ20](https://ideas.repec.org/a/cup/jfinqa/v55y2020i3p751-781_2.html)) | `entry_pilot.realized_intraday_vol` | E, Z | RS−/RV |
| I13 | Relative strength since open | log(C_k/O_0) − β₆₀·(same for SMH or IGV by theme); also against SPY | 15m | k+ | C intraday; A monthly analog ([MG99](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:4:p:1249-1290)) | MISSING (PatchTST averaged channels) | E, S | ÷ σ |
| I14 | Index half-hours | SPY r_1 = log(P_10:00/C_{t−1}); r_12 = log(P_15:30/P_15:00); SPY since open; SPY VWAP distance | 15m/30m | 10:00 / 15:30 | A historical ([Gao18](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf), [BDLM21](https://academicweb.nd.edu/~zda/intramom.pdf)); ↓ C ([firmtape](https://dev.to/firmtape/intraday-momentum-is-dead-in-the-0dte-era-we-measured-it-on-1085-spx-sessions-43g0)) | MISSING (SPY cube exists) | E (15:30 vs MOC), R | ÷ SPY σ |
| I15 | Intraday breadth | share of the 94 names with C_k > C_{t−1}; share above their own VWAP; mean sign(r_k) ("TICK proxy") | 15m | k+ | C ([TICK](https://www.tradingsim.com/blog/tick-index)); B daily ([Zaremba20](https://www.sciencedirect.com/science/article/pii/S0264999319312982)) | daily only (`deep_stage2.breadth`) | R, E | level |
| I16 | Time and calendar | slot; minutes to close; weekday; FOMC −1/0/+1; OPEX; quad witching; index rebalance days | — | ex ante | B (repo in-sample: quad witching −41 bp, t −3.1) | `calendar.calendar_features`; `day_type` | E, R | one-hot |
| I17 | Dealer gamma sign | net option market-maker gamma (index) | daily | Ct | A conditional ([BDLM21](https://academicweb.nd.edu/~zda/intramom.pdf)) | MISSING (no options history) | R | sign |
| I18 | Closing auction | auction first print against the last regular print; auction volume | session | after 16:00 | B (deviations revert, [BM23](https://ideas.repec.org/a/eee/finmar/v66y2023ics1386418123000502.html)) | `sip_cube.auction_open/auction_volume` | labels only | — |

**Family D — daily location and trend** (daily adjusted panel; `Ct`, or
`C15:30` on the live row for close-auction decisions).

| ID | Feature | Definition (parameters) | TF | PIT | Grade | Repo today | Decisions | Normalization |
|---|---|---|---|---|---|---|---|---|
| D01 | EMA distances | log(C/EMA_n), n ∈ {9, 21, 50, 200}; log(C/SMA200) | daily | Ct | B↓ index rules ([STW99](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf)); A portfolio timing ([HYZ13](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf)) | `technical.technical_features` | S, E | ÷ σ20; CS rank |
| D02 | MAD | SMA21/SMA200 − 1 | daily | Ct | A ([AKS21](https://econpapers.repec.org/RePEc:wly:revfec:v:39:y:2021:i:2:p:127-145)) | partial (EMA distances) | S | CS rank |
| D03 | Trend-factor MA set | log(C/SMA_L), L ∈ {3, 5, 10, 20, 50, 100, 200, 400} | daily | Ct | A ([HZZ16](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html)) | partial | S | CS rank |
| D04 | EMA slopes, stack, crosses | 5-session log slope of EMA 9/21/50/200; stack −3..3; 9/21 and 50/200 cross within 5 sessions | daily | Ct | C↓ (repo: crosses lose, stack ~0) | `technical.technical_features` | control | as is |
| D05 | Bollinger | z = (C − SMA20)/(2σ20); %b; bandwidth 4σ20/SMA20 and its 126-session percentile (squeeze) | daily | Ct | B↓ ([FJQ17](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)) | z: `entry.bollinger_z`, `levels.band_position`, `deep_stage2.band_z`; bandwidth only in `entry_pilot` | E, S | percentile |
| D06 | Keltner | (C − EMA20)/ATR10; squeeze = BB(20, 2) inside KC(20, 1.5·ATR10) | daily | Ct | C ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels)) | MISSING | E | as is |
| D07 | ATR and range volatility | ATR14/C; Parkinson, Garman-Klass, Rogers-Satchell (20-session means) | daily | Ct | A efficiency ([Molnár](http://mmquant.net/wp-content/uploads/2016/09/range_based_estimators.pdf)) | MISSING (`alpha.range_mean_*` is a range mean) | normalization, Z | log |
| D08 | Range position (Donchian) | (C − min L_n)/(max H_n − min L_n), n ∈ {20, 55, 60, 252}; breakout flags | daily | Ct | B ([BLL92](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html)); repo: top of 60-session range t 3.7 (in-sample) | `levels.range_position_60`; `alpha.close_over_max/min_*` | S, E | scale-free |
| D09 | 52-week high/low | log(C/H252), log(C/L252); new high within 5 sessions | daily | Ct | A ([GH04](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html)) with ↓ caveat | `technical.technical_features` | S | CS rank |
| D10 | RSI / stochastic | RSI(14) Wilder; RSI(2); %K(14), %D(3), daily and 15m | daily, 15m | Ct / k+ | B−/C ([CNL14](https://mpra.ub.uni-muenchen.de/54149/1/MPRA_paper_54149.pdf)) | `profit_taking.rsi` (14) only | E, X | /100 |
| D11 | MACD | (EMA12 − EMA26)/σ63, signal EMA9, histogram; Baz multi-scale | daily | Ct | B ([LZR19](https://arxiv.org/abs/1904.04912)) | `technical` `macd_*` (Baz) | S | as defined |
| D12 | ADX/DMI | ADX(14), +DI, −DI (Wilder), daily and 60m | daily | Ct | C ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx)) | MISSING | R, E | /100 |
| D13 | Swing support/resistance | support and resistance distance, signed gap, reward/risk, at-support, confluence, level kind | daily | Ct (swings stamped at t+5) | B ([Osler03](https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html)) | `levels.level_features`, `level_identity` | E, X | ÷ ATR14 |
| D14 | Weekly timeframe | log(C/wEMA9), log(C/wEMA21); close above a rising wEMA21; weekly stack | weekly | Wt | B ([HZZ16](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html)); alignment rules C | `technical`/`levels` (`_weekly_ema`) | S, R | ÷ σ |
| D15 | 12-1 and residual momentum | Σ log r over t−252..t−21; residual on 252-session beta to SPY | daily | Ct | A ([JT93](https://econpapers.repec.org/RePEc:bla:jfinan:v:48:y:1993:i:1:p:65-91), [BHM11](https://econpapers.repec.org/RePEc:eee:empfin:v:18:y:2011:i:3:p:506-521)) | `baselines.residual_momentum(120, 21)`: 252/21 missing | S | CS rank |
| D16 | Capital-gains overhang | As GH05: weekly data. RP_{w} = k⁻¹ Σ_{n=1}^{260} V_{w−n} Π_{τ=1}^{n−1}(1 − V_{w−n+τ}) P_{w−n}, V = weekly turnover (volume / shares outstanding, EDGAR point-in-time), truncated at 260 weeks, k making the weights sum to 1. CGO = (P_{w−2} − RP_{w−1})/P_{w−2}: one-week price lag against bid-ask bounce | weekly | Wt | A ([GH05](https://www-2.rotman.utoronto.ca/facbios/file/momentum_JFE.pdf)) | MISSING | S | CS rank |
| D17 | Volume profile | 20/60-session histogram of 15m volume by price bin (0.25·ATR14): POC, VAH/VAL (70%), high/low-volume nodes; distance to POC; inside-value flag | 15m→daily | Ct | C ([Market Profile](https://en.wikipedia.org/wiki/Market_profile)) | MISSING | E, X | ÷ ATR14 |
| D18 | Round numbers | distance to the nearest $1/$5/$10 multiple, by price level | daily, 15m | k+ | B ([BHJ12](https://econpapers.repec.org/RePEc:inm:ormnsc:v:58:y:2012:i:2:p:413-431)) | MISSING | E | ÷ ATR14 |
| D19 | Candles | hammer, star, engulfing, net over 3 sessions | daily | Ct | C↓ ([MYR06](https://mro.massey.ac.nz/bitstreams/cf13fcfc-21d5-4e4b-89b6-d4f8cf347a84/download)) | `technical.technical_features` | negative control | — |
| D20 | Anchored VWAP | log(C/AVWAP) from the last 8-K 2.02 session, and from the 252-session high/low date | daily/15m | Ct | C ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap)) | MISSING | S, E | ÷ ATR14 |

**Family M — returns, momentum, links.**

| ID | Feature | Definition (parameters) | TF | PIT | Grade | Repo today | Decisions | Normalization |
|---|---|---|---|---|---|---|---|---|
| M01 | Returns | log returns over 1, 5, 10, 20, 60 sessions; minus SPY/QQQ/SMH/IGV | daily | Ct | A ([JT93](https://econpapers.repec.org/RePEc:bla:jfinan:v:48:y:1993:i:1:p:65-91)) | `alpha.alpha_features` | S | CS rank |
| M02 | Theme momentum | theme-basket return over 20/60/120 sessions; name minus theme | daily | Ct | A ([MG99](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:4:p:1249-1290)) | `alpha rel_theme_*`; `baselines.theme_momentum` | S | CS rank |
| M03 | Connected-firm momentum | 21-session return of linked peers. Proxy for shared analyst coverage: same-theme names weighted by 252-session return correlation. Customer links from 10-K "major customer" disclosures where parseable | daily | Ct | A ([AH20](https://ideas.repec.org/a/eee/jfinec/v136y2020i3p649-675.html), [CF08](https://pages.stern.nyu.edu/~afrazzin/pdf/Economic%20Links%20and%20Predictable%20Returns%20-%20Cohen%20and%20Frazzini.pdf)) with ↓ | MISSING | S | CS rank |
| M04 | Overnight/intraday split | Σ gaps and Σ open-to-close over 20/60 sessions; tug-of-war share = share of the last 21 sessions with gap > 0 and open-to-close < 0 | daily from 15m | Ct | A ([LPS19](https://econpapers.repec.org/RePEc:eee:jfinec:v:134:y:2019:i:1:p:192-213), [ABJK22](https://ink.library.smu.edu.sg/lkcsb_research/7712/)) | MISSING (gap per session exists) | S, E | CS rank |
| M05 | MAX | largest daily return in the last 21 sessions | daily | Ct | A ([BCW11](https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf)) | MISSING | S | CS rank |
| M06 | Abnormal volume | log(V_t / mean V_{t−50..t−1}); weekly version | daily | Ct | A ([GKM01](https://sites.duke.edu/sgervais/?p=64)) | `alpha volume_ratio_20/60` | S | CS rank |
| M07 | News-conditioned reversal | 1- and 5-session return × 1[no 8-K in window], and the with-8-K complement | daily | Ct | A ([DLS14](https://econpapers.repec.org/article/inmormnsc/v_3a60_3ay_3a2014_3ai_3a3_3ap_3a658-674.htm), [Savor12](https://econpapers.repec.org/article/eeejfinec/v_3a106_3ay_3a2012_3ai_3a3_3ap_3a635-659.htm)) | MISSING (8-K events in `edgar.py`) | S, E | CS rank |
| M08 | Beta, correlation | 60-session beta and correlation to SPY and SMH | daily | Ct | B | `alpha beta_60`, `corr_*` | Z, R (controls) | as is |

**Family V — volatility and return distribution.**

| ID | Feature | Definition (parameters) | TF | PIT | Grade | Repo today | Decisions | Normalization |
|---|---|---|---|---|---|---|---|---|
| V01 | Realized variance | RV = g² + Σ_k r_k² from 15m; HAR lags 1/5/22 | daily | Ct | A ([ABDL03](https://econpapers.repec.org/RePEc:ecm:emetrp:v:71:y:2003:i:2:p:579-625), [Corsi09](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738)) | partial (stage-1 target; `alpha vol_*` close-to-close) | Z, R, normalization | log |
| V02 | Semivariance, signed jumps | RS+, RS−, SJ = RS+ − RS−, each ÷ RV; 5/20-session means | daily | Ct | A volatility ([PS15](https://econpapers.repec.org/RePEc:tpr:restat:v:97:y:2015:i:2:p:683-697)); B returns ([BLZ20](https://ideas.repec.org/a/cup/jfinqa/v55y2020i3p751-781_2.html)) | MISSING | S, Z | CS rank |
| V03 | Realized skewness | √n·Σr³ / RV^{3/2} over the week's 15m returns | weekly | Wt | A ([ACJV15](https://ideas.repec.org/a/eee/jfinec/v118y2015i1p135-167.html)) | MISSING | S | CS rank |
| V04 | Volatility ratio | vol5/vol60; standard deviation of daily RV over 20 sessions | daily | Ct | B | `alpha vol_ratio_5_60` | R | log |
| V05 | VIX state | level, 5-day change, VIX / realized volatility of SPY | daily | Ct | A ([Nagel12](https://www.nber.org/papers/w17653)) | `macro.macro_features` | R, E | z |
| V06 | Existing forecasts | stage-1 next-session volatility; stage-2 drawdown20 | daily | Ct | repo (R² 0.27; IC 0.09-0.15) | `vol_forecasts.npz`, `drawdown_forecasts.npz` | E conditioning only (Z lost) | as is |

**Family X — events, text, positioning.**

| ID | Feature | Definition (parameters) | TF | PIT | Grade | Repo today | Decisions | Normalization |
|---|---|---|---|---|---|---|---|---|
| X01 | Earnings clock | sessions since and until 8-K 2.02; earnings-day gap; reaction residual | event | 8-K | B↓ ([Martineau22](https://econpapers.repec.org/article/nowjnlcfr/104.00000122.htm)) | `edgar.py` | S, E | as is |
| X02 | Release tone | tone blend (guidance, demand, change) | event | release plus scoring | repo: IC 0.044, t 3.0 (in-sample) | `language.py` | S | as is |
| X03 | Fundamentals | EDGAR point-in-time features | quarterly | acceptance | repo | `fundamental_features.py` | S | CS rank |
| X04 | Short interest | SI / shares outstanding; days to cover = SI / ADV | semi-monthly | publication (lagged) | A aggregate ([RRZ16](https://ideas.repec.org/a/eee/jfinec/v121y2016i1p46-65.html)); B cross-section ([Hong et al.](https://www.nber.org/system/files/working_papers/w21166/w21166.pdf)) | MISSING (no data) | S, R | CS rank |
| X05 | Retail attention | abnormal volume × \|gap\| × 1[no 8-K] | daily | 09:30 / Ct | A ([Barber22](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190), [BKTZ12](https://bearworks.missouristate.edu/articles-cob/576/)) | MISSING | E (do not pay the open), S | CS rank |

**Family G — desk state** (internal, no external grade).

| ID | Feature | Definition (parameters) | TF | PIT | Repo today | Decisions |
|---|---|---|---|---|---|---|
| G01 | Grade and stances | grade one-hot; each analyst's stance; count bullish | daily | Ct (nightly) | stage-2 scalars | S, X |
| G02 | Grade age | sessions since the last grade change; flips in the last 60 sessions | daily | Ct | derivable (`decision_history.py`) | X |
| G03 | Distance to flip | per analyst, (score − stance threshold) / sd(score, 60) | daily | Ct | MISSING | X (downgrade hazard) |
| G04 | Regime | exposure, confidence, participation percentile, AI drawdown, leader, tightening | daily | Ct | `regime.py`; `deep_stage2.regime_scalars` | R |

### 3.3 Normalization: making levels visible and comparable

The old sequence models saw **scale-free returns only**, without the overnight
gaps. That hides every level a trader reads. The rules for the retrain:

1. **Levels as log ratios in volatility units.** Every level is expressed as
   log(price/level), divided by ATR14 or the matching σ. "1.5 ATR above VWAP"
   means the same thing for a $20 and a $900 name, and in 2018 and 2025. JKX
   attribute part of the CNN's advantage to exactly this implicit scaling
   ([JKX](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf)).
2. **Intraday returns and volume by slot.** Divide by σ_slot(k) and by the
   trailing same-slot volume; the opening bar should not dominate
   ([Andersen-Bollerslev 1997](https://www.sciencedirect.com/science/article/abs/pii/S0927539897000042)).
3. **Gaps are part of the path.** In sequences, either insert the overnight
   return as its own step before each session's first bar, or add it as a
   channel on slot 0.
4. **Cross-sectional ranks per date** (rank-Gauss) for every selection feature
   and target, computed within that date's point-in-time eligible names. Keep
   the time-series version too, for entry features: an entry decision is per
   order, not cross-sectional.
5. **Winsorize** raw features at 0.5/99.5% using training-fold quantiles only.
   Nets get robust z-scores (median/IQR) from training folds. Trees need no
   scaling, but they still need the volatility-normalized versions, because
   comparability across dates is not a monotone transform of one column.
6. **No feature selection after the fact.** The whole catalogue goes in.
   Importances (permutation or SHAP) are reported, never used to prune on test
   results. Trees tolerate uninformative columns
   ([Grinsztajn et al.](https://arxiv.org/abs/2207.08815)).

### 3.4 Data gaps (what cannot be built today)

- **No pre-market data.** The SIP cube is the regular session plus the closing
  auction (`sip_cube.py`), so pre-market highs and flags cannot be built.
- **No bar-level VWAP or trade count stored.** The store keeps OHLCV
  (`alpaca.IntradayBar`), although the bars endpoint returns `vw` and `n`
  ([Alpaca docs](https://docs.alpaca.markets/docs/historical-stock-data-1)).
  VWAP is therefore the typical-price proxy, and fetching `vw` would need a
  re-fetch.
- **No options or dealer-gamma history, no short interest, no analyst coverage
  or news feed** (only EDGAR 8-K).
- **Early closes are excluded** from the cubes: 21 per name (session anatomy).
- **Live volume.** SIP bars arrive 15 minutes late on the free plan; IEX quotes
  carry about 2.5% of volume.

---

## 4. Targets aligned to decisions

The rule: **a target is the quantity the decision earns, in the decision's
units, on rows the decision faces.** Stage 1's next-session open-to-close rank
broke it: the book never trades that quantity. To get enough labels, train on
every point-in-time eligible (name, session) row, about 81-83k, with the grade
as a feature. Evaluate only on the orders the `/4` policy actually generates.

| Decision | ID | Definition | Train rows / evaluation rows | Horizon; purge | Loss | Decision rule | Primary metric |
|---|---|---|---|---|---|---|---|
| Entry: take the dip trigger or wait for the close | T-E1 | Let k* be the first slot whose close ≤ 0.99·O_0 (the board's trigger). P_fill is the price `fill_timing._dip_or_close_fill` uses, the trigger bar's close, so candidate and control share one convention; a robustness run moves both to the open of slot k*+1. y = log(P_auction/P_fill): positive means the trigger fill beat the close | eligible name-sessions where the trigger fires (the dip filled 41% of `/4` orders on 2016-2023 and 49% on 2024-2026) / `/4` buy orders | intraday; purge 1 + embargo 5 | L2 on winsorized y | take the trigger if ŷ > 0, else the close | paired bp/d against `dip_or_close`; bp per trigger-fired order |
| Exit: take the pop or wait for the close | T-X1 | mirror of T-E1 for SELL/TRIM (first close ≥ 1.01·O_0), y = log(P_fill/P_auction) | eligible sessions where the pop fires / `/4` sells | intraday | L2 | take the pop if ŷ > 0 | paired bp/d against pop-or-close |
| Entry: 15:30 or MOC | T-E3 | y = log(P_auction/P_15:30) for the name and for SPY; inputs I14 and I15 + gamma proxy where available | all eligible sessions / `/4` orders reaching the close fallback | intraday | L2 (ridge + LightGBM) | buy at 15:30 if ŷ > 0 (sells mirrored) | paired bp/d against `dip_or_close` |
| Level diagnostic | T-B1 | first touch of a level L ∈ {PDL, PDH, VWAP ± 1σ, OR low/high, swing support, lower band} at slot k: +1 if a later close ≥ L + 0.25·ATR comes before one ≤ L − 0.25·ATR, −1 for the opposite, 0 if neither by 15:45 (triple barrier, [López de Prado](https://philpapers.org/rec/LPEAIF)) | all touches / — | intraday | multinomial | none: diagnostic only | AUC by level type, 2016-2023 halves |
| Selection overlay | T-S1 | y = CS rank of [log(O_{t+21}/O_{t+1}) − the same for the equal weight of point-in-time eligible names] | all eligible name-sessions / A/A+ names | 20 sessions; purge 20 + embargo 5 | L2 on rank-Gauss (GKX-style) | drop A/A+ names in the bottom decile of ŷ and re-spread equal weight; fund the redeploy leg in ŷ order | paired bp/session against `graded-equal-weight/4` |
| Redeploy order | T-S3 | as T-S1 over 5 sessions | same | 5; purge 5 + 5 | L2 | funding order when cash is short | sub-test of T-S1 |
| Sizing | — | none registered: volatility sizing, vol targeting and trims all lost (`vol-sizing-2026-09-27.md`, `profit-taking-2026-09-27.md`) | — | — | — | — | — |
| Regime | — | only T-E3 at index level; day-type exposure already has its own study (`day_type.py`) | — | — | — | — | — |

Why these, and not others:

1. **T-E1 and T-X1** are exactly the choice the board makes today: take the
   1% level fill, or fall back to the close. The ML entry-level study moved the
   level (a volatility-scaled k) and could not tell direction. T-E1 keeps the
   board's level and asks the only remaining question: on *this* trigger, will
   the close be lower or higher than the fill? It conditions on what the dip
   literature says matters: news or no news, relative volume, VIX, gap, level
   location, index flow
   ([Savor 2012](https://econpapers.repec.org/article/eeejfinec/v_3a106_3ay_3a2012_3ai_3a3_3ap_3a635-659.htm);
   [Nagel 2012](https://www.nber.org/papers/w17653);
   [Da et al. 2014](https://econpapers.repec.org/article/inmormnsc/v_3a60_3ay_3a2014_3ai_3a3_3ap_3a658-674.htm)).
2. **T-E3** is the intraday direction signal with a published record
   ([Gao et al.](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf)).
   It is also the next question the ML entry-level study already registered.
3. **T-S1** measures what the book earns from holding a name, relative to the
   hurdle every arm faces. The target runs open to open because the scorecard's
   plain execution fills at the open. The 20-session horizon matches the reset
   clock and the literature's advice to train on the holding horizon, to keep
   turnover down
   ([Blitz et al. 2023](https://www.robeco.com/en-int/insights/2023/07/the-term-structure-of-machine-learning-alpha)).
   The review of 2026-09-26 recommended the same label
   (`learned_policy.relative_open_labels`).
4. **Why no drawdown or downgrade target for selling.** Every sell-side use of
   forecastable risk lost on this book: drop the worst drawdown decile −1.6 to
   −2.3 bp/session, trims −0.1 to −1.1 bp/d. The names most likely to fall are
   the ones earning the return (stage 2, profit taking). T-B1 stays a
   diagnostic, so that a level feature can show information without a new
   selling rule being inferred from it.

---

## 5. Training protocol

### 5.1 Data, windows, splits

- **Rows.** Point-in-time membership (`point_in_time.eligibility`), SIP
  complete sessions 2016-02 to 2026-09, and the daily panel from 2015 for
  warm-up. Trees handle missing values natively. Nets impute the training
  median and add a missing flag.
- **Windows.** 2016-2023 is the choosing window. 2024-2026 is reported only:
  the walk-forward runs through it unchanged, and nothing is ever chosen on it.
- **Outer walk-forward.** Expanding window. The first fit comes after 500
  sessions (first test about 2018-02, as in stages 1 and 2). Refit every 63
  sessions for trees and every 252 sessions for the CNN and sequence model
  (compute; JKX fit once and never refit). Predictions are out of sample only.
- **Purge and embargo.** Remove every training row whose label window
  overlaps the test block (purge = label horizon H: 20 for T-S1, 5 for T-S3, 1
  for the intraday targets). Add a 5-session embargo for autocorrelated
  features ([purged CV](https://en.wikipedia.org/wiki/Purged_cross-validation);
  [López de Prado 2018](https://philpapers.org/rec/LPEAIF)).
- **Nested validation.** Inside each outer training window, the last 252
  sessions, after a purge of H, form the validation block. It is used for early
  stopping and for choosing one configuration from the grid. The chosen
  configuration is refit on the whole outer window with the early-stopped
  number of rounds or epochs, scaled by the ratio of training rows. Test blocks
  never touch any choice.
- **CPCV for overfitting.** On 2016-2023 only, a combinatorially symmetric
  split (S = 16 blocks) of each target's trial-return matrix gives the
  probability of backtest overfitting
  ([Bailey et al.](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf);
  `candidate_stats.probability_of_backtest_overfitting`).

### 5.2 Model families and the pre-registered grids

**M1: LightGBM, the primary baseline**, on the tabular catalogue (Families
I, D, M, V, X, G).

- **Objective.** L2 regression for T-E1, T-X1, T-E3 and T-S1/T-S3. Multiclass
  for T-B1.
- **Grid, 8 configurations:** `num_leaves` ∈ {15, 63} × `learning_rate` ∈
  {0.02, 0.05} × `min_data_in_leaf` ∈ {200, 1000}.
- **Fixed settings:** `feature_fraction` 0.7, `bagging_fraction` 0.7,
  `bagging_freq` 1, `lambda_l2` 10, `max_bin` 255, `max_depth` −1, at most 3,000
  rounds with early stopping after 200 rounds without improvement in the
  validation metric: mean decision value for E/X, mean daily rank IC for S.
  These are the documented overfitting controls
  ([LightGBM tuning](https://lightgbm.readthedocs.io/en/stable/Parameters-Tuning.html)).
- **Ensemble.** 5 seeds (`seed`, `bagging_seed`, `feature_fraction_seed`),
  averaged.

**M2: the JKX chart CNN, run exactly as published**
([JKX](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf)).

- **T-S1 images.** Daily I5 (32×15, 2 blocks) and I20 (64×60, 3 blocks). OHLC
  at 3 px a day, a moving average of the image length, and volume in the bottom
  fifth, rendered from `chart_cnn.render_chart` extended to 5 days.
- **Label.** 1 if the T-S1 relative return is above the date's median.
- **Training.** Xavier initialization, batch norm, leaky ReLU, 50% dropout on
  the fully connected layer; Adam at 1e-5, batch 128; stop when validation loss
  has not improved for 2 epochs (at most 100); **5 independently trained
  networks averaged**.
- **Grid.** {I5, I20}: 2 configurations.
- **Exploratory extension for T-E1.** One-session images of the 26 bars (78×64
  px) with the VWAP line, prior-day high/low/close lines and the opening-range
  box, 2 blocks, same training rules: 1 configuration. It is flagged as an
  extension and counted as a trial.

**M3: a level-aware sequence model** that fixes the §0.1 defects.

- **Inputs.** For E/X, 5 sessions × 26 bars; for S, 60 sessions × 26 bars. The
  overnight gap is a step before each session. Channels: z_k (I03), log(C/VWAP),
  log(C/PDC), log(C/PDH), log(C/PDL) in ATR units, log(C/EMA21 on 15m), log
  RVOL_k, name minus SMH/IGV slot return, SPY slot return. Learned slot and
  session embeddings. A daily-feature MLP branch (Families D, M, V, X, G) is
  concatenated before the head.
- **Architecture.** A channel-mixing TCN with kernel 3 and dilations 1, 2, 4,
  8, 16 (receptive field 63 steps), attention pooling with a learned query plus
  the last step, and a 2-layer head.
- **Grid, 8 configurations:** AdamW `lr` ∈ {3e-4, 1e-3} (cosine decay, 5%
  warm-up) × dropout ∈ {0.1, 0.3} × width ∈ {32, 64}.
- **Fixed settings:** weight decay 1e-2, batch 512, gradient clipping 1.0, at
  most 60 epochs, early stopping patience 6 on validation loss, best weights
  restored. Grid selection uses 1 seed; the chosen configuration is trained with
  **5 seeds, averaged**.

**Determinism for M2 and M3.** Seeds recorded;
`torch.use_deterministic_algorithms(True)`,
`torch.backends.cudnn.benchmark = False`. Reproducibility across GPUs and
releases is not guaranteed
([PyTorch](https://docs.pytorch.org/docs/main/notes/randomness.html)), so
per-seed out-of-sample predictions are saved and the seed spread is reported.
A result whose decision-test mean changes sign in 2 or more of the 5 seeds is
not accepted.

### 5.3 What each trial is scored on

- **Diagnostics, never a pass.** IC or AUC per target on 2016-2023, split into
  2016-2019 and 2020-2023, with Newey-West t at lag 20
  (`candidate_stats.hac_t`), and the residual after controlling for the V06
  volatility forecast (a signal that vanishes there is volatility, not
  direction).
- **Decision tests.** Each registered rule of §4 runs through the existing
  engines. Entry and exit use `market_fill_timing` on the `/4` policy's own
  orders, SIP cube fills, 20 offsets. Selection uses `market_pit_scorecard`
  with the live execution set, 20 offsets. Candidate and control always share
  the fill convention of `fill_timing.py`: a triggered order fills at the
  trigger bar's close, otherwise at the official close. That is slightly
  optimistic for a person acting after the bar closes. A robustness run
  therefore moves both to the next bar's open (`timing_research.py`
  convention), and a pass must survive it.
- **Costs.** 10 bp and 25 bp one way, as always. **Also at 16 bp**, the
  operator-reported live slippage. A pass must hold at 16 and at 25.
- **Adoption floors, as fixed by the operator.**
  - **Entry and exit:** beat the board's `dip_or_close` (and pop-or-close for
    sells) by **≥ +2 bp a day with Newey-West t ≥ 2 on 2016-2023, and not
    worse on 2024-2026.**
  - **Selection:** beat `graded-equal-weight/4` by **≥ +2 bp a session with t
    ≥ 2.0 on 2016-2023 at 25 bp, not negative on 2024-2026, and above the
    control in at least 15 of 20 offsets.**
- **Registered per-fill diagnostic.** Candidate minus control in **bp per
  trigger-fired order**, with the t clustered by date. §6.3 shows that the
  book floor needs 59-106 bp per order, so a timing model can be right and
  still immaterial. A per-fill gain of **at least 25 bp with t ≥ 3** that fails
  the book floor is written up as "RECORD: real but immaterial". It changes
  nothing live.
- **Multiplicity.** A candidate that passes a floor also needs a **deflated
  Sharpe ratio ≥ 0.95 at N = 44** (this study's registered trials,
  `candidate_stats.deflated_sharpe`, which uses the across-trial variance of
  Sharpe ratios), **PBO < 0.2**, and an SPA p-value < 0.10 against the control
  ([Hansen 2005](https://cdr.lib.unc.edu/downloads/zp38wf793);
  `candidate_stats.superior_predictive_ability`). The deflated Sharpe is also
  reported at the book's cumulative count (§5.4).

### 5.4 Multiplicity accounting

**Registered trials in this study** (each is one (target, family,
configuration) cell):

| Target | M1 LightGBM | M2 JKX CNN | M3 sequence | Other | Total |
|---|---|---|---|---|---|
| T-E1 | 8 | 1 (intraday image, exploratory) | 8 | — | 17 |
| T-X1 | 8 | — | — | — | 8 |
| T-E3 | — | — | — | 1 (ridge on I14-I16) | 1 |
| T-S1 | 8 | 2 (I5, I20) | 8 | — | 18 |
| **Total** | 24 | 3 | 16 | 1 | **44** |

- Nested validation reduces this to **8 outer candidates**, one per target and
  family. Both counts are reported.
- **The book's cumulative count is about 274.** 146 trials were counted by
  2026-09-26 (`pit-arms-2026-09-26.md`: 6 arms plus 140 earlier experiments),
  84 were registered on 2026-09-26/28 (cap sweep 8, stage 1 8, stage 2 16,
  execution timing 7, catastrophe stop 7, execution ablation 10, vol sizing 7,
  profit taking 7, mid-cycle 10, ML entry level 4), and this study adds 44.
- **What the best null trial looks like.** The expected maximum of N
  independent standard-normal t-statistics, (1−γ)Φ⁻¹(1−1/N) + γΦ⁻¹(1−1/(Ne)),
  is ~1.46 at N = 8, ~2.2 at N = 44 and ~2.9 at N = 274
  ([Bailey-López de Prado 2014](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)).
  A t of 2.0 is below what the best of this study's own null trials would show,
  which is why the deflated-Sharpe and PBO conditions sit next to the
  operator's t ≥ 2. Harvey, Liu and Zhu reach the same place from the factor
  literature: t > 3.0
  ([HLZ 2016](https://www.nber.org/papers/w20592)).
- **Frozen before the run:** the feature list (§3.2), grids, seeds, windows,
  purges and floors. Any change is a new trial, counted
  ([Arnott-Harvey-Markowitz](https://people.duke.edu/~charvey/Research/Published_Papers/P138_A_backtesting_protocol.pdf)).

### 5.5 Order of work

1. **Features.** Build Families I, D, M, V, X and G with the repo's causality
   test: tamper with session t+1 and assert that row t is unchanged. Add a
   point-in-time test for the `C15:30` recomputation. Export one dataset per
   target.
2. **Diagnostics (2016-2023 only).** Univariate IC or AUC by feature and
   target. Measure the 20-session cross-sectional dispersion needed for the
   §6.3 arithmetic. Re-measure the Gao and Baltussen regressions on our SIP SPY
   bars for 2016-2023 and 2024-2026 before T-E3 is run. These are diagnostics;
   they cannot promote anything.
3. **M1** on every target, with its decision tests.
4. **M2 and M3** on T-E1 and T-S1 regardless of M1's outcome. This is the fair
   test of the operator's claim about sequence models with the right inputs.
   Comparing them with M1 on the same decision test is the result.
5. **Write-up:** one verdict per trial, and PASS / RECORD / INSUFFICIENT
   EVIDENCE per target.

### 5.6 Compute

- **M1.** About 81k rows × about 150 columns, 34 folds × 8 configurations × 5
  seeds: minutes to an hour on CPU (Spark or desktop).
- **M3.** Stage 2's CNN took 21 minutes for 34 folds on the RTX 5080. With
  annual refits and 8 + 5 runs per target, expect about 3-5 hours per target.
- **M2.** 83k 64×60 images (about 320 MB); JKX's lr 1e-5 converges slowly, so
  expect hours per seed on the 5080.
- **Scheduling.** GPU jobs run one at a time on a Spark, whose GPU is shared
  with the LLM server (stage-1 compute notes); long runs go to the RTX 5080.

---

## 6. Gaps and honest priors

### 6.1 The operator's suspected missing inputs, one by one

| Suspected missing input | Fed to a learner before? | Literature | Prior that it adds out-of-sample decision value here |
|---|---|---|---|
| EMAs 9/21/50/200, slopes, crosses | yes: 33-column set to LightGBM, MLP and a cross-sectional net (09-05); in the technical analyst's evidence behind `hgb_desk`; not in the deep models | index rules ↓; cross-sectional MA distance and trend factor A (monthly) | selection: low to moderate, mostly already inside the grade; timing: very low |
| Bollinger | yes: band position (a leg of the technical analyst), stage-2 `band_z`, entry triggers, entry pilot | profits vanished after popularization (B↓) | low |
| Multi-timeframe trend | yes: weekly and daily trend (`levels.py`) is the grade's strongest location leg | trend factor A; alignment rules C | low incremental: it is already in the book |
| Support/resistance zones | yes: `levels.py` in the cross-sectional net and the desk evidence | order clustering at levels B (FX, NYSE depth) | low for return; possible for bounce-or-break risk (T-B1) |
| Day-trading technicals (VWAP, ORB, relative volume, pivots, prior-day levels) | partly: VWAP distance and relative volume on IEX in the entry pilot (no edge); never in the SIP deep models | no peer-reviewed large-cap evidence (C); ORB's edge is relative-volume selection; index late-day momentum A↓ | low; worth one proper test as conditioning inputs to T-E1 |
| Overnight gaps inside the history | no: dropped from every sequence | overnight/intraday decomposition A | moderate for selection (cheap: M04) |
| Relative volume | no in deep models; IEX version in the pilot | monthly A; intraday C | low to moderate, as a conditioning variable |
| Proper training (early stopping, ensembles, level-aware architecture) | no for stages 1/2; partial for the chart-CNN replica (patience 2, at most 5 epochs, one seed); not audited for the September tree sweeps | ensembles and early stopping are the published recipe (GKX, JKX) | removes noise (seed spread 0.008-0.0125) but adds no signal by itself |

### 6.2 What was genuinely missing

The nine structural defects of §0.1 are real, and a fair test needs all of them
fixed. They are *necessary* for the operator's hypothesis to be tested at all.
There is no evidence they are *sufficient* for a result. The inputs the
literature grades A for this book's horizon are the slow cross-sectional
features missing today:

- MAD 21/200 (D02) and the trend-factor moving-average set (D03);
- 12-1 residual momentum (D15; 120/21 is not 252/21);
- capital-gains overhang (D16);
- the overnight/intraday split and tug of war (M04);
- MAX (M05);
- news-conditioned reversal (M07);
- realized semivariance and skewness (V02, V03);
- connected-firm momentum (M03).

These are chart-derived, and they belong to selection, not to the 15-minute
board.

### 6.3 How much the decisions can move the book

- **Entry and exit timing.**
  - The `/4` book placed 758 orders in the 2,012 sessions of 2016-2023, 0.377
    a session, and 180 in the 686 sessions of 2024-2026, 0.262 a session, at
    about 5-9% of NAV each (`scorecards/ml_entry_level.json`, `dip_orders`).
  - A per-order gain of x bp adds (orders per session) × weight × x to the
    book. To add +2 bp a day, x must be 59-106 bp in 2016-2023 and 85-152 bp in
    2024-2026.
  - For scale: the session's open-to-close standard deviation is 186-235 bp;
    fill windows differ by 1-4 bp in expectation (session anatomy); the dip
    fill beat the close by −8.7 bp per dip fill in 2016-2023 and +36.0 in
    2024-2026.
  - **The entry floor is out of reach for any plausible timing model.** That is
    why §5.3 registers the per-fill diagnostic.
- **Selection.**
  - With 20-session cross-sectional dispersion σ_xs of about 8-10%
    (an assumption, to be measured in step 2 of §5.5) and a top-12-of-60
    selection intensity φ(Φ⁻¹(0.8))/0.2 = 1.40, an incremental rank IC of 0.03
    buys about 0.03 × 9% × 1.40 ≈ 0.38% per 20 sessions, about 1.9 bp a session
    gross.
  - Turnover at 10-25 bp costs roughly 0.3-0.6 bp a session.
  - The overlay therefore needs an incremental IC of about 0.035-0.04 over the
    grade. The grade itself measured about 0.035, in-sample and on survivors
    (NEXT_SESSION 2026-09-05 night). Trees on technicals reached 0.010-0.019.

### 6.4 Priors, with reasons

| Outcome | Prior |
|---|---|
| T-S1 overlay passes the selection floor, the deflated Sharpe and PBO | ~10% |
| T-E1 switch passes the +2 bp/d entry floor | ~3% |
| T-E1 reaches the per-fill diagnostic (≥ 25 bp per order, t ≥ 3) | ~15% |
| T-E3 15:30-vs-MOC switch passes | ~5% |
| At least one honest pass across the study | ~12-15% |
| A deep model (M2 or M3) beats LightGBM on the same decision test by ≥ 0.5 bp/d, given that some signal exists | ~20% |

Reasons:

1. **The book's return is mostly beta to a hot sector.** Holding every
   point-in-time member returned 27.7% on 2016-2023. The grade adds about 2
   points (t 1.5), and everything built on top of it has lost: sizing, trims,
   stops, concentration.
2. **The literature puts technical predictability where this book is not.**
   It lives in small, illiquid, high-turnover names (JKX value-weighted Sharpe
   0.49; [Avramov et al.](https://econpapers.repec.org/RePEc:inm:ormnsc:v:69:y:2023:i:5:p:2587-2619)),
   at minutes-scale horizons for large caps
   ([Aït-Sahalia et al.](https://www.nber.org/system/files/working_papers/w30366/w30366.pdf)),
   and it decays after publication
   ([McLean-Pontiff](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary)).
3. **The repo's own record.** More than ten learner and feature-set
   combinations (§0.1) have converged on rank IC of about 0.01-0.02 for
   direction, on daily and 15-minute data alike. The richer inputs of stage 2 bought *risk* forecasts
   (drawdown IC 0.09-0.15), not direction.
4. **The decisions have little leverage** (§6.3).
5. **The case for trying anyway.** Two classes of input have never been tested
   fairly. The slow cross-sectional set of §6.2 is A-graded for the selection
   horizon. Gap-aware, level-relative intraday state is C-graded, but it is
   exactly the operator's hypothesis, and the deep models' blind spots mean it
   has not yet been tested. A clean
   negative from this protocol would close it with evidence, which is worth the
   compute.

### 6.5 What would change these priors

- Step-2 diagnostics show a T-E1 feature, such as relative volume at the
  trigger, no-news × drawdown, or VWAP distance, with |IC| ≥ 0.03 in *both*
  2016-2019 and 2020-2023. The per-fill prior would then rise from ~15% to
  ~30%. The book floor stays out of reach (§6.3).
- A slow feature from §6.2 adds rank IC ≥ 0.02 over the grade at 20 sessions,
  in both halves of 2016-2023. The selection prior would then rise to about 20%.
- The SIP SPY re-measurement shows the Gao slope still positive in 2024-2026 at
  t ≥ 2. T-E3 would become the most promising cheap trial.

---

## References

Every link was opened while preparing this note, except where §"Not accessed"
says otherwise.

**Machine learning and asset pricing.**
[GKX 2020](https://dachxiu.chicagobooth.edu/download/ML.pdf) ·
[JKX 2023](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf) ·
[JKX replication](https://github.com/George-hardworking/reimaging-price-trends-replication-and-extension) ·
[Murray-Xia-Xiao 2024](https://ideas.repec.org/a/eee/jfinec/v153y2024ics0304405x2400014x.html) ·
[Kelly-Malamud-Zhou 2024](https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13298) ·
[Nagel 2025](https://ideas.repec.org/p/nbr/nberwo/34104.html) ·
[Krauss-Do-Huck 2017](https://econpapers.repec.org/article/eeeejores/v_3a259_3ay_3a2017_3ai_3a2_3ap_3a689-702.htm) ·
[Fischer-Krauss 2018](https://www.sciencedirect.com/science/article/abs/pii/S0377221717310652) ·
[Avramov-Cheng-Metzker 2023](https://econpapers.repec.org/RePEc:inm:ormnsc:v:69:y:2023:i:5:p:2587-2619) ·
[Blitz et al. 2023](https://www.robeco.com/en-int/insights/2023/07/the-term-structure-of-machine-learning-alpha) ·
[Lim-Zohren-Roberts 2019](https://arxiv.org/abs/1904.04912) ·
[Poh et al. 2021](https://arxiv.org/pdf/2012.07149) ·
[Grinsztajn et al. 2022](https://arxiv.org/abs/2207.08815)

**Intraday.**
[Gao-Han-Li-Zhou 2018](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/ee7dac49-530b-4950-b5d0-e0b5eee08f2e.pdf) ·
[Baltussen et al. 2021](https://academicweb.nd.edu/~zda/intramom.pdf) ·
[Heston-Korajczyk-Sadka 2010](https://www.bauer.uh.edu/departments/finance/documents/Heston-Korajczyk-Sadka-jf-2010-01-07.pdf) ·
[Aït-Sahalia et al. 2022](https://www.nber.org/system/files/working_papers/w30366/w30366.pdf) ·
[Chinco et al. 2019](https://ideas.repec.org/a/bla/jfinan/v74y2019i1p449-492.html) ·
[Aleti-Bollerslev-Siggaard](https://public.econ.duke.edu/~boller/Papers/MS_2025.pdf) ·
[Liu-Stentoft](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4496917) ·
[Andersen-Bollerslev 1997](https://www.sciencedirect.com/science/article/abs/pii/S0927539897000042) ·
[Bogousslavsky-Muravyev 2023](https://ideas.repec.org/a/eee/finmar/v66y2023ics1386418123000502.html) ·
[Berkman et al. 2012](https://bearworks.missouristate.edu/articles-cob/576/) ·
[Grant-Wolf-Yu 2005](https://digitalcommons.montclair.edu/acctg-finance-facpubs/70/) ·
[Lou-Polk-Skouras 2019](https://econpapers.repec.org/RePEc:eee:jfinec:v:134:y:2019:i:1:p:192-213) ·
[Akbas et al. 2022](https://ink.library.smu.edu.sg/lkcsb_research/7712/) ·
[Plastun et al.](https://ideas.repec.org/p/pre/wpaper/201963.html) ·
[Elm Wealth](https://elmwealth.com/night-moves-overnight-drift/)

**Technical analysis.**
[Brock-Lakonishok-LeBaron 1992](https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html) ·
[Sullivan-Timmermann-White 1999](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Sullivan_Timmermann_White.pdf) ·
[Bajgrowicz-Scaillet 2012](https://access.archive-ouverte.unige.ch/access/metadata/c0c2aa38-f0bf-430e-b994-dbe8bb53fb13/download) ·
[Park-Irwin 2007](https://experts.illinois.edu/en/publications/what-do-we-know-about-the-profitability-of-technical-analysis/) ·
[Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf) ·
[Savin-Weller-Zvingelis 2007](https://www.biz.uiowa.edu/faculty/gsavin/papers/hsrevision_paw_10%2019%2006.pdf) ·
[Han-Yang-Zhou 2013](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf) ·
[Han-Zhou-Zhu 2016](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html) ·
[Avramov-Kaplanski-Subrahmanyam 2021](https://econpapers.repec.org/RePEc:wly:revfec:v:39:y:2021:i:2:p:127-145) ·
[Neely-Rapach-Tu-Zhou 2014](https://ideas.repec.org/a/inm/ormnsc/v60y2014i7p1772-1791.html) ·
[Moskowitz-Ooi-Pedersen 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) ·
[Huang et al. 2020](https://down.aefweb.net/WorkingPapers/w717.pdf) ·
[Hurst-Ooi-Pedersen 2017](https://www.aqr.com/Insights/Research/Journal-Article/A-Century-of-Evidence-on-Trend-Following-Investing) ·
[George-Hwang 2004](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html) ·
[52WH revisited (WP)](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/576995/Haoxu-Wang-paper_NZFM.pdf) ·
[Osler 2000](https://www.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.html) ·
[Osler 2003](https://ideas.repec.org/a/bla/jfinan/v58y2003i5p1791-1819.html) ·
[Kavajecz-Odders-White 2004](https://ideas.repec.org/a/oup/rfinst/v17y2004i4p1043-1071.html) ·
[Bhattacharya-Holden-Jacobsen 2012](https://econpapers.repec.org/RePEc:inm:ormnsc:v:58:y:2012:i:2:p:413-431) ·
[Grinblatt-Han 2005](https://www-2.rotman.utoronto.ca/facbios/file/momentum_JFE.pdf) ·
[Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf) ·
[Marshall-Young-Rose 2006](https://mro.massey.ac.nz/bitstreams/cf13fcfc-21d5-4e4b-89b6-d4f8cf347a84/download) ·
[Chong-Ng-Liew 2014](https://mpra.ub.uni-muenchen.de/54149/1/MPRA_paper_54149.pdf) ·
[Holmberg et al. 2013](http://www.econ.umu.se/ueslpnr/ues845.pdf)

**Momentum, reversal and links.**
[Jegadeesh-Titman 1993](https://econpapers.repec.org/RePEc:bla:jfinan:v:48:y:1993:i:1:p:65-91) ·
[Blitz-Huij-Martens 2011](https://econpapers.repec.org/RePEc:eee:empfin:v:18:y:2011:i:3:p:506-521) ·
[Moskowitz-Grinblatt 1999](https://econpapers.repec.org/RePEc:bla:jfinan:v:54:y:1999:i:4:p:1249-1290) ·
[Ali-Hirshleifer 2020](https://ideas.repec.org/a/eee/jfinec/v136y2020i3p649-675.html) ·
[Cohen-Frazzini 2008](https://pages.stern.nyu.edu/~afrazzin/pdf/Economic%20Links%20and%20Predictable%20Returns%20-%20Cohen%20and%20Frazzini.pdf) ·
[Nagel 2012](https://www.nber.org/papers/w17653) ·
[Da-Liu-Schaumburg 2014](https://econpapers.repec.org/article/inmormnsc/v_3a60_3ay_3a2014_3ai_3a3_3ap_3a658-674.htm) ·
[Savor 2012](https://econpapers.repec.org/article/eeejfinec/v_3a106_3ay_3a2012_3ai_3a3_3ap_3a635-659.htm) ·
[Bali-Cakici-Whitelaw 2011](https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf) ·
[Gervais-Kaniel-Mingelgrin 2001](https://sites.duke.edu/sgervais/?p=64) ·
[Barber et al. 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190) ·
[Zaremba et al. 2020](https://www.sciencedirect.com/science/article/pii/S0264999319312982) ·
[Brown-Cliff 2004](https://www.sciencedirect.com/science/article/abs/pii/S0927539803000422) ·
[Rapach-Ringgenberg-Zhou 2016](https://ideas.repec.org/a/eee/jfinec/v121y2016i1p46-65.html) ·
[Hong et al. (DTC)](https://www.nber.org/system/files/working_papers/w21166/w21166.pdf) ·
[Martineau 2022](https://econpapers.repec.org/article/nowjnlcfr/104.00000122.htm) ·
[UCLA Anderson Review](https://anderson-review.ucla.edu/is-post-earnings-announcement-drift-a-thing-again/)

**Volatility.**
[Andersen-Bollerslev-Diebold-Labys 2003](https://econpapers.repec.org/RePEc:ecm:emetrp:v:71:y:2003:i:2:p:579-625) ·
[Corsi 2009](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1365738) ·
[Patton-Sheppard 2015](https://econpapers.repec.org/RePEc:tpr:restat:v:97:y:2015:i:2:p:683-697) ·
[Bollerslev-Li-Zhao 2020](https://ideas.repec.org/a/cup/jfinqa/v55y2020i3p751-781_2.html) ·
[Amaya et al. 2015](https://ideas.repec.org/a/eee/jfinec/v118y2015i1p135-167.html) ·
[Christensen-Siggaard-Veliyev 2023](https://econpapers.repec.org/article/oupjfinec/v_3a21_3ay_3a2023_3ai_3a5_3ap_3a1680-1727..htm) ·
[Molnár (range estimators)](http://mmquant.net/wp-content/uploads/2016/09/range_based_estimators.pdf)

**Replication and protocol.**
[McLean-Pontiff 2016](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary) ·
[Hou-Xue-Zhang 2020](https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html) ·
[Harvey-Liu-Zhu 2016](https://www.nber.org/papers/w20592) ·
[Novy-Marx-Velikov 2016](https://ideas.repec.org/p/nbr/nberwo/20721.html) ·
[Arnott-Harvey-Markowitz 2019](https://people.duke.edu/~charvey/Research/Published_Papers/P138_A_backtesting_protocol.pdf) ·
[Deflated Sharpe](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf) ·
[PBO](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf) ·
[Purged CV](https://en.wikipedia.org/wiki/Purged_cross-validation) ·
[PyTorch reproducibility](https://docs.pytorch.org/docs/main/notes/randomness.html) ·
[LightGBM tuning](https://lightgbm.readthedocs.io/en/stable/Parameters-Tuning.html)

**Practitioner sources (C-grade by definition).**
[ZBA ORB](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284) ·
[ORB summary](https://danfin.net/opening-range-breakout-research) ·
[QuantConnect ORB](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/) ·
[Concretum papers](https://concretumgroup.com/papers/) ·
[ZA VWAP](https://concretumgroup.com/volume-weighted-average-price-vwap-the-holy-grail-for-day-trading-systems/) ·
[noise-area replication](https://github.com/codecat-ops/zarattini-2024-momentum-spy) ·
[0DTE-era measurement](https://dev.to/firmtape/intraday-momentum-is-dead-in-the-0dte-era-we-measured-it-on-1085-spx-sessions-43g0) ·
[Crabel](https://openlibrary.org/books/OL1611959M/Day_trading_with_short_term_price_patterns_and_opening_range_breakout) ·
[NR7 (Oxford Strat)](https://oxfordstrat.com/trading-strategies/nr7/) ·
[Fidelity A/D](https://www.fidelity.com/learning-center/trading-investing/advance-decline) ·
[Warrior gap-and-go](https://www.warriortrading.com/gap-go/) ·
[Aziz strategies](https://www.shortform.com/books/blog/how-to-day-trade-for-a-living-by-andrew-aziz.html) ·
[Holy Grail](https://www.tradingsetupsreview.com/the-holy-grail-trading-setup/) ·
[RSI(2)](https://www.tradingsetupsreview.com/trade-2-period-rsi/) ·
[Elder triple screen](https://blog.elearnmarkets.com/triple-screen-trading-method-alexander-elder-way-trading/) ·
[StockCharts RSI](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/relative-strength-index-rsi) ·
[StockCharts ADX](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/average-directional-index-adx) ·
[StockCharts Keltner](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/keltner-channels) ·
[StockCharts pivots](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/pivot-points) ·
[StockCharts VWAP](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-overlays/volume-weighted-average-price-vwap) ·
[StockCharts stochastic](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/stochastic-oscillator-fast-slow-and-full) ·
[Camarilla](https://www.mypivots.com/dictionary/definition/42/camarilla-pivot-points) ·
[TICK](https://www.tradingsim.com/blog/tick-index) ·
[Market Profile](https://en.wikipedia.org/wiki/Market_profile) ·
[Madhavan VWAP](https://www.smallake.kr/wp-content/uploads/2014/07/TP_Spring_2002_Madhavan.pdf) ·
[SEC momentum ignition (Lexology)](https://www.lexology.com/library/detail.aspx?g=cb81a662-37a9-4e9c-a31d-a9c3fc636d7f) ·
[Alpaca bar fields](https://docs.alpaca.markets/docs/historical-stock-data-1)

**Retail outcomes.**
[Barber-Lee-Liu-Odean 2014](https://ideas.repec.org/a/eee/finmar/v18y2014icp1-24.html) ·
[Chague-De-Losso-Giovannetti](https://ideas.repec.org/p/spa/wpaper/2019wpecon47.html) ·
[FTC v. Warrior Trading](https://www.ftc.gov/news-events/news/press-releases/2022/04/federal-trade-commission-cracks-down-warrior-trading-misleading-consumers-false-investment-promises)

### Not accessed, or accessed only in part

- **Abstract or summary only.** SSRN pages were rate-limited (HTTP 429), and
  Wiley, JSTOR and PM-Research blocked the full text (403 or robots) for the
  JF versions of Brock-Lakonishok-LeBaron, George-Hwang, McLean-Pontiff and
  Wood-McInish-Ord. Figures for those papers come from abstracts, the
  publishers' repositories linked above, or the CFA Institute digest.
- **GKX tuning grids.** The exact grids and seed count are in GKX's Internet
  Appendix, which was not retrieved. §2.1 describes the regularization but
  quotes no grid.
- **Cited by URL for their role, not for a figure (not opened):**
  Berkowitz-Logue-Noser (1988), Hansen's SPA paper, Baz et al. (2015), the PBO
  paper (Bailey et al.), López de Prado's book (PhilPapers), Crabel's book (Open
  Library), and the SSRN page of the SPY "noise area" paper. Its figures come
  from the replication and the Concretum list.
- **Publisher pages given beside an opened preprint (not opened):** the RFS
  page of GKX, the JF pages of JKX and Kelly-Malamud-Zhou, the JFE page of Gao
  et al., and the JPM page of Fang-Jacobsen-Qin. All figures come from the
  preprints.
- **Not used:** Leung et al. (2021, JFDS), blocked by robots;
  QuantifiedStrategies pages, blocked by a bot check; a PMC review, blocked by
  a captcha; the Kaggle Optiver winning write-up, which returned no content.
  No claim here rests on them.
- **Grant-Wolf-Yu 2005:** abstract only; the magnitudes were not seen.
- **Holmberg et al. 2013:** the per-trade return magnitudes in the working
  paper were ambiguous in the extraction, so only the success rates are quoted.
