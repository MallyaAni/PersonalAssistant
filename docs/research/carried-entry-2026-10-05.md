# Carried 1% entry result

VERIFIED: producer `13c3580d`, pinned runtime image `5c6c5605`, all 20
no-carry controls exactly reproduce every original daily NAV, cash, exposure,
turnover and fee value. Forty funded accounts, 34,206 original intentions;
independent recorded-action and ledger reconstruction passed. Both producer
and final verifier exited zero, without OOM. Four initial real-engine tests
passed in 0.027 seconds. No model, production account or live setting changed.

The verifier's first run exposed float32 arithmetic in its own price-times-
quantity operation; using a Python float for the execution price restores the
original ledger's float64 arithmetic. Assertions were retained. Source, output
and original failed run remain on Spark in `scratch/carried-entry-20261005`.
The separately frozen producer files were not overwritten by later experiments.

| Window | Median paired cumulative gain difference | Positive phases |
| --- | ---: | ---: |
| 2018-02-01–2026-09-30 | -13.5073 percentage points | 6/20 |
| Through 2020 | -3.8911 points | 7/20 |
| 2021 onward | +8.3169 points | 13/20 |
| Reused 2026-08-17 onward | +0.1147 points | 13/20 |

FAILED: consistent improvement over the existing entry rule. Removing the
same-session buy deadline alone is not a qualified replacement. This result
does not establish that 1% is optimal. The next registered experiment predicts
whether waiting until the next session is favorable, instead of carrying that
same fixed trigger. Neither experiment constitutes exact live-policy parity.

Machine-readable account hashes and results: `carried-entry-2026-10-05.json`.
Diagram impact NONE: isolated research changes within the existing path.
