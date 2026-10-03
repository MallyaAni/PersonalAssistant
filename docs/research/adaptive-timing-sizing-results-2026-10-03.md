# Adaptive timing and stock-specific funded sizing

The combined policy is implemented on `codex/learned-entry-risk-20261002`.
It does not qualify for live replacement: its recorded cumulative gain is below
the saved equal-weight rule component with either execution clock. Production
policy and dashboard are unchanged. Independent artifact verification passed
for all 120 new accounts, 13,062 allocation resets, 52,160 intents and 51,468 fills.

The implementation connects prior-only holding-return forecasts and historical
stock covariance to cash-constrained target weights, then routes frozen quantities
through the learned buy/sell continuation clock. It preserves covered sales,
fees, missing evidence, first-attempt locks and expired opportunities. Proposed
sales cannot fund same-session purchases. Missing held cross-risk or an
uncertified allocation prevents additions; it does not fabricate a forecast.

Only 120 new carried accounts ran: growth sizing with both timing clocks, three
cost levels and all twenty reset phases. The 120 saved equal-weight controls and six ETF accounts
were reused without refitting or replay. The fixed period is 2018-02-01 through
2026-09-30, with 2,177 return sessions, NAV1 and zero cash yield. Orders execute
against the declared next-bar-open proxy, not proven broker or midpoint fills.

Full-period metrics below are medians across twenty phases. Drawdown is reported
as a positive loss. Costs are per side. Gross trading is traded notional divided
by contemporaneous NAV, annualized; it includes buys and sells. ETF accounts
pay the opening purchase cost and remain invested without terminal liquidation.

| 10bp per side | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading/year |
|---|---:|---:|---:|---:|---:|
| Equal weights, rule timing | 723.39% | 27.64% | 37.15% | 1.060 | 6.780 |
| Equal weights, learned timing | 735.77% | 27.86% | 37.86% | 1.069 | 6.685 |
| Growth sizing, rule timing | 457.72% | 22.01% | 38.74% | 0.850 | 7.195 |
| Growth sizing, learned timing | 476.01% | 22.47% | 37.78% | 0.850 | 7.203 |
| SPY | 209.52% | 13.97% | 33.72% | 0.782 | 0.116 |
| QQQ | 364.83% | 19.47% | 35.12% | 0.865 | 0.116 |

| 25bp per side | Net gain | CAGR | Drawdown loss | Sharpe | Gross trading/year |
|---|---:|---:|---:|---:|---:|
| Equal weights, rule timing | 654.27% | 26.35% | 37.73% | 1.021 | 6.777 |
| Equal weights, learned timing | 667.15% | 26.60% | 38.43% | 1.031 | 6.682 |
| Growth sizing, rule timing | 422.51% | 21.09% | 39.11% | 0.800 | 6.891 |
| Growth sizing, learned timing | 422.98% | 21.11% | 38.74% | 0.805 | 6.903 |
| SPY | 209.06% | 13.95% | 33.72% | 0.781 | 0.115 |
| QQQ | 364.13% | 19.44% | 35.12% | 0.865 | 0.115 |

Paired contrasts subtract gains within each matching phase before taking the
median. They therefore differ from subtracting the displayed arm medians.
Phases overlap; winning-phase counts are sensitivity checks, not independent
trials or a probability of future profit.

| Combined minus equal-weight rule | Paired median gain difference | Winning phases |
|---|---:|---:|
| Full, zero costs | −229.84pp | 1/20 |
| Full, 10bp | −236.79pp | 2/20 |
| Full, 25bp | −178.29pp | 1/20 |
| 2018–20, 10bp | −11.64pp | 6/20 |
| 2021–26, 10bp | −103.07pp | 1/20 |
| Reused 2026-08-17 through 2026-09-30, 10bp | −2.11pp | 3/20 |

At 10bp, learned timing within growth sizing adds a paired median 8.25pp versus
growth sizing with rule timing, winning 11/20 phases. That is insufficient to
offset the sizing loss. Median average exposure is 63.81% versus 71.09% for
the rule component, with worse drawdown and Sharpe. Lower exposure is not a
demonstrated risk benefit here. The combined arm beats QQQ in 16/20 phases and
SPY in 20/20 over the full period, but this does not establish an investable edge.
Its reused recent median gain is −0.66%, versus +2.07% for the rule component.

These are reconstructed twenty-session reset component accounts, not exact
live-policy parity. Historical grades and the stock book use current-vintage
reconstruction, not original historical publications. Earlier experiments have
already used this data and the recent window; there is no untouched holdout
claim. The holding means target the next 09:30 open through the opening ten
sessions later; candidate fills use a selected intraday next-bar open. Their
entry-clock compatibility requires separate validation. The ten-session forecast
versus twenty-session target resets was declared before the run and remains
unresolved. Missing opportunities and
unsupported early-close sessions remain explicit. No winning stock, regime,
threshold, cost level or reset phase was selected for deployment.

The allocation ablation identifies where performance deteriorates, but does not
prove whether return calibration, covariance estimation or horizon mismatch
caused it. The next bounded investigation is a read-only check of saved forecasts
against their exact matured 09:30 ten-session outcomes and their twenty-session
extension, without treating either as realized intraday account returns. It must
fix groups and denominators before reading errors, preserve unavailable labels,
and avoid adjusting parameters from these results. This finding rejects this
candidate; it does not establish that equal sizing or the existing timing rule
is universally optimal.

Evaluated source: `63c21f682893e72552db9c3c1bac7f2c284f0e11`.
Fixed implementation protocol: `45d6b5a624aa0656cf062acb6cdee1e3deabe101`
(initial registration `e04985b2`). Whole 2,293-file source manifest SHA256:
`b86461d5d50f0080526a6704c9d073d764bfa2f347daf06d3190dfe45545e254`.
Original result SHA256:
`258c4b87d899382acc90ecc26a4b7e94edd190a125b98aa090a5acb8ce518a97`.
The pinned source image passed 115 relevant checks with no skips, including
seven independent allocation acceptance cases and eighteen unchanged default
replay comparisons. This engineering validation does not establish profitability.

Independent verifier v3 passed 37 native and 37 pinned-image corruption/acceptance
cases, then reconciled all saved accounts, allocation certificates, quantities,
cash, shares, fees, strict decision counts, stock contributions and all six arms'
scores and paired summaries. It did not run a strategy, refit a model or replay
an old account. Two earlier audit versions were preserved after exact scalar
versus vector cash and held-only NAV summation differences changed one strict
counter each. The corrected audit matches authenticated book arithmetic; no
count, threshold or tolerance was relaxed. Production model containers retained
their original IDs and start times.

Independent proof SHA256:
`4d5db0ca9c3c3f437dedf78c9d13682664ef05e8ffe84b094d8032c017f0d7c1`.
Verifier SHA256:
`9fcee0f2740e88d80f9b2dc9529bec1bb024e53230bb509aa0f51bf6f13fc1e0`.
Complete compact readback is in the adjacent JSON, SHA256:
`c7167e49b103f587a95e0271e67573ce2cb6db337118d2729d83c57d8ab676ba`.
The producer and independent verifier have both exited successfully. Do not
restart, refit or rescore this completed experiment.
