## topic
Selection and portfolio construction: which stock-selection signals still work out of sample, after publication and after costs, and which portfolio-construction ("balancer") methods can beat SPY and QQQ for a long-only book of about 100 to 500 US names that uses only free data
## findings
--- [0]
## technique
Background: how much published anomaly returns shrink after publication, after costs and after 2005 (the prior for everything below)
## sources
McLean & Pontiff (2016) 'Does Academic Research Destroy Stock Return Predictability?' JF 71(1):5-32 https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 ; Chen & Velikov (2023) 'Zeroing In on the Expected Returns of Anomalies' JFQA 58(3):968-1004 https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/zeroing-in-on-the-expected-returns-of-anomalies/945133D5A3ECEEAF466AEE91551FD225 ; Chen & Welch (Jul 2026) 'What Useful Alphas?' arXiv:2607.06502 https://arxiv.org/abs/2607.06502 ; Green, Hand & Zhang (2017) RFS 30(12):4389 https://academic.oup.com/rfs/article-abstract/30/12/4389/3091648 ; Hou, Xue & Zhang (2020) 'Replicating Anomalies' RFS 33(5):2019 https://www.nber.org/papers/w23394 ; Jensen, Kelly & Pedersen (2023) 'Is There a Replication Crisis in Finance?' JF 78(5):2465 https://onlinelibrary.wiley.com/doi/full/10.1111/jofi.13249 ; Harvey, Liu & Zhu (2016) RFS 29(1):5 https://www.nber.org/papers/w20592
## reported_evidence
McLean-Pontiff: across 97 predictors, portfolio returns are 26% lower out of sample and 58% lower after publication. Chen-Velikov (published JFQA version) covers 204 anomalies after effective spreads, post-publication decay and the post-2000s trading era. The average anomaly nets 4 bp/month, the strongest about 10 bp after correcting for data mining, and combinations about 20 bp. The earlier FEDS working-paper version said 120 anomalies and 8 bp; I report the published figures. Chen-Welch (2026), which I read in full text: after 2005, in the top 90% of market cap (about 3,000 names), the median long-short anomaly return is about 7 bp/month. Profitability is the only category with a healthy median, about 25 bp/month. Momentum, value and intangibles-based anomalies are 'essentially dead', and the only momentum survivors are the seasonal and off-season variants at about 50 bp/month. The key result for a long-only book is that long-leg-minus-market t-stats are essentially standard normal, so 'any long leg outperformance is entirely due to luck'. After empirical-Bayes shrinkage every long-leg alpha estimate is zero. Green-Hand-Zhang: 12 of 94 characteristics are independent in non-microcaps over 1980-2014, only 2 since 2003, and non-microcap hedge returns are insignificant since 2003. Hou-Xue-Zhang: with value weights and NYSE breakpoints, 65% of 452 anomalies fail |t|>1.96, 82% fail at t>2.78, and 96% of the trading-frictions category fails. Jensen-Kelly-Pedersen: most factors do replicate in a Bayesian sense across 93 countries. Those are gross, capped value-weighted long-short numbers, not net long-only ones.
## replication_and_decay
The pessimistic papers (Chen-Velikov, Chen-Welch, Green-Hand-Zhang, Hou-Xue-Zhang) and the optimistic one (Jensen-Kelly-Pedersen) disagree mainly about whether costs are included, whether microcaps are included, and whether the question is 'is it real' or 'is it tradeable post-2005 in large caps'. For this desk the tradeable, large-cap, long-only question is the one that matters.
## data_required
None; this is the prior.
## fit_to_this_desk
The desk's own findings match this literature: learned models failed, the valuation increment has a combined t of 0.05, and equal-weighting the whole book beats every selection rule. Any within-book selection signal should be expected to add roughly 0 to 2 CAGR points gross, with wide noise, over roughly 94 names. The measured desk-score IC of about 0.046 (t 3.2 on 147 non-overlapping windows, 2015-2026, hindsight universe) is about what a real but weak signal looks like.
## implementation_sketch
Adopt this as the written prior in every shadow protocol. A candidate's gate should require beating equal weight over the same eligible set on untouched sessions, net of 25 bp, not beating the incumbent rule. Also report the long-leg-minus-SPY and long-leg-minus-QQQ t-stat, with a t>3 hurdle in the Harvey-Liu-Zhu sense for anything chosen from a search.
## pitfalls
Hindsight universe (the 2026-picked AI book) and a survivor-only S&P 500 cross-section both inflate every selection rule, especially momentum and breakout rules, because the delisted and dropped losers are missing. The desk measures book survivorship at about 19 points a year.
## confidence
strong
--- [1]
## technique
Cross-sectional 12-1 price momentum (buy past 12-month winners, skipping the latest month)
## sources
Jegadeesh & Titman (1993) JF; Jegadeesh & Titman (2001) JF 56:699 https://www.nber.org/papers/w7159 ; Asness, Frazzini, Israel & Moskowitz (2014) 'Fact, Fiction and Momentum Investing' JPM https://www.aqr.com/Insights/Research/Journal-Article/Fact-Fiction-and-Momentum-Investing ; Israel & Moskowitz (2013) JFE 108:275 https://www.aqr.com/Insights/Research/Journal-Article/The-Role-of-Shorting-Firm-Size-and-Time-on-Market-Anomalies ; Frazzini, Israel & Moskowitz 'Trading Costs of Asset Pricing Anomalies' https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498 ; Daniel & Moskowitz (2016) 'Momentum Crashes' JFE 122:221 https://www.nber.org/papers/w20439 ; Barroso & Santa-Clara (2015) JFE 116:111 ; Novy-Marx (2012) JFE and Goyal & Wahal (2015) JFQA 'Is Momentum an Echo?' ; Chen & Welch (2026) arXiv:2607.06502
## reported_evidence
Jegadeesh-Titman 2001: profits continued through the 1990s, and reversal appears 4-5 years later. The 'about 1%/month' figure for 1993 is from memory (UNVERIFIED from the abstract); Chen-Welch cite 1.0-1.5%/month for the full universe. Israel-Moskowitz: long positions supply half of momentum profits, with no reliable relation to size, over 86 years of US data. Asness et al. (AQR, a practitioner with an interest): using about $1tn of live trades from 1998-2013, momentum 'easily survives' costs. Frazzini-Israel-Moskowitz: real costs are under a tenth of earlier estimates, and value and momentum scale better than reversal. Daniel-Moskowitz: crashes cluster in panic states after market falls, and a dynamic mean/variance-scaled version roughly doubles alpha and Sharpe. Barroso-Santa-Clara: scaling by 6-month realised volatility lifts long-short Sharpe from 0.53 to 0.97. Novy-Marx's 'echo' (12-7 beats 6-2) is absent in 37 non-US countries (Goyal-Wahal).
## replication_and_decay
Momentum replicates across centuries, countries and asset classes. However, Chen-Welch (2026) find plain momentum 'essentially dead' after 2005 in the top-3000 universe, and only seasonal variants survive. Crash risk remains (2009, and a smaller one in 2020). All the favourable cost evidence is for institutional long-short books, not a 94-name retail long-only book.
## data_required
Yahoo daily adjusted closes, 252 sessions. That is enough.
## fit_to_this_desk
Feasible. The desk's 'technical'/'rotation' analysts and rel_mkt/rel_theme features already overlap heavily with momentum. Long-only, the long half is the part that exists (Israel-Moskowitz). Rebalanced every 20 sessions it runs at very high turnover, so a buffer is needed. Crash risk hits high-beta AI names hardest.
## implementation_sketch
A single score: 12-1 total return, cross-sectionally ranked within the eligible set on the S&P 500 learning cross-section plus the book. Enter the top k, hold until the name falls out of the top 2k (a buy/hold buffer). Compare against equal weight on the same eligible set. Optional crash guard: halve momentum tilts when the market's trailing 24-month return is negative and 1-month volatility is high (the Daniel-Moskowitz panic state). This should be one pre-registered variant, not a tuned one.
## pitfalls
Survivor-only S&P 500 membership flatters momentum. Overlapping 20-session labels overstate t. Momentum on a theme book mostly re-bets on the theme's beta. Crash drawdowns coincide with QQQ rebounds, so relative underperformance against QQQ is severe exactly when the market recovers.
## confidence
moderate
--- [2]
## technique
Residual (idiosyncratic) momentum: rank on 12-1 residual returns after removing factor or market exposure, scaled by residual volatility
## sources
Blitz, Huij & Martens (2011) 'Residual Momentum' J. Empirical Finance 18(3):506-521 https://www.sciencedirect.com/science/article/abs/pii/S0927539811000041 ; Blitz, Hanauer & Vidojevic (2020) 'The idiosyncratic momentum anomaly' IREF 69:932 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2947044 ; Huij & Lansdorp (2017) 'Residual Momentum and Reversal Strategies Revisited' https://www.ssrn.com/abstract=2929306 (full text read)
## reported_evidence
Blitz-Huij-Martens: risk-adjusted profits about twice those of total-return momentum, more consistent over time, and not explained by the standard momentum explanations. In Huij-Lansdorp's FactSet US developed universe, 1986-2008: conventional momentum 16.1%/yr at 21.6% volatility (return-to-risk 0.74), residual momentum 13.1%/yr at 10.3% volatility (1.28). For comparison, the original CRSP study reported 10.3% at 22.7% volatility and 11.2% at 12.5%. Out of sample, 2009-2015, the volatility reduction held across all regions. Residual momentum beat conventional by 25-40 points in 2009, but conventional generally beat residual in the trending 2010-2015 markets. Blitz-Hanauer-Vidojevic: robust in developed and emerging markets, and survives controls for recent factors.
## replication_and_decay
The benefit replicates out of sample and internationally, but it is a RISK reduction (return-to-risk), not a higher raw return. All authors are Robeco-affiliated, so there is a practitioner interest. Chen-Welch's post-2005 null for momentum in large caps also applies here. I found no independent post-2015 US large-cap net-of-cost long-only study (UNVERIFIED either way).
## data_required
Daily returns plus factor returns. Ken French's daily factors are free and public. Alternatively, SPY/QQQ/IWM/sector-ETF returns from Yahoo can serve as factor proxies. A 36-month regression window is standard.
## fit_to_this_desk
Feasible with free data. However, by construction it strips market, theme and style beta from the ranking. The goal here is to beat QQQ in a bull AI regime, and in trending markets conventional momentum beat residual (Huij-Lansdorp, 2010-2015). Expect a better Sharpe and shallower drawdowns, and possibly lower CAGR, than total-return momentum.
## implementation_sketch
For each name, regress daily excess returns on SPY, QQQ and the theme basket over the prior 36 months, then take the sum of residuals from month -12 to -2 divided by residual standard deviation. Use it as a tie-break or veto inside A-graded names, not as the primary rank. Shadow it against the same eligible set with total-return momentum and equal weight.
## pitfalls
Short histories for recent IPOs (CRWV, NBIS) make the betas unstable, so require at least 24 months or exclude. The choice of factor model barely matters, per the literature, so do not search over factor sets.
## confidence
moderate
--- [3]
## technique
52-week-high momentum (nearness of price to its 52-week high)
## sources
George & Hwang (2004) 'The 52-Week High and Momentum Investing' JF 59:2145 https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.2004.00695.x ; Barroso & Wang (2021, WP) 'What explains price momentum and 52-week high momentum when they really work?' https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/576995/Haoxu-Wang-paper_NZFM.pdf
## reported_evidence
George-Hwang (1963-2001, equal-weighted portfolios): nearness to the 52-week high dominates and improves on past-return momentum, and its returns do not reverse in the long run. Barroso-Wang, as reported in secondary citation (not verified from the PDF, so partly UNVERIFIED), find the effect limited to small stocks and explained by price momentum. A secondary claim that 52-week-high returns were significantly negative over 2001-2014 is UNVERIFIED because I could not locate the primary table.
## replication_and_decay
Mixed. The original tests are equal-weighted, which overweights microcaps. Post-2005 large-cap evidence folds into Chen-Welch's 'momentum is dead' result.
## data_required
Yahoo daily highs and closes.
## fit_to_this_desk
Feasible but redundant. The desk's 20-day Bollinger breakout entry (ENTRY_BAND_Z=1.10 in backend/agents/trading/desk/paper.py) is already an anchoring and breakout rule of the same family.
## implementation_sketch
Do not add it as a separate engine. At most, report the 52-week-high ratio as a diagnostic next to the band trigger.
## pitfalls
Anchoring signals fire most on names that have just gapped. Those are the discrete, attention-grabbing moves that the frog-in-the-pan and MAX literatures associate with weaker continuation.
## confidence
weak
--- [4]
## technique
Industry, theme and factor momentum
## sources
Moskowitz & Grinblatt (1999) 'Do Industries Explain Momentum?' JF 54:1249 https://www.aqr.com/Insights/Research/Journal-Article/Do-Industries-Explain-Momentum ; Grundy & Martin (2001) RFS 14:29 ; Ehsani & Linnainmaa (2022) 'Factor Momentum and the Momentum Factor' JF 77:1877 https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13131
## reported_evidence
Moskowitz-Grinblatt: industry momentum explains much of individual-stock momentum. Grundy-Martin: industry momentum is not robust to a one-month skip between formation and holding, and loses significance with the skip. Ehsani-Linnainmaa: the average factor earns 6 bp/month after a losing year and 51 bp/month after a winning year, and momentum in high-eigenvalue principal-component factors subsumes most forms of individual-stock momentum.
## replication_and_decay
Industry momentum depends on the most recent month, which puts it close to short-horizon continuation with high turnover. Factor momentum replicates, but it is a timing overlay on long-short factors, not a long-only selection rule.
## data_required
Theme or GICS labels (the desk has theme baskets) plus daily returns.
## fit_to_this_desk
Partly already present: the rel_theme features, theme_cap=0.40 and the rotation analyst at half a vote. For a single-theme AI book, 'theme momentum' is mostly the book's beta to AI. Across the S&P 500 learning cross-section, sector momentum is feasible but turnover-heavy.
## implementation_sketch
If tested, use it only as a slow tilt: rank themes on 6-12 month return with a skip month (to respect Grundy-Martin), and move theme caps by at most one step per reset. Do not add a monthly sector-rotation engine.
## pitfalls
Without the skip month it is partly bid-ask bounce and reversal carryover. With 5-10 themes, the breadth is tiny.
## confidence
weak
--- [5]
## technique
Frog-in-the-pan: an information-discreteness filter on momentum
## sources
Da, Gurun & Warachka (2014) 'Frog in the Pan: Continuous Information and Momentum' RFS 27(7):2171-2218 https://academicweb.nd.edu/~zda/Frog.pdf (full text read)
## reported_evidence
Definition: ID = sgn(PRET) x (%neg days - %pos days) over the 12-1 formation window. Low ID means continuous information (many small same-sign days). Momentum falls monotonically from 5.94% for continuous-information stocks to -2.07% for discrete-information stocks with similar formation returns (from the abstract). Media coverage coincides with discrete information and weakens continuation. Sample: CRSP, ending 2007.
## replication_and_decay
I found no independent post-2007 US large-cap net-of-cost replication (UNVERIFIED). Chen-Welch's general post-2005 momentum null probably applies.
## data_required
Yahoo daily returns only.
## fit_to_this_desk
Cheap and feasible. It also bears directly on the desk's upper-tail band breakout: a 2.2-sigma 20-day breakout is by construction a discrete, attention-grabbing move. The FIP evidence (and MAX, below) predicts weaker continuation for exactly those entries.
## implementation_sketch
One pre-registered shadow: among A-graded names that trigger the band, enter only when 12-1 ID is at or below the cross-sectional median (continuous), or scale the entry size by ID tercile. Judge it on untouched sessions against the incumbent band entry. Report the hit rate and the next 20-session return by ID tercile from existing records first, as a descriptive check before any shadow.
## pitfalls
The effect was documented on long-short deciles across all caps. Inside 94 correlated names, the ID dispersion may be too small to matter.
## confidence
weak
--- [6]
## technique
Earnings momentum: post-earnings-announcement drift, standardized unexpected earnings (SUE), and earnings-release tone
## sources
Martineau (2022) 'Rest in Peace Post-Earnings Announcement Drift' Critical Finance Review 11(3-4):613-646 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3111607 ; Wu, Akin, Martineau, Gregoire & Veneris (2025) arXiv:2509.24254 https://arxiv.org/abs/2509.24254 ; Yu, Liu, Zhang & He (Jun 2026) 'Fast Numbers, Slow Language' arXiv:2606.29734 https://arxiv.org/abs/2606.29734 ; Chen et al. (Sep 2026) 'Does Training on Future Data Pay? Look-Ahead Bias in Forecasting with Pretrained Models' arXiv:2609.20554 https://arxiv.org/abs/2609.20554
## reported_evidence
Martineau: prices now fully reflect earnings surprises on the announcement date. For large stocks the drift has been non-existent since 2006, and it has only recently disappeared for microcaps. Wu et al. (138,000 press releases, 2005-2023): press-release text is as informative as the surprise for announcement-day returns, but 'stock prices fully reflect the content of press releases at market open'. Yu et al. (S&P 1500, 2022-2025): the quantitative surprise is 'largely eliminated by the next market open', while conference-call transcript sentiment peaks on the next trading day. That paper does not state costs or out-of-sample design. Chen et al. 2026: pretrained models with post-origin data vintages change point-in-time forecasts (and on average reduced accuracy), so historical LLM scores violate the information set.
## replication_and_decay
This is a textbook case of decay after publication and technology change (Chen-Velikov's 'modern era'). What remains is intraday or next-day and requires call transcripts, which are paid or not in the free data set.
## data_required
EDGAR 8-K press releases (free) and a local LLM (which the desk has). SUE needs consensus estimates (I/B/E/S, paid). A seasonal random-walk SUE can be computed from EDGAR XBRL.
## fit_to_this_desk
Feasible, but the desk decides at the close and fills at the next open, which is after the point where the release is priced. The release-tone vote (A+ requires a bullish release) is therefore more plausibly worth something as a veto against buying into bad news than as a drift signal. The desk's own note (IREN, January 2026: 'a bullish release and a strong tape over bearish filings was the losing trade') is consistent with this.
## implementation_sketch
Measure the tone vote's marginal contribution to 20-session forward returns after the first open, net of the open gap, on non-overlapping windows. If it is zero, keep it only as a downgrade veto. Record the LLM version and prompt version per score, as the roadmap already requires, and label all pre-model-cutoff tone backtests as leakage-exposed.
## pitfalls
The local LLM was trained on text that postdates most backtest dates, so historical tone is not point-in-time. Release timing (before the open or after the close) decides whether a close-decision fill at the next open can ever capture anything.
## confidence
strong
--- [7]
## technique
Analyst forecast revisions and recommendation changes
## sources
Standard literature (for example Chan, Jegadeesh & Lakonishok 1996 JF on earnings momentum). Not re-verified here, because the data requirement alone rules it out.
## reported_evidence
UNVERIFIED in this pass. Historically revisions predicted returns, and Da-Gurun-Warachka note that an ID built from analyst revisions gives results similar to the price-based one.
## replication_and_decay
Likely subject to the same post-2005 large-cap decay (Chen-Welch).
## data_required
I/B/E/S or a similar consensus feed (paid).
## fit_to_this_desk
Not feasible under the desk's rule of free data only.
## implementation_sketch
None. If a proxy is wanted, the frog-in-the-pan ID from prices is the free substitute the FIP paper itself validates.
## pitfalls
Scraped free consensus data has no reliable point-in-time history.
## confidence
weak
--- [8]
## technique
Quality and profitability (gross profits over assets, cash-based operating profitability)
## sources
Novy-Marx (2013) 'The Other Side of Value: The Gross Profitability Premium' JFE 108:1-28 https://www.nber.org/papers/w15940 ; Chen & Welch (2026) arXiv:2607.06502 (full text read)
## reported_evidence
Novy-Marx: gross profits over assets has about the same predictive power as book-to-market, and profitable firms earn higher returns despite higher market caps. Controlling for profitability sharply improves value strategies, especially among the largest stocks. The GP long-short numbers from the paper are not re-verified (UNVERIFIED). Chen-Welch, post-2005, top-3000 universe: the best survivors are cash-based operating profitability, R&D-adjusted operating profitability and gross profitability, at about 59-66 bp/month raw for the best. The profitability category averages about 25 bp/month long-short. After selection-bias shrinkage the best earns about 6 bp/month, 'even this required shorting', and 'the long-only return was at most zero net of selection bias'.
## replication_and_decay
This is the most robust category post-2005, but it is a long-short, short-leg story. There is no evidence of long-leg outperformance against the market.
## data_required
EDGAR XBRL (Revenues, CostOfRevenue or GrossProfit, Assets, operating cash flow), as-of filing date. The desk has fundamentals_asof.
## fit_to_this_desk
Feasible on the S&P 500 learning cross-section. It conflicts with the AI book, where several high-flyers (CRWV, NBIS, OKLO, IREN) have negative or thin profitability, so a profitability filter would have excluded much of the hindsight book's return. Useful as a junk veto (exclude the bottom decile of profitability among S&P names) rather than as a return engine.
## implementation_sketch
Cash-based operating profitability from as-of XBRL, used as a veto on the bottom decile within the S&P cross-section only. Shadow it against the no-veto rule. Do not apply it to the book's pre-profit names without a separate, pre-declared rule.
## pitfalls
XBRL tag inconsistencies (the desk just fixed fiscal-interval and unit issues). Filing-date lag must be respected. Financials need a separate definition.
## confidence
moderate
--- [9]
## technique
Accruals (Sloan)
## sources
Green, Hand & Soliman (2011) 'Going, Going, Gone? The Apparent Demise of the Accruals Anomaly' Management Science 57(5):797-816 https://pubsonline.informs.org/doi/abs/10.1287/mnsc.1110.1320
## reported_evidence
Hedge returns to the accruals anomaly have decayed in US markets to the point where they are no longer reliably positive. The authors attribute this partly to hedge-fund capital exploiting it.
## replication_and_decay
Dead in the US. Chen-Welch show the intangibles and accounting categories also dead post-2005 in large caps.
## data_required
EDGAR balance sheet and cash flow.
## fit_to_this_desk
Feasible but not worth building.
## implementation_sketch
None.
## pitfalls
Not applicable.
## confidence
strong
--- [10]
## technique
Short-term reversal, including intraday or 15-minute reversal and 'HFT-style' cross-sectional rebalancing
## sources
Avramov, Chordia & Goyal (2006) JF 61(5) https://papers.ssrn.com/sol3/papers.cfm?abstract_id=555968 ; de Groot, Huij & Zhou (2012) J. Banking & Finance 36(2) https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1963131 ; Frazzini, Israel & Moskowitz (Trading Costs) https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2294498 ; Huij & Lansdorp (2017) https://www.ssrn.com/abstract=2929306 ; Heston, Korajczyk & Sadka (2010) 'Intraday Patterns in the Cross-section of Stock Returns' JF 65(4):1369 https://arxiv.org/abs/1005.3535
## reported_evidence
Avramov-Chordia-Goyal: the largest reversals occur in illiquid, high-turnover stocks, and contrarian profits are smaller than likely transaction costs. De Groot-Huij-Zhou: restricting to large caps and reducing turnover gives 30-50 bp per week net, using institutional cost estimates. Frazzini-Israel-Moskowitz: reversal is the style most constrained by trading costs. Huij-Lansdorp: conventional reversal 4.4%/yr at 19.9% volatility against residual reversal 11.1% at 9.4% volatility (US, 1986-2008, gross). Heston-Korajczyk-Sadka: half-hour returns continue at exact daily multiples for at least 40 days. Reversals under one hour reflect liquidity imbalance and bid-ask bounce, and the authors frame the pattern as useful for timing trades to cut execution cost.
## replication_and_decay
Hou-Xue-Zhang: frictions-type anomalies mostly fail in value-weighted tests. The net-positive large-cap result (de Groot et al.) comes from Robeco authors using institutional costs on pre-2010 data.
## data_required
For daily reversal, Yahoo daily. For intraday, Alpaca IEX 15-minute bars. The IEX feed carries only part of consolidated volume, and quotes are not NBBO-complete.
## fit_to_this_desk
Poor as an alpha source. The desk's retail cost assumptions (10 and 25 bp) are at or above the gross weekly edge, and a 15-minute cross-sectional rebalancer would multiply turnover (the desk already measured green/red daily switching at about 200 turns a year as a loser). The desk's own finding that waiting for pullbacks costs more than it saves is consistent. The only credible use of 15-minute bars in selection and portfolio work is execution scheduling of the once-a-day decision (Heston-Korajczyk-Sadka), and the desk found the open as good as any first-hour print.
## implementation_sketch
Do not build a 15-minute alpha engine. If anything, run a descriptive study of same-half-hour-yesterday continuation for execution slicing only, gated on a slippage improvement against the next-open fill.
## pitfalls
The IEX-only volume share biases volume and imbalance signals. Bid-ask bounce in 15-minute closes looks like reversal alpha.
## confidence
strong
--- [11]
## technique
Volatility and lottery effects (idiosyncratic volatility, the MAX effect, betting against beta) and low-volatility tilts
## sources
Bali, Cakici & Whitelaw (2011) 'Maxing Out' JFE 99:427 https://pages.stern.nyu.edu/~rwhitela/papers/max%20jfe11.pdf ; Frazzini & Pedersen (2014) 'Betting Against Beta' JFE 111:1 https://pages.stern.nyu.edu/~lpederse/papers/BettingAgainstBeta.pdf ; Hou, Xue & Zhang (2020) https://www.nber.org/papers/w23394
## reported_evidence
Bali et al.: the maximum daily return over the past month (MAX) is negatively related to future returns, and the lowest-minus-highest MAX decile difference exceeds 1%/month raw and risk-adjusted. Frazzini-Pedersen: high beta is associated with low alpha across US equities, 20 international markets and other assets, because leverage-constrained investors bid up high-beta assets. Hou-Xue-Zhang: 96% of the trading-frictions anomalies, which include volatility and MAX-type measures, fail with value weights and NYSE breakpoints.
## replication_and_decay
Mostly a small-cap and short-leg phenomenon. It is weak in value-weighted large caps.
## data_required
Yahoo daily.
## fit_to_this_desk
Feasible. As a long-only CAGR engine a low-volatility tilt works against the goal: a book of high-beta AI names beats QQQ in up markets precisely through beta and skew, and the desk measured that volatility-scaled allocation roughly halved CAGR. MAX is more useful as a narrow veto on entries: skip or halve a band breakout when the trigger day itself is an extreme one-day jump.
## implementation_sketch
At most one pre-registered veto: no band entry when the name's MAX over the last 21 sessions is in the top decile of the eligible cross-section on the decision day. Judge it against the incumbent entry on untouched sessions.
## pitfalls
The hindsight book is full of lottery-like winners, so any backtest on it will say MAX 'doesn't matter' or even helps. Forward, the literature prior is the opposite.
## confidence
moderate
--- [12]
## technique
Signal combination: integrating vs mixing signals, and turnover netting
## sources
Fitzgibbons, Friedman, Pomorski & Serban (2017) 'Long-Only Style Investing: Don't Just Mix, Integrate' J. Investing 26(4):153 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2802849 ; DeMiguel, Martin-Utrera, Nogales & Uppal (2020) RFS 33(5):2180 https://www.ssrn.com/abstract=2912819 ; Chen & Velikov (2023) ; Avramov, Cheng & Metzker (2023) 'Machine Learning vs. Economic Restrictions' Management Science 69(5):2587 https://pubsonline.informs.org/doi/10.1287/mnsc.2022.4449
## reported_evidence
Fitzgibbons et al. (AQR): for long-only portfolios, aggregating style scores into one composite before selecting beats a mix of single-style sleeves, because it avoids names with offsetting exposures. DeMiguel et al.: with transaction costs, the number of jointly significant characteristics rises from 6 to 15, because rebalancing trades across characteristics cancel. Chen-Velikov: combinations net about 20 bp/month long-short after costs and decay. Avramov et al.: deep-learning signals earn their profits in microcaps, distressed stocks and high-volatility states, and deteriorate further after costs because of turnover and extreme positions.
## replication_and_decay
The integration and netting results are mechanical, so they carry over. The ML result matches the desk's own null for learned models.
## data_required
Whatever the component signals need.
## fit_to_this_desk
The desk already integrates (the conviction sum in backend/agents/trading/desk/grading.py, with equal analyst weights). Its finding that walk-forward ridge weights lost to equal weights (25.0% vs 27.2% from 2018) matches this literature, so keep equal weights.
## implementation_sketch
Keep one integrated score. If momentum or profitability is added, add it as one more equal-weight rank inside the conviction sum, not as a separate sleeve. Measure turnover netting directly: trades under the composite against the sum of trades under separate sleeves.
## pitfalls
Adding signals to a 94-name cross-section quickly overfits. Any weights found by search must clear t>3 on untouched sessions.
## confidence
moderate
--- [13]
## technique
Return seasonality: same-calendar-month momentum and off-season momentum (the one momentum family that survives post-2005 in large caps)
## sources
Heston & Sadka (2008) 'Seasonality in the Cross-Section of Stock Returns' JFE 87:418 ; Keloharju, Linnainmaa & Nyberg (2016) 'Return Seasonalities' JF 71(4):1557 https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12398 ; Chen & Welch (2026) arXiv:2607.06502
## reported_evidence
Heston-Sadka: stocks with high returns in a given calendar month tend to repeat in the same month, at annual lags up to 20 years, independent of size, industry and earnings announcements. Keloharju et al.: selecting on historical same-calendar-month returns earns 13%/yr, and similar seasonalities appear in anomalies, commodities and indices. Chen-Welch: off-season momentum and long-horizon (16-year-plus) seasonal momentum are the only momentum variants surviving post-2005 in the top-3000 universe, at about 50 bp/month long-short, before shrinkage and costs.
## replication_and_decay
Survives in the most recent and strictest test, but long-short and gross. Long-leg evidence is not separately reported, and Chen-Welch's general long-leg result (indistinguishable from luck) presumably applies.
## data_required
Monthly returns built from Yahoo daily. At least 5 and ideally 10-20 years per name. Many AI-book names lack this, so it is feasible mainly on the S&P 500 cross-section.
## fit_to_this_desk
Partial fit. It is new information the desk does not currently use, it is cheap to compute, and it is weakly correlated with 12-1 momentum. Recent IPOs in the book cannot be scored.
## implementation_sketch
A shadow on the S&P 500 learning cross-section: at each monthly decision, rank on the average same-calendar-month return over years 2-20 (seasonal) and on the average other-month return over years 2-5 (off-season, per the Chen-Zimmermann signal definitions). Take the top quintile, equal weight, with a buy/hold buffer. Gate: long-leg minus SPY and minus QQQ on untouched sessions, net of 25 bp.
## pitfalls
The survivor-only S&P 500 list creates a strong look-ahead for 20-year histories (only survivors have them). Monthly signals flip, so turnover is high without a buffer.
## confidence
weak
--- [14]
## technique
Equal weight (1/N) against optimized weights, and the rebalancing premium
## sources
DeMiguel, Garlappi & Uppal (2009) 'Optimal Versus Naive Diversification' RFS 22(5):1915 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1376199 ; Plyakha, Uppal & Vilkov 'Equal or Value Weighting?' https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1787045 ; Kirby & Ostdiek (2012) JFQA 47(2):437 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1530022
## reported_evidence
DeMiguel et al.: none of 14 models is consistently better than 1/N on Sharpe, certainty-equivalent return or turnover across 7 data sets. Sample mean-variance needs about 3,000 months of data to beat 1/N with 25 assets and about 6,000 with 50. Plyakha et al.: monthly-rebalanced equal weight beats value weight on return, four-factor alpha and Sharpe. About 42% of the outperformance is alpha from the contrarian rebalancing (it harvests reversal and idiosyncratic volatility), and the rest is factor exposure. Kirby-Ostdiek: low-turnover volatility timing and reward-to-risk timing can beat 1/N net of costs on diversified test portfolios.
## replication_and_decay
The 1/N result is one of the most replicated in portfolio choice. The Kirby-Ostdiek counterpoint applies to portfolios of portfolios, not concentrated single-stock books.
## data_required
None beyond prices.
## fit_to_this_desk
Directly explains the desk's key fact: equal-weighting the whole book (about 38-41% CAGR since 2016) beats every selection and sizing rule. The live book (backend/agents/trading/desk/risk.py BOOK_CONFIG: top_fraction=0.1, which is about 9 names, inverse volatility, a 0.30 volatility target, name_cap 0.15, and a regime multiplier) departs from 1/N on three counts: concentration, inverse volatility, and a volatility-target cash drag.
## implementation_sketch
Shadow 'A-graded, equal-weighted, capped' against the incumbent. Eligible set: all names graded A or A+ (or the top 30-50% by conviction), weights 1/N, name cap about 8-10%, rebalanced to equal weight at each reset with a buy/hold buffer. Unallocated weight goes to QQQ, not cash (see below).
## pitfalls
The 38-41% equal-weight figure is itself a hindsight-universe artefact and is not a target. The forward comparison must be against funded SPY and QQQ.
## confidence
strong
--- [15]
## technique
Inverse-volatility weighting, volatility targeting and volatility-managed portfolios
## sources
Moreira & Muir (2017) 'Volatility-Managed Portfolios' JF 72:1611 https://www.nber.org/papers/w22208 ; Cederburg, O'Doherty, Wang & Yan (2020) 'On the performance of volatility-managed portfolios' JFE 138(1):95-117 https://ideas.repec.org/a/eee/jfinec/v138y2020i1p95-117.html ; DeMiguel, Martin-Utrera & Uppal (2024) 'A Multifactor Perspective on Volatility-Managed Portfolios' JF (open access, full text read) https://lbsresearch.london.edu/id/eprint/3716/ ; Barroso & Santa-Clara (2015) JFE 116:111
## reported_evidence
Moreira-Muir: taking less risk when volatility is high raises Sharpe ratios across market, value, momentum, profitability and other factors. Cederburg et al.: across 103 strategies, volatility-managed portfolios do not systematically beat their unmanaged versions in real time, because of unstable spanning regressions. DeMiguel et al. (2024) summarise that Cederburg et al. show 'these strategies fail out-of-sample' and Barroso-Detzel that they 'do not survive transaction costs'. Their own conditional multifactor version does outperform out of sample net of costs, but that is a long-short multifactor construct. Barroso-Santa-Clara's Sharpe improvement (0.53 to 0.97) is for the long-short momentum factor.
## replication_and_decay
For single-factor or single-asset volatility timing, the out-of-sample and net-of-cost record is poor. Where it works, it improves Sharpe, not CAGR.
## data_required
Daily returns.
## fit_to_this_desk
The desk's own numbers agree: volatility-targeted allocation (vol, vol_trend in backend/agents/trading/desk/allocation.py) roughly halved CAGR, the live book's volatility target was raised from 0.25 to 0.30 because the constraint 'cost return without buying safety', and backend/market/sizing.py scales the book down whenever estimated volatility exceeds the target. In a high-volatility AI book, inverse volatility plus a volatility target mechanically underweights the names that drive outperformance against QQQ and parks the difference in cash.
## implementation_sketch
Shadow the incumbent with the volatility target removed (or set non-binding), equal weight in place of inverse volatility, and the residual in QQQ. Keep a single de-risking brake with hysteresis (the QQQ 200-day brake, already measured at about -1.7 CAGR for about 10 points less drawdown) as the only exposure control. Report realised drawdown against QQQ's drawdown, which matches the user's stated benchmark-relative drawdown objective.
## pitfalls
Removing the volatility target raises absolute drawdown in crashes (the desk measured 0.40 against 0.30 as costing about 8 drawdown points with COVID in the sample). The user's objective is drawdown relative to SPY and QQQ, so state that trade explicitly rather than hiding it.
## confidence
strong
--- [16]
## technique
Hierarchical risk parity (HRP), shrinkage covariance (Ledoit-Wolf) and minimum-variance or mean-variance optimizers
## sources
Lopez de Prado (2016) 'Building Diversified Portfolios that Outperform Out of Sample' JPM 42(4):59 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2708678 ; 'Hierarchical risk parity: Efficient implementation and real world analysis' Future Generation Computer Systems 167 (2025) https://dl.acm.org/doi/10.1016/j.future.2025.107744 ; Ledoit & Wolf (2004) JPM 30(4):110 ; Ledoit & Wolf (2017) 'Markowitz Meets Goldilocks' RFS 30(12):4349 https://ssrn.com/abstract=2383361 ; Jagannathan & Ma (2003) JF 58(4):1651 https://www.nber.org/papers/w8922 ; Cotton (2024) 'Schur Complementary Allocation' arXiv:2411.05807 ; Ovalle et al. (Jul 2026) 'Fragility of Minimum-Variance Portfolios' arXiv:2607.18624
## reported_evidence
Lopez de Prado: in Monte Carlo experiments HRP has lower out-of-sample variance than critical-line-algorithm minimum variance and than traditional risk parity. That is a simulation, not a return test. The FGCS 2025 paper (S&P 500 constituents, 2005-2023) finds 1/N beats HRP on out-of-sample risk-adjusted returns 'across all experimental setups', based on the abstract only. Ledoit-Wolf 2017: nonlinear shrinkage dominates linear shrinkage in historical backtests for minimum-variance-type portfolios. Jagannathan-Ma: a long-only constraint acts like shrinkage, so constrained minimum variance from a plain sample covariance performs as well as factor-model and shrinkage estimators. Ovalle et al. 2026: long-only minimum variance is fragile, with threshold effects from correlation and volatility interaction. Structured shrinkage reduces out-of-sample variance and turnover.
## replication_and_decay
The out-of-sample benefit of these methods is variance reduction. None is shown to raise total return over 1/N for equity stock books. A 2025 empirical test on S&P 500 names finds 1/N ahead.
## data_required
Daily returns. A 1-5 year covariance window (one HRP study found 5 years of daily data best).
## fit_to_this_desk
Feasible but misdirected. Every one of these minimises or equalises risk, and on a high-volatility AI book that means underweighting the highest-return names. It is the same mechanism as the volatility-target drag. Covariance is useful for risk reporting and for a correlation-aware theme cap, not for weights.
## implementation_sketch
Do not replace weights. Optionally use Ledoit-Wolf shrinkage (a shrunk covariance) only to compute the book's reported risk against SPY and QQQ, and to flag when the effective number of independent bets falls below a pre-declared floor.
## pitfalls
The 'outperform out of sample' framing in the HRP literature refers to variance. Do not read it as a return claim.
## confidence
strong
--- [17]
## technique
Rebalance frequency, no-trade bands and buy/hold buffers, partial trading, and staggered tranches
## sources
Novy-Marx & Velikov (2016) 'A Taxonomy of Anomalies and Their Trading Costs' RFS 29(1):104 https://www.nber.org/papers/w20721 (full text read) ; Garleanu & Pedersen (2013) 'Dynamic Trading with Predictable Returns and Transaction Costs' JF 68(6):2309 https://nbgarleanu.github.io/DynTrad.pdf ; Hoffstein, Faber & Braun (2020) 'Rebalance Timing Luck' https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3673910 ; Fan, Medeiros, Yang & Yang (2024/25) 'Cost-aware Portfolios in a Large Universe of Assets' arXiv:2412.11575
## reported_evidence
Novy-Marx-Velikov: a buy/hold spread (hold names you would not newly buy) is 'the single most effective simple cost mitigation'. Most anomalies with one-sided monthly turnover under 50% keep significant net spreads, but only two above 50% do. Costs cut realised spreads by more than 1% of monthly one-sided turnover (20% monthly turnover costs at least 20 bp/month). Equal-weighted academic results cost 2-3x more to trade and are 'misleading'. Garleanu-Pedersen: aim in front of the target and trade partially toward it, giving more weight to slower-decaying signals. Hoffstein et al.: the rebalance schedule alone changes long-only factor-index returns by often more than 100 bp a year, and staggered tranches neutralise this. Fan et al.: cost-penalised rebalancing improves results on S&P 500 and Russell 2000 names.
## replication_and_decay
These are mechanical and robust; they do not decay.
## data_required
None beyond prices and a cost model.
## fit_to_this_desk
Partly implemented already: speed=0.5, min_trade=0.005, and start-phase sweeps of the 20-session reset in backend/agents/trading/desk/paper.py. The desk's spread of CAGR across phases (5.7 points) is exactly the rebalance timing luck Hoffstein et al. describe. The grade rotation (sell below A) acts as a buffer, but entry and exit share the same threshold.
## implementation_sketch
(1) Split the book into 4 tranches rebalanced 5 sessions apart instead of a single 20-session clock. This removes the phase lottery without changing expected return. (2) Add hysteresis to the rotation: enter at A or above within the top k by conviction, and exit only when the grade falls to C or the name leaves the top 2k. (3) Keep partial trading toward target. Run it as a named shadow with the gate written first.
## pitfalls
Tranching quadruples the number of small orders. Keep min_trade and whole-share rounding in the simulator.
## confidence
strong
--- [18]
## technique
Kelly and fractional-Kelly sizing
## sources
MacLean, Thorp & Ziemba (2010) 'Good and Bad Properties of the Kelly Criterion' https://www.stat.berkeley.edu/~aldous/157/Papers/Good_Bad_Kelly.pdf ; Chopra & Ziemba (1993), as cited therein
## reported_evidence
Kelly maximises long-run growth but its bets can be very large and risky in the short term. Fractional Kelly trades growth for safety. Errors in means, variances and covariances matter roughly 20:2:1 for final wealth (Chopra-Ziemba, cited in the MacLean-Thorp-Ziemba summary; I did not re-read the primary paper).
## replication_and_decay
This is theory, not an anomaly. The practical issue is estimation error in the edge.
## data_required
An estimate of the edge and its variance.
## fit_to_this_desk
The desk's per-name expected-return estimates (IC about 0.04) are far too noisy for per-name Kelly. Full Kelly on noisy alphas produces the extreme positions Avramov et al. show destroy net returns. A book-level exposure fraction (stocks plus QQQ against cash) is the only place a Kelly argument is usable, and there it says a long-only equity book with positive expected excess return should rarely hold large idle cash.
## implementation_sketch
If used at all: size total equity exposure as at most half Kelly from the benchmark's long-run excess return and volatility, which in practice means staying near fully invested. Per-name weights stay 1/N with caps.
## pitfalls
Kelly on backtested hindsight-book returns gives absurd leverage.
## confidence
moderate
--- [19]
## technique
Concentration and skewness: why beating cap-weighted SPY or QQQ with a few names is hard, and what drove the hindsight book
## sources
Bessembinder (2018) 'Do Stocks Outperform Treasury Bills?' JFE 129:440 https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2900447 ; Heaton, Polson & Witte (2017) 'Why Indexing Works' ASMBI 33(6) https://arxiv.org/pdf/1510.03550v2 ; practitioner data on the S&P 500 Equal Weight index against the S&P 500, 2023-2024 (for example https://www.lcgassociates.com/wp-content/uploads/2024/01/Index-Concentration.pdf)
## reported_evidence
Bessembinder: most CRSP stocks since 1926 have lifetime buy-and-hold returns below one-month T-bills, and the best 4% of companies account for the entire net gain of the US market. Heaton-Polson-Witte: because the best stocks greatly outperform the rest, a randomly chosen subset of an index is more likely to underperform it. For active managers, that likelihood matters more than fees. Practitioner figures (the equal-weight S&P about 12 points behind the S&P 500 in 2023, Magnificent 7 above 30% of the index) come from secondary sources and are UNVERIFIED.
## replication_and_decay
Right-skewed stock returns are structural, not an anomaly.
## data_required
None.
## fit_to_this_desk
This is the core explanation of the desk's results. The equal-weight 94-name book won because the hindsight-selected set contains the right-tail winners, and equal weight guarantees owning all of them. The live top-10% book (about 9 names) raises the chance of missing them, which is consistent with 'equal weight beats every selection rule'. Against QQQ, which already holds the mega-cap AI winners at cap weight, the book beats the benchmark only through theme beta and small/mid-cap skew. Idle cash is pure drag against a benchmark that is always 100% invested.
## implementation_sketch
(1) Broaden rather than concentrate: all A-graded names, or the top 30-50%, equal weight. (2) Put the residual into QQQ, or a SPY/QQQ split, instead of cash; the desk's own proxy found deploying idle cash worth about +5 CAGR. (3) Report tracking error and active share against QQQ so the user can see when the book is simply a leveraged theme bet.
## pitfalls
Broadening within a single-theme book does not diversify theme risk. Correlated drawdowns against QQQ remain, and the trend brake is the only measured protection.
## confidence
strong
## ranked_recommendations
Ranked by expected net improvement over funded SPY and QQQ, per unit of build effort and overfitting risk. Every item is a named shadow with its gate written before its first session, judged only on untouched sessions, and none may be tuned on 2024-2026.

1. Stop paying the cash drag: hold unallocated weight in QQQ (or a fixed SPY/QQQ split) instead of cash. The only exposure control would be the existing QQQ 200-day trend brake with hysteresis.
   - Why: the benchmarks are always fully invested. The desk's own proxy put deploying idle cash at about +5 CAGR. The 0.30 vol target in backend/agents/trading/desk/risk.py (BOOK_CONFIG), and vol/vol_trend in allocation.py, cut return (vol-targeted allocation roughly halved CAGR). Cederburg et al. (2020) show single-asset volatility management fails out of sample.
   - Cost: almost no free parameters (just the benchmark choice), so overfitting risk is minimal.
   - Gate: net CAGR against funded QQQ at 25 bp, with drawdown reported relative to QQQ's own drawdown.

2. Replace inverse-vol concentration with broad, capped equal weight.
   - Change: equal weight across every A/A+ name (or the top 30-50% by conviction) with a cap of about 8-10% per name. This replaces the top-10% (about 9 names) inverse-vol book.
   - Why: 1/N is the hardest benchmark in portfolio choice (DeMiguel et al. 2009; HRP loses to 1/N on S&P 500 names 2005-2023, FGCS 2025). Rebalancing to equal weight earns a contrarian alpha (Plyakha, Uppal & Vilkov). With right-skewed returns and a weak signal (IC about 0.04), concentration lowers the median outcome (Bessembinder; Heaton, Polson & Witte).
   - The desk's own result that equal weight beats every selection rule is this effect, measured.

3. Turnover hygiene that does not change the signal.
   - Staggered tranches: four sub-books rebalanced 5 sessions apart instead of one 20-session clock. The desk's 5.7-point CAGR spread across start phases is exactly the timing luck Hoffstein et al. describe.
   - Buy/hold hysteresis: enter at A within the top k, exit at C or outside the top 2k. Novy-Marx & Velikov found this the single best cost mitigation.
   - Keep partial trading and min_trade (Garleanu & Pedersen).
   - Effect: small but near-certain net gain, and far less path luck in the scorecard.

4. At most one new selection input, added as one more equal-weight rank inside the existing conviction sum (integrated, not a separate sleeve).
   - Candidates: 12-1 momentum, or residual momentum against SPY, QQQ and the theme basket, plus cash-based operating profitability used only as a bottom-decile veto on the S&P 500 learning cross-section.
   - Expectation: roughly 0-2 CAGR points gross at best. Chen & Welch (2026) find post-2005 large-cap anomaly long legs indistinguishable from luck, and profitability the only category still earning, mostly on the short side.
   - Residual momentum is likely to improve Sharpe more than CAGR, so judge it on both.

5. Two cheap single-comparison vetoes on the band-breakout entry: a frog-in-the-pan filter (enter only when the 12-1 information-discreteness score is at or below the median) and a MAX filter (no entry when the trigger follows a top-decile one-day jump).
   - Evidence is weak, but the mechanism targets exactly what a 2.2-sigma breakout buys, and each costs one shadow.

6. Return-seasonality shadow on the S&P 500 learning cross-section (same-calendar-month and off-season momentum).
   - The only momentum family surviving post-2005 in large caps (Chen & Welch 2026). Low confidence for the long leg, and badly survivorship-exposed on 20-year histories.

7. Use 15-minute bars only for execution: slicing or timing the once-a-day decision, gated on measured slippage against the next-open fill.
   - Do not build a 15-minute selection or reversal engine. Evidence against: Avramov, Chordia & Goyal; Frazzini, Israel & Moskowitz; the desk's own green/red switching result. The desk also found the open as good as any first-hour print, so this is low priority.

8. Kelly reasoning only at the level of total book exposure, where it argues for staying near fully invested. Never use it per name.
## what_not_to_do
- **Covariance optimizers:** do not build HRP, Ledoit-Wolf mean-variance or minimum-variance optimizers expecting more return. Their proven out-of-sample benefit is lower variance, and on a high-vol AI book that means underweighting the names that beat QQQ.
- **Vol targeting and inverse-vol:** do not add or tighten them as return tools. Cederburg et al. (2020) show single-strategy vol management fails in real time, and the desk measured the CAGR loss itself.
- **Dead signals:** do not trade PEAD/SUE drift, accruals, or 1-month or intraday short-term reversal. Large-cap PEAD has been gone since 2006 (Martineau), press releases are priced by the open (Wu et al. 2025), accruals are dead (Green, Hand & Soliman), and reversal profits sit below costs (Avramov, Chordia & Goyal; Frazzini, Israel & Moskowitz).
- **15-minute alpha:** do not build a 15-minute cross-sectional rebalancer. IEX-only volume and retail spreads leave nothing, and turnover of about 200 a year already lost.
- **Analyst data:** do not use analyst revisions or consensus SUE. They need paid I/B/E/S and break the free-data rule.
- **Many-feature ML:** do not add ML models with many features on about 94 names. Avramov, Cheng & Metzker and Green, Hand & Zhang show the signal lives in microcaps, distressed names and high-turnover positions. The desk's null result on learned models already agrees.
- **Hindsight benchmark:** do not treat the 38-41% equal-weight hindsight-book CAGR, or any backtest on the 2026-picked book or survivor-only S&P 500 list, as the target or as evidence. The forward benchmark is funded SPY and QQQ at 10 and 25 bp.
- **Equal-weighted academic results:** do not cite them as net evidence; they cost 2-3x more to trade (Novy-Marx & Velikov). Do not cite long-short factor Sharpe numbers (Barroso & Santa-Clara, Blitz et al.) as long-only CAGR evidence.
- **Concentration:** do not concentrate further (top decile or fewer names) to chase winners. With skewed returns and a weak IC, concentration raises the chance of missing the few names that make the return (Bessembinder; Heaton, Polson & Witte).
- **Search and tuning:** do not search thresholds, lookbacks or factor sets and then report the best. Anything selected by search needs t>3 on untouched sessions (Harvey, Liu & Zhu), and nothing is tuned on 2024-2026.
- **Historical LLM tone:** do not treat historical local-LLM tone scores as point-in-time. The model saw post-dated text (Chen et al. 2026), so label those backtests as leakage-exposed.
- **Redundant momentum engines:** do not add a separate 52-week-high engine or a no-skip industry-momentum engine. Both duplicate the existing band breakout and rotation, and the evidence is weak or small-cap-only (Barroso & Wang; Grundy & Martin).