# Candidate: retire the pre-meeting FOMC cut

Status: IMPLEMENTED on branch `fix/fomc-chart-20261028` in
`~/scratch/fixes-20261028`, tested, NOT merged, NOT installed. The installed
release (`map-fixes`, approved 2026-10-28T03:59:44Z) still runs
`fomc-3-session-weakness/2` until this release is approved and installed.

## The change

`backend/agents/trading/desk/event_risk.py` becomes
`fomc-hold-through-meeting/1`:

- `ENABLED = False`, `RETIRED_ON = 2026-10-28`, with the reason recorded in
  `RETIREMENT_REASON`.
- `live_path` returns full exposure on every session; no new reduction can
  be planned (`event_execution.plan` and `policy_book.simulate` only start a
  cycle when the factor is 0.5).
- `decision` still reports the calendar, sessions to the next decision,
  SPY's five-session return and the retired parameters, so the dashboard
  shows what the rule would have seen.
- `exposure_path` and `evaluation_slices` remain for research and for the
  arithmetic of a cycle that was already open.

`backend/api/v1/market.py` serves `enabled: false` and `retired_on`. The
desk panel now stays visible while an event cycle is open, labels itself
"retired policy", and states that no reduction is requested.

No sizing, grading, model, cost or timing parameter changes. The open
2026-10-28 cycle still restores at 15:45 ET under `decision_close`.

Retiring the cut also removes the pause it needed: `event_risk.calendar_blocks`
is false for a retired policy, so an unavailable FOMC calendar no longer
routes the nightly to a HOLD. `nightly_plan`, `event_status`, `decision_view`,
`holdings` and `learned_personal_guidance` use it; an enabled policy keeps
the old pause, and records written before retirement (no `enabled` flag)
keep it too.

## The evidence

`docs/research/fomc-cut-retirement-2026-10-28.md` and the addendum in
`docs/research/fomc-lead-in-2026-10-22.md`. Across the 34 triggered meetings
2015-2026 the book rose from the cut to the decision close in 20 (59%),
mean +0.48%, median +0.86%; SPY rose in 21 (mean +0.18%). The ten-year
five-session lead-in is positive on average, and halving the book from five
sessions before each decision with 25 bp per leg cost about five points a
year. The gate is waiting at 1 of 6 meetings (−$770.49 September,
−$1,403.15 October through 10-27 after costs).

## Tests

- `backend/tests/test_trading_event_risk.py` 11 passed.
- Event/planning suites (nightly_plan, plan_parity, policy_book,
  market_event_recovery, trading_event_execution, fomc_gate, live_policy,
  market_daily) plus the event-risk file: 149 passed, 1 skipped.
- View/board suites (decision_view, market_holdings, personal_guidance
  isolation): 95 passed, 1 skipped.
- `test_live_model_history_nightly_model.py` 41 passed; adjacent simulation
  suites (live_policy_features, midcycle_ew, execution_ablation,
  allocation_evaluation) 68 passed.
- Frontend: `tsc --noEmit` clean; 15 FOMC Playwright cases pass, including
  the three new ones (retired label; an unknown calendar does not pause; an
  open cycle stays visible).

## Install sequence (after 15:45 ET on 2026-10-28)

Let today's restoration fill first. Then merge `fix/fomc-chart-20261028` to
main, push, verify `source_identity()` equals `release.proposed.json`, and
run `install_leader_release.py --revision <merge commit>` with the owner's
authorization, then deploy through `scripts/deploy.sh`. Confirm
`check-trading-admission.sh` ADMITTED with host == container before the
19:30 ET nightly, so tomorrow's plan runs retired. Do not deploy during the
nightly.

Bound sources changed (5):

- `backend/agents/trading/desk/event_risk.py`
- `backend/agents/trading/desk/nightly_plan.py`
- `backend/api/v1/market.py`
- `backend/market/decision_view.py`
- `backend/market/learned_personal_guidance.py`
