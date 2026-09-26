## topic
overlays-and-methodology
## findings
--- [0]
## technique
Index trend filter used as an exposure brake (Faber 10-month SMA, or 200-day SMA with hysteresis; the desk already runs this as the QQQ brake)
## sources
Faber (2007, updated 2013), 'A Quantitative Approach to Tactical Asset Allocation', Journal of Wealth Management, SSRN 962461: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461. CXO Advisory, '10-Month SMA Timing Signals Over the Long Run' (secondary source, Shiller data 1871-2012): https://www.cxoadvisory.com/technical-trading/10-month-sma-timing-signals-over-the-long-run/. Zakamulin (2014), 'The real-life performance of market timing with moving average and time-series momentum rules', J. Asset Management 15(4):261-278: https://econpapers.repec.org/RePEc:pal:assmgt:v:15:y:2014:i:4:d:10.1057_jam.2014.25. Desk code: backend/agents/trading/desk/trend_brake.py
## reported_evidence
Faber, S&P 500 1901-2012: timing CAGR 10.18% against buy-and-hold 9.32%. I confirmed these figures only through a search snippet of the author's PDF, because the PDF host did not resolve. While out of the market the rule holds 90-day T-bills. It is invested about 70% of the time and makes fewer than one round trip a year. Five-asset version 1973-2012: 10.5% against 9.9%. CXO over 1,704 months (1871-2012): mean monthly return 0.75% for SMA10 against 0.79% for buy-and-hold, SD 2.73% against 4.10%, in stocks 61.9% of the time. SMA10 was better risk-adjusted in 11 of 15 decades. It breaks even at about 1% one-way friction, and a one-month execution delay cuts the mean to 0.61%/month. Zakamulin's abstract: with out-of-sample tests and realistic costs, the reported performance is 'highly overstated'. Desk result: the QQQ 200-day brake (0.97/1.02, halve the book) cut max drawdown by about 10 points at about -1.7 CAGR, simulated with cash earning zero.
## replication_and_decay
Both the benefit and its size come from a few deep bear markets (1929-32, 1973-74, 2000-02, 2008). In V-shaped crashes (2020) and choppy years it whipsaws. Secondary summaries say Faber's post-2006 timing underperformed stocks in most years after 2009 (UNVERIFIED). My own arithmetic: about 30% of time out times a 3.5-4% average T-bill is about 1%/yr, roughly the whole 0.86%/yr CAGR edge Faber reports. So most of the historical total-return edge is T-bill income plus lower volatility drag. In a simulator where cash earns zero, as this desk's does, that edge largely vanishes.
## data_required
QQQ/^NDX daily from Yahoo (^NDX from 1985); Ken French daily market and RF series from 1926 (free); FRED DTB3 for T-bill yields.
## fit_to_this_desk
Already implemented and fully feasible on free data. The evidence says it is drawdown insurance. It cannot be expected to raise total return over QQQ in a bull-dominated decade. Only about 3 meaningful trend breaks fall in 2016-2026, so the parameters cannot be validated on the desk's own sample.
## implementation_sketch
Keep the frozen rule and do not retune. Re-score it (1) with cash credited at DTB3, (2) on independent long histories: French market 1926-2025 and ^NDX 1985-2026, reporting CAGR, max drawdown and the per-episode outcome for every bear market, and (3) as insurance, i.e. expected CAGR cost per point of drawdown avoided. Report it beside an unbraked twin at all 20 reset offsets.
## pitfalls
Mining the lookback (150/200/250 days, 10 months) and the band; signal lag in V-shaped recoveries; cost of delayed execution; zero cash yield biases the result against it; bootstrapping with short blocks destroys the 200-day structure.
## confidence
strong
--- [1]
## technique
Time-series momentum (12-month sign) on the index as an overlay
## sources
Moskowitz, Ooi, Pedersen (2012), 'Time series momentum', JFE 104(2):228-250. Huang, Li, Wang, Zhou (2020), 'Time series momentum: Is it there?', JFE 135(3):774-794, https://doi.org/10.1016/j.jfineco.2019.08.004 (PDF: https://down.aefweb.net/WorkingPapers/w717.pdf). Hurst, Ooi, Pedersen (2017), 'A Century of Evidence on Trend-Following Investing', JPM 44(1):15-29, https://jpm.pm-research.com/content/44/1/15.abstract
## reported_evidence
Huang et al. used the same 55 futures as MOP over 1985-2015. For 47 of 55 assets the t-statistic is below 1.65; only 8 slopes are significant at 10% and 3 at 5%. Only 3 assets have a significant out-of-sample R-squared. The pooled-regression t-statistic falls below parametric and nonparametric bootstrap critical values. A TSM strategy performs virtually the same as one based on the historical sample mean. Hurst et al.: diversified long/short trend-following was positive in every decade since 1880 and did well in 8 of the 10 largest 60/40 drawdowns.
## replication_and_decay
The case for TSM rests on diversified long/short multi-asset futures. Evidence for a single equity index is weak (Huang et al.). For a long/flat equity index it reduces to the trend filter above.
## data_required
Index daily closes only.
## fit_to_this_desk
No incremental value over the existing 200-day brake. The diversification benefit needs shorting and futures across asset classes, which is outside the mandate; Alpaca is not a futures broker (UNVERIFIED for current product set).
## implementation_sketch
None beyond a robustness twin: an ensemble of 6-12-month sign checks recorded next to the brake. This reduces specification risk (see the GEM fragility finding) without adding a tuned parameter.
## pitfalls
Pooled t-statistics overstate significance. A single-index signal gives only a handful of independent decisions per decade.
## confidence
strong
--- [2]
## technique
Dual momentum (Antonacci GEM: relative US vs international, absolute vs T-bills, bonds as the fallback)
## sources
Antonacci (2012/2017), 'Risk Premia Harvesting Through Dual Momentum', SSRN 2042750: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2042750. Newfound Research (2019), 'Fragility Case Study: Dual Momentum GEM': https://blog.thinknewfound.com/2019/01/fragility-case-study-dual-momentum-gem/
## reported_evidence
GEM 1974-2013: 17.43%/yr, SD 12.64%, Sharpe 0.87, max drawdown -22.7%, against ACWI at about 9.55%. These come from Antonacci's book and site via search results; I did not verify them in the primary PDF (UNVERIFIED). Newfound: over the same backtest, a 9-month lookback returned 43.1% cumulative against 146.1% for 10 months; in 2010 alone the figures were +12.2% and -9.31%. An equal-weight ensemble of 6-12-month lookbacks landed near the median outcome with a higher Sharpe and a lower drawdown.
## replication_and_decay
Secondary sources report that GEM lagged SPY by about 5 points a year over 2014-2022 (UNVERIFIED). It exited late in 2018 Q4 (at about -14%), and in 2022 bonds failed as the defensive asset.
## data_required
Daily ETF closes.
## fit_to_this_desk
The relative leg (international, bonds) is outside the stock/index/cash mandate. The absolute leg is the existing trend brake. Within the book, relative momentum already is the breakout rotation.
## implementation_sketch
Do not adopt. Carry over the lesson that specification risk is large, so any momentum or trend parameter should be run as an ensemble of lookbacks, not a single optimised value.
## pitfalls
Specification risk, lookback mining, whipsaw, choice of the defensive asset.
## confidence
moderate
--- [3]
## technique
Volatility-managed exposure (scale by inverse realised variance or volatility; Moreira and Muir) and its critiques
## sources
Moreira & Muir (2017), 'Volatility-Managed Portfolios', JF 72(4):1611-1644; NBER w22208: https://www.nber.org/system/files/working_papers/w22208/w22208.pdf. Cederburg, O'Doherty, Wang, Yan (2020), 'On the performance of volatility-managed portfolios', JFE 138(1):95-117, https://doi.org/10.1016/j.jfineco.2020.04.015. Liu, Tang, Zhou (2019), 'Volatility-Managed Portfolio: Does It Really Work?', JPM, SSRN 3283395. Barroso & Detzel (2021), JFE 140(3):744-767. Harvey, Hoyle, Korgaonkar, Rattray, Sargaison, Van Hemert (2018), 'The Impact of Volatility Targeting', JPM 45(1):14-33.
## reported_evidence
From the Moreira and Muir PDF text (verified): the scaled market (w = c / previous-month realised variance), 1926-2015, has alpha 4.86%/yr and beta 0.6. Its weights at the 75th/90th/99th percentiles are 1.6/2.6/6.4x. Their cost table: E[R] 9.47%, alpha 3.98% after 10bp, breakeven 56bp. Capped at 1 (no leverage): E[R] 5.61% excess, alpha 2.12%. Capped at 1.5: E[R] 7.18%, alpha 3.10%. Cederburg Table 1 puts the unmanaged market's excess mean at 7.80%/yr (1926-2016). So without leverage, vol management lowers total excess return by about 2.2 pts/yr, and even a 1.5x cap stays below buy-and-hold. Cederburg, 103 strategies (verified): the vol-managed version has the higher Sharpe in 53 cases and the original in 50 (binomial p=0.84); only 8 differences are significant, concentrated in momentum. Real-time out-of-sample, combining the managed and unmanaged market gives Sharpe 0.42 against 0.46 for the unmanaged market alone. Liu-Tang-Zhou: once look-ahead is removed from the scaling constant, max drawdowns are 68-93% and the strategy beats the market only during the financial crisis. Barroso-Detzel: after costs only the managed market survives, and only when sentiment is high. Harvey et al.: vol targeting raises Sharpe for equities and credit and reduces left tails.
## replication_and_decay
The weaknesses are well replicated: the gain disappears out of sample, it depends on leverage, and it relies on a full-sample scaling constant. The desk's own finding (vol / vol_trend allocation roughly halved CAGR) matches the no-leverage row.
## data_required
Daily index returns for realised volatility.
## fit_to_this_desk
It cannot raise total return over QQQ long-only and unlevered. It is a Sharpe and left-tail tool. The only legitimate use here is as a governor on a leverage sleeve (see the conditional leverage finding).
## implementation_sketch
Do not adopt standalone. If it is used as a leverage governor: 21-day realised volatility (not variance), clipped weights [0.5, 1.5], the scaling constant set from as-of data only, and monthly or hysteresis rebalancing to limit turnover.
## pitfalls
Full-sample c is look-ahead; the implied leverage is extreme when variance is low; margin cost; turnover; structural instability of the spanning regressions.
## confidence
strong
--- [4]
## technique
Risk-managed momentum (scale the momentum sleeve by its own trailing volatility)
## sources
Barroso & Santa-Clara (2015), 'Momentum has its moments', JFE 116(1):111-120: https://econpapers.repec.org/RePEc:eee:jfinec:v:116:y:2015:i:1:p:111-120. Cederburg et al. (2020), above. Daniel & Moskowitz (2016), 'Momentum crashes', JFE 122(2) (not fetched; UNVERIFIED details).
## reported_evidence
Barroso and Santa-Clara's abstract: momentum risk is highly variable and predictable, and managing it 'virtually eliminates crashes and nearly doubles the Sharpe ratio' of the long/short WML strategy. Cederburg: the few significant out-of-sample vol-management gains are concentrated in momentum-type strategies.
## replication_and_decay
Robust for long/short WML. The crash risk sits mostly in the short (loser) leg during rebounds (Daniel & Moskowitz; UNVERIFIED here), so a long-only winner book gets a smaller benefit.
## data_required
The book's daily returns.
## fit_to_this_desk
The breakout rotation is long-only momentum. Unlevered scaling of the book by its own volatility behaves like the vol-target the desk already found halves CAGR. Low expected benefit to total return.
## implementation_sketch
At most a recorded shadow in which the book is scaled to a volatility target inside a [0.75, 1.25] band, used only together with the leverage sleeve.
## pitfalls
Same leverage dependence and turnover as above; the evidence comes from long/short factors.
## confidence
weak
--- [5]
## technique
Drawdown control, stop-loss rules and CPPI / portfolio insurance
## sources
Kaminski & Lo (2014), 'When do stop-loss rules stop losses?', J. Financial Markets 18:234-254: https://dspace.mit.edu/bitstream/handle/1721.1/114876/Lo_When%20Do%20Stop-Loss.pdf. Annaert, Van Osselaer, Verstraete (2009), 'Performance evaluation of portfolio insurance strategies using stochastic dominance criteria', JBF 33(2):272-280, SSRN 979882: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=979882
## reported_evidence
Kaminski-Lo: whether a stop-loss adds value depends on the return process. Under a random walk it lowers expected return; under momentum or regime switching it can earn a positive 'stopping premium'. Annaert et al. (block bootstrap): buy-and-hold earns higher average excess returns than stop-loss, synthetic put or CPPI, and there is no stochastic dominance in either direction.
## replication_and_decay
The consensus is that insurance costs expected return. CPPI also carries cash-lock risk after a crash.
## data_required
Daily book NAV.
## fit_to_this_desk
The trend brake already serves as the drawdown control. A CPPI floor would add path dependence and would reliably cost total return against QQQ.
## implementation_sketch
Do not add. If a hard risk limit is required, record it as a pure risk constraint with its expected cost stated, not as a return improver.
## pitfalls
Cash lock; whipsaw; stacking with the brake doubles the de-risking lag cost.
## confidence
strong
--- [6]
## technique
Regime signals: VIX term structure, credit spreads, market breadth
## sources
Fassas & Hourvouliades (2019), 'VIX Futures as a Market Timing Indicator', JRFM 12(3):113: https://www.mdpi.com/1911-8074/12/3/113 (page returned 403; only the search summary was seen). Goyal, Welch, Zafirov (2024), RFS 37(11):3490-3557: https://academic.oup.com/rfs/article/37/11/3490/7749383. Welch & Goyal (2008), RFS 21(4). Market breadth across 64 countries, Economic Modelling (authors/year UNVERIFIED): https://www.sciencedirect.com/science/article/pii/S0264999319312982. FRED note on the ICE BofA HY OAS: https://fred.stlouisfed.org/series/BAMLH0A0HYM2
## reported_evidence
VIX futures: periods of backwardation were followed by positive S&P returns, so it acts as a contrarian signal; in contango there is no signal (search summary only). Goyal-Welch-Zafirov: of 29 predictors published after 2008, more than a third are no longer significant even in-sample, and half of the rest perform poorly out-of-sample. Breadth: advance-decline breadth predicts market and industry returns across 64 countries over 1973-2018 (abstract-level only). FRED, verified: starting April 2026 the ICE BofA HY OAS series keeps only 3 years of observations.
## replication_and_decay
Equity-premium predictors generally decay out-of-sample (GWZ). The VIX finding is contrarian: backwardation is a bad moment to sell.
## data_required
^VIX and ^VIX3M from Yahoo (free); BAA10Y on FRED (daily, start date UNVERIFIED); HYG/IEF as a credit proxy (2007+); breadth from a point-in-time constituent list.
## fit_to_this_desk
Poor fit. Long HY OAS history is no longer free. Breadth computed from current S&P members is biased upward because survivors had stronger trends. There are too few regime switches in 10 years to validate anything.
## implementation_sketch
Record only as shadows with pre-registered rules. Do not let any of these signals trigger de-risking; backwardation evidence argues against selling into it.
## pitfalls
Survivorship in breadth; data-vendor licensing changes; many signals means a large DSR N; contrarian signs.
## confidence
weak
--- [7]
## technique
Conditional leverage: lift beta modestly only when trend is up and volatility is low (margin or a 2x ETF sleeve such as QLD/SSO); decay of leveraged ETFs
## sources
Gayed & Bilello (2016), 'Leverage for the Long Run', Charles H. Dow Award, SSRN 2741701: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2741701; figures via the CXO summary https://www.cxoadvisory.com/volatility-effects/leveraging-the-u-s-stock-market-based-on-sma-rules/ because the primary PDF was not machine-readable. Avellaneda & Zhang (2010), 'Path-dependence of leveraged ETF returns', SIAM J. Financial Math 1:586-603, SSRN 1404708. Cheng & Madhavan (2009), J. Investment Management, SSRN 1539120. Hsieh, Chang, Chen (2025), arXiv 2504.20116: https://arxiv.org/abs/2504.20116
## reported_evidence
Gayed-Bilello, Oct 1928 to Oct 2015 (via CXO): buy-and-hold Sharpe 0.30, max drawdown -86%. Constant 2x: Sharpe 0.27, max drawdown -99%. SMA200 at 1x: Sharpe 0.60, max drawdown -50%. SMA200 rotation at 2x: Sharpe 0.51, max drawdown -78%. The S&P's annualised return was +14.1% above its SMA200 and -2.3% below. Assumptions: 1% annual cost of leverage, switching costs ignored, about 5 switches a year. Standard daily-rebalanced leveraged ETF math (Avellaneda-Zhang form): ln(V_T/V_0) ≈ L*ln(S_T/S_0) - ((L^2 - L)/2)*∫σ² dt - (L-1)*r*T - fee*T. Hsieh et al.: whether an LETF beats its target multiple depends on autocorrelation; trends help and mean reversion hurts (about 20 years of SPY/QQQ).
## replication_and_decay
CXO caveats: today's low leverage cost is applied to the whole history, and the 1928 start flatters SMA rules. I have not seen an independent out-of-sample test. My arithmetic at σ = 22% (QQQ-like), r = 4% and fee 0.95%: 2x beats 1x in expectation only if QQQ's arithmetic drift exceeds r + 1.5σ² + fee ≈ 12.2%/yr (about 9.8% geometric). The volatility drag alone is (L² - L)/2 * σ² ≈ 4.8%/yr at 2x and ≈ 14.5%/yr at 3x.
## data_required
QQQ/QLD/TQQQ and SPY/SSO daily from Yahoo; ^NDX from 1985 and the French market from 1926 for synthetic leveraged series; DTB3 for financing.
## fit_to_this_desk
This is the only overlay family with a mechanism to beat QQQ on total return in up-trending regimes, and it does so by adding risk. Alpaca supports Reg-T margin and leveraged ETFs. Futures are likely unavailable there (UNVERIFIED). Paper trading does not charge borrow or margin fees ('coming soon' per the Alpaca docs), so financing must be charged in the ledger. The book probably already has beta above 1 to QQQ; measure it before adding leverage.
## implementation_sketch
Pre-registered shadow. Target exposure = 1.25x the book (or a 25% QLD sleeve) only when the existing brake is risk-on (QQQ > 1.02 x SMA200) AND QQQ's 21-day realised volatility is below its trailing 252-day median. Otherwise 1.0x, falling to the brake's 0.5x when risk-off. Charge financing at DTB3 + 2% (assumption). Test first on synthetic ^NDX 1985-2026 and French 1926-2025 series, including the 1987 and 2020 gap stresses, then SPA against the unlevered incumbent, then a season of forward shadow for fill and financing fidelity.
## pitfalls
Gap risk: a -20% day (1987) is about -40% at 2x and -60% at 3x. The 2020 crash began while above the SMA200. Leverage magnifies idiosyncratic concentration in a high-beta AI book. Volatility drag; margin calls; financing cost regime (4-5% rates); parameter mining of the vol gate.
## confidence
moderate
--- [8]
## technique
Cash-yield accounting (credit idle cash at the T-bill rate in research and in the ledger)
## sources
Faber (2007/2013), where cash is 90-day T-bills. Alpaca paper trading docs: https://docs.alpaca.markets/docs/paper-trading. Desk code: backend/market/allocation_controls.py line 21 ('idle cash earns nothing'); backend/market/research_journal_replay.py:187 asserts cash_yield == 0.0; backend/market/forward_actions.py already accrues dividends.
## reported_evidence
Every historical trend or overlay study that looks good credits T-bill income while out of the market. The desk's research harness and replay manifest fix cash yield at 0. Alpaca's paper docs (verified): paper trading 'does NOT simulate dividends' and does not simulate market impact or slippage.
## replication_and_decay
This is accounting, not a signal, so it does not decay. It matters most when rates are 3-5%.
## data_required
FRED DTB3 (free, daily).
## fit_to_this_desk
Trivial to implement. It fairly re-scores the brake and any cash-holding policy. Part of the '+5 CAGR from deploying idle cash next session' proxy result is the zero-yield assumption, roughly cash share times T-bill yield. Live, a T-bill ETF sleeve (SGOV/BIL) in the paper account would show ex-dividend price drops without the distributions, so the desk's ledger, which accrues dividends, must remain the score of record.
## implementation_sketch
Add cash_yield = previous-day DTB3/252 under a new protocol version; never retrofit it into frozen results. Report both zero-yield and T-bill-credited figures for one season of transition. Live: optionally park idle cash in a T-bill ETF, with distributions accrued in forward_actions.
## pitfalls
Changing a frozen protocol in place; double-counting if the broker also pays interest (Alpaca live cash interest UNVERIFIED); the benchmarks are fully invested, so their comparison is unaffected.
## confidence
strong
--- [9]
## technique
Entry-point timing: decide on the 15:45 bar and fill in the same day's closing auction (market-on-close), instead of deciding at the close and filling at the next open
## sources
Lou, Polk, Skouras (2019), 'A tug of war: Overnight versus intraday expected returns', JFE 134(1):192-213: https://econpapers.repec.org/RePEc:eee:jfinec:v:134:y:2019:i:1:p:192-213. Berkman, Koch, Tuttle, Zhang (2012), 'Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open', JFQA 47(4): https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/paying-attention-overnight-returns-and-the-hidden-cost-of-buying-at-the-open/F9AAD159B512C651F09D5D52011D88E0. Cliff, Cooper, Gulen (2008), SSRN 1004081. Alpaca order docs: https://docs.alpaca.markets/docs/orders-at-alpaca. Gao, Han, Li, Zhou (2018), 'Market intraday momentum', JFE 129:394-414; a post-publication check found it 'much weaker': https://www.diva-portal.org/smash/get/diva2:1878991/FULLTEXT01.pdf
## reported_evidence
Lou, Polk and Skouras (abstract, verified), across 14 strategies: profits are 'earned entirely overnight (for reversal and a variety of momentum strategies)' or entirely intraday. Berkman et al. (abstract, verified): positive overnight returns are followed by intraday reversals, because the opening price is high relative to intraday prices. The effect is concentrated in stocks with recent retail attention that are hard to value, and the implicit cost of buying them near the open frequently exceeds the effective half-spread. Cliff-Cooper-Gulen (secondary summary): the US equity premium over 1993-2006 was earned overnight; for QQQ over 1999-2006, close-to-open was +23.7% against open-to-close -23.3%. Alpaca (verified): CLS orders are rejected if submitted between 3:50pm and 7:00pm ET, and OPG orders between 9:28am and 7:00pm ET.
## replication_and_decay
The overnight/intraday split is widely replicated (the individual replications were not fetched here). Intraday momentum weakened after publication. No evidence specific to this book yet.
## data_required
Yahoo daily OHLC (close-to-open and open-to-close legs); Alpaca IEX 15-minute bars since 2016 for the 15:30-15:45 snapshot; official closing prices.
## fit_to_this_desk
Strong fit, and this is the most useful role for the 15-minute data. The adopted rule decides at the close and fills at the next open. That skips the overnight leg where momentum profits accrue, and it pays the opening premium on retail-attention names (CRWV, IREN, NBIS, OKLO fit that profile). The earlier study compared the open with first-hour prints, not with the prior close, so this question is untested.
## implementation_sketch
(1) Decompose the incumbent's 2016-2026 simulated returns into close-to-open and open-to-close legs per position; this costs almost nothing. (2) If the edge sits overnight, build the variant: signal from the 15:45 IEX bar, submitted as CLS before 3:50, filled at the official close, same 20-session resets and 10/25bp costs. Report how often the 15:45 and 16:00 signals agree. (3) Judge on the 10-year history with DSR (N counted) and SPA against the incumbent. Use a forward season only to check that closing-auction fills match the ledger. Treat exits symmetrically (sell at the close, not the next open).
## pitfalls
The IEX-only last trade at 15:45 is noisy for thin names (IEX has a low single-digit share of consolidated volume; exact figure UNVERIFIED); closing-auction imbalances; look-ahead if the 16:00 close is used both for the signal and the fill; more overnight gap exposure.
## confidence
moderate
--- [10]
## technique
Rebalance timing luck and tranching the 20-session reset
## sources
Hoffstein, Faber, Braun (2020), 'Rebalance Timing Luck: The (Dumb) Luck of Smart Beta', SSRN 3673910: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3673910. Hoffstein, Sibears, Faber (2019), SSRN 3319045. Newfound GEM fragility (above).
## reported_evidence
In long-only factor indices, rebalance timing luck often exceeds 100bp annualised. A replication of S&P Enhanced Value showed calendar-year differences above 40% from the rebalance schedule alone. The remedy is overlapping (tranched) portfolios.
## replication_and_decay
This is a mechanical property of periodic rebalancing, so it does not decay.
## data_required
The existing panel.
## fit_to_this_desk
Direct fit. Each backtest of a 20-session-reset policy is one of 20 possible offsets, so a rule comparison can flip depending on the offset.
## implementation_sketch
Run the incumbent and every candidate at all 20 offsets and report the median and the range. Adopt only if the candidate wins at the median and in a pre-registered share of offsets (for example 15 of 20). Live, optionally run 4 tranches at offsets 0/5/10/15, each with 25% of capital: same expected return, lower outcome variance, and cleaner evaluation.
## pitfalls
Tranching does not raise expected return; minimum order sizes and fractional-share handling; each tranche's costs must be accounted separately.
## confidence
strong
--- [11]
## technique
Statistical power: how many sessions it takes to detect excess return over QQQ/SPY, and what a shadow season can show
## sources
Grinold & Kahn, Active Portfolio Management (2nd ed., 2000): t ≈ IR * sqrt(years) (textbook, not fetched). Numbers below are my own computations. Alpaca paper docs (above).
## reported_evidence
Formula: years needed = ((z_a + z_b) * TE / alpha)^2, and the standard error of annualised excess after S sessions = TE / sqrt(S/252). +5%/yr at 15% tracking error (IR 0.33): t ≥ 2 needs 36 years (9,072 sessions); 80% power at one-sided 5% needs 55.6 years (14,022 sessions); two-sided needs 70.6 years; the HLZ t ≥ 3 bar needs 81 years. +5% at 25% TE: 100 years for t ≥ 2. +10% at 15% TE: 9 years (2,268 sessions). +20% at 25% TE: 6.2 years (1,575 sessions). At 15% TE the standard error is ±30.7%/yr after 60 sessions, ±15% after 252, ±6.7% after 1,260 and ±4.7% after 2,520; at 30% TE these double. Sampling at 15 minutes instead of daily does not shrink them, because precision of the mean depends on calendar length. For a paired candidate-versus-incumbent test with difference volatility s_d: Δ = 2%, s_d = 3% needs 13.9 years; Δ = 3%, s_d = 3% needs 6.2 years; Δ = 5%, s_d = 3% needs 2.2 years (80% power, one-sided 5%).
## replication_and_decay
Standard statistics. Overlay benefits arrive in episodes (bear markets), so the effective sample is the number of episodes, about 2-3 per decade, not the number of sessions.
## data_required
Ledger daily returns for the strategy, the benchmarks and the incumbent.
## fit_to_this_desk
Directly applicable to the 'shadow for a season' gate. A season can detect only implementation defects or effects above about 60%/yr at 15% TE. Evidence about alpha has to come from long history with multiple-testing control. Forward shadows should confirm implementation fidelity and non-inferiority.
## implementation_sketch
Each shadow gate pre-registers the expected Δ, s_d taken from the backtest, the sessions needed, and a decision rule. Superiority claims use history plus DSR/SPA. A forward season must pass fill-fidelity bounds (ledger against broker, slippage series) and a non-inferiority margin (for example not worse than -X%/yr at 90% confidence). Use HAC or bootstrap standard errors.
## pitfalls
Treating a good season as proof; ignoring autocorrelation and fat tails; comparing against unmatched beta.
## confidence
strong
--- [12]
## technique
Probabilistic Sharpe ratio (PSR), minimum track record length (MinTRL) and deflated Sharpe ratio (DSR), applied to active returns against QQQ
## sources
Bailey & López de Prado (2012), 'The Sharpe Ratio Efficient Frontier', J. Risk 15(2):3-44: https://www.davidhbailey.com/dhbpapers/sharpe-frontier.pdf. Bailey & López de Prado (2014), 'The Deflated Sharpe Ratio', JPM 40(5): https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf (SSRN 2460551).
## reported_evidence
PSR(SR*) = Φ[(SR^ - SR*) * sqrt(T-1) / sqrt(1 - γ3*SR^ + ((γ4-1)/4)*SR^²)], using the per-period SR, skew γ3 and raw (not excess) kurtosis γ4. MinTRL = 1 + [1 - γ3*SR^ + ((γ4-1)/4)*SR^²] * (Z_a/(SR^ - SR*))². DSR is PSR with SR* = SR0 = sqrt(V[SR_n]) * ((1-γ)Φ^-1(1-1/N) + γΦ^-1(1-1/(N*e))), γ = 0.5772. The formulas are images in the paper; the code in its appendix confirms the expected-maximum term. I reproduced the paper's worked example numerically (annualised SR 2.5, T = 1,250, N = 100, V = 0.5, γ3 = -3, γ4 = 10): DSR = 0.900, and 0.9505 at N = 46, matching the paper. Desk-scale examples (10 years daily, trial-SR spread 0.3 annualised, skew -0.5, kurtosis 6): SR0 = 0.36 at N = 5, 0.47 at 10, 0.57 at 20, 0.68 at 50, 0.76 at 100, 0.83 at 200. A best-of-50 rule with SR 1.0 has DSR 0.84 and fails 0.95. MinTRL for SR > 0 at 95%: SR 0.5 needs 2,775 sessions (11 years); SR 1.0 needs 708 (2.8 years); SR 2.0 needs 186; SR 3.0 needs 87.
## replication_and_decay
Widely adopted. Its limit: DSR corrects for the number of trials and for non-normality, but not for universe hindsight.
## data_required
Daily net ledger returns and a registry of every variant tried, with its daily returns.
## fit_to_this_desk
Pure computation. For benchmark-relative claims, apply it to strategy minus QQQ (the IR in place of SR). N must include variants tried by earlier studies and other agents in the repo (the learned-model lines, entry studies and allocation variants), clustered into effective independent trials.
## implementation_sketch
Keep a trials registry (a JSONL of variant id, date, protocol and daily returns). Before any adoption, compute DSR on active returns with N_eff from correlation clustering, and require DSR ≥ 0.95 plus a positive SPA result. Report PSR/MinTRL for every shadow.
## pitfalls
Undercounting N; using excess kurtosis where the formula needs raw kurtosis; short-sample Sharpe estimates with hidden crash risk; the hindsight book is not deflatable.
## confidence
strong
--- [13]
## technique
Probability of backtest overfitting (CSCV), minimum backtest length (MinBTL) and combinatorial purged cross-validation (CPCV)
## sources
Bailey, Borwein, López de Prado, Zhu (2017), 'The Probability of Backtest Overfitting', J. Computational Finance, SSRN 2326253: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253. Bailey, Borwein, López de Prado, Zhu (2014), 'Pseudo-Mathematics and Financial Charlatanism', Notices of the AMS 61(5):458-471. Bailey, Ger, López de Prado, Sim, Wu, 'Statistical Overfitting and Backtest Performance': https://sdm.lbl.gov/oapapers/ssrn-id2507040-bailey.pdf. López de Prado (2018), Advances in Financial Machine Learning, ch. 7 and 12. Arian, Norouzi M., Seco (2024), Knowledge-Based Systems 305:112477: https://www.sciencedirect.com/science/article/abs/pii/S0950705124011110
## reported_evidence
Verified text: with only 5 years of daily data, if 45 or more independent variants are tried, the best one is likely to show an annualised SR of 1.0 or better by chance. MinBTL (years) ≈ (maxZ(N)/E[max SR])², which I computed as 2.5 years for N = 10, 3.6 for 20, 5.0 for 45, 6.4 for 100 and 10.6 for 1,000. On a 10-year history with zero skill, the expected best-of-N annualised SR is about 0.60 for N = 20, 0.80 for N = 100 and 1.03 for N = 1,000. CSCV splits the T x N performance matrix into S blocks and takes all C(S, S/2) in-sample/out-of-sample splits (S = 16 gives 12,870). PBO is the share of splits in which the in-sample winner ranks below the out-of-sample median (logit ≤ 0). CPCV with N groups and k test groups gives C(N, k) splits and φ = (k/N) * C(N, k) paths (N = 10, k = 2: 45 splits, 9 paths), with purging and an embargo. Arian et al. (synthetic): CPCV had lower PBO and better DSR than K-fold, purged K-fold and especially walk-forward.
## replication_and_decay
The methods are theory plus simulation. Arian et al. is synthetic, not market out-of-sample.
## data_required
Daily returns of every tried configuration.
## fit_to_this_desk
Cheap on the existing panel. The learned-model studies used chronological single-path splits; CSCV/CPCV plus PBO would put a number on how likely each 'winner' is an artefact.
## implementation_sketch
For every study that picks among configurations, log the full T x N matrix, run CSCV with S = 16 and report PBO. For learned models use CPCV (N = 10, k = 2) with an embargo of at least the label horizon (20 sessions). Adopt only if PBO < 0.2 and DSR ≥ 0.95 (thresholds to be pre-registered).
## pitfalls
CSCV assumes blocks are comparable; with 10 years, each block is about 7.5 months and regimes cluster. Every discarded variant must be kept in the matrix.
## confidence
strong
--- [14]
## technique
White's Reality Check, Hansen's SPA and Romano-Wolf StepM for choosing among many candidates against a benchmark
## sources
White (2000), 'A Reality Check for Data Snooping', Econometrica 68(5):1097-1126. Hansen (2005), 'A Test for Superior Predictive Ability', JBES 23(4):365-380: https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html. Sullivan, Timmermann, White (1999), JF 54(5):1647-1691: https://ideas.repec.org/a/bla/jfinan/v54y1999i5p1647-1691.html. Romano & Wolf (2005) StepM (not fetched). Python package arch (Sheppard), which provides bootstrap.SPA, RealityCheck, StepM, MCS and optimal_block_length: https://github.com/bashtage/arch
## reported_evidence
Sullivan-Timmermann-White (abstract verified): they expanded Brock-Lakonishok-LeBaron's 26 rules into a full universe and applied it to 100 years of DJIA data. After the Reality Check adjustment, profitability over the following 10-year out-of-sample period was low. The often-cited counts (about 7,846 rules, 1987-1996 out-of-sample) are UNVERIFIED here. Hansen: SPA is more powerful and less sensitive to poor or irrelevant alternatives, through studentisation and a sample-dependent null.
## replication_and_decay
Standard tools in the data-snooping literature. Technical-rule edges on the DJIA vanished out of sample.
## data_required
Daily net return series for all K candidates, the incumbent and the benchmarks.
## fit_to_this_desk
Easy fit. It answers the real question: is the best of what we tried better than the incumbent, or better than QQQ, after accounting for how many things we tried? Adding arch is a dependency decision that needs the operator's approval.
## implementation_sketch
Loss differential d_k,t = r_incumbent,t - r_k,t, net of cost. Run SPA with a stationary bootstrap, block length from optimal_block_length and B = 10,000. Require the consistent p-value < 0.05. Use StepM to name which candidates survive. Run separately against QQQ and SPY for reporting.
## pitfalls
Leaving discarded candidates out of K; one 10-year path cannot contain regimes it never saw; low power at IR < 0.5 (see the power finding).
## confidence
strong
--- [15]
## technique
Paired block bootstrap and robust tests of Sharpe-ratio differences
## sources
Politis & Romano (1994), 'The Stationary Bootstrap', JASA 89(428):1303-1313. Politis & White (2004), 'Automatic Block-Length Selection for the Dependent Bootstrap', Econometric Reviews 23(1):53-70: https://public.econ.duke.edu/~ap172/Politis_White_2004.pdf, with the Patton-Politis-White (2009) correction. Ledoit & Wolf (2008), 'Robust performance hypothesis testing with the Sharpe ratio', J. Empirical Finance 15(5):850-859: https://www.econ.uzh.ch/dam/jcr:ffffffff-935a-b0d6-0000-00007214c2bc/jef_2008pdf.pdf
## reported_evidence
Ledoit-Wolf: the Jobson-Korkie/Memmel test is invalid under heavy tails or time-series dependence. Instead, form a studentised time-series (block) bootstrap confidence interval for the Sharpe difference and reject if it excludes 0. The stationary bootstrap resamples blocks of random (geometric) length, which keeps the resampled series stationary.
## replication_and_decay
Standard.
## data_required
Aligned daily net returns of the strategy and its benchmarks.
## fit_to_this_desk
Direct fit for a confidence interval on CAGR, Sharpe and max-drawdown differences against QQQ/SPY over 2016-2026.
## implementation_sketch
Resample the strategy and QQQ/SPY with the same indices so their cross-correlation is kept, using a Politis-White block length. Report 5-95% intervals for the CAGR and Sharpe differences and the drawdown distribution. For trend overlays, prefer long independent histories, because a 200-day rule needs blocks far longer than 200 days.
## pitfalls
Resampling a bull-heavy decade reproduces its bias. Intervals will be wide (at TE 25-30%, the 10-year CAGR-difference interval is roughly ±8-10%/yr). Short blocks break trend-filter dynamics.
## confidence
strong
--- [16]
## technique
Multiple-testing thresholds and expected decay of backtested edges
## sources
Harvey, Liu, Zhu (2016), '...and the Cross-Section of Expected Returns', RFS 29(1):5-68, NBER w20592. Harvey & Liu (2015), 'Backtesting', JPM 42(1):13-28, https://people.duke.edu/~charvey/backtesting/. McLean & Pontiff (2016), 'Does Academic Research Destroy Stock Return Predictability?', JF 71(1):5-32: https://ideas.repec.org/a/bla/jfinan/v71y2016i1p5-32.html. Goyal-Welch-Zafirov (2024), above.
## reported_evidence
HLZ: 316 published factors; a new factor should clear t > 3.0. Harvey-Liu: the haircut for multiple testing is nonlinear (marginal Sharpe ratios are cut heavily, high ones mildly), so a flat 50% rule of thumb is wrong. McLean-Pontiff, 97 predictors: returns are 26% lower out-of-sample and 58% lower after publication.
## replication_and_decay
Established consensus.
## data_required
None beyond the trials registry.
## fit_to_this_desk
It calibrates expectations: plan for a 25-60% shrinkage of any backtested edge. 2024-2026 has already been touched, so treat it as in-sample.
## implementation_sketch
Use t ≥ 3 (or the Harvey-Liu haircut) as the adoption bar for any new signal. Budget for decay when sizing the expected benefit in each protocol.
## pitfalls
Stating a t = 2 result as a discovery; not counting LLM-agent explorations as trials.
## confidence
strong
--- [17]
## technique
Benchmark design: an equal-weight baseline of the same universe, beta-matched QQQ, and point-in-time membership
## sources
fja05680/sp500, point-in-time S&P 500 membership since 1996: https://github.com/fja05680/sp500. Ken French Data Library for market and RF from 1926 (not fetched this session). Brown, Goetzmann, Ibbotson, Ross (1992), 'Survivorship Bias in Performance Studies', RFS (UNVERIFIED, not fetched).
## reported_evidence
Desk fact: equal-weighting the hindsight-picked book returns about 38-41% CAGR since 2016 and beats every selection rule tested. So the book's excess over QQQ comes from choosing the universe in 2026 plus beta, not from skill. Selection or weighting rules have so far added negative value against the equal-weight baseline of the same universe.
## replication_and_decay
Survivorship and look-ahead in the universe are standard, well-documented biases.
## data_required
Point-in-time membership; the book's daily returns; the QQQ return and the T-bill rate for a beta-matched benchmark.
## fit_to_this_desk
Directly applicable. The delisted names' prices are often missing from Yahoo, so bias remains even with point-in-time membership, but it can be counted.
## implementation_sketch
Report three numbers for every candidate. (1) Against the equal-weight baseline of the same universe: selection and weighting skill. (2) Against beta-matched QQQ (β^ * QQQ + (1 - β^) * T-bill, with β^ estimated as-of from trailing 252 sessions): alpha separated from leverage. (3) Against the funded SPY/QQQ accounts: the user's goal, which is not evidence of skill. Rebuild the S&P learning cross-section on point-in-time membership and count missing delisted names per date.
## pitfalls
Calling excess over QQQ 'alpha' when beta is above 1 in a bull market; comparing selection rules to QQQ rather than to the equal-weight baseline; survivorship in breadth and cross-sectional features.
## confidence
strong
## ranked_recommendations
Ranked by expected net improvement over SPY/QQQ per unit of implementation effort and overfitting risk:

