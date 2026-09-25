# Scope missing-price wording to the display snapshot

September 25, 2026. Display wording only; no change to quote eligibility,
trading signals, timestamps, API behavior or the collector.

## Objective and first failing boundary

The shared `StockBoard.SessionPrice` checks only `live.extended_hours`.
`getDeskSessionPrices` independently validates `/session-prices`, whose backend
reads a stored display snapshot. `/mine` separately fetches execution quotes.
Missing, invalid or timed-out display evidence can coexist with an eligible
execution quote. Therefore **“No fresh quote from available feeds”** asserts
more than this component knows.

The acceptance path must preserve actual producer-shaped BUY, 3.3% size, IEX
spread caveat, original bid/ask/time and raw payloads, while qualifying both
board and full-panel display wording. Refresh, reload, missing data, original
quote deadlines and regular-session restrictions must keep working.

**FAILED original:** five desired-behavior browser cases fail on the old
unavailable label, after BUY and 3.3% assertions pass. Cases cover generic
unavailable, missing envelope, missing symbol quote, malformed price and a
specific recorded reason. All five have clean six-category diagnostics.
The full panel also repeats the old generic reason. Failures were preserved
before the production edit, against immutable f108 assets.

## Targeted change

- Main unavailable label: “Display midpoint unavailable”.
- Tooltip and noncompact subtitle explicitly separate display-snapshot
  evidence from execution checks.
- The exact generic old reason becomes “No usable midpoint in this display
  snapshot”. Other reasons remain, attributed as “Recorded display-snapshot
  reason: …”. Raw responses are not rewritten.

Only the shared component's wording and purpose comment change. Existing
freshness validators, source fallback, session logic, timestamps, prices,
grading, ranking, sizing and actions are untouched. The board retains its
explicit regular-bar fallback. Existing stale/fresh display states are unchanged.

Five counterexamples were added to `desk-execution-evidence.spec.ts`; four
neighboring price suites update only wording assertions and one test name.
No timeout, fixture, equality assertion or error check was relaxed.

## Verification

**VERIFIED current candidate:**

- Focused execution/display suite: 17 pass, 11.376 s; 17 clean diagnostics.
- Price suites: 64 pass, 61.778 s; 17 clean diagnostic attachments, plus their
  existing fixture-specific checks.
- Combined desk/price/history/action/research UI suite: **269 pass**, 188.077 s,
  zero skipped, flaky or unexpected results and no report errors. All 72
  six-category diagnostic attachments are clean.
- Root independently runs execution evidence, grade timing and simple actions:
  **33 pass**, 28.432 s, zero skips/flaky/unexpected results; all 26 diagnostic
  attachments clean. Seven simple-action cases have no such attachment.
- Root and agent TypeScript/build checks pass. Root's complete independently
  rebuilt output is byte-identical to the accepted candidate. Existing CSS
  pseudo-class and large-chunk warnings remain; temporary output-directory
  warnings are expected. No dependencies were installed.
- Eight synthetic real-producer execution fixtures pass their source check.
  Independent review finds no widening of claims or weakening of tests.
  Root inspects board, full-panel and phone screenshots.
- All 33 unchanged architecture diagrams and the published page remain
  synchronized. Diff checks pass.

**FAILED intermediate assertion:** the first wider price run reports 52 passes
and 12 failures, all at one exact tooltip expectation that still omitted the
new qualification. Appending the qualification to that expected string preserves
full equality and makes the same immutable bundle pass all 64. No production
edit followed that assertion failure; original evidence remains retained.

The combined run includes the separately published test-only
[phone scroll correction](phone-evidence-test-2026-09-25.md), checkpoint
`39daae1c47b0b3b77c0ec53d21c8f75bfaa7bcb8`. Its old visibility failure was a
test-placement defect, not a new production layout regression.

## Evidence and source identity

Starting production tree: `a5de878f62c54d2d6713d783c4312b012272c0bf`.
The phone-only checkpoint changes no production source. Final StockBoard SHA256:
`b2da497f10771cb7e588f88a7d326bfd06efad6a1cd676c58e995ee8ba19f950`.
Accepted asset `index-DytNPHqD.js`, SHA256
`8d078ca40efe634b83eece063b23a07237ece4f09c44609e7926ad45b7a07119`.

Agent evidence directory:
`/private/tmp/anios-display-snapshot-wording.7uTeIm/`.
`BASELINE_FAILURE.md` SHA256
`ec13ae14079fc8927ee5a681bf321e720ce7141f88f2d9d5ac462185976b018e`;
`candidate-broad-report.json` SHA256
`fc4933d6f2691a53eb51397687fdf855b2277e16eb1f13e067315650027ad4ea`.
Original/candidate bundles, sources, reports and screenshots are retained there.

Root receipt: `/private/tmp/anios-display-root.4tLv17/ROOT_RECEIPT.md`, SHA256
`0db5f60102cc0597979200dbb66983ac2a6392971b2811eb79b908ebecf2fa01`.
Its `display-report.json` SHA256 is
`eb3ece367ba2dd5be1e9a5e415fe9dce921a10f3918cfed3ea9b3d496d11ddc3`.
Both use cached headless Chromium, isolated network-none containers, read-only
source and identified assets, with synthetic API interception. No macOS
computer-access permission or system-setting change is needed.

## Limits

**UNVERIFIED:** deployed provider availability, all-hours coverage, actual
occurrence of this display/execution divergence in production and profitable
strategy behavior. This is not a fresh quote probe, a fix for the underlying
unavailable data or qualification of wide IEX execution. No backend, collector,
provider/model/account call, fit, historical replay, order or holding changed.
No deployment or service restart; collector activation still needs direction.

**Diagram impact: NONE — snapshot-local wording; no architectural flow change.**
