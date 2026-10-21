# Grade direction with leader-tilted equal weight

The owner asked for the sizing arm with the most gain for the least added
drawdown on the point-in-time book, and the scorecard of 2026-10-21
(`docs/research/sizing-timing-validation-2026-10-21.md`, last two sections)
named it: equal weight across every A/A+ name, tilted by trailing-return rank,
scaled to a realised-volatility target, never levered. This is a behavioral
contract for installing that sizing beside the existing grade rules, not a
claim of higher returns.

Candidate policy `grade-led-leader-weight/1` (`backend/market/grade_led_leader_policy.py`)
keeps every rule of the installed `grade-led-learned-sizing/1`: A/A+ permits
entry; a held stock below A exits; a missing grade protects the holding at its
current size through the same retained-capital partition; an eligible unheld
stock remains a BUY signal when funding, whole-share rounding or execution
timing blocks an order; preserved holdings cannot finance purchases; the
existing account, cash, cost, per-name cap and whole-share guards remain
mandatory; ordinary orders keep the installed probability timing and company
exits go at the open. Grade signals, receipts and certificates keep their
fields, and the installed model-only policies and their histories are untouched.

What changes is only the size of each eligible name, computed on each decision
session from the completed report and nothing after it:

1. Eligible = every name graded A or A+ that is not buy-blocked, plus every
   held name graded A or A+ (a held blocked name is kept but may not grow).
2. Each eligible name starts with an equal slot. The slots are tilted by the
   name's trailing 63-session return rank among the eligible names, linearly
   from 0.5x for the weakest to 1.5x for the strongest (strength 0.5), and
   renormalised so the slots sum to one unit of capital.
3. The whole book is scaled by min(1, 0.25 / realised), where realised is the
   sample standard deviation (ddof 1) of the equal-weight basket's last 63
   daily log returns of adjusted close, annualised by sqrt(252). The book is
   never levered; the remainder is cash.
4. Each name is then capped at the existing per-name limit (`growth.CAP`, 25%).

`leader_weights(closes, sized)` is the one pure function that does this, and
`size_report` applies it to a report; the funded policy's sizing step and the
account-free unit-capital publication (`strategy_model_allocation`) both call
it, so the published percentages and the funded plan come from the same
arithmetic. The tilt is `point_in_time.TILTS["leader"]`, the research function
the scorecard arm `ew_graded_leader_25` used. A name without a full finite
63-session window is not sized: unheld it is excluded with reason
`trailing_window_unavailable`; held, the night's sizing is refused as
`leader_window_unavailable` and only grade exits are planned.

What the policy does not do: it does not read the learned scenario
distribution or run the growth optimiser, and its receipt says so
(`target_basis` and `reason` are `grade_led_leader_weight`, `leader_sizing`
carries the window, multipliers, realised volatility and scale, and there is no
`optimizer` or `scenario` claim). It does not fit anything: 63, 0.5, 0.25 and
the 25% cap are the scorecard's settings, taken as they were scored. It does
not change the timing heads, the broker admission, the event policy or the
settlement rules. The 25% cap was not part of the scorecard arm (which ran
uncapped); with the book's usual count of A/A+ names a 1.5x slot stays under
it, and the cap is the installed hold limit rather than a new parameter.

Evidence it rests on: the point-in-time scorecard of 2026-10-21 (CAGR 24.3%
at worst drawdown -35.9% across 20 offsets against the installed rule's 16.5%
at -34.0%, ahead of plain equal weight in 20 of 20 offsets in 2024-26). Three
settings of one parameter are not a fit, but a scorecard is not forward
evidence either. No performance claim follows from implementing this contract.

Acceptance it needs: the owner's review and release approval under the paper
lock (the admission CLI refuses a policy change by design, so the proposed
`config.json`, `release.json` and `evidence.json` are installed by hand as on
2026-10-13), then a fresh ordinary nightly and the following real session on
the paper account. Private fixtures are not that acceptance, and the paper
account's forward record is the only out-of-sample evidence that counts.
