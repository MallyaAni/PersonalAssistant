# Continuous price evidence — September 25, 2026

## Background collection — isolated acceptance, not deployed coverage

Based on `main` at `61a31e20761901615600846b8e0983b72001124d`. The current
increment adds a backend-lifetime display collector and a single persisted
snapshot. It does **not** add a historical archive, delayed SIP fallback,
execution input, strategy, account operation or model call. No laptop system
settings or computer-control permissions changed. No deployment was performed.

### What changed

- A due pass runs independently of browsers, default every 15 seconds while
  the backend is running. Existing credentials and safe POSIX locking are
  required; unsupported hosts remain importable with collection inactive.
- A dedicated shared file lock and persisted attempt time suppress duplicate
  worker passes. One private-mode, atomic, bounded `latest.json` holds up to
  256 graded symbols and 1 MB. This is latest-state persistence, not an archive.
- The existing authenticated GET only reads and revalidates persisted evidence.
  Repeated reads neither contact a provider nor write files. Missing/corrupt
  storage returns `as_of: null` and unavailable rows, not a fabricated capture.
- Original `as_of`, quote `at`, recorded source/session and freshness deadline
  are retained. Recorded phases, including `unknown`, are not recomputed against
  a later calendar. Age is revalidated; a GET never renews freshness.
- Completed malformed/failed fetches publish an empty failure instead of
  preserving a still-fresh older success. A storage failure cannot promise a
  replacement; retained data ages out normally. Sanitized failure-transition
  and recovery logs disclose that distinction without provider contents.
- Shutdown drains any active threaded pass. The UI explicitly says the
  **dashboard checks** for session quotes every minute, distinct from the
  collector schedule and any guarantee of new observations.

### Final acceptance and boundaries

**VERIFIED:** 357 backend cases passed, zero failures/skips, 7.59 seconds;
60 existing all-NaN warnings remain in entry-session gap fixtures. This includes
135 storage cases, eight collector cases, nine API cases, seven startup/config
cases and existing feed/calendar/desk/execution regressions.

The startup acceptance runs real `uvicorn.Server` with `backend.main:app` and
its actual lifespan on container loopback. A real temporary snapshot appears
before any HTTP client exists. Two authenticated clients perform ten reads with
unchanged bytes/mtime and source timestamps; unauthenticated/wrong-owner requests
fail 401/403. A failed pass replaces still-fresh success, a later pass recovers,
and app shutdown waits for a held writer. After stopping, no new writes occur
and the original quote expires. Only unrelated model/document maintenance and
provider data are synthetic, and the test cadence is accelerated. No production
database, model, provider, account, receipt or order is touched.

Storage acceptance includes real cross-process duplicate suppression and lock
recovery, bounded malformed JSON/FIFO/symlink handling, failed-publication cleanup,
original timestamp expiry, and application import with `fcntl` unavailable.
It does not prove cleanup of orphan temporary files after arbitrary process
termination midway through publication; no scavenger was added.

**VERIFIED browser workflow:** 47 focused cases (49.946 seconds) plus 171 broader
cases (74.814 seconds), **218 distinct cases**, zero failed/skipped/flaky, against
the same compiled artifact. Chart opening, first-open persisted evidence,
reload, expiry without polling, failure/recovery, source/time labels and
unchanged signal/size/account behavior are exercised. All browser API data is
intercepted; these tests do not independently prove the backend collector or
live provider. Production TypeScript/build and changed-test strict typing pass.

**FAILED intermediate checks retained:** the first API test compared equivalent
UTC/ET instants as unequal strings (six failures); the corrected assertion checks
the exact stored original plus instant equality. The store's initial hardening
suite had 107 passed / 14 failed, exposing malformed-input and unsafe-path cases.
The frontend's first seven-case run had two reopen harness errors; corrected
baseline is 7/7, and the new cadence assertion separately failed old wording.
The first broad browser run passed 165 / failed six solely because its screenshot
folder was read-only. Correcting that evidence mount, without production edits,
produced the final 171/171 run. A reviewer reproduced four returned storage
failures with no warning before the failure-transition logging correction.

