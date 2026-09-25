# Stock-history return units and missing evidence

## Objective and unchanged boundaries

Correct the dashboard's historical price-change display, missing-vote meaning
and regular-session execution explanation. No stored record, return calculation,
model, grade, allocation, collector, account or order behavior changes.

Starting main revision: `d8dcca430267df410ebe7892669e15de6e780153`.
The turn's initial pull was current. Only the history/display component, its
client contract, regression tests and this evidence documentation change.

## Findings and targeted corrections

- `Panel.forward_log_returns` calculates `log(adjusted_close[t+h] /
  adjusted_close[t])`; the desk history writer rounds it to six decimal places
  and HTTP preserves those units. The old table multiplied it by 100 and
  labelled it a percentage. A doubling therefore appeared as +69.3%, not
  +100%. The display now uses `expm1(log_return) * 100`; missing, nonfinite or
  overflowing results remain unavailable. Its explanation names adjusted-close
  price change, not a funded trade return or personal P/L. The separate
  conditional annualized daily log-return statistics remain untransformed.
- Historical grade comparisons previously substituted neutral for a missing
  earlier vote and ignored an analyst absent from the later panel. They now
  compare the union of both panels. Only numeric -1, 0 and 1 count as observed
  votes. Unknown-to-known comparisons explicitly do not prove a vote changed.
- Independent review found that session-row glyphs still contradicted those
  comparisons: null rendered neutral and an invalid number rendered
  `Fundefined`. A history-only formatter now applies the same validity check
  and displays `?`, with a matching legend. Shared live vote rendering is
  unchanged.
- Published empty vote maps can have either an omitted aggregate or explicit
  null. Both arrive through HTTP as null and previously crashed `.toFixed`.
  They now display `Votes not recorded`; genuine aggregate zero remains zero.
  The client type reflects the nullable field.
- The exact execution reason `Market closed or clock unavailable` previously
  became `Market closed; no executable quote until the open`, erasing
  uncertainty and overgeneralizing the regular-session execution policy.
  It now says the regular session is closed or its clock unavailable and
  execution is blocked. A fresh overnight display quote does not resolve
  execution eligibility or erase strategy intent.
- The session-count heading now uses the singular when exactly one row is
  shown. No history filtering or sorting changes.

`published` identifies the grade/vote overlay from the retained nightly record,
not the provenance of every field in the row. Outcomes, exposure, confidence
and earnings markers are still replay-derived. The client comment now states
that boundary; no archival merge behavior changes. The converted percentage
inherits the stored six-decimal log-return precision and the available price
history's adjustments, not independently verified executions or accounting.

## Backend acceptance

**VERIFIED:** 18 tests passed, zero skips/warnings, 1.90 seconds. The new test
file supplies seven cases, with eleven neighboring contract checks.

Synthetic raw closes stay constant while adjusted closes double, halve, then
stay flat. The real writer and authenticated ASGI HTTP route preserve rounded
log returns; inverse conversion recovers +100%, -50% and 0% within rounding
precision. Published partial/empty stances override replay evidence, while
explicit null, omitted aggregate and observed-zero controls remain distinct.
JSON files remain byte-for-byte unchanged after GET; stranger access is denied.
False/unknown regular-session flags retain supplied dated quotes and strategy
intent while blocking execution at `describe` and `decision_view` boundaries.

This is real in-process ASGI HTTP, not Uvicorn startup or deployed-provider
acceptance. In particular, it does not exercise a clock exception inside
`execution_quotes.fetch`, whose existing fallback can discard quotes. No model
inference, production account, external data or database is exercised.

Backend evidence:
`/private/tmp/anios-history-contract.qrDGKs/RECEIPT.md`, SHA256
`b40ab30dfaa5b6dfa41b1956012bfc00a7070c5ce470ee2d4206a9cd803d71de`.
Final JUnit `backend-reviewed.xml`, SHA256
`64691e829404e43c6ea1de97fb0a30581e6296e423e1432ba6269cf93ad5d639`.
The receipt records the exact cached Python image, read-only checkout and
network-disabled runtime. Scoped Ruff check/format and `git diff --check` pass.

## Browser acceptance

**VERIFIED:** 144 browser tests passed in 67.94 seconds, zero failures, skips
or flaky cases: 16 new history cases plus 128 neighboring desk cases. Final
TypeScript and production build pass. Existing CSS/chunk-size warnings remain.
The browser serves the preserved `build-accepted` artifact over isolated
loopback, not a hot-reloading checkout or the deployment clone. Source and
dependencies are read-only, network is disabled, APIs are intercepted with
dated synthetic evidence, and the new cases check page/console errors, failed
required requests, unexpected network access and forbidden writes.

The actual history dialog shows ordinary +100%, -50%, zero and unavailable
outcomes while retaining conditional log-return statistics. Empty/partial,
invalid, null and genuinely neutral votes stay distinct in transitions and
row glyphs; missing aggregate rows render without crashing. The overnight case
keeps a dated BOATS display price and Sell intent while execution is blocked,
including a visible corrected clock explanation. Both the root and frontend
agent inspected screenshots. Independent source review found no remaining
blocking issue in the scoped correction.

**FAILED before correction:** the initial nine-case baseline had seven product
assertion failures, one genuine-zero control pass and one locator failure. The
corrected locator independently reproduced the bad clock title. A later test
reproduced the null-aggregate crash. Independent review reproduced four
invalid/null glyph failures against the first built candidate; the singular
heading assertion also failed before its correction. All original results
remain retained. A hot-reload candidate run had 33 passes and one strict
diagnostic failure from 18 aborted module requests after an edit. Acceptance
moved to immutable built bytes without weakening those diagnostics.

Browser evidence: `/private/tmp/anios-history-accuracy.Owh809/RECEIPT.md`.
Receipt SHA256:
`9a3c0c216e5ffadb84a1165cd6aab57ae2cad33190a0e26a05c820b403ca80dc`.
`accepted.json` SHA256:
`8337783e8988a288fd15234e9852c7151b8c3383335b24d80bca9ecc6b8f94da`.
Main built asset `index-CPp9Lo2K.js` SHA256:
`3351f0703fe1226e78df1caa754c0c0eb875dab92e828ace722e35f218f96d83`.

Final source SHA256:

- `DeskPanel.tsx`: `268666e7fc54cefd23e4105d7efadc44ab3330ed5564bfcaf9e4e21b84650179`.
- `api.ts`: `101931c9058f38b2c342a424740cbda46ed43a65ffda58679cb28cf95faaf478`.
- `desk-history-accuracy.spec.ts`: `a02442dc180b27350a55ffff59236756c5bc38baba2490489e34bb4f780427ab`.
- `test_desk_history_meaning.py`: `2e1e4d42c3db06c475bc292e02d986f94c0baa3dd48521974c62bbc1ff1b1437`.

## Deployment and performance limits

No deployment or live data request is part of this correction. It neither
qualifies continuous overnight coverage nor establishes an investment edge.
Full release gates, actual runtime artifact identity and the deployed user
workflow remain **UNVERIFIED**. Collector activation must be resolved before
restarting the pending backend. Deployment remains Spark-only through
`scripts/deploy.sh --wait-post`, without bypassing its gates/postchecks.

**Diagram impact: NONE — field-level frontend meaning and contract tests.**
All 33 unchanged diagram render/fingerprint checks and the published page pass.
The first invocation used host Mermaid CLI 11.17.0 and correctly failed the
fingerprint check; mounting the existing lockfile-pinned 11.16.0 dependency
volume repaired the invocation. No canonical diagram or dependency was changed.
