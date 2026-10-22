# Candidate: the volatility target never cuts the book below half

Status: IMPLEMENTED on branch `vol-floor`, tested, NOT merged, NOT
installed. The proposed release files beside this README carry the
branch's identity (two bound sources differ from the installed release:
`grade_led_leader_policy.py` and the contract doc, revision 4). Awaiting
the owner's word. The first plan it can affect is the nightly after it is
installed.

## The change

`grade_led_leader_policy.leader_weights` scales the book to the 0.25
volatility target with `scale = max(EXPOSURE_FLOOR, min(1, target /
realised))`, `EXPOSURE_FLOOR = 0.5`. The certificate carries
`exposure_floor`. Nothing else changes: entry grade B, tilt, EWMA-20,
cap 0.25, open fills.

## The evidence

Year by year the rule without a floor made −6% in 2020 (A cut; +7% with the
B cut) while the equal-weight A/A+ book made +37%: the March spike cut the
exposure to a sixth and the rebound ran without it. Point-in-time
scorecard, B cut, 25 bp, 20 offsets (`floor_scores.json`):

| | CAGR | worst DD | Sharpe | 2020 |
|---|---|---|---|---|
| installed (no floor) | 26.0% | −34.3% | 1.11 | +7.4% |
| **floor 0.5** | **26.7%** | −34.1% | **1.12** | +16.6% |
| floor 0.65 | 27.5% | −36.0% | 1.12 | +22.2% |
| floor 0.35 | 26.2% | −34.3% | 1.11 | +11.7% |

Every other year within a point of the installed rule. A floor of 0.5 is
the highest that did not buy drawdown.

## Install sequence

Merge `vol-floor` to main, push, `install_leader_release.py --revision
<merge commit>` from `~/dspark-commit` with the owner's authorization,
deploy from `~/deploy/anios`, ADMITTED host==container. Installing re-binds
the config, so the standing publication stops verifying until the next
nightly: install after the close, or run `publish_now.py` right after and
accept one session where the board's plan and the paper tab's saved
targets disagree (as on 2026-10-22).
