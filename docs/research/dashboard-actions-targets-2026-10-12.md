# Action filtering and saved allocation labels

The user reported that clicking Action no longer filtered the board and that
plain "target 10%" text looked arbitrary under the new learned system. The prior
audit missed the lost heading interaction and did not make the saved-plan basis
clear enough in compact rows or chart summaries. Starting clean main checkpoint
5b7f2e69876cf81acb08ca00b90f6fc53611af6c on
codex/learned-live-release-20261006; main pulled before editing.

VERIFIED production source of the values: the October9 record was written
2026-10-09T23:47:24+00:00 under graded-equal-weight/5, with ten 0.1 targets and
84 zero targets. Installed holding policy is
joint-stock-risk-funded/6-retained-holdings-probability-timing-research, config
d4ff38db0f136462f5ff0246fdb0737a9947603d4a5fe9ad0d46792e626c2704.
The old targets are real archived values, not freshly computed learned targets.
No record, account, model or config is rewritten to manufacture a new plan.

The Action heading now opens BUY, SELL, TRIM, HOLD and No order checkboxes.
Mixed orders match each actual displayed leg. Filtering composes with search
and the existing views/sorts, survives live paper refreshes, includes completed
orders as history, and has explicit recovery from empty results. All selected
actions preserve the complete original view. The menu supports outside clicks,
Escape/focus restoration, and a phone viewport without clipping the recovery
control. It never changes an order or personal account.

The board labels its saved allocation session/policy. Compact rows, row details,
stock cards and the chart's current-position summary date every saved target.
Missing targets remain unavailable. Holdings without an order compare against
the saved target but no longer promise a future trim/top-up at an old reset.
The old reset count is identified as recorded, and actual order wording remains
the executor's own wording. This presentation also applies to future learned
records; no installation state or current allocation is guessed from a grade.

FAILED baseline: both new interaction/provenance cases fail against the unchanged
compiled prior release; private logs/traces retained under
/tmp/dashboard-actions-targets-baseline-20261012.log and its results directory.
VERIFIED candidate: 52 board/personal/chart browser tests plus six targeted
layout/stock-panel cases passed without skips. TypeScript and Vite production
build passed, with existing build warnings. All three focused cases passed on
the final source after the copy adjustments. This is 58 unique cases, with the
three final-source cases rerun, not 61 distinct cases.

VERIFIED canonical frontend release 9fee373ce9eb779478bc0cd614ae0e0e48187efb
through scripts/deploy.sh, no skip flags; type/build and cheap post-deploy checks
passed. Independent execution SHA
7b46c6f497c74f7a20d4e3a047ad5a4f4123ff3f311576451979483fcbb00ba9;
log SHA faf10fe2314b2549c9f7bb85de762f9cb9514cd30342da6377f961e20b563a2d.
Root scratch/learned-dashboard-actions-targets-release-20261012, gateway
d2ec12494487/image75272b7f; compiled index-B_QZE9i-.js SHA
126e6008839bfe571ef0eed5e1a75c685f04422da8e672e225926415a00e5af7.
Backend cfe8b7b50228/e479 and model services unchanged. All28 reviewed trading
source files and14 original artifact/config/state/record hashes match before,
after deployment and after browser acceptance. Never redeploy for this proof.

VERIFIED actual authenticated browser reload of that compiled asset: Action's
five filters open; deselecting HOLD hides ten portfolio rows and yields the
correct empty state; Show all recovers them; Escape dismisses the menu. All-name
counts are BUY0/SELL0/TRIM0/HOLD10/No order84. No order selection composes with
SNDK search and Show all actions recovers it. SNDK expanded row, full card and
chart Now summary all show Saved target10.0% with October9 session; row details
retain graded-equal-weight/5. Restored default portfolio view. No console errors
or warnings, no submitted orders. [Exact proof](dashboard-actions-targets-proof-2026-10-12.json).

Only frontend source/tests and docs change. Preserve all28 reviewed trading
files, original eight numeric artifacts, configs, Friday record and paper state,
backend/model services and the completed evidence roots. First ordinary learned
nightly, fresh timing and following paper execution remain unverified. This is
not an independent numerical audit of every financial value for all94 stocks.

Diagram impact: NONE — restored filtering and dated presentation of existing data.
