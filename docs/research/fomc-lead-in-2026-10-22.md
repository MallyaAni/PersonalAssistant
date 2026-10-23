# Do the weeks before an FOMC decision sell off? — 2026-10-22

The owner's observation ("the weeks leading up to FOMC sell off hard, like
this week and last") measured on every scheduled decision in the store,
2015-01 to 2026-09 (93 decisions; the unscheduled March 2020 actions left
out). Script: `~/dsv41/universe/fomc_window.py`. "Book EW" is today's 94
book names equal-weighted (a hindsight universe; read it as the theme).

## Ten years

| | 5 sessions before: mean / median / % down | any 5 sessions: mean / % down | decision day | 5 sessions after |
|---|---|---|---|---|
| SPY | +0.50% / +0.59% / 31% | +0.28% / 39% | +0.06% | +0.07% |
| QQQ | +0.54% / +1.03% / 39% | +0.38% / 40% | +0.20% | +0.23% |
| book EW | +0.75% / +1.21% / 29% | +0.66% / 38% | +0.45% | +0.50% |

The lead-in has been *better* than an ordinary week, not worse, and down
less often. The only year it was clearly negative is 2022 (the hiking
year: SPY −1.6%, QQQ −2.4% over the five sessions before). Halving the
book from five sessions before each decision through the decision, with
25 bp on each leg, cost about five points a year on SPY, QQQ and the book
over 2015–2026 (QQQ 18.6% → 13.2%; book EW 34.0% → 25.9%).

## Since June 2026

The guidance change under the new chair (the September study's context)
coincides with a different pattern. Five / ten sessions before, book EW:

| decision | 5 before | 10 before | day | 5 after |
|---|---|---|---|---|
| 2026-06-17 | +3.1% | −6.6% | −0.5% | −0.8% |
| 2026-07-29 | −6.6% | −7.5% | −3.8% | +14.1% |
| 2026-09-16 | −4.0% | −2.1% | +0.7% | +6.8% |
| 2026-10-28 (pending, at t−4) | −5.6% (last 5) | −11.5% (last 10) | | |

Three of the four lead-ins since June were hard selloffs and the two
completed ones bounced hard after the decision. Four meetings is an
anecdote, not evidence: in 2025 the same lead-ins were up in seven of
eight meetings.

## Decision (owner deferred: "up to you")

The paper account's FOMC rule (`fomc-3-session-weakness/2`, cut to 50%
three sessions before when SPY's five-session return is negative, restore
at the open after the decision) stays on for the 2026-10-28 meeting. It is
the only rule that speaks to the post-June regime, the cut is already
queued for the 2026-10-23 open, and the cost of one cycle is small. It is
on trial with a stated end: if its cumulative effect after costs (the
nightly's "FOMC gate" line, −770 after one meeting) is still negative after
the December meeting, it is switched off, since the ten-year record says
the lead-in is not a selloff on average.

Note the restoration is what matters most in this regime: the two
completed cycles since June rose 7–14% in the five sessions after the
decision, so a cut that restores late would be the expensive part.

The dashboard's "allocation check failed" banner on FOMC nights was a
false alarm: the check expected the ordinary nightly's allocation receipt,
which the nightly does not write when the FOMC rule owns the plan. Fixed in
`grade_parity._compare_targets` (grades are still checked; targets are
reported as not compared, with the reason), only when the record's own
`event_risk` block names that session.
