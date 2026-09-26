## topic
Intraday strategies and entry timing at about 15-minute resolution for a long-only retail US equity/ETF desk (Alpaca paper, Basic plan with real-time IEX, free delayed-SIP history, Yahoo daily, EDGAR). Covers (a) entry-timing improvements for the daily-rebalanced cash-bounded-breakout-rotation/3 book and (b) standalone intraday alpha sleeves.
## findings
--- [0]
## technique
Market intraday momentum (MIM): the first half-hour return, measured from the prior close to 10:00, predicts the last half-hour return (15:30-16:00). The 12th half-hour (15:00-15:30) also predicts it.
## sources
Gao, Han, Li, Zhou (2018), 'Market intraday momentum', JFE 129(2):394-414, https://www.sciencedirect.com/science/article/abs/pii/S0304405X18301351. Numbers below come from the SSRN working-paper text (SSRN 2552752 copy: https://c.mql5.com/forextsd/forum/173/intraday_momentum_-_the_first_half-hour_return_predicts_the_last_half-hour_return.pdf). Replication: Limkriangkrai, Chai, Zheng (2023) PBFJ 80:102086, https://researchmgt.monash.edu/ws/files/519509174/494419119_oa.pdf. Extension: Baltussen, Da, Lammers, Martens (2021) JFE 142(1):377-403, https://www.sciencedirect.com/science/article/abs/pii/S0304405X21001598. International: Li, Sakkas, Urquhart (2022) JFM 57. 0DTE mechanism: Adams, Dim, Eraker, Fontaine, Ornthanalai, Vilkov, SSRN 5641974; Dim, Eraker, Vilkov, SSRN 4692190.
## reported_evidence
Verified from the working paper: SPY, Feb 1993 to Dec 2013. Out-of-sample R2 is 1.2% using r1 alone and 1.8% using r1 plus r12. The sign-timing strategy (long or short in the last half-hour) returns 6.67%/yr with 6.19% vol, Sharpe 1.08. Being always long in the last half-hour returns -1.11%/yr. Daily buy-and-hold SPY returns 6.04%/yr with Sharpe 0.29. After quoted spreads (post-July 2001) the timing strategy returns 4.46%/yr; after 2005 it returns 6.52% net vs 7.96% gross. The long-only, no-leverage mean-variance version (0<=w<=1) returns only 3.22%/yr, Sharpe 0.82. Gains concentrate on days with high first-half-hour volatility and volume and on recession days. Across 11 ETFs, QQQ has the lowest out-of-sample R2 (0.70%). The Sharpe of 1.08 is earned with market exposure for only 30 minutes a day, so it is not comparable to a buy-and-hold Sharpe.
## replication_and_decay
The US result replicates on SPY for 1996-2013 (coefficient 7.15, R2 1.7%, out-of-sample R2 1.7%, rising to 2.3% with r12). Across Asia-Pacific markets it is mixed: present in China and Japan, absent in Hong Kong and Singapore. Baltussen et al. find it in more than 60 futures, 1974-2020, and link it to short-gamma hedging; the effect reverts over the next days. Adams et al. (SSRN abstract via search; the full text returned 403) report that 0DTE hedging needs predict lower momentum returns and lower volatility. A vendor blog (FirmTape, UNVERIFIED, commercial) reports a flat slope (+0.006, t 0.6) on 1,085 SPX sessions from April 2022 to August 2026. Every primary sample ends in 2020 or earlier. The 0DTE era gives a plausible reason for decay. I could not verify any independent post-2021 peer-reviewed estimate.
## data_required
SPY and QQQ 15-minute bars. The prior close to 10:00 return and the 15:00-15:30 and 15:30-16:00 returns fall exactly on a 15-minute grid. Consolidated (SIP) history is free on Alpaca for any window ending more than 15 minutes ago. Realistic fills need closing-auction access (MOC).
## fit_to_this_desk
Technically feasible with 15-minute bars. Economically a poor fit. In a long-only book the usable part is 'long the last half-hour when r1>0', and holding the last half-hour unconditionally lost money. A 30-minute sleeve competes for capital that would otherwise earn the full SPY/QQQ return. Even the pre-2013 long-only version (3.22%/yr) is below buy-and-hold (6.04%/yr), and the effect is weakest on QQQ. At most it could be an overlay on cash that is idle anyway, adding a few basis points a year.
## implementation_sketch
Only as a frozen falsification check, never as a tuned sleeve. Rebuild SPY/QQQ 15-minute bars from feed=sip for 2016-2026. Freeze the rule as the paper states it: long at 15:30 if r1>0, exit at the MOC close. Score it on total return of the capital it uses, compared with holding SPY/QQQ, net of 10 and 25 bp. Report it per year, with 2022+ (the 0DTE era) as its own segment.
## pitfalls
Comparing Sharpe instead of total return. Letting the sleeve use capital the book would otherwise hold. Buying at the 15:30 quote while assuming the close price. Selecting the volatility/volume condition on 2024-2026 data. The IEX-only 15:30 print is not the consolidated price.
## confidence
moderate
--- [1]
## technique
SPY 'noise area' intraday momentum with a VWAP trailing stop and volatility sizing (Zarattini, Aziz, Barbon, 'Beat the Market')
## sources
Zarattini, Aziz, Barbon (2024), 'Beat the Market: An Effective Intraday Momentum Strategy for S&P500 ETF (SPY)', SSRN 4824172 / SFI RP 24-97, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4824172. Authors' summary: https://concretumgroup.substack.com/p/beat-the-market-with-intraday-momentum. Parameter summary: CXO Advisory, https://www.cxoadvisory.com/momentum-investing/complex-intraday-time-series-momentum-strategy-applied-to-spy/. Community replication: https://www.quantconnect.com/forum/discussion/17091/. Follow-up: Maroy, SSRN 5095349 (403; abstract seen only via search).
## reported_evidence
Authors, May 2007 to early 2024, 1-minute data. The noise band is the 14-session average absolute move from the open at each time of day. Trades are long or short on band breaks and flat at the close. Costs are $0.0035/share commission plus $0.001/share slippage (per CXO). Reported stages: base 6.2%/yr with Sharpe 0.61; adding the VWAP/current-band stop gives 9.7%/yr, Sharpe 1.24; adding dynamic sizing (up to 4x leverage per CXO) gives 19.6%/yr, Sharpe 1.33, 1,985% total net. I could not fetch the paper PDF. The exact decision-grid frequency (clock-hour vs half-hour) and drawdown are UNVERIFIED.
## replication_and_decay
The QuantConnect forum reproduces it closely only when the bid/ask spread is ignored. One user's leverage-1 run shows Sharpe 0.40, a 37% win rate, and fees equal to 16.7% of returns. Others report heavy degradation with realistic fills and margin handling. A reviewer (quantmacro substack) flags the untested execution assumptions and a win rate of about 43%. Maroy's follow-up reports Sharpe above 3 from parameter and exit optimisation. That is in-sample search and should be treated as overfitting evidence, not support. I found no out-of-sample record after April 2024.
## data_required
1-minute or at most 30-minute SPY bars, intraday VWAP (which needs consolidated volume), intraday short-selling, and margin up to 4x.
## fit_to_this_desk
Poor. The desk is long-only and unlevered. Without shorts and leverage the base version made about 6%/yr before stops, below SPY buy-and-hold over the same years (roughly 10%/yr; my estimate, not from the paper). The strategy is flat overnight, which is where most of the historical equity premium accrued. VWAP built from IEX (about 2.5% of volume) is a noisy proxy. The one transferable idea is using the time-of-day-normalised move from the open as an activity filter, and the repo's 2026-09-25 microstructure review already proposes that.
## implementation_sketch
Do not build it as a sleeve. If wanted, run it as a frozen falsification only: long-only, 1x, the paper's 14-day band, a 30-minute grid on SIP 15-minute bars, spread modelled from delayed-SIP quotes. The hurdle is buy-and-hold SPY/QQQ total return at the same drawdown.
## pitfalls
Leverage produces most of the headline number. Exact stop fills are assumed. Parameters were chosen on a period that overlaps the reported sample. Minute-level stops cannot be simulated honestly on 15-minute bars: you do not know the path inside the bar.
## confidence
weak
--- [2]
## technique
Opening Range Breakout (ORB) on 'Stocks in Play' ranked by relative opening volume (Zarattini, Barbon, Aziz)
## sources
Zarattini, Barbon, Aziz (2024), 'A Profitable Day Trading Strategy for the U.S. Equity Market', SSRN 4729284 / SFI RP 24-98, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4729284. Text read from the hosted SSRN copy https://www.wealth-lab.com/api/discussion/download/pdf/8007-ssrn-4729284-1-pdf. Replication: https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/. Earlier QQQ/TQQQ ORB by the same authors is cited in the paper.
## reported_evidence
Verified from the paper text. Universe is about 7,000 CRSP stocks, 2016-2023, survivorship-free, with unadjusted IQFeed intraday data. Filters: price above $5, 14-day average volume above 1M shares, ATR above $0.50. Direction follows the first 5-minute candle. Entry is a stop order at the range high or low, the stop-loss is 10% of the 14-day ATR, and the exit is the close. Each trade risks 1% of capital, leverage is capped at 4x, start capital is $25k, and the only cost is $0.0035/share commission (the extracted text mentions no slippage model). Base ORB on all stocks: 29% total, 3.2%/yr IRR, Sharpe 0.48. Top-20 relative-volume 5-minute ORB: 1,637% total, 41.6%/yr IRR, Sharpe 2.81, max drawdown 12%, alpha 35.8%, beta 0.00. By timeframe: 15-minute ORB 17.4%/yr, Sharpe 1.43, drawdown 11%; 30-minute 2.3%/yr, Sharpe 0.21, drawdown 35%; 60-minute 4.1%/yr, Sharpe 0.40. The S&P 500 returned 198% (14.2%/yr).
## replication_and_decay
QuantConnect reports 2016 only, 1,000 names, Sharpe 2.40, and 68% of parameter combinations beating the benchmark Sharpe. That is not independent out-of-sample evidence. Forum users note failures in other regimes. Performance collapses as the opening range lengthens, which points to fragility: the edge lives in the first minutes, where spreads are widest. I found no independent out-of-sample result after 2023.
## data_required
Real-time 5-minute or 15-minute bars and consolidated opening volume for thousands of names at 9:35-9:45, a 14-day history of same-window volume, intraday short-selling, fast stop orders, and margin.
## fit_to_this_desk
Not feasible as published. The Basic plan gives real-time IEX only, about 2.5% of volume per Alpaca docs, so a relative-volume screen is noise. Consolidated SIP bars arrive 15 minutes late, so the 9:30-9:45 bar is usable only at about 10:00. The desk is long-only (half the trades vanish) and unlevered: dividing the leveraged 15-minute results by leverage leaves roughly single-digit returns (my inference). The pattern-day-trader rule was removed by SEC approval on 2026-04-14 (verified). The effective date, reported as 2026-06-04, is UNVERIFIED. The removal eases the account constraint but does not change the economics.
## implementation_sketch
Keep only the idea, not the strategy. A causally normalised 'in play' flag (opening-window consolidated volume relative to its own 14-day same-window average, from SIP history) could serve as an entry-veto or delay feature for names the book already chose. That is the fixed hypothesis in docs/research/microstructure-15-minute-review-2026-09-25.md, tested with an unconditional-delay control.
## pitfalls
Assuming stops fill exactly at 10% ATR. Bias from reading the paper's 25 best tickers. Ignoring spread at 9:35. Using IEX volume. PDT and settlement rules in cash accounts. Treating a 5-minute result as evidence for a 15-minute cadence.
## confidence
weak
--- [3]
## technique
Market-level overnight vs intraday return decomposition (overnight drift): hold overnight and avoid the session, or the reverse
## sources
Kelly and Clark (2011), J. Asset Management 12:132-145, https://link.springer.com/article/10.1057/jam.2011.2. Bondarenko and Muravyev (2023), 'Market Return Around the Clock: A Puzzle', JFQA 58(3):939-967. Boyarchenko, Larsen, Whelan (2023), 'The Overnight Drift', RFS 36(9):3502-3547, https://academic.oup.com/rfs/article-abstract/36/9/3502/7076616. Same authors, 'The Disappearing Overnight Drift', NY Fed Liberty Street Economics, 2026-07-01, https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/. Glasserman et al. (2025) arXiv 2507.04481.
## reported_evidence
Kelly and Clark (abstract): QQQ 1999-2006 geometric overnight risk premium +23.7% vs intraday -23.3%. Bondarenko and Muravyev: E-mini futures 2004-2018, returns positive overnight and near zero during regular hours. Boyarchenko et al.: 1998-2019, most of the premium accrues 2-3am ET at the European open, linked to dealer inventory from closing order imbalances.
## replication_and_decay
Verified from the NY Fed 2026 post. The 2-3am window earned about 3.7%/yr annualised over 1998-2020 but has averaged close to zero since 2021. Dispersion of end-of-day imbalances fell from 6.5% to 2.9%. The overnight-only ETFs NSPY and NIWM closed in August 2023, 14 months after launch. The 'all gains overnight' fact is well replicated for 1993-2020. Whether it persists after 2021 is doubtful.
## data_required
Daily open and close (Yahoo or SIP daily). Futures data for the 2-3am window, which a cash-equity desk cannot trade.
## fit_to_this_desk
There is no standalone sleeve here: the desk cannot trade 2-3am, and an overnight-only ETF strategy was tried live and closed. The relevant implication is structural. A long-only book already holds overnight. Any intraday-only sleeve forfeits whatever overnight premium remains, which historically was most of it.
## implementation_sketch
None as a strategy. Use it as a diagnostic: report the book's and the benchmarks' overnight vs intraday split by year from daily open/close data, so you can see whether the desk's next-open fills systematically miss or gain the first overnight.
## pitfalls
Extrapolating 1993-2020 patterns past the 2021 break. The 'open' price source matters: the official auction open and the first IEX print differ.
## confidence
strong
--- [4]
## technique
Cross-sectional overnight/intraday clienteles. Momentum profits accrue overnight, most other anomalies intraday. Intensity of the overnight-up, intraday-reversal 'tug of war' predicts future returns.
## sources
Lou, Polk, Skouras (2019), 'A tug of war: Overnight versus intraday expected returns', JFE 134(1):192-213, https://personal.lse.ac.uk/polk/research/TugOfWar.pdf. Akbas, Boehmer, Jiang, Koch (2022), 'Overnight returns, daytime reversals, and future stock returns', JFE 145:850-875, https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004116. Aboody, Even-Tov, Lehavy, Trueman (2018), JFQA 53(2):485-505, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2554010. Bogousslavsky (2021), 'The cross-section of intraday and overnight returns', JFE 141:172-194.
## reported_evidence
Verified from the LPS PDF, CRSP/TAQ 1993-2013. The standard momentum strategy (MOM) earns an overnight CAPM alpha of 0.98%/month (t 3.84) and an intraday alpha of -0.02% (t -0.06). The overnight leg's Sharpe is 0.77 vs 0.31 close-to-close. Earnings momentum (SUE) earns 100% overnight (0.56%, t 3.20). Industry momentum earns 1.07% overnight (t 6.47) and -0.63% intraday (t -2.03). Time-series momentum earns 1.40% overnight (t 3.24). Nine of 14 characteristics earn their premia intraday. The pattern replicates in nine non-US markets. Akbas et al. (abstract): more frequent positive-overnight, negative-day months predict higher future cross-sectional returns. Aboody et al.: overnight returns persist short-term and reverse long-term. Bogousslavsky: mispricing factors earn returns through the day but do poorly at the close as arbitrageurs de-lever.
## replication_and_decay
LPS includes its own international replication. Akbas et al. extend the finding. Samples end in 2013-2019. The market-level overnight drift has faded since 2021 (NY Fed 2026). Whether the cross-sectional momentum-overnight split survives after 2021 is UNVERIFIED.
## data_required
Daily open and close only: Yahoo daily, or SIP daily for official opens. Monthly counts of overnight-up and day-down sessions per stock. No intraday bars needed.
## fit_to_this_desk
The best-fitting item in this topic. It uses free daily data, it is long-only compatible, and it bears on both stock choice and entry time. (1) Entry timing: the breakout/rotation signal is momentum-like, and momentum's premium has historically arrived overnight. Deciding at close t and filling at open t+1 forfeits the first overnight of each new holding and keeps a staler last overnight. The expected size is small: about 0.98%/21, or roughly 5 bp per night, for a decile long-short, and less for long-only. It adds to any spread saving from avoiding the open. (2) Selection: overnight-momentum and tug-of-war intensity can be tested as frozen features in the balancer on the S&P 500 learning cross-section.
## implementation_sketch
(a) A diagnostic that needs no new fitting: for every historical /3 entry, compute log(open[t+1]/close[t]) and compare it with the same quantity for SPY/QQQ and for non-selected names. This measures what the next-open fill gives up. (b) Register an 'entry_at_close' variant for simulate.py, mirroring the existing exit_at_close flag. The decision must come from the completed 15:30 or 15:45 SIP bar, never from the close itself, with a MOC or LOC order submitted before 15:50 ET (Alpaca rejects cls orders from 15:50 to 19:00). (c) Add overnight-share-of-momentum and tug-of-war-count features to the balancer's candidate set under the frozen protocol, scored only on untouched sessions.
## pitfalls
Deciding on close t and filling at close t is look-ahead of the final minutes. Use the 15:45 proxy and first measure how often the proxy decision differs from the close decision. Closing-auction deviations reverse about 85% overnight (Bogousslavsky and Muravyev), so buying into a buy-imbalanced close pays a transient premium. Post-2021 decay is possible. Survivorship in both universes inflates any momentum feature.
## confidence
moderate
--- [5]
## technique
Intraday seasonality and short-lag reversal (Heston, Korajczyk, Sadka): the same half-hour's return continues on later days; short-lag reversals are bid-ask bounce
## sources
Heston, Korajczyk, Sadka (2010), 'Intraday Patterns in the Cross-section of Stock Returns', JF 65:1369-1407. arXiv version: https://arxiv.org/abs/1005.3535 (ar5iv text read).
## reported_evidence
arXiv version, NYSE stocks 2001-2005. Lag-13 (same half-hour next day) coefficient is about 3 bp with t above 9.6, persisting for at least 40 days. A decile winner-minus-loser portfolio earns about 3.01 bp next day and loses money when buying at the ask and selling at the bid. The effect is largest at the open (above 11 bp) and the close (above 8 bp). Reversal at lags 1-8 disappears in bid-to-bid and ask-to-ask returns, so it is microstructure. The abstract says timing trades can save roughly the effective spread.
## replication_and_decay
Extended by Lou, Polk, Skouras and by Keloharju et al. on return seasonalities. It is consistently not profitable after spreads as a standalone strategy. No evidence that it became tradable.
## data_required
Half-hour or 15-minute returns per stock (SIP). Quote data for spread-aware tests.
## fit_to_this_desk
Useful only for execution timing: for a name the book will buy anyway, avoid the half-hour where it has repeatedly been bid up. Not an alpha sleeve. Short-lag intraday mean reversion at 15-minute latency is liquidity-provider P&L the desk cannot capture with marketable orders.
## implementation_sketch
Low priority. After TCA exists (finding 8), check whether the realised cost at the desk's chosen execution window varies with the name's own past same-window return. Only as a registered diagnostic.
## pitfalls
The effect is smaller than the spread. Minute-level causality cannot be checked on 15-minute IEX bars.
## confidence
strong
--- [6]
## technique
Gap and attention effects at the open: fade or continuation after overnight gaps; buying high-attention names at the open
## sources
Berkman, Koch, Tuttle, Zhang (2012), 'Paying Attention: Overnight Returns and the Hidden Cost of Buying at the Open', JFQA 47(4):715-741, https://www.semanticscholar.org/paper/Paying-Attention:-Overnight-Returns-and-the-Hidden-Berkman-Koch/ff64bccbd678828e4a83fb0304e8e15148ef67a6. Plastun, Sibande, Gupta, Wohar (2020), 'Price gap anomaly in the US stock market: The whole story', NAJEF 52:101177, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3461283. Repo: docs/research/intraday-timing-2026-09-15.md (Study 1 and Study 2).
## reported_evidence
Berkman et al. (abstract): high-attention stocks show high overnight returns followed by intraday reversal because the opening price is high. The effect is concentrated in retail-attention, hard-to-value names, and the implicit cost of buying them near the open often exceeds the effective half-spread. Plastun et al. (abstract): index-level gaps, 1928-2018, move in the gap's direction on the gap day. The repo's Study 1 (1,413 sessions, 2021-2026, 93 book names) found the open as good as any first-hour print. For gap-ups of at least 2%, waiting 15-60 minutes paid -8.9 to -11.7 bp, t between -1.3 and -1.5: the right direction per Berkman, but below the registered threshold (20 bp, t>3). Study 2: every confirmation entry (EMA reclaims, prior-low reclaim) was worse than the open by 0.5-2.0% per episode.
## replication_and_decay
Berkman is a JFQA Sharpe Award paper. Its retail-attention mechanism is plausibly stronger in 2020-2026 for names like CRWV, IREN, NBIS and OKLO, but that is UNVERIFIED. Index gaps continue while single-name high-attention gaps fade, so the two findings do not conflict. The repo's own result on these names is directional but not significant.
## data_required
Official opens (daily) and completed 9:30-9:45 and 9:45-10:00 SIP bars. Optionally an attention proxy such as release tone or earnings-day flags, which the desk already has.
## fit_to_this_desk
Feasible. This is the only conditional delay with both an external mechanism and in-house directional support. The expected gain is small: about 10 bp on the subset of buys that gap up at least 2%.
## implementation_sketch
Register one fixed rule before observing outcomes: if a buy name's official open is at least 2% above the prior close, defer its buy to the 10:00 bar (a marketable limit with a cap). Include the unconditional-delay control and full cash/holding propagation, as docs/research/microstructure-15-minute-review-2026-09-25.md already requires. Score only untouched sessions, at 10 and 25 bp plus measured spread.
## pitfalls
Deleting fills from the incumbent journal is not an account simulation. Missed runaway gap-ups: Study 2 shows waiting skips the best names. Do not search thresholds (2%, 10:00) on 2021-2026, which is already examined.
## confidence
moderate
--- [7]
## technique
Time-of-day liquidity: where to trade. The spread curve is now S-shaped rather than U-shaped, the open has become more expensive, and the closing auction is cheap but carries transient pressure.
## sources
Bogousslavsky and Muravyev (2023), 'Who trades at the close? Implications for price discovery and liquidity', JFM 66. Working-paper PDF read: https://static1.squarespace.com/static/6310c0b9bb63a25599f4418c/t/634ffc92f81e226b2c30654f/1666186387645/who-trades-at-the-close_June2021.pdf. Upson and Van Ness (2017), JFM 32:49-68, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2389922.
## reported_evidence
Verified from the PDF. The closing auction was 7.5% of daily volume in 2018, up from 3.1% in 2010. The average absolute auction deviation from the 4pm midpoint is 8.1 bp against an average half-spread of 7.6 bp; it is 20.6 bp for small stocks, 2.66 bp for large stocks, and 3.63 bp for SPY, QQQ and sector ETFs (99th percentile 16.32 bp). The auction matches the pre-close bid or ask 68.5% of the time. The reversal coefficient is -0.85: most of the deviation reverts overnight. Index add/delete days add about 21 bp. At the open (9:30-9:45, 333 large stocks), effective spreads rose about 10 bp from 2010 to 2018 and NBBO depth fell about 63%. Upson and Van Ness: spreads are highest at the open and lowest at the close.
## replication_and_decay
The trend runs toward more volume at the close (indexing), with no upward trend in auction deviations. The deterioration at the open is a documented trend through 2018. Post-2018 magnitudes are UNVERIFIED.
## data_required
Delayed-SIP historical quotes and trades around each fill, free once the window is more than 15 minutes old on the Basic plan per Alpaca docs. Official open and close prints.
## fit_to_this_desk
Directly relevant to (a). Since 2026-09-08 the paper desk has sent buys as 'day' market orders queued for the open (backend/market/alpaca_trading.py submit_market_on_open). Those fill at the first continuous print, where spreads are widest; opg was abandoned because the paper venue rarely prints an opening auction. Sells already use cls (MOC). For high-volatility book names, a 9:30:01 market order plausibly costs several to 10+ bp more than the closing auction or a print at 9:45-10:00. That estimate is UNVERIFIED for these names and is exactly what TCA should measure.
## implementation_sketch
(1) Measure first (finding 13). (2) Candidate execution clocks, each registered with the same decision and a shared control: next-open day order (incumbent); next-open auction opg (live-only, cannot be validated on paper); 9:45 or 10:00 marketable limit; same-day MOC or LOC from a 15:45 decision (finding 5). Choose on measured cost plus tracking error to the official open, not on returns.
## pitfalls
Paper fills ignore spread size, price improvement and impact, so paper cannot rank these clocks. Buying at a buy-imbalanced close pays a premium that reverts, so use LOC with a cap. Index-rebalance days behave differently.
## confidence
strong
--- [8]
## technique
Execution algorithms (Almgren-Chriss optimal execution, VWAP/TWAP slicing) for a small account
## sources
Almgren and Chriss (2001), 'Optimal execution of portfolio transactions', J. Risk 3:5-40. Frazzini, Israel, Moskowitz (2018), 'Trading Costs', SSRN 3229719, https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3229719.
## reported_evidence
Almgren-Chriss trades impact cost against timing risk. Slicing only pays when an order is a meaningful fraction of volume. Frazzini et al. (abstract): $1.7T of live institutional trades across 21 markets over 19 years; actual costs were an order of magnitude below earlier academic estimates. Under the standard square-root impact law, a retail order of 1e-5 of daily volume costs about 1-2 bp of impact. That figure is my illustration, not a sourced number.
## replication_and_decay
This is established execution theory, not an alpha claim, so decay does not apply.
## data_required
Order size relative to ADV (from daily volume) and spread (from delayed-SIP quotes).
## fit_to_this_desk
At the desk's size, impact is negligible and the half-spread plus the time-of-day choice dominates. Slicing into VWAP/TWAP adds timing risk and operational complexity for almost no expected saving. VWAP is useful only as a TCA yardstick.
## implementation_sketch
No algorithm. One order per name at the chosen auction or window, with a limit cap. Log arrival mid, fill, and VWAP benchmark per fill.
## pitfalls
Building execution machinery before measuring the cost it is meant to reduce.
## confidence
strong
--- [9]
## technique
2026 preprints already reviewed in the repo: Mesfin's falsification of OHLCV intraday momentum in MNQ futures, and TradeFM, a generative trade-flow foundation model
## sources
Mesfin (2026), arXiv 2605.04004 v3, https://arxiv.org/abs/2605.04004. Kawawa-Beaudan, Sood, Papasotiriou, Borrajo, Veloso (2026), arXiv 2602.23784, https://arxiv.org/abs/2602.23784. Repo review: docs/research/microstructure-15-minute-review-2026-09-25.md.
## reported_evidence
Mesfin: 947 sessions, 2021-2025. None of 14 OHLCV signal families passed all gates; most gross edges (0.07-1.50 points) were below the 2-point friction. The positive control on 15-minute bars (London, N=247) netted +4.09 points (t 4.30), but one extra 15-minute entry delay turned it to -2.91 (t -2.78). TradeFM: a 524M-parameter model on proprietary event-level data. It reports stylised-fact fidelity only and no trading P&L; the abstract pages confirm this.
## replication_and_decay
Both are preprints with no independent replication. The repo notes internal inconsistencies in Mesfin's significance thresholds.
## data_required
TradeFM needs event-level order-flow data the desk does not have. Mesfin is futures OHLCV.
## fit_to_this_desk
Neither supports a 15-minute alpha sleeve. Mesfin's transferable lesson is to stress-test entry delay and costs separately.
## implementation_sketch
Use Mesfin's gate structure (out-of-sample t, trade count, net-of-cost sign, per-year consistency, one-bar delay stress) as the acceptance checklist for any intraday rule.
## pitfalls
Reading synthetic simulation duration as a trading horizon (TradeFM). Importing futures cost levels into cash equities.
## confidence
strong
--- [10]
## technique
Base rates for retail day trading
## sources
Barber, Lee, Liu, Odean (2014), 'The cross-section of speculator skill: Evidence from day trading', JFM 18:1-24, https://faculty.haas.berkeley.edu/odean/papers/day%20traders/The%20Cross-Section%20of%20Speculator%20Skill.pdf. SEC Release 34-105226 (2026-04-14), approving the FINRA Rule 4210 amendment that removes the PDT and $25k provisions, https://www.sec.gov/files/rules/sro/finra/2026/34-105226.pdf.
## reported_evidence
Taiwan data: fewer than 1% of day traders earn predictable positive abnormal returns net of fees. The top 500 earn +37.9 bp/day after fees; the bottom-ranked earn -28.9 bp/day. SEC order text verified: the PDT definition, day-trading buying power and the $25,000 minimum are eliminated and replaced by intraday margin standards. The effective date (reported as 2026-06-04 in FINRA Notice 26-10) is UNVERIFIED because finra.org could not be fetched.
## replication_and_decay
Consistent with other day-trader studies (e.g., Brazil); not re-checked here.
## data_required
None.
## fit_to_this_desk
This is a prior, not a technique. A standalone 15-minute sleeve starts from a population where almost nobody wins after costs. The regulatory change removes an account-size barrier but not the economics.
## implementation_sketch
Use it as the prior when setting acceptance thresholds: demand a larger out-of-sample margin for any day-trading sleeve than for a cost reduction.
## pitfalls
Survivorship in published strategy papers vs population outcomes.
## confidence
strong
--- [11]
## technique
Existing live intraday rule under audit: exit at the close (MOC) plus the 'green-day skip', which cancels a pending sell when the name opens up
## sources
Repo: docs/CHANGELOG.md, 2026-09-11 entry (deploy c988172). backend/agents/trading/desk/simulate.py (exit_at_close, green_day_skip). backend/market/alpaca_trading.py (submit_market_on_close, TIF cls).
## reported_evidence
Repo's own simulation over 11.66 years on the book. Baseline sell-at-open: 25.1% CAGR, Sharpe 1.44. Exit-at-close alone: 24.3%, Sharpe 1.38. Exit-at-close plus green-day skip: 36.0% CAGR at 25.6% vol, Sharpe 1.33, max drawdown -28.4%, 81 fewer trades. Sharpe fell while CAGR and vol rose, which means more exposure, not better timing.
## replication_and_decay
Measured only on the hindsight-picked book, where equal-weight buy-and-hold makes about 38-41% CAGR. Any rule that sells less converges toward that biased benchmark. No S&P 500 cross-section test and no unconditional 'defer every sell one session' control is recorded.
## data_required
Daily opens and closes. The existing simulator.
## fit_to_this_desk
Already live. It is the repo's largest claimed intraday-flavoured gain, and it is probably a survivorship and exposure artefact.
## implementation_sketch
Re-run the three variants plus an unconditional one-session sell-deferral control on the S&P 500 learning cross-section, and report exposure-matched (beta and cash) differences. Keep the rule only if the conditional version beats the unconditional deferral there.
## pitfalls
Judging the rule on the book. Comparing CAGR without matching exposure.
## confidence
moderate
--- [12]
## technique
Measurement infrastructure: consolidated (SIP) history instead of IEX, and post-trade cost analysis instead of trusting paper fills
## sources
Alpaca docs: https://docs.alpaca.markets/docs/historical-stock-data-1 (IEX is about 2.5% of market volume); https://docs.alpaca.markets/us/docs/about-market-data-api (Basic: real-time IEX, history since 2016, 'latest 15 minutes' restriction); https://docs.alpaca.markets/docs/paper-trading (fill model); https://docs.alpaca.markets/docs/orders-at-alpaca (opg rejected from 9:28 to 19:00; cls rejected from 15:50 to 19:00).
## reported_evidence
Paper trading fills against the NBBO and gives random partial fills 10% of the time. It does not check order size against NBBO size and does not model market impact, latency slippage, queue position or price improvement. The free plan can query historical SIP data once the window's end is more than 15 minutes old. The repo's 15-minute research store is built with feed=iex (backend/market/alpaca.py line 154). backend/cli/market_pick_audit.py already swaps in feed=sip for history.
## replication_and_decay
n/a (vendor documentation, current as of fetch).
## data_required
Historical SIP 15-minute bars for book plus S&P 500 names from 2016; SIP quotes and trades in a window around each paper fill timestamp.
## fit_to_this_desk
Required before any entry-timing decision. The current 10 and 25 bp cost stresses are assumptions. Paper fills cannot tell the incumbent next-open day order apart from the alternatives.
## implementation_sketch
(1) A one-time rebuild of the research 15-minute store from feed=sip, keeping the IEX cache for provenance and reconciling closes. (2) A nightly TCA job: for each fill, fetch SIP quotes from 1 minute before to 5 minutes after the fill time the next morning. Record arrival mid, effective half-spread, and fill vs official open or close. Aggregate by name, clock and gap bucket. Use the result to replace fixed bp costs in simulate.py with measured per-bucket costs.
## pitfalls
Rate limit of 200 requests/min. The adjustment basis must match (adjustment=all) between SIP and the daily store. Quotes can be crossed or locked at 9:30. Paper fill timestamps are not live fills.
## confidence
strong
## ranked_recommendations
Ranked by expected net gain over SPY/QQQ relative to implementation and overfitting risk. The honest headline: nothing in the intraday literature is likely to lift this long-only, unlevered book's total return above SPY/QQQ by itself. Execution-cost savings and one overnight-timing test are worth doing. Standalone 15-minute sleeves are not.

