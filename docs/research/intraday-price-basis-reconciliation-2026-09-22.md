# Intraday price-basis reconciliation — root review, 2026-09-22

**Historical scoring remains unavailable.** A generic correction of the existing
two-provider history is not established. This reviewed report replaces the
worker's unsupported cause and readiness claims; its original remains isolated.
No strategy outcomes, fitted ratios or frozen-cache rewrites were performed.

## Verified observations

Root independently reread the explicit intraday2026-09-20 and daily2026-09-18
partitions and dated action cache. The following are last regular15-minute
closes, not guaranteed auction closes or fills:

| Symbol/date | Cached intraday | Cached daily adjusted | Fresh IEX `all` | Fresh IEX `raw` |
|---|---:|---:|---:|---:|
| AVGO2024-07-12 |1667.26|166.9276|166.42|1698.62|
| AVGO2024-07-15 |168.31|168.2557|168.00|171.475|
| WRB2024-07-09 |74.76|49.8412|49.77|78.75|
| WRB2024-07-11 |49.65|49.6418|49.58|52.30|
| WDC2025-02-21 |46.59|51.6817|46.59|68.715|
| APTV2026-03-31 |58.83|69.4400|58.83|69.445|

Root made eight bounded read-only requests to the existing free IEX endpoint
with explicit all/raw adjustment, observed2026-09-22T22:43:09Z. No provider
subscription, order, model call, service change or cache write occurred.
`/tmp/codex-provider-adjustments-20260922.json` stores request-mode receipts,
response hashes and selected rows; `/tmp/codex-check-provider-adjustments-
20260922.py` is the script (one continuous filename). The existing backend image
was `sha256:997055765439e8d37539430c7ed87bb3707c6a619615532fecee18b057b4da90`.

The cache records AVGO split10 on2024-07-15; WRB split1.5 on2019-04-03,
2022-03-24 and2024-07-11; and WDC split1.323 on2025-02-24. APTV's action cache
has no2026 spin event. Official sources independently confirm AVGO's split,
WRB's2024 split and APTV's2026 distribution:
[Broadcom](https://investors.broadcom.com/news-releases/news-release-details/broadcom-inc-announces-second-quarter-fiscal-year-2024-financial),
[W.R. Berkley](https://ir.berkley.com/news/news-details/2024/W--R--Berkley-Corporation-Declares-Special-Dividend-Increases-Regular-Quarterly-Cash-Dividend-9-1-and-Announces-3-For-2-Stock-Split/default.aspx),
[Aptiv](https://www.aptiv.com/en/newsroom/article/aptiv-board-of-directors-approves-spin-off-of-versigent).
An issuer distribution establishes an event; it does not establish either
provider's complete historical adjustment convention.

## Corrections to the worker's conclusions

- The worker reported AVGO's cached07-12 close as1692.04; root reads1667.26.
  Calling the old AVGO/WRB cache simply raw is also inaccurate: the sampled
  cached values differ from current raw quotes and current all-adjusted quotes.
  Missing split normalization relative to daily adjusted history is supported;
  the exact old fetch/adjustment process is not independently established.
- A one-day price move does not prove a daily series is unadjusted for a
  spin-off. WDC's fresh raw pre-event quote68.715 differs substantially from
  cached daily close51.935; the worker's claim that this daily close is raw is
  unsupported. Matching selected Yahoo closes is not byte-level or whole-series
  proof of adjustment correctness.
- WDC/APTV cached specimens DO match fresh provider `all` specimens. Their
  mismatch with Yahoo therefore cannot be dismissed as merely an old broken
  cache. Current provider conventions still differ on these examples.
- Four near-matching09-18 closing samples do not establish compatibility for
  every September symbol, its preceding20-session daily window, all intraday
  observations and its forward endpoint. The proposed post-last-action filter
  was not accepted as scoring authorization. Recent dividends, missing action
  records, symbol continuity and future outcomes still require evidence.

## Bounded next step

Finish the already scoped preparation wiring. Keep existing daily mapping,
eligibility,20/5 horizons and opportunity accounting fixed. Do not rescale old
prices from cross-provider close ratios or silently drop troublesome names.

A usable evaluation requires either a separately reviewed dated transformation
with documented provider/action factors and source hashes, or fresh consistent
forward observations whose full lookback and eventual outcomes have a declared
basis. Switching the incumbent's daily source would change the input contract
and must be documented before outcomes, not represented as exact live parity.
Neither path is verified by the present sample. Raw/all specimens now narrow the
missing evidence; another blind full-history fetch is not the next step.

Implementation checks remain verified independently of this data failure.
Historical candidate superiority and midpoint fills remain UNVERIFIED.
