# Dashboard consistency with the learned paper policy

The user required the live rankings and explanations to follow the released
learned allocation, holding and timing system. The deployed backend and installed
selectors were already verified; the board still added A+/A buy and C/B exit
priority and described sizing with the old reset rules. This was a presentation
gap in the release, not a new model qualification or parameter experiment.

The board now presents exceptions, due orders and waiting orders first, with
funded order size determining priority within the actionable groups. Other names
follow the recorded policy target weights. Analyst grades remain available and
can be sorted explicitly, but do not override automatic action priority. This
is a view of the allocator's recorded decisions, not another trained return score.
Unsupported retained holdings are shown separately from available model
allocations. Missing targets remain missing; explicit zero remains zero. A
receipt from another session cannot label a target as a current model allocation.
Order status and timing remain the executor's own recorded words. Row details,
ticker panels, plan status and the guide use the same allocation basis and permit
model reductions while grades remain strong. Historical records keep their policy.

VERIFIED local browser acceptance: 33 tests in desk-trade-board.spec.ts and
simple-actions.spec.ts, plus the affected analyst-guide test, all passed with no
skips. The tests cover an A+ trim ahead of a smaller C exit, target ranking against
grade and position size, retained capital, zero/missing targets, stale receipts,
manual sort/reset, refresh, completed/mixed orders, personal isolation, mobile
layout, and matching ticker details. TypeScript and the Vite production build
passed. Existing CSS/chunk-size build warnings remain. The two new ranking cases
fail on the unchanged 68617e2b baseline: small C exit first and position-size
ordering. Baseline and intermediate failed test logs are retained privately under
/tmp/anios-dashboard-baseline-20261012 and /tmp/learned-dashboard-*.log.

Only frontend source/types/tests and documentation changed. The 28 reviewed
trading runtime files, original eight artifact files, holding/timing configs,
account state and Friday record must remain unchanged through deployment.
Production release/browser verification is pending at this checkpoint and will
be recorded after canonical scripts/deploy.sh completes. The original complete
10586-unit/100-routing deployment is not rerun for this frontend-only diff;
the canonical script determines its applicable gates and image builds.

UNVERIFIED first ordinary learned nightly (Monday October12,19:30ET), fresh
actual-session learned timing and following paper execution/reconciliation.
Fixture browser scenarios are not that market-session proof. No new fits,
orders, backtests, control replays or economic superiority claims.

Diagram impact: NONE — presentation of existing allocation and execution data;
no architectural boundary changed.
