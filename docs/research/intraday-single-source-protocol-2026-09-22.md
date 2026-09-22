# Fixed single-source entry diagnostic

Declared before outcome scoring on 2026-09-22. The reviewed two-provider cache
cannot currently support reliable comparison. This bounded diagnostic derives
both daily reference closes and intraday entries from the same fresh IEX
15-minute snapshot requested with adjustment=all. It never repairs old caches.

The fixed cohort is AVGO, WRB, WDC, APTV (selected for previously identified
adjustment failures), plus SPY and QQQ (benchmark instruments). This small,
deliberately selected cohort cannot estimate universe-wide strategy performance.
Requested entry sessions are all full exchange sessions from 2026-08-03 through
2026-09-18 inclusive. Source dates are 2026-06-29 through 2026-09-18. Label
data_as_of is 2026-09-18 at 16:00 America/New_York. No dates, names, thresholds or
horizons will be changed after observing outcomes to improve the result.

Daily reference closes come only from complete regular sessions in the same
snapshot, with full20 preceding exchange-session coverage. Early-close sessions
count in the history and horizons. Entry-day data is evaluated by causal prefix;
later missing/invalid bars cannot delete an earlier opportunity. Missing inputs
retain their requested denominator with a reason. Label windows remain20 sessions
primary and5 secondary; immature/missing outcomes remain explicit.

Both methods use identical supplied inputs and the existing frozen mapping.
The reviewed replay runs in price-component mode without inventing historical
grades. It compares the incumbent entry formula and experimental entry sequence,
NOT exact live momentum, historical portfolio performance or personal turnover.
Changing the daily source from Yahoo to IEX regular-session closes is an explicit
contract change confined to this diagnostic. Current live strategy is unchanged.

Execution remains zero added cost, next consecutive regular bar open at actual
event observation, an optimistic zero-latency proxy rather than a midpoint fill.
Raw response text, SHA256 hashes, requested adjustment/feed/range, page tokens
and fetch timestamps are retained outside frozen caches. Fresh retrospective
adjustments are not point-in-time data vintages or independently audited action
factors. Results may support debugging and a forward test, never a profitability
or superiority claim by themselves. No orders, paid data, model/service or UI
changes, fitted transformations or outcome-based symbol exclusions are permitted.

Provider adjustment definitions: [Alpaca historical bars](https://docs.alpaca.markets/us/v1.4.2/reference/stockbars).
The explicit all mode includes split, dividend and spin-off adjustments. Shared
response rows avoid mixing providers' conventions; they do not prove the
provider's underlying prices or adjustments are error-free.
