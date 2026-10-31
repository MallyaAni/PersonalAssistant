# Position sizing: is it good, and what stays frozen — 2026-10-30

Status: research note and program decision. **No live rule change.** The
installed rule stays `grade-led-leader-weight/1` for the forward window.
This note answers the owner's sizing question with measured evidence, records
the P4 risk-dial decision as deferred to the 252-session review, and records
that no new strategy is started.

## What the sizing does

`backend/market/grade_led_leader_policy.py` sizes the book in one pass from
the report's trailing closes:

1. every name graded A or better takes an equal slot, tilted by its
   trailing 63-session return rank (`strength 0.5`, multipliers roughly
   0.5-1.5);
2. each slot is multiplied by the P/E-history tilt
   `1 + 0.5 * (1 - 2h)`, where `h` is the name's price/earnings rank in its
   own trailing three years (multipliers roughly 0.5-1.5);
3. the book is scaled to a 0.25 realised-volatility target, using an
   EWMA-20 estimate of the equal-weight basket's daily variance annualised
   by 252, but never below a 0.5 exposure floor;
4. each name is capped at 25% of equity; the remainder is cash; the book is
   never levered;
5. resizes under 1% of equity are not traded; exits always trade.

The calculation reads only the trailing window ending on the decision
session. The receipt records `optimizer_ran: false`.

## The evidence that it works

The account-faithful simulator (`policy_book.simulate`: the nightly's
grades, fills at the next open from cash on hand, whole shares, 10 bp, the
FOMC cycle) is the scorecard. On split-corrected grades, tuned 2015-2022 and
checked 2023-2026:

| arm | CAGR | worst DD | Sharpe | source |
|---|---:|---:|---:|---|
| installed leader sizing, A entry / B hold | 34.9% | −28.3% | 1.38 | code comment; `account-simulator-rule-2026-10-24.md` |
| same, plus P/E-history tilt | 37.6% | −27.7% | 1.46 | `pe-history-tilt-2026-10-24.md` |
| B entry / B hold (no A cut) | 31.5% | −30.0% | 1.31 | same |
| equal weight, no costs, IT+Comm PIT | 19.9% | −34.4% | 0.93 | `trading-program-2026-10-28.md` |

The individual choices each paid for themselves in the same simulator:
the 0.5 exposure floor earned 26.7% a year at −34.1% and Sharpe 1.12
against 26.0%, −34.3% and 1.11 without it, and made 2020 +16.6% against
+7.4%; EWMA-20 beat trailing standard deviation (−34.2% against −35.1%,
Sharpe 1.03 against 0.97) while a ridge forecast did worse (−39.8%); the
leader tilt added 2.3 CAGR points at the same drawdown, with strength 1.0
jumping the drawdown to −42%; the 1% minimum trade cut about 81,000 fills
to 7,000 with no return cost.

The honest-universe caveat is the program's: the 37.6% headline is the
choice of names, not the rule. On the point-in-time S&P 500 the installed
rule earns 14.8% at −34.7% and Sharpe 0.90 (10 bp; 14.2%, −33.3%, 0.88 at
25 bp), about SPY plus one to three points with a better Sharpe and a
similar drawdown. Inside IT+Comm it roughly matches equal weight and trails
QQQ. That is the fair comparison, and the sizing is not claiming more.

## The forward record so far

The paper account started at 100,000 on 2026-09-04 and stood at 84,166.47
on 2026-10-30, −15.83%. The desk also shadows `graded-equal-weight/5`
(equal weight, every A/A+ name, fully invested, the measured reset
cadence) on its own dry-run ledger; it started at 100,000 on 2026-09-30 and
stood at 81,549.87, −18.45%. This is not the installed rule with only the
sizing changed - it is a different policy - so the comparison is
directional, not a controlled experiment. Over the 17 sessions both ran:

