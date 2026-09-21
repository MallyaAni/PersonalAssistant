# Portfolio exposure objective clarified by the user

The user wants to maximize returns by owning individual stocks at favorable
prices, shifting toward cash or indexes when conditions deteriorate, and
participating promptly in recoveries. The immediate concern is large losses
in volatile names on bad market days. The user explicitly named **SPY and
QQQ as the benchmarks for both gains and drawdown limits**. This supersedes
the earlier uncertainty about an absolute drawdown percentage. Do not invent
one, and do not describe a relative drawdown target as a guaranteed loss limit.

This changes the next strategy priority from marginal entry timing to joint
portfolio exposure and allocation. The current live fundamental correction
continues first because its inputs are used by the decision engine.

## Decision contract

1. Estimate how much total equity risk the account can carry from information
   actually available at the decision time. Consider portfolio volatility,
   cross-stock correlation, broad-market weakness and participation, liquidity
   and scheduled event exposure; missing inputs must be explicit. Test simple
   controls before a learned forecaster.
2. Allocate that budget across eligible stocks and an explicit index holding.
   Stock selection must justify its incremental risk relative to the index.
   An index reduces individual-company concentration, not broad-market risk.
3. Allocate defensive capital explicitly among cash, eligible money-market
   instruments and eligible bonds/treasuries. User named SWVXX as an example:
   it is a prime money-market mutual fund, not a conventional bond fund.
   These buckets are not interchangeable. Model income, duration, credit and
   liquidity risk, fund availability and actual dealing/settlement times.
   Do not simulate a mutual fund as an instant-fill ETF or equate its yield
   with a guaranteed cash rate. If the connected broker cannot trade an
   instrument, mark it unavailable; do not invent an executable order.
4. Use one shared implementation for target calculation, order previews and
   historical/forward simulation. Risk reductions need explicit priority over
   ordinary rotation and sell-deferral rules. Include a re-entry rule so a
   protection policy is judged on the recovery as well as the decline.
5. Keep the single stock table and BUY/HOLD/SELL enum. Index and cash exposure,
   current versus target allocation, and the reason for a change must be clear
   without adding competing recommendation tables.

## Broad selloffs and unusual shocks

The user explicitly wants a defensive response to bear markets and unusual
events such as COVID, rather than remaining fully exposed to volatile stocks.
Use general observable market stress and portfolio risk measurements; do not
hardcode hindsight labels or an event's subsequently known crash dates into
the decision rule. A rapid risk-reduction path and a measured re-entry path
must both be tested. An unforeseen gap can occur before any signal or order;
the system cannot promise to detect every shock before losses start.

Test distinct scenarios: abrupt equity/liquidity shock, prolonged bear trend,
inflation/rate shock where duration may lose alongside stocks, and rapid
rebound/false alarm. Bonds must earn their defensive allocation under the
relevant risks; do not assume all bonds hedge all equity declines. Keep this
as one integrated allocation decision and one funded account, with realistic
cash timing, rather than disconnected per-asset backtests.

Instrument references: [Schwab SWVXX product page](https://www.schwabassetmanagement.com/products/swvxx)
and [SEC Investor.gov bond fund risks](https://www.investor.gov/introduction-investing/investing-basics/glossary/bond-funds-and-income-funds).

## Evaluation before adoption

Primary objective: outperform both SPY and QQQ in net compounded returns,
with no larger peak-to-trough drawdown than either, on the SAME evaluation
window. Report each comparison separately; do not choose the easier benchmark
after observing results or silently average them into a blended benchmark.
If a policy only wins on returns or only wins on drawdown, label that trade-off
explicitly rather than calling the objective achieved. This is a performance
target, not a promise of dominance in every interval or an executable stop
calculated using a benchmark's future drawdown.

Use dividend-inclusive total-return buy-and-hold SPY and QQQ controls,
identical start/end sessions and starting capital, explicit execution costs
and consistent cash income assumptions. Include full-window and predeclared
rolling/regime comparisons so a favorable aggregate cannot conceal sustained
underperformance. Report worst day/week and recovery alongside max drawdown.
Historical benchmark drawdowns may judge an experiment afterwards; they must
never enter an earlier decision as a future-informed risk threshold.

Optimize net compounded portfolio outcomes, not signal classification
accuracy or an isolated stock's hit rate. Compare the incumbent, index-only
controls and simple exposure controls on identical executable calendars,
costs, starting capital and cash assumptions. Report net growth, maximum
drawdown and recovery time, worst day/week and average worst-tail loss,
upside/downside participation, turnover and missed rebound returns.

Distinguish protection from simply holding less risk: include exposure- or
risk-matched comparisons. Count false exits, re-entry delay and trading costs.
Show a return/downside frontier relative to BOTH named benchmarks. Freeze a
small candidate set and its definitions
before looking at outcomes; do not mine the reused 2024–2026 sample for
winning thresholds. Future-session evidence remains necessary for promotion
of a learned allocation policy.

Published work motivates testing volatility-managed exposure but does not
validate this desk: [Moreira and Muir, Volatility Managed Portfolios](https://www.nber.org/papers/w22208).
Trend-based protection can also experience drawdowns and weaker performance;
it is not an oracle for impending red days: [AQR, You Can't Always Trend When You Want](https://www.aqr.com/insights/research/journal-article/you-cant-always-trend-when-you-want).

## Known implementation boundary

Current regime controls include participation and a 60-session yield-change
rule. The simulator normally assigns zero target weight to its benchmark.
The existing event-risk path can override ordinary exit deferral for specific
events; it is not a general stock/index/cash allocation engine. These are
source observations, not an assertion that any proposed replacement is
already implemented or better. Inspect the actual live execution path before
extending it. Preserve the existing frozen research ledgers and avoid double
applying an exposure reduction.

The next acceptance milestone after the data correction is a bounded,
executable stock/index/cash allocation path with measured downside and
re-entry behavior. Another entry-price model alone does not satisfy this
objective. Do not stop supervision merely because the fundamental patch is
finished; carry this clarified portfolio objective into the next work unit.
