# Stage 4 literature: market structure, turning points and ML timing for the graded book (2026-09-29)

Research only: no code, no model, no live change. This memo covers structure,
trends, turning points and ML for them. Mean reversion and Bollinger squeezes
are covered in depth by a separate memo; they appear here only where they
touch "buy the dip". It is an input to the Stage-4 registration of
grade-conditional multi-day timing.

**The question.** The grade gate decides what to hold: every A/A+ name at
equal weight, a 20% cap, a reset every 20 sessions, downgrade exits. Stage 4
asks when to buy and sell within 1-20 sessions:

- An A-grade name in a pullback may keep falling for days before its
  structure turns.
- A weakening name may break structure before it is downgraded.
- The operator believes A-grade names should be bought on dips and lower
  grades sold on pops, and asks whether CNNs can detect structure shifts.

## How to read this

- **Evidence grades.** These follow
  [feature-research-2026-09-29.md](feature-research-2026-09-29.md).
  - **A:** peer-reviewed, with out-of-sample or post-publication evidence that
    survives costs in a relevant market and horizon.
  - **B:** mixed. Peer-reviewed but in-sample, gross of costs, in another
    asset class, only in small stocks, or contested. Strong working papers
    also go here.
  - **C:** practitioner material, vendor or educator backtests.
  - **↓** marks decay after publication or after costs.
- **Access flags.** "Abstract only" or "summary only" means I could not read
  the full text. The figures then come from the abstract or from the named
  summary. A few extractions from full PDFs were ambiguous, and I say so
  where it matters.
- **Repo facts.** These are cited by document. Unless marked out-of-sample,
  they are in-sample on the point-in-time book.
- **My calculations.** Everything marked "(calculation)" is my own
  arithmetic, with its assumptions stated. It is not a literature result.

---

## 0. The answer in brief

1. **Timing on price alone is a bet that returns are predictable.** For a
   martingale, no stopping rule has a positive expected gain. With the A
   book's drift, any wait that holds cash pays for it:
   - about 10 bp a session on 2016-2023 (every A/A+ name at equal weight
     compounded at 29.9%);
   - about 17 bp a session on 2024-2026.

   Waiting is close to free only if the capital waits inside the rest of the
   book. The repo's timing rules that skipped or waited in cash all lost
   (§1.5).
2. **The +2 bp a session floor is a problem of scale, not of signal.**
   - Re-timing every entry and every downgrade exit touches about 0.5 orders
     a session at 5-9% of NAV each.
   - To add +2 bp a session, that needs roughly 45-105 bp of improvement on
     every re-timed order: 59-106 bp for entries alone, about 45-80 bp with
     exits included.
   - A rule that re-times only a fifth of the orders needs about 250-500 bp
     on each one.
   - The large-cap effects in the literature at 1-20 days are 10-50 bp per
     affected order, and they have been decaying (§5, §10).