1. Measure costs before changing anything (finding 13). Rebuild the 15-minute research store from free delayed SIP data; the code already does this in market_pick_audit. Add next-morning TCA of every paper fill against SIP quotes. The overfitting risk is zero, because this replaces the assumed 10/25 bp with measured costs per name and time of day. Paper fills cannot do that job: no impact, no size check, no auction. Every later ranking depends on this step.

2. Take buys out of the first continuous print after the open (findings 8 and 5). The incumbent 'day' market order queued for the open fills where effective spreads are widest and have been getting worse. The closing auction costs about 2.7 bp for large caps and about 3.6 bp for SPY/QQQ, and momentum-type premia have historically arrived overnight (Lou-Polk-Skouras: 0.98%/month overnight vs -0.02% intraday). Register a same-day MOC/LOC entry decided on the completed 15:45 SIP bar, before the 15:50 cls cutoff.
   - First step, no outcomes needed: measure how often the 15:45-proxy /3 decision differs from the close-based decision.
   - Then run it as a shadow on untouched sessions only, alongside an unconditional control, using measured costs.
   - Expected value = spread saved per trade × trades per year, plus a few bp of first-night drift per entry. My rough estimate is +0.5 to 2%/yr at typical rotation turnover. That is UNVERIFIED and depends on the desk's actual trade count.
   - Risks: decision-proxy error, closing price pressure that reverts overnight (-0.85), and weaker overnight effects since 2021.

