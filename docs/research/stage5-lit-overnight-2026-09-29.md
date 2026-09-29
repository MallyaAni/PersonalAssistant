# Stage 5 literature: buying at the decision day's close (2026-09-29)

This memo is research only. It changes no code, no model and nothing live.
It feeds the pre-registration of one test: move the book's buys from the next
session to the decision day's closing auction. It sets expectations and lists
the traps.

**The lead (post-hoc).** On the executor's own orders, the price of a bought
name rose between the decision close C_t and the board's fill in the next
session ([stage-4 follow-up](stage4-audit-and-overnight-2026-09-29.md)):

- +22.3 bp per buy on 2018-2023;
- +51.9 bp per buy on 2024-2026;
- most of that rise happened overnight.

A market-on-close (MOC) buy, decided at about 15:45 ET from 15:45 data,
would pay C_t instead. Prices also rose overnight after sell decisions, so
sells stay on the next session.

## How to read this

- **Evidence grades.** These follow
  [feature-research-2026-09-29.md](feature-research-2026-09-29.md).
  - **A:** peer-reviewed, with out-of-sample or post-publication evidence
    that is relevant here.
  - **B:** peer-reviewed but in-sample, in another market, or contested.
    Strong working papers also go here.
  - **C:** exchange, vendor, law-firm or practitioner material.
- **Access flags.**
  - "[abstract]" means I read only the abstract.
  - "[summary]" means I read a secondary summary or a conference page, not
    the paper.
  - "[full text]" means I read the paper itself.
  - Every reference below was located by web search on 2026-09-29. None is
    cited from memory.
- **Repo facts.** These are cited by file and are in-sample. The per-order
  figures come from `scorecards/stage4/audit/overnight_submitted.json` and
  `overnight_executed.json` (offset 10 of 20).
- **Calculations.** Anything marked "(calculation)" is my own arithmetic,
  with its assumptions stated. It is not a literature result.
- **Sign convention.** As in the audit, a positive number is a move against
  the order: a buy's price rising, or a sell's price falling.

---

## 0. The answer in brief

