# Extended-hours source options — September 25, 2026

## What is and is not established

The existing feed types do not establish fresh coverage throughout 04:00–08:00
and 17:00–20:00 ET. The bounded midday probe established fresh IEX access,
accessible indicative overnight data, and denied latest SIP/BOATS requests. It
did not observe the two gap windows or prove all-symbol continuity. A separately
approved, single historical request subsequently established sample access below;
no subscription or purchase was made.

Primary documentation identifies a credible **delayed SIP history** option at
the already-integrated Alpaca provider, without assuming a new paid plan.
The September 24 sample is **VERIFIED** for this account and query, not a promise
of future entitlement or continuous current gap-window coverage. Delayed
observations cannot satisfy a real-time requirement or enter the fresh-quote
field merely because they were just downloaded.

## Source qualification

- [Alpaca's Market Data FAQ](https://docs.alpaca.markets/us/docs/market-data-faq.md),
  updated September 21, says historical SIP queries without a subscription
  require an explicit end at least 15 minutes old. Latest SIP endpoints require
  a subscription, so the earlier latest-feed denial does not settle historical
  access. The older historical overview uses broader, less specific wording;
  this remains a lead to test, not a guaranteed entitlement.
- [Historical bars](https://docs.alpaca.markets/us/reference/stockbars.md)
  support dated one-minute intervals. The FAQ includes eligible extended-hours
  `T` trades in minute bars, but the timestamp is the **interval start**, not the
  last trade instant. Missing eligible trades can mean no bar, and excluded
  trade conditions mean the close need not equal the last reported trade.
  A delayed bar, delayed trade and delayed midpoint need separate meanings.
- [IEX's schedule](https://www.iexexchange.io/resources/trading/trading-hours-holidays)
  is 08:00–17:00 ET. Single-venue access does not establish consolidated prices
  or coverage outside that window.
- [Alpaca's 24/5 guide](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api.md)
  distinguishes actual BOATS data from free **indicative** overnight quotes,
  20:00–04:00 ET. Neither is evidence of 04:00–08:00 or 17:00–20:00 coverage.
- The existing Yahoo collector is daily-only and does not retain an intraday
  quote timestamp. Yahoo's [coverage page](https://help.yahoo.com/kb/finance-for-web/exchanges-data-providers-yahoo-finance-sln2310.html)
  lists real-time sources on its own service, not a supported automation
  contract. Its [August 4 terms](https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html)
  require express prior permission for automated collection; redistribution
  restrictions also apply. No such permission was established for expansion.
- The existing Cboe options parser discards the underlying quote timestamp;
  snapshot fetch time is not quote time. The public
  [delayed-quote dashboard](https://www.cboe.com/delayed_quotes/) prohibits
  automated extraction. It is not a qualified replacement price feed.

Alpaca's [terms](https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf)
also distinguish personal/noncommercial use from publication or distribution.
The private owner desk is the current scope; public/multi-user distribution and
indefinite retention rights were not established by this review.

## Approved historical SIP sample — verified September 25

The user approved **one** read-only historical SIP request, now consumed. At
2026-09-25 15:43:58 UTC, the existing backend container requested September 24,
04:00–20:00 ET, for SPY, QQQ, AAOI and ORCL. Exact bounds were
`2026-09-24T08:00:00Z` through `2026-09-24T23:59:59Z`, with `feed=sip`,
`timeframe=1Min`, `adjustment=raw`, `limit=10000`, and ascending order.
One GET, 20-second timeout, redirects disabled, no retry or pagination.

HTTP 200 returned **3,316 valid bars**, zero invalid/duplicate slots and no next
page. Each symbol had observations in both previously unqualified gap windows:

| Symbol | Total bars | Observed minutes, 04:00–08:00 ET / 240 | Observed minutes, 17:00–20:00 ET / 180 |
| --- | ---: | ---: | ---: |
| SPY | 893 | 228 | 125 |
| QQQ | 915 | 240 | 135 |
| AAOI | 663 | 128 | 46 |
| ORCL | 845 | 167 | 144 |

These counts are **observed eligible-trade minute bars**, not uptime percentages.
Missing minutes do not by themselves establish an outage. Interval-start stamps
are not last-trade timestamps. This proves this historical query succeeded; it
does not measure current delayed publication, real-time entitlement, vendor
accuracy or all-symbol/all-day continuity. No delayed fallback is implemented.

The request used existing SSH access, without laptop security/permission changes,
remote files, service changes, account writes or orders. The sanitizer passed
15 offline checks. Six imported helper source hashes and the unchanged running
backend image were pinned: image
`sha256:001e64f3720e2f8fdb8690edb90a074064dc6f744e0c29d20058974472c82b48`,
created `2026-09-25T03:57:10.142649866Z`. It has no source-revision label;
the deploy checkout must not be substituted for complete runtime identity.
Probe script: `/private/tmp/anios-delayed-sip-probe.Virfci2w/probe.py`, SHA-256
`b7b99089e96b9a556786f5e7960839c7fab019e2758a6768ac4077b204e23b8f`.
Sanitized result: `result.json` in that directory, SHA-256
`67784f94279f51bdac2b1b20a4425932bdd9439b1ef37e688f27d9100b8ae11b`.

## Remaining evidence, not an implemented delayed feed

A further observation within each gap would need fresh authorization and must
distinguish delayed publication from current availability. Both earlier live
probe allowances are exhausted; no additional request is implied here.

The sample also does not establish always-on collection. The separately tested
[background collector](continuous-price-evidence-2026-09-25.md) uses existing
latest-quote feeds, not this historical-bars endpoint. Browser suspension and
provider coverage are separate limitations. No historical archive, strategy fit,
backtest, execution rule or candle source changed in this source qualification.

Full inspected-source hashes, captured primary documents and use caveats:
`/private/tmp/anios-session-source-qualification.fxmeQF/RECEIPT.md`, SHA-256
`a2bf3fc57bc96d1ee1e45762893c5dcfe96086db5daaa663512fe9ad53e39b4b`.
The source review is pinned to `a9a63c02a9879e7086311509d6fc45deb1548583`;
it does not describe subsequent session-reader corrections as already deployed.