Changed collector/store/startup/API-test/main modules pass Ruff; the existing
whole-file `_desk_mine_payload` complexity and a settings comment-length error
remain outside this change. Existing frontend CSS/bundle warnings remain.
Full repository/routing/deploy gates and deployed workflow are **UNVERIFIED**.

### Artifact identity and receipts

Backend runtime: immutable image
`63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`;
current source mounted read-only, network disabled, synthetic test credentials.
Final JUnit evidence: `/private/tmp/anios-background-backend-final.LCxuKuKf/backend-final.xml`.
Relevant source/test/config hashes stayed unchanged across acceptance.

Browser runtime:
`5b8f294aff9041b7191c34a4bab3ac270157a28774d4b0660e9743297b697e48`,
isolated Vite preview of
`/private/tmp/anios-background-session-locked.2RVA6ZyQ/dist/`, entry
`index-CsdUQRsl.js`, SHA-256
`f7ef22cf667105cc8f978df82611a85efc31f423f6ba3fd5ae31ed65875dc1f8`.
Focused receipt/results are beside that artifact. Broad final results:
`/private/tmp/anios-background-root-browser-locked.4bXuRMgK/results.json`, SHA-256
`142a1eb1bb4061f2fdebb783884e7b7ab682f318d415c278e073cb3020f0ce46`.
The initial screenshot-mount failure is retained at
`/private/tmp/anios-background-root-browser.25ovoVHJ/`.

Final frontend tooling comes from the existing read-only
`anios_codex_node_modules` volume: Vite 8.1.4, Playwright 1.61.1, Chromium 1228.
An offline version audit found 373 installed lock-aligned packages, 41 absent
optional/platform packages, zero required omissions or version mismatches.
This proves installed versions, not tarball content integrity or a fresh
`npm ci`. No shared dependencies, lockfile or OS settings were changed.

The same 218 cases also passed earlier on the newer host dependencies
(Vite 8.3.1, Playwright 1.63.0), in 50.416 + 81.779 seconds. That separately
pinned artifact remains at `/private/tmp/anios-background-session-candidate.8s5p6gQK/`;
the broad receipt is `/private/tmp/anios-background-root-browser-final.rk6GcXwk/`.
Those results are additional runtime evidence, not another 218 distinct tests
or the final lock-aligned candidate.

**Diagram impact: UPDATED — session-price-collection, anios-system,
runtime-deployment, agent-trading-desk.** The 33-view canonical check and
published-page check pass with locked Mermaid 11.16.0. Browser checks exercise
all four affected views/links/zoom, with 81 contained labels and zero errors.
All 29 unrelated sources/SVGs remain byte-identical. The old apparent stale
diagram failure was local CLI 11.17.0 drift: the unchanged 32-view baseline
passes with 11.16.0. Receipt:
`/private/tmp/anios-session-price-diagrams.CSVmdaBf/RECEIPT.md`.

### Still not proved

Collection while the backend is stopped, an end-to-end latency SLA, all-hours
fresh prices, all-symbol continuity, provider accuracy and real-time SIP access
remain unverified or unavailable. The collector does not override provider
coverage, caching/backoff or entitlement. A successful historical sample below
cannot be relabelled real-time.

The separately approved [single historical SIP request](extended-hours-source-options-2026-09-25.md)
returned 3,316 valid September 24 minute bars for four symbols, including both
gap windows, with no next page. That allowance is consumed; no further requests
were made. No delayed fallback is wired. Independent
[/3 attribution](fixed-strategy-attribution-2026-09-25.md) found roughly 90%
stock exposure during its worst drawdown; it does not demonstrate red-day
protection or qualify a strategy promotion.

## Earlier availability checkpoint

The remainder preserves earlier evidence and its then-current limitations;
on-demand collection is superseded in source by the increment above, not claimed
deployed merely because source was changed.

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
