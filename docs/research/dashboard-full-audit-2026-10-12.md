# Full dashboard consistency audit

The user asked for every dashboard surface to agree with the released learned
paper system. Starting branch `codex/learned-live-release-20261006`, HEAD
`e1887e2ac7a626557812f68e51a4a000aad575d0`, clean; main pulled and current.
The prior ranking release `641344eb` was already deployed and accepted. This
follow-up concerns presentation and browser acceptance, not new economic runs.

The source audit covered the paper board and filters, account-size scaling,
row details and full stock panels, daily/weekly/15-minute charts, recommendation
archives, paper balances/history/fills, optional personal inputs and receipts,
analyst votes and evidence dates, quote provenance, options diagnostics,
opportunity explanations, FOMC controls, and historical/frozen/forward research.

| Surface | Consistency requirement and correction |
| --- | --- |
| Rankings and targets | Existing automatic ranking remains readiness/funded orders then recorded targets. Explicit zero now remains visible in the compact position column. |
| Timing/help | Use the executor's recorded rule. Missing plans remain unavailable; no invented old 1% rule. A next-open tag does not imply next-close sells. |
| Row and stock details | Share the original model observation, state, reason and timestamp; observations are not fills. Restore the same dated analyst evidence in row details. |
| Event allocation | Identify the recorded FOMC priority separately from available or unavailable ordinary model allocation. |
| Charts and replay | When historical and current policies differ, label the comparison explicitly. Historical grade statistics and replay decisions do not describe the new allocator. |
| Opportunity analysis | Analyst reference scores do not override recorded targets or orders. |
| Personal guidance | Only show personal guidance/confirmed-fill controls when the personal section is opened. Preserve separate account/cash inputs and backend policy admission. |
| Research | Preserve original policy, source, costs, windows, missingness and limitations. Frozen comparisons are not adoption proof or personal-account returns. |
| Prices/options | Preserve independent source/capture/effective timestamps, stale/unavailable states, and stored options calculation provenance. |

The first audit attempts exposed outdated browser selectors and an environment
mismatch: dev API defaults to localhost:8000, while strict fixtures require the
same origin. The final sweep uses the TypeScript-checked production Vite build
through a local preview, matching the gateway's compiled delivery. Tests now
open actual row details for reasons and the separate technical panel for stored
options evidence instead of expecting obsolete duplicate locations. Options
provenance and technical assertions remain intact. Intentional conversation
request cancellation during an explicit reload is recorded separately; required
desk request failures still fail the fixture. No fixture can submit provider or
broker writes. Failed logs, traces and screenshots remain private under /tmp.

Three new consistency scenarios fail on the unchanged e1887e2a baseline:
missing timing acquires the old rule, event allocation is called unavailable,
and full stock details omit the recorded model observation. Candidate focused
sweep: 145/146 passed; the remaining test expected obsolete legacy prose and
was updated to verify the same recorded timing. VERIFIED all 348 unique cases
across 27 files: the compiled full sweep passed 336 with 12 fixture failures;
the entire affected independent-session-prices file then passed 16/16, no skips.
Its original clock setup could pause in the past after transport latency, and
its initial price assertion preceded its promised response-batch wait. The fix
pauses at the same original instant before navigation and waits for the original
synthetic quote response before asserting the unchanged exact content. No
production fix or relaxed numeric/provenance assertion was used for this race.
TypeScript and Vite production build passed; existing CSS/chunk-size warnings
remain. Full log SHA 80b3b7bda0b0a60ceb2f764feb3def691a32253aa1bb40e111f2a2d598ad5649;
build log b879f6ec0792e36b4a1e5e4ee02f91ff726402cc80ad7ecf1165fb32c7768a7d.
Baseline and all intermediate failed results remain private. Canonical deployment
and actual live browser acceptance are pending at this code checkpoint.

Only frontend source/tests and docs change. Preserve the reviewed 28 trading
runtime files, original eight numeric artifacts, installed holding/timing
configuration, real paper state and original Friday record, and backend/model
service identities through the canonical frontend deployment. Friday legitimately
keeps its original graded-equal-weight policy. Do not rewrite it to learned.

UNVERIFIED: first ordinary learned nightly, real-session timing observation and
following paper execution/reconciliation. These browser fixtures do not close
those boundaries. The live browser panel is presently queued/unavailable for
attachment; its new release must not be labelled manually accepted without a
fresh actual browser session.

Diagram impact: NONE — presentation of existing evidence/decisions; no new
agent, architecture boundary, model, API, database or execution path.
