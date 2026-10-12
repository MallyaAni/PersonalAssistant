# Chart actions, sizes and execution times

The user asked whether an action and size on any stock chart represents a real
historical trigger, and required simple wording across every viewable timeframe.
Starting clean e42953b78f412747df6d933a8a543b42c2ac1b4d on
codex/learned-live-release-20261006; main pulled before editing.

VERIFIED source distinguishes three meanings: paper fills from settled records;
grade changes (saved or recalculated readings); policy replay (recalculated
historical targets). Replay is not a recorded order, fill, or qualification of
the installed learned policy. Current order quantities also have a planned,
submitted or filled basis; opposing legs must not be summed as one action.

FAILED prior presentation: grade arrows appeared by default alongside execution
markers; fifteen-minute fill markers accepted the endpoint's assumed opening
or closing slot for a fill that carried only a date. Mixed current orders could
show one aggregate quantity. Two default/timing regression cases fail the prior
compiled source. Original private traces retained. A first candidate suite was
stopped after optional-grade tests failed to enable the newly optional layer;
those tests now explicitly enable it and retain their full source/paint checks.

The default chart marks paper fills only. Its concise legend identifies shares
and fill price, unadjusted fill prices on D/W, and weekly grouping. Grades,
personal saved recommendations and replay remain available by explicit selection.
Recommendations remain labelled as recommendations, not fills. Fifteen-minute circles now
require the original timezone-aware execution instant and its containing valid
candle; date-only executions remain in the list with a short timing note.
Removed unused projected-fill and convention-timed fill drawing paths. Nonpositive
fill quantities/prices are rejected. The current chart summary preserves each
BUY/TRIM/etc. leg's quantity, basis and state. No record or trading logic changes.

VERIFIED read-only serving audit of all94 stored histories: all104 fills exactly
match the settled-record reader;80 have stored execution times and24 carry only
a date. All histories asof October9 under graded-equal-weight/5. Private proof
scratch/chart-history-provenance-20261012-v2.json SHA
b8d6d5d4c917689ef0ec5bc19080c945980232ad11e87b75b65c6d0b615491b1.
Initial private helper import failure retained; no product defect or data change.
These are recorded historical paper trades under their original policy, not
proof of what today's learned system would have triggered in the past.

VERIFIED108 browser cases across charts, paper account and trade board, no skips;
real canvas painting, timeframe/visibility controls, archive immutability,
personal isolation, missingness, live refresh, multiplicity and phone layouts.
Final production type/build passed; six focused final-source cases also passed
before the last personal-recommendation default adjustment. All six release-source
cases passed again afterward, including the main desk timeframe journey. This
is109 unique cases with focused reruns. Deployed browser acceptance remains
pending at this source checkpoint. Preserve completed backend
release, models, original artifacts/configs/state/Friday record and all94histories.
Deployment only through scripts/deploy.sh, distinct
scratch/learned-chart-execution-release-20261012. Do not repeat old gates/accounts.
Ordinary learned nightly and subsequent paper execution remain unverified.

Diagram impact: NONE — existing chart layers and order presentation.