1. **The overnight premium in US stocks is old and large-cap.**
   - S&P 500 stocks earned +2.8 to +4.8 bp a night on 1993-2006, and
     −2.8 to +0.2 bp a day
     ([Cliff-Cooper-Gulen 2008](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081),
     via a summary).
   - For the largest stocks, "essentially all of their risk premium is
     earned overnight"
     ([Lou-Polk-Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)).
   - Market-level updates to 2022-2023 still show it
     ([Lou-Polk-Skouras 2024](https://personal.lse.ac.uk/loud/LouPolkSkouras.pdf);
     [Glasserman et al. 2025](https://arxiv.org/abs/2507.04481)).
   - One narrow form has disappeared since 2021: the futures drift around
     the European open
     ([NY Fed 2026](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/)).
2. **Momentum is earned overnight; one-month winners give some back
   overnight.** The long-short overnight CAPM alphas a month are +0.98% for
   12-month momentum and +1.07% for industry momentum. Reversal (losers
   minus winners) earns +0.93% overnight
   ([Lou-Polk-Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf)).
   For a book of A-graded winners, the literature's overnight tilt is a few
   bp a night. That is well below what we measured.
3. **Weighted by order size, the gain is smaller than the headline**
   (calculation, §1).
   - The audit's +0.9 and +2.2 bp a session used simple per-order means.
   - Weighted by each order's share of equity, the gross gain is:
     - **+0.8 to +1.0 bp a session on 2018-2023;**
     - **+0.2 to +0.9 bp a session on 2024-2026.**
   - That is before any cost of deciding at 15:45.
   - "2024-2026 is stronger" is largely an artefact of equal-weighting small
     orders.
4. **Much of the move is one session of the book's drift.** Moving a buy
   one session earlier earns one session of the name's expected return.
   - On 2018-2023 that drift (8.1 bp) is about a third to two-fifths of the
     weighted move.
   - On 2024-2026 it (17.7 bp) is all of the executed-basis move or more,
     and most of the submitted-basis move.
   - Forward-looking, the gain is only as large as the A names' future
     drift.
5. **The closing auction is the cheapest place to trade.**
   - It handles about 9-10% of US volume.
   - Its price impact is lower than in continuous trading for all but
     Nasdaq microcaps
     ([Goyal-Jegadeesh-Wu 2026](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/price-impact-in-closing-auctions-opening-auctions-and-continuous-markets-a-benchmark-for-cost-of-trading-on-anomalies/0F72910A79C5B42CF6E85F55164CE846);
     [BMLL 2025](https://www.bmlltech.com/news/market-insight/into-the-close-unpacking-u-s-closing-auction-dynamics-and-the-impact-of-the-russell-reconstitution)).
   - A retail-sized MOC order in these names costs about nothing beyond the
     closing price.
   - Alpaca accepts MOC ("cls") orders until **15:50 ET**
     ([Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca)).
   - Robinhood does not offer MOC orders
     ([Robinhood](https://www.robinhood.com/us/en/support/articles/order-types)).
6. **Deciding at 15:45 costs little for a slow signal. What stops it is
   feasibility.**
   - Buys caused by the nightly grade change (entries) cannot be known at
     15:45.
   - Nor can buys caused by after-hours news (event buys), or adds paid for
     by next-day sales without margin.
   - These must stay on the board's rule. Otherwise the MOC arm is worse
     for them, because it gives up the dip.
7. **An evening or overnight buy is possible but worse priced.**
   - Overnight spreads are about 4-10 times wider on ETFs, and 28 against
     20 bp on actively traded stocks
     ([BlackRock 2025](https://www.blackrock.com/corporate/literature/whitepaper/blackrock-market-spotlight-24-hour-trading.pdf);
     [Eaton-Shkilko-Werner 2025](https://afajof.org/management/viewp.php?n=162176)).
   - Only limit orders are accepted, and trades have been cancelled
     ([Markets Media 2024](https://www.marketsmedia.com/blue-ocean-ats-resumes-after-cancelling-trades/)).
   - First measure *when* our buys' overnight rise happens. That settles
     whether an evening buy could capture it.
8. **What a skeptic says** (§7).
   - The finding is post-hoc and tail-driven: the 2018-2023 median is
     −3.6 bp.
   - Both windows have already been seen.
   - It is partly compensation for more time invested, not an execution
     edge.
   - A live confirmation needs about 3-9 years of orders (calculation).
9. **Design** (§8).
   - Move only buys that are knowable at 15:45 to the MOC.
   - Keep everything else, and all sells, on the board.
   - Measure the gain weighted by order size, per session.
   - Run a 2×2 decision-time × fill diagnostic, and split the overnight
     move by time before the run.
10. **Prior** (§9).
    - About **10%** that the 2018-2023 criterion passes (≥ +1 bp a session,
      t ≥ 2).
    - About **5%** that it also holds on 2024-2026, with "holds" meaning
      positive and ≥ +0.5 bp.
    - About **1-2%** under a strict reading, where 2024-2026 must also reach
      ≥ +1 bp with t ≥ 2.
    - The likely outcome is "positive, below the floor, recorded not acted
      on".

---

## 1. What our own numbers say (repo facts, and one correction)

The stage-4 follow-up reported simple means per order. The audit files also
hold the median and the mean weighted by order size. The weight is the share
of equity each order moves: |units| × close_t / NAV_t
(`backend/market/stage4_orders.py`). The weighted mean is what reaches the
book.

| Buys, C_t to … | Window | Orders | Mean (naive t) | Median | Share rising | Weighted mean, submitted | Weighted mean, executed |
|---|---|---|---|---|---|---|---|
| next open | 2018-2023 | 1,065 | +14.6 (3.1) | +17.1 | 57% | +14.9 | +20.3 |
| next open | 2024-2026 | 389 | +44.1 (3.2) | +29.2 | 60% | +12.0 | +3.0 |
| board's fill | 2018-2023 | 1,065 | +22.3 (3.4) | **−3.6** | 49% | +19.5 | +23.6 |
| board's fill | 2024-2026 | 389 | +51.9 (2.9) | +22.8 | 53% | +21.2 | **+5.1** |

All figures are bp per buy. The submitted basis counts each decision as it
was made. On the executed basis the executed counts are 1,042 and 383 buys,
and the simple means are +21.4 and +45.6 bp.

**How the move breaks down (repo facts).**

- **Heavy tails.**
  - On 2018-2023 the median buy's price *fell* from C_t to the board's fill
    (−3.6 bp), and only 49% of buys rose. The +22.3 bp mean is carried by a
    minority of large moves.
  - On 2024-2026 the median buy rose +22.8 bp.
- **Small orders carry the 2024-2026 mean.**
  - The weighted C_t-to-fill is +21.2 bp (submitted) or +5.1 bp (executed),
    against a simple mean of +51.9 bp.
  - By kind (simple means, submitted), the overnight rise was +45.7 bp for
    194 adds, +65.0 for 64 retries and +200.7 for 17 event buys, but only
    +6.3 for 114 entries.
- **Earnings nights are not the driver.**
  - Buys with earnings between C_t and the open: 23 orders at +25.7 bp on
    2018-2023, and 7 orders at −57.8 bp on 2024-2026.
  - Without them the overnight means are +14.3 and +46.0 bp.
- **Sells rose overnight too.**
  - The move against a sell was −10.5 and −40.3 bp on the submitted basis.
    Most sells are rotation exits: −9.6 and −37.0 bp.
  - So the rise is not specific to the names being bought.
  - The executed sells are selected on red opens, so their basis is biased
    (97% adverse on 2018-2023, by construction).
- **The book's unconditional overnight gap is much smaller.**
  - It averaged +3.9 bp a session on 2016-2023 and +7.6 bp on 2024-2026.
    Open-to-close averaged +4.1 and −0.4 bp
    ([session anatomy](session-anatomy-2026-09-27.md)).
  - On simple means, bought names moved about 4-6 times that on the
    decision nights.
  - Weighted by size, they moved 4-5 times that on 2018-2023. On 2024-2026
    they moved 0.4-1.6 times that, close to the book's usual night.

**The correction to the headline (calculation).**

- **Equity bought a session.** Buys a session × mean order weight:
  - 2018-2023: 0.70 × 5.9% ≈ **4.2%**;
  - 2024-2026: 0.57 × 7.5% ≈ **4.3%**.
  - The inputs are from [stage 4](stage4-results-2026-09-29.md). This
    assumes buys have the same mean weight as all orders. The run must
    compute Σ w·Δ / sessions exactly.
- **Gross gain a session** (equity bought × weighted C_t-to-fill):
  - 2018-2023: 4.2% × 19.5 to 23.6 bp = **+0.81 to +0.98 bp**;
  - 2024-2026: 4.3% × 5.1 to 21.2 bp = **+0.22 to +0.91 bp**.
  - The audit's +0.9 and +2.2 used the simple means (4.2% × 22.3 and
    4.3% × 51.9).
- **One session of drift alone** (stage 4: the A/A+ drift is +8.07 bp on the
  model window, +17.69 bp on 2024-2026):
  - 4.2% × 8.1 = +0.34 bp a session;
  - 4.3% × 17.7 = +0.76 bp a session.
  - On 2024-2026 the whole weighted gain is about one session of drift or
    less. On 2018-2023 about 60% of it is extra.
- **Noise.** Assume orders are independent, with each order's move scaled
  by its share of equity.
  - The standard error of the per-session mean is about 0.28 bp on
    2018-2023. The per-order SD is 217 bp and the weight 5.9%, over 1,512
    sessions.
  - On 2024-2026 it is about 0.76 bp. The per-order SD is 351 bp and the
    weight 7.5%, over 686 sessions.
  - So a +0.9 bp gain would read t ≈ 3 on 2018-2023 but only t ≈ 1.2 on
    2024-2026. Clustering by date would lower both.

---

## 2. Overnight versus intraday returns in US stocks (topic 1)

### 2.1 The founding papers

- **Cliff, Cooper and Gulen (2008)**, SSRN working paper; I found no
  journal version.
  [abstract; figures from a [CXO summary](https://www.cxoadvisory.com/calendar-effects/buy-at-the-close-and-sell-at-the-open/)]
  - Abstract: "the US equity premium over the last decade is solely due to
    overnight returns".
  - The pattern holds for individual stocks, indexes and futures, on NYSE
    and Nasdaq.
  - On 1993-2006, S&P 500 stocks averaged +0.028% to +0.048% a night and
    −0.028% to +0.002% a day, depending on the averaging.
  - "High opening prices that decline in the first hour" drive much of it.
    The first hour returned −1.2 to −3.6 bp.
  - Overnight returns were *less* volatile than daytime returns. Grade B.
- **Kelly and Clark (2011)**, *Journal of Asset Management* [abstract].
  - On QQQQ, the tech-heavy Nasdaq-100 fund, for 1999-2006, the
    geometric-average close-to-open risk premium was +23.7%, against −23.3%
    open-to-close.
  - Overnight volatility was lower.
  - The authors draw "broad implications for when investors should buy and
    sell". Grade B: short sample, index funds only.
- **Berkman, Koch, Tuttle and Zhang (2012)**, *JFQA* [abstract].
  - Overnight returns are positive and then reverse during the day. The
    driver is "an opening price that is high relative to intraday prices".
  - The effect is concentrated in stocks that recently drew retail
    attention, stocks that are hard to value or costly to arbitrage, and
    periods of high retail sentiment.
  - For retail buyers of high-attention stocks at the open, the implicit
    cost "frequently exceed[s] the effective half spread".
  - I could not read the magnitudes. Grade A for the direction.
- **Aboody, Even-Tov, Lehavy and Trueman (2018)**, *JFQA* [full text].
  - Sample: 1992-2013, prices above $5.
  - **Overnight returns persist week to week.** Next week's overnight
    return differs by 1.76 percentage points (t 46.0) between the top and
    bottom deciles of this week's overnight return.
  - In the largest size quartile the spread is 0.98 pp. That is about
    20 bp a night between the extreme deciles (calculation: 0.98% / 5).
  - Next week's close-to-close spread is only 0.26 pp, so the night's gain
    is mostly given back by day.
  - Persistence is stronger in harder-to-value firms.
  - Over longer horizons the high-overnight names underperform, by
    0.62 pp a month. Grade A.

### 2.2 The cross-section and asset pricing

- **Lou, Polk and Skouras (2019)**, *JFE* [full text].
  - **Sample and definitions.**
    - 1993-2013.
    - Stocks under $5 and those in the bottom NYSE size quintile are
      excluded.
    - "Open" is the VWAP of 09:30-10:00, so "overnight" includes the first
      half hour. Results hold with the CRSP open, the first trade and the
      opening midquote.
  - **The market.** Overnight 0.55% a month, intraday excess 0.38% a month.
    "For the largest stocks, essentially all of their risk premium is earned
    overnight."
  - **Momentum and reversal.** See §3. Of 14 strategies, each earns its
    profit entirely overnight or entirely intraday.
  - **The size premium** is earned intraday.
  - The authors warn that transaction costs make overnight/intraday trading
    strategies "much less attractive". Grade A.
- **Hendershott, Livdan and Rösch (2020)**, *JFE* [abstract].
  - Beta is weakly related to 24-hour returns.
  - Returns are *positively* related to beta overnight and *negatively*
    during the day, across portfolios and countries.
  - High-beta tech names should earn their premium at night. That is a
    risk reading of the overnight premium. Grade A.
- **Bogousslavsky (2021)**, *JFE* [abstract].
  - Margin requirements are higher overnight, and lending fees are charged
    only on positions held overnight.
  - So arbitrageurs shrink positions before the close. A mispricing factor
    "earns positive returns throughout the day but performs poorly at the
    end of the day".
  - The pattern "strengthens in the second half of the sample".
  - Reading: underpriced names tend to be weak into the close and recover
    later, which favours buying them at the close. I have not verified
    which anomalies he tests. Grade A.
- **Akbas, Boehmer, Jiang and Koch (2022)**, *JFE* [abstract]. A higher
  frequency of "positive overnight, negative day" returns predicts *higher*
  future returns. The authors read it as daytime arbitrageurs over-correcting
  overnight demand. Grade A.
- **Barardehi, Bogousslavsky and Muravyev**, *RFS*, forthcoming. The SFS
  listed it in August 2025, and it is now an advance article [abstract].
  - Overnight returns are mostly news, and intraday returns mostly trading.
  - Sorting on past *intraday* returns gives short-term reversal and
    momentum without long-term reversal.
  - Sorting on past *overnight* returns gives only long-term reversal.
  - Sample 1926-2019. Grade A.

### 2.3 Where in the night the return accrues

- **Barclay and Hendershott (2003)**, *RFS* [full text, parts].
  - Sample: Nasdaq, March-December 2000.
  - After-hours trading was 4% of volume and cost "four to five times"
    daytime spreads.
  - 74% of close-to-open price discovery happened pre-open, and 15%
    post-close.
  - Post-close prices were noisier. Grade A, but old.
- **Bondarenko and Muravyev (2023)**, *JFQA* [abstract]. In S&P 500
  futures, the "4 hours around European open account for the entire average
  market return". The Sharpe ratio is 1.6, profitable after costs. The rest
  of the 24 hours is "a noisy zero". Grade A for futures.
- **Boyarchenko, Larsen and Whelan (2023)**, *RFS* [abstract].
  - US equity futures returns are large and positive around the European
    open.
  - They are linked to end-of-day order imbalances and dealer inventory.
    Sell-offs are followed by strong overnight reversals, rallies by weaker
    ones.
  - **The same authors' 2026 update** (NY Fed *Liberty Street Economics*,
    July 1, 2026) [full text]:
    - The 02:00-03:00 window earned about 3.7% a year on 1998-2020, and has
      "averaged close to zero since 2021".
    - They attribute this to smaller end-of-day imbalances.
    - Two NightShares ETFs (NSPY, NIWM) built to harvest overnight returns
      launched in June 2022 and "were closed fourteen months later".
  - Grade A for the paper; the update is C.
- **Perreten (2026)**, working paper, S&P 500 stocks, 2008-2023 [summary].
  - The close-to-open return splits into after-market (16:00-20:00),
    "dark" (20:00-04:00) and pre-market parts.
  - After-market averages about +0.9 bp a day.
  - Dark returns are positive. Pre-market returns are negative and offset
    "a substantial share" of them.
  - Price discovery builds gradually through the pre-market. Grade B.
- **Eaton, Shkilko and Werner (2025)**, "Nocturnal Trading", working paper
  [summary]. The 20:00-04:00 period contributes about 9% of 24-hour price
  changes, and about two-thirds of those changes do not reverse by the next
  close. Liquidity figures are in §6. Grade B.

### 2.4 After publication, and 2021-2026

- **Index level, practitioner.**
  - Elm Wealth: "the effect has been waning following the circulation of a
    half dozen relevant papers between 2008 and 2015". At 1 bp a trade, the
    index overnight strategy "would not have made any money in the last 8
    years" to 2022
    ([Haghani-Ragulin-Dewey 2022](https://elmwealth.com/night-moves-overnight-drift/)).
  - Nasdaq: since 1993, SPY returned +12% intraday against about 20-fold
    overnight. But in rolling 12-month windows since 2001 "the day strategy
    leads 30% of the time"
    ([Mackintosh 2024](https://www.nasdaq.com/articles/night-and-day)).
  - Grade C.
- **Market level, academic.**
  - Lou, Polk and Skouras (2024, working paper) [summary], 1993-2023:
    - The market's average overnight return was 1.83% a quarter, against
      0.25% intraday.
    - *High* smoothed overnight returns forecast *lower* close-to-close
      market returns over the next quarter (R² 16%).
    - They tie overnight returns to individual investors' expectations.
    - "The majority of the Covid crash and rebound comes overnight."
  - Glasserman, Krstovski, Laliberte and Mamaysky (2025, arXiv)
    [full text, parts]:
    - "nearly all the gains in the U.S. stock market" over 30 years came
      overnight.
    - For S&P 500 stocks since 2000, overnight minus intraday averages
      2.75 bp a day, about 7.2% a year.
    - News topics explain part of it.
  - Grade B: working papers.
- **The retail channel.**
  - Ahn, Fan, Noh and Park (2024, working paper) [full text]:
    - Korean data, 2009-2021.
    - Retail investors "net buy stocks near market open and net sell near
      close".
    - Higher retail share predicts a larger overnight-intraday gap.
    - The SSRN version is titled "Retail Ebb and Flow and the
      Overnight–Intraday Return Gap". I could not load its author list.
  - Barber, Huang, Odean and Schwarz (2022), *JF* [abstract]: the stocks
    Robinhood users buy most heavily lose 4.7% over the next 20 days.
    Attention-driven buying overshoots.
  - I found **no peer-reviewed US study of the overnight gap in the
    zero-commission era (2019-2026)**. The evidence for "2024-2026 is
    stronger because of retail" is thin.
- **Cross-section.** The peer-reviewed momentum/overnight evidence ends in
  2013 (Lou-Polk-Skouras) or 2019 (Barardehi-Bogousslavsky-Muravyev). I
  found no post-2019 update.

### 2.5 Sizes and signs at a glance

| Source | Sample | Stocks | Overnight | Intraday |
|---|---|---|---|---|
| Cliff-Cooper-Gulen (summary) | 1993-2006 | S&P 500 stocks | +2.8 to +4.8 bp a night | −2.8 to +0.2 bp a day |
| Kelly-Clark | 1999-2006 | QQQQ | +23.7% (geometric risk premium) | −23.3% |
| Lou-Polk-Skouras 2019 | 1993-2013 | CRSP value-weighted | 0.55% a month | 0.38% a month (excess) |
| Lou-Polk-Skouras 2024 | 1993-2023 | market | 1.83% a quarter (≈ +2.9 bp a night, calculation) | 0.25% a quarter |
| Glasserman et al. | since 2000 | S&P 500 stocks | overnight − intraday = 2.75 bp a day | |
| Repo: the book | 2016-2023 / 2024-2026 | held A/A+ names | +3.9 / +7.6 bp a session | +4.1 / −0.4 bp |
| Repo: the book's buys | 2018-2023 / 2024-2026 | decision nights | +14.6 / +44.1 bp simple; +14.9 / +12.0 weighted (submitted) | |

**Reading.**

- The book's unconditional overnight gap sits in the literature's range.
- The buys' overnight move is several times that on simple means. Weighted
  by size it is 4-5 times that on 2018-2023, and about the same as the
  gap on 2024-2026.
- The generic large-cap premium explains about 3-5 bp of it per buy. The
  rest needs the momentum, reversal, attention or drift channels (§3), or
  noise.

---

## 3. Momentum and the overnight/intraday split (topic 2)

**The overnight/intraday CAPM alphas, per month, long-short, 1993-2013**
([Lou-Polk-Skouras 2019](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf),
Table 2):

| Strategy | Overnight (t) | Intraday (t) |
|---|---|---|
| Momentum, 12-1 months | +0.98% (3.84) | −0.02% (−0.06) |
| Industry momentum | +1.07% (6.47) | −0.63% (−2.03) |
| Earnings momentum (SUE) | +0.56% (3.20) | +0.21% (0.70) |
| Short-term reversal (losers minus winners) | +0.93% (4.28) | −1.05% (−3.25) |

**What this implies for a book of A-graded tech winners.**

- **12-month and industry momentum add overnight.**
  - The long-short spread is about +4.7 to +5.1 bp a night (calculation:
    monthly ÷ 21).
  - A long-only winner earns roughly half of that above the market,
    +2 to +3 bp a night.
- **One-month winners give some back overnight.** Losers bounce overnight,
  about +4.4 bp a night long-short (calculation).
  - If a buy follows a *down* day or week, as a top-up or a retried dip
    buy, reversal adds to the overnight rise.
  - If it follows a strong week, reversal subtracts.
- **Recent overnight winners keep winning at night for about a week.**
  Among large caps, the extreme deciles are about 20 bp a night apart
  ([Aboody et al. 2018](https://anderson-review.ucla.edu/wp-content/uploads/2021/03/Aboody-et-al_overnight_returns_and_firmspecific_investor_sentiment_JFQA2018.pdf)).
  A name in the top decile might expect about +10 bp a night above average
  (calculation, half the spread). This is the one channel in the
  literature large enough to reach our per-buy numbers.
- **Where momentum comes from.** Momentum built on intraday moves (trading)
  persists without long-term reversal. Moves built overnight (news) show
  only long-term reversal
  ([Barardehi-Bogousslavsky-Muravyev](https://academic.oup.com/rfs/advance-article-abstract/doi/10.1093/rfs/hhag036/8626980)).
- **Summing the channels (calculation).**
  - The large-cap premium (+3 to +5 bp) plus the momentum tilt (+2 to
    +3 bp), plus or minus reversal (±2 to 4 bp), plus the attention and
    persistence tilt (0 to +10 bp).
  - That gives roughly **+3 to +15 bp per buy per night**.
  - At 4.2% of equity bought a session, that is **+0.1 to +0.6 bp a
    session**.
  - Our in-sample weighted +15 to +24 bp per buy (2018-2023) sits at or
    above the top of that range.
- **The dip after the open fits Berkman et al.** The first 15-minute bar
  averaged −1.2 and −7.8 bp. That is what one expects if attention demand
  lifts the open.
  - After the open our buys kept rising: +7.7 to +7.8 bp more by the fill,
    and +23 to +31 bp more by t+5.
  - That is continuation, not the "tug of war" day reversal.

**Verdict.** The literature makes a *positive* expected gain from buying
winners before the night plausible (grade A for the direction). It
supports a few bp per buy, not tens. The measured excess over that is best
treated as in-sample drift plus tails until shown otherwise.

---

## 4. Execution at the close (topic 3)

### 4.1 How big and how cheap the closing auction is

- **Its share of volume has grown.**
  - 3.1% of US volume in 2010, 7.5% in 2018 (Bogousslavsky and Muravyev
    2023, *Journal of Financial Markets* [abstract]).
  - Its peak was about 10% in 2019 (Jegadeesh and Wu 2022, *JFE*
    [abstract]).
  - In 2024 it matched about $50bn a day, "roughly 9%" of volume, and about
    20% on index-rebalance and expiry days
    ([BMLL 2025](https://www.bmlltech.com/news/market-insight/into-the-close-unpacking-u-s-closing-auction-dynamics-and-the-impact-of-the-russell-reconstitution),
    grade C).
- **It is cheap.**
  - Closing auctions "match volumes at low cost".
  - Closing prices "typically match pre-close bid or ask prices".
  - Price impact is "lower than during continuous trading".
  - Deviations "revert quickly and almost completely, on average".
  - (Bogousslavsky and Muravyev 2023 [abstract]. The 2020 conference
    version says the deviations "reverse overnight".)
  - Price impact "is lower in closing auctions than in the continuous
    market for all stocks except Nasdaq microcaps", and opening auctions
    "are illiquid". Long/short portfolios on financial ratios cost 17-41 bp
    a year to trade. Excluding microcaps and trading in closing auctions,
    that falls to 9-21 bp (Goyal, Jegadeesh and Wu 2026, *JFQA*
    [abstract]).
  - The temporary part of auction price impact takes about 3-5 days to
    dissipate, and NYSE auctions are deeper than Nasdaq's (Jegadeesh and Wu
    2022 [abstract]).
- **Industry figures.** On NYSE, auction orders up to 2.5% of CADV in
  Russell 1000 stocks move the price by about 0.3× the average daily spread
  ([NYSE, Li 2023](https://www.nyse.com/data-insights/closing-auction-immediate-market-impact-price-drift-and-transaction-cost-of-trading-part-2),
  grade C).
  - I did not find, and so do not cite, Virtu or ITG studies of the close.
- **Repo fact.** On this book the closing auction's first print sits 0.2 bp
  from the last regular print in expectation
  ([session anatomy](session-anatomy-2026-09-27.md)).
- **For our orders.** A retail-sized order in a mega-cap is a tiny fraction
  of closing volume, so our own impact is nil. What remains is the auction
  price itself:
  - it can sit at the pre-close ask when imbalances are to buy;
  - it can be dislocated on rebalance days.
  - Both are already inside C_t, which is exactly what an MOC buy pays.

### 4.2 Cutoffs and imbalance publication

- **NYSE**
  ([fact sheet](https://www.nyse.com/publicdocs/nyse/NYSE_Auctions_Closing_Process_Fact_Sheet.pdf);
  [auctions page](https://www.nyse.com/trade/auctions)):
  - MOC and LOC orders can be entered, changed or cancelled until
    **15:50 ET**.
  - After 15:50 they can be entered only on the side that offsets a
    significant imbalance, and cannot be cancelled.
  - Imbalances are published from 15:50, every second.
  - Floor-broker D orders are accepted until 15:59:50.
- **Nasdaq**
  ([closing-cross FAQ, 2025](https://www.nasdaqtrader.com/content/productsservices/trading/crosses/openclose_faqs.pdf)):
  - MOC orders must arrive before **15:55 ET**, LOC before 15:58.
    Imbalance-only orders must carry a limit.
  - The Net Order Imbalance Indicator runs from 15:50: every 10 seconds
    until 15:55, then every second.
- **The executor's broker, Alpaca**
  ([orders doc](https://docs.alpaca.markets/docs/orders-at-alpaca)):
  - "CLS orders submitted after 3:50pm but before 7:00pm ET will be
    rejected".
  - After 19:00 they queue for the next day's close.
  - They are "routed to the primary exchange" and execute under its
    auction rules.
  - **So at Alpaca the effective cutoff is 15:50 for both exchanges.** A
    15:45 decision leaves five minutes.

### 4.3 Retail access

| Broker | MOC orders | Source |
|---|---|---|
| Alpaca | yes: TIF `cls`, 15:50 ET cutoff, primary-exchange auction | [Alpaca](https://docs.alpaca.markets/docs/orders-at-alpaca) |
| Schwab (thinkorswim) | yes: MOC and LOC order types; cutoff not stated | [thinkorswim manual](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Trade/Order-Entry-Tools/Order-Types) |
| Interactive Brokers | yes: listed for all platforms; cutoff not confirmed | [IBKR](https://www.interactivebrokers.ca/en/index.php?f=599) |
| Robinhood | **no**: "doesn't currently support … Market-on-Close orders" | [Robinhood](https://www.robinhood.com/us/en/support/articles/order-types) |

- **Paper fills are not the auction.** Alpaca's paper venue does not
  document how it fills `cls` orders. It fills market orders against the
  NBBO, and it simulates neither slippage nor impact
  ([paper trading](https://docs.alpaca.markets/docs/paper-trading)).
- **This has bitten before.** The repo already saw the paper venue fail to
  fill opening-auction orders (`backend/market/alpaca_trading.py`, note on
  2026-09-08).
- **Check every live MOC fill against the official close.**

---

## 5. Deciding before the close (topic 4)

### 5.1 Implementation shortfall and the cost of delay

- **Implementation shortfall.** This is the gap between a paper portfolio
  traded at decision prices and the real one
  ([Perold 1988](https://www.pm-research.com/content/iijpormgmt/14/3/4),
  *JPM*). The move from C_t to the fill is its "delay" component.
- **Frazzini, Israel and Moskowitz (2018)**, "Trading Costs", SSRN/AQR
  working paper [full text, parts].
  - Data: $1.7 trillion of live trades, 1998-2016.
  - Mean market impact is 9.97 bp, measured from the price when trading
    starts.
  - Mean implementation shortfall is 11.02 bp. It is measured from the
    theoretical price, "the closing price at the time the strategy's
    desired holdings and trades are generated, which is typically the
    prior day's closing price". It includes opportunity cost.
  - Large caps: 8.90 bp of market impact.
  - Reading: a large institution lost about **1 bp a trade** between
    portfolio formation and the start of trading, and to opportunity cost
    (calculation: 11.02 − 9.97). Our buys' delay is **15-24 bp** weighted
    on 2018-2023.
  - Either the book's orders are unusually drift-driven, or the mean is a
    tail result. Grade B: an AQR working paper, but live data.
- **Novy-Marx and Velikov (2016)**, *RFS* [abstract]. Costs always reduce
  profitability, "increasing data-snooping concerns". A buy/hold spread is
  the best cost mitigation. Our test changes timing, not turnover, so its
  cost effect is second-order. Its data-snooping warning applies in full.

### 5.2 Signal decay when deciding at 15:45

- **The one direct test I found is practitioner** (grade C).
  - [Concretum/Zarattini (2025)](https://concretumgroup.com/when-execution-delays-erode-short-term-alpha/)
    ran a fast mean-reversion signal on SPY.
  - Close-signal filled at the close (theoretical): 31 bp per trade.
  - 15:45 signal filled MOC: 27 bp per trade, with about 61% of entries
    overlapping.
  - Close signal filled at the next open: 22 bp.
  - That is about 66% of the alpha kept with a 15-minute early decision,
    against about 49% with the overnight delay. "For fast-decaying signals
    even small execution delays matter."
- **What this means for the book.**
  - Its signal is slow: yesterday's grade plus mechanical weights. Price
    moves between 15:45 and 16:00 should change few orders.
  - The size of the change is measurable: report how many orders the 15:45
    and close decisions share, by order kind.
  - I found no peer-reviewed study of "decide at 15:45, fill MOC" against
    "decide at the close, fill next day" for slow equity signals. **The
    evidence here is thin.**

### 5.3 The last 15 minutes are not random

- **The market's last half hour continues the day.**
  - The first half hour, measured from the prior close, predicts the last
    half hour for the S&P 500 ETF on 1993-2013
    ([Gao-Han-Li-Zhou 2018](https://econpapers.repec.org/RePEc:eee:jfinec:v:129:y:2018:i:2:p:394-414),
    *JFE*).
  - In more than 60 futures, the last 30 minutes follow the rest of the
    session. This is linked to gamma hedging and reverses within days
    ([Baltussen-Da-Lammers-Martens 2021](https://econpapers.repec.org/article/eeejfinec/v_3a142_3ay_3a2021_3ai_3a1_3ap_3a377-403.htm),
    *JFE*).
  - Implication: on strong market days, an MOC buy pays a close pushed up
    late in the day, which tends to come back later.
- **Single stocks reverse into the close.** Intraday losers are pushed up in
  the last 30 minutes, 3.41 bp a day long-short for the largest stocks on
  1993-2019. The predictability disappears once the next overnight is
  included
  ([Baltussen-Da-Soebhag 2025](https://academicweb.nd.edu/~zda/EOD.pdf),
  working paper [full text, parts]).
  - Implication: an MOC buy of a name that fell during the day pays a close
    lifted by a few bp, which reverts overnight. This works *against* the
    MOC for dip-driven adds.
- **Mispricing arbitrage** unwinds into the close (Bogousslavsky 2021,
  §2.2). This works *for* the MOC when the book's names resemble the long
  leg of anomalies.
- **Net effect.** These are few-bp effects of opposite sign. None of them
  rescues or kills the idea. Record them as moderators (§8).

### 5.4 Look-ahead traps specific to this test

1. **Bar stamps.**
   - "15:45 data" must be the close of the 15:30-15:45 bar.
   - Alpaca bars are stamped at the interval *start*
     ([extended-hours source note](extended-hours-source-options-2026-09-25.md)),
     so an off-by-one reads the 15:45-16:00 bar.
2. **Grade timing.**
   - The nightly grade for day t exists only at 19:30.
   - A 15:45 decision may use only the grade from the night before, unless
     every grade input can be recomputed from data available at 15:45.
3. **After-hours information.**
   - The control's 19:30 decision can react to news between 16:00 and
     19:30 (the event buys are the extreme case).
   - That selection inflates the post-hoc C_t-to-open move, and no 15:45
     decision can have it.
   - The test compares the two policies as they would really run, so this
     is priced in. It also means the post-hoc number overstates what is
     available.
4. **Daily-bar features.**
   - Anything computed from day t's daily bar must be recomputed with the
     15:45 price, or else lagged. That includes today's return, volatility
     windows, bands and caps.
5. **Early closes and cutoffs.**
   - On half days, shift the decision and cutoff relative to the 13:00
     close.
   - Confirm the exchanges' half-day cutoffs before going live; I did not
     verify them.
   - Simulate submission latency. A decision that misses 15:50 falls back
     to the board.
6. **Price basis.** Scale fills by the session's own official close, as in
   the [execution-timing study](execution-timing-2026-09-27.md).
   `adj_close / close` does not undo splits.
7. **Funding.**
   - A buy at C_t paid for by a sale on t+1 needs cash on hand or one night
     of margin.
   - At a 5-8% annual rate that is about 1.4-2.2 bp a weeknight on the
     borrowed amount, and about three times that over a weekend
     (calculation: rate ÷ 365 per calendar day).
   - Cash that would have sat idle also loses any sweep interest for that
     night.

---

## 6. Extended-hours and overnight trading for retail (topic 5)

### 6.1 Liquidity and price quality

- **Volume is small but growing.**
  - Overnight (20:00-04:00) trading was "not quite reaching 0.11% of total
    volume and 0.15% of notional" in 2025 to June.
  - It was 61% exchange-traded products, peaking around 21:00 and 03:00 ET
    ([NYSE, Poser 2025](https://www.nyse.com/data-insights/night-moves-what-trades-and-when-in--the-overnight-market)).
  - A September 2026 law-firm note puts overnight ATS volume at about
    0.9% of daily NMS share volume, growing 359% year on year
    ([WilmerHale 2026](https://www.wilmerhale.com/en/insights/client-alerts/20260929-23x5-trading-comes-to-us-exchanges-what-firms-should-know-before-launch)).
    It does not say which period that figure covers.
  - Grade C.
- **Spreads are wider**
  ([Eaton-Shkilko-Werner 2025](https://afajof.org/management/viewp.php?n=162176),
  working paper [summary]):
  - Volume-weighted quoted spreads are 28 bp overnight against 20 bp in
    regular hours for frequently traded stocks, and 89 against 37 bp across
    the full sample.
  - Nocturnal trading is 10-20% of retail volume in the names that trade
    overnight. About 80% of it comes from Asia-Pacific.
  - Realized spreads were negative overnight for frequently traded stocks:
    liquidity providers lost to takers on average.
- **ETFs show the same gap.** Overnight spreads on iShares ETFs were
  "nearly 10 times wider" on average. IVV went from 1 to 4 bp, and SOXX
  from 2 to 22 bp. Protections such as Limit Up-Limit Down and the Order
  Protection Rule may not apply in the overnight session
  ([BlackRock 2025](https://www.blackrock.com/corporate/literature/whitepaper/blackrock-market-spotlight-24-hour-trading.pdf),
  grade C).
- **After-hours trading** in 2000 cost four to five times daytime spreads,
  with noisier prices
  ([Barclay-Hendershott 2003](https://faculty.haas.berkeley.edu/hender/after_hours_price_discovery.pdf)).
  I found no recent peer-reviewed update for large caps.
- **Earnings releases after the close** see "a significant portion of the
  price change and price discovery … immediately after the earnings
  releases" (S&P 500, 2004-2008;
  [Jiang-Likitapiwat-McInish 2012](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/information-content-of-earnings-announcements-evidence-from-afterhours-trading/39171BF13B8D5EE4890B930F2FF4E19C),
  *JFQA*).

### 6.2 Access and operational risk

- **Alpaca 24/5**
  ([doc, updated 2026-07-07](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api.md)):
  - The overnight session runs 20:00-04:00 on Blue Ocean ATS and takes
    **limit orders only**, TIF `day` or `gtc`.
  - An unfilled `day` order carries into the pre-market, regular and
    after-hours sessions.
- **Schwab** offers 24/5 trading on all S&P 500 and Nasdaq-100 stocks. Its
  disclosure lists "lower liquidity, higher volatility … wider spreads"
  ([Schwab, February 2025](https://pressroom.aboutschwab.com/press-releases/press-release/2025/Schwab-Makes-Expanded-24-Hour-Trading-Available-to-All-Clients/default.aspx)).
- **Trades can be cancelled.** On 2024-08-05 Blue Ocean cancelled trades
  from 01:45 to 03:06 ET and reopened with a limited symbol list
  ([Markets Media 2024](https://www.marketsmedia.com/blue-ocean-ats-resumes-after-cancelling-trades/)).
- **The structure is about to change.**
  - Five venues have conditional SEC approval for overnight sessions: 24X,
    Cboe EDGX, MEMX, Nasdaq and NYSE Arca.
  - Exchange overnight trading is planned to start on **2026-12-06**,
    depending on SIP readiness.
  - The sessions run Sunday to Thursday, 20:00-04:00, with a 20:00-21:00
    pause Monday to Thursday, and take limit orders only
    ([WilmerHale 2026](https://www.wilmerhale.com/en/insights/client-alerts/20260929-23x5-trading-comes-to-us-exchanges-what-firms-should-know-before-launch);
    [Jones Day 2026](https://www.jonesday.com/en/insights/2026/09/nyse-and-nasdaq-move-to-23hour-trading-day-overnight-session-is-an-evolution-but-not-yet-a-revolution)).
  - Any live result after December 2026 comes from a different market
    structure from the backtest.

### 6.3 Would an evening buy capture part of the overnight move?

- **For the average large stock, most of the night's price discovery comes
  pre-open, not in the post-close session.**
  - Pre-open accounted for 74% of close-to-open price discovery on Nasdaq
    in 2000, against 15% post-close (Barclay-Hendershott).
  - For S&P 500 stocks on 2008-2023, after-market returns average only
    about +0.9 bp (Perreten).
  - That favours an evening buy placed after the 19:30 decision.
- **Against it:**
  1. Half the quoted spread overnight is several bp even for liquid names.
     That is comparable to the *average* night's premium.
  2. Fills are uncertain with limit orders only.
  3. Dark returns partly reverse pre-market (Perreten). A buy at the
     20:00-04:00 price can pay a level that fades by 09:30.
  4. Our buys' own move may be concentrated *before* 19:30. If so, the
     decision is reacting to it and no evening order captures it.
- **Measure first (cheap, descriptive, not a trial).** Split each buy's
  C_t-to-open move into:
  - 16:00-19:30;
  - 19:30-20:00;
  - 20:00-04:00, the gap from the last post-market print to the first
    pre-market print;
  - 04:00-09:30;
  - the opening print.
  - Use the SIP's extended-hours minute bars. The one-day sample on
    2026-09-24 showed they exist for 04:00-08:00 and 17:00-20:00
    ([source note](extended-hours-source-options-2026-09-25.md)).
- **How to read the split.**
  - If most of the move comes after 20:00, an evening limit buy is worth a
    registered test on its own terms, with no 15:45 decision needed.
  - If most comes before 19:30, only a pre-close decision captures it.
- **Verdict.** Grade B at best, because the only direct decomposition
  (Perreten) is an unpublished working paper I saw only as a summary.

---

## 7. What a skeptic would say (topic 6)

### 7.1 It is compensation, not an execution edge

- **Risk.** Beta is priced overnight
  ([Hendershott-Livdan-Rösch 2020](https://econpapers.repec.org/article/eeejfinec/v_3a138_3ay_3a2020_3ai_3a3_3ap_3a635-662.htm)).
  Buying at C_t adds one night of exposure to a high-beta name, so the
  expected gain is partly pay for bearing it.
  - Against a pure risk story: overnight returns were *less* volatile than
    daytime returns (Cliff-Cooper-Gulen; Kelly-Clark).
- **Illiquidity and constraints.**
  - Arbitrageurs pay more to hold overnight (Bogousslavsky 2021).
  - Dealers are paid to carry end-of-day imbalances overnight
    (Boyarchenko-Larsen-Whelan 2023). That channel has vanished in futures
    since 2021 (NY Fed 2026).
- **Opening price pressure.** Part of the measured close-to-open is a high
  opening print (Berkman et al.; Cliff-Cooper-Gulen). It is not a return
  one can hold. The board's dip rule already recovers some of it (−1 to
  −8 bp in the first bar).
- **Our own numbers point the same way.** Weighted by order size, one
  session of the A book's drift accounts for a third to two-fifths of the
  gain on 2018-2023 and about all of it on 2024-2026 (§1). An MOC buy is
  "be invested one session earlier". It is worth what the names' next session
  is worth, and in a falling year it loses. **Report it by year** and
  alongside the change in exposure (equity-days invested).

### 7.2 Data-mining a post-hoc finding

- **How it arose.** The lead came from a diagnostic run after stage 4
  failed. The diagnostic looked at five intervals, two sides and two
  windows.
- **The t values are naive.** Orders cluster by date and overnight moves
  are market-wide.
- **The hurdle is higher than t = 2.**
  - For findings chosen from many, t > 3.0 is the recommended bar
    ([Harvey-Liu-Zhu 2016](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:1:p:5-68.),
    *RFS*).
  - Across 97 published predictors, returns were 26% lower out of sample
    and 58% lower after publication
    ([McLean-Pontiff 2016](https://ideas.repec.org/a/bla/jfinan/v71y2016i1p5-32.html),
    *JF*;
    [CFA digest](https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary)
    for the figures).
  - Deflate the Sharpe ratio for the trials actually run
    ([Bailey-López de Prado 2014](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2460551),
    *JPM*).
- **The mean is tail-driven.** On 2018-2023 the median buy's C_t-to-fill
  is −3.6 bp and only 49% of buys rose.
- **Neither window is a holdout.** 2018-2023 and 2024-2026 were both seen
  before this test was designed. The backtest can check *feasibility*
  (does the 15:45 version keep the gain?). It cannot give independent
  confirmation.

### 7.3 Regime dependence

- **The recent window is only "stronger" on simple means.** Weighted by
  order size, C_t-to-fill is +5.1 to +21.2 bp per buy on 2024-2026,
  against +19.5 to +23.6 bp on 2018-2023 (§1).
- **The drift that drives it doubled.** The A/A+ drift was 8.1 bp a
  session on 2018-2023 and 17.7 bp on 2024-2026.
- **Unusual overnight strength is a warning sign.** High smoothed overnight
  returns have forecast *weaker* markets
  ([Lou-Polk-Skouras 2024](https://personal.lse.ac.uk/loud/LouPolkSkouras.pdf)).
  Day beat night in 30% of rolling years since 2001
  ([Mackintosh 2024](https://www.nasdaq.com/articles/night-and-day)).
- **Overnight edges have faded after discovery.** The futures one
  disappeared, and a product built to harvest it closed within 14 months
  (NY Fed 2026).
- **The session structure changes on 2026-12-06** (§6.2).

### 7.4 What effect size is realistic for this book

- **In-sample gross, before 15:45 feasibility** (§1, calculation):
  - +0.8 to +1.0 bp a session on 2018-2023;
  - +0.2 to +0.9 bp a session on 2024-2026.
- **Cutting it to what can be decided at 15:45.**
  - Entries were 24% of buys by count on 2018-2023 and 29% on 2024-2026,
    and they are probably larger by weight.
  - With entries, event buys and cash-constrained adds on the board, a
    plausible share of buy weight that can move is 50-80%.
  - That gives **+0.4 to +0.8 bp a session on 2018-2023** (calculation).
- **Literature-consistent, forward-looking:** +3 to +15 bp per buy per
  night, or **+0.1 to +0.6 bp a session** (§3).
- **The +1 bp floor sits above all three.**
- **Power for live confirmation (calculation).**
  - A 20 bp per-order effect at t = 2 needs about (2 × SD / 20)² orders.
    With per-order SDs of 217-351 bp, that is 470-1,230 buys.
  - At 0.57-0.70 buys a session, that is **about 3-9 years**.
  - A paper shadow will check the fills, not the effect.

---

## 8. Design choices the literature supports (answer a)

1. **Which orders.**
   - **Buys only.**
   - **Sells stay on the next session under the board's rule.** The
     overnight premium is positive on average, and our sells saw −10.5 and
     −40.3 bp.
   - **Only buys knowable at 15:45 move to the MOC.** That means adds from
     weight drift, scheduled resets and retries, using the previous night's
     grade and cash on hand.
   - **These stay on the board:**
     - entries from the nightly grade change;
     - event buys;
     - adds paid for by next-day sales without margin.
   - A hybrid run is required: the 15:45 run handles the MOC buys, and the
     19:30 run handles the rest, seeing the MOC fills.
   - Report every result by order kind.
2. **Which decision time.**
   - The close of the 15:30-15:45 bar, with point-in-time universe and
     grades.
   - Submit by 15:50 ET, the Alpaca and NYSE cutoff. Simulate latency.
   - On early-close days, use the same offsets from the early close.
   - A missed cutoff falls back to the board.
3. **Which fill.**
   - The official close: the closing auction print, or the Nasdaq official
     closing price for Nasdaq names, from the SIP cube.
   - Scale it by the session's own close.
   - Use the last regular print only when no auction print exists, and
     flag those days.
   - Use no LOC limit in the primary arm.
4. **Which costs.**
   - Charge the scorecard's per-fill cost in both arms, so the comparison
     is cost-neutral.
   - Sensitivities:
     - +1-2 bp on MOC fills, because the close usually prints at the
       pre-close bid or ask;
     - one night of margin interest on any buy that runs ahead of its
       funding sale;
     - lost cash interest.
5. **Which statistic.**
   - The paired daily difference in book returns, in bp a session, with
     Newey-West t at lag 20. This is weighted by order size by
     construction.
   - The median across the 20 offsets, and the number of positive offsets.
   - Per order: the weighted mean, the median, the 1%-trimmed mean, the
     share positive and the contribution of the top 10 orders, with t
     clustered by date.
   - A deflated Sharpe ratio counting one primary trial.
6. **Which windows.**
   - 2018-2023 for the decision. 2024-2026 is reported, and neither window
     is tuned.
   - Say plainly that both windows were seen before registration.
   - Add annual rows, and split up and down market days.
7. **What floor is realistic.**
   - The evidence supports **+0.3 to +0.8 bp a session**, not +1.
   - Choose one before the run:
     - **Keep +1 bp** for consistency with stage 4. Expect "recorded, not
       acted on".
     - **Or pre-register two tiers.**
       - ≥ +1 bp with t ≥ 2 on 2018-2023 means act.
       - +0.5 to +1 bp with t ≥ 2, and a positive sign on 2024-2026, means
         adopt MOC buys as a no-cost default. This rests on the change
         being free at the broker and low risk, not on an alpha claim.
   - Given its power (standard error about 0.76 bp), 2024-2026 can only be
     asked for sign and size, not t ≥ 2.
8. **Diagnostics, not trials, fixed in advance.**
   - **A 2×2** of decision time (15:45 or 19:30) against fill (MOC at C_t
     or the board next day).
     - The 19:30-decision, MOC-at-C_t cell is infeasible and serves only
       as an upper bound.
     - The 15:45-decision, board cell isolates the cost of deciding early.
   - **The overnight split by time** (§6.3).
   - **Moderators:**
     - order kind;
     - the day-t open-to-close sign (reversal);
     - the trailing 5-session overnight-return sum (Aboody persistence);
     - the market's day-t return (sell-off reversals, Boyarchenko et al.);
     - earnings or news nights;
     - index-rebalance and expiry days;
     - year.
   - **How many orders the 15:45 and close decisions share.**
9. **If adopted.**
   - Paper-trade `cls` buys and compare every fill with the official close.
   - Do not expect live data to confirm the size of the effect for years
     (§7.4).
   - Re-check after 2026-12-06.

---

## 9. Prior (answer b)

- **P(2018-2023 ≥ +1.0 bp a session, with Newey-West t ≥ 2) ≈ 10%**
  (range 5-25%).
  - The weighted in-sample gross is already +0.8 to +1.0 bp before any
    cost of deciding at 15:45.
  - The part that can be decided at 15:45 is plausibly half to four-fifths
    of it.
  - The upper end of the range covers the case where every grade input can
    be recomputed at 15:45 and entries become movable.
- **P(the above, and on 2024-2026 positive with ≥ +0.5 bp a session)
  ≈ 5%.** This is ≈ 50% conditional. The weighted 2024-2026 gross is +0.2
  to +0.9 bp, and the standard error is about 0.76 bp.
- **Under the strict reading** (2024-2026 also ≥ +1 bp with t ≥ 2):
  **≈ 1-2%**.
- **For calibration:**
  - P(2018-2023 positive with t ≥ 2 at any size) ≈ 50%.
  - Expected point estimates: about **+0.5 bp a session on 2018-2023**,
    and **+0.4 bp** on 2024-2026 with t near 1.
  - Under the two-tier floor, the chance of reaching at least the default
    tier is about 30%. That tier is ≥ +0.5 bp with t ≥ 2 on 2018-2023, and
    a positive sign on 2024-2026.

---

## References

Each entry was located by web search on 2026-09-29. The flags say what I
read.

**Overnight and intraday returns**

- Cliff, M. T., Cooper, M. J., and Gulen, H. (2008). "Return Differences
  between Trading and Non-Trading Hours: Like Night and Day." SSRN working
  paper 1004081.
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=1004081)
  [abstract; figures via CXO summary]
- Kelly, M. A., and Clark, S. P. (2011). "Returns in trading versus
  non-trading hours: The difference is day and night." *Journal of Asset
  Management* 12(2): 132-145.
  [Springer](https://link.springer.com/article/10.1057/jam.2011.2) [abstract]
- Berkman, H., Koch, P. D., Tuttle, L., and Zhang, Y. J. (2012). "Paying
  Attention: Overnight Returns and the Hidden Cost of Buying at the Open."
  *JFQA* 47(4): 715-741.
  [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/abs/paying-attention-overnight-returns-and-the-hidden-cost-of-buying-at-the-open/F9AAD159B512C651F09D5D52011D88E0)
  [abstract]
- Aboody, D., Even-Tov, O., Lehavy, R., and Trueman, B. (2018). "Overnight
  Returns and Firm-Specific Investor Sentiment." *JFQA* 53(2): 485-505.
  [EconPapers](https://econpapers.repec.org/RePEc:cup:jfinqa:v:53:y:2018:i:02:p:485-505_00)
  [full text]
- Lou, D., Polk, C., and Skouras, S. (2019). "A tug of war: Overnight
  versus intraday expected returns." *JFE* 134(1): 192-213.
  [PDF](https://personal.lse.ac.uk/polk/research/TugOfWar.pdf) [full text]
- Hendershott, T., Livdan, D., and Rösch, D. (2020). "Asset pricing: A
  tale of night and day." *JFE* 138(3): 635-662.
  [EconPapers](https://econpapers.repec.org/article/eeejfinec/v_3a138_3ay_3a2020_3ai_3a3_3ap_3a635-662.htm)
  [abstract]
- Bogousslavsky, V. (2021). "The cross-section of intraday and overnight
  returns." *JFE* 141(1): 172-194.
  [EconPapers](https://econpapers.repec.org/article/eeejfinec/v_3a141_3ay_3a2021_3ai_3a1_3ap_3a172-194.htm)
  [abstract]
- Akbas, F., Boehmer, E., Jiang, C., and Koch, P. D. (2022). "Overnight
  returns, daytime reversals, and future stock returns." *JFE* 145(3):
  850-875.
  [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0304405X21004116)
  [abstract]
- Barardehi, Y. H., Bogousslavsky, V., and Muravyev, D. "What Drives
  Momentum and Reversal? Evidence from Day and Night Signals." *Review of
  Financial Studies*, forthcoming (advance article,
  doi:10.1093/rfs/hhag036; SFS listing August 2025).
  [OUP](https://academic.oup.com/rfs/advance-article-abstract/doi/10.1093/rfs/hhag036/8626980);
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4069509);
  [SFS](https://sfs.org/rfs-forthcoming-paper-95/) [abstract]
- Bondarenko, O., and Muravyev, D. (2023). "Market Return Around the
  Clock: A Puzzle." *JFQA* 58(3): 939-967.
  [EconPapers](https://econpapers.repec.org/RePEc:cup:jfinqa:v:58:y:2023:i:3:p:939-967_1)
  [abstract]
- Boyarchenko, N., Larsen, L. C., and Whelan, P. (2023). "The Overnight
  Drift." *Review of Financial Studies* 36(9): 3502-3547.
  [IDEAS](https://ideas.repec.org/a/oup/rfinst/v36y2023i9p3502-3547..html)
  [abstract]
- Boyarchenko, N., Larsen, L. C., and Whelan, P. (2026, July 1). "The
  Disappearing Overnight Drift." Federal Reserve Bank of New York, *Liberty
  Street Economics*.
  [link](https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/)
  [full text]
- Lou, D., Polk, C., and Skouras, S. (2024). "The Day Destroys the Night,
  Night Extends the Day: A Clientele Perspective on Equity Premium
  Variation." Working paper, July 2024.
  [PDF](https://personal.lse.ac.uk/loud/LouPolkSkouras.pdf) [summary]
- Glasserman, P., Krstovski, K., Laliberte, P., and Mamaysky, H. (2025).
  "Does Overnight News Explain Overnight Returns?" arXiv:2507.04481.
  [arXiv](https://arxiv.org/abs/2507.04481) [full text, parts]
- Ahn, Y., Fan, A. Q., Noh, D., and Park, S. (2024). "Retail Trading
  Intensity and the Overnight-Intraday Return Gap." Working paper,
  February 2024. A later SSRN version is titled "Retail Ebb and Flow and
  the Overnight–Intraday Return Gap."
  [PDF](http://donnoh.com/documents/ahn_fan_noh_park_2024.pdf);
  [SSRN](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4752520)
  [full text of the 2024 version]
- Barber, B. M., Huang, X., Odean, T., and Schwarz, C. (2022).
  "Attention-Induced Trading and Returns: Evidence from Robinhood Users."
  *Journal of Finance* 77(6): 3141-3190.
  [EconPapers](https://econpapers.repec.org/RePEc:bla:jfinan:v:77:y:2022:i:6:p:3141-3190)
  [abstract]
- Haghani, V., Ragulin, V., and Dewey, R. (2022). "Night Moves: Is the
  Overnight Drift the Grandmother of All Market Anomalies?" Elm Wealth.
  [link](https://elmwealth.com/night-moves-overnight-drift/) [practitioner]
- Mackintosh, P. (2024). "Like Night and Day." Nasdaq.
  [link](https://www.nasdaq.com/articles/night-and-day) [practitioner]

**Closing auction and execution**

- Bogousslavsky, V., and Muravyev, D. (2023). "Who trades at the close?
  Implications for price discovery and liquidity." *Journal of Financial
  Markets* 66: 100852.
  [IDEAS](https://ideas.repec.org/a/eee/finmar/v66y2023ics1386418123000502.html);
  2020 version at the
  [AEA](https://www.aeaweb.org/conference/2021/preliminary/paper/H9T4hef7)
  [abstracts]
- Jegadeesh, N., and Wu, Y. (2022). "Closing auctions: Nasdaq versus NYSE."
  *JFE* 143(3): 1120-1139.
  [EconPapers](https://econpapers.repec.org/RePEc:eee:jfinec:v:143:y:2022:i:3:p:1120-1139)
  [abstract]
- Goyal, A., Jegadeesh, N., and Wu, Y. (2026). "Price Impact in Closing
  Auctions, Opening Auctions, and Continuous Markets: A Benchmark for Cost
  of Trading on Anomalies." *JFQA*, online March 5, 2026,
  doi:10.1017/S0022109026102592.
  [Cambridge](https://www.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/price-impact-in-closing-auctions-opening-auctions-and-continuous-markets-a-benchmark-for-cost-of-trading-on-anomalies/0F72910A79C5B42CF6E85F55164CE846)
  [abstract]
- Li, C. (2023). "Closing Auction: Immediate market impact, price drift
  and transaction cost of trading (part 2)." NYSE.
  [link](https://www.nyse.com/data-insights/closing-auction-immediate-market-impact-price-drift-and-transaction-cost-of-trading-part-2)
  [exchange]
- Laible, R., and Thakur, S. (2025). "Into the Close: Unpacking U.S.
  Closing Auction Dynamics and the Impact of the Russell Reconstitution."
  BMLL.
  [link](https://www.bmlltech.com/news/market-insight/into-the-close-unpacking-u-s-closing-auction-dynamics-and-the-impact-of-the-russell-reconstitution)
  [vendor]
- NYSE, "NYSE Closing Process" fact sheet and
  [auctions page](https://www.nyse.com/trade/auctions);
  Nasdaq, "The Nasdaq Opening and Closing Crosses" FAQ (2025);
  Alpaca, [orders](https://docs.alpaca.markets/docs/orders-at-alpaca),
  [paper trading](https://docs.alpaca.markets/docs/paper-trading) and
  [24/5](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api.md);
  Schwab
  [thinkorswim order types](https://toslc.thinkorswim.com/center/howToTos/thinkManual/Trade/Order-Entry-Tools/Order-Types);
  [IBKR MOC](https://www.interactivebrokers.ca/en/index.php?f=599);
  [Robinhood order types](https://www.robinhood.com/us/en/support/articles/order-types).
  [primary documents]
- Perold, A. F. (1988). "The Implementation Shortfall: Paper versus
  Reality." *Journal of Portfolio Management* 14(3): 4-9.
  [JPM](https://www.pm-research.com/content/iijpormgmt/14/3/4)
  [citation only; pages via the Wikipedia reference list]
- Frazzini, A., Israel, R., and Moskowitz, T. J. (2018). "Trading Costs."
  SSRN working paper 3229719 (AQR).
  [AQR](https://www.aqr.com/Insights/Research/Working-Paper/Trading-Costs)
  [full text, parts]
- Novy-Marx, R., and Velikov, M. (2016). "A Taxonomy of Anomalies and
  Their Trading Costs." *RFS* 29(1): 104-147.
  [EconPapers](https://econpapers.repec.org/RePEc:oup:rfinst:v:29:y:2016:i:1:p:104-147.)
  [abstract]
- Zarattini, C. (2025). "When Execution Delays Erode Short-Term Alpha."
  Concretum Group.
  [link](https://concretumgroup.com/when-execution-delays-erode-short-term-alpha/)
  [practitioner]

**End of day**

- Gao, L., Han, Y., Li, S. Z., and Zhou, G. (2018). "Market intraday
  momentum." *JFE* 129(2): 394-414. [abstract]
- Baltussen, G., Da, Z., Lammers, S., and Martens, M. (2021). "Hedging
  demand and market intraday momentum." *JFE* 142(1): 377-403. [abstract]
- Baltussen, G., Da, Z., and Soebhag, A. (2025). "End-of-Day Reversal."
  Working paper, April 2025.
  [PDF](https://academicweb.nd.edu/~zda/EOD.pdf) [full text, parts]

**Extended hours and overnight**

- Barclay, M. J., and Hendershott, T. (2003). "Price Discovery and Trading
  After Hours." *RFS* 16(4): 1041-1073.
  [PDF](https://faculty.haas.berkeley.edu/hender/after_hours_price_discovery.pdf)
  [full text, parts]
- Jiang, C. X., Likitapiwat, T., and McInish, T. H. (2012). "Information
  Content of Earnings Announcements: Evidence from After-Hours Trading."
  *JFQA* 47(6): 1303-1330. [abstract]
- Eaton, G. W., Shkilko, A., and Werner, I. M. (2025). "Nocturnal
  Trading." Working paper, March 2025.
  [AFA](https://afajof.org/management/viewp.php?n=162176) [summary]
- Perreten, T. (2026). "Price Discovery Overnight: Evidence from Pre- and
  After-Market Trading." Working paper, University of Fribourg, February
  2026.
  [link](https://mfc3.eventsadmin.com/Papers/ViewContribution?cid=14387&h=34E9F3229E21B084DE4A06E94CD0FC5F)
  [summary]
- Poser, S. W. (2025). "Night Moves: What Trades and When in the
  Overnight Market." NYSE.
  [link](https://www.nyse.com/data-insights/night-moves-what-trades-and-when-in--the-overnight-market)
  [exchange]
- BlackRock (2025). "Market Spotlight: 24 Hour Trading."
  [PDF](https://www.blackrock.com/corporate/literature/whitepaper/blackrock-market-spotlight-24-hour-trading.pdf)
  [vendor]
- Markets Media (2024, August 7). "Blue Ocean ATS Resumes After Cancelling
  Trades."
  [link](https://www.marketsmedia.com/blue-ocean-ats-resumes-after-cancelling-trades/)
- Charles Schwab (2025, February 12). "Schwab Makes Expanded 24-Hour
  Trading Available to All Clients."
  [link](https://pressroom.aboutschwab.com/press-releases/press-release/2025/Schwab-Makes-Expanded-24-Hour-Trading-Available-to-All-Clients/default.aspx)
- WilmerHale (2026, September 29). "23x5 Trading Comes to US Exchanges."
  [link](https://www.wilmerhale.com/en/insights/client-alerts/20260929-23x5-trading-comes-to-us-exchanges-what-firms-should-know-before-launch);
  Jones Day (2026, September). "NYSE and Nasdaq Move to 23-Hour Trading
  Day."
  [link](https://www.jonesday.com/en/insights/2026/09/nyse-and-nasdaq-move-to-23hour-trading-day-overnight-session-is-an-evolution-but-not-yet-a-revolution)
  [law firms]

**Multiple testing**

- Harvey, C. R., Liu, Y., and Zhu, H. (2016). "… and the Cross-Section of
  Expected Returns." *RFS* 29(1): 5-68. [abstract]
- McLean, R. D., and Pontiff, J. (2016). "Does Academic Research Destroy
  Stock Return Predictability?" *Journal of Finance* 71(1): 5-32.
  [citation; figures via the CFA digest]
- Bailey, D. H., and López de Prado, M. (2014). "The Deflated Sharpe
  Ratio: Correcting for Selection Bias, Backtest Overfitting and
  Non-Normality." *Journal of Portfolio Management* 40(5): 94-107.
  [abstract]

### Not verified, or not found

- **Industry studies of MOC costs.** I found no Virtu or ITG study of
  market-on-close costs, so none is cited.
- **Cutoffs I could not confirm.** Schwab's and IBKR's MOC cutoff times,
  and the exchanges' half-day cutoffs.
- **Alpaca paper fills.** How Alpaca's paper venue fills `cls` orders is
  not documented.
- **Magnitudes I could not read.**
  - Berkman et al.: I read only the abstract.
  - Cliff-Cooper-Gulen: the per-night figures come from a secondary
    summary (CXO Advisory), not the paper.
  - Hendershott-Livdan-Rösch: the units of the beta slopes were unclear,
    so none is quoted.
- **Samples and details I could not check.**
  - Bogousslavsky (2021): the sample and the list of anomalies.
  - Perreten (2026) and Eaton-Shkilko-Werner (2025): seen only through
    summary pages. Perreten's dark and pre-market magnitudes are
    approximate.
  - Ahn et al.: the SSRN version's author list, because the page was
    rate-limited.
- **No peer-reviewed evidence found for:**
  - the overnight/intraday split of momentum after 2019;
  - US retail flows and the overnight gap in 2019-2026;
  - "decide at 15:45, fill MOC" for slow equity signals.