3. Audit the live green-day skip on the S&P 500 learning cross-section with an unconditional one-session sell-deferral control (finding 12). Its +11.7 CAGR on the book came with a lower Sharpe and higher vol. That looks like exposure to a hindsight-picked universe, not timing skill. This is cheap and could remove a flattering artefact from the live policy.

4. One registered conditional delay: defer buys of names that gap up at least 2% at the open to the 10:00 bar, with an unconditional-delay control (finding 7). Berkman et al. give the mechanism, and the repo's Study 1 points the same way (-9 to -12 bp, not significant). Expected value is small and applies to a subset of buys. Test it only on untouched sessions, with no threshold search.

5. Selection features from the overnight/intraday split (finding 5): overnight-momentum share and tug-of-war intensity (Akbas et al. 2022), from free daily open/close data. They go into the balancer's candidate features under the frozen protocol. This is the only item here aimed at 'choosing the right stocks'. The risk is moderate: it adds features to a desk where learned models have not yet beaten the rule, and the samples end before the 2021 decay.

6. Standalone 15-minute sleeves (Gao intraday momentum on SPY/QQQ, Zarattini noise-area, ORB on stocks in play): at most a frozen, long-only, 1x falsification run on SIP data with total return against buy-and-hold SPY/QQQ as the hurdle. Expect them to fail. Their headline numbers depend on shorting, up to 4x leverage, 1-5 minute data, or pre-2013 and pre-0DTE samples. Long-only versions earn less than simply holding the index: Gao's long-only mean-variance portfolio made 3.22%/yr vs 6.04%/yr buy-and-hold. For a real total-return gain, keeping idle cash in SPY/QQQ (the earlier proxy's +5 CAGR) beats any sleeve here.

