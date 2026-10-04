# Saved holding forecasts: calibration and horizon compatibility

The saved return estimates do not establish reliable stock-specific sizing.
Across the full eligible A/A+ cohort, ten-session absolute forecasts have
correlation 0.0173 with subsequent log returns and 1.0112 times the squared
error of predicting zero. Relative forecasts have correlation 0.0529 and
1.0156 times that reference error. The separate SPY head has negative
correlation and greater error. These descriptive findings support testing
causal calibration before trusting raw means; they do not prove why the
combined allocation lost, or establish a profitable replacement.

Only existing forecast and price artifacts were read. No model was fitted,
account replayed or provider called. The protocol was frozen at 6642030e,
with the exact volatility-tie convention fixed at a29de5c9 before any error
cells were read. Evaluated source is 27c19d5e4df85b5115e2306da4786f75a06d64a3.

The exact target is adjusted next-session 09:30 open to the open ten
sessions later. Daily open is scaled once by adjusted_close / close.
Relative means subtract the same SPY log return. These are not the returns
of selected intraday fills. Data availability ends at 2026-09-30 16:00
New York. Twenty-session labels are compatibility checks, not the accuracy
of a fitted twenty-session model.

All fixed windows below use eligible A/A+ stocks. MSE ratio compares squared
forecast error with a zero-log-return prediction on identical matched rows;
below one is lower error. It is not a cash-policy or profitability comparison.

| Ten-session window/head | Matched rows | Pearson | MSE / zero MSE |
|---|---:|---:|---:|
| Full period, absolute | 12,950 | 0.0173 | 1.0112 |
| Full period, relative | 12,950 | 0.0529 | 1.0156 |
| 2018–20, absolute | 4,414 | 0.0395 | 1.0051 |
| 2018–20, relative | 4,414 | 0.0908 | 1.0076 |
| 2021–26, absolute | 8,536 | 0.0086 | 1.0138 |
| 2021–26, relative | 8,536 | 0.0387 | 1.0181 |
| Reused Aug 17–Sep 30, 2026, absolute | 146 | 0.1065 | 0.9247 |
| Reused Aug 17–Sep 30, 2026, relative | 146 | 0.1084 | 0.9652 |

| Ten-session SPY head | Matched rows | Pearson | MSE / zero MSE |
|---|---:|---:|---:|
| Full period | 2,166 | -0.1741 | 1.0682 |
| 2018–20 | 735 | -0.1237 | 1.0535 |
| 2021–26 | 1,431 | -0.2228 | 1.0829 |
| Reused Aug 17–Sep 30, 2026 | 21 | -0.2269 | 1.7728 |

| Full-period A/A+ volatility/head | Matched rows | Pearson | MSE / zero MSE |
|---|---:|---:|---:|
| low, absolute | 3,555 | -0.0276 | 1.0390 |
| low, relative | 3,555 | 0.0139 | 1.0419 |
| middle, absolute | 3,811 | 0.0217 | 1.0071 |
| middle, relative | 3,811 | 0.0980 | 0.9962 |
| high, absolute | 5,584 | 0.0207 | 1.0069 |
| high, relative | 5,584 | 0.0352 | 1.0182 |

Full-period A/A+ coverage is 13,137 causal opportunities: 13,070 finite
forecasts, 67 unavailable forecasts, 120 immature ten-session outcomes and
12,950 matched rows. There are no missing mature entry/end prices in that
cohort; 67 opportunities lack complete prior-volatility history. The full
eligible stock cohort retains 75,883 opportunities and 74,635 matched rows.
All 94 stock histories, every missing group and all fixed cells are retained
in the adjacent JSON; no favorable name or regime was chosen for adoption.

The twenty-session A/A+ extension has 12,850 matched rows and 220 immature
outcomes. Its mean realized log return is 0.02225 versus the unchanged
ten-session prediction mean 0.00960. This is a horizon mismatch, not proof
that changing the horizon improves trading. The reused recent extension
has only 46 matched rows. Overlapping labels and phase accounts are not
independent trials; no significance or annualized performance is inferred.

Historical grades/book are current-vintage reconstruction. Monthly receipts
prove simulated training maturity, not historical publication/inference
times. The recent window was already used. These limitations prevent a
live adoption claim even if an individual descriptive cell is favorable.

VERIFIED: 38 native and 38 pinned-image diagnostic checks, then 20 native
and 20 pinned-image independent-verifier cases, all without skips. The
actual read-only verifier independently reconciled 23 saved row fields,
168 window/head/group cells, 752 per-stock cells and 141 monthly clocks.
It did not call the diagnostic producer, a model or an account replay.
FAILED: the raw forecast evidence supports no reliable live replacement.
UNVERIFIED: whether a causal, horizon-matched calibration improves net wealth.
Production policy, dashboard and model container identities remain unchanged.

Original report SHA256: `0631868f8231a96b8828b3df203a0f7fe48bc75b315abf0bb5d36fbb1061c341`.
Rows SHA256: `885af27f1ee626589d4a76ce00d48736561e69c7350b13e3200c36b867fe736b`.
Independent proof SHA256: `4c794a391c2f6d2a48d273363f0ef7b837ecdb4d612b45135d3b27e2f4e7e497`.
Whole 2,298-file source manifest SHA256: `7769b595f4674841c8e46ff8de412f6269041e9536c137cd7c601eed0c8f7a7b`.
Verifier SHA256: `813d94ade7e8a59272ba4d389104631bae80283f3e97f88b6a9c438b5f5e8706`.
Published JSON SHA256: `76456538007462a3d89124330f8d7b309047948ffa070a1a3d9c3e9f4a8579f5`.
The original producer and verifier both exited successfully; never restart
this diagnostic or refit/replay its original studies.
