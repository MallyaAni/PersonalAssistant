# Live models on historical observations

The human requests historical actions and quantities from the currently installed
grade-led system. Grade-only arrows, legacy equal-weight targets and previous
model-only simulations are not substitutes for that account.

Freeze the exact current holding head, timing heads, holding risk bank, timing
residual bank, grade-led policy, costs, risk guards and source revision. Apply
the same numerical inference, grade-constrained sizing, funded whole-share
planner and learned sender to historical observations. Daily features and
intraday features must use the relevant observation prefix only. The model
parameters were trained later: this is a retrospective current-model simulation,
not historically published forecasts, out-of-sample evidence or broker fills.
Original model publication and training dates remain visible in provenance.

Historical direction preserves the authenticated ticker history's saved and
recalculated grades. These differ from the raw grade archive rebuilt by the
current nightly; neither is silently substituted for the other. The Oct12
current feature row, forecasts and scenarios match the authentic live observation.
Parity planning compares each reader against its own authenticated grade prefix,
with identical current grades, targets and quantities. Historical feature-prefix
checks use the preserved chart-grade inputs. Benchmark context grades retain
the authentic live input archive's values, not missing values inferred from the
absence of an ETF chart-history endpoint.

Use a separate $100,000 synthetic cash account, zero initial shares and10bp
per side, starting2019-03-01 with the prior completed close as its first planning
observation. Preserve missing-data refusals, pending orders, corporate actions,
cash, shares, fees and actual session calendars. Never borrow previous-policy
fills, holdings or quantities. No new base-model fits or tuning; retain the
same live market calibration and residual arithmetic with its frozen current
bank. All old versions and the actual paper account remain unchanged.

Primary ticker history must show decision quantities and grade direction from
this account, including additions/trims while the grade stays eligible. A
grade entry with zero funded size remains explicitly BUY0shares with its reason;
an unowned grade exit has no sale. Decision timestamps and simulated execution
timestamps remain distinct. Actual paper executions retain their original
account provenance. The main Stocks overview stays current-only.

Acceptance requires exact model/config/source authentication; equality of
historical adapter and live numerical sizing/timing on shared observations;
unchanged-prefix features; additions/holds/trims for eligible grades under
different risk/cash inputs; no below-A additions; no sale-proceeds funding;
independent cash/share/fee/raw-price/corporate-action ledger reconciliation;
all-stock API integrity and owner isolation; original artifact preservation;
and actual compiled-browser quantities, dates, empty/blocked states, ranges
and persistence. Separate real ordinary-nightly and next-session acceptance
remains necessary. A running simulation or a projection is not completion.
