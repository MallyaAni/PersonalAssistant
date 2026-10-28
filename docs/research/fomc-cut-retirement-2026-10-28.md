# Retiring the pre-meeting FOMC cut — 2026-10-28

The owner's reading was that the book sells off into recent Fed meetings and
rallies into or on the decision, and that the paper account's rule was
cutting on the wrong side of that move. The measurements below say he is
right about the turn and that the cut was backwards on the longer record
too. The cut is retired; the account holds through meetings.

## What the rule did

`fomc-3-session-weakness/2`: in the three sessions before a scheduled
decision, if SPY's trailing five-session return was negative, held shares
were cut by half at the next open, held through decision day, and restored
at 15:45 on decision day (`decision_close`). The restoration timing was
already changed on 2026-10-23 after the post-June overnight gaps; the cut
itself was not re-examined.

## The measurement that decided it

Across the 34 triggered meetings from 2015 to 2026 (the rule only fires on
a negative five-session SPY return), measured from the cut to the decision
close on the paper book:

| | rose | mean | median |
|---|---|---|---|
| book | 20 / 34 (59%) | +0.48% | +0.86% |
| SPY | 21 / 34 | +0.18% | +0.41% |

The trigger is a dip signal, not a risk-off signal. The ten-year lead-in
study (`fomc-lead-in-2026-10-22.md`) found the five sessions before a
decision were *better* than an ordinary week: SPY +0.50% mean, 31% down;
QQQ +0.54%; book equal-weight +0.75%. Halving the book from five sessions
before every decision, with 25 bp per leg, cost about five points a year
over 2015–2026 (QQQ 18.6% → 13.2%; book EW 34.0% → 25.9%).

Since the June 2026 guidance change the selloff-then-rebound pattern has
been sharper — three of four lead-ins were hard selloffs and the two
completed cycles bounced +14.1% and +6.8% in the five sessions after — but
four meetings is an anecdote, not the basis for the decision. The basis is
the 34-meeting arithmetic, which points the same way.

## Live evidence, and why it is not the basis

The FOMC gate (`fomc-gate/1`) recorded, after 25 bp of overlay costs:

- September 2026: −$770.49 (contaminated by a late intraday fill).
- October 2026 through 10-27: −$1,403.15; the restoration is still open.

The gate is waiting at 1 of 6 meetings and has no new cycles to score after
the retirement. Those numbers are consistent with the longer record but a
two-meeting sample could not decide anything.

## The change

`backend/agents/trading/desk/event_risk.py`:

- `VERSION = "fomc-hold-through-meeting/1"`, `ENABLED = False`,
  `RETIRED_ON = 2026-10-28`, with the reason stored in `RETIREMENT_REASON`.
- `live_path(panel)` returns full exposure on every session. No new cycle
  can start: `event_execution.plan` and `policy_book.simulate` only start a
  cycle when the factor equals `REDUCED` (0.5).
- `decision(panel)` still reports the calendar, the sessions to the next
  decision, SPY's five-session return and the retired parameters, so the
  dashboard can show what the rule would have seen. `factor` is 1.0 when
  the calendar is known.
- `exposure_path` and `evaluation_slices` remain for research and for the
  arithmetic of a cycle that was already open. `live_path` no longer calls
  `exposure_path`.
- `calendar_blocks(event_policy)` is false for a retired policy, so an
  unavailable FOMC calendar no longer pauses ordinary planning. `nightly_plan`,
  `event_status`, `decision_view`, `holdings` and `learned_personal_guidance`
  use it; an enabled policy and pre-retirement records (no `enabled` flag)
  keep the old pause.

A cycle that was already open still completes. The 2026-10-28 cycle (cut
filled at the 10-23 open) restores at 15:45 ET on 2026-10-28 under the
existing `decision_close` timing; `event_execution.plan` and
`nightly_plan.event_plan_required` both keep an open `state.event_cycle` on
the event path until the restoration fills.

The dashboard section is now visible when the policy is enabled **or** an
event cycle is active, labels itself "retired policy" after retirement, and
states that no reduction is requested. Without that, retiring the cut would
have hidden the open October restoration from the operator.

## Release consequence

Five bound sources change: `event_risk.py`, `nightly_plan.py`,
`backend/api/v1/market.py`, `decision_view.py` and
`learned_personal_guidance.py` are in
`learned_live_holding.source_identity()`. Changing them invalidates the
installed 44-file release, so the retirement is not live until a new
release is approved and installed through the release ceremony
(`install_leader_release.py`, then `scripts/deploy.sh`). Until then the
installed nightly still runs `fomc-3-session-weakness/2`. The 2026-10-28
15:45 restoration must be allowed to run before any deploy.

## What this does not claim

Retiring the cut does not add a timing edge; it removes a negative one. The
post-June selloff-then-rebound pattern is not established as a rule, and no
new entry or exit timing is proposed here. The decision-day close
restoration remains the one piece with a measured post-June benefit.