Implementation order once approved: 1, then 2's decision-agreement check, then 3, then the registered shadows for 2 and 4, then 5. Nothing in 6 gets built.
## what_not_to_do
- Don't build ORB-on-stocks-in-play or the SPY noise-area strategy as sleeves. The published results need shorting, up to 4x leverage, 1-5 minute data, and near-exact stop fills. The 30- and 60-minute ORB versions earned only 2.3% and 4.1%/yr even with leverage.
- Don't rank or filter 'stocks in play' by IEX volume. IEX is about 2.5% of consolidated volume, and real-time SIP is not on the free plan.
- Don't compare time-in-market-limited strategies by Sharpe. Gao's Sharpe of 1.08 comes from 30 minutes of exposure a day. The objective here is total return vs SPY/QQQ.
- Don't treat Alpaca paper fills as execution evidence. The paper venue ignores impact, size and price improvement, and it did not fill 8 of 9 opg auction orders.
- Don't decide on the close and fill at that same close in any backtest. Use a completed 15:30 or 15:45 bar and measure how often that proxy disagrees with the close decision.
- Don't search thresholds, delays or clocks on 2021-2026 book sessions, or on 2024-2026 at all. Study 1 and Study 2 already used that history.
- Don't reintroduce confirmation or pullback entries (EMA reclaim, prior-low reclaim). The repo measured every variant as worse than the open, and coarser bars were worse still.
- Don't chase the overnight drift. It has averaged close to zero since 2021 (NY Fed 2026), and the overnight-only ETFs closed in 2023.
- Don't trade Heston-Korajczyk-Sadka seasonality or short-lag intraday reversal as alpha. They are smaller than the spread, and the reversal is bid-ask bounce.
- Don't build VWAP/TWAP/Almgren-Chriss slicing at retail size. Impact is negligible, and the decision that matters is which auction or window to trade in.
- Don't cite TradeFM (no P&L) or Mesfin (a falsification study) as support for 15-minute alpha.
- Don't judge any timing rule on the hindsight-picked book alone. Survivorship makes any rule that sells less look good, as the green-day skip shows. Always include an unconditional-delay control and the S&P 500 learning cross-section.
- Don't let an intraday sleeve take capital the book or the benchmark would otherwise hold overnight.