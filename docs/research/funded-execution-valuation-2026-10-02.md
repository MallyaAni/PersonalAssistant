# Consolidated valuation supplement

Registered before scoring the October 2 forward cohort. The ongoing experiment
and its code/inputs remain frozen; no recorded decision or conditional fill is
changed. An integrity check found 221 wide IEX valuation quotes among the first
455 checks. A single venue's bid is not a reliable consolidated portfolio mark.

Fetch only two fixed 30-second historical SIP quote windows, ending at the frozen
first observation and the final observation (capped immediately before the
regular close). Query only frozen starting holdings, opportunity symbols, SPY
and QQQ. Requests must be at least 16 minutes after the window endpoint, retain
all original response bytes/hashes and pagination links, and stop on refusal or
an incomplete/contradictory chain. No paid entitlement or fallback feed.

At each endpoint select the latest source event at or before that endpoint,
preserving nanosecond order. Missing, invalid, stale, crossed or greater-than-25-bp
quotes make that symbol unavailable; never skip an invalid latest event to use
an older favorable price. These delayed observations are outcome labels only,
not evidence that the decision had SIP access at the time.

Revalue the original starting holdings and each arm's unchanged ending cash and
holdings at consolidated bids. Retain the original 10/25-bp costs and conditional
IEX displayed-liquidity attempts. Report total return, paired gain, ending cash,
turnover and same-capital SPY/QQQ quote references. With endpoint marks only,
consolidated drawdown is unavailable. Missing marks remain unavailable, and no
CAGR, annualized Sharpe, broker-fill proof or policy adoption follows from this
partial session. Original IEX proxy metrics remain separate and unchanged.

Provider contract: [historical quotes](https://docs.alpaca.markets/us/reference/stockquotes-1)
requires complete pagination; [data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq)
explains the 15-minute recent-SIP restriction and IEX/SIP coverage difference.
