# Shared nightly planning inputs

## Scope and status

The operator requested consistent rules for Stock rankings and the live paper
account. This checkpoint is a prerequisite, **not completed account alignment**.
It introduces no strategy candidate, timing change, personal account enrollment,
API, new archive or broker operation. The existing nightly paper call now uses
`nightly_plan.plan`, which dispatches to the unchanged ordinary/event planners.
This code remains on `fix/shared-strategy-inputs-20260929`, not production main.

The nightly record receives one market-only `planner_inputs` block: exact raw
closing prices, allocation targets, close grades, adjusted-close band entries,
band blockers, covered downgrades and event policy, with explicit versions and
session dates. Downgrades cover all graded names; each account's holdings filter
them inside the planner. Paper holdings, cash, equity, working orders and state
are not copied into this shared block. The existing balance history does not
duplicate it.

Broker reconciliation, cancellation, submission and state saving stay in the
existing caller, in the same order. Policy-migration force is decided before
reconciliation as before. The pure dispatch copies account state, including a
no-op plan, so a caller cannot mutate the input state through its return value.

## Boundaries that remain open

- Personal guidance still uses its separate planner and intraday timing rule.
  No current dashboard action changes in this checkpoint.
- Personal execution state is not initialized. It needs explicit confirmation
  of starting holdings/cash and outstanding orders; browser receipt
  acknowledgements are not fill confirmations.
- Ongoing alignment needs confirmed partial/full fills, rejected/missed orders,
  deferred buys, its own rebalance clock and the same auction schedule. A
  missed opening trade must not be relabelled as a current intraday Buy.
- Event/pending-order protection does not depend on entry calculations. Those
  records carry `entries: null` and `downgrades: null`, meaning not evaluated,
  not no signals. A different account cannot use that incomplete block for an
  ordinary plan; dispatch refuses it. Completing that market context without
  delaying event protection is required before personal activation.
- Legacy records and unsuccessful paper calls have no exact input block. No
  historical snapshot is reconstructed or claimed to be the executed input.
- Version checks reject incompatible planner policies; they do not certify
  replay across arbitrary source changes under an unchanged version.

## Verification

**VERIFIED:** 239 offline tests passed (8 warnings from existing missing-mark
cases): nightly input/dispatch tests, market daily, paper, event execution, live
policy, missing marks, grade parity, desk records/API, paper history and personal
isolation. The tests compare complete ordered order baskets and resulting state
with the original planners for rebalance, forced reset, mid-cycle, limited cash,
deferred buys, already-seen sessions, event reduction/restoration, pending orders
and unknown calendars. Actual record save/readback preserves tied-order inputs
and numeric values. Dry-run integration asserts no broker submissions or account
file writes. New module/test Ruff checks and `git diff --check` passed.

**UNVERIFIED:** full-repository gate for this additional refactor, deployed
behavior, personal activation and multi-session manual execution parity. The
8,073-pass full Spark gate belongs to the separate dashboard commit `f9618b1`,
not this code. No performance improvement is claimed for a behavior-preserving
refactor; the adopted allocation/execution policies remain unchanged.

Diagram impact: NONE — internal factoring of the existing nightly planning and
record flow; no store, account, execution or external-service boundary added.
