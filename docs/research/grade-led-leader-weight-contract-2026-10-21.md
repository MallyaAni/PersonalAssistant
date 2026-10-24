# Grade direction with leader-tilted equal weight

The owner asked for the sizing arm with the most gain for the least added
drawdown on the point-in-time book, and the scorecard of 2026-10-21
(`docs/research/sizing-timing-validation-2026-10-21.md`, last two sections)
named it: equal weight across every eligible name, tilted by trailing-return
rank, scaled to a volatility target, never levered. This is a behavioral
contract for installing that sizing beside the existing grade rules, not a
claim of higher returns. Five revisions since the first install are recorded
at the end: open fills for every leg, an EWMA volatility estimate, the entry
boundary at B, an exposure floor, and the entry at A held while B with a 1%
minimum trade.

Candidate policy `grade-led-leader-weight/1` (`backend/market/grade_led_leader_policy.py`)
keeps every rule of the installed `grade-led-learned-sizing/1` except where
this document says otherwise: a grade at or above the policy's entry grade
permits entry; a held stock below it exits; a missing grade protects the
holding at its current size through the same retained-capital partition; an
eligible unheld stock remains a BUY signal when funding, whole-share rounding
or execution timing blocks an order; preserved holdings cannot finance
purchases; the existing account, cash, cost, per-name cap and whole-share
guards remain mandatory; every leg, ordinary or company exit, goes at the next
open (revision 1 below). Grade signals, receipts and certificates keep their
fields, and the installed model-only policies and their histories are untouched.

What changes is only the size of each eligible name, computed on each decision
session from the completed report and nothing after it:

1. Eligible = every name graded at or above the entry grade that is not
   buy-blocked, plus every held name graded at or above the hold grade (a
   held blocked name is kept but may not grow). The entry grade is A and the
   hold grade B (`ENTRY_GRADE = 2`, `HOLD_GRADE = 1` on the policy class;
   revision 5 below); revision 3 drew both at B.
2. Each eligible name starts with an equal slot. The slots are tilted by the
   name's trailing 63-session return rank among the eligible names, linearly
   from 0.5x for the weakest to 1.5x for the strongest (strength 0.5), and
   renormalised so the slots sum to one unit of capital.
3. The whole book is scaled by min(1, 0.25 / forecast), where forecast is the
   exponentially weighted (span 20) standard deviation of the equal-weight
   basket's last 63 daily log returns of adjusted close, annualised by
   sqrt(252) (`forecast_volatility`; revision 2 below, the first install used
   the plain sample standard deviation). The book is never levered; the
   remainder is cash.
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

## Revisions

1. Open fills (f6bec580, released 2026-10-21 16:46 ET). `plan()` routes every
   leg `execution_timing="next_open"`; the nightly submits market-on-open
   orders and the learned fifteen-minute timing is not consulted. Basis: the
   execution-timing study of 2026-09-27 found no fill convention that beat
   the next open, and the live timing never filled on its own judgement.
2. EWMA volatility (e22e9a25, released 2026-10-21 19:55 ET). The target is
   measured against an EWMA-20 estimate of the basket's variance: on the
   scorecard worst drawdown -34.2% against -35.1% and Sharpe 1.03 against
   0.97 for the trailing estimate; a walk-forward ridge forecast did worse.
3. Entry grade B. A name is admitted at B or better and held while it keeps
   at least B (`entry_grade = minimum_held_grade = 1`; exits are labelled
   "Grade below B"). Basis: the point-in-time scorecard
   (`leader_ewma_minB`, 20 offsets, 25 bp): 26.0% a year at worst drawdown
   -34.3% against 22.0% at -34.2% for the A cut, ahead in both windows
   (2016-23 25.0% against 23.6%; 2024-26 39.9% at -26.4% against 26.4% at
   -30.5%), ahead of QQQ in 20 of 20 offsets and of plain equal weight in 18.
   The grade read behind it (`docs/research/grade-quality-2026-10-22.md`):
   over the next sixty sessions B names earned +3.8% over QQQ against A's
   +2.8% and A+'s +5.7%, so the A cut kept the weakest upper grade and left
   a better one out. The publication contract admits a positive weight at
   any letter the policy's entry grade allows, and every reader of grade
   signals asks the policy class for that boundary rather than assuming A.
