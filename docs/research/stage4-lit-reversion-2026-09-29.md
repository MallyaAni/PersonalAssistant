# Stage 4 literature memo: short-term reversal, volatility squeezes and grade-conditioned timing (2026-09-29)

This is research only. No code was changed, and none of the book's data was read,
so every rule in §7 can still be registered before it is run. The only numbers
of my own come from public data: the Ken French library and the CBOE VIX, in
Appendix A. The script is `scorecards/stage4/french_reversal.py`.

**Scope.** This memo covers five topics from the stage-4 brief:

1. short-term reversal;
2. rule-based mean reversion;
3. volatility compression and breakouts;
4. the operator's hypothesis that timing should depend on the grade;
5. exit timing.

Market structure, trend turning points and CNNs are covered in a separate memo.

**Sources and access.** Peer-reviewed papers and NBER/SSRN working papers come first.
Practitioner sources are marked **(practitioner)**. **(abstract only)** means only
the abstract or a publisher's summary could be read. Pages that could not be read
are listed at the end.

**Evidence grades.** They follow `feature-research-2026-09-29.md`:

- **A.** Peer-reviewed, with out-of-sample or post-publication evidence that
  survives realistic costs in a relevant market and horizon.
- **B.** Mixed: in-sample only, before costs, another asset class, only small
  stocks, or contested by later work.
- **C.** Practitioner folklore, or backtests by vendors and educators.
- **↓** means the effect decayed after publication or disappears after costs.

---

## 0. Bottom line

