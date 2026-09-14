# Retail decision workflow and macro research

Design recorded September 14, 2026. This is a proposed evaluation path, not an
enabled strategy or evidence of higher returns.

Implementation checkpoint: the dashboard now has an explicit cash-limited
preview of the existing evening targets. The backend funds all additions
together, floors whole shares, subtracts existing holdings, and excludes
unexecuted sale proceeds and FOMC-paused additions. Cash stays in page memory;
holdings/equity/context changes and reload require reconfirmation. The preview
expires after fifteen minutes and labels last-known reference prices. It is not
dynamic intraday allocation or an executable-price recommendation.

The economic context now collects headline/core CPI, final-demand PPI and
headline/core PCE from FRED CSV downloads, on current nightly refreshes or through
`python -m backend.cli.market_economics`. It archives collection-time vintages,
calculates changes from exact matching calendar months, and displays collection
and observation ages separately. Publication timestamps and archived consensus
remain unavailable. Revised histories must not be backfilled into prior decisions.
DeepSeek classifies supplied inflation pressure with evidence IDs under an
agent-owned prompt; its assessment does not change grades, exposure or orders.
New-policy evaluation, dynamic intraday targets and executable quote evidence
remain unfinished.

## Objective

Help the operator decide what to own over days or weeks, how much to hold, and
when an observed entry is suitable. A fifteen-minute refresh is an observation
cadence, not a requirement to trade fifteen-minute moves. The strategy must not
depend on beating the initial CPI/PPI announcement reaction.

A [Federal Reserve-hosted study of news analytics](https://www.federalreserve.gov/econres/ifdp/first-to-quotreadquot-the-news-new-analytics-and-algorithmic-trading.htm)
found faster stock-price responses and reduced liquidity around the articles
it studied. That supports avoiding a news-speed premise; it does not establish
an exploitable later response or prove that a slower strategy has an advantage.

The intended dashboard combines current ranked candidates, dated entry evidence,
recommended total shares and additional shares, existing manual positions, and
an explicit cash constraint. A Record buy button records a completed brokerage
fill. It must not imply broker connectivity or represent a planned order as a
position. Show the signal time, relevant price/bar time, and expiration together.

## What exists today

The live analyst votes are fundamental, technical, release sentiment and value
at one vote each, rotation at half. A bearish core stance caps the grade at B;
weighted conviction orders names within the dashboard's grade buckets. The
allocation engine also considers volatility, caps, grade multipliers and regime.
Its selection score is continuous conviction, so its selections need not equal
the first rows of a grade-first display. Grades are not calibrated probabilities.

The expectations-gap learner estimates revenue growth, not share price. Its
session-relative rank is blended with relative valuation. The evening record
identifies whether the learner was actually used. The intraday plain-value
reader cannot reproduce that blend; it must not replace a growth-model vote.
Until equivalent intraday valuation is implemented, preserve the evening value
vote, refresh compatible technical evidence, and label those inputs explicitly.

Regime code measures participation, rotation, correlation shifts, theme trend
and drawdown. Rising ten-year yields can reduce exposure. A drawdown flag alone
does not trigger liquidation. The separate FOMC rule can reduce held shares.
VIX, dollar and oil features exist in the broader research model, but their
presence is not proof of an active allocation input in the trading desk.

No CPI, PPI or PCE release ingestion into the live desk's allocation was found.
Missing yield data is currently represented as no tightening signal, and the
macro alignment can carry an old observation forward without an age limit.
These are unresolved evidence-quality gaps, not confirmations of benign risk.
Evening allocations do not currently become new intraday target weights.

## How to test the intended system

1. Preserve a dated facts layer. Record each economic observation's period,
   release timestamp, retrieval timestamp, revision/vintage and units. Store
   missing/stale status independently of its value. An absence of data cannot
   count as evidence for an economic regime. A consensus surprise requires a
   real archived consensus; never fabricate it from the previous reading.
2. Let DeepSeek interpret the supplied macro and company evidence under a
   bounded schema, with evidence references and an explicit unknown result.
   It must not invent release values, forecasts, timestamps or position sizes.
   Pin each prompt with real-model functional cases before use.
3. Separate portfolio exposure from stock preference. Macro risk should inform
   a tested portfolio budget; stock grades rank candidates inside it. A leading
   stock in a weak universe does not automatically deserve a purchase. Cash is
   a valid outcome. Do not count the same rates or FOMC reduction twice.
4. Evaluate entries after observable market responses using the existing
   technical timing protocol. Compare completed-bar confirmations against the
   funded baseline. Do not assume a fixed pause after a release, a technical
   indicator, or a more elaborate prompt creates an edge. Retain candidates that
   never enter in the portfolio comparison, not just successful fills.
5. Calculate proposed shares with the shared risk engine and actual recorded
   holdings, using explicit operator-confirmed available cash. Do not use paper
   cash as real-account cash, infer settled funds from equity, or let every row
   independently spend the same cash. Recompute the whole proposal after a fill.
   Keep the current strategy's scheduled orders separate from experimental sizes.
6. Require current executable quote evidence for any actionable price range.
   A fifteen-minute IEX bar is historical trade data, not the spread or available
   size. Record observed spread/price impact and rejected or partial executions;
   trade-cost assumptions are not observed execution quality.

Use the cash-at-fill baseline and frozen decision inputs. Compare net returns,
drawdown, turnover, time invested, cash usage and recovery after false exits.
Report recessionary/bear, inflationary, rising and sideways periods separately,
using only classifications available at the decision time. Retain all tested
variants and reserve later forward decisions as a holdout. New logic stays a
separate research track until that comparison justifies promotion.

## Source data references

The [BLS CPI methodology](https://www.bls.gov/opub/hom/cpi/concepts.htm) describes
consumer price measurement; the [BEA PCE price index](https://www.bea.gov/data/personal-consumption-expenditures-price-index)
provides a separate inflation measure. These are data sources, not trading
signals by themselves. [FRED real-time periods](https://fred.stlouisfed.org/docs/api/fred/realtime_period.html)
and [ALFRED vintages](https://alfred.stlouisfed.org/help) support reconstructing
what was reported at a historical date. Using today's revised history in an
earlier simulated decision would contaminate the proposed evaluation.