| line | installed sizing | equal-weight shadow |
|---|---:|---:|
| return, 2026-09-30 → 2026-10-30 | −16.02% | −18.45% |
| return, 2026-10-21 → 2026-10-30 (current sizing live) | −6.20% | −7.71% |
| annualised daily volatility | 56.2% | 70.1% |
| worst drawdown from peak | −21.36% | −22.20% |
| daily return correlation | 0.865 | — |

That is consistent with the brake doing its job in this tape: the installed
book lost about 2.4 points less than the equal-weight book over the overlap
and ran about 14 points less realised volatility, at a similar drawdown.
It is one path of 17 sessions and the policies differ in more than sizing,
so it is evidence, not proof.

## What the sizing is not

At the 2026-10-30 close the plan's realised basket volatility was 0.703,
so the scale sat on the 0.5 floor: 12 sized names, 50% gross, 49.97% cash.
The target is 0.25, but the floor deliberately overrides it; the book's
expected volatility at target weights is about 32%, not 25%. The floor is
the documented choice that avoided the 2020 mistake, but it means the
volatility target is a soft cap in exactly the regime where it matters.

Other measured weaknesses:

- **The estimator lags.** EWMA-20 is backward-looking; the brake engaged
  after most of this drawdown had already happened. A forward-looking ridge
  forecast did worse on the scorecard, so the naive forecaster is the one
  that earned its place, but the lag is the cost.
- **Risk is not equal per dollar.** At target weights the largest risk
  contributions are SMCI 13.8%, SNDK 13.7%, ALAB 10.5% and MU 9.8%; the
  smallest is NTAP 4.0%. INTC gets 3.4% of the capital but 7.6% of the
  risk; SNDK gets 9.7% of the capital and 13.7% of the risk. The 25% cap
  limits capital, not risk contribution.
- **The tilt is procyclical.** The leader tilt loads recent winners; in a
  reversal those names lead down. The P/E tilt partly offsets it. It is a
  return-seeking tilt, not a risk control.
- **One theme.** All 12 sized names are technology/semiconductor. The
  basket-vol estimate captures their correlation, but the floor still holds
  50% of a correlated book; there is no sector cap.

## Improvement candidates, not live changes

Each would need its own pre-registration, the honest point-in-time universe,
costs at 10 and 25 bp, a placebo, and a forward shadow before it could be
installed. None is a live change now.

1. **Risk-balanced slots.** Replace equal capital slots with inverse-vol or
   risk-parity slots so each name carries a similar share of risk. The
   measured dispersion above (4.0% to 13.8%) is the size of the problem.
2. **Sector or theme cap.** A cap on the aggregate weight in one theme would
   have cut this book's concentration; the closed sector-cap study failed on
   the broad universe, so this needs a new registration aimed at the
   thematic book, not a retry of the old one.
3. **A faster brake or a hard risk cap.** The ridge forecast failed; a
   shorter EWMA span or a hard portfolio-vol cap could be tested, but the
   floor interaction must be measured, not assumed.

## Decisions

- **P4 risk dial (item 3).** Keep the installed 0.25 target now. The
  measurement in `risk-dial-2026-10-28.md` says 0.25 is the knee on the
  thematic universe; 0.20 is the cautious setting (1.2 CAGR points for 4.7
  fewer drawdown points, best Sharpe 0.98); 80/20 theme/SPY is the efficient
  core-satellite first step (−2.2 drawdown points for −1.1 CAGR points).
  The owner's dial decision is deferred to the 252-session review; no live
  change is made now.
- **No new strategy (item 4).** No new selection or timing strategy is
  started. The installed rule and its forward record stay; P1 is the
  highest-priority workstream, and the rule cannot be judged if it changes
  every week.

## Caveats

- The forward comparison is 17 sessions, one path, and the live account
  changed policy on 2026-10-21. The shadow is a different policy (equal
  weight, fully invested), so the gap measures the whole book difference,
  not the sizing alone.
- The risk contributions are ex-post estimates from the last 63 sessions at
  target weights, not the realised contributions of the drifted book.
- The scorecard is tuned 2015-2022 and checked 2023-2026; the absolute
  levels are survivor-flattered on today's names. The rule-against-equal-
  weight comparison is the fair one.
