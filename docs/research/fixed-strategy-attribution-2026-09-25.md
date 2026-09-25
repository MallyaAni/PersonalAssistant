# Frozen `/3` attribution — September 25, 2026

This is an independent accounting audit of retained
`cash-bounded-breakout-rotation/3` journals, **not another fit, strategy replay,
new forecast or recommendation**. Both 10/25 bp accounts cover 1,684 intervals,
2020-01-06 through 2026-09-18. All 21 pinned inputs stayed unchanged.
Eight arithmetic self-checks and 380 separately implemented 50-digit Decimal
name/window comparisons passed; maximum per-name discrepancy was `1.59e-15`.
Attribution reconciles marked holdings, actual fills and fees to NAV. Intended
orders and zero-filled batches are not treated as executed trades.

## What the saved accounts reveal

| Observation | 10 bp | 25 bp |
| --- | ---: | ---: |
| Worst closing drawdown | −37.33% | −37.58% |
| Average stock exposure during that drawdown | 89.56% | 89.54% |
| Average cash exposure during that drawdown | 10.44% | 10.46% |
| Net gain attributed to SNDK, DELL, LITE, MU and NVDA | 66.91% | 68.00% |
| Largest closing single-name weight, DELL | 31.60% | 31.85% |

The drawdown peaked January 23, 2025, troughed April 8, and recovered its peak
September 5. Exposure averages cover 53 closing observations including the
peak/trough. Both endpoints were fully invested in stocks; SPY exposure was
zero throughout and the journals contain no QQQ position. This **does not
demonstrate the user's desired red-day protection through cash or indexes**.
It also does not prove that upcoming red days were predictable or an alternative
allocation would have worked better. Index holdings themselves do not guarantee
protection from market losses.

Closing weights can drift above an entry-sizing target; the maximum is not by
itself proof of a sizing-rule violation. Concentrated gain attribution is
additive accounting, not causal alpha or the return of a portfolio excluding
those names. The two observed September 18 Q/TYL OHLC anomalies generated zero
actual fills in both journals. That does not rule out indirect effects on
features, decisions or other accounts.

## Limits and next use

This corroborates accounting only. Today's survivor universe, missing historical
membership/security identity, incomplete point-in-time fundamentals, unverified
delisted-security terminal payouts/returns and actual settlement, and unaudited
reconstructed grades prevent an unbiased
superiority claim over SPY/QQQ. The original study producer was interrupted;
its root manifest is absent. Recovery and attribution receipts do not silently
replace a successful producer manifest. The fitted allocation gate remains
rejected; no policy, holdings, execution or deployment changed.
The synthetic journals' terminal balances themselves were reconciled.

The findings identify requirements for future predeclared evaluation: risk-off
exposure and downside behavior, concentration, costs, chronological out-of-sample
comparisons and source validity must be assessed alongside long-run return.
They are not authorization to optimize repeatedly on this known drawdown.

## Pinned evidence

Full receipt and reproducible standard-library scripts:
`/private/tmp/anios-fixed-journal-attribution.3sojJz/RECEIPT.md`, SHA-256
`658d5444cae1b06b9863d94293ddb5ef5daa4e7c88da4c1949c7ed4c8188f8d9`.
Both scripts were independently rerun; the Decimal proof was byte-identical,
and attribution differed only in its recorded output path.

- `results-02.json`: `7bc9ce044a1a23729421f6a497662b58a55d7a6e01ac485217d64ad821f90240`.
- `decimal-proof-02.json`: `4df32e9aa0d5e108038b38a0cb1fafec55e7b196d98d700bf0db32fdd9588b8d`.
- `audit.py`: `2ffdca2d4f9e4eea1f87cf2a62a9004933d5ce38a5400d76f4fb32f17400fc5e`.
- `decimal_crosscheck.py`: `d4f7b4ec6d042ef82c26c8ad794284d3156e34d83a5bdbbe10367b4561f34680`.

No provider, Spark, model, account, order or deployment calls occurred in this
audit. Runtime strategy effectiveness and unbiased superiority remain
**UNVERIFIED**. Temporary receipt paths are local evidence, not a data archive
or a promise of long-term availability.
