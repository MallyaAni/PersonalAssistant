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
VERIFIED canonical deployment of641344ebe10135fbc5d0ae74b2605d9294a8430f,
completed2026-10-12T07:51:19Z, exit0. The script selected its frontend-only short
path, built/type-checked frontend and gateway, and passed cheap post-deploy
checks. No skip flags were supplied and the original complete10586-unit/
100-routing gates were not repeated. Root
scratch/learned-dashboard-release-20261012 retains claim, execution, deploy log
and independent verification. Exact [release proof](learned-dashboard-proof-2026-10-12.json).
Execution SHA50e07ea82fb7403254d1bab3e2a2e3d0d35634a83f07448cefc5b0b40fc8ccd3;
log65b25a7f2073c6c8b972760cfe8686cd3e3ed3d11d609147dffa275b5c9b4b1f.
Gateway609d205281f2/imagea860c48f; compiled index SHA
2fbc8dcc07a8769648112a6c69c07bdee53dd9da9e5a0ba74160c672ebe37ba0.
The independent check compared all16changed tracked files to Git, authenticated
the new compiled text and absence of the old grade-priority text, and verified
unchanged28trading files, original8artifacts/configs/state/Friday record and all
other services including the backend and main text/embedding models.

VERIFIED manual browser session on the actual compiled deep-matter.com desk:
reload/auth persistence,10paper positions/no orders, new Reset ranking text,
explicit grade sort and restoration of the allocation-based order, SNDK details
with the correct original Friday target/policy, and strong-grade-trim help.
Console errors/warnings0 after reload. An old-tab paper502 observed before the
reload cleared; the new session loaded real paper data. Friday remains
graded-equal-weight/5; the browser did not fabricate a learned nightly record.
Screenshot /tmp/learned-dashboard-ranking-live-20261012.png, SHA
dfdb2d557cff99738e16c59a4e0915ee9308de1a19a297522eaac8814d90c17b,
kept private outside Git. The33diagram pairs passed synchronization; the
ancillary architecture.html fingerprint check remains FAILED on unchanged
inputs (diagram sources, ML_SYSTEM_DESIGN and page generator were untouched).
No unrelated page regeneration was included.

UNVERIFIED first ordinary learned nightly (Monday October12,19:30ET), fresh
actual-session learned timing and following paper execution/reconciliation.
Fixture browser scenarios are not that market-session proof. No new fits,
orders, backtests, control replays or economic superiority claims.

Diagram impact: NONE — presentation of existing allocation and execution data;
no architectural boundary changed.