1. Build the evaluation stack before touching strategy (days of work, no overfitting risk).
   - A trials registry.
   - DSR/PSR on active returns against QQQ.
   - Hansen SPA/StepM across every candidate, using a stationary bootstrap.
   - Reporting of all 20 reset offsets.
   - Three benchmarks for every candidate: the equal-weight baseline of the same universe, beta-matched QQQ, and the funded SPY/QQQ accounts.
   Why first: the power numbers show a shadow season cannot detect realistic alpha. At 15% tracking error, +5%/yr needs 36 years (9,072 sessions) to reach t = 2; after 60 sessions the standard error is about ±31%/yr. Without this stack every later idea risks false adoption. It adds no return by itself; it protects the gains below.

2. Credit idle cash at the T-bill rate (FRED DTB3) as a new protocol version.
   - It is mechanical and certain, and the gain grows with the cash share.
   - At 3-5% T-bill yields and 15-30% average cash, it is worth roughly +0.5 to +1.5%/yr on the scored book. This is an estimate.
   - It also re-scores the trend brake and the 'deploy idle cash' result fairly.
   - Live: keep the ledger as the score of record. Alpaca paper does not simulate dividends, so a T-bill ETF held in paper would be mis-scored.

3. Test the entry point: the same-day close against the next open. This is the right use of the 15-minute data.
   - First, split the incumbent's history into close-to-open and open-to-close legs. That uses Yahoo OHLC only and costs almost nothing.
   - If the edge sits overnight, as Lou-Polk-Skouras found for momentum, test deciding on the 15:45 IEX bar with a CLS order submitted before 3:50pm ET, against deciding at the close and filling at the next open.
   - Berkman et al. show that buying high-attention retail names at the open costs more than the half-spread; this book is full of such names.
   - The upside is capturing the entry-night return and avoiding the opening premium. The overfitting risk is low: one pre-registered variant, judged on 10 years with DSR N counted, then a forward season for fill fidelity only.

