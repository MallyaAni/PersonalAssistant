# Held-B retention: fixed funded comparison

Objective: measure whether learned stock-specific holding forecasts improve
sale-versus-hold decisions inside the existing daily reset/rotation book.
VERIFIED: pure retention planning and purged monthly heads pass88source-image
cases atb68682cf; nonlinear execution timing at7575711c is independently scored
but has not established a recent advantage. UNVERIFIED: real daily fits,
account-aware retention, funded gains, exact live execution and adoption.

This protocol is frozen before real daily fitting or economic outcomes. It is
one selection intervention, not a model/threshold search. The already registered
daily head configuration and labels stay unchanged. Do not refit old timing
models, rerun their old account controls or select subgroups from these results.

## Sources and opportunity set

Reuse the original snapshot SHA8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58
and its96original daily parquet source hashes (94stocks plusSPY/QQQ). Frozen
vintage2026-09-30, supplied2016onward calendar, fixed evaluation2018-02-01 through
2026-09-30. The actual source OHLCV must match the snapshot open/close/adjusted
close bytes numerically and cover the reviewed exchange calendar. Daily OHLC is
already split-adjusted; adjusted_close/close is its remaining adjustment factor.
No raw intraday cube conversion, provider calls, missing-data interpolation,
price-ratio fitting, grade filling or removal of inconvenient symbols/sessions.
Hash-authenticate every original source before deriving a Panel; changed or
missing sources halt preparation with an explicit reason.

Grades and universe are a current-vintage reconstruction. They are common to
all arms but not attested historical publications or tradable point-in-time
selection. Label endpoint availability is a supplied historical opening clock,
not the time a later cache was written. Recent2026-08-17..09-30 is reused.

## Heads and planning

Use the [registered daily model contract](learned-retention-plan-2026-10-03.md):
13completed-close features; pooled stock-minusSPY10-session log-return mean
and separate absoluteSPYmean; open[t+1] to open[t+11]; monthly whole-date purge,
strictly prior endpoints and post-Aug17 endpoint freeze; minimum504distinct
mature feature-valid dates in a maximum756calendar decision rows. Existing
64tree/15leaf HGB config remains fixed. Missing forecasts use the incumbent.
The exponentiated mean forecast is a plug-in comparison, not expected wealth.

An opt-in planning adapter acts at BOTH scheduled resets and ordinary daily
rotation, before execution. On a reset it compares the B holding with the
incumbent's declared purchase shortfalls/cash destination, reserves retained
marked weight and allocates only remaining weight to unchanged eligible A/A+
targets. With no retained name return the original target bit exactly.

On a midcycle session compute the counterfactual rotation's actual capped
purchase proposals with paper._rotation_orders and current holdings/marks.
Divide their dollar amounts by that batch's gross released sale dollars;
unallocated proceeds are cash, requiring the SPY forecast. This declared
counterfactual basket is a forecast proxy, not claimed realized reinvestment:
today's buys can only use cash already present and purchases may be deferred.
After retention, recompute the shared planner with removed B exits and those
B names purchase-blocked. Do not add to retained B. Recipient caps and required
forecasts are checked without dropping/renormalizing unknown recipients.

C/unknown/ineligible names and explicit mandatory exits preserve incumbent
behavior. FOMC lifecycle supersedes the adapter and uses existing cut/restore
account state. Buy-blocking alone does not liquidate an existing B. Trim any
retained holding only to the existing25%hold cap; no new learned risk limit.
The ordinary rotation's15%entry cap, buy blockers and minimum trade convention
remain unchanged. Invalid adapter inputs refuse; unavailable valid forecasts
fall back. Invalid destination capacity is recorded and preserves the incumbent
proposal rather than fitting a different basket.

## Accounts and controls

Three arms: unchanged incumbent, learned retention, unconditional eligible-B
retention with the same mandatory overrides and cap. The third is a mechanism
control; do not manufacture forecasts to implement it. No choice among arms
after scoring. Twenty reset offsets0..19, NAV1, continuously carried fractional
adjusted shares/cash, zero cash yield,0/10/25bp per side. Each arm has its own
holdings, deferred purchases, reset clock and FOMC lifecycle state. Benchmarks
SPY and QQQ are separately funded next-open buy-and-hold accounts over the same
fixed dates. Do not compound independent reset books into an alleged live NAV.

Both stock arms use exactly the existing _live_rules_options daily execution:
next-open buys, legacy next-close sells, green-open sell deferral, presale cash
funding and shared deferred purchase handling. Daily early-close sessions use
their recorded daily opens/closes; this does not prove intraday early-close,
current1%dip/pop executor or broker-fill parity. No actual paper/real orders.
An all-unavailable forecast adapter must match the incumbent's account journal,
orders, state transitions, cash/holdings and metrics bit exactly before fitting.

## Acceptance and report

Before economic scoring: complete source/provenance/date/basis validation;
real small-fit behavior; head-specific warmup/purge; future-prefix invariance;
unavailable fallback parity; no B additions or uncovered sales; retained reserve
across resets; ordinary versus mandatory exits; actual cash/fees/deferred buys;
FOMC priority; unchanged default simulator path; immutable source/artifact identity.
Saved models/forecasts and account journals must be independently authenticated
and reconciled without refitting or strategy resimulation.

Report every cost/offset and paired net gain first, then CAGR, positive drawdown
loss, Sharpe,252-session rolling benchmark win rates, fees, turnover, B retention
counts and unavailable/missed opportunities. Fixed full,2018-20,2021-26 and reused
recent windows. Report causal prior-SPY trend/volatility diagnostics as descriptive
means, not retrospectively switchable compounded regime performance. Include
unconditional retention to distinguish forecast value from simply selling less.

No historical diagnostic alone promotes a policy. A credible replacement needs
stable funded gains across offsets/costs/subperiods, acceptable drawdown/turnover,
benefit over unconditional retention and verified current live-intent/funding/
receipt compatibility on new evidence. Any uncertainty or contrary result remains
visible. Keep working on the first unsupported boundary; no hindsight threshold,
window, symbol, model or outcome selection to manufacture an adoption claim.
