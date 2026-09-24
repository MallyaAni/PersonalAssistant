# Dated evening analysis and latest available grades

## Objective and boundary

Separate the latest accepted grade and personal decision from the dated evening
analysis in both the stock-row expansion and full ticker panel. Preserve the
original recorded wording without presenting a historical imperative as a
current trade instruction. Expiry must restore the evening grade and remove
intraday vote changes. Both surfaces must remain usable on a 390-pixel phone.

This is presentation only: no score, model prompt, API, permission, persistence,
strategy, holding, order or deployment changes. It does not establish fair value
or a current executable signal. Diagram impact: NONE — unchanged data flow.

Started on `main` at `7d801c1af051cb8ca6bebb868b8d6183a09b7094`.
Only the three coordinated frontend files were dirty on resumption; no unrelated
local changes were present. A fresh fetch confirmed local/origin divergence 0/0.
The standing workflow remains Mac → `spark main` → GitHub from Spark. Deployment
is a separate authorized action on Spark through `scripts/deploy.sh`.

## Defect and correction

The preserved synthetic browser baseline renders an evening A+ and the undated
headline `Own: 3 analysts for, none against` beside an intraday B and a newer bar
price. One diagnostic journey passed and the intended dated-summary regression
failed. A repository regression then failed before the production edit.

`EveningAnalysis` now renders the recorded grade, structured votes, session and
unchanged reasons. The exact original headline is closed by default under
**Original recorded wording**, with its recorded write time and an explicit
historical/non-current-instruction warning. **Latest available grade** separately
contains the accepted grade, vote changes, dated bar and existing decision.
The existing freshness filters and evening-row normalization remain authoritative.

Three existing journeys now open the original-wording archive before asserting
the headline; one existing locator is scoped to the separate full-evidence
section. Their content assertions remain. No raw archived record is rewritten.

## VERIFIED acceptance

- Full Desk browser matrix: **115/115 passed**, no skips or flaky tests,
  **79.812 seconds**: 106 existing cases plus nine new timing/mobile cases.
- Final focused repeat after adding the scrolled mobile screenshot and two
  viewport assertions: **9/9 passed**, **8.213 seconds**.
- All nine focused diagnostic records: zero console errors, page exceptions,
  failed requests, HTTP errors, unexpected requests or forbidden writes.
- Exact grade assertions cover row/no-row, current/expired/missing updates,
  expiry while the dialog is open, preserved accessible headline text, archive
  controls, mobile overflow and complete visibility of both grade sections.
- TypeScript `--noEmit`, production build and `git diff --check` passed.
- Root and implementing agent inspected the desktop, mobile expansion and
  scrolled mobile detail screenshots. The original failed reproduction is kept.

An initial whole-Desk run had 105 passes and nine failures: five screenshot
writes into the read-only source mount, plus the four intentional workflow/locator
changes above. The runner's working directory was moved to writable evidence;
the source stayed read-only. These failed runs are retained, not discarded.
Build warnings remain for an existing CSS pseudo-class and large chunks.

Local evidence: `/private/tmp/anios-aaoi-browser.eVPCSe/`, including
`UI_CHANGE_ACCEPTANCE.md`, `repo-regressions-02.json`, `repo-final-focused.json`,
the original `results-02.json`, screenshots and failed-run traces. That receipt
records full commands, runtime and source hashes. Vite serves the actual checkout
on localhost 5174, not the deployment clone. Runtime: Node 24.20.0, Playwright
1.63.0, Vite 8.3.1; image digest
`sha256:eff16c30e6f3f4af0a03fa4b706120d5e9b0891c344a27d64559aff5900a4a27`.

Final frontend SHA256:

- `DeskPanel.tsx`: `0c53cd2d66e253fd8e2be9b9186cc4710f1aa5c989724d93bf70f975838f5b8d`
- `desk-evidence-timing.spec.ts`: `190012efc8d82ca6aae96378e0e8ddf2f6a7ff31ace33a2b6492164d17bed48d`
- `desk.spec.ts`: `c4154ee962da5cdb0cfe41a798c35a21550ea67efdd38a2df01b2781f67583bb`

## Exact-commit checkpoint and retained proof

Commit `654e02f35a8316ea9d6789d568886982c2173590`, tree
`760152d2753189f0b25c35fe30f7d265d6c41805`, repeated **115/115** browser cases
in **80.882274 seconds**, zero skipped/flaky/unexpected results. All nine timing
diagnostic records have six empty error/write arrays. TypeScript, fresh
production build and diff checks pass; HEAD, tree, clean worktree and source
hashes agree before/after. Only the isolated local Vite server was restarted.
The exact-commit receipt is `COMMIT_654e02f3_ACCEPTANCE.md` under the local
evidence root, SHA256
`769e54bd168ffb72a7c829b45b18bc73a46e16974a38ee4ac2c59279de93abf3`.

The verified code checkpoint is published to Spark and to GitHub **from Spark**,
with local/origin divergence 0/0. No deployment occurred.
Separate evidence retention at
`/home/animallya96/anios/data/market/research/desk-evidence-timing-20260924.23g6gtpu/`
verifies **348 payload files / 29,173,792 bytes**, including the exact frontend
source archive, all final/failed browser evidence and transport tools. There are
zero missing, changed or unexpected payload files. All 44 files in the earlier
retained browser baseline are unchanged. The new
`retention/retention-readback.json` SHA256 is
`af9ec721bcbe21ecec4104e7cc7bc93b2bd0c28b99758d0c047c85c0bbab12cb`.
Local retention proof: `/private/tmp/anios-ui-retention.X3UwhZ/`.

## UNVERIFIED and next work

Public/deployed behavior remains UNVERIFIED; no deployment occurred. Fixtures
intercept all API traffic, disable desk writing, and allow only the read-only
mine POST with `record_history=false`. They prove this UI workflow, not live
writable-account persistence, primary financial accuracy or an AAOI valuation.

The wider AAOI concern is not solved by this display correction. Fundamental
scores use revenue growth/acceleration and gross margin, while sentiment is
earnings-release tone. Relative percentiles are not probabilities, and the
combined letter grade is neither intrinsic fair value nor entry timing.
Per-feature fiscal dates, precise analyst labels and scored-versus-context value
attribution remain separate tasks. Price/book is currently cited but not scored;
the active expectations-gap augmentation is absent from the prose score registry.
Do not silently alter scores or regenerate history to correct those labels.

The parallel source audit found historical availability gaps in expectations-gap
assembly. Their actual affected rows and financial impact remain unmeasured.
Keep the completed historical study frozen; do not retune it or promote its
large reconstructed incumbent return as investable evidence.