4. Exposure floor 0.5. The volatility target scales the book down but never
   below half its full exposure (`EXPOSURE_FLOOR`; the certificate carries
   `exposure_floor`). Basis: the rule held a sixth of its book through 2020
   and made -6% in a year the equal-weight A/A+ book made +37%, the spike
   having cut the exposure first and kept it cut through the rebound. On
   the scorecard (B cut, 25 bp, 20 offsets) the floor earned 26.7% a year
   at worst drawdown -34.1% and Sharpe 1.12 against 26.0%, -34.3% and 1.11
   (2020 +16.6% against +7.4%); 0.65 bought drawdown (-36.0%), 0.35 changed
   nothing. Research: `~/dsv41/universe/floor_arm.py`, payloads under
   `data/market/research/universe-hindsight/floor_scores.json`.
5. Entry at A, hold while B, 1% minimum trade (supersedes the entry of
   revision 3). A name is admitted at A or better and held while it keeps
   at least B (`entry_grade = 2`, `minimum_held_grade = 1`; exits are still
   labelled "Grade below B"), and a resize smaller than 1% of equity is not
   traded (`min_trade = 0.01`, passed to the funded planner, which never
   suppresses a full exit). Basis: the account-faithful simulator
   (`backend/market/policy_book.py`, the same engine that draws the strategy
   charts): the nightly's own grades (the current fundamentals mode; the
   scorecard behind revision 3 graded with the research mode, which puts
   8,264 name-sessions on the other side of the B line), market-on-open
   fills from the cash on hand before the day's sells, whole shares, 10 bp,
   the band buy block and the FOMC cycle. Admitting and holding at B earned
   34.0% a year at worst drawdown -29.5%, Sharpe 1.39, 82,446 fills; this
   rule 39.4% at -26.9%, Sharpe 1.51, 6,703 fills; ahead in the window it was
   chosen on (2015-2022: 25.0% against 19.8%) and in the one it was not
   (2023-2026: 74.4% against 68.5%), in 7 of 11 calendar years, and at 25 bp
   (37.6% against 29.9%). The minimum trade alone is worth little return
   (+0.1 to +0.9 points between 0.25% and 2%) but cuts the daily resize
   churn; holding grace sessions, dropping the band block and the entry at
   A+ did not lead in both windows. `docs/research/account-simulator-rule-2026-10-24.md`.
5. Entry at A, hold while B, 1% minimum trade (supersedes the entry of
   revision 3). A name is admitted at A or better and held while it keeps
   at least B (`entry_grade = 2`, `minimum_held_grade = 1`; exits are still
   labelled "Grade below B"), and a resize smaller than 1% of equity is not
   traded (`min_trade = 0.01`, passed to the funded planner, which never
   suppresses a full exit). Basis: the account-faithful simulator
   (`backend/market/policy_book.py`, the same engine that draws the strategy
   charts): the nightly's own grades (the current fundamentals mode; the
   scorecard behind revision 3 graded with the research mode, which puts
   8,264 name-sessions on the other side of the B line), market-on-open
   fills from the cash on hand before the day's sells, whole shares, 10 bp,
   the band buy block and the FOMC cycle. Admitting and holding at B earned
   34.0% a year at worst drawdown -29.5%, Sharpe 1.39, 82,446 fills; this
   rule 39.4% at -26.9%, Sharpe 1.51, 6,703 fills; ahead in the window it was
   chosen on (2015-2022: 25.0% against 19.8%) and in the one it was not
   (2023-2026: 74.4% against 68.5%), in 7 of 11 calendar years, and at 25 bp
   (37.6% against 29.9%). The minimum trade alone is worth little return
   (+0.1 to +0.9 points between 0.25% and 2%) but cuts the daily resize
   churn; holding grace sessions, dropping the band block and the entry at
   A+ did not lead in both windows. `docs/research/account-simulator-rule-2026-10-24.md`.
6. P/E-history sizing tilt and split-corrected valuation history. Each sized
   name's leader slot is multiplied by 1 + 0.5 (1 - 2h), h the percentile of
   its price/earnings within its own trailing 756 sessions (the valuation
   analyst's `price_earnings` evidence; at least 250 readings; missing leaves
   the slot unchanged), before the slots are normalised (`PE_HISTORY_TILT`,
   `report_pe_tilt`; the certificate carries the multipliers). The same
   change corrects `levels_pit.split_adjusted_shares`, which put market caps a
   split factor too low before each later split and so graded later winners
   cheap in advance; the figures of revision 5 restated on corrected grades
   are 34.8% a year at -27.7% (to 2022 19.1%, after 73.8%) against 31.4% for
   entering and holding at B. With the tilt: 37.4% at -27.1%, Sharpe 1.45, to
   2022 21.2%, after 77.4%, at 25 bp 35.2%. `docs/research/pe-history-tilt-2026-10-24.md`.
