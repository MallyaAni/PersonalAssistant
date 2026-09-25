# Continuous price evidence — September 25, 2026

## Requirement and current boundary

The user requires overnight, premarket and postmarket price updates without
assuming that XNYS regular-session closure means every trading venue is closed.
Schedule, observed quote availability, price freshness and strategy execution
eligibility are separate facts. Missing data must not become a fabricated price,
and a display midpoint must not become a trade, candle or guaranteed fill.

**Partially implemented, not end-to-end verified.** Source checkpoint
`5e49870110f4a208e575410c08504f8b4d617c36` separates existing regular and session
price reads in the browser. A session response now publishes independently under
the current poll/account/lifecycle guard. A slow or failed regular read cannot
withhold it; a failed session read removes its old envelope independently. The
regular failure message explicitly describes regular-session data. Existing
five-second session timeout, timestamps, expiry, request cadence, chart candles,
account recording and execution rules remain unchanged. No deployment occurred.

## Browser acceptance

The original frozen browser test passed its healthy control and failed its
regular-network-failure case: both received a fresh synthetic postmarket quote,
but the failing regular feed made board and chart discard it. Its unchanged
candidate replay passes **2/2**. The persistent 18-case baseline passed 14 and
failed four intended regressions: regular network/JSON failure, and delayed
regular completion withholding either a new quote or optional-feed invalidation.

On the exact final compiled artifact, **174 existing cases passed** in 84.625
seconds, and **18 new cases passed** in 25.976 seconds: **192 distinct cases
across two runs**, zero failed/skipped/flaky. New tests use real chart open/close,
Refresh, Apply and navigation interactions; they check source/time/midpoint
meaning, expiry, failure, out-of-order/account/unmount rejection and unchanged
regular signals. Strict typing of both changed browser modules, production
TypeScript, build and diff checks pass. All exercised source hashes stayed fixed.

The 18-case run intercepted 471 API requests, including 60 session-price and
43 non-recording guidance reads. No real account/provider writes occurred.
Five intentional transport aborts and one HTTP 503 account for all six expected
console errors; no unexpected diagnostics were accepted. Synthetic IEX quotes
at 18:00 ET test the client boundary, not real IEX operating hours or access.

- Artifact: `/private/tmp/anios-independent-session-candidate.UzwxlZ1S/dist/`,
  `index-BnYKkHLd.js`, SHA-256
  `51276851043c9a381ee5925bb67c2761e8ac1ac50bd151c09114beabe90619ea`.
- Existing suite/source manifest:
  `/private/tmp/anios-independent-session-acceptance.XqBOO0k6/`.
- New suite, failed baseline, unchanged replay and harness-calibration details:
  `/private/tmp/anios-independent-persistent-candidate-final.1iySyuWy/RECEIPT.md`,
  SHA-256 `becc85178c4d2e2d202d6ef7ea5a6ca251435e075e48f88fa8a46e698ba163a1`.

## Actual feed access — one bounded midday observation

Exactly four SPY latest-quote GETs were made at **11:21:13 ET on September 25**
through the existing deployed credentials/transport. No subscription, order,
account, service or remote file was changed; no credentials/raw errors were
printed. Nine reviewed helper/import hashes were checked before calls.

| Feed | Observed result | Meaning |
| --- | --- | --- |
| SIP | HTTP 403 | Current request denied; consolidated latest-quote access not established. |
| IEX | HTTP 200; valid quote age 0.104 seconds | Fresh single-venue quote observed now, not proof of all-session continuity. |
| BOATS | HTTP 403 | Current request denied; actual overnight venue feed access not established. |
| `overnight` | HTTP 200; quote over seven hours old | Feed accessible, but not fresh at midday. The 04:00 ET observation is not evidence of an overnight outage. |

Runtime image was
`sha256:001e64f3720e2f8fdb8690edb90a074064dc6f744e0c29d20058974472c82b48`,
unchanged before/after. Its revision label was empty; deploy checkout
`879abc56ca4d7b3827bf4b8244991d0d02bf0c00` is context, not proof of that complete
image tree. Sanitized receipt with helper hashes:
`/private/tmp/anios-feed-entitlement-probe.BBq5Xy/RECEIPT.md`, SHA-256
`513dcf5825223ddb05d6190e82663c1598a17ce976c4decbd18d0044774e4b51`.
The four-call allowance was exhausted; no repeated probe is implied.

## Remaining implementation and coverage work

The actual backend audit made 14 isolated observations; the existing 24 tests
passed, including tests that currently require no requests during regular or
weekend phases. These tests **do not verify the new requirement**:

- `session_prices.fetch` skips provider lookup for regular/closed/unknown
  calendar phases. An omitted lookup is not observed unavailability.
- An empty/stale/partial primary HTTP 200 prevents fallback; fallback is tried
  only on 403, before per-symbol freshness selection.
- Quote validity is capped at phase boundaries; any retained previous-phase
  observation must keep its source time/phase and cannot be relabelled current.
- Frontend schedule-based suppression and generic market-closed/update wording
  need their own acceptance cases. Correct XNYS schedule labels can remain, but
  must not state that every source or venue is closed.

Next bounded implementation: separate expected schedule from provider lookup,
validate per-symbol responses before bounded fallback selection, and preserve
source/indicative/timestamp distinctions. Then test regular/pre/post/overnight,
unknown calendar, rollovers, missing/stale/partial/denied feeds and unchanged
execution. Qualify existing alternative sources before considering new access;
no purchase or new subscription is authorized.

[Alpaca 24/5 documentation](https://docs.alpaca.markets/us/docs/245-trading-for-trading-api.md)
distinguishes actual BOATS from free indicative overnight quotes (20:00–04:00
ET). [IEX's official schedule](https://www.iexexchange.io/resources/trading/trading-hours-holidays)
lists 08:00–17:00 ET. Those accessible feed types alone do not establish fresh
04:00–08:00 or 17:00–20:00 coverage. More polling cannot certify missing venue
coverage. The [latest-quotes reference](https://docs.alpaca.markets/us/reference/stocklatestquotes-1.md)
also distinguishes quotes from trades and response time from quote time.

Full offline audit/source citations:
`/private/tmp/anios-session-feed-audit.znWifG/RECEIPT.md`.
Live extended-hours continuity, symbol breadth, deployed UI, strategy quality
and provider accuracy remain **UNVERIFIED**. Diagram impact: NONE — existing
feed/ownership relationships, internal client completion correction and evidence.
