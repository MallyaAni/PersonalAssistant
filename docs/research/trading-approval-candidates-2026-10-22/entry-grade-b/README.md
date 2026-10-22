# Candidate: draw the leader-weight slots at B or better

Status: IMPLEMENTED on branch `entry-grade-b` (ee301307), tested, NOT
merged, NOT installed. The proposed release files beside this README
carry the branch's identity and `install_leader_release.py --dry-run`
accepts them. The first plan it can affect is the 19:30 ET nightly after
it is installed, so it is installed after the 2026-10-22 close, not
before the open: the orders queued at the broker for that open were
sized under the A cut, and the board must keep describing them.

Install sequence (after 16:00 ET): merge the branch to main, push, run
`install_leader_release.py` with `--revision <merge commit>` from
`~/dspark-commit`, deploy from `~/deploy/anios`, confirm ADMITTED
host==container, then `publish_now.py` is NOT needed (the 19:30 nightly
publishes under the new boundary). Regenerate the chart replay afterwards
with `market_policy_replay_research.py --arm leader_ewma_minB` once that
arm is mapped in `INSTALLED_ARMS` (one-line change: the replay must show
the B-cut rule, not the A-cut one).

## The change

`grade-led-leader-weight/1` admits a name at A or A+ and exits it when the
grade slips below A (`joint_funded_policy._required_stocks`: `grade >= 2`;
`minimum_held_grade = 2`). The candidate admits at B or better and holds
while at least B. Sizing, tilt, EWMA volatility target, cap and open fills
are unchanged.

## The evidence

Point-in-time scorecard, 20 offsets, 25 bp, `~/dsv41/pit/pit_leader_ewma_minB_20261021.json`:

| | CAGR | worst DD | Sharpe | > QQQ | > EW |
|---|---|---|---|---|---|
| installed (A cut) | 22.0% | −34.2% | 0.99 | 20/20 | 0/20 |
| B cut | 26.0% | −34.3% | 1.11 | 20/20 | 18/20 |
| installed, 2016–2023 | 23.6% | −34.2% | 1.03 | | |
| B cut, 2016–2023 | 25.0% | −34.3% | 1.07 | | |
| installed, 2024–2026 | 26.4% | −30.5% | 1.07 | | |
| B cut, 2024–2026 | 39.9% | −26.4% | 1.37 | | |
| A+ only | 19.0% | −33.8% | 1.01 | 10/20 | 0/20 |

Four points of CAGR for a tenth of a point of drawdown, better in both
windows, and the owner's criterion (more gain for no more drawdown) is
met outright. The grade-quality read (`docs/research/grade-quality-2026-10-22.md`)
explains it: at 60 sessions B names earn +3.8% over QQQ against A's
+2.8% (A+ +5.7%), so the A cut keeps the weakest upper grade and drops a
better one. Neighbours of the B cut (target 0.20, cap 0.20, tilt 0.25)
are in `arms_grade2.log` / `arms_summary.py`.

## The scope (why this is not a one-line change)

The A boundary is written into: `joint_funded_policy._required_stocks`
and `minimum_held_grade`; `grade_led_policy.grade_signals` (action and
the reason strings "A/A+ entry permission" / "Below A; exit");
`strategy_publication.validate` (a positive weight must carry A or A+);
`learned_live_holding` and the joint policy's mandatory grade exit
("Grade below A; exit"); `decision_view`, `current_opportunities`,
`learned_personal_guidance`, `holdings` (entry_permitted / sell wording);
the frontend `publicationValid` and the pre-market plan branch in
`SignalBoard.tsx`; the e2e fixtures that assert the A wording. The
clean form is an `entry_grade` on the policy class, carried into the
publication so every reader checks against the policy's own boundary
rather than a letter. Bound sources change, so this is a release:
candidate patch, identity, install after the close, deploy, republish.
The contract document `grade-led-leader-weight-contract-2026-10-21.md`
(bound) is rewritten in the same release, which also lets it stop
describing the probability timing the open-fill release retired.

## Not adopted tonight (scored, lost)

Trade bands 1%/2%, QQQ-trend exposure cuts, trailing stops 15%/25%, hold
through B after an A entry, pre-earnings entry guard: none beat the
installed rule (`docs/research/leader-policy-signal-audit-2026-10-21.md`).
