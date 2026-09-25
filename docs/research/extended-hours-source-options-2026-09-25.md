# Extended-hours source options — September 25, 2026

## What is and is not established

The existing feed types do not establish fresh coverage throughout 04:00–08:00
and 17:00–20:00 ET. The bounded midday probe established fresh IEX access,
accessible indicative overnight data, and denied latest SIP/BOATS requests. It
did not observe the two gap windows or prove all-symbol continuity. No further
market-data request, subscription or purchase was made during this review.

Primary documentation identifies a credible **delayed SIP history** option at
the already-integrated Alpaca provider, without assuming a new paid plan.
Actual account entitlement and gap-window coverage are **UNVERIFIED**. Delayed
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

## Next evidence, not an implemented feed

After a new bounded allowance—the prior four-call probe is exhausted—one
historical SIP batch for a completed trading day could test actual access and
dated pre/post coverage. Use explicit 04:00–20:00 ET bounds converted to UTC,
`1Min`, `adjustment=raw`, a fixed small representative symbol set and a bounded
page limit. Report per-symbol timestamp coverage, gaps and pagination, not only
HTTP status. A subsequent observation within each gap would need to distinguish
delayed publication from current availability. No sample was run here.

Even a successful sample would not establish always-on collection. The current
session-price endpoint is read on demand by the mounted desk's one-minute timer;
browser suspension, closure and provider gaps remain separate limitations.
There is no new server-side session-quote collector or historical archive in
this change. No strategy fit, backtest, execution rule or candle source changed.

Full inspected-source hashes, captured primary documents and use caveats:
`/private/tmp/anios-session-source-qualification.fxmeQF/RECEIPT.md`, SHA-256
`a2bf3fc57bc96d1ee1e45762893c5dcfe96086db5daaa663512fe9ad53e39b4b`.
The source review is pinned to `a9a63c02a9879e7086311509d6fc45deb1548583`;
it does not describe subsequent session-reader corrections as already deployed.