4. Run the 20-session reset as tranches (for example 4 offsets at 25% of capital each) and evaluate every rule across all offsets.
   - Expected return does not change.
   - Timing-luck variance falls; the literature reports it often exceeds 100bp/yr.
   - Rule comparisons stop hinging on a lucky reset date.

5. Conditional beta lift: 1.25x the book, or a 25% QLD/SSO sleeve, only when the existing brake is risk-on and QQQ's 21-day realised volatility is below its trailing median.
   - This is the only overlay family with a mechanism to beat QQQ on total return, and it works by taking more risk.
   - The evidence is in-sample (Gayed-Bilello: 2x rotation Sharpe 0.51 against 0.30 for buy-and-hold, max drawdown -78%, switching costs ignored).
   - Leveraged-ETF math sets a hurdle: at 22% volatility and 4% rates, 2x only helps if QQQ's arithmetic drift exceeds about 12%/yr.
   - Test first on independent histories (French market 1926+, ^NDX 1985+) with explicit financing and 1987/2020 gap stresses, then SPA against the unlevered incumbent, then shadow.
   - Risk is high and confidence moderate to low. Adopt only if it passes and the operator accepts the larger drawdowns.

6. Keep the QQQ trend brake as insurance, and do not retune it.
   - Re-score it with cash yield on long independent histories.
   - Present it as a cost of about 1-2 CAGR per roughly 10 points of drawdown avoided, not as a return enhancer.

