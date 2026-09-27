# The mid-cycle rule on the `/4` book: results (2026-09-27)

Pre-registration: [midcycle-ew-plan-2026-09-27.md](midcycle-ew-plan-2026-09-27.md)
(six variants; the addendum registers four more built after the first six
ran, counted as trials 7-10). Run on spark1 from `701ef87e` (first six)
and `c74d5bbe` (`--only ... --merge`); payload
`docs/research/scorecards/midcycle_ew.json`, 480 simulator runs. Everything
below is the live execution set with one mid-cycle keyword changed, 25 bp,
point-in-time book, 20 offsets.

## The finding the tables did not show: the book is 78% invested

The diagnostics were built to say where the cash is. Under the live
executor the graded equal-weight book - designed to be fully invested -
holds **22.3% cash on average on 2016-2023 and 32.4% on 2024-2026**. The
reset-only book (`mc-off`) holds 7.1% / 11.6%, and that 7% is itself a
leak of the reset: sells fill at the close and buys at the next open are
paid only from cash on hand, so on a fully invested book every reset's
buys go partly unpaid, and the single retry runs under the mid-cycle
entry's gates (band block, 15% name cap) and is then dropped. The other
15 points come from the mid-cycle rotation: 33 downgrade exits a year put
proceeds in cash that waits for a band breakout which mostly never comes
before the next reset (9.5 entries a year at 2.6% each).

## The table (25 bp; medians across 20 offsets; bp/d and t paired against `live`, Newey-West lag 20)

| variant | 2016-2023 CAGR | maxDD | invested | vs live bp/d (t) | above live | 2024-2026 CAGR | maxDD | invested | vs live bp/d (t) | above live |
|---|---|---|---|---|---|---|---|---|---|---|
| live (control) | 23.2% | -36.0% | 78% | — | — | 52.6% | -17.2% | 68% | — | — |
| mc-off (no mid-cycle) | 27.8% | -43.3% | 93% | +0.6 (+0.5) | 18/20 | 47.7% | -27.7% | 88% | -1.4 (-0.5) | 7/20 |
| mc-target-size | 23.3% | -37.8% | 80% | -0.4 (-1.3) | 5/20 | 55.3% | -16.8% | 70% | +0.6 (+0.6) | 18/20 |
| mc-no-idle-cash (sweep) | 25.3% | -36.9% | 82% | +0.2 (+0.7) | 20/20 | 56.4% | -17.7% | 72% | +0.6 (+0.8) | 18/20 |
| mc-new-grades-only | 23.5% | -41.4% | 88% | -0.2 (-0.2) | 12/20 | 54.7% | -21.0% | 80% | +1.1 (+0.5) | 14/20 |
| mc-exit-only | 23.0% | -35.8% | 76% | -0.1 (-0.4) | 3/20 | 52.7% | -17.6% | 66% | -0.7 (-1.4) | 11/20 |
| **mc-redeploy** (2% buffer) | 24.8% | -43.2% | 91% | -0.3 (-0.3) | 16/20 | **60.2%** | -21.2% | 84% | +4.0 (+1.7) | 18/20 |
| mc-redeploy-nobuffer | 24.7% | -43.8% | 92% | -0.3 (-0.3) | 17/20 | 61.0% | -21.3% | 85% | +4.0 (+1.6) | 18/20 |
| mc-redeploy-no-exits | 27.9% | -45.7% | 98% | +0.7 (+0.5) | 19/20 | 49.1% | -30.4% | 96% | +0.9 (+0.3) | 11/20 |
| reset-full-invest | 28.5% | -44.8% | 96% | +1.0 (+0.8) | 18/20 | 50.2% | -27.4% | 93% | -1.5 (-0.5) | 10/20 |

Full span 2016-2026: live 27.4% / -36.0%; mc-redeploy 30.0% / -43.2%;
reset-full-invest 30.6% / -44.8%; mc-off 29.6% / -43.3%.

**Registered verdict: every variant RECORD.** None clears +1.0 point with
paired t >= 2.0 and a drawdown within 3 points of live; the daily paired
t never exceeds 1.7 because these variants change *exposure*, and an
exposure difference is a noisy daily series. The pre-registered second
reading - offsets above live and the exposure-adjusted gain - says
CONSISTENT for `mc-off`, `mc-no-idle-cash`, `mc-redeploy-no-exits` and
`reset-full-invest` on the choosing window, and for `mc-redeploy` on both.

## Reading it

1. **The 4.3 points are exposure, not selection.** Scale live's CAGR to
   mc-off's invested fraction and the gap is +0.0 points. The live
   executor is not choosing worse names than the plain book; it is
   holding a fifth of the equity in cash by accident, and that cash is
   what bought the 7 points of drawdown in 2022. Every variant in this
   table sits on roughly the same exposure/return line.
2. **The downgrade exits are the one part of the mid-cycle rule that
   earns its place.** Keep exits and redeploy the cash (`mc-redeploy`)
   and the recent window goes from 52.6% to 60.2% with drawdown -21%;
   redeploy but drop the exits and it falls to 49.1% with drawdown -30%.
   The exit on a lost grade is worth about 10 points of drawdown and 5-11
   points of return on 2024-2026, and roughly nothing on 2016-2023. The
   *entries* (band breakouts at 2.6%) are worth nothing anywhere: every
   variant that changes how entries are sized or gated is within noise.
3. **So the design question is exposure, and it is the operator's.** The
   account today is a 78%-invested book with downgrade exits, and it got
   there by inheriting an executor built to size concentrated `/3`
   positions from cash. The alternatives measured here are:
   - keep it: 23.2% / 52.6% with -36% / -17% drawdowns;
   - `mc-redeploy`: cash above 2% goes back to targets at the next open,
     unconditionally: 24.8% / 60.2%, 30.0% over the span, with -43% / -21%
     drawdowns (the 2022 bear at 91% invested instead of 78%);
   - `reset-full-invest` (fix only the reset's leak, no mid-cycle buying):
     28.5% / 50.2%, -45% / -27%; the highest choosing-window number and
     the one that gives up the exits' recent-window benefit least
     cleanly.
   None of these is a statistical claim about a better signal. They are
   the same book at different exposure, and the one with the exits kept
   and the cash redeployed (`mc-redeploy`) is the version that matches
   what the policy says it is - fully invested in the graded names - while
   keeping the one mid-cycle rule that has evidence behind it.
4. **What would change the executor, and how.** If the operator chooses
   `mc-redeploy`, it is a registered change to the live path
   (`simulate.run(midcycle_redeploy=True)` has the exact semantics; the
   executor's planner needs the same leg in `paper.midcycle_orders`),
   built with tests, gated, and switched on after Monday's `/4` rebalance
   has fired and Tuesday's parity is green - not before. The shadow
   ledger keeps pricing the current executor beside it.
