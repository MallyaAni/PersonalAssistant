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

VERIFIED first semantic release9f028b8208640ecf2c476205503be920c6765a4e,
canonical frontend deployment finished15:25:17Z, type/build/cheap checks passed,
no skip flags. Root scratch/learned-chart-execution-release-20261012, independent
execution9715fb47a6e6499263495e8e0bf5625f8e4bd895b5242c28c98c11b5b6e5ed22.
Actual browser authenticated compiled asset index-lOo_4x1O.js; SNDK, NTAP and
AAOI D/W/15m share sizes and dated fill lists; NTAP5/10/20/60intraday windows;
0console errors/warnings. SNDK timed BUY1/BUY2 and AAOI SELL127 were painted on
their recorded intraday bars. FAILED full-range label bounds: some edge BUY
labels clipped horizontally and same-candle labels could exceed vertical space.
Two new actual-canvas bounds regressions reproduce clipping on desktop/phone.

Targeted follow-up preserves every fill separately, reduces circle size and
reserves space for each visible label. Full history gets edge padding; panning
and zoom keep the selected range and update vertical room. No quantities,
prices, times or trade logic change. Bounds tests check actual painted text lies
inside the canvas on D/W/15m at1280/390px, including first/last fills and five
same-candle executions. Initial bounds candidate2/2passed; broad suite108other
cases passed while two expanded bounds cases failed because the harness cleared
paint evidence before clicking an already selected D view, which requests no
redraw. Retained the failed run, fixed its interaction sequence and kept every
bounds assertion. All8 source checks passed, including Recent/Full history.
Shortened the default15m caption and collapsed the detailed historical policy
comparison. VERIFIED all9 final source cases passed, no skips; type/build passed.
This covers111 unique cases across the broad suite and focused runs. Distinct
canonical scratch/learned-chart-labels-release-20261012 remains pending at this checkpoint.
Never rerun the first deployment.

Diagram impact: NONE — existing chart layers and order presentation.

The bounds release c5ba98f002a606312a9d25faa85c024471162125 completed canonical
frontend deployment at15:52Z, with independent exact source/bundle checks.
FAILED live readability on crowded AAOI weekly views: long individual labels
overlapped and dynamic vertical margins distorted the stock-price scale.
Fixtures passing text bounds did not prove legibility on a dense real chart.
Both semantic and bounds roots/screenshots remain preserved; never rerun them.

The final presentation replaces stacks with BUY/SELL filled-share totals per
candle: per day on D, per week on W, per containing15-minute bar on15m. BUY and
SELL are never netted. A label is a sum of recorded filled shares, not a single
new order or a reconstructed model trigger. Individual records, original dates,
quantities and unadjusted fill prices remain unchanged in the list. Removed the
extra vertical-margin algorithm; retained edge spacing and small circles.
Stock-price axis padding below zero is not labelled as a price. Markers say
action and shares only; their legend defines the grouping.110browser cases
passed/no skips on this candidate; all11final-source cases passed afterward,
including D/W/15m, both ranges, phone/desktop, nonnegative price labels,
same-candle totals and separate BUY/SELL weekly totals.111unique cases overall.
Canonical scratch/learned-chart-shares-release-20261012 pending. No data, trading rules,
model artifacts or backend services change.

Share-total release9bb741752e6975dff3ff3ef1236454e1fe537554 completed16:30:49Z,
root scratch/learned-chart-shares-release-20261012; source/bundle/preserved files
verified. Real AAOI daily and weekly totals matched the individual list; price
scale distortion resolved. A final recent-W spacing adjustment shows fewer
candles at once so adjacent weekly quantity labels have room on desktop/phone.
All260weekly candles and21/9-week indicators remain loaded and unchanged; this
does not alter a strategy or qualification window.11targeted final-source cases
passed, including every timeframe/range/phone path. Distinct canonical
scratch/learned-chart-weekly-spacing-release-20261012 pending; no prior release
rerun.