Not ranked, because the evidence says they will not improve total return here: unlevered vol targeting; index time-series momentum and dual momentum; CPPI and stop-loss; VIX, credit or breadth regime switches; and any standalone 15-minute alpha.

Candid bottom line: overlays that reduce exposure do not beat QQQ on total return in bull-dominated samples. Only more beta can, and it brings more risk. The book's historical excess over QQQ comes from hindsight universe selection plus beta. The realistic improvements are:
- accounting correctly (cash yield, beta-matched benchmarks);
- executing better (closing-auction entries, tranching);
- possibly a small, gated beta lift;
- and above all not adopting false positives.
## what_not_to_do
- Do not treat a season-long shadow as evidence of alpha.
  - At 15% tracking error, the standard error of annualised excess is about ±31% after 60 sessions and ±15% after 252.
  - +5%/yr needs about 36 years for t = 2, and about 56 years for 80% power.
  - Use forward shadows for fill fidelity and non-inferiority only.
- Do not adopt unlevered vol targeting or the vol / vol_trend allocation.
  - Moreira and Muir's own no-leverage version earns 5.61% excess against the market's about 7.80%; even a 1.5x cap earns 7.18%.
  - Cederburg et al. find no systematic real-time gain across 103 strategies (53 wins against 50).
- Do not tune the brake's lookback or its 0.97/1.02 band on 2016-2026. That window holds only about 3 relevant episodes, and it is already touched.
- Do not re-derive trend or momentum parameters as single optimised values. The GEM fragility study showed a 9-month and a 10-month lookback ending at 43% and 146% cumulative. Use ensembles, or leave the parameters frozen.
- Do not use VIX backwardation as a sell trigger; the evidence says it is contrarian-bullish.
- Do not build breadth from current S&P members; survivors bias it upward.
- Do not rely on FRED's ICE BofA HY OAS for backtests; since April 2026 FRED keeps only 3 years of it.
- Do not add CPPI, stop-loss floors or dual momentum rotation into bonds or international equities.
  - Insurance lowers average return (Annaert et al.).
  - The GEM-style rotation reportedly lagged SPY after its publication (UNVERIFIED).