3. **Market structure** (swing points, higher highs and higher lows, break of
   structure, change of character).
   - I found no peer-reviewed test of break of structure or change of
     character; the terms are practitioner vocabulary
     ([LuxAlgo](https://www.luxalgo.com/library/concept/break-of-structure/)).
   - Chart patterns carry information, but no profit in large caps
     ([Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf);
     [Savin-Weller-Zvingelis 2007](https://www.biz.uiowa.edu/faculty/gsavin/papers/hsrevision_paw_10%2019%2006.pdf)).
   - Support and resistance levels on NYSE/Nasdaq stocks do not beat
     buy-and-hold
     ([Zapranis-Tsinaslanidis 2012](https://ideas.repec.org/a/taf/apfiec/v22y2012i19p1571-1585.html)).
   - On technology-industry portfolios, technical rules worked on 1995-2002
     and none beat buy-and-hold on 2003-2010
     ([Shynkevich 2012](https://econpapers.repec.org/RePEc:eee:jbfina:v:36:y:2012:i:1:p:193-208)).
   - The directional-change "overshoot ≈ threshold" law is what a random walk
     implies (§1.4). Directional-change trading results are in FX, intraday
     and gross of costs.
4. **Momentum turning points** carry information at the index level.
   - US 1969-2018 ([Goulding-Harvey-Mazzoleni 2023](https://people.duke.edu/~charvey/Research/Published_Papers/P158_Momentum_turning_points.pdf);
     [working paper](https://www.toptradersunplugged.com/wp-content/uploads/2021/12/Momentum-Turning-Points.pdf)).
     "Correction" months (slow momentum up, fast down) were 24.5% of the
     sample. The next month earned 6.5% annualized, against 9.5% after
     "Bull" months and −7.7% after "Bear" months.
   - Blending the fast and slow signals raises the Sharpe ratio from
     0.38/0.34 to 0.48.
   - There is no single-stock evidence.
   - Time-series momentum in single stocks exists at 12 months (0.76% a
     month value-weighted) and has faded: 0.55%, t 1.76, on 1996-2017
     ([Lim-Wang-Yao 2018](https://eprints.lancs.ac.uk/id/eprint/128366/1/Time_Series_Momentum_in_Nearly_100_Years_of_Stock_Returns.pdf)).
5. **Change-point and regime detection.**
   - The best out-of-sample evidence is at the index level. A statistical
     jump model on the S&P 500, 1990-2023, after 10 bp costs and a one-day
     delay, raised the Sharpe ratio from 0.48 to 0.68
     ([Shu-Yu-Mulvey 2024](https://arxiv.org/html/2402.05272v2)). Its median
     detection lag was 25 calendar days.
   - Markov-switching bull/bear models do not forecast market returns
     ([Kirby 2023](https://www.sciencedirect.com/science/article/abs/pii/S1544612322005463)).
   - I found no credible out-of-sample single-stock evidence for Bayesian
     online change-point detection, hidden Markov or CUSUM timing.
6. **Pullbacks and falling knives in large caps.**
   - **The one-month pattern in high-turnover names is momentum, not
     reversal.** Among the 500 largest stocks, short-term momentum earns
     +0.42% a month (t 4.91) and short-term reversal −0.02%
     ([Medhat-Schmeling 2022](https://openaccess.city.ac.uk/id/eprint/31278/1/MS_short_term_mom_v27.pdf)).
     Reversal turns into momentum for high-turnover stocks near their
     52-week high
     ([Chen-Stivers-Sun 2024](https://www.sciencedirect.com/science/article/abs/pii/S0927539824000902)).
   - **Liquidity dips in the largest stocks are small and short.** Price
     pressure is 17 bp with a half-life of 0.54 days
     ([Hendershott-Menkveld 2014](http://faculty.haas.berkeley.edu/hender/price_pressures.pdf)).
   - **Reversal pays mainly after market-wide falls.** It earns 1.18% a week
     after large market declines, against 0.52-0.64% otherwise
     ([Hameed-Kang-Viswanathan 2010](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/lEJ6N1370226075.pdf)),
     and it scales with VIX ([Nagel 2012](https://www.nber.org/papers/w17653)).
   - **Drops with information drift; drops without it revert**
     ([Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf)).
   - **Buying the dip loses to holding.** On the S&P 500 it underperforms
     buy-and-hold: Sharpe −0.04 on 1965-2025 and −0.27 since 1989. It also
     underperforms on the Magnificent 7
     ([AQR 2025, practitioner](https://www.aqr.com/-/media/AQR/Documents/Alternative-Thinking/AQR-Alternative-Thinking---Hold-the-Dip.pdf?sc_lang=en)).
7. **ML for turning points.**
   - **Chart CNNs mostly capture short-term reversal in small stocks.**
     Jiang-Kelly-Xiu's CNN reaches a 7.15 Sharpe ratio equal-weighted but
     1.49 value-weighted on 5-day images, and 2.16 against 0.49 on 20-day
     images ([JKX](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf)).
     Four simple close-location and reversal variables explain 73% of the
     weekly CNN portfolio returns
     ([Dixon-Zeng 2024](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/925943/CNN-Draft-July-2024.pdf)).
   - **Turning-point classifiers report accuracy or cost-free backtests.**
   - **Meta-labeling has no peer-reviewed out-of-sample, after-cost evidence
     in equities.**
   - **The repo's CNNs already failed.** The JKX replica and the stage-3 CNN
     overlays gave −0.001 IC and −0.2 to −0.4 bp a session.
8. **Multi-timeframe confirmation.**
   - Combining horizons helps at monthly frequency, in the trend factor and
     in the Goulding-Harvey-Mazzoleni blend.
   - I found no systematic test of "weekly trend plus daily trigger".
   - In this repo, every intraday confirmation lost to the open, and the
     coarser the bar the larger the loss.
9. **Candidates** (§9, nine rules).
   - **Best supported, but small:**
     - C1, a momentum-screen entry delay that is switched off in market
       stress;
     - C2, patience after information shocks.
   - **Mixed or weak:** C4 (patience with names in deep drawdown), C5
     (downgrade-exit screen) and C3 (name-level momentum states).
   - **Likely to fail:**
     - C6, structure-break exits;
     - C7, a sector regime gate;
     - C8, a meta-label model;
     - C9, a CNN structure-turn detector.
10. **Prior** (§10).
    - The chance that any one rule adds at least +2 bp a session after costs
      is about 2-4%.
    - The chance that at least one of the nine does, before deflation, is
      about 8%. After the deflated-Sharpe gate it is about 3%.
    - The best real single-rule effect is likely +0.1 to +0.5 bp a session,
      and all the favourable rules together stay under +1 bp.
    - The study's honest product is per-event diagnostics and a clean
      negative.

---

## 1. First principles and the book's arithmetic

### 1.1 Timing is a bet on predictability

If prices were a martingale, the expected gain of any rule that decides when
to act from past prices would be zero (optional stopping). Swing points, a
break of structure and moving-average crosses are all functions of past
prices. So a structure-timing rule can add value only if the structure state
changes the conditional distribution of future returns.

Pattern studies show exactly that change in distributions, and warn that
"informativeness does not guarantee a profitable trading strategy"
([Lo-Mamaysky-Wang](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf)).

### 1.2 Drift, and where the waiting capital sits

The A book has strong positive drift.

- **2016-2023.** Every A/A+ name at equal weight compounded at 29.9%, about
  10.4 bp a session (feature-research §0.1; calculation: ln 1.299 / 252).
- **2024-2026.** The live executor returned 52.6%, about 16.8 bp a session
  (`docs/research/midcycle-ew-2026-09-27.md`).

A buy deferred by W sessions while the money sits in cash costs about
w · W · μ in expectation:

- at w = 7% of NAV, W = 5 and μ = 10.4 bp, that is 3.6 bp of NAV per order;
- at the 2016-2023 rate of 0.38 orders a session, it is about 1.4 bp a
  session of drag;

before any price improvement (calculation).

If the waiting capital stays in the rest of the A book, the expected cost is
only w · W · (μ_name − μ_book). That is close to zero, because the grade's
own cross-sectional edge is small: about 2 points a year, t 1.5
(feature-research §6.4). **Every candidate in §9 therefore parks waiting
capital in the book.** This is the single most important design choice.

### 1.3 Scale: why the floor is hard

- **Order counts.** The `/4` book placed 758 orders in the 2,012 sessions of
  2016-2023 (0.377 a session) and 180 in 686 sessions of 2024-2026 (0.262),
  at 5-9% of NAV each (feature-research §6.3). There are also about 33
  downgrade exits a year, roughly 0.13 a session (`midcycle-ew-2026-09-27.md`).
- **What +2 bp a session needs.** An average improvement of 59-106 bp on
  every order in 2016-2023, and 85-152 bp in 2024-2026 (feature-research
  §6.3). With entries and exits together (about 0.5 a session at 7%), it is
  still about 55-60 bp per order (calculation).
- **Selective rules need much more.** A rule that re-times only a fifth of the
  orders needs about 5 times that per re-timed order: roughly 250-500 bp.
  That is about 0.5-1 standard deviation of a 5-session relative return for
  these names (calculation).
- **Power** (calculation).
  - Assume a 5-session name-minus-book return with a standard deviation of
    about 4.5-5.5%, which is 2-2.5% a day of residual volatility.
  - Over all 758 entries of 2016-2023, the standard error of a mean
    per-event effect is 16-20 bp. A t of 3 then needs about 50-60 bp.
  - Over the 150 or so events a selective rule touches, the standard error
    is 37-45 bp, and a t of 3 needs about 110-135 bp.
  - Clustering of events at resets makes both larger.
  - Most effects the literature supports (10-50 bp per affected order) are
    below what this study can detect.

### 1.4 Swing points under a random walk: frequency, overshoot, time out

A zigzag or directional-change rule with threshold θ has a leg that ends when
the price retraces θ from its running extreme. For a driftless random walk
with daily volatility σ, two standard drawdown results apply (calculation;
the Taylor/Lehoczky results for Brownian drawdowns):

- the expected leg length is θ²/σ² sessions;
- the further move after a directional change is confirmed (the
  "overshoot") is exponentially distributed with mean θ.

Consequences:

- **The "scaling law" is the null.** Glattfelder, Dupuis and Olsen found in FX
  that "on average, a directional change Δx_dc is followed by an overshoot of
  the same magnitude"
  ([ar5iv](https://ar5iv.arxiv.org/html/0809.1040)). That is what a random
  walk implies, so the law is not by itself evidence of predictability. The
  empirical finding that overshoots take about twice as long as the
  directional change is extra information about the time scale, not about
  direction.
- **Frequency.** At σ = 3% a day:
  - θ = 3σ (9%) gives legs of about 9 sessions, roughly 14 down-turns per
    name a year;
  - θ = 5σ (15%) gives about 25 sessions, roughly 5 a year.

  An exit and re-entry on each down-turn costs about 32 bp at 16 bp a side.
  That is 1.6-4.5% a year per position before any whipsaw (calculation).
- **Time out of the market.** In a driftless walk, the time between a down-turn
  confirmation and the next up-turn confirmation is half the time, whatever
  θ is (by symmetry). A symmetric structure-exit rule is therefore out of the
  name about half the time, less in a strong uptrend. On a book whose return
  comes from being invested, that forgoes up to half the drift unless the
  down-leg state predicts negative returns (calculation).
- **Confirmation lag of moving averages.** A simple average of n sessions lags
  the price by (n−1)/2 sessions, its centre of mass. Price-minus-average and
  crossover rules trade that lag against whipsaws
  ([Zakamulin](https://smallake.kr/wp-content/uploads/2016/04/SSRN-id2585056.pdf)).

### 1.5 What this repo has already measured that bears on multi-day timing

| Finding | Where | What it implies |
|---|---|---|
| Every confirmed intraday entry (first close above the 15/30/60-minute 9-EMA, or above the prior low) lost to the open print. The paired difference was −0.5% to −2.0% per episode, and the coarser the bar the worse. "By the time a bar has confirmed a turn, the move that mattered has happened." | `docs/research/intraday-timing-2026-09-15.md`, Study 2 | Confirmation has a cost, and here it was larger than any benefit. |
| Letting context skip entries cut exposure from 86.6% to 56.3% and cost −22.8 bp a day (95% CI −40.6 to −6.8) against always entering, on the 2025-2026 window. | `entry-context-results-2026-09-21.md` | Waiting in cash is expensive; park the capital. |
| After "bad trend" market states, the book's next 20 sessions were *better*. With the benchmark under its 50-day average, +1.63% (t 0.94); 5% off its high, +2.87% (t 1.66). In-sample, non-overlapping windows. | `opportunity-and-cash-2026-09-18.md` | Market-level trend breaks were buying opportunities for this book, not exits. |
| Single-name catastrophe stops: every trigger in ten years was a false alarm, and every stop that fired cost CAGR. | `catastrophe-stop-2026-09-27.md` | The grade rotation, not price stops, removes broken names. |
| A dip into a support level closes where a matched dip into nothing closes. The isolated-level bounce is intraday and gives back −14 bp over 5 sessions. | `sr-levels-2026-09-29.md` | Level-based structure does not carry over days. |
| Inside the A/A+ book, the most stretched name kept winning: dropping it cost 4.5% per 20 sessions on 2024-2026 (t +2.4). The one-month reversal separates graded names at large, not A/A+ names from each other. | `stage3-results-2026-09-29.md` | This is the short-term momentum that §5.2 predicts for high-turnover, near-high names. "Buy A on dips" has little to work with inside the book. |
| Nothing beat the board's 1% dip rule. The models' own timing lost 1.5 bp a session on 2024-2026 (t −3.0). The CNN overlays gave −0.4 and −0.2 bp a session. | `stage3-results-2026-09-29.md` | The ML-timing prior is low on this data. |

---

## 2. Market structure (topic 1)

### 2.1 Definitions in use

- **Fractal swing point** (Williams, practitioner). A bar whose high (low) is
  the highest (lowest) of k bars on each side, commonly k = 2. It is known only
  k bars later. The repo's `levels.swing_points` uses 5 bars, stamped at
  confirmation.
- **Zigzag or directional change (DC).** A turn is confirmed when the price has
  moved θ from the running extreme since the last turn. The extreme becomes
  the swing point, and the move after confirmation is the overshoot
  ([Wikipedia: directional-change intrinsic time](https://en.wikipedia.org/wiki/Directional-change_intrinsic_time);
  [Wu-Han 2023](https://arxiv.org/html/2309.15383v1) give the formal
  p(t) ≥ P_ext(1+θ) condition). With θ scaled to volatility, the swing points
  are comparable across names and years.
- **Uptrend and downtrend.** The last two confirmed swing highs and the last
  two swing lows are both rising (higher highs and higher lows), or both
  falling.
- **Break of structure (BOS)** is "a with-trend structural break": in an
  uptrend, trading through the latest swing high.
- **Change of character (CHoCH)** is the same mechanics against the trend,
  and "warns the trend may be turning"
  ([LuxAlgo, practitioner](https://www.luxalgo.com/library/concept/break-of-structure/)).
  - The same source advises requiring "a candle body to close beyond the
    swing", because wick-only pokes often reverse.
  - It gives no pivot lengths and no statistics.
  - (Usage varies: many traders call a close below the last higher low a
    bearish break of structure, as the feature-research memo does.)
- **Dow theory** is the historical ancestor: persistent primary trends,
  confirmation across the industrial and transport averages, and "lines"
  before a trend emerges
  ([Brown-Goetzmann-Kumar 1998](http://depot.som.yale.edu/icf/papers/fileuploads/2439/original/98-86.pdf)).

### 2.2 Systematic tests

| Study | Sample | Finding | Costs, recency | Here? |
|---|---|---|---|---|
| [Brown-Goetzmann-Kumar 1998](http://depot.som.yale.edu/icf/papers/fileuploads/2439/original/98-86.pdf) | 255 Hamilton editorials, DJIA 1902-1929 | Following the calls returned 10.73% a year against 10.75% for buy-and-hold, with Sharpe 0.559 against 0.456, alpha 4.04% and beta 0.33. 110 correct calls against 74 wrong. A neural net recovered his rules as momentum and reversal rules. | Index, pre-1930 | No. It shows structure-trend reading reduced risk at the index level, not single-stock timing. |
| [Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf) | 1962-1996, NYSE/AMEX and Nasdaq, 50 random stocks per 5-year subperiod | Kernel smoothing over 38-day windows at 0.3 × the cross-validated bandwidth; ten patterns; one-day returns three days after completion. On NYSE/AMEX 7 of 10 patterns change the return distribution. On Nasdaq all 10 do. | No trading test: "informativeness does not guarantee a profitable trading strategy" | Weak: information, not profit; the test period ends in 1996. |
| [Savin-Weller-Zvingelis 2007](https://www.biz.uiowa.edu/faculty/gsavin/papers/hsrevision_paw_10%2019%2006.pdf) | S&P 500 and Russell 2000 stocks (June 1990 members), 1990-1999 | 63-day kernel windows; horizons of 20/40/60 days. Head-and-shoulders predicts lower returns: about 5-7% a year risk-adjusted in the Russell 2000 when combined with the market. "No evidence that a stand-alone trading strategy based on HS patterns applied to S&P 500 stocks would be profitable." | Break-even costs 80-90 bp in the Russell sample | Large caps: no. |
| [Zapranis-Tsinaslanidis 2012](https://ideas.repec.org/a/taf/apfiec/v22y2012i19p1571-1585.html) (abstract only) | NYSE and Nasdaq daily closes, about 20 years | Rule-based horizontal support and resistance from local extrema. Supports predict "trend interruptions" better than resistances, but "fail to generate excess returns when … compared with simple buy-and-hold". | Gross | No. This matches the repo's own finding. |
| [Marshall-Qian-Young 2009](https://ideas.repec.org/a/taf/apfiec/v19y2009i15p1213-1221.html) (abstract only) | US stocks by size, liquidity and industry, 1990-2004 | Moving-average and trading-range-break rules are "rarely profitable". Where they are, it is in smaller, less liquid stocks, with no industry pattern. | After data snooping | No. |
| [Shynkevich 2012](https://econpapers.repec.org/RePEc:eee:jbfina:v:36:y:2012:i:1:p:193-208) (abstract only) | Technology-industry and small-cap portfolios, 1995-2010 | Many technical rules show superior predictability after the data-snooping adjustment in the first half. "Technical analysis is not able to outperform the buy-and-hold approach for any portfolio in the set in the second half". | Small or moderate costs; ↓ | The closest sector match to this book, and negative since 2003. |
| [Bajgrowicz-Scaillet 2012](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p473-491.html) (abstract only) | 7,846 rules on the DJIA, 1897-2011 | Winners cannot be picked in advance. "Even in-sample, the performance is completely offset by the introduction of low transaction costs." | ↓ | Index, but the multiplicity lesson applies. |

I found no peer-reviewed, systematic test of higher-high/higher-low sequences,
break of structure or change of character as trading rules on single stocks.
A search for smart-money-concept backtests returned only practitioner blogs
and a Medium post, none of which I would cite as evidence.

### 2.3 Directional change and intrinsic time

- **[Glattfelder-Dupuis-Olsen 2011](https://arxiv.org/abs/0809.1040).** They
  found 12 scaling laws across 13 FX rates over about three orders of
  magnitude. The overshoot is about equal to the DC threshold, and takes
  about twice the time and ticks ([ar5iv](https://ar5iv.arxiv.org/html/0809.1040)).
  §1.4 shows the size law is the random-walk null.
- **Tsang et al. 2017** profile equity price movements in DC terms
  ([QF](https://www.tandfonline.com/doi/abs/10.1080/14697688.2016.1164887);
  seen in search, 403 on access). It is a descriptive framework.
- **[Adegboye-Kampouridis 2021](https://repository.essex.ac.uk/29573/)**
  (abstract only). ML predicts DC trend reversals on 20 FX markets, 10-minute
  data, 10 months and 1,000 datasets, and "statistically outperform[s]" 10
  benchmarks.
- **[Wu-Han 2023](https://arxiv.org/html/2309.15383v1).** DC plus HMM regime
  detection on 8 FX pairs, tick data, 2019-2020. The combined strategy
  averaged a 58.76% return against −24.36% for the baseline, with
  **transaction costs explicitly excluded**.
- **[GP-DC on 33 datasets from 3 stock markets](https://link.springer.com/chapter/10.1007/978-3-031-14721-0_3)**
  (abstract only). It beats buy-and-hold. The abstract reports no magnitudes
  or costs.
- **Bull and bear dating is a DC rule at index scale.**
  [Lunde-Timmermann 2004](https://econweb.ucsd.edu/~atimmerm/dur-14-2.pdf)
  date bull and bear markets with 20/15, 20/10, 15/15 and 15/10% filters on
  daily US stocks from 1885 to 1997.
  - With 15/10 there were 86 bull markets (mean 49 weeks, median 27) and 83
    bear markets (mean 24 weeks, median 17).
  - The bull hazard *falls* with age and the bear hazard *rises* with age.
    The paper models no confirmation lag.

### 2.4 Verdict on market structure

- **Claim.** Swing structure identifies when a trend has turned.
- **Evidence.**
  - Structure and patterns are informative about return distributions (B).
  - Rules built on them do not beat buy-and-hold in large US stocks, or in
    technology portfolios since 2003 (A-negative ↓).
  - Break of structure and change of character are untested (C).
- **Applicability at 1-20 days to large and mid-cap tech: low.**
  - The repo's level and bounce results say the same.
  - DC is still the cleanest way to *define* swing points for a study: it is
    volatility-scaled, has no look-ahead, and closes-only confirmation
    matches practitioner practice.
  - Use it for definitions and state features, not as a rule expected to pay.

---

## 3. Trend turning points and momentum (topic 2)

### 3.1 Fast and slow momentum disagreement

**[Goulding-Harvey-Mazzoleni 2023](https://www.sciencedirect.com/science/article/abs/pii/S0304405X23001034)
(JFE).**

- **Signals.** Slow = sign of the 12-month return. Fast = sign of the 1-month
  return.
- **States.** Bull (+,+), Correction (+,−), Bear (−,−), Rebound (−,+).
- **US 1969-2018** (working paper version, whose numbers match the published
  contributions):

  | State | Share of months | Next-month mean, annualized | Volatility |
  |---|---|---|---|
  | Bull | 48.3% | 9.5% | 11.3% |
  | Correction | 24.5% | 6.5% | 17.8% |
  | Bear | 16.7% | −7.7% | 20.8% |
  | Rebound | 10.5% | 9.6% | 17.3% |

  "Five of the 10 worst months" followed Corrections
  ([working paper](https://www.toptradersunplugged.com/wp-content/uploads/2021/12/Momentum-Turning-Points.pdf)).
- **Strategies.** The published version gives Sharpe ratios of 0.38 for SLOW,
  0.34 for FAST and 0.48 for the 50/50 MED blend. The intermediate speed is
  better in all 20 international markets tested. About two thirds of the
  alpha is market timing and one third volatility timing
  ([published PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P158_Momentum_turning_points.pdf)).
- **Scope.** The paper is explicitly about single-asset index time-series
  momentum. It does not analyze individual stocks (same source).
- **Costs.** Small for index futures.

**[Garg-Goulding-Harvey-Mazzoleni, "Breaking Bad Trends"](https://people.duke.edu/~charvey/Research/Published_Papers/P167_Breaking_bad_trends.pdf)
(FAJ 2024).**

- **Sample.** 43 futures (11 equity indices, 8 bonds, 24 commodities),
  1990-2022.
- **Turning points hurt static trend.** One more standard deviation of
  turning points (+0.47 a year) goes with about 8.9 points lower annual
  return for 12-month time-series momentum at 10% volatility.
- **Dynamic blending.** It earned 3.4% a year against 0.3% on 2009-2019, with
  turnover of 399% against 229%. It stays ahead for costs below 29 bp.

**Reading for this book.**

- A "Correction" state in an A name (12-1 up, last month down) is the
  operator's "A in a pullback".
- At the index level the next month is still positive on average, but with
  a fatter left tail. That argues for *sizing*, such as a partial entry, more
  than for waiting.
- The transfer to single stocks is untested.

### 3.2 Time-series momentum in single stocks

- **Futures.**
  [Moskowitz-Ooi-Pedersen 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf)
  use 58 instruments, a 12-month lookback and a 1-month hold. Returns are
  positively predictable for 1-12 months and partly reverse after that. The
  diversified Sharpe ratio is above 1, and all equity index futures show
  it.
- **Single US stocks.**
  [Lim-Wang-Yao 2018](https://eprints.lancs.ac.uk/id/eprint/128366/1/Time_Series_Momentum_in_Nearly_100_Years_of_Stock_Returns.pdf)
  (JBF) use months t−12 to t−2 and a 1-month hold.
  - It earns 0.76% a month value-weighted (t 3.35), and 1.09% in large caps.
  - It is 0.63% net of turnover costs.
  - It fell to 0.55% on 1996-2017 (t 1.76).
  - 3-month formation periods are weak (0.25-0.30%).
- **Horizon.** The persistence is monthly. At 1-20 days, own-return trends in
  large caps are dominated by short-term momentum or reversal effects (§5.2).

### 3.3 Trend factor and moving averages

- **[Han-Zhou-Zhu 2016](https://www.sciencedirect.com/science/article/abs/pii/S0304405X16301271)
  (abstract only).**
  - Moving averages from 3 to 1,000 days combined into one trend factor
    earn 1.63% a month (monthly Sharpe 0.47) on 1930-2014.
  - That compares with 0.79% for short-term reversal, 0.79% for momentum
    and 0.34% for long-term reversal.
  - It earned +0.75% a month in 2007-2009, against −3.88% for momentum.
  - It is a cross-sectional, monthly factor.
- **[Levine-Pedersen 2016](https://research.cbs.dk/en/publications/which-trend-is-your-friend/).**
  Time-series momentum and moving-average crossovers "are equivalent
  representations in their most general forms". Choosing between them is
  choosing a weighting of past returns.
- **[Zakamulin-Giner 2020](https://ideas.repec.org/a/taf/quantf/v20y2020i6p985-1007.html).**
  Moving-average rules give "more robust forecast accuracy" than momentum
  rules. The two are more similar the stronger the trend.
- **[Zakamulin 2014](https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html)
  (abstract only).** With out-of-sample choice and real frictions, the
  performance of moving-average and momentum timing "is highly overstated".
  - The anatomy paper finds on the S&P 1857-2014 a median Sharpe of 0.53
    for robust moving-average rules against 0.38 passive
    ([SSRN 2585056](https://smallake.kr/wp-content/uploads/2016/04/SSRN-id2585056.pdf)).
  - That is index-level and monthly.
- **[Dichtl 2020](https://ideas.repec.org/a/wly/revfec/v38y2020i2p352-378.html)
  (abstract only).** Of 4,100 S&P 500 strategies under Hansen's SPA test, only
  technical under- and overreaction strategies dominate buy-and-hold, and
  only "in some simulation setups".
- **[Han-Yang-Zhou 2013](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf).**
  10-day moving-average timing of equal-weighted *portfolios* sorted by
  volatility, 1963-2009, earns 9.3-21.8% CAPM alpha a year, rising with
  volatility, with break-even costs of about 28-112 bp. There is no
  individual-stock test. Equal-weighted high-volatility portfolios carry
  small-stock autocorrelation that single large caps lack.

### 3.4 Trend following on single stocks (practitioner)

- **[Wilcox-Crittenden 2005](https://www.cis.upenn.edu/~mkearns/finread/trend.pdf).**
  - 24,000+ US securities including delisted ones, 1983-2004.
  - Entry on a close at an all-time high; exit on a **10-ATR** trailing stop;
    0.5% round-trip cost.
  - Win rate 49.3%, winner/loser ratio 2.56, **average hold 305 calendar
    days**.
  - The 1991-2004 portfolio earned 19.3% against 12.0% for the S&P, with a
    maximum drawdown of −20.8% against −44.7%.
- **[Zarattini-Pagani-Wilcox 2025](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5084316)**
  (SSRN).
  - 66,000+ trades, 1950-2024.
  - "Less than 7% of trades" produce the cumulative profit.
  - CAGR 15.19% and alpha 6.18% on 1991-2024.

What single-stock trend following that works looks like: very wide stops and
holds of about a year, with the profit in a few right-tail winners. A
structure exit on daily swings, a few ATR from the price, truncates exactly
that tail.

### 3.5 Whipsaws and how long a turn takes to confirm

| Mechanism | Confirmation lag | Source |
|---|---|---|
| 5-bar fractal | 2 bars after the extreme, by construction | definition |
| Moving average of n sessions | (n−1)/2 sessions behind the price | centre of mass; [Zakamulin](https://smallake.kr/wp-content/uploads/2016/04/SSRN-id2585056.pdf) on the lag/whipsaw trade-off |
| DC at θ = 3σ (about 9% here) | a 9% move from the extreme; under a random walk the expected further move equals θ | §1.4; [Glattfelder et al.](https://ar5iv.arxiv.org/html/0809.1040) |
| Statistical jump model on the S&P 500 | median 25 calendar days | [Shu-Yu-Mulvey](https://arxiv.org/html/2402.05272v2) |
| Fast momentum state | 1 month | [GHM](https://people.duke.edu/~charvey/Research/Published_Papers/P158_Momentum_turning_points.pdf) |
| Repo: intraday confirmations | 1-3 bars; every one worse than the open | `intraday-timing-2026-09-15.md` |

- **Whipsaw cost.** On these names a symmetric DC exit at 3σ fires about 14
  times a name a year under a random walk, costing about 4.5% a year in
  round trips at 16 bp a side. At 5σ it is about 5 times and 1.6% a year.
  Either way the rule sits out about half the time (§1.4, calculation).
- **Stop-losses.** "Under random walk conditions, stop-loss rules decrease
  expected returns". They can add value only "in the presence of momentum"
  ([Kaminski-Lo](https://ideas.repec.org/p/hhs/sifrwp/0063.html), abstract
  only; their empirical case is a stock-to-bond switch).

### 3.6 Path quality

**[Da-Gurun-Warachka 2014](https://academicweb.nd.edu/~zda/Frog.pdf) ("frog
in the pan").**

- **Definition.** Information discreteness ID = sgn(past return) × (%negative
  days − %positive days).
- **Result.** Momentum falls from 5.94% (continuous paths) to −2.07%
  (discrete paths) over 6 months. The spread is 8.01 points (t 8.54), and
  about 4.92 points among large caps, on 1927-2007.
- **Link to structure.** A steady staircase of higher highs and higher lows
  persists more than a jumpy one. This is monthly and cross-sectional, but it
  is the best-supported "structure quality" measure I found. It belongs in
  the feature set of any model (C8).

### 3.7 Verdict on turning points

- **Claim.** Detecting a trend turn early improves entries and exits.
- **Evidence.**
  - At the index level, fast/slow disagreement is informative and blending
    speeds helps (A, monthly, futures and indices).
  - Single-stock time-series momentum exists at 12 months and is decaying
    (B↓).
  - Crossover and moving-average timing on single US stocks is rarely
    profitable since 1990 (A-negative).
  - Stock trend following that works uses wide stops and long holds (C).
- **At 1-20 days in large tech: low.** A turn is confirmed only after the
  move a swing trader wants. Whipsaw costs and time out of the market are
  large for 3%-a-day names. The only cheap use is to *size* entries by state
  (C3) or to condition other rules on it.

---

## 4. Change-point and regime detection (topic 3)

### 4.1 CUSUM

- **Filter rules are CUSUM.**
  [Lam-Yam 1997](https://link.springer.com/article/10.1023/A:1009604804110)
  (abstract only) show that "the familiar filter trading strategy … is … a
  particular case of CUSUM procedures". No out-of-sample equity trading
  evidence is in the abstract.
- **López de Prado's symmetric CUSUM filter** is an *event sampler*: sample a
  bar when the cumulative deviation passes h, then reset. It is not a
  forecast ([AFML snippet 2.4, via mlfinpy](https://mlfinpy.readthedocs.io/en/latest/Filtering.html)).
  The standard recursion is S⁺_t = max(0, S⁺_{t−1} + r_t − E[r]) and
  S⁻_t = min(0, S⁻_{t−1} + r_t − E[r]), with an event when S⁺ > h or
  S⁻ < −h.
- **Use here.** To define *events*, such as "a name moved 2σ20 since the last
  event", on which a model is trained. It is not a timing rule in itself.

### 4.2 Bayesian online change points and CPD in deep momentum

- **[Adams-MacKay 2007](https://arxiv.org/abs/0710.3742).** The algorithm
  computes online the posterior over the time since the last change point.
  It is a method paper, with no trading evidence.
- **[Wood-Roberts-Zohren 2022](https://arxiv.org/abs/2105.13727).**
  - An online change-point module (Gaussian-process based, not the
    Adams-MacKay algorithm) is inserted into a deep momentum LSTM.
  - Over 1995-2020 the Sharpe ratio rose by "one-third", and by about
    "two-thirds" in 2015-2020.
  - The sample is 50 futures.
- **[Momentum Transformer, Wood et al.](https://arxiv.org/abs/2112.08534).**
  It beats time-series momentum and mean-reversion baselines, "maintains
  profitability after accounting for transaction" costs, and held up in
  COVID. Futures.
- **Evidence for single stocks.** A search for Bayesian online change-point
  trading on equities with out-of-sample, after-cost evaluation found no
  credible result, only method notes and a 2025 conference paper.

### 4.3 Hidden Markov, Markov switching and jump models

- **[Maheu-McCurdy-Song 2012](https://ideas.repec.org/p/tor/tecipa/tecipa-402.html)
  (abstract only).** Four index regimes: bull, bull correction, bear, bear
  rally. Its economic example is Value-at-Risk, not trading returns.
- **[Kirby 2023](https://www.sciencedirect.com/science/article/abs/pii/S1544612322005463)
  (FRL).** Markov-switching bull/bear models show "no evidence that these
  models predict market returns". The regime means differ because negative
  skewness needs them to, "regardless of whether there is any actual
  variation in conditional expected returns". The regime label is a
  description, not a forecast.
- **[Bulla et al. 2011](https://mpra.ub.uni-muenchen.de/21154/) (abstract
  only).**
  - US, Japanese and German indices, about 40 years of daily data.
  - The rule cuts exposure in the high-volatility regime and is profitable
    out of sample after costs.
  - Volatility falls 41% on average; excess return is 18.5-201.6 bp a year.
  - The gain is mostly risk reduction.
- **[Shu-Yu-Mulvey 2024](https://arxiv.org/html/2402.05272v2).**
  - **Model.** A statistical jump model with features downside deviation
    (half-life 10) and Sortino (half-lives 20 and 60). The jump penalty is
    chosen by time-series cross-validation on performance.
  - **Out of sample, S&P 500 1990-2023, 10 bp costs, one-day delay:**

    | Strategy | Return | Volatility | Sharpe | Max drawdown |
    |---|---|---|---|---|
    | Buy-and-hold | 10.2% | 18.2% | 0.48 | −55.2% |
    | HMM | 8.5% | 11.3% | 0.54 | −28.9% |
    | Jump model | 11.2% | 13.1% | 0.68 | −26.6% |

  - About 0.5 regime shifts a year against 2.0 for the HMM.
  - **Median detection lag: 25 calendar days.**
- **HMMs on tech stocks** ([Nguyen 2017](https://ideas.repec.org/a/gam/jrisks/v5y2017i4p62-d120204.html)
  on AAPL, GOOG and FB; [Nguyen 2018](https://ideas.repec.org/a/gam/jijfss/v6y2018i2p36-d138097.html)
  on S&P monthly; MDPI).
  - Two-state HMMs beat a *naïve* forecast on three stocks.
  - No costs, no multiple-testing control, a weak benchmark.
  - Not evidence.

### 4.4 Verdict on change points and regimes

- **Claim.** Regime and change-point models detect bull and bear states well
  enough to time trades.
- **Evidence.**
  - At the index level, persistent-state models (jump models) reduce
    drawdown and raise the Sharpe ratio out of sample after costs (A−/B).
    Their lag is weeks, and their gain comes from avoiding long bear markets.
  - Markov-switching bull/bear means are not return forecasts (Kirby).
  - Change-point modules help deep trend models on futures (B).
  - Single stocks: nothing credible.
- **At 1-20 days in large tech: low.**
  - A 25-day median lag is longer than most pullbacks in these names.
  - Repo: the book's next 20 sessions were *better* after benchmark trend
    breaks (§1.5).
  - A sector-level gate (C7) is the only form worth testing, and its prior
    is poor.

---

## 5. Pullbacks, the 52-week high and falling knives (topic 4)

### 5.1 The 52-week high: anchoring and continuation

- **[George-Hwang 2004](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf).**
  - 1963-2001; top 30% against bottom 30% by price over the 52-week high;
    6-month hold.
  - 0.45% a month raw (1.23% excluding January); 0.86% risk-adjusted.
  - This beats Jegadeesh-Titman and industry momentum, and "future returns
    forecast using the 52-week high do not reverse in the long run"
    ([abstract](https://ideas.repec.org/a/bla/jfinan/v59y2004i5p2145-2176.html)).
- **[Bhootra-Hur 2013](https://ideas.repec.org/a/eee/jbfina/v37y2013i10p3773-3782.html).**
  Stocks with a *recent* 52-week high beat those with a distant one by 0.70% a
  month. Recency roughly doubles the 52-week-high strategy's return.
- **[Huddart-Lang-Yetman 2009](https://pure.psu.edu/en/publications/volume-and-price-patterns-around-a-stocks-52-week-highs-and-lows-/)
  (abstract only).** Volume spikes when the price crosses the upper or lower
  limit of its past range. "After either event, returns are reliably
  positive".
- **[Della Vedova-Grant-Westerholm 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1)
  (abstract only).** Households sell into the 52-week high with limit orders.
  That uninformed selling "leads to a doubling of unconditional 52WH anomaly
  returns".
- **[Chen-Stivers-Sun 2024](https://www.sciencedirect.com/science/article/abs/pii/S0927539824000902)
  (abstract only).** The one-month reversal fades as turnover and price
  relative to the 52-week high rise. It turns into momentum for stocks that
  have both high turnover and a price near the 52-week high.

**Reading.** A-grade semis near their highs, with heavy turnover, are the
stocks for which the literature expects *continuation*, not a dip-and-rebound.
That matches the repo's stage-3 finding inside the A/A+ book (§1.5).

### 5.2 One-month reversal against one-month momentum in large caps

- **[Medhat-Schmeling 2022](https://openaccess.city.ac.uk/id/eprint/31278/1/MS_short_term_mom_v27.pdf)
  (RFS), 1963-2018.**
  - In the top turnover decile, short-term momentum earns +1.37% a month
    (t 4.74). Low-turnover stocks reverse: −1.41% (t −7.13).
  - Among the **largest 500 stocks**, short-term momentum earns **0.42% a
    month (t 4.91)** and reversal −0.02% (t −0.19). Megacaps earn 0.53%.
  - The strategy nets 1.00% a month (t 3.47) after costs.
  - It holds in 22 developed markets and persists for 12 months.
- **[Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf),
  1982-2009.**
  - Standard reversal alpha is 0.33% a month (t 1.37).
  - "Residual" reversal is 1.34% (t 9.28). It removes expected returns,
    cash-flow news (analyst revisions) and the industry.
  - The profit is in month 1 (1.57%), 0.40% in month 2 and about 0 by month
    5. It is about 0.54% a month after roughly 80 bp of monthly costs.
  - Losers' reversals load on liquidity; winners' reversals load on
    sentiment.
- **[de Groot-Huij-Zhou 2012](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf),
  1990-2009, weekly reversal with low-turnover construction.**
  - Top 100 US stocks: 77.9 bp a week gross, 53.1 net.
  - Top 500: 65.0 gross, 30.5 net.
  - Top 1,500: −17.6 net.
  - These are *decile long-short* spreads, not single-order timing gains.
- **Decay.**
  - [Khandani-Lo](https://www.nber.org/system/files/working_papers/w14465/w14465.pdf):
    the daily contrarian strategy's profits fell from 1995 to 2007. Every
    year from 2002 on is below the sample average.
  - [Dai-Medhat-Novy-Marx-Rizova 2023](https://www.nber.org/papers/w30917):
    higher volatility means "faster, initially stronger reversals"; lower
    turnover means "more persistent, ultimately stronger reversals".
  - Their practitioner summary adds that for high-volatility, high-turnover
    stocks reversals last "a few weeks at most". Average reversal returns
    "have declined over the past 20 years", and reversal screens are best
    folded into rebalancing trades rather than traded alone
    ([Dimensional Q&A](https://www.dimensional.com/ie-en/insights/q-and-a-on-short-run-reversals-with-mamdouh-medhat-and-robert-novy-marx)).
- **[Gong-Liu-Liu 2015](https://www.sciencedirect.com/science/article/abs/pii/S0378426614003252)
  (abstract only).** With months t−2 and t−12 excluded, recent-past and
  intermediate-past momentum predict equally well, in the US and 26 markets.

### 5.3 After a large decline: continuation or reversal?

| Study | Event and sample | Finding | Large caps? |
|---|---|---|---|
| [Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf) (JFE) | Daily abnormal return beyond ±10% (four-factor), 1993/11-2009; 5 or more analyst reports in the prior year | With an analyst report (information) the price drifts; without one it reverses over 20 trading days. Long no-information losers against short winners earns 20% a year (Sharpe 1.66); the information strategy 16% (Sharpe 1.21). | Robust after excluding stocks under $5 and the NYSE bottom decile |
| [Chan 2003](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf) (2001 working paper; JFE 2003) | Monthly movers with and without headlines, 1980-1999, about 1,557 random CRSP stocks | News losers drift down for months, most after bad news. No-news extremes reverse in the next month. My extraction reports that value-weighted, "the difference between news and no-news winner and loser returns is virtually zero". | Weak |
| [Cox-Peterson 1994](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p255-67.html) (abstract only) | Large one-day declines | Short-term reversals are explained by bid-ask bounce and liquidity, "not … overreaction". The decliners "perform poorly over an extended time horizon". | The falling knife keeps falling over months |
| [Bremer-Sweeney 1991](https://ideas.repec.org/a/bla/jfinan/v46y1991i2p747-54.html) (abstract only) | Extremely large negative returns in large firms | A positive adjustment lasts "approximately two days" | Short |
| [Park 1995](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/market-microstructure-explanation-for-predictable-variations-in-stock-returns-following-large-price-changes/D98180CB28103AEEE8D5C439FEC0DE20) (abstract only) | Large price changes, on bid-ask midpoints | The day-1 reversal disappears. Later short-run reversals remain but "are not large enough to cover" the spread. | No, after costs |
| [Hendershott-Menkveld 2014](http://faculty.haas.berkeley.edu/hender/price_pressures.pdf) | NYSE specialist inventory, 697 stocks, 1994-2005 | Price pressure averages 49 bp with a half-life of 0.92 days; in the largest quintile it is 17 bp with a half-life of 0.54 days. | Non-information dips in large caps are gone within about a day |
| [Hameed-Kang-Viswanathan 2010](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/lEJ6N1370226075.pdf) | Weekly contrarian returns by market state | 1.18% a week (t 3.01) after large market declines, against 0.52-0.64% otherwise. Limit-order buyers earn 1.56%. | State dependence |
| [Nagel 2012](https://www.nber.org/papers/w17653) (abstract only) | Reversal as the return to liquidity provision | "Strongly time-varying and highly predictable with the VIX" | State dependence |
| [Cooper-Gutierrez-Hameed 2004](https://www.semanticscholar.org/paper/Market-States-and-Momentum-Gutierrez-Cooper/85b2db4ae48f1adf668080906ea1599ab7069c9a) (abstract only) | Momentum by market state, 1929-1995 | 0.93% a month after up markets, −0.37% after down markets | Trends persist in up markets |
| [So-Wang 2014](https://dspace.mit.edu/handle/1721.1/119665) (abstract only) | Reversals around earnings | A "six-fold increase in short-term return reversals during earnings announcements" | Event dependence |
| [Coval-Stafford 2007](https://ideas.repec.org/a/eee/jfinec/v86y2007i2p479-512.html) (abstract only) | Mutual-fund fire sales, 1980-2003 | Trading against forced flows "earn[s] highly significant returns" | Mechanism for non-information dips |
| [Cheng-Hameed-Subrahmanyam-Titman 2017](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/shortterm-reversals-the-effects-of-past-returns-and-institutional-exits/7B9F21C81D419D4C51430E2CC376A649) (abstract only) | Monthly reversal conditional on the past quarter | "Price declines over the previous quarter lead to stronger reversals across the subsequent 2 months" | Cuts against waiting on deep losers |

### 5.4 Who earns the dip, and over what horizon

- **Retail buyers of dips.**
  - Individuals buy after declines and earn positive excess returns the
    next month ([Kaniel-Saar-Titman 2008](https://ideas.repec.org/a/bla/jfinan/v63y2008i1p273-310.html),
    abstract only).
  - Barrot-Kaniel-Sraer (2002-2010) measure 15 bp a week, peaking about 16
    trading days after the imbalance and back to zero by day 80. It is
    nearly double when VIX is high
    ([Barrot-Kaniel-Sraer](https://faculty.haas.berkeley.edu/dsraer/Barrot_Kaniel_Sraer.pdf)).
  - **Retail does not capture it:** −90 bp on the day of the trade, and an
    average hold of 310 days (median 40) against a premium that is gone in
    about 20 days (same source).
- **Institutional practice** (Dimensional, practitioner, C). "Buys can be
  delayed on securities that exhibit downward momentum until that effect has
  dissipated. Conversely, sales can be delayed for securities exhibiting
  upward momentum", with no added turnover
  ([Dimensional](https://www.dimensional.com/sg-en/insights/myth-busting-with-momentum-how-to-pursue-the-premium)).
  This is grade-gated timing in production: a slow model decides what, and
  a momentum screen decides when. **The screen delays buying falling names;
  it does not buy the dip.**
- **Cost mitigation.** A buy/hold spread, with stricter requirements for
  opening than for keeping a position, is the most effective cost
  mitigation for anomalies
  ([Novy-Marx-Velikov 2016](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p104-147..html),
  abstract only). This is the grade book's own hysteresis.

### 5.5 "Buy the dip" as a strategy

- **[AQR "Hold the Dip" 2025](https://www.aqr.com/-/media/AQR/Documents/Alternative-Thinking/AQR-Alternative-Thinking---Hold-the-Dip.pdf?sc_lang=en)**
  (practitioner, well documented).
  - 196 buy-the-dip variants on the S&P 500, 1965-2025: dips of 5-20%,
    lookbacks of 1 week to 1 year, holds of 1 month to 5 years.
  - The average Sharpe ratio was **0.04 lower** than passive, and **0.27
    lower since 1989**. Over 60% of variants underperformed. Only 16 of 196
    had significant alpha.
  - On the **Magnificent 7 (2012-2025)** buying the dip "remains inferior to
    buy-and-hold even among high-growth stocks".
  - Summary: [Alpha Architect](https://alphaarchitect.com/is-trend-following-better-than-buy-the-dip/).
- **Bonini-Shohfi-Simaan (EFM 2024)** found "no reliable outperformance" for
  buy-the-dip. This is summary only, via
  [Evidence Investor](https://www.evidenceinvestor.com/post/buy-the-dip);
  the [publisher page](https://onlinelibrary.wiley.com/doi/10.1111/eufm.12465)
  returned 403.

AQR's strategies wait in cash for the dip, which is the §1.2 drag. The
lesson for this book: waiting for a dip before owning a name the grade wants
is costly unless the capital stays invested.

### 5.6 Analysts, grades and the direction of the dip

- **[Womack 1996](https://ideas.repec.org/a/bla/jfinan/v51y1996i1p137-67.html)
  (abstract only).** After new broker buy recommendations the drift is
  "modest and brief (+2.4 percent)". After sell recommendations it is
  "−9.1 percent", persisting for six months. For this book: sell downgrades
  promptly, and do not wait long for a pop.
- **Jegadeesh-Kim-Krische-Lee 2004** (summary only, via
  [paperswithbacktest](https://paperswithbacktest.com/strategies/analyzing-the-analysts-when-do-recommendations-add-value)).
  - Consensus recommendation levels add value only for stocks with
    favourable quantitative traits: value and positive momentum.
  - For unfavourable stocks, higher recommendations go with worse returns.
  - An A grade on a name whose trend has broken is the least reliable A.
    The grade already includes trend, so this is mostly priced in.

### 5.7 Verdict on "buy A on dips, sell lower grades on pops"

**Supported, with limits.**

- **Market-wide stress.** In liquidity events (high VIX, large market
  declines), dips in quality names revert, and waiting is costly (A). The
  right action is *buy now* (Nagel; Hameed-Kang-Viswanathan; Coval-Stafford).
  Repo: the book did better after benchmark breaks.
- **Non-information, name-level dips** revert (A for the mechanism). In the
  largest stocks they revert within about a day, so a *multi-day* rule has
  nothing left to capture.

**Not supported.**

- **Calm, name-specific pullbacks in high-turnover names near their highs.**
  The one-month pattern there is momentum (A). The evidence-based action is
  the reverse of "buy the dip": delay the buy briefly until the fall stops,
  and never skip (Dimensional). The repo's stage-3 result inside the A book
  agrees.
- **Information-driven drops**, such as a downgrade, an earnings gap or a
  guide-down, drift (A mechanism). For large caps the value-weighted effect
  is small (B).

**On the sell side.**

- Sell downgrades promptly (Womack).
- Delay only while a name still has upward short-term momentum (Dimensional,
  C), and only for a few sessions.

**Applicability at 1-20 days to large and mid-cap tech: moderate for the
direction of effects, low for their size.**

---

## 6. ML for turning points (topic 5)

### 6.1 Chart CNNs: Jiang-Kelly-Xiu and what came after

- **[JKX 2023](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf) (JF).**
  - **Design.** Trained and validated on 1993-2000, then held fixed for
    2001-2019.
  - **Long-short Sharpe ratios:**

    | Images / horizon | Equal-weight | Value-weight |
    |---|---|---|
    | 5-day images, 5-day returns | 7.15 | 1.49 |
    | 20-day images, 20-day returns | 2.16 | 0.49 |

  - **What it learned.** "When a stock closes on the low end of its recent
    high-low range, future returns tend to be high". Turnover is "nearly
    identical" to the weekly short-term reversal strategy, and there is no
    cost deduction.
  - The feature-research memo quotes 6.75 for the 5-day equal-weight
    Sharpe; the two figures appear to come from different tables or
    versions.
- **[Dixon-Zeng 2024](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/925943/CNN-Draft-July-2024.pdf)
  (working paper).**
  - Four geometric variables (weekly short-term reversal, last close's
    position in the range, its last-day change, and relative last-day
    volume) explain 31% of the weekly CNN predictions and **73% of weekly
    CNN portfolio returns**.
  - Equal-weight earns 80% a year (Sharpe 7.18) against 23% value-weight
    (Sharpe 1.57), "likely from small firms".
  - Performance falls from the 5-day to the 60-day horizon.
- **[Byun-Na-Song 2026](https://www.sciencedirect.com/science/article/abs/pii/S1544612326001169)
  (FRL, abstract only).** A vision transformer factor on candlestick images
  is priced across firm sizes. The CNN factor "shows weaker performance,
  particularly for large-cap stocks".
- **[Jeong-Byun-Kim 2026](https://www.sciencedirect.com/science/article/abs/pii/S0275531925004878)
  (abstract only).** Chart CNNs in Korea beat benchmarks, "particularly for
  short-term forecasting".
- **[Murray-Xia-Xiao 2024](https://ideas.repec.org/a/eee/jfinec/v153y2024ics0304405x2400014x.html)
  (JFE, abstract only).** ML on past returns predicts the cross-section,
  "strong among the largest 500 stocks", with nonlinearities distinct from
  momentum and reversal. It is monthly and about selection, not timing.
- **Repo.**
  - The JKX replica, which departed from the recipe, scored IC −0.001 at 20
    sessions (feature-research §0.1).
  - The faithful stage-3 5-day and 20-day CNN overlays gave −0.4 and −0.2
    bp a session.
  - The 20-day CNN found a laggard only on 2024-2026 (stage-3 results).

### 6.2 Classifiers of trend reversal and turning points

- **[Sezer-Ozbayoglu 2018](https://www.sciencedirect.com/science/article/abs/pii/S1568494618302151)
  (CNN-TA).**
  - 15 × 15 images of technical indicators, labelled Buy, Sell or Hold from
    the "hills and valleys" of an 11-day window: a turning-point label
    ([README](https://github.com/omerbsezer/CNN-TA/blob/master/README.md)).
  - Dow 30 stocks with 5-year rolling training.
  - Reported 12.6% a year against 10.5% for buy-and-hold, with no stated
    costs, a 71% win rate and cash more than half the time. A practitioner
    review calls the results "simply too good" and flags overfitting and
    label-rate imbalance
    ([ENJINE](https://www.enjine.com/blog/paper-review-algorithmic-financial-trading-with-deep-convolutional-neural-networks-time-series-to-image-conversion-approach/)).
- **[Velay-Daniel 2018](https://arxiv.org/abs/1808.00418).** CNN and LSTM
  *recognize* two chart patterns. Only accuracy is reported.
- **[Song 2024](https://www.sciencedirect.com/science/article/pii/S2405844024001671)
  (Heliyon).** A neural net for upward reversals after crashes, on KOSDAQ,
  tested on 2018-2020 with three crash episodes. Profit per trade was
  11.7-18.1%, with no costs and three events.
- **Piecewise-linear turning-point literature** (for example
  [Chang et al. 2009, IEEE SMC-C](https://dl.acm.org/doi/10.1109/TSMCC.2008.2007255),
  seen in search, not opened). Turning points are labelled from
  piecewise-linear segmentation of the *whole* series, and small samples are
  common. I did not rely on it.
- **[Buchanan-Benhamou 2026](https://arxiv.org/html/2603.14453v1)
  (arXiv).**
  - An LSTM on the 30 largest S&P 500 names, 2005-2025, next-day horizon,
    2 bp round-trip costs.
  - Directional accuracy rose from 56% to 62%.
  - Portfolio P&L went from −2.15 to 0.28 in their units: barely positive.
- **[Fischer-Krauss 2018](https://www.sciencedirect.com/science/article/abs/pii/S0377221717310652).**
  An LSTM on S&P 500 constituents, 1992-2015, earned 0.46% a day before
  costs (Sharpe 5.8). "As of 2010, excess returns seem to have been
  arbitraged away … fluctuating around zero after transaction costs" at 5 bp
  a half-turn. A simple reversal rule captured about half of the LSTM's
  gross return.
- **[Brogaard-Zareei 2023](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/machine-learning-and-the-stock-market/F54ECC9DA40067B35261B32691D1DDA2)
  (JFQA, abstract only).** ML finds profitable technical rules out of
  sample, but "this out-of-sample profitability decreases through time".

### 6.3 Sequence models with change points (trend following)

- Deep momentum networks with online change-point detection
  ([Wood-Roberts-Zohren 2022](https://arxiv.org/abs/2105.13727)) and the
  Momentum Transformer ([Wood et al.](https://arxiv.org/abs/2112.08534)) are
  the best-documented "learn the turn" results.
- Both are on futures portfolios with a slow-trend base.
- They teach the architecture: trend state plus change-point severity as
  inputs, Sharpe-optimized.
- They are not evidence for 1-20 day single-stock timing.

### 6.4 Labels: triple barrier, trend scanning, meta-labeling

- **Triple-barrier labels.** An upper profit-taking barrier and a lower
  stop-loss barrier, both set in multiples of recent volatility, plus a
  vertical time barrier. The label is whichever is hit first
  ([AFML ch. 3, via mlfinpy](https://mlfinpy.readthedocs.io/en/latest/Labelling.html)).
- **Trend-scanning labels.** Fit forward regressions over windows up to L and
  take the window with the largest |t| of the slope. The label is its sign,
  or 0 below a t threshold
  ([mlfinlab docs](https://random-docs.readthedocs.io/en/latest/implementations/labeling_trend_scanning.html)).
- **Meta-labeling.** A primary model proposes the side; a secondary binary
  model decides whether to take the bet and how large
  ([mlfinpy](https://mlfinpy.readthedocs.io/en/latest/Labelling.html);
  [Wikipedia](https://en.wikipedia.org/wiki/Meta-Labeling)). **The grade is
  the natural primary model here.**
- **Evidence on meta-labeling.**
  - **Wikipedia's summary.** The published improvements come from "synthetic
    data and simulated trading environments", in Joubert 2022 (JFDS) and
    Meyer-Barziy-Joubert 2023 (JFDS). The JFDS page blocked access.
  - **Hudson & Thames (practitioner).** On E-mini S&P futures, meta-labeling
    raised the precision of a 20/50 moving-average trend rule from 0.48 to
    0.54, and of a Bollinger rule from 0.17 to 0.20, with **no transaction
    costs**
    ([blog](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/)).
  - **A Lund bachelor's thesis** (weak) on an S&P 500 market-neutral
    strategy found meta-labeling did *not* improve on a non-meta model
    ([thesis](https://lup.lub.lu.se/student-papers/record/9120301/file/9120304.pdf)).
  - I found no peer-reviewed, out-of-sample, after-cost meta-labeling result
    on equities.
- **Timing with short-horizon ML after costs.**
  - One-month ML alpha was "mainly profitable before 2004"; 3-12 month models
    stayed net positive
    ([Blitz et al., via Robeco](https://www.robeco.com/en-int/insights/2023/07/the-term-structure-of-machine-learning-alpha)).
  - Deep-learning profits come from "difficult-to-arbitrage stocks"
    ([Avramov-Cheng-Metzker 2023](https://econpapers.repec.org/RePEc:inm:ormnsc:v:69:y:2023:i:5:p:2587-2619),
    abstract only).
  - Ignoring costs leads models to "fleeting small-scale characteristics"
    ([Jensen-Kelly-Malamud-Pedersen](https://research.cbs.dk/en/publications/9a2926d9-858b-449d-b658-8f204cac58bb),
    abstract only).

**The favourable point for this book.** *Re-timing orders the grade already
requires adds no turnover*. The usual cost objection to short-horizon ML
largely falls away. Only the signal problem remains.

### 6.5 Verdict: can a CNN detect structure shifts?

**Detection is easy; prediction is the question.**

- A structure shift (a directional-change turn, a break below the last
  higher low) is a deterministic function of the price path. A 20-line rule
  detects it exactly and without error.
- A CNN can learn to recognize chart shapes (Velay-Daniel; CNN-TA).

**What a CNN could add.** It could learn *which* shifts are followed by
continuation. That is the same conditional-predictability question any model
faces, and the evidence on it is:

- **JKX-type CNNs.** What they learn is mostly short-horizon reversal and
  close location, concentrated in small stocks (A for that description).
  Value-weighted they are weak, and CNN factors are weaker in large caps
  (B).
- **Turning-point CNN and LSTM papers.** They report accuracy or cost-free
  backtests on small samples (C).
- **The repo.** Faithful CNN runs on this book recorded zero or negative.

**The honest answer.**

- No credible evidence says a CNN detects *tradeable* structure shifts in
  large-cap tech at 1-20 days.
- Test it once, in decision units (C9), with a low prior.
- The sequence model's post-hoc laggard (stage 3) is a *selection* lead, not
  a timing one.

---

## 7. Multi-timeframe confirmation (topic 6)

- **Combining horizons helps at monthly frequency.**
  - The trend factor draws on moving averages from 3 to 1,000 days
    ([Han-Zhou-Zhu](https://www.sciencedirect.com/science/article/abs/pii/S0304405X16301271)).
  - Blending 1-month and 12-month signals raises the Sharpe ratio from
    0.38/0.34 to 0.48
    ([GHM](https://people.duke.edu/~charvey/Research/Published_Papers/P158_Momentum_turning_points.pdf)).
  - Dynamic blending beats static 12-month trend when costs are under 29 bp
    ([Garg et al.](https://people.duke.edu/~charvey/Research/Published_Papers/P167_Breaking_bad_trends.pdf)).
  - Trend signals are linear filters over horizons, so "multi-timeframe" is a
    weighting choice
    ([Levine-Pedersen](https://research.cbs.dk/en/publications/which-trend-is-your-friend/)).
- **"Weekly trend, daily trigger" as a rule.** Elder's triple screen and
  similar schemes appear in practitioner guides (for example
  [takeprofitapp](https://takeprofitapp.com/en/learn/triple-screen-trading-system),
  seen in search). I found no systematic, peer-reviewed test.
- **Repo.**
  - Weekly trend up: +1.0% against −2.0% over 20 sessions (t 4.2,
    in-sample). It is already a leg of the grade (feature-research §1.15).
  - Intraday confirmation of daily reversal entries lost to the open,
    progressively more on coarser bars (§1.5).
- **Verdict.** B as features; C as rules. The weekly leg is already inside the
  grade. A daily trigger inside a weekly uptrend is the confirmation problem
  of §1.5 again. **Applicability here: low.**

---

## 8. Summary by topic

| Topic | Claim | Best evidence (numbers) | Survives costs and recent data? | Applies to large/mid tech at 1-20 days? |
|---|---|---|---|---|
| Swing structure, break of structure, change of character | Structure turns predict returns | Patterns are informative (LMW); head-and-shoulders not stand-alone profitable in the S&P 500 (SWZ); support/resistance does not beat buy-and-hold (ZT 2012); tech portfolios: no rule beats buy-and-hold on 2003-2010 (Shynkevich) | No (↓) | Low: define with it, don't expect it to pay |
| Directional change | Event time reveals turns | Scaling laws in FX, which equal the random-walk null for overshoot; FX, intraday, cost-free trading tests | Untested | Low |
| Fast/slow momentum states | Disagreement flags turning points | Index: Correction 6.5% next month (annualized), Bear −7.7%; MED Sharpe 0.48 against 0.38 | Index yes; stocks untested | Low to moderate, as a sizing state |
| Time-series momentum, stocks | Own trend persists | 0.76% a month value-weighted; 0.55% (t 1.76) on 1996-2017 | Partly (↓) | Monthly, not 1-20 days |
| Moving-average and trend timing, stocks | Crossovers time single names | Rarely profitable 1990-2004 (MQY); overstated out of sample (Zakamulin); practitioner stock trend following needs 10-ATR stops and about 300-day holds | No | Low |
| Regime detection | Bull/bear states time trades | Jump model on the S&P 500: Sharpe 0.68 against 0.48, 25-day lag; Markov-switching means do not forecast (Kirby) | Index yes | Low (lag; repo) |
| 52-week high and anchoring | Near-high names continue | 0.45-1.23% a month (GH); recency 0.70% (BH); momentum for high-turnover near-high stocks (CSS) | Monthly, B↓ | Moderate as a state, not a rule |
| Falling knife | Dips revert | Largest 500: short-term momentum +0.42% a month, reversal ≈ 0 (MS); price-pressure half-life 0.54 days (HM); reversal 1.18% a week after large market declines (HKV); information drifts (Savor) | Reversal ↓; state effects yes | Direction yes, size small |
| Buy the dip | Waiting for dips beats holding | Sharpe −0.04 (−0.27 since 1989); Magnificent 7 worse than buy-and-hold (AQR) | No | Negative |
| Chart CNNs | CNNs find turning patterns | Value-weighted Sharpe 0.49-1.49 against 2.16-7.15 equal-weighted; 73% of weekly CNN returns explained by 4 simple variables | Not after costs in large caps | Low (repo negative) |
| Meta-labeling and triple barrier | A secondary model filters a primary rule | Precision gains in practitioner and synthetic tests; a student thesis negative | Unknown | Right framing, unproven |
| Multi-timeframe | Weekly trend plus daily trigger | Horizon blends help monthly (HZZ, GHM); alignment rules untested | Monthly yes | Low |

---

## 9. Candidate rules for the Stage-4 study

### 9.1 Conventions shared by every candidate (fixed before any run)

**Events.** The grade is the primary model.

- **ENTRY:** any live-executor order (`graded-equal-weight/4` with the
  idle-cash redeploy) that raises a name's target weight by at least 2
  percentage points. That covers new A/A+ names and reset top-ups.
- **EXIT:** any order that takes a target to zero because of a downgrade
  below A.
- **TRIM:** reset cuts of at least 2 points (C5 only).
- **HELD:** A/A+ names at target (C6 only).

**Control.** The order is placed on event session s with the board's fill:
`dip_or_close` for buys and `pop_or_close` for sells.

**Candidate.** It may defer the order to session s+d, with 0 ≤ d ≤ W.

- Wait conditions use data through the close of s−1.
- Triggers are evaluated on completed daily bars. A trigger at the close of
  s+k places the order on s+k+1 with the board's fill convention.
- **Fallback:** the order is placed on s+W. **An order is never skipped.**
- **Cancellation:** a grade reversal before placement cancels the deferred
  order. The control's round trip is then counted against it.

**Parking.**

- Deferred buy capital stays in the rest of the A/A+ book, pro rata, through
  the idle-cash redeploy.
- A deferred sale stays in the name.
- Two sensitivities are reported but are not trials: parking in cash at 0%,
  and parking in QQQ.

**Costs.** 10, 16 and 25 bp a side, as in stage 3. Re-timing adds no trades;
C3's split entry is notional-neutral; C6 adds real round trips.

**Units and states** (all on daily adjusted bars):

- **σ20:** the standard deviation of the last 20 daily log close-to-close
  returns.
- **Peer residual:** the name's log return minus the point-in-time equal
  weight of eligible names.
- **Market stress M_t = 1** if any of:
  - VIX at or above its trailing 252-session 80th percentile;
  - SPY 5-session log return at or below −4%;
  - SMH 5-session log return at or below −7%.
- **Negative information shock I⁻_{i,t} = 1** if any session j in [t−4, t]
  has:
  - (a) an 8-K item 2.02 and a gap at or below −2σ20;
  - (b) a peer-residual return at or below −3σ20 on volume at least twice
    its 50-session mean;
  - (c) a stance downgrade by any of the grade's analysts
    (`decision_history`); or
  - (d) any 8-K and a peer-residual return at or below −2σ20.

  I⁺ mirrors it.
- **Directional-change structure, θ = 3σ20, frozen at the start of each
  leg:**
  - An up-turn is confirmed when C_t ≥ L·(1+θ), with L the lowest close
    since the last down-turn. A down-turn is confirmed when
    C_t ≤ H·(1−θ), with H the highest close since the last up-turn.
  - Swing points are the extremes. Up and down trends are the rising or
    falling sequences of the last two swing highs and lows.
  - A bearish break is a close below the last swing low while in an
    uptrend. A bullish change of character is a close above the last swing
    high while in a downtrend or down-leg.
  - Closes only, no wicks (§2.1).
- **Momentum state (GHM per name):**
  - slow = sign(ln C_{t−21}/C_{t−252}); fast = sign(ln C_t/C_{t−21});
  - Bull (+,+), Correction (+,−), Bear (−,−), Rebound (−,+).
- **52-week high:** R52 = C_t / the highest high of the last 252 sessions,
  and its age in sessions.
- **One-bar turn T1:** C_t > H_{t−1}.

**Readouts.**

- Paired bp a session against the control: Newey-West lag 20, 20 offsets,
  2016-2023 choosing, 2024-2026 reported.
- **Per re-timed order**, in bp, with the t clustered by date.
- The share of events deferred and the mean deferral.
- A split into price improvement and parking return.
- Every candidate is also reported by grade (A+ against A) and by M_t, as
  diagnostics, not trials.

### 9.2 The candidates

**C1: Momentum-screen entry delay, switched off in stress.** Evidence B: the
Dimensional practice (C), short-term momentum in large caps (A), and the
Nagel and Hameed-Kang-Viswanathan exemption (A).

- **Applies to:** ENTRY.
- **Wait if** all of:
  - the peer-residual 21-session return is in the bottom quintile of
    eligible names;
  - the peer-residual 5-session return is below 0;
  - M = 0.
- **Trigger:** T1, or the peer-residual 5-session return turns non-negative.
- **W = 5; fallback on s+5.**
- **Why:**
  - It delays buying a name that is falling against its peers in calm
    markets.
  - It buys immediately in stress, when dips revert.
  - It is the evidence-based version of "buy A on dips": wait for the dip to
    *stop*, never skip, and don't wait in a panic.
- **Expectation:**
  - It defers 15-25% of entries.
  - Per re-timed order about +5-25 bp.
  - For the book, at most about +0.05-0.2 bp a session.

**C2: Patience after information shocks.** Evidence: A for the mechanism
(Savor, Chan, Da-Liu-Schaumburg), B for large caps.

- **Applies to:** ENTRY with I⁻ = 1.
- **Trigger:** a confirmed directional-change up-turn (θ = 3σ20) or a bullish
  change of character.
- **W = 10; fallback on s+10.**
- **Entries without I⁻:** the control.
- **Mirror for exits:** an EXIT with I⁺ = 1 (for example, the name is
  downgraded after an earnings gap up) sells on the open of s, without
  waiting for a pop. Otherwise the control.
- **Expectation:**
  - Rare: about 10% of entries.
  - Per event about +50-150 bp if large-cap information drift exists.
  - For the book about +0.1-0.5 bp a session.

**C3: Name-level momentum states.** Evidence: A at the index level (GHM,
Garg et al.), B↓ in single stocks (Lim-Wang-Yao).

- **Applies to:** ENTRY.
- **Bull or Rebound:** the control.
- **Correction:**
  - 50% on the control schedule;
  - the other 50% at the first session back in Bull (fast ≥ 0), or at
    W = 10.
- **Bear:** wait until fast ≥ 0, W = 20, with the fallback.
- **Expectation: about 0 to negative.** A Correction in an A name is an
  ordinary pullback, and the index evidence says its next month is lower but
  still positive.

**C4: Patience with deep-drawdown names** (the falling-knife form). Evidence
B, mixed:

- far below the 52-week high means weaker momentum (George-Hwang);
- quarterly losers reverse more (Cheng et al.);
- declines keep underperforming for months (Cox-Peterson).

- **Applies to:** ENTRY with R52 ≤ 0.75 (25% or more below the 52-week high).
- **Trigger:** a confirmed directional-change up-turn (θ = 3σ20) or a bullish
  change of character.
- **W = 10; fallback.**
- **All other entries:** the control.
- **Expectation: about 0.** The report gives the near-high split
  (R52 ≥ 0.90 and age ≤ 60) as a diagnostic.

**C5: Downgrade-exit momentum screen.** Evidence: Dimensional (C),
short-term momentum (A), and Womack's post-downgrade drift, which bounds W.

- **Applies to:** EXIT and TRIM.
- **Delay if** all of:
  - the 5-session return is above 0;
  - C > EMA10;
  - I⁻ = 0.
- **Trigger:** C_t < L_{t−1} (a close below the prior session's low), or
  C < EMA10.
- **W = 5; fallback.**
- **Otherwise:** the control (`pop_or_close` on s).
- **Expectation: about 0.** It is the evidence-based form of "sell lower
  grades on pops": let a rising name run for a few sessions, and sell a
  falling one now.

**C6: Structure-break partial exit for held A names, before any downgrade**
(the operator's "breaks structure first"). Evidence against it: Kaminski-Lo,
Wilcox-Crittenden, the repo's stops and trims, and §1.4.

- **Applies to:** HELD A/A+ names.
- **Cut to 50% of target on t+1 if** all of:
  - a directional-change down-turn is confirmed at θ = **5σ20**;
  - a bearish break of structure;
  - fast < 0;
  - peer-residual 63-session return < 0.
- **Restore to target** on a directional-change up-turn (θ = 5σ20), a bullish
  change of character, or the next reset, whichever comes first.
- **Proceeds:** parked in the book. Costs are paid on both legs.
- **Expectation: −0.3 to −1.5 bp a session.**

**C7: Sector regime gate** (a statistical jump model). Evidence: Shu-Yu-Mulvey
(A−, index); against it, Kirby and the repo's cash-state results.

- **Model.**
  - A two-state jump model on the daily excess returns of SMH, and of IGV
    for software names.
  - Features: exponentially weighted downside deviation (half-life 10) and
    Sortino ratios (half-lives 20 and 60).
  - The jump penalty is chosen by time-series cross-validation on data
    before each test year.
  - The regime at the close of t acts on t+1.
- **Applies to:** ENTRY in the bear regime. Wait until the regime turns bull,
  **W = 20**, with the fallback. Exits are unchanged.
- **Expectation: negative.** The detection lag of about 25 days is longer than
  these names' pullbacks.

**C8: Meta-label model: enter now or defer 5 sessions** (LightGBM, the
stage-3 M1 protocol). Evidence: C for meta-labeling; B↓ for short-horizon ML
after 2004.

- **Primary model:** ENTRY events.
- **Training rows:** every eligible A/A+ name-session, as a pseudo-event.
- **Label, in the decision's units.** With the capital parked in the book,
  the gain from a fixed 5-session deferral is
  y = ln(B_{t+5}/B_t) − ln(C_{i,t+5}/C_{i,t}), where B is the book excluding
  i: the negative of the name's 5-session return relative to its book.
- **Auxiliary diagnostic label (triple barrier, relative to the book):**
  barriers at ±1.5·σ20·√5, vertical barrier at 5 sessions. Reported as an
  AUC only.
- **Features:**
  - the §9.1 states: directional-change state and distances in σ units,
    momentum state, R52 and its age, M, I⁻ and I⁺;
  - 5, 21 and 63-session peer residuals;
  - turnover as the 20-session over the 250-session average volume;
  - information discreteness over 60 sessions;
  - σ20 and the realized semivariance share;
  - VIX level and 5-day change; SPY, QQQ and SMH 5-day returns;
  - grade, grade age, stance count, and sessions to the next 8-K 2.02.
- **Decision.** Defer by 5 sessions if ŷ is in the bottom tercile of the
  date's predictions among eligible names; otherwise the control. Using a
  per-date tercile avoids fitting a threshold.
- **Protocol.** The stage-3 settings: an 8-configuration grid, 5 seeds, an
  expanding walk-forward, purge 5 plus embargo 5, nested validation on the
  last 252 sessions.
- **Expectation: fails.** Its value is a clean, general test of every state
  above at once.

**C9: CNN detector of structure turns** (the operator's CNN question).
Evidence: the JKX descriptions (A for what CNNs learn), large-cap weakness
(B), and the repo's negative runs.

- **Input.** JKX-recipe 20-day OHLC and volume images, 64×60, with the
  gap-inclusive path. The architecture and training follow the stage-3 M2
  recipe: Adam at 1e-5, batch 128, patience 2, 5-network ensemble.
- **Label** (rows in a down-leg, where the last confirmed turn was down).
  y = 1 if an up-turn (θ = 3σ20 from the running minimum after t) is
  confirmed before the price falls another θ below C_t, within 20 sessions;
  y = 0 if the fall comes first. Rows where neither happens are dropped.
  This is a symmetric triple barrier on structure.
- **Decision.** For an ENTRY in a down-leg: if p̂ < 0.5, wait for the up-turn
  (W = 10, with the fallback); otherwise the control.
- **A second configuration**, the stage-3 M3 temporal convolutional network
  on the same label, counts as a second trial.
- **Expectation: fails.** It answers "can a CNN see a structure turn coming?"
  in decision units.

### 9.3 Which ones the evidence supports

| Rank | Candidate | Support | Most likely outcome |
|---|---|---|---|
| 1 | C1 momentum screen, switched off in stress | B: Dimensional practice; short-term momentum in the largest 500 (t 4.9); VIX and market-state reversal | Correct direction, about +0.05-0.2 bp a session; per-event t below 3 because of power |
| 2 | C2 information patience | A mechanism; B for large caps | Rare events; the per-event effect may be visible; the book effect is small |
| 3 | C4 deep-drawdown patience | B, conflicting | About 0 |
| 4 | C5 exit screen | C/B | About 0 |
| 5 | C3 momentum states | A index, B↓ stocks | About 0 or negative (it defers into rising names) |
| — | C6 structure exits | Against | Negative: whipsaw, time out, repo precedent |
| — | C7 regime gate | Index only; repo against | Negative: lag, exposure |
| — | C8 meta-label | C | Fails the floor; useful diagnostic |
| — | C9 CNN | Against for large caps | Fails; answers the operator |

### 9.4 Trials and gates

- **Trials.** C1-C7 are 7 rules. C8 is 8 configurations, nested to 1 outer
  candidate. C9 is 2 configurations. That makes **17 registered trials**, and
  the book's cumulative count goes from 409 to about 426.
- **The best null t** at that count is about 3.0 (the stage-3 plan's
  formula).
- **Gates.** Keep the stage-3 gates:
  - +2 bp a session with t ≥ 2 on 2016-2023 at 16 and 25 bp;
  - not negative on 2024-2026;
  - above the control in at least 15 of 20 offsets;
  - a deflated Sharpe ≥ 0.95 at the cumulative count;
  - PBO < 0.2.
- **A per-event diagnostic** of at least 25 bp per re-timed order with t ≥ 3
  is the category "RECORD: real but immaterial".

---

## 10. Honest prior: can multi-day timing of a graded book add more than about 2 bp a session after costs?

**Mechanics (calculation).**

- **The per-order hurdle.** Re-timing touches at most about 0.5 orders a
  session at about 7% of NAV. +2 bp a session needs about 55-60 bp average
  improvement across *all* entries and exits, and 250-500 bp per order for a
  rule that touches a fifth of them.
- **What the literature supports for large caps**, per affected order and
  gross:
  - short-term momentum: 0.42% a month for the whole decile spread in the
    largest 500. Over a 3-5 session wait that is about 3-10 bp for the
    affected names.
  - no-information price pressure: 17 bp, mostly gone in a day.
  - reversal in market stress: about 1% a week, which argues for buying now,
    not waiting.
  - information drift: large per event but rare (Savor's ±10% abnormal
    shocks).
- **The ceiling.** Stacked optimistically, the best single rule is worth
  about +0.1-0.5 bp a session, and all the favourable rules together stay
  under +1 bp. Decay pushes it lower: reversal, short-horizon ML
  alpha and the tech-sector technical rules have all faded since the early
  2000s (§5.2, §6.4, §2.2).
- **Exposure rules** (C6, C7) could reach the size needed only by cutting
  exposure. The book's return comes from staying invested in a trending
  sector. The repo priced that: skipping cost −22.8 bp a day, stops were
  100% false alarms, and bad-trend states were followed by better returns.

**Probabilities** (my judgement; the candidates share one weak signal, so the
chances are not independent):

| Outcome | Prior |
|---|---|
| The best single rule (C1 or C2) passes the +2 bp a session floor with t ≥ 2, not negative on 2024-2026 | about 3-4% |
| At least one of the nine passes that floor, before deflation | about 8% |
| … and also the deflated Sharpe (≥ 0.95 at about 426 trials) and PBO | about 3% |
| At least one candidate shows a per-event effect of 25 bp or more with t ≥ 3 ("real but immaterial") | about 20% (most likely C1 split by stress, or C2) |
| C6 (structure exits) is positive after costs on 2016-2023 | about 10% |
| C9 (CNN) beats C8 (trees) on the same decision test by 0.5 bp a session or more | about 10% |

**What would move the prior.**

- A per-event C1 or C2 effect of 50 bp or more with t ≥ 3 in *both* 2016-2019
  and 2020-2023. That would lift the chance of a real-but-immaterial result
  to about 50%. It would lift the chance of passing the floor only to about
  6%, because the scale is the binding constraint.
- A C6 variant positive in both halves with fewer than 3 triggers per name a
  year. That would make structure exits worth a forward shadow.

**What the study is for.** The likeliest outcome is RECORD for every
candidate. The value is:

1. per-event evidence on whether the operator's "dip" and "pop" instincts
   point the right way in each market state;
2. a clean, decision-unit answer to the CNN question;
3. confirming that the grade and full investment, not timing, carry the book.

Because re-timing adds no turnover, a candidate that is right but immaterial
could still be adopted on operator preference. That is a product decision,
not an evidence one.

---

## References

Links were opened unless marked otherwise. "Abstract only" means the figures
come from the abstract or landing page.

**Market structure, patterns, directional change.**
[Brown-Goetzmann-Kumar 1998](http://depot.som.yale.edu/icf/papers/fileuploads/2439/original/98-86.pdf) ·
[Lo-Mamaysky-Wang 2000](https://www.nber.org/system/files/working_papers/w7613/w7613.pdf) ·
[Savin-Weller-Zvingelis 2007](https://www.biz.uiowa.edu/faculty/gsavin/papers/hsrevision_paw_10%2019%2006.pdf) ·
[Zapranis-Tsinaslanidis 2012 (abstract)](https://ideas.repec.org/a/taf/apfiec/v22y2012i19p1571-1585.html) ·
[Marshall-Qian-Young 2009 (abstract)](https://ideas.repec.org/a/taf/apfiec/v19y2009i15p1213-1221.html) ·
[Shynkevich 2012 (abstract)](https://econpapers.repec.org/RePEc:eee:jbfina:v:36:y:2012:i:1:p:193-208) ·
[Bajgrowicz-Scaillet 2012 (abstract)](https://ideas.repec.org/a/eee/jfinec/v106y2012i3p473-491.html) ·
[LuxAlgo BOS/CHoCH (C)](https://www.luxalgo.com/library/concept/break-of-structure/) ·
[Glattfelder-Dupuis-Olsen 2011](https://arxiv.org/abs/0809.1040) ([full text](https://ar5iv.arxiv.org/html/0809.1040)) ·
[DC intrinsic time (Wikipedia)](https://en.wikipedia.org/wiki/Directional-change_intrinsic_time) ·
[Tsang et al. 2017 (seen, 403)](https://www.tandfonline.com/doi/abs/10.1080/14697688.2016.1164887) ·
[Adegboye-Kampouridis 2021 (abstract)](https://repository.essex.ac.uk/29573/) ·
[Wu-Han 2023](https://arxiv.org/html/2309.15383v1) ·
[GP-DC equities (abstract)](https://link.springer.com/chapter/10.1007/978-3-031-14721-0_3) ·
[Lunde-Timmermann 2004](https://econweb.ucsd.edu/~atimmerm/dur-14-2.pdf)

**Trends and turning points.**
[Goulding-Harvey-Mazzoleni 2023 (JFE abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0304405X23001034) ·
[GHM published PDF](https://people.duke.edu/~charvey/Research/Published_Papers/P158_Momentum_turning_points.pdf) ·
[GHM working paper](https://www.toptradersunplugged.com/wp-content/uploads/2021/12/Momentum-Turning-Points.pdf) ·
[Garg et al. 2024](https://people.duke.edu/~charvey/Research/Published_Papers/P167_Breaking_bad_trends.pdf) ·
[Moskowitz-Ooi-Pedersen 2012](https://w4.stern.nyu.edu/facdir/lpederse/papers/TimeSeriesMomentum.pdf) ·
[Lim-Wang-Yao 2018](https://eprints.lancs.ac.uk/id/eprint/128366/1/Time_Series_Momentum_in_Nearly_100_Years_of_Stock_Returns.pdf) ·
[Han-Zhou-Zhu 2016 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0304405X16301271) ·
[Levine-Pedersen 2016](https://research.cbs.dk/en/publications/which-trend-is-your-friend/) ·
[Zakamulin 2014 (abstract)](https://ideas.repec.org/a/pal/assmgt/v15y2014i4d10.1057_jam.2014.25.html) ·
[Zakamulin, Anatomy](https://smallake.kr/wp-content/uploads/2016/04/SSRN-id2585056.pdf) ·
[Zakamulin-Giner 2020 (abstract)](https://ideas.repec.org/a/taf/quantf/v20y2020i6p985-1007.html) ·
[Dichtl 2020 (abstract)](https://ideas.repec.org/a/wly/revfec/v38y2020i2p352-378.html) ·
[Han-Yang-Zhou 2013](https://www.kevinsheppard.com/files/teaching/mfe/advanced-econometrics/Han_Yang_Zhou.pdf) ·
[Wilcox-Crittenden 2005 (C)](https://www.cis.upenn.edu/~mkearns/finread/trend.pdf) ·
[Zarattini-Pagani-Wilcox 2025 (C)](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5084316) ·
[Da-Gurun-Warachka 2014](https://academicweb.nd.edu/~zda/Frog.pdf) ·
[Kaminski-Lo (abstract)](https://ideas.repec.org/p/hhs/sifrwp/0063.html) ·
[Detzel et al. 2021 (abstract)](https://ideas.repec.org/a/bla/finmgt/v50y2021i1p107-137.html) ·
[Gong-Liu-Liu 2015 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0378426614003252)

**Change points and regimes.**
[Lam-Yam 1997 (abstract)](https://link.springer.com/article/10.1023/A:1009604804110) ·
[CUSUM filter (mlfinpy)](https://mlfinpy.readthedocs.io/en/latest/Filtering.html) ·
[Adams-MacKay 2007](https://arxiv.org/abs/0710.3742) ·
[Wood-Roberts-Zohren 2022](https://arxiv.org/abs/2105.13727) ·
[Momentum Transformer](https://arxiv.org/abs/2112.08534) ·
[Maheu-McCurdy-Song (abstract)](https://ideas.repec.org/p/tor/tecipa/tecipa-402.html) ·
[Kirby 2023](https://www.sciencedirect.com/science/article/abs/pii/S1544612322005463) ·
[Bulla et al. 2011 (abstract)](https://mpra.ub.uni-muenchen.de/21154/) ·
[Shu-Yu-Mulvey 2024](https://arxiv.org/html/2402.05272v2) ·
[Nguyen 2017](https://ideas.repec.org/a/gam/jrisks/v5y2017i4p62-d120204.html) ·
[Nguyen 2018](https://ideas.repec.org/a/gam/jijfss/v6y2018i2p36-d138097.html)

**Pullbacks, reversal, news, liquidity.**
[George-Hwang 2004](https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf) ·
[Bhootra-Hur 2013](https://ideas.repec.org/a/eee/jbfina/v37y2013i10p3773-3782.html) ·
[Huddart-Lang-Yetman 2009 (abstract)](https://pure.psu.edu/en/publications/volume-and-price-patterns-around-a-stocks-52-week-highs-and-lows-/) ·
[Della Vedova-Grant-Westerholm 2023 (abstract)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/investor-behavior-at-the-52week-high/5D1C7CA21396521F3B41D91B06A25BE1) ·
[Chen-Stivers-Sun 2024 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0927539824000902) ·
[Medhat-Schmeling 2022](https://openaccess.city.ac.uk/id/eprint/31278/1/MS_short_term_mom_v27.pdf) ·
[Da-Liu-Schaumburg 2014](https://academicweb.nd.edu/~zda/Reversal.pdf) ·
[de Groot-Huij-Zhou 2012](https://repub.eur.nl/pub/25718/AnotherLook_2011.pdf) ·
[Khandani-Lo](https://www.nber.org/system/files/working_papers/w14465/w14465.pdf) ·
[Dai-Medhat-Novy-Marx-Rizova](https://www.nber.org/papers/w30917) ·
[Dimensional Q&A on reversals (C)](https://www.dimensional.com/ie-en/insights/q-and-a-on-short-run-reversals-with-mamdouh-medhat-and-robert-novy-marx) ·
[Chan 2001/2003](http://www.econ.yale.edu/~shiller/behfin/2001-05-11/chan.pdf) ·
[Savor 2012](https://faculty.wharton.upenn.edu/wp-content/uploads/2012/10/Stock-Returns-After-Major-Price-Shocks---May-2012---Final.pdf) ·
[Cox-Peterson 1994 (abstract)](https://ideas.repec.org/a/bla/jfinan/v49y1994i1p255-67.html) ·
[Bremer-Sweeney 1991 (abstract)](https://ideas.repec.org/a/bla/jfinan/v46y1991i2p747-54.html) ·
[Park 1995 (abstract)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/market-microstructure-explanation-for-predictable-variations-in-stock-returns-following-large-price-changes/D98180CB28103AEEE8D5C439FEC0DE20) ·
[Hendershott-Menkveld 2014](http://faculty.haas.berkeley.edu/hender/price_pressures.pdf) ·
[Hameed-Kang-Viswanathan 2010](https://web2-bschool.nus.edu.sg/wp-content/uploads/media_rp/publications/lEJ6N1370226075.pdf) ·
[Nagel 2012 (abstract)](https://www.nber.org/papers/w17653) ·
[Cooper-Gutierrez-Hameed 2004 (abstract)](https://www.semanticscholar.org/paper/Market-States-and-Momentum-Gutierrez-Cooper/85b2db4ae48f1adf668080906ea1599ab7069c9a) ·
[So-Wang 2014 (abstract)](https://dspace.mit.edu/handle/1721.1/119665) ·
[Kaniel-Saar-Titman 2008 (abstract)](https://ideas.repec.org/a/bla/jfinan/v63y2008i1p273-310.html) ·
[Barrot-Kaniel-Sraer](https://faculty.haas.berkeley.edu/dsraer/Barrot_Kaniel_Sraer.pdf) ·
[Coval-Stafford 2007 (abstract)](https://ideas.repec.org/a/eee/jfinec/v86y2007i2p479-512.html) ·
[Cheng-Hameed-Subrahmanyam-Titman 2017 (abstract)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/shortterm-reversals-the-effects-of-past-returns-and-institutional-exits/7B9F21C81D419D4C51430E2CC376A649) ·
[Womack 1996 (abstract)](https://ideas.repec.org/a/bla/jfinan/v51y1996i1p137-67.html) ·
[Jegadeesh-Kim-Krische-Lee 2004 (summary)](https://paperswithbacktest.com/strategies/analyzing-the-analysts-when-do-recommendations-add-value) ·
[Dimensional momentum screens (C)](https://www.dimensional.com/sg-en/insights/myth-busting-with-momentum-how-to-pursue-the-premium) ·
[Novy-Marx-Velikov 2016 (abstract)](https://ideas.repec.org/a/oup/rfinst/v29y2016i1p104-147..html) ·
[AQR Hold the Dip 2025 (C)](https://www.aqr.com/-/media/AQR/Documents/Alternative-Thinking/AQR-Alternative-Thinking---Hold-the-Dip.pdf?sc_lang=en) ·
[Alpha Architect summary (C)](https://alphaarchitect.com/is-trend-following-better-than-buy-the-dip/) ·
[Bonini-Shohfi-Simaan 2024 (summary only)](https://www.evidenceinvestor.com/post/buy-the-dip)

**ML, CNNs, labels.**
[JKX 2023](https://www.aidf.nus.edu.sg/wp-content/uploads/2022/02/Xiu-Re-Imagining-Price-Trends.pdf) ·
[Dixon-Zeng 2024](https://acfr.aut.ac.nz/__data/assets/pdf_file/0005/925943/CNN-Draft-July-2024.pdf) ·
[Byun-Na-Song 2026 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S1544612326001169) ·
[Jeong-Byun-Kim 2026 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0275531925004878) ·
[Murray-Xia-Xiao 2024 (abstract)](https://ideas.repec.org/a/eee/jfinec/v153y2024ics0304405x2400014x.html) ·
[Sezer-Ozbayoglu 2018 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S1568494618302151) ·
[CNN-TA README](https://github.com/omerbsezer/CNN-TA/blob/master/README.md) ·
[ENJINE review (C)](https://www.enjine.com/blog/paper-review-algorithmic-financial-trading-with-deep-convolutional-neural-networks-time-series-to-image-conversion-approach/) ·
[Velay-Daniel 2018](https://arxiv.org/abs/1808.00418) ·
[Song 2024](https://www.sciencedirect.com/science/article/pii/S2405844024001671) ·
[Buchanan-Benhamou 2026](https://arxiv.org/html/2603.14453v1) ·
[Fischer-Krauss 2018 (abstract)](https://www.sciencedirect.com/science/article/abs/pii/S0377221717310652) ·
[Brogaard-Zareei 2023 (abstract)](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/machine-learning-and-the-stock-market/F54ECC9DA40067B35261B32691D1DDA2) ·
[Avramov-Cheng-Metzker 2023 (abstract)](https://econpapers.repec.org/RePEc:inm:ormnsc:v:69:y:2023:i:5:p:2587-2619) ·
[Blitz et al. 2023 (Robeco summary)](https://www.robeco.com/en-int/insights/2023/07/the-term-structure-of-machine-learning-alpha) ·
[Jensen-Kelly-Malamud-Pedersen (abstract)](https://research.cbs.dk/en/publications/9a2926d9-858b-449d-b658-8f204cac58bb) ·
[Labels: triple barrier, meta-labeling, trend scanning (mlfinpy)](https://mlfinpy.readthedocs.io/en/latest/Labelling.html) ·
[Trend scanning (mlfinlab docs)](https://random-docs.readthedocs.io/en/latest/implementations/labeling_trend_scanning.html) ·
[Meta-labeling (Wikipedia)](https://en.wikipedia.org/wiki/Meta-Labeling) ·
[Hudson & Thames meta-labeling test (C)](https://hudsonthames.org/does-meta-labeling-add-to-signal-efficacy-triple-barrier-method/) ·
[Lund thesis (weak)](https://lup.lub.lu.se/student-papers/record/9120301/file/9120304.pdf)

### Not accessed, or accessed only in part

- **Publisher pages that blocked access (403, 429 or robots).** Wiley
  (Glabadanidis 2015 and 2017, Zakamulin 2018, Bonini et al. 2024), SSRN
  pages (GHM, Han-Zhou-Zhu), Taylor & Francis (Tsang et al., Garg et al.'s
  FAJ page) and JFDS (Joubert 2022). The GHM and Garg figures come from the
  authors' Duke PDFs and the GHM working paper.
- **Glabadanidis 2015**, which reportedly applies moving-average timing to
  individual stocks, could not be opened. No claim here rests on it.
- **Seen in search only, not opened.** Kritzman-Page-Turkington 2012,
  Chang et al. 2009 (piecewise-linear turning points), smart-money-concept
  backtest blogs, and triple-screen practitioner guides.
- **Uncertain extractions.**
  - Chan (2001 working paper): the news/no-news month-1 figures were
    ambiguous, so only the qualitative results and the value-weighted
    caveat are used.
  - Bremer-Sweeney: the RePEc abstract text reads "ten-day"; only its
    two-day adjustment result is used.
  - JKX: the 5-day equal-weight Sharpe appears as 7.15 here and 6.75 in the
    feature-research memo, from different tables or versions.
- **Repo facts** come from the project documents and `docs/research/` files
  named in §1.5. They were read, not recomputed.
