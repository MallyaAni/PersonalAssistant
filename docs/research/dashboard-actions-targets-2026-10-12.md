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
the final source after the copy adjustments. Canonical deployment and actual
compiled browser acceptance are pending at this code checkpoint.

Only frontend source/tests and docs change. Preserve all28 reviewed trading
files, original eight numeric artifacts, configs, Friday record and paper state,
backend/model services and the completed evidence roots. First ordinary learned
nightly, fresh timing and following paper execution remain unverified. This is
not an independent numerical audit of every financial value for all94 stocks.

Diagram impact: NONE — restored filtering and dated presentation of existing data.
