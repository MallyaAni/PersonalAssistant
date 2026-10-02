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

## Provider correction before scoring

The first actual start-window request returned HTTP 200 and 8,533 records in one
page. Version 1 rejected 64 differing records sharing an earlier timestamp;
timestamps are not unique provider event identities. No endpoint outcome or
policy score was produced. Version 2 preserves the same immutable response:
earlier timestamp ties do not invalidate a later unique event; differing records
at the latest timestamp make that symbol's mark explicitly ambiguous/unavailable.
No row-order tie-break or favorable-price selection. The start response is reused
without another request. This corrects source interpretation, not a budget or
strategy threshold. The frozen execution implementation remains unchanged.

The start window leaves NTAP unavailable under the fixed spread budget; it is a
starting holding. Total NAV/return and same-capital benchmark gains therefore
remain unavailable if that starting mark is missing. Paired absolute gain can
still be identified when missing holdings have identical quantities in both
arms: cancel those common positions algebraically, and require ending marks for
every quantity difference. This does not provide a percentage return, benchmark
comparison or missing stock price. The accounting case is pinned separately.

## Auction state correction before scoring

The full clock-path acceptance reproduced a v1 replay defect: a qualified MOC
decision was recorded as unsupported, but a later observation could invent a
market fallback although the live order would already be queued. All five real
cohort opportunities encounter that boundary. No real policy score was produced;
the pending v1 scoring watcher was stopped, while recording completed normally.

Evaluation version 2 makes unsupported auction outcomes terminal and withholds
the affected ending wealth, return and paired gain. The native-engine adapter
has the same terminal guard. Raw recording version 1 and its hashes remain
unchanged; the reader accepts only the exact verified original recorder hash
with every other implementation hash still matching, and reports recording and
evaluation identities separately. This is a correctness fix, not a strategy or
budget change. Actual paper-broker receipts are the next evidence boundary;
auction prices must not be inferred from bars or ordinary quotes.

## Observed closing-outcome supplement before gain calculations

The matched GET-only paper receipts show two filled `market/cls` orders and three
expired orders, submitted after the cohort began. Their prices have not been used
for gain calculations. Retain the original unsupported-auction comparison, and
add a separately identified closing supplement using these actual terminal
receipts. Validate raw byte hashes, client identity, symbol/side, quantities,
submission/filled/receipt clocks and terminal status. Missing or still-working
orders stay unknown. Expired zero-fill orders remain zero-fill outcomes.

Apply recorded average execution prices and quantities only to the control's
previously unsupported auctions, with the same 10/25-bp stress and starting cash.
Stress resizing is explicit: reported broker quantity and modelled funded
quantity remain distinct. Treat the closing auctions as one funding batch:
their sale proceeds do not fund that batch's buys. The candidate still uses only
the original observed IEX evidence and conditional displayed-liquidity attempts.
No new candidate attempt is invented for the unsampled last 15 seconds.

For this separately named supplement, value both resulting books at the fixed
regular closing instant using delayed SIP endpoint labels. Original sampled
interval and unsupported proxy results remain unchanged and separate. This is a
fixed-intent component comparison, not an exact full live-policy reconstruction,
actual candidate fills or an adoption test. The original missing NTAP starting
mark still prevents total-return/wealth-based benchmark claims; identifiable
paired absolute gain remains separate. No budgets or strategy windows are tuned.
