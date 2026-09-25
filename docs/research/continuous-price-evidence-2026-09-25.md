# Continuous price evidence — September 25, 2026

## Availability correction — source only, not continuous-coverage proof

Verified scoped source checkpoint:
`fa729bad490154578698e2294b775398c4b39dfa`. No deployment.

The new reader no longer uses regular/closed/unknown calendar labels to skip
provider lookup. It selects SIP/IEX or BOATS/indicative overnight by New York
wall time, validates each symbol, and tries the fallback only for unresolved
names. A fresh primary wins; otherwise a fresh fallback wins; otherwise the
newest valid stale observation retains its source/time but no current price.
Each row records the expected schedule at its original quote timestamp. A
phase boundary does not reset its age or silently relabel it.

Raw responses have a ten-second per-feed/batch cache. Each read revalidates
timestamps. Both feeds back off after denial (300 seconds), throttling
(30 seconds) or other failure (10 seconds). Feed-generation guards protect
cache/backoff publication against older overlapping completions; only metadata
is locked, never a provider call. Two default curl timeouts are now two seconds
each. This verifies configured bounds, **not a measured end-to-end latency SLA**.
No change was made to execution quotes, regular bars, signal inputs or accounts.

The board/chart no longer suppress fresh observations on a regular-session
flag. They distinguish source, indicative midpoint, stale observation and
explicit regular-bar fallback, and date observations from earlier New York
days. Polling is described as checking quotes every minute, not guaranteed new
prices. Unknown schedules cannot establish a previous-session observation.
XNYS pre/post labels include the overnight period, so they cannot override the
independent, finer-grained quote schedule. Only a newer, nonfuture explicit
regular open has an exact compatible meaning for the retained legacy transition.

### Reproduced failures and acceptance

- Frozen original backend plus the initial final 52-case module: **7 passed,
  45 failed**. Missing fallback, schedule suppression and overflow failures
  are preserved at `/private/tmp/anios-session-availability-baseline.AFH7dp/`.
- The corrected first candidate still failed all **six overlap cases** with
  the expanded 58-case module. Older errors erased newer success or imposed
  backoff; older successes overwrote newer prices. The guarded candidate passes
  all six, including identical monotonic start times. `OVERLAP-RECEIPT.md`
  preserves both source revisions and exact commands; SHA-256
  `8d9735275bb7f9ba7c31b1b023297519a9f4334448d4e2288da2b9f69c178541`.
- Final backend regression: **205 passed**, no failures/skips, 3.29 seconds,
  with 60 existing all-NaN warnings from entry-session gap fixtures. This includes
  58 new behavior cases, 24 updated original cases, seven ASGI API cases and
  existing calendar/freshness/execution/desk regression tests. The separate
  89-case agent run is a subset, not another 89 distinct tests.
- Original browser acceptance: **1 control passed, 15 failed**. Three later
  review cases separately reproduced false previous-session wording for an
  unknown schedule and newer XNYS pre/post timestamps during overnight.
  The corrected artifact passes **40 focused cases**, no failures/skips/flaky,
  in 40.0 seconds. The same final artifact passes **171 broader cases** in
  77.134 seconds: **211 distinct browser cases across two runs**, no failures,
  skips or flaky cases. Source/test manifests stayed fixed through both runs.

The actual rendered dashboard, chart opening, timers, source/time text, regular
candles and unchanged action/size semantics are exercised by browser tests.
API/provider inputs are intercepted fixtures; no actual provider, model, order,
holding or receipt mutation occurred. ASGI tests prove authorized in-process
routing, not a deployed HTTP server. Browser servers run Vite preview on an
isolated loopback port from the explicit compiled candidate, not the deploy tree.

Final candidate artifact:
`/private/tmp/anios-session-availability-taxonomy-final.KDA32A7R/dist/`,
`index-CI7b1eYH.js`, SHA-256
`0b0a8fc5edc431a31fb4c24f52e7b9b5d2a5e0c85318b9d7aab8ffb3fea7e021`.
Root source manifests, backend results and broad browser evidence:
`/private/tmp/anios-session-availability-final.hzzWpSif/`.
Backend runtime is immutable image `63056fccae98`; browser runtime is
`eff16c30e6f3`, both network-disabled with source mounted read-only.

Ruff/format checks, production TypeScript/build and affected browser-module
strict typing pass. Earlier calibration failures are retained: Vite needed its
own writable temporary directory under a read-only source mount; a test compared
equivalent timestamps as strings; an intermediate build caught a removed local
binding before browser acceptance. These are not claimed as passing runs.
Existing CSS/bundle warnings remain. Full repository/deploy gates were not run;
previously documented unrelated gate failures were not fixed by this task.

### Remaining user requirement

**UNVERIFIED:** real all-hours/all-symbol continuity, deployed UI, new entitlement
and actual market-wide price accuracy. The reader still runs on demand from the
mounted desk's one-minute timer; it is **not an always-running server collector**.
Browser suspension/closure and real feed gaps are separate limits. The previous
four-call provider allowance was not repeated. No deployment was started.

The [existing-source qualification](extended-hours-source-options-2026-09-25.md)
documents delayed SIP history as a no-new-paid-subscription lead, with explicit
timestamp, delay and license limits. It is not wired or tested with this account.
No source purchase, model fit or historical strategy rerun occurred.
Diagram impact: NONE — existing endpoints/providers/ownership relationships;
internal availability, cache and display corrections only.

## Earlier independent-refresh checkpoint and live probe

The sections below retain the evidence and remaining-work assessment from before
the availability correction above; their implementation gaps are historical,
not a description of the current corrected source.

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