- Do not hold 2x or 3x leveraged ETFs unconditionally.
  - Volatility drag is about (L² - L)/2 * σ², i.e. about 4.8%/yr at 2x and about 14.5%/yr at 3x at 22% volatility, before financing and fees.
  - A 1987-style -20% day is about -60% at 3x.
- Do not build a standalone 15-minute intraday alpha on IEX-only bars at retail costs.
  - One round trip a day at 10bp costs about 25%/yr; at 25bp it costs about 63%/yr.
  - Alpaca paper fills at the NBBO with no slippage or impact, so paper results overstate.
  - IEX's share of consolidated volume is low, so bars are sparse for thin names.
  - Put the 15-minute data to work on entry timing (15:45 decision, market-on-close fill) and on measuring execution quality.
- Do not score from the Alpaca paper broker's P&L.
  - Paper trading simulates no dividends and no slippage.
  - Missing SPY dividends flatter a low-yield book against SPY. Keep the ledger, which accrues dividends, as the score of record.
- Do not keep simulating cash at zero yield while comparing cash-holding overlays; it penalises every overlay that holds cash.
- Do not count trials from only the current study. DSR's N and SPA's candidate set must include every variant tried across the repo's studies and agents, including discarded ones.
- Do not compare selection or weighting rules to QQQ as evidence of skill.
  - Compare them to the equal-weight baseline of the same hindsight universe and to beta-matched QQQ.
  - Excess over QQQ in a 2026-chosen AI book is mostly hindsight plus beta.
- Do not rely on single-path walk-forward for model selection; use CPCV/CSCV and report PBO.
- Do not bootstrap trend-filter benefits with short blocks; test them on independent long histories (French market 1926+, ^NDX 1985+) instead.
- Do not retrofit cash yield, fill timing or tranching into frozen protocols; each goes in as a new protocol version with its gate written before its first session.