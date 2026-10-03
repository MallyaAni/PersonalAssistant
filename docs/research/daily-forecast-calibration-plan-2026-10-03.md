# Saved holding-forecast calibration — fixed diagnostic protocol

Registered after the combined allocation experiment, before reading any forecast
error cells. This is a diagnostic on already reused data, not a new untouched
test, policy variant or authorization to promote a strategy. Do not fit, refit,
refetch, simulate accounts, tune parameters or choose stocks/windows from results.

VERIFIED: source 63c21f68 implemented funded growth sizing and both execution
clocks. Independent artifact proof covers all 120 new accounts. FAILED: growth
sizing loses against the equal-weight rule component with either clock.
UNVERIFIED: forecast calibration and whether entry-clock or holding-horizon
compatibility explains any of that loss. The compatibility gap is identified
from source, not established as its economic cause.

Use only the original daily study at source
95ee87086ac336ea81e80f6b29a693a62d686602 and its authenticated prepared arrays,
relative/SPY forecasts, fit receipts, original OHLC/provenance and complete
supplied exchange calendar. Daily OHLC have the store's preserved split basis;
adjusted opens are open * adjusted_close / close. Never use SIP session scaling
or apply an extra split adjustment. No inference/publication timestamps exist:
monthly fit receipts establish simulated maturity only, not historical availability.

At decision close t, absolute predicted log return is relative[t,stock]+SPY[t].
Exact ten-session target is log(adjusted_open[t+11]/adjusted_open[t+1]). Verify
this and its SPY-relative decomposition against the original prepared labels.
Twenty-session log(adjusted_open[t+21]/adjusted_open[t+1]) is a separately named
horizon-compatibility diagnostic, not accuracy of a fitted twenty-session model.
Neither label is the realized return of an intraday account.

All original 94 stocks are fixed before diagnostics; SPY is a separate market
head and QQQ is not a training stock. Keep every causal prediction opportunity
from 2018-02-01 through 2026-09-30 regardless of later label availability. Report
two fixed stock cohorts: original eligible stocks, and eligible A/A+ stocks that
could be increased by the tested allocator. Historical grades/book are current-
vintage reconstruction and must stay labelled accordingly. Include forecast
unavailability, immature outcomes, missing start/end prices and unavailable
prior-volatility history as distinct denominators; no imputation or outcome
filter may alter the causal opportunity count.

Report all, 2018–20, 2021–26 and the explicitly reused 2026-08-17..09-30 windows.
For stock heads, also report fixed low/middle/high volatility terciles using
cross-sectional mean-rank of each eligible stock's preceding 252 daily log
returns, ending at the decision close. Only complete positive prior prices may
establish a volatility group; missing history remains an explicit group. Ties
share a rank. Groups use no outcome, later price or later membership. No group
will select a policy. Per-stock full-period diagnostics retain all 94 symbols,
including unavailable ones; no selective winner list.

For absolute and relative stock heads and the separate SPY head, report causal
opportunities, finite forecasts, mature labels, matched rows, mean prediction,
mean realized log return, mean error (prediction minus realization), MAE, RMSE,
residual variance and Pearson correlation when identified. Compare mean squared
forecast error to a zero-log-return reference on the identical matched rows.
Use population moments; constant/singleton correlations are unavailable. No
annualized return, Sharpe, significance or profitability claim from these errors;
overlapping labels and stocks are not independent trials.

Acceptance: supplied-array business logic only, explicit data_as_of and basis;
exact exchange indices/endpoints; prepared ten-session labels must reconcile;
monthly fit clocks, freeze and maximum matured training endpoint must be checked;
late rows retain immature outcomes; missing values stay missing; split/dividend
basis is coherent; future-label mutations cannot alter prediction opportunities
or prior-volatility groups. Root authenticates original files before invocation,
reviews synthetic acceptance, then reads diagnostic cells once. Existing forecast
files, fitted models, source and account histories remain unchanged.