1. **Plain short-term reversal has disappeared in large caps.**
   - **Then.** The Fama-French reversal factor (long last month's losers, short
     its winners, value-weighted) earned 1.05% a month in 1927-1962 (t 5.2) and
     0.78% in 1963-1989 (t 5.4).
   - **Now.** It earned 0.00% in 2010-2026:08 (t 0.0) and −0.45% in
     2020-2026:08. The large-cap half earned −0.10% a month since 2010, and the
     largest size quintile −0.19% (Appendix A).
   - **Long only.** Buying last month's large-cap losers against the middle
     group earned −0.08% a month since 2010.
   - **After costs.** The plain strategy nets −1.28% a month
     ([Novy-Marx-Velikov 2016](https://www.nber.org/system/files/working_papers/w20721/w20721.pdf)).
2. **What survives is conditional, long-short and monthly.**
   - **Industry-relative, excluding earnings announcers:** 0.58% a month after
     decimalization, May 2001 to 2021, t 3.29
     ([Dai-Medhat-Novy-Marx-Rizova 2024](https://www.nber.org/system/files/working_papers/w30917/w30917.pdf)).
   - **Residual, after cash-flow news:** four times the standard reversal's
     alpha, to 2009
     ([Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf)).
   - **Residual, on factor residuals:** positive after costs among the 100
     largest stocks, to 2008
     ([Blitz et al. 2013](https://www.efmaefm.org/0EFMSYMPOSIUM/2012/papers/017_update.pdf)).
   - **The mechanism** is paid liquidity provision
     ([Nagel 2012](https://www.nber.org/papers/w17653)).
   - **None of these** is a single-name timing rule.
3. **This book's A names sit where reversal turns into momentum.**
   - **High turnover.** The top turnover decile shows short-term *momentum* of
     +1.37% a month; among the 500 largest stocks it is +0.42% a month
     ([Medhat-Schmeling 2022](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/5dea8896-1a7b-4b9c-916e-439c0f1cfc71.pdf)).
   - **High turnover plus a high price-to-52-week-high ratio** also means
     momentum
     ([Chen-Stivers-Sun 2024](https://ideas.repec.org/a/eee/empfin/v79y2024ics0927539824000902.html);
     [Chiang-Kirby-Nie 2021](https://www.sciencedirect.com/science/article/abs/pii/S0378426621000261)).
   - **The same result in this book.** Stage 3 found that stretched A names kept
     winning on 2024-2026.
4. **The conditioning that separates a dip worth buying from a falling knife is
   news versus no news**
   ([Chan 2003](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf);
   [Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf);
   [Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf)).
   - **The companions** are industry-relative versus raw returns, and whether the
     move formed intraday or in an overnight gap
     ([Lou-Polk-Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf);
     [Barardehi-Bogousslavsky-Muravyev](https://experts.illinois.edu/en/publications/what-drives-momentum-and-reversal-evidence-from-day-and-night-sig/)).
   - **The book can build all three:** the 8-K clock, the theme ETFs, and the
     15-minute bars.
5. **Rule-based mean reversion has no peer-reviewed out-of-sample test on
   large-cap single names.** That covers RSI(2), IBS, consecutive down days and
   Bollinger %b.
   - **The practitioner tests are gross of costs.** RSI(2) < 5 on Russell 1000
     stocks, 1995-2015, averaged 0.75% a trade over about 4-5 days, with 0.13%
     in 2014
     ([Alvarez, practitioner](https://alvarezquanttrading.com/blog/the-health-of-stock-mean-reversion-dead-dying-or-doing-just-fine/)).
   - **The edge sits in small, fallen stocks**
     ([Alvarez](https://alvarezquanttrading.com/blog/rsi2-strategy-double-returns-with-a-simple-rule-change/)).
   - **Index-level technical rules decayed.** Bollinger's buy-minus-sell spread
     fell from 0.454% a day before 1983 to 0.002% after 2002
     ([Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)).
6. **Squeezes carry no direction, and there is no evidence of an unusually large
   move after one.**
   - **Volatility is persistent**, so a squeeze forecasts low volatility that
     rises only slowly
     ([Corsi 2009](https://academic.oup.com/jfec/article-abstract/7/2/174/856522)).
   - **Direction comes from elsewhere:** trend and the 52-week high
     ([George-Hwang 2004](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)),
     abnormal volume
     ([Gervais-Kaniel-Mingelgrin 2001](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:877-919))
     and news.
   - **The one breakout family with long survivorship-free evidence** is
     all-time-high breakouts with wide trailing stops, held for months
     ([Wilcox-Crittenden 2005, practitioner](https://www.cis.upenn.edu/~mkearns/finread/trend.pdf);
     [Zarattini-Pagani-Wilcox 2025](https://concretumgroup.com/does-trend-following-still-work-on-stocks/)).
     It is not a 1-20 day rule.
7. **The operator's hypothesis gets its direction right in the cross-section.**
   - **The support.** Losers with strong fundamentals and winners with weak
     fundamentals reverse more
     ([Zhu-Sun-Chen 2019](https://www.sciencedirect.com/science/article/abs/pii/S0927539819300234);
     [Zhu-Sun-Tu 2021](https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=7866&context=lkcsb_research)).
     Analyst levels add value only when the quantitative signals agree
     ([Jegadeesh-Kim-Krische-Lee 2004](https://paperswithbacktest.com/strategies/analyzing-the-analysts-when-do-recommendations-add-value)).
   - **The limits.** The evidence is monthly long-short and mostly pre-2015. An
     unaudited replication is negative for 2005-2026. Inside this book's A/A+
     names the reversal did not separate winners from losers (stage 3).
   - **Little path to time after a rating change.** In the post-2003 era the
     post-revision drift is about zero
     ([Altınkılıç-Hansen-Ye 2016](https://econpapers.repec.org/RePEc:eee:jfinec:v:119:y:2016:i:2:p:371-398)),
     and the reaction is concentrated on days 0 and +1
     ([Loh-Stulz 2011](https://cpb-us-w2.wpmucdn.com/u.osu.edu/dist/0/30211/files/2017/07/When-Are-Analyst-Recommendation-Changes-Infuential-2kelvug.pdf)).
8. **Exits.**
   - **Stops lower expected returns** unless returns trend or switch regimes
     ([Kaminski-Lo 2014](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf)).
     Trailing stops on US stocks over 1926-2016 cut risk but also cut returns
     and the Sharpe ratio
     ([Dai et al. 2021](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)).
   - **Discretionary selling of salient extremes** costs about 80 bp a year
     against selling at random
     ([Akepanidtaworn et al. 2023](https://www.nber.org/papers/w29076)).
   - **Holding losers to wait for a pop** is the disposition error
     ([Odean 1998](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf)).
   - **Resting limit sells get adversely selected**
     ([Linnainmaa 2010](https://paperswithbacktest.com/strategies/do-limit-orders-alter-inferences-about-investor-performance-and-behavior)).
9. **The arithmetic decides it.**
   - **What the floor needs.** The book places 0.377 orders a session (0.262 on
     2024-2026) at 5-9% of NAV. To add +2 bp a session, a rule must gain 59-106
     bp on every order (85-152 bp on 2024-2026).
   - **What a martingale allows.** If prices follow a martingale, no rule that
     waits for a trigger can beat immediate execution in expectation; it can
     only lose the drift.
   - **The best case from history.** The best large-cap figure is the loser
     quintile's next-week excess return among the 100 largest US stocks: 43.7
     bp gross, 1990-2009
     ([De Groot-Huij-Zhou 2012](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf)).
     Captured on every order, that is about 1.2 bp a session.
10. **Honest prior.**
    - **About 3%** that any grade-conditioned multi-day timing rule adds more
      than 2 bp a session after 16-25 bp costs on the existing orders.
    - **About 5%** once a tactical overlay that trades more is included.
    - **About 10-15%** that the best-supported rule (T2 or T7, §7) shows a real
      but immaterial gain per order.

---

## 1. The decision and the arithmetic

**What multi-day timing changes.**

- **Today.** The board executes each order on the day it is generated. BUY
  fills on the first completed 15-minute bar at least 1% under the open, else
  at the close. SELL/TRIM fills on a 1% pop, else at the close.
- **Where the orders come from.** 20-session rebalances, downgrades below A, and
  the executor's mid-cycle entries and idle-cash redeploy
  (`stage3-results-2026-09-29.md`).
- **The change.** A multi-day rule lets an order wait up to W sessions for a
  trigger and falls back to the close of session W.

**How much a timing rule has to earn** (`feature-research-2026-09-29.md` §6.3,
from `ml_entry_level.json`):

| Window | Orders per session | Order size | Gain per order needed for +2 bp a session |
|---|---|---|---|
| 2016-2023 | 0.377 | 5-9% of NAV | 59-106 bp |
| 2024-2026 | 0.262 | 5-9% of NAV | 85-152 bp |

If a rule changes only a fraction f of orders, each changed order must gain 1/f
times more. With f = 0.3, that is 200-350 bp on 2016-2023.

**Why waiting cannot help without reversal.**

- **The martingale case.** Suppose the name's price is a martingale relative to
  wherever the waiting money sits (the book, through the idle-cash redeploy, or
  cash). The optional stopping theorem then gives E[P_τ] = P_0 for any rule that
  stops within W sessions. No waiting rule improves the expected fill.
- **The drift case.** If the relative drift is μ > 0, waiting loses about
  μ·E[τ].
- **So the only source of gain** is predictable reversal of the name's relative
  return inside the window. The literature question is therefore narrow: how
  strong is 1-20 day reversal in large, liquid, high-turnover tech names today,
  and does the grade strengthen it?

**The best case from the literature.**

- **The figure.** Among the 100 largest US stocks in 1990-2009, stocks in the
  bottom quintile of past-week return beat the equal-weight cross-section by
  43.7 bp the following week, before costs
  ([De Groot-Huij-Zhou 2012](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf)).
- **Applied to this book.** Timing every buy to capture it would add
  43.7 × 0.377 × 7% ≈ 1.2 bp a session before the cost of waiting.
- **Why that overstates it:**
  - it is pre-2010;
  - only a minority of orders will meet a bottom-quintile week inside a short
    window;
  - part of it is bid-ask bounce (§2.1).

**The book's own record** (from `stage3-results-2026-09-29.md` and the
feature-research memo):

- **Timing.** No learned timing rule beat `dip_or_close`: −0.6 to −0.1 bp a
  session. The `free` rules lost 1.5 bp a session on 2024-2026 (t −3.0).
- **The dip fill.** It beat the close by −8.7 bp per filled dip on 2016-2023
  and by +36.0 bp on 2024-2026.
- **Reversal features.** The one-month reversal features have IC −0.03 to −0.05
  across graded names, but they do not separate the A/A+ names from each other.
- **Stretched names.** Dropping the most stretched A name would have cost 4.5%
  per 20 sessions on 2024-2026 (t +2.4).

---

## 2. Short-term reversal (1 day to 1 month)

### 2.1 Magnitude and decay

**Classic magnitudes.**

- **Monthly.** The value-weighted Fama-French reversal factor earned 1.05% a
  month in 1927-1962 and 0.78% in 1963-1989 (Appendix A).
- **Daily** ([Nagel 2012](https://www.nber.org/system/files/working_papers/w17653/w17653.pdf)).
  Nagel's strategy uses Lehmann weights on the last 5 days' market-adjusted
  returns and rebalances daily. Over 1998-2010 it earned:

  | Priced at | Mean per day | Sharpe |
  |---|---|---|
  | Transaction prices | 0.30% | 8.44 |
  | Quote midpoints | 0.18% | 4.50 |
  | The same strategy on industry portfolios | 0.02% | — |

  The 0.12 point gap between transaction and midpoint prices is bid-ask bounce.
- **Decay by 2007**
  ([Khandani-Lo, NBER w14465](https://www.nber.org/system/files/working_papers/w14465/w14465.pdf)).
  They ran the Lo-MacKinlay contrarian strategy on S&P 1500 stocks over
  1995-2007. Average returns were above the full-sample mean in every year
  before 2002 and below it from 2002 on. As the fetch read it, the one-day-hold
  returns fell from about 60 bp a day in the mid-1990s to 10-20 bp a day by
  2007, before costs.
- **Decay by decimalization.** Anomaly returns "approximately halved after
  decimalization"
  ([Chordia-Subrahmanyam-Tong 2014](https://ideas.repec.org:443/a/eee/jaecon/v58y2014i1p41-58.html),
  abstract only).

**Decay in the French data** (my computation; Appendix A). The table shows the
mean monthly return in %, with the Newey-West t in brackets, for value-weighted
portfolios long prior-month losers and short prior-month winners.

| Series | 1927-62 | 1963-89 | 1990-99 | 2000-09 | 2010-19 | 2020-26:08 | 2010-26:08 |
|---|---|---|---|---|---|---|---|
| ST_Rev factor (2×3 sort) | 1.05 (5.2) | 0.78 (5.4) | 0.11 (0.5) | 0.35 (0.9) | 0.31 (1.5) | −0.45 (−1.3) | 0.00 (0.0) |
| Big half (above NYSE median) | 0.31 (1.4) | 0.46 (3.0) | −0.02 (−0.1) | 0.43 (1.0) | 0.27 (1.1) | −0.64 (−1.4) | −0.10 (−0.4) |
| Largest size quintile (5×5 sort) | 0.44 (1.6) | 0.43 (2.1) | −0.26 (−0.8) | 0.69 (1.2) | 0.29 (0.8) | −0.92 (−1.2) | −0.19 (−0.5) |
| Big half, losers minus middle (long leg) | 0.11 (0.9) | 0.35 (3.0) | 0.00 (0.0) | −0.14 (−0.4) | 0.06 (0.4) | −0.31 (−1.2) | −0.08 (−0.6) |

**Reading.**

- **The finding.** At one month, plain reversal in large caps has been
  indistinguishable from zero since 1990 and negative since 2020.
- **Long only.** "Buy last month's large-cap losers" has had no edge.
- **Why 2020-2026 is negative.** It is the short-term momentum of §2.7.
- **Horizon.** This is a monthly measurement. The weekly and daily
  literature (§2.8) is older, and none of it covers 2010-2026 for large caps.

### 2.2 What drives it: liquidity provision

- **Nagel's reading.** Reversal returns proxy for the returns to liquidity
  provision. They rise sharply when intermediaries withdraw
  ([Nagel 2012](https://www.nber.org/papers/w17653)).
- **Individuals as liquidity providers**
  ([Kaniel-Saar-Titman 2008](https://static1.squarespace.com/static/5e6033a4ea02d801f37e15bb/t/5f5beb55689b700d25e3b1fe/1599859541913/kaniel_saar_titman_trading_and_returns.pdf)).
  On the NYSE in 2000-2003, individuals bought after declines: −2.47% over the
  prior 20 days. They earned +0.80% excess over the next 20 days. The authors
  read this as liquidity provision to institutions that demand immediacy.
- **Liquidity is dearest before earnings.** Short-term reversals are six times
  larger during earnings announcements than outside them, as market makers
  demand compensation for inventory risk
  ([So-Wang 2014](https://ideas.repec.org/a/eee/jfinec/v114y2014i1p20-35.html),
  abstract only).
- **Somebody still pays for immediacy.** Mutual funds' costs of immediacy exceed
  their liquidity-provision returns by 1.9% a year over 1984-2017, and by more
  than 2.5% a year for large-cap and momentum funds
  ([Ignashkina-Rinne-Suominen 2022](https://www.sciencedirect.com/science/article/pii/S0378426622000309),
  abstract only).
- **The two legs have different drivers.** The long leg (losers) reflects
  liquidity shocks and fire sales. The short leg (winners) reflects sentiment
  under short-sale constraints
  ([Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf)).
  A long-only book can only harvest the long leg.
- **Bid-ask bounce.** After large one-day declines, the reversal is explained by
  bid-ask bounce and market liquidity, with no overreaction, and the decliners
  perform poorly over longer horizons
  ([Cox-Peterson 1994](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p255-67.html),
  abstract only).

### 2.3 Dependence on the VIX

- **Nagel 2012**
  ([PDF](https://www.nber.org/system/files/working_papers/w17653/w17653.pdf)):
  - **The slope.** The daily reversal return rises by 0.22 points per point of
    normalized VIX at transaction prices, 0.16 at midpoints, and 0.07 for
    industry portfolios.
  - **Monthly fit.** Adjusted R² is 0.56, 0.25 and 0.07 respectively.
  - **2008.** Returns "virtually exploded" in the crisis.
  - **The largest stocks** show about 0.1% a day at a high VIX, read off a
    figure, so the figure is approximate.
- **My monthly check on 1990-2026** (Appendix A). VIX is taken at formation.
  With VIX ≥ 25, the factor returned about 0.76% a month on 1990-2009 and
  0.55% on 2010-2026; with VIX < 25 it returned about 0.09% and −0.09%.

  | VIX at formation | ST_Rev, 1990-2009 | ST_Rev, 2010-2026:08 | Big half, 1990-2009 | Big half, 2010-2026:08 |
  |---|---|---|---|---|
  | ≥ 25 | 0.76% (n = 51) | 0.55% (n = 29) | 0.45% | 0.25% |
  | < 25 | 0.09% | −0.09% | 0.13% | −0.16% |

  - **Reading.** The direction agrees with Nagel.
  - **Why it is weak:** the high-VIX samples are small, and the linear slopes
    are insignificant (|t| < 1.6).
- **The same months hold the worst crashes of the strategy.** Large-cap
  prior-month losers minus winners returned:

  | Month | Return |
  |---|---|
  | October 2008 | −8.8% |
  | November 2008 | −11.6% |
  | February 2009 | −9.6% |
  | April 2009 | −11.0% |
  | March 2020 | −16.4% |
  | May 2025 | −9.9% |

  The same stress periods also hold some of the best months: +9.1% in April
  2020 and +3.9% in March 2009. A high VIX raises the expected payoff of
  liquidity provision over 1-5 days. Over a 20-day swing it also raises the
  variance a great deal, and it is when losers most often keep falling.
- **A weaker related result** (low-tier journal)
  ([Kudryavtsev 2017](https://riskmarket.co.uk/jrc/journals-articles/issues/vix-index-and-stock-returns-following-large-price-moves/)).
  Large moves on days when the VIX moves the other way reverse over 2-20 days.
  Large moves that go with the VIX drift instead.

### 2.4 News versus no news

- **Chan 2003**
  ([working paper](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf);
  [JFE](https://ideas.repec.org/a/eee/jfinec/v70y2003i2p223-260.html)). The
  working-paper sample is 1980-1999: a random subset of CRSP, about 280-600
  stocks at a time.
  - **Stocks without news.** Extreme movers show a strong reversal in the first
    month (the no-news momentum strategy loses almost 2%) and nothing after.
  - **Stocks with news.** They drift, and the drift is concentrated in bad
    news: the 3-factor alpha of news losers reaches −6.9% at 12 months, against
    about zero for news winners.
  - **Excluding stocks under $5,** news losers reach −3.9% and no-news losers
    about 0.
- **Savor 2012**
  ([paper](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf)).
  The sample is November 1993 to December 2009, with shocks of ±10% abnormal
  return on a day (against Fama-French three factors plus momentum). Over the
  next 20 trading days:

  | Shock type | What follows | Long-short return | Sharpe |
  |---|---|---|---|
  | With analyst reports (information) | drift | about 16% a year | 1.21 |
  | Without analyst reports | reversal | about 20% a year | 1.66 |
  | Both combined | — | close to 37% a year, gross | — |

  Information events are more common in larger firms.
- **Da-Liu-Schaumburg 2014**
  ([paper](https://academicweb.nd.edu/~zda/Reversal.pdf)). The sample is
  1982-2009, about 2,350 stocks covering about 75% of market capitalization.

  | Strategy | Three-factor alpha per month | t |
  |---|---|---|
  | Standard reversal | 0.33% | 1.37 |
  | Residual, after removing analyst-revision cash-flow news and expected returns | 1.34% | 9.28 |
  | Residual after an 80.5 bp a month cost estimate | about 0.54% | 3.90 |
  | Residual, 2000-2009 | 1.04% (0.99% raw) | — |
- **Earnings announcers** (§2.5 has the sources).
  - Intra-industry losers and winners revert less after an earnings
    announcement (Hameed-Mian 2015).
  - Among recent announcers, the conventional reversal is masked by
    post-earnings drift (Dai-Medhat-Novy-Marx-Rizova 2024).
- **The drift leg is now weak in large caps.** Post-earnings drift has been
  absent for large stocks since 2006
  ([Martineau 2022](https://econpapers.repec.org/article/nowjnlcfr/104.00000122.htm),
  abstract only). News dips in large caps therefore do not reliably continue.
  They do not reliably revert either.
- **What this book can observe.** It has the 8-K acceptance clock
  (`edgar.py`) and abnormal volume. It has no analyst-report feed. A no-news
  flag built from 8-Ks and volume is the practical proxy.

### 2.5 Industry versus idiosyncratic components

- **Hameed-Mian 2015**
  ([paper](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/BwXb81392625636.pdf)).
  The sample is 1968-2010. Risk-adjusted returns per month:

  | Strategy | Return per month |
  |---|---|
  | Intra-industry reversal | 0.97% |
  | Conventional reversal | 0.63% |
  | Intra-industry, large caps (conventional insignificant there) | 0.47% |
  | Intra-industry, 2000-2010 | 0.94% |
  | Intra-industry, skipping a day | 0.57% |
  | Inter-industry (i.e. momentum) | −0.30% |
- **Blitz-Huij-Lansdorp-Verbeek 2013**
  ([paper](https://www.efmaefm.org/0EFMSYMPOSIUM/2012/papers/017_update.pdf);
  [JFM](https://ideas.repec.org/a/eee/finmar/v16y2013i3p477-504.html)). The
  sample is 1929-2008, stocks above the NYSE median.

  | Strategy | Monthly return | Sharpe or t |
  |---|---|---|
  | Residual reversal (on Fama-French three-factor residuals) | 1.34% | Sharpe 1.28 |
  | Conventional reversal | 0.97% | Sharpe 0.62 |
  | Conventional, after 1990, gross | 0.18% | t 0.42 |
  | Conventional, after 1990, net | −0.26% | — |
  | Residual, after 1990, gross | 1.00% | t 3.55 |
  | Residual, after 1990, net | 0.70% | — |
  | Residual, net, top 500 stocks | 0.67% | t 2.77 |
  | Residual, net, top 100 stocks | 0.81% | t 3.03 |
- **Dai-Medhat-Novy-Marx-Rizova 2024**
  ([NBER w30917](https://www.nber.org/system/files/working_papers/w30917/w30917.pdf);
  [FAJ](https://www.tandfonline.com/doi/abs/10.1080/0015198X.2023.2292534)).
  The sample is 1973-2021.

  | Strategy | Return per month | t |
  |---|---|---|
  | Conventional reversal | 0.31% | 1.68 |
  | Industry-relative | 0.74% | 5.40 |
  | Industry-relative, adjusted for announcements | 1.08% | 9.35 |
  | The same, May 2001 to 2021 | 0.58% | 3.29 |

  There is "surprisingly little variation" across the top four NYSE size
  quintiles.
- **Blitz-van der Grient-Honarvar 2023.** Adjusting for short-term industry
  momentum, factor momentum and residual factors doubles the risk-adjusted
  return of reversal
  ([Robeco summary](https://www.robeco.com/en-us/insights/2023/10/reversing-the-trend-of-short-term-reversal),
  abstract only).
- **For this book.** The part of a move shared with SMH or IGV behaves like
  momentum. The residual behaves like reversal. Every dip rule should therefore
  be defined on the residual against the theme ETF.

### 2.6 Overnight versus intraday components

The two main papers split different things:

| Paper | What it splits | Sample |
|---|---|---|
| Lou-Polk-Skouras 2019 | the holding-period return | 1993-2013 |
| Barardehi-Bogousslavsky-Muravyev (RFS) | the signal | 1926-2019 |

- **Lou-Polk-Skouras 2019**
  ([paper](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)):

  | Portfolio | Overnight CAPM alpha, per month (t) | Intraday CAPM alpha, per month (t) |
  |---|---|---|
  | Reversal (close to close about zero in this sample) | +0.93% (4.28) | −1.05% (−3.25) |
  | Momentum | +0.98% (3.84) | −0.02% (−0.06) |
- **Barardehi-Bogousslavsky-Muravyev**
  ([abstract](https://experts.illinois.edu/en/publications/what-drives-momentum-and-reversal-evidence-from-day-and-night-sig/);
  abstract only). Portfolios formed on past *intraday* returns show short-term
  reversal, and momentum without long-term reversal. Portfolios formed on past
  *overnight* returns show only long-term reversal.
- **Della Corte-Kosowski** (conference working paper)
  ([paper](https://www.cicfconf.org/sites/default/files/paper_357.pdf)).
  - At daily frequency on 1993-2014, about 39% and 25% of the overnight return
    reverses in the later and first intraday periods, against about 2% for
    intraday returns.
  - Their overnight-signal, intraday-execution reversal earns 1.68% a day
    against 0.33% close to close. That is gross and dominated by small stocks.
- **The tug of war.** More frequent "positive night, negative day" patterns
  predict higher returns
  ([Akbas et al. 2022](https://ink.library.smu.edu.sg/lkcsb_research/7712/),
  abstract only).
- **End-of-day reversal**
  ([Baltussen-Da-Soebhag](https://academicweb.nd.edu/~zda/EOD.pdf), working
  paper). Intraday losers are bought in the last 30 minutes, by retail
  dip-buying and reduced short selling. For the largest firms this is a 3.41 bp
  a day alpha (t 10.61) on 1993-2019. The authors say it may not survive
  costs.
- **Reading for multi-day timing.** A dip built intraday without news is a
  candidate for reversal. A gap down on news carries information at the
  one-month horizon, although part of any gap refills intraday on the next day.

### 2.7 Size, turnover and lottery-like names

- **Cheng-Hameed-Subrahmanyam-Titman 2017**
  ([paper](https://si-cheng.net/wp-content/uploads/2018/12/2017-JFQA-Cheng_Hameed_Subrahmanyam_Titman-Short-Term-Reversals.pdf)).
  The sample is 1980-2011.
  - **Losers only.** Monthly reversal is concentrated in past-quarter losers,
    at 0.81-1.68% a month across size groups. Past-quarter winners show
    reversal "not reliably different from 0".
  - **Large firms decayed.** For large firms it fell from 1.34% in 1980-1999
    to 0.49% in the recent decade.
  - **Institutional exits** strengthen it, to 0.95-1.23% a month.
  - **For this book:** buying dips in names that are already winning, which A
    names often are because the grade includes trend, is where the reversal
    is weakest.
- **Avramov-Chordia-Goyal 2006**
  ([paper](https://users.nber.org/~confer/2004/mmsu04/goyal.pdf)). Reversal is
  concentrated in high-turnover, illiquid losers, and "contrarian trading
  strategy profits are smaller than the likely transactions costs."
- **Medhat-Schmeling 2022**
  ([paper](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/5dea8896-1a7b-4b9c-916e-439c0f1cfc71.pdf)).
  Winners minus losers per month, 1963-2018:

  | Group | Return per month | t |
  |---|---|---|
  | Highest-turnover decile (momentum) | +1.37% | 4.74 |
  | Lowest-turnover decile (reversal) | −1.41% | 7.13 |
  | Above the NYSE median size | +0.62% | 3.01 |
  | 500 largest stocks | +0.42% | 4.91 |
  | After half-spreads | +1.00% | 3.47 |

  The effect persists for 12 months.
- **Chiang-Kirby-Nie 2021**
  ([abstract](https://www.sciencedirect.com/science/article/abs/pii/S0378426621000261)).
  There is "no evidence of monthly return reversals for the top quintile of
  small- and large-cap stocks ranked by turnover", and the top decile shows
  momentum. Their explanation is that news-driven moves continue.
- **Chen-Stivers-Sun 2024**
  ([abstract](https://ideas.repec.org/a/eee/empfin/v79y2024ics0927539824000902.html)).
  Reversal weakens as turnover and the price-to-52-week-high ratio rise, and it
  becomes momentum when both are high. Reversal is strongest for low-PTH,
  low-turnover stocks.
- **The weekly volume evidence is mixed:**
  - high-transaction stocks reverse and low-transaction stocks continue
    ([Conrad-Hameed-Niden 1994](https://econpapers.repec.org/RePEc:bla:jfinan:v:49:y:1994:i:4:p:1305-29),
    abstract only);
  - low-volume losers reverse more, and high-volume stocks less
    ([Cooper 1999](http://home.business.utah.edu/finmc/Att34685.pdf)).
- **Lottery-like names**
  ([Chen-Cohen-Liang-Sun 2025](https://ideas.repec.org/a/eee/empfin/v82y2025ics0927539825000301.html),
  abstract only). Weekly reversal is 1.66% a week in high-MAX stocks against
  0.65% in low-MAX stocks. It works only when retail order imbalance is in its
  top quintile.
- **For this book.** The names are large, liquid, high-turnover and often near
  their 52-week highs. That is where monthly reversal is weakest or reversed.
  The possible exception is a retail-frenzy week in a high-MAX name.

### 2.8 Costs for liquid names

- **De Groot-Huij-Zhou 2012**
  ([paper](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf)). US stocks,
  1990-2009, one-week formation, rebalanced daily. Returns in bp per week:

  | Universe and variant | Gross | Weekly turnover | Net |
  |---|---|---|---|
  | Top 1,500 | 61.7 | — | −66.1 (Keim-Madhavan costs) / −103.7 (Nomura) |
  | Top 500 | 71.9 | — | −3.0 |
  | Top 100, basic (long +43.7, short −40.3) | 84.2 | 711% | 31.5 |
  | Top 100, buffered (hold until out of the top or bottom half) | 77.9 | 337% | 53.1 |
  | Top 100, buffered, 2000-2009 | — | — | 59.0 |
  | Top 100, buffered, non-crisis periods | — | — | 34.8 |

  The Nomura one-way cost for the largest stocks is about 5-6 bp.
- **Re-costing it at this book's rates** (my scaling, not in the paper).

  | Top 100 variant | Implied cost at about 5.5 bp one way | Cost at 16 bp | Net at 16 bp |
  |---|---|---|---|
  | Basic | 52.7 bp a week | about 153 bp a week | about −69 bp a week |
  | Buffered | 24.8 bp a week | about 72 bp a week | about +6 bp a week |

  At retail costs, even the best pre-2010 large-cap reversal barely breaks
  even.
- **Novy-Marx-Velikov 2016**
  ([paper](https://www.nber.org/system/files/working_papers/w20721/w20721.pdf)).
  Plain reversal earns 0.37% a month gross on 90.9% one-sided monthly
  turnover. Costs of about 1.65% a month leave −1.28% net (t −6.02). With 10%
  and 50% buy and hold spreads it is still −0.72% a month.
- **Institutional costs**
  ([Frazzini-Israel-Moskowitz](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf)).
  In live institutional trades the mean market impact is 9.97 bp, 8.90 bp for
  large caps, with a median of 6.18 bp. The book's registered 10 bp is close
  to that, and the operator's reported 16 bp is higher.

### 2.9 Verdict for topic 1

| Claim | Evidence | After 2010, after costs | Applies to our names at 1-20 days? | Grade |
|---|---|---|---|---|
| Losers beat winners next week or month | ST_Rev 0.78%/mo (1963-89); Nagel 0.30%/day (1998-2010) | 2010-26: ST_Rev 0.00%/mo, big half −0.10%/mo; net −1.28%/mo | no for plain monthly; weak at 1-5 days | A↓ |
| Reversal is paid liquidity provision and scales with the VIX | Nagel slope 0.22; individuals +0.80% over 20 days | right direction in my monthly VIX split, small n; crisis months crash | 1-5 days in stress only | A (1-5 d) / B (20 d) |
| No-news moves reverse, news moves drift | Chan; Savor about 20%/yr; residual alpha ×4 | 0.58%/mo after 2001 (industry-relative); drift gone in large caps since 2006 | yes: the best conditioning, small magnitude | A/B |
| The industry component continues, the residual reverses | intra-industry 0.97 vs 0.63%/mo; residual Sharpe 1.28 | residual net 0.81%/mo in the top 100, to 2008 | yes: measure dips against SMH/IGV | A/B |
| Intraday-formed moves reverse; overnight (news) moves do not | signal split (BBM); holding split (LPS) | through 2019 | plausible; the book has the split | B |
| High turnover or near the 52-week high gives momentum | +1.37%/mo top-turnover decile; turnover and PTH studies | large caps 0.42-0.62%/mo | yes: A names sit in the momentum regime | A |
| Survives costs in liquid names | top 100 net +31.5 / +53.1 bp/week (1990-2009) | at 16 bp: about −69 / +6 bp/week (my scaling) | not at retail costs | B↓ |

---

## 3. Rule-based mean reversion used by traders

### 3.1 Connors RSI(2)

**The rules** (as reported by StockCharts; practitioner).

- **Long.** Buy when RSI(2) falls below 5-10 with the close above SMA200.
- **Exit.** Sell on a close above SMA5.
- **Short** is the mirror image.
- **Stops.** Connors reported that stops "hurt" performance on stocks and
  indices
  ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2)).

**Independent tests** (all practitioner, gross of costs).

- **Russell 1000, 1995 to mid-2015**
  ([Alvarez](https://alvarezquanttrading.com/blog/the-health-of-stock-mean-reversion-dead-dying-or-doing-just-fine/)).
  - **Setup.** Point-in-time membership including delisted stocks; buy
    RSI(2) < 5 at the close, sell when RSI(2) > 70.
  - **Results.** 0.75% average a trade over 4.1-5.1 bars, and 0.13% in 2014.
    The trend is "barely sloping down".
  - **Caution.** The 0.75% is raw, not market-adjusted. A 4.5-day hold
    includes roughly 20 bp of ordinary drift.
- **Russell 3000, 2007 to mid-2018**
  ([Alvarez](https://alvarezquanttrading.com/blog/rsi2-strategy-double-returns-with-a-simple-rule-change/)).
  - **Setup.** RSI(2) < 10 with the close above the 100-day average; a limit
    buy 5% under the close; exit when RSI(2) > 50 or after 10 days.
  - **Results.** CAR in the low teens. Restricting to *ex-index* stocks,
    former members that had dropped out, raised CAR by 698%.
  - **Reading.** The edge lives in small, fallen names, not in large index
    members.
- **Long-short.** "Long/short portfolios tend to have really small edges"
  ([Alvarez](https://alvarezquanttrading.com/blog/rsi2-relative-strength-index-analysis/)).
  On S&P 500 signals, "edges are harder to find and smaller"
  ([Alvarez](https://alvarezquanttrading.com/blog/mean-reversion-vs-trend-following-through-the-years/)).
- **S&P futures, 2000-2019, a modified RSI(2)**
  ([EasyLanguage Mastery](https://easylanguagemastery.com/strategies/connors-2-period-rsi-update-2019/)).
  - **Results.** 120 trades, 77% winners, profit factor 1.91, about 2.1% a
    year on $100k risking $2k a trade.
  - **Caveats.** No costs; the strategy was in a drawdown from about 2018.

**Peer review.** No peer-reviewed out-of-sample test of RSI(2) on large-cap
single names was found.

**Verdict.** C.

### 3.2 IBS (internal bar strength)

- **Definition.** IBS = (C − L)/(H − L).
- **ETFs**
  ([Pagonidis, NAAIM paper](https://www.naaim.org/wp-content/uploads/2014/04/00V_Alexander_Pagonidis_The-IBS-Effect-Mean-Reversion-in-Equity-ETFs-1.pdf)).
  - **The effect.** IBS < 0.2 was followed by +0.35% the next day and IBS > 0.8
    by −0.13%. A long-short IBS strategy averaged 29.38% a year over 1993-2013.
  - **Costs.** The author notes an IBS-only strategy struggles with costs and
    works better as a filter.
  - **Scope.** Individual stocks were not tested.
- **As a filter on stocks**
  ([Alvarez, practitioner](https://alvarezquanttrading.com/blog/internal-bar-strength-for-mean-reversion/)).
  S&P 500 dips with RSI(2) < 2.5, above the 200-day average and with the index
  up over 126 days: trades with IBS < 10 had 58% higher average profit and made
  up 34% of the trades.
- **Verdict.** C for single names.

### 3.3 Consecutive down days and large one-day drops

- **No modern peer-reviewed test** on large-cap single names was found.
- **Large firms, older sample.** Extremely large negative returns are followed
  by higher-than-expected returns for about two days
  ([Bremer-Sweeney 1991](https://econpapers.repec.org/article/blajfinan/v_3a46_3ay_3a1991_3ai_3a2_3ap_3a747-54.htm),
  abstract only).
- **Bid-ask bounce and liquidity.** They explain the reversal after large
  one-day declines, and the decliners then underperform
  ([Cox-Peterson 1994](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p255-67.html),
  abstract only).
- **Microstructure scale.** In Nasdaq-100 names, 31% of an extreme one-minute
  drop reverses in the next minute
  ([Rif-Utz 2021](https://www.sciencedirect.com/science/article/pii/S1062976921000922)).
  That is far below our horizon.
- **Verdict.** C.

### 3.4 Bollinger %b and z-score reversion

- **Fang-Jacobsen-Qin 2017**
  ([paper](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)).
  They tested 14 markets' indices, with the DJIA from 1885 to 2014. Only
  indices were tested.
  - **Which reading wins.** The volatility-breakout (trend) reading beats the
    contrarian one.
  - **Decay.** The daily buy-minus-sell spread was 0.454% before 1983, 0.296%
    in 1983-2001 and 0.002% since 2002.
  - **With 1% costs,** Bollinger rules beat buy-and-hold on Sharpe in 5
    markets over the full sample, and in 1 (Italy) after 2002.
- **In-house.** Closes below the lower band returned +0.9% over 5 sessions,
  in-sample (+2.1% while the AI basket fell). Trims at z > 3 lost
  (feature-research §1.6).
- **Verdict.** B↓.

### 3.5 Distance from moving averages

- **Long-average distance.** In the cross-section, distance from long averages
  (MAD 21/200; the trend factor) predicts continuation. See feature-research
  §2.6 and the trend-factor paper
  ([Han-Zhou-Zhu 2016](https://ideas.repec.org/a/eee/jfinec/v122y2016i2p352-375.html),
  seen in search, not opened).
- **Short-average stretch fades weakly in-house.**
  - The 21-EMA stretch fade has IC −0.022 at 5 sessions (t −2.79).
  - One-month stretch features have IC −0.03 to −0.05 across graded names.
  - Neither separates names inside the A/A+ book.
- **Verdict.** B/C.

### 3.6 Weekly filter rules with volume

- **Cooper 1999**
  ([paper](http://home.business.utah.edu/finmc/Att34685.pdf)). Largest 300
  NYSE/AMEX stocks, weekly, 1962-1993.
  - **In-sample.** Losers of more than 10% in a week earned +1.60% the next week
    (t 8.32).
  - **Out of sample, 1978-1993.** The active long rule earned 0.72% a week
    against a 0.32% benchmark.
  - **Costs.** Break-even round-trip costs are 0.8-1.8%.
  - **Standing.** It is the one academic out-of-sample test of a rule-based
    weekly reversal in large caps. It predates decimalization.
- **Verdict.** B↓.

### 3.7 Why mean-reversion trades "don't always work out"

1. **News.** Dips that carry information continue
   ([Chan 2003](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf);
   [Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf)).
   Oscillator rules have no news filter.
2. **The momentum regime.** In high-turnover names near their highs, one-month
   losers keep losing (§2.7).
3. **Liquidity crises.**
   - **Monthly crashes.** Large-cap reversal lost 8.8% in October 2008, 11.6% in
     November 2008 and 16.4% in March 2020 (Appendix A).
   - **The August 2007 quant crisis.** The contrarian strategy suffered its
     worst losses on 6-9 August 2007. Positions opened on 8-9 August then
     earned 8.20% and 8.96% if held five days
     ([Khandani-Lo](https://www.nber.org/system/files/working_papers/w14465/w14465.pdf)).
   - **So** mean reversion is paid for bearing crash risk.
4. **Payoff shape.** A high win rate comes with a fat left tail. Stops lower the
   expected return in a mean-reverting process
   ([Kaminski-Lo 2014](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf)).
5. **Adverse selection of dip fills.** Limit and dip fills happen
   preferentially when the price keeps going
   ([Linnainmaa 2010](https://paperswithbacktest.com/strategies/do-limit-orders-alter-inferences-about-investor-performance-and-behavior)).
6. **Decay.**
   - Technical-rule profits on DJIA stocks over 1928-2012 are "confined to
     particular episodes primarily from the mid-1960s to mid-1980s"
     ([Taylor 2014](https://research-information.bris.ac.uk/en/publications/the-rise-and-fall-of-technical-trading-rule-success/),
     abstract only).
   - Bollinger profits vanished after 2002 (Fang-Jacobsen-Qin).
7. **The cost of waiting in rising markets** (practitioner, index level).
   - Even perfect-foresight "buy the dip" lost to monthly purchases in over 70%
     of 40-year S&P 500 windows starting 1920-1979.
   - Missing the bottom by two months meant losing 97% of the time
     ([Of Dollars and Data](https://ofdollarsanddata.com/even-god-couldnt-beat-dollar-cost-averaging/)).

### 3.8 Verdict for topic 2

| Rule | Best evidence | After 2010, after costs | Applies to our names at 1-20 days? | Grade |
|---|---|---|---|---|
| RSI(2) < 5-10 above SMA200 | practitioner: 0.75%/trade gross (R1000, 1995-2015) | weaker lately; edge in ex-index small stocks | unlikely; drift cost | C |
| IBS < 0.2 | ETFs: +0.35% next day | costs bind; not tested on stocks | at most a 1-day filter | C |
| Consecutive down days / large drops | old large-firm studies; bid-ask explanation | none | unlikely | C |
| Bollinger %b / z | indices: the contrarian reading is worst | 0.002%/day after 2002 | no | B↓ |
| Short-average stretch | in-house 21-EMA IC −0.022 (5 sessions) | not inside the A/A+ book | selection, not timing | B/C |
| Volume-filtered weekly reversal | Cooper: out of sample 0.72%/wk vs 0.32% (1978-93) | pre-decimalization | weak | B↓ |

---

## 4. Volatility compression and breakouts

### 4.1 Definitions (practitioner)

- **Bollinger squeeze.** BandWidth "near the low end of its six-month range".
  Per StockCharts, "narrowing bands do not provide any directional clues", and
  Bollinger warns of "head fakes"
  ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze)).
- **TTM squeeze.** BB(20, 2) inside KC(20, 1.5×ATR), with a momentum histogram
  (close minus the average of the Donchian midline and SMA20, smoothed by
  linear regression) for direction
  ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ttm-squeeze)).
- **NR7 / NR4.** The narrowest daily range of the last 7 (or 4) sessions
  (Crabel).
- **VCP.** A volatility contraction pattern: successively shallower pullbacks
  (Minervini). No independent test was found.
- **Donchian breakout.** A close above the N-day high.

### 4.2 Does compression predict a large move?

- **Volatility is persistent.** The HAR model's daily, weekly and monthly
  components reproduce long memory and forecast well
  ([Corsi 2009](https://academic.oup.com/jfec/article-abstract/7/2/174/856522)).
  - **The implication** (my inference from the model). When all three
    components are low, which is what a squeeze is, the 1-20 day forecast
    stays low and climbs only gradually toward the mean.
  - **So** a squeeze predicts that volatility will rise from its trough. It
    does not predict an unusually large move.
- **NR7 statistics**
  ([Bulkowski, practitioner](https://www.thepatternsite.com/nr7.html)). 1,201
  stocks, 1990-2013:

  | Market and breakout | Average move after the breakout | Failure rate (moves < 5%) |
  |---|---|---|
  | Bull market, up | +7% | 46% |
  | Bull market, down | −6% | 47% |
  | Bear market, up | +8% | 40% |
  | Bear market, down | −12% | 27% |

  NR7 ranks 11th of 23 patterns.
- **Squeeze versus breakout.** The squeeze filter did not beat the plain
  volatility-breakout rule across markets
  ([Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)).
- **Conclusion.** No evidence was found that squeezes in large caps are
  followed by larger absolute moves than usual. The book can measure this
  directly (diagnostic D1 in §7.4).

### 4.3 Does anything predict the direction?

- **Compression itself does not** (StockCharts, above).
- **What does:**
  - **Trend and nearness to the 52-week high** (§4.4).
  - **Abnormal volume.** Stocks with unusually high volume over a day or a week
    appreciate over the next month
    ([Gervais-Kaniel-Mingelgrin 2001](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:877-919),
    abstract only).
  - **News and fundamentals**
    ([Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf);
    [Kecskés-Michaely-Womack 2017](https://ideas.repec.org:443/a/inm/ormnsc/v63y2017i6p1855-1871.html)).
  - **Past intraday returns**
    ([Barardehi et al.](https://experts.illinois.edu/en/publications/what-drives-momentum-and-reversal-evidence-from-day-and-night-sig/)).
  - **The option smirk** is also used in the literature. The book has no options
    history.
- **For a book that only holds A names,** the grade already tilts direction.
  The squeeze adds a volatility state, not a sign.

### 4.4 52-week-high breakouts

- **George-Hwang 2004**
  ([paper](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf)). 6-month
  formation and holding, 1963-2001:

  | Strategy | All months, per month | Excluding January |
  |---|---|---|
  | 52-week high | 0.45% | 1.23% |
  | Individual momentum (Jegadeesh-Titman) | 0.48% | 1.07% |
  | Industry momentum | 0.45% | 0.50% |

  The 52-week-high returns do not reverse in the long run.
- **Volume and returns at the extremes.** Volume spikes when price crosses the
  52-week high or low, and "after either event, returns are reliably positive"
  ([Huddart-Lang-Yetman 2009](https://pure.psu.edu/en/publications/volume-and-price-patterns-around-a-stocks-52-week-highs-and-lows-/),
  abstract only).
- **Household selling at the high**
  ([Della Vedova-Grant-Westerholm 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1),
  abstract only). Households sell with limit orders at the 52-week-high price,
  out of anchoring. This uninformed selling "leads to a doubling" of the
  anomaly's returns, and institutions take the other side.
- **Short-term momentum near the high.** High PTH and high turnover mean
  short-term momentum
  ([Chen-Stivers-Sun 2024](https://ideas.repec.org/a/eee/empfin/v79y2024ics0927539824000902.html)).
- **Analysts anchor too.** They are more likely to upgrade stocks near, or
  recently at, their 52-week high
  ([Lin 2018](https://ideas.repec.org/a/bla/acctfi/v58y2018is1p375-422.html),
  abstract only). An analyst-stance leg of the grade therefore partly
  re-encodes the 52-week high.
- **Implication.** For A names at or near their 52-week high, waiting for a dip
  fights the best-documented short-horizon continuation among large caps. The
  selling pressure at the high is what an institution buys.

### 4.5 Channel and all-time-high breakouts

- **Wilcox-Crittenden 2005** (Blackstar Funds; practitioner)
  ([paper](https://www.cis.upenn.edu/~mkearns/finread/trend.pdf)).
  - **Setup.** 24,000+ US stocks including 12,673 delisted, 1983-2004. Buy on a
    close at an all-time high; exit on a 10-ATR trailing stop; 0.5% round-trip
    costs.
  - **Results.** 18,000+ trades, 49.3% winners, win/loss ratio 2.56,
    expectancy about 15.2% a trade, average hold 305 days.
- **Zarattini-Pagani-Wilcox 2025** (fund research; summary page)
  ([Concretum](https://concretumgroup.com/does-trend-following-still-work-on-stocks/)).
  - **Results.** Survivorship-free, 1950-2024; 1991-2024 CAGR 15.19% with
    6.18% a year alpha; out of sample 2005-2024 "confirmed".
  - **Caveats.** Fewer than 7% of trades generate the profits. Costs bite below
    $1m without turnover control.
- **Relevance.** This supports letting breakouts run for months with wide
  stops. It says nothing about 1-20 day timing.

### 4.6 Popularity versus profitability

Bollinger profits vanished as the bands became popular: 0.454% a day before 1983,
0.296% in 1983-2001 and 0.002% after 2002
([Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf)).
All of it was measured on indices.

### 4.7 Verdict for topic 3

| Claim | Evidence | After 2010, after costs | Applies to our names at 1-20 days? | Grade |
|---|---|---|---|---|
| A squeeze predicts a large move | volatility persistence; NR7 moves are ordinary | none | no; it predicts a volatility state | C |
| A squeeze predicts direction | explicitly no | — | no | C |
| Breakout direction continues | Bollinger breakout beat contrarian, but decayed to 0.002%/day | indices only | weak | B↓ |
| Near the 52-week high comes continuation | George-Hwang; Huddart et al.; household anchoring; PTH momentum | the turnover-PTH study is recent | yes: argues against waiting for dips in A names near highs | A |
| All-time-high breakouts with wide stops | Wilcox-Crittenden; Zarattini et al. 2025 out-of-sample | practitioner, months-long holds | not a 1-20 day rule | B/C |

---

## 5. The operator's hypothesis: grade-conditioned timing

### 5.1 Reversal conditioned on fundamentals

- **Zhu-Sun-Chen 2019**
  ([abstract](https://www.sciencedirect.com/science/article/abs/pii/S0927539819300234)).
  - **The claim.** Fundamental strength (FSCORE) "exerts a significant
    influence" on reversal strategies. "Past losers with strong fundamentals
    significantly outperform past winners with weak fundamentals." After
    controlling for fundamentals, sentiment explains reversal better than
    liquidity shocks.
  - **Quantpedia's summary** (practitioner):
    - **Setup.** 1984-2015, the top 40% by market cap, price above $5. Long
      losers with FSCORE 7-9, short winners with FSCORE 0-3, rebalanced
      monthly.
    - **Results.** 12.01% a year in large stocks, volatility 20.6%, Sharpe
      0.39, maximum drawdown −59%.

    ([Quantpedia](https://quantpedia.com/strategies/combining-fundamental-fscore-and-equity-short-term-reversals))
  - **An unaudited replication** of 2005-2026 returned −1.76% a year, Sharpe
    −0.10
    ([paperswithbacktest](https://paperswithbacktest.com/strategies/fundamental-strength-and-short-term-return-reversal)).
- **Zhu-Sun-Tu 2021**
  ([paper](https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=7866&context=lkcsb_research)).
  The strategy is long recent losers with strong earnings surprises and short
  recent winners with weak ones, 1980-2015.

  | Variant | Return per month | Five-factor alpha |
  |---|---|---|
  | Equal-weighted | 2.34% (t 10.92) | 1.94% |
  | Value-weighted | 1.02% (t 4.16) | 0.86% (t 3.29) |
  | 1980-1999 | 2.75% | — |
  | 2000-2015 | 1.67% | — |
- **Removing cash-flow news** quadruples reversal alpha, to 2009
  ([Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf)).
- **Reading.**
  - **Where it helps.** The cross-section supports the *direction* of the
    operator's intuition. A dip in a fundamentally strong name without bad
    news is more likely liquidity or sentiment, and more likely to revert. A
    pop in a weak name is more likely sentiment, and more likely to fade.
  - **The caveats:**
    - these are monthly long-short portfolios whose short legs carry much of
      the return;
    - large-cap, value-weighted magnitudes are about half the headline;
    - the one independent (unaudited) replication after 2005 is negative.

### 5.2 Analyst views: levels, changes and quantitative signals

- **Jegadeesh-Kim-Krische-Lee 2004**
  ([abstract as quoted by paperswithbacktest](https://paperswithbacktest.com/strategies/analyzing-the-analysts-when-do-recommendations-add-value);
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=291241) was rate
  limited; abstract only).
  - **Analysts favor glamour stocks:** positive momentum, high growth.
  - **Levels.** The consensus level "adds value only among stocks with
    favorable quantitative characteristics (i.e., high value and positive
    momentum)". Among stocks with unfavorable characteristics, "higher
    consensus recommendations are associated with worse subsequent returns."
  - **Changes.** The quarterly *change* is "a robust return predictor"
    orthogonal to other signals.
  - **Replication.** An unaudited replication over 1990-2026 returned 0.20% a
    year (Sharpe 0.10).
- **Barber-Lehavy-Trueman**
  ([paper](https://www.anderson.ucla.edu/documents/areas/fac/accounting/trueman_ratings.pdf)).
  Daily abnormal returns, 1986-2006:

  | Group | Per day |
  |---|---|
  | Strong buy | +1.0 bp |
  | Buy | +0.7 bp |
  | Hold | −0.2 bp |
  | Sell | −2.5 bp |
  | Upgrades | +1.9 bp |
  | Downgrades | −1.0 bp |
  | Upgrades to buy or strong buy | +2.0 bp |
  | Upgrades to hold or sell | +0.1 bp |
  | Double upgrades to buy minus double downgrades to sell | +5.2 bp |

  Levels matter given changes.
- **Barber-Lehavy-McNichols-Trueman 2001.** Consensus strategies earn over 4% a
  year gross with daily rebalancing, "not reliably greater than zero" net
  ([abstract](https://econpapers.repec.org/article/blajfinan/v_3a56_3ay_3a2001_3ai_3a2_3ap_3a531-563.htm)).
- **China.** The trend effect weakens after revisions, and recommendations
  often contradict trend signals
  ([Ma et al. 2023](https://www.sciencedirect.com/science/article/abs/pii/S0927538X23001452),
  abstract only).
- **For the grade.**
  - A favorable stance is informative when the trend agrees, and the grade
    already requires trend.
  - When the trend breaks, a still-favorable stance predicts *worse* returns
    (Jegadeesh et al.). "A-grade with a broken trend" is exactly where
    dip-buying fails.
  - The grade's changes carry more information than its level.

### 5.3 The price path after upgrades and downgrades

- **Womack 1996**
  ([abstract](https://econpapers.repec.org/article/blajfinan/v_3a51_3ay_3a1996_3ai_3a1_3ap_3a137-67.htm)).
  After a large initial reaction, buy recommendations drift "+2.4 percent" and
  "short-lived". Sell recommendations drift "−9.1 percent", extending for six
  months.
- **Loh-Stulz 2011**
  ([paper](https://cpb-us-w2.wpmucdn.com/u.osu.edu/dist/0/30211/files/2017/07/When-Are-Analyst-Recommendation-Changes-Infuential-2kelvug.pdf);
  [NBER abstract](https://www.nber.org/papers/w14971)). 1993-2006, two-day
  reactions to one-notch changes:

  | Change | Full sample | Excluding earnings, guidance and multiple-recommendation days |
  |---|---|---|
  | Upgrade | +2.50% | +1.91% |
  | Downgrade | −3.55% | −1.56% |

  Days 0 and +1 account for "almost all" of the −5 to +5 day reaction. More
  than a third of reactions have the wrong sign, and only about 10% are
  significant.
- **Bradley-Clarke-Lee-Ornthanalai 2014**
  ([working paper](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/jump2-1-12.pdf)).
  With corrected timestamps, 30-minute returns are +1.83% for upgrades and
  −2.10% for downgrades. 25% of recommendations come with price jumps.
- **Piggybacking.** Revisions "piggyback on recent news, events, long-term
  momentum, and short-run contrarian return predictors" and are "usually
  information-free"
  ([Altınkılıç-Hansen 2009](https://econpapers.repec.org/RePEc:eee:jaecon:v:48:y:2009:i:1:p:17-36),
  abstract only).
- **No drift after 2003.** Post-revision drift was not significantly different
  from zero in 2003-2010
  ([Altınkılıç-Hansen-Ye 2016](https://econpapers.repec.org/RePEc:eee:jfinec:v:119:y:2016:i:2:p:371-398),
  abstract only).
- **Attention.** In low-attention (low-turnover) stocks, the drift is "more
  than double"
  ([Loh 2010](https://econpapers.repec.org/RePEc:bla:finmgt:v:39:y:2010:i:3:p:1223-1252),
  abstract only).
- **Earnings-based changes**
  ([Kecskés-Michaely-Womack 2017](https://ideas.repec.org:443/a/inm/ormnsc/v63y2017i6p1855-1871.html),
  abstract only). Changes that come with EPS revisions have larger initial
  reactions (+1.3% for upgrades, −2.8% for downgrades) *and* larger drift. As
  a strategy they earn 3% a month risk-adjusted.
- **Analyst trade ideas, 2000-2015**
  ([Birru-Gokkaya-Liu-Stulz 2022](https://www.nber.org/system/files/working_papers/w26062/w26062.pdf)).
  Two-day reactions are +0.906% for buys and −1.963% for sells. Buys continue
  to 1.19% at 5 days, 1.39% at 42 and 1.90% at 63, with no reversal.
- **Small first reactions**
  ([Kudryavtsev 2020](https://ideas.repec.org/a/spt/rmkjrc/v7y2020i1f.html),
  low-tier journal). One- to six-month drifts after upgrades (downgrades) are
  larger when the first 5-10 days' reaction is low (high).
- **Retail attention**
  ([Welagedara-Deb-Singh 2017](https://ideas.repec.org/a/eee/pacfin/v45y2017icp211-223.html),
  abstract only). Investors underreact to upgrades, more so when retail
  attention is high. Downgrades are priced faster, and downgrades of
  high-retail-attention stocks overreact and reverse.
- **Contrarian revisions**
  ([CFA digest](https://rpc.cfainstitute.org/research/cfa-digest/2014/01/bucking-the-trend-the-informativeness-of-analyst-contrarian-recommendations-digest-summary)).
  Revisions against the recent trend (53,085 revisions, 1994-2009) draw
  stronger reactions: upgrades 0.27 points more, downgrades 0.59 points more
  negative. The effect is mostly before Reg FD.

**The typical path** (my synthesis):

1. a run-up in the direction of the revision before the event (piggybacking);
2. a jump concentrated in the first 30 minutes to day +1;
3. in the post-2003 large-cap era, roughly flat drift on average.

Drift is larger when the change is earnings-based, when attention is low, and
after downgrades in older samples.

**Timing entries after an upgrade.** No documented post-upgrade pullback
exists to wait for. The one result on the initial reaction (small first
reaction, larger drift) argues for entering promptly when the reaction was
small.

**Timing exits after a downgrade.** Most of the move is on days 0 and +1.
Waiting several days for a bounce has support only in retail-attention
overreactions.

The book's grade is internal, not a sell-side rating. Its nearest analogs are
earnings-based changes (Kecskés) and post-earnings drift, which is gone in large
caps (Martineau).

### 5.4 Pops in weak or downgraded names

- **Attention pops fade.** Intense Robinhood buying predicts −4.7% abnormal
  return over 20 days for the top stocks bought each day
  ([Barber et al. 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190),
  abstract only).
- **Pops without information fade:**
  - no-information winners reverse (Savor);
  - no-news winners reverse (Chan);
  - winners with weak fundamentals reverse (Zhu-Sun-Chen);
  - short-side reversal reflects sentiment under short-sale constraints (Da,
    Liu and Schaumburg).
- **Bad news travels slowly,** mostly in stocks with low analyst coverage and in
  losers
  ([Hong-Lim-Stein 2000](https://www.nber.org/papers/w6553)). That matters less
  for these covered names.
- **The disposition channel**
  ([Frazzini 2006](https://pages.stern.nyu.edu/~afrazzin/pdf/The%20Disposition%20Effect%20and%20Underreaction%20to%20news%20-%20Frazzini.pdf)).
  Stocks with large unrealized losses underreact to bad news, at about −1.13% a
  month alpha. The overhang spread earned 2.43% a month over 1980-2002.
- **Reading.** "Sell pops in weak names" is supported when the pop is a no-news
  attention pop. Waiting days for a pop in a weak name with bad news is the
  disposition error (§6.2).

### 5.5 How value, momentum and quality interact

- **Value and momentum.** Value works best among losers, and momentum works best
  among *expensive* stocks
  ([Asness 1997](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/1997/the-interaction-of-value-and-momentum-strategies)).
  For expensive tech names, continuation dominates.
- **Quality.** Quality earns significant risk-adjusted returns in the US and 24
  other countries, and they cannot be tied to risk
  ([Asness-Frazzini-Pedersen, QMJ](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk)).
- **Earnings momentum**
  ([Novy-Marx 2015](https://www.nber.org/papers/w20984)).
  - **It explains price momentum.** Earnings momentum explains price momentum,
    and past price performance has no independent pricing power.
  - **Crashes.** Controlling for past performance in earnings-momentum
    strategies removes the crashes without lowering returns.
  - **For timing.** The fundamental leg, the grade, is the durable one. Price
    conditioning mainly adds volatility.

### 5.6 What this book has already shown

From `stage3-results-2026-09-29.md`:

- **One-month reversal features** separate graded names at large (IC −0.03 to
  −0.05, same sign in 2016-19 and 2020-23). They do not separate A/A+ names
  from each other.
- **Dropping the most stretched A name** was flat on 2016-2023 (−14 bp per 20
  sessions) and cost 4.5% on 2024-2026 (t +2.4).
- **The richest models could not beat the 1% dip rule.** They had bands, RSI,
  levels, VWAP and multi-timeframe trend.

### 5.7 Synthesis: when the operator's intuition is right and when it is wrong

| Situation | Literature says | Direction for the rule |
|---|---|---|
| A name, residual dip vs SMH/IGV, no 8-K, formed intraday, name not near highs, low relative turnover | reversal is likeliest here (§2.4-2.7, §5.1) | wait a few days for a dip: supported in direction, small in size |
| A name, dip on news (8-K, earnings, guidance) | news moves carry information; large-cap drift is about 0 after 2006 | do not wait; buy on schedule, or re-grade |
| A name near its 52-week high with high turnover | short-term momentum; household limit sells there are uninformed | buy now; waiting costs drift |
| A name whose trend broke while analysts stay bullish | favorable levels predict *worse* returns without favorable quantitative signals | the grade should catch it; do not buy the dip |
| Market-wide stress (VIX ≥ 25) | liquidity provision pays at 1-5 days; monthly reversal crashes in crises | only very short waits, small size |
| B/C name after a news-driven downgrade | news drifts; reaction concentrated on days 0 and +1 | sell now (pop or close on day 0) |
| B/C name after a no-news slide | liquidity dips revert partly | a short wait for a bounce is defensible; gain small |
| B/C name spiking without news (attention) | attention and no-news pops fade | sell into the pop now; never wait days for one |

---

## 6. Exit timing

### 6.1 Stops

- **Kaminski-Lo 2014**
  ([paper](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf)).
  - **Theory.**
    - With IID returns, stops always lower the expected return: the stopping
      premium is −p·π.
    - Stops help only with momentum (ρ ≥ π/σ) or with regime switching they
      detect.
  - **Test.** S&P futures against 10-year Treasury futures, 1993-2011.
    - **Monthly stops added value** (one calibration: +1.5% return, −5%
      volatility, Sharpe up to 20% higher).
    - **Daily and weekly stops** had negative stopping premiums over large
      parameter ranges.
- **Han-Zhou-Zhu**
  ([summary](https://paperswithbacktest.com/strategies/taming-momentum-crashes-a-simple-stop-loss-strategy);
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199); working
  paper, abstract only).
  - **The effect.** A 15% stop on momentum portfolios cuts the worst monthly
    loss from −49.79% to −17.43% (equal-weight) and from −64.97% to −22.10%
    (value-weight), 1926-2013. Sharpe ratios "more than doubled".
  - **The caveat.** Those crashes are mostly short-leg events, and this is a
    long-short portfolio, not a long-only book of single names.
- **Trailing stops on US stocks, 1926-2016**
  ([Dai-Marshall-Nguyen-Visaltanachoti 2021, ACFR summary](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk)).
  - **Returns.** They lower risk, but also returns and the Sharpe ratio.
  - **Costs.** After costs, thresholds tighter than 10% lose; 10-20% thresholds
    keep reducing downside risk.
- **Mean-reversion systems.** Connors: stops "hurt"
  ([StockCharts](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2);
  practitioner).
- **In-house.** Catastrophe stops, trims, volatility sizing and profit taking
  all failed their registered tests (feature-research §6.4).
- **For this book.**
  - A names are in a momentum regime. Wide trailing stops (≥ 15-20%, or 3-4
    ATR) might be close to neutral. Tight stops lose after costs.
  - The downgrade exit is already a slow, information-based stop.

### 6.2 Selling into strength or weakness, and the disposition effect

- **Winners sold beat losers held**
  ([Odean 1998](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf)).
  Winners investors sold went on to beat the losers they kept by 1.03% over 84
  trading days and 3.41% over 252.
- **Losses plus bad news keep underperforming**
  ([Frazzini 2006](https://pages.stern.nyu.edu/~afrazzin/pdf/The%20Disposition%20Effect%20and%20Underreaction%20to%20news%20-%20Frazzini.pdf)).
- **Professional sells**
  ([Akepanidtaworn-Di Mascio-Imas-Schmidt 2023](https://www.nber.org/system/files/working_papers/w29076/w29076.pdf)).
  - **Sells.** Portfolio managers' sells underperform a random-sell
    counterfactual by about 80 bp over a year. Their buys beat it by about 120
    bp.
  - **The heuristic.** Positions in the top or bottom 5% of past returns are
    sold more than 50% more often.
  - **Attention helps.** Sells on earnings days, when attention is high, are
    better by about 154 bp.
- **Limit-order adverse selection** mechanically produces poor post-trade
  returns, the disposition effect and contrarian-looking patterns
  ([Linnainmaa 2010](https://paperswithbacktest.com/strategies/do-limit-orders-alter-inferences-about-investor-performance-and-behavior),
  abstract only).
- **Household limit sells at the 52-week high** are uninformed, and
  institutions profit from them
  ([Della Vedova et al. 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1)).
- **Implications:**
  1. Rule-based exits (the grade) beat discretionary sells of salient
     extremes.
  2. Do not trim A names just because they popped. Profit-taking lost
     in-house, and stretched names kept winning.
  3. A same-day pop sell for a downgraded name is harmless. Waiting days for
     one is the disposition trap.
  4. Avoid resting sell limits at salient levels: the 52-week high and round
     numbers.

### 6.3 Time stops

- **No peer-reviewed evidence** was found.
- **Practitioner mean-reversion systems** exit on close > SMA5, RSI(2) above
  50-70, or a 10-day time stop, with typical holds of 4-5 days (Connors;
  Alvarez).
- **For this book,** the 20-session reset already acts as the time stop.

### 6.4 After a downgrade

- **Timing of the move.** Most of the reaction is on days 0 and +1 (Loh-Stulz;
  Bradley et al.).
- **No later drift.** Post-revision drift is about zero after 2003
  (Altınkılıç-Hansen-Ye), and post-earnings drift about zero in large caps
  after 2006 (Martineau).
- **The one exception.** No-news liquidity dumps may bounce.
- **So** exit timing after a downgrade is probably immaterial in expectation.
  Executing on day 0 minimizes variance and complexity.

### 6.5 Verdict for topic 5

| Claim | Evidence | Applies to our names? | Grade |
|---|---|---|---|
| Stops improve returns | only with momentum or regime switching; trailing stops on stocks lower Sharpe | wide stops about neutral, tight stops lose | A (as a negative) |
| Sell into strength | winners sold outperform; profit-taking lost in-house | not for A names | A |
| Sell weak names on pops | yes for no-news attention pops; waiting for pops loses | sell on day 0; take a same-day pop if it comes | A/B |
| Time stops | practitioner only | the 20-session reset already does it | C |

---

## 7. Candidate rules for a grade-conditional multi-day timing study

### 7.1 Common protocol and definitions

**The test.** The rules are tested as in stage 3 T-I:

- **Orders.** The `/4` policy's own orders.
- **Control.** The board as it is: BUY = `dip_or_close` on day 0; SELL/TRIM =
  pop-or-close on day 0.
- **Offsets and costs.** 20 offsets; costs of 10, 16 and 25 bp one way.
- **Statistics.** Newey-West at lag 20; per differing order, with the t
  clustered by date.
- **Windows.** 2016-2023 is the choosing window; 2024-2026 is reported only.

**Day 0** is the session in which the allocator emits the order.

**Triggers.**

- **When they are evaluated.** On the 15:30 live row (the `C15:30` convention);
  a fired trigger executes in that session's closing auction.
- **Robustness run.** Evaluate at the prior close and execute through the next
  session's `dip_or_close` or pop-or-close.

**Fallback.** If no trigger fires by session W, execute at the close of W.

**Cancellation.**

- **When.** A pending buy is cancelled if the name falls below A during the wait.
  A pending sell is cancelled if the name returns to A.
- **Rebalances.** A rebalance during the wait replaces the pending order.
- **Reporting.** Cancellations are reported separately, because avoided round
  trips are a possible gain of their own.

**Money while waiting.**

- **Buys.** The pending buy's capital sits in the idle-cash redeploy leg, the
  live executor's behavior. Waiting then costs the name's return minus the
  book's. Report a cash variant too.
- **Sells.** A pending sell keeps the position.

**Definitions.**

- **Residual return.** r_d is the daily log return. The theme ETF is SMH for
  semiconductors and IGV for software.
  - β60 is the OLS beta on the theme over sessions d−60..d−1.
  - e_d = r_d − β60·r_theme,d.
  - σ_e is the standard deviation of e over d−60..d−1.
  - z1 = e_d/σ_e and z5 = Σ_{k=0..4} e_{d−k}/(σ_e·√5).
- **No-news flag.** NN_d = 1 if no 8-K was accepted between 16:00 ET on session
  d−3 and 15:30 on d; filings after 16:00 count for the next session
  (`edgar.py`). NN5_d = 1 if no 8-K was accepted over sessions d−4..d, the
  window of z5, on the same timing convention. The variant with item 2.02
  only counts as a separate trial.
- **Intraday share.** IS5 = Σ_5 log(C/O) / Σ_5 r over the last 5 sessions,
  computed only when Σ_5 r < 0 and clipped to [0, 1.5].
- **Price indicators.**
  - RSI(2) with Wilder smoothing.
  - SMA_n on adjusted closes.
  - PTH = C/max(H over 252 sessions).
  - IBS = (C − L)/(H − L), and 0.5 if H = L.
  - BB(20, 2) as SMA20 ± 2·sd20. Squeeze = BandWidth ≤ its minimum over the
    prior 126 sessions. TTM-on = BB(20, 2) inside KC(20, 1.5·ATR20, Wilder).
- **Turnover.** The 20-session mean of volume over point-in-time shares
  outstanding, ranked within the day's eligible names.
- **VIX.** The CBOE VIX at 15:30 on day d.

### 7.2 The candidates

| ID | Name | Grades acting | Buy trigger (wait W, fallback) | Exit counterpart (wait W, fallback) | Evidence | Expected |
|---|---|---|---|---|---|---|
| T1 | RSI2-A (Connors) | buys A+/A; sells below A | RSI(2) ≤ 10 and C > SMA200 (5; close of day 5) | RSI(2) ≥ 90 (3; close of day 3); no wait if NN = 0 or C < SMA50 | C | negative on 2024-26 |
| T2 | Residual dip without news, formed intraday | buys A+/A; sells below A | z5 ≤ −1.5, NN5 = 1, IS5 ≥ 0.5 (5; close of day 5) | sell on day 0 if NN = 0 in the last 3 sessions or z5 ≥ +1.5; else wait for z1 ≥ +1.0 with NN = 1 (3; close of day 3) | A/B (direction) | per order ≥ 0; book about 0 |
| T3 | VIX liquidity provision | only when VIX ≥ 25 | z1 ≤ −1.5 and NN = 1 (3; close of day 3) | z1 ≥ +1.5 and NN = 1 (2; close of day 2); news → day 0 | A at 1-5 days | noisy, few events |
| T4 | Grade urgency | buys: A+ day 0, A waits; sells: C day 0, B waits | A: T2 trigger (3; close of day 3) | B: z1 ≥ +1.0 and NN = 1 (3; close of day 3); C and news → day 0 | B−, inferred | about 0 |
| T5 | Grade-change event | buys on upgrades into A/A+; sells on downgrades below A | CAR5 ≤ +1: day 0. CAR5 > +2: wait for a 1σ_e pullback from the post-event high (5; close of day 5) | CAR5 ≥ −1 or news: day 0. CAR5 ≤ −2 with NN = 1: wait for z1 ≥ +1 (3; close of day 3) | B−/C | about 0 |
| T6 | Squeeze breakout | only if squeeze or TTM is on at day 0 | first close above the upper band (10; close of day 10) | lower-band close: sell now; upper-band close: hold (5; close of day 5) | C/B↓ | negative or 0 |
| T7 | T2 with a momentum veto | as T2 | as T2, but waits only if PTH < 0.90 and turnover rank below the median; otherwise day 0 | same veto on sells | A/B | ≥ T2 per order, fewer orders |
| T8 | IBS one-day deferral | only on fall-back-to-close days | if IBS ≥ 0.8 and RSI(2) ≥ 70: defer to day 1's `dip_or_close` (max 1 day) | if IBS ≤ 0.2 and RSI(2) ≤ 30: defer to day 1's pop-or-close | C | immaterial |
| T9 | Dip overlay on A names | held A+/A names | add +50% of target weight (cap 20%) on the T7 trigger; one add per name at a time | trim the add at the first z1 ≥ +1.0 with NN = 1, or after 10 sessions, or on a downgrade | A/B direction; costs decide | negative after costs |

CAR5 = Σ e over sessions −4..0, divided by σ_e·√5.

**Details and reasons.**

- **T1, RSI2-A.**
  - **What it tests.** The operator's "buy weakness in an uptrend" in its
    best-known retail form, as a named control.
  - **Why it should fail:**
    - The edge in practitioner tests sits in small, fallen stocks (§3.1).
    - The trigger ignores news.
    - A names on 2024-2026 behaved with momentum.
  - **A variant, T1b.** Three consecutive lower closes above SMA200 (sells:
    three higher closes). If run, it counts as its own trial.
- **T2, residual dip without news, formed intraday.**
  - **The idea.** It encodes every reversal condition the literature supports
    that the book can observe: residual against the theme; no 8-K; formed
    intraday; A-grade fundamentals (§2.4-2.6, §5.1).
  - **The sell side.** Selling is immediate unless the weakness is a no-news
    slide. That follows the news-drift and disposition evidence (§5.4,
    §6.2).
  - **Expected result.** The best per-order diagnostic of the set. It is still
    very unlikely to reach the book floor (§8).
- **T3, VIX liquidity provision.** Nagel's time variation, gated to high-VIX
  days. The number of events is small. The monthly crisis crashes (§2.3) are a
  warning that longer waits in stress catch falling knives.
- **T4, grade urgency.** The operator's "grade-weighted timing" taken
  literally. Conviction sets patience: A+ never waits, A may; C exits at once,
  B may wait.
- **T5, grade-change event.**
  - **The idea.** It uses the one piece of evidence on the path after an event
    (small first reaction → larger drift; Kudryavtsev) and the earnings-based
    change result (Kecskés).
  - **Exact trigger.** The pullback is a close at least σ_e (one daily residual
    standard deviation, as a fraction of price) below the highest close since
    day 0. For 1 < CAR5 ≤ 2 the order executes on day 0, as in the control.
    Rebalance top-ups and trims that are not grade events also follow the
    control.
  - **Weaknesses.** Low-tier sources, and zero drift after 2003
    (Altınkılıç-Hansen-Ye).
- **T6, squeeze breakout.**
  - **What it tests.** The operator asked about squeezes. This is the
    Fang-Jacobsen-Qin "squeeze method" as a timing rule.
  - **Why it should fail.** The literature says the squeeze adds no direction
    and the breakout's profits have decayed.
  - **A diagnostic first** (D1 in §7.4). Most of the question can be answered
    without spending a trial.
- **T7, T2 with a momentum veto.**
  - **The change.** Waiting is allowed only where reversal is documented: away
    from the 52-week high and at below-median turnover (Chen-Stivers-Sun;
    Medhat-Schmeling; Chiang-Kirby-Nie).
  - **Expected result.** It changes fewer orders, so the per-order gain can be
    higher while the book effect stays small.
- **T8, IBS one-day deferral.** A close-location filter at one day
  (Pagonidis; Alvarez). It is at most a few bp per affected order. It overlaps
  with the end-of-day reversal, which is already in the closing price.
- **T9, dip overlay on A names.**
  - **Why it exists.** It is the only design with enough orders to move the
    book, because it trades beyond the allocator's orders.
  - **Why it should fail.** It pays two costs per round trip: §2.8 shows 16 bp
    one way wipes out even pre-2010 large-cap reversal. The arithmetic is in
    §8.
  - **Constraint.** It must respect the 20% cap and the executor's
    breakout-entry gate from stage 3.

### 7.3 Which the evidence supports, and which will likely fail

- **Best supported:** T2 and T7.
  - Their conditioning variables (news, residual against the theme, formed
    intraday, away from highs and heavy turnover) are exactly those the
    literature ties to reversal.
  - T7 is the version most consistent with this book's own 2024-2026 finding
    that stretched names kept winning.
- **Likely to fail:**
  - **T1 and T1b** (oscillator dips ignore news and momentum);
  - **T6** (no direction in squeezes);
  - **T8** (immaterial);
  - **T5** (weak evidence, zero drift after 2003);
  - **T4** (conviction-weighted patience has no direct evidence);
  - **T3** (right idea, too few events, crash risk);
  - **T9** (costs).

### 7.4 Registration advice

1. **Register few trials.**
   - **Primaries:** T2, T7 and T9.
   - **Operator-requested named controls:** T1 and T6.
   - **Leave T3, T4, T5 and T8 unregistered** unless the operator asks for them.
   - **The count.** Five trials take the cumulative count from 408 to 413. The
     expected best null t stays about 3.0.
2. **Diagnostics before any decision test** (descriptive only; counted per the
   book's convention):
   - **D1.** After a squeeze, is the 1-20 day absolute residual move larger
     than its unconditional value, and is its sign predictable?
   - **D2.** How often does T2's trigger fire inside a 5-session window, and
     what is the mean residual return over days 1-5 after it fires, split by
     news?
   - **D3.** The same as D2 for the sell side after downgrades.

   If D2's post-trigger residual is below +25 bp, drop T2, T7 and T9 before
   spending the trials.
3. **Keep the per-order diagnostic.** A per-order gain of at least 25 bp with
   t ≥ 3 that fails the floor is "RECORD: real but immaterial", as in stage 3.
4. **Pass bar.** The same floors as stage 3: +2 bp a session with t ≥ 2 on
   2016-2023 at 16 and 25 bp, not negative on 2024-2026, and deflated Sharpe
   ≥ 0.95.

---

## 8. Honest prior

| Outcome | Prior |
|---|---|
| Any of T1-T8 passes the +2 bp a session floor after 16-25 bp costs (t ≥ 2 on 2016-23, ≥ 0 on 2024-26, deflated Sharpe ≥ 0.95) | about 3% |
| T9 (the overlay) passes | about 2-3% |
| At least one honest pass | about 5% |
| T2 or T7 shows a per-order gain ≥ 25 bp with t ≥ 3 but fails the floor | about 10-15% |
| T1 or T6 is negative on 2024-2026 | about 70% |

**Reasons.**

1. **The arithmetic** (§1).
   - **Even the best case falls short.** The largest historical large-cap
     reversal leg is 43.7 bp a week gross, pre-2010. Captured on every order,
     it would add about 1.2 bp a session. The floor needs 59-106 bp per order.
   - **No gain without reversal.** Under a martingale, waiting rules earn zero
     minus drift.
2. **T9's overlay arithmetic.**
   - **The formula.** bp a session = n × w × (g − 2c), where n is triggers a
     session, w the add size in NAV, g the gross edge per round trip and c the
     one-way cost.
   - **Plugging in.** Assume n ≈ 0.3 (about 8 held names, each triggering on
     about 4% of sessions; to be measured in D2), w = 5% and c = 16 bp. Reaching
     +2 bp a session then needs g ≈ 165 bp per round trip. With w = 10%, where
     the 20% cap allows it, g ≈ 99 bp.
   - **Against the literature.** Its large-cap weekly figure is under 45 bp
     gross, and it is from before 2010.
3. **Decay.** Plain large-cap reversal has been about zero since 1990 and
   negative since 2020 (Appendix A).
4. **The regime.** A names are high-turnover and often near their highs, where
   monthly reversal becomes momentum (§2.7, §4.4). The book's own 2024-2026 data
   agree.
5. **The record.** Every timing and sell-side overlay on this book has come out
   RECORD. The dip fill's edge over the close has been −8.7 and +36 bp per
   filled dip.
6. **Why it is not zero.** The news-conditioned residual reversal is real in
   the cross-section through at least 2009-2021, and nobody has tested it on
   this book's order flow. It could show a real per-order effect: the 10-15%
   line above.

## 9. What would change the prior

- **D2 on 2016-2023.** If T2's post-trigger 5-day residual is at least +60 bp
  with t ≥ 3 in both 2016-19 and 2020-23, and no-news beats news by at least
  50 bp:
  - the per-order prior rises to about 30%;
  - the floor prior rises to about 8% for T9 and stays about 3% for the rest.
- **D1.** If squeezes show a signed residual move after 5-20 days of at least
  50 bp in the direction of the prior 60-day trend, in both halves, T6 moves
  from "control" to "candidate".
- **Order flow.** If the book's orders per session rise, for example with a
  cap change or breakout-entry gating, the per-order hurdles in §1 fall
  proportionally.

**What may be worth more than timing** (an idea, not from the literature). If
grades flip often, a one- or two-night confirmation, or a hysteresis band,
before buying new A names and selling former ones may save more in avoided
round trips (2 × 16 bp) than any price-timing rule earns. The flip rate
(G02 in the feature catalogue) would show whether this is worth registering.

---

## References, by topic

**Short-term reversal.**
[Nagel 2012, NBER abstract](https://www.nber.org/papers/w17653) ·
[Nagel 2012, PDF](https://www.nber.org/system/files/working_papers/w17653/w17653.pdf) ·
[Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf) ·
[Chan 2003, working paper](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf) ·
[Chan 2003, JFE record](https://ideas.repec.org/a/eee/jfinec/v70y2003i2p223-260.html) ·
[Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf) ·
[De Groot-Huij-Zhou 2012](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf) ·
[Blitz et al. 2013](https://www.efmaefm.org/0EFMSYMPOSIUM/2012/papers/017_update.pdf) ·
[Blitz-van der Grient-Honarvar 2023, Robeco summary](https://www.robeco.com/en-us/insights/2023/10/reversing-the-trend-of-short-term-reversal) ·
[Dai-Medhat-Novy-Marx-Rizova 2024](https://www.nber.org/system/files/working_papers/w30917/w30917.pdf) ·
[Hameed-Mian 2015](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/BwXb81392625636.pdf) ·
[Khandani-Lo](https://www.nber.org/system/files/working_papers/w14465/w14465.pdf) ·
[Chordia-Subrahmanyam-Tong 2014](https://ideas.repec.org:443/a/eee/jaecon/v58y2014i1p41-58.html) ·
[Medhat-Schmeling 2022](https://assets.super.so/e46b77e7-ee08-445e-b43f-4ffd88ae0a0e/files/5dea8896-1a7b-4b9c-916e-439c0f1cfc71.pdf) ·
[Chiang-Kirby-Nie 2021](https://www.sciencedirect.com/science/article/abs/pii/S0378426621000261) ·
[Chen-Stivers-Sun 2024](https://ideas.repec.org/a/eee/empfin/v79y2024ics0927539824000902.html) ·
[Cheng-Hameed-Subrahmanyam-Titman 2017](https://si-cheng.net/wp-content/uploads/2018/12/2017-JFQA-Cheng_Hameed_Subrahmanyam_Titman-Short-Term-Reversals.pdf) ·
[Avramov-Chordia-Goyal 2006](https://users.nber.org/~confer/2004/mmsu04/goyal.pdf) ·
[Novy-Marx-Velikov 2016](https://www.nber.org/system/files/working_papers/w20721/w20721.pdf) ·
[Frazzini-Israel-Moskowitz, Trading Costs](https://spinup-000d1a-wp-offload-media.s3.amazonaws.com/faculty/wp-content/uploads/sites/3/2021/08/Trading-Cost.pdf) ·
[Kaniel-Saar-Titman 2008](https://static1.squarespace.com/static/5e6033a4ea02d801f37e15bb/t/5f5beb55689b700d25e3b1fe/1599859541913/kaniel_saar_titman_trading_and_returns.pdf) ·
[So-Wang 2014](https://ideas.repec.org/a/eee/jfinec/v114y2014i1p20-35.html) ·
[Ignashkina-Rinne-Suominen 2022](https://www.sciencedirect.com/science/article/pii/S0378426622000309) ·
[Lou-Polk-Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) ·
[Barardehi-Bogousslavsky-Muravyev](https://experts.illinois.edu/en/publications/what-drives-momentum-and-reversal-evidence-from-day-and-night-sig/) ·
[Della Corte-Kosowski](https://www.cicfconf.org/sites/default/files/paper_357.pdf) ·
[Akbas et al. 2022](https://ink.library.smu.edu.sg/lkcsb_research/7712/) ·
[Baltussen-Da-Soebhag](https://academicweb.nd.edu/~zda/EOD.pdf) ·
[Conrad-Hameed-Niden 1994](https://econpapers.repec.org/RePEc:bla:jfinan:v:49:y:1994:i:4:p:1305-29) ·
[Cooper 1999](http://home.business.utah.edu/finmc/Att34685.pdf) ·
[Chen-Cohen-Liang-Sun 2025](https://ideas.repec.org/a/eee/empfin/v82y2025ics0927539825000301.html) ·
[Cox-Peterson 1994](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p255-67.html) ·
[Bremer-Sweeney 1991](https://econpapers.repec.org/article/blajfinan/v_3a46_3ay_3a1991_3ai_3a2_3ap_3a747-54.htm) ·
[Rif-Utz 2021](https://www.sciencedirect.com/science/article/pii/S1062976921000922) ·
[Kudryavtsev 2017](https://riskmarket.co.uk/jrc/journals-articles/issues/vix-index-and-stock-returns-following-large-price-moves/) ·
[Martineau 2022](https://econpapers.repec.org/article/nowjnlcfr/104.00000122.htm)

**Rules and technical analysis.**
[StockCharts RSI(2)](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/rsi-2) ·
[Alvarez: health of mean reversion](https://alvarezquanttrading.com/blog/the-health-of-stock-mean-reversion-dead-dying-or-doing-just-fine/) ·
[Alvarez: RSI2 analysis](https://alvarezquanttrading.com/blog/rsi2-relative-strength-index-analysis/) ·
[Alvarez: RSI2 on ex-index stocks](https://alvarezquanttrading.com/blog/rsi2-strategy-double-returns-with-a-simple-rule-change/) ·
[Alvarez: IBS](https://alvarezquanttrading.com/blog/internal-bar-strength-for-mean-reversion/) ·
[Alvarez: mean reversion vs trend](https://alvarezquanttrading.com/blog/mean-reversion-vs-trend-following-through-the-years/) ·
[Alvarez: recent returns](https://alvarezquanttrading.com/blog/using-recent-returns-for-mean-reversion/) ·
[EasyLanguage Mastery RSI(2)](https://easylanguagemastery.com/strategies/connors-2-period-rsi-update-2019/) ·
[Pagonidis IBS](https://www.naaim.org/wp-content/uploads/2014/04/00V_Alexander_Pagonidis_The-IBS-Effect-Mean-Reversion-in-Equity-ETFs-1.pdf) ·
[Taylor 2014](https://research-information.bris.ac.uk/en/publications/the-rise-and-fall-of-technical-trading-rule-success/) ·
[Of Dollars and Data](https://ofdollarsanddata.com/even-god-couldnt-beat-dollar-cost-averaging/)

**Compression and breakouts.**
[Fang-Jacobsen-Qin 2017](https://acfr.aut.ac.nz/__data/assets/pdf_file/0007/29896/100009-Popularity-vs-Profitability-BB-August-Final.pdf) ·
[StockCharts squeeze](https://chartschool.stockcharts.com/table-of-contents/trading-strategies-and-models/trading-strategies/bollinger-band-squeeze) ·
[StockCharts TTM](https://chartschool.stockcharts.com/table-of-contents/technical-indicators-and-overlays/technical-indicators/ttm-squeeze) ·
[Bulkowski NR7](https://www.thepatternsite.com/nr7.html) ·
[Corsi 2009](https://academic.oup.com/jfec/article-abstract/7/2/174/856522) ·
[Ang-Hodrick-Xing-Zhang 2006](https://www.nber.org/papers/w10852) ·
[George-Hwang 2004](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf) ·
[George-Hwang abstract](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html) ·
[Huddart-Lang-Yetman 2009](https://pure.psu.edu/en/publications/volume-and-price-patterns-around-a-stocks-52-week-highs-and-lows-/) ·
[Della Vedova-Grant-Westerholm 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1) ·
[Lin 2018](https://ideas.repec.org/a/bla/acctfi/v58y2018is1p375-422.html) ·
[Gervais-Kaniel-Mingelgrin 2001](https://econpapers.repec.org/RePEc:bla:jfinan:v:56:y:2001:i:3:p:877-919) ·
[Wilcox-Crittenden 2005](https://www.cis.upenn.edu/~mkearns/finread/trend.pdf) ·
[Zarattini-Pagani-Wilcox 2025](https://concretumgroup.com/does-trend-following-still-work-on-stocks/)

**Grade-conditioned timing and analysts.**
[Jegadeesh-Kim-Krische-Lee 2004, abstract via paperswithbacktest](https://paperswithbacktest.com/strategies/analyzing-the-analysts-when-do-recommendations-add-value) ·
[Zhu-Sun-Chen 2019](https://www.sciencedirect.com/science/article/abs/pii/S0927539819300234) ·
[Quantpedia, FSCORE reversal](https://quantpedia.com/strategies/combining-fundamental-fscore-and-equity-short-term-reversals) ·
[paperswithbacktest, FSCORE reversal](https://paperswithbacktest.com/strategies/fundamental-strength-and-short-term-return-reversal) ·
[Zhu-Sun-Tu 2021](https://ink.library.smu.edu.sg/cgi/viewcontent.cgi?article=7866&context=lkcsb_research) ·
[Barber-Lehavy-Trueman](https://www.anderson.ucla.edu/documents/areas/fac/accounting/trueman_ratings.pdf) ·
[Barber et al. 2001](https://econpapers.repec.org/article/blajfinan/v_3a56_3ay_3a2001_3ai_3a2_3ap_3a531-563.htm) ·
[Womack 1996](https://econpapers.repec.org/article/blajfinan/v_3a51_3ay_3a1996_3ai_3a1_3ap_3a137-67.htm) ·
[Loh-Stulz 2011](https://cpb-us-w2.wpmucdn.com/u.osu.edu/dist/0/30211/files/2017/07/When-Are-Analyst-Recommendation-Changes-Infuential-2kelvug.pdf) ·
[Loh-Stulz, NBER abstract](https://www.nber.org/papers/w14971) ·
[Bradley et al. 2014](https://www.scheller.gatech.edu/directory/research/finance/lee/pdf/jump2-1-12.pdf) ·
[Altınkılıç-Hansen 2009](https://econpapers.repec.org/RePEc:eee:jaecon:v:48:y:2009:i:1:p:17-36) ·
[Altınkılıç-Hansen-Ye 2016](https://econpapers.repec.org/RePEc:eee:jfinec:v:119:y:2016:i:2:p:371-398) ·
[Loh 2010](https://econpapers.repec.org/RePEc:bla:finmgt:v:39:y:2010:i:3:p:1223-1252) ·
[Kecskés-Michaely-Womack 2017](https://ideas.repec.org:443/a/inm/ormnsc/v63y2017i6p1855-1871.html) ·
[Birru et al. 2022, NBER](https://www.nber.org/system/files/working_papers/w26062/w26062.pdf) ·
[Birru et al. 2022, JF record](https://ideas.repec.org/a/bla/jfinan/v77y2022i3p1829-1875.html) ·
[Kudryavtsev 2020](https://ideas.repec.org/a/spt/rmkjrc/v7y2020i1f.html) ·
[Welagedara-Deb-Singh 2017](https://ideas.repec.org/a/eee/pacfin/v45y2017icp211-223.html) ·
[CFA digest, contrarian revisions](https://rpc.cfainstitute.org/research/cfa-digest/2014/01/bucking-the-trend-the-informativeness-of-analyst-contrarian-recommendations-digest-summary) ·
[Ma et al. 2023](https://www.sciencedirect.com/science/article/abs/pii/S0927538X23001452) ·
[Asness 1997](https://rpc.cfainstitute.org/en/research/financial-analysts-journal/1997/the-interaction-of-value-and-momentum-strategies) ·
[Quality Minus Junk](https://www.aqr.com/Insights/Research/Working-Paper/Quality-Minus-Junk) ·
[Novy-Marx 2015](https://www.nber.org/papers/w20984) ·
[Hong-Lim-Stein 2000](https://www.nber.org/papers/w6553) ·
[Barber et al. 2022](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190)

**Exits.**
[Kaminski-Lo 2014](https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf) ·
[Han-Zhou-Zhu, summary](https://paperswithbacktest.com/strategies/taming-momentum-crashes-a-simple-stop-loss-strategy) ·
[Han-Zhou-Zhu, SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199) ·
[Dai et al. 2021, ACFR summary](https://acfr.aut.ac.nz/research/using-trailing-stop-loss-rules-to-reduce-risk) ·
[Odean 1998](https://faculty.haas.berkeley.edu/odean/papers%20current%20versions/areinvestorsreluctant.pdf) ·
[Frazzini 2006](https://pages.stern.nyu.edu/~afrazzin/pdf/The%20Disposition%20Effect%20and%20Underreaction%20to%20news%20-%20Frazzini.pdf) ·
[Akepanidtaworn et al., NBER abstract](https://www.nber.org/papers/w29076) ·
[Akepanidtaworn et al., PDF](https://www.nber.org/system/files/working_papers/w29076/w29076.pdf) ·
[Linnainmaa 2010](https://paperswithbacktest.com/strategies/do-limit-orders-alter-inferences-about-investor-performance-and-behavior)

**Data.**
[French: reversal factor](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_ST_Reversal_Factor_CSV.zip) ·
[French: 6 portfolios, size × prior 1-0](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/6_Portfolios_ME_Prior_1_0_CSV.zip) ·
[French: 25 portfolios, size × prior 1-0](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/25_Portfolios_ME_Prior_1_0_CSV.zip) ·
[CBOE VIX history](https://cdn.cboe.com/api/global/us_indices/daily_prices/VIX_History.csv)

**Internal.** `claude/stage3-results-2026-09-29.md` and
`claude/feature-research-2026-09-29.md` (project docs).

### Access notes

- **Abstract or summary only**, with figures taken from the abstract or
  summary:
  - Jegadeesh-Kim-Krische-Lee (SSRN and ResearchGate returned 429);
  - Barardehi-Bogousslavsky-Muravyev; Akbas et al.;
  - Zhu-Sun-Chen (numbers from the Quantpedia and paperswithbacktest pages);
  - Chiang-Kirby-Nie; Chen-Stivers-Sun; Chen-Cohen-Liang-Sun; So-Wang;
    Ignashkina et al.;
  - Chordia-Subrahmanyam-Tong; Altınkılıç-Hansen; Altınkılıç-Hansen-Ye;
    Loh 2010; Kecskés et al.;
  - Welagedara et al.; Lin 2018; Huddart et al.; Della Vedova et al.;
  - Gervais et al.; Conrad-Hameed-Niden; Cox-Peterson; Bremer-Sweeney;
    Martineau; Taylor;
  - Barber et al. 2022; Linnainmaa; Han-Zhou-Zhu stop-loss;
  - Dai et al. (ACFR summary);
  - Blitz-van der Grient-Honarvar (Robeco summary).
- **Working-paper versions** rather than the journal versions: Chan 2003 (2001
  draft), Bradley et al. (2012 draft), Avramov-Chordia-Goyal (2004 conference
  draft).
- **Figures read off a chart** by the fetch tool are marked "approximate":
  Nagel's largest-decile VIX figure, and Khandani-Lo's yearly averages.
- **Not read:**
  - the Springer page of "The reversal of large stock price declines: The case
    of large firms" (HTTP 429; no claim rests on it);
  - Lo-Remorov 2017 (not fetched);
  - Handa-Schwartz 1996 (Wiley 403);
  - the Driessen-Lin-Van Hemert abstract (cut off; no claim made);
  - the Stooq price download (connection reset; no own single-stock test was
    run);
  - the Kellogg and EFMA 2024 reversal pages (robots);
  - the CXO and Concretum Substack summaries (paywalled).
- **Seen in search results only, not opened:** Han-Zhou-Zhu 2016 trend factor
  (cited for its role, via the feature-research memo).

---

## Appendix A. Reversal decay and VIX split in the French library

**Data.**

- Ken French data library, CRSP 202608 vintage (through August 2026):
  - the ST_Rev factor;
  - 6 portfolios formed on size and prior 1-0 month return (2×3, value-weighted);
  - 25 portfolios formed on size and prior 1-0 month return (5×5,
    value-weighted).
- CBOE daily VIX closes from 1990.

**Method.**

- **Series** (monthly, value-weighted):
  - long the low prior-month-return portfolio, short the high one;
  - the "big half" legs of the 2×3 sort;
  - ME5 PRIOR1 minus ME5 PRIOR5 in the 5×5 sort;
  - the long leg as losers minus the middle portfolio.
- **Statistics.** Means by period with Newey-West t at 3 lags.
- **VIX split.** VIX at the end of month t−1 (formation) against the return in
  month t; terciles, a 25 threshold, and a linear slope with Newey-West t.

**Script.** `scorecards/stage4/french_reversal.py`; run it in a folder holding the
unzipped CSVs and `VIX_History.csv`.

**Additional results not tabulated above.**

- **VIX terciles** (ST_Rev factor):
  - **1990-2009.** Low 0.06%, mid 0.21%, high 0.42% a month; the slope is about
    0.
  - **2010-2026.** Low 0.10%, mid −0.44%, high 0.35%; the slope is 0.066 per
    VIX point, t 1.52.
- **Largest quintile after 2010.**
  - By tercile (cuts at VIX 15.4 and 19.0): low 0.01%, mid −0.21%, high
    −0.38%. No monotone relation.
  - Above VIX 25: +0.35% a month (n = 29), against −0.29% below it (n = 171).
  - So any VIX effect at the one-month horizon in the largest names sits in
    the few stress months, and is too noisy to rely on.
- **The big-half series over 2010-2026:08:** 200 months, 48% positive, monthly
  standard deviation 3.92%.

**Caveats.**

- These are market-wide, long-short, one-month holding portfolios. They are not
  the book's 94 names, and not 1-5 day horizons.
- The 1-5 day literature (Nagel; De Groot et al.) ends in 2009-2010.
