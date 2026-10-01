# Sector-aware sells S2: don't sell a downgraded name into its own peer group's rally. Pre-registration (2026-10-01)

**Status: registered before any code or fill is read.** Batch S2 of
[the scenario catalogue](trading-scenarios-2026-09-30.md), a new row
beside B2/B3 (the exit on the day the sell fills).

## The question

On the night of 2026-09-30 the desk graded COHR B. The paper account sold
14 shares at about $298.63 at 10:00 ET on 2026-10-01, on the board's sell
rule (a 15-minute bar closing 1% over the open). The whole
optical-networking group then rallied: COHR +10.3% open to close, AAOI
+7.5%, CIEN +7.1%, LITE +6.6% (the operator's figures). The desk grades
each name alone and has no notion of a peer group, so it sold a name into
a rally its own group was having that morning.

Is a sell rule that reads the name's peer group a better fill than the
board's rule? The peer group is computed from prices, point in time,
never from a sector label typed into code.

## What is known before this note (disclosed, cited, not repeated)

- **Stage 4, the sells section** (`stage4-results-2026-09-29.md`):
  holding a sell up to five sessions for a one-sigma bounce paid +1.6 bp
  a session on 2018-2023, positive at all 20 offsets. Nearly all of it
  came from names downgraded to B (+1.69 bp a session, +95.8 bp a
  re-timed order, t 3.11). A third of it was drift (+1.07 drift-adjusted,
  t 1.33), and it lost 2.2-3.0 bp a session on 2024-2026. RECORD. So a
  deferral of a downgrade sell is known to carry the drift and the
  B-bounce of 2018-2023, and to have lost since; the rules below are
  judged on 2024-2026 as well as the model window for that reason.
- **Universe expansion** (`universe-expansion-results-2026-09-30.md` on
  `research/universe-expansion`): ranking within the S&P 500's eleven
  sector cohorts lost 13-28 CAGR points against the book. That was a
  *selection* change; this study changes only the fill of sells the
  executor already makes, and uses no sector labels.
- **Structure rules S1f** (`structure-rules-results-2026-09-30.md` on
  `research/structure-rules`): a sell at the 21-EMA / 20-day-high level
  lost (−0.11 bp a session, negative at all 20 offsets, −21.7 bp a
  re-timed sell). It was the first study to price the book's sells
  against the board's sell rule; this one reuses its sell-side harness.
- **Nothing has measured a peer-group reading on this book.** The
  2026-10-01 COHR sell is one observation and is reported as a case, not
  used as a criterion.
- **The arithmetic, stated before the run.** On the model window the
  executor makes about 0.25 sells a session at about 6% of equity (stage
  4: 375 sells over 1,512 sessions). If a rule re-times 40 of them, the
  +2 bp-a-session floor needs about 1,300 bp a re-timed sell. The floor is
  therefore out of reach at any plausible firing rate. The reading that
  can say something is the per re-timed order one ("real but immaterial":
  25 bp at a clustered t of 3), which leaves the board unchanged.

## Definitions (fixed now)

All prices are on the panel's adjusted basis. A cube price is moved onto
it by `stage4_labels.cube_scale`, never by `adj_close / close`.

- **Returns.** r_i(s) = ln(adjC_i(s) / adjC_i(s−1)), the daily log return
  of name i. The market return r_m(s) is the same for the panel's
  benchmark (SPY).
- **Window.** W(t) = the 60 sessions t−59..t, so the returns use closes
  t−60..t, all on or before t. Nothing after t enters t's peer group.
- **Residual return.** e_i(s) = r_i(s) − a_i − b_i r_m(s) for s in W(t),
  where a_i and b_i are the OLS intercept and slope of r_i on r_m over
  W(t), refitted at every t.
- **Eligible at t.** A name other than the benchmark with all 60 returns
  in W(t) finite and a non-zero residual variance. A *peer* must also be
  a point-in-time member of the book at t (the membership history the
  point-in-time scorecard reads). The name being judged needs only its
  own window.
- **Correlation.** ρ_ij(t) = the Pearson correlation of e_i and e_j over
  W(t).
- **Peer group P_i(t).** The k = **5** eligible names j ≠ i with the
  largest ρ_ij(t), ties broken by panel column. With fewer than 5
  eligible peers, or without a finite SPY window, the name has no peer
  group at t and no rule fires.
- **Peer-group daily return.** g_i(s) = the equal-weight mean of r_p(s)
  over p in P_i(t), for s in t−19..t. **σ_g(t)** = its standard
  deviation (ddof 1) over those 20 sessions.
- **The peer group's morning.** R_g(t) = the equal-weight mean, over the
  peers p with a complete cube session at t+1, of
  ln(first-bar close_p(t+1) / adjC_p(t)). The first bar is 09:30-09:45
  ET. R_g covers the overnight gap and the first fifteen minutes. With
  fewer than **3** of the 5 peers priced, R_g is undefined and no rule
  fires.
- **Downgrade sells.** `stage4_orders` details `rotation_exit` and
  `reset_exit`: sells of a name graded below A at t. **Trims** are sells
  of a name still A/A+. Event (FOMC) sells are out of every scope.

The parameters k = 5, the 60-session window, the 20-session σ_g, the
3-of-5 floor and the 1% of G2 are fixed here and not searched.

## The candidates

These are sell fill rules in session t+1, on stage 4's machinery. The
orders are the executor's own (`stage4_orders`, `ew-redeploy` under
`graded-equal-weight/5`, executed basis, 20 start offsets, statistics at
the median offset). Each rule is priced against the control, the board's
sell rule as written: the first 15-minute bar of t+1 closing at or above
open × 1.01, else the official close (`dip_or_close`, sell side, as S1f
priced it). Each rule decides at the close of t+1's first bar, when the
name's and the peers' first bars are known together. A sell outside a
rule's scope, or where the rule does not fire, fills as the control to
the bit.

- **G1, peer rally: defer (downgrade sells).** When R_g(t) > σ_g(t), the
  sell is not sent in t+1. It is re-planned for t+2 and filled there by
  the control rule, as S1b deferred buys and as the desk's retry leg does.
  Its wait is one session, and its drift-adjusted gain is stage 4's
  g − μ·1 for a sell (waiting holds the stock). It is unpriced when t+2
  is not a complete cube session.
- **G2, peer rally: market-on-close (downgrade sells).** When R_g(t) >
  ln(1.01), meaning the peer group is up more than the name's own 1%
  threshold by its first bar, the sell skips the 1%-pop trigger and
  fills at the official close of t+1. It does not wait past t+1.
- **G3, peer rally: defer (trims and exits to C).** G1's rule and
  trigger, applied only to sells whose grade at t is not B: trims (A/A+)
  and exits of names graded C. Grade-B exits are left to the control. B
  is excluded because stage 4 found the bounce after a B downgrade
  regime-dependent (paid until 2023, lost after), so G3 asks whether
  the peer reading pays where that known effect is absent.

Three candidates. Reported beside them, deciding nothing:

- how often each fires, on the in-scope sells and on every name-day with
  a peer group;
- the reading by grade and by detail;
- the next-bar fills;
- every 2026 sell a rule changed at the median offset;
- the 2026-10-01 COHR case (decision 2026-09-30), whether or not the
  simulated book held COHR that night;
- the peer groups computed for COHR, AAOI, NVDA and OKLO on 2026-09-30,
  with their correlations and σ_g;
- the mean peer correlation, and the turnover of the peer groups
  (the share of P_i(t−1) still in P_i(t)).

A sanity reading, stated now: if correlation means anything, COHR's peers
on 2026-09-30 should be optical and AI-networking names. If they are not,
the write-up says so. That is a reading, not a criterion.

## Criteria, fixed now

The vocabulary and thresholds are structure-rules' S1a-S1f.

A rule **REPLACES** the board's sell rule for its scope if, at the median
offset:

1. the model-window (2018-01-02..2023-12-29) mean gain over the control
   is at least **+2.0 bp of equity a session** with a Newey-West t (lag
   20) **≥ 2.0**;
2. the next-bar run (bar fills at the following bar's open) holds the
   same floor;
3. 2024-2026 is **not negative**;
4. the deflated Sharpe at N = 3 is **≥ 0.95** (the cumulative count is
   reported beside it);
5. the drift-adjusted mean (G1 and G3 wait one session; for G2 this reads
   as criterion 1) is **≥ +1.0 bp at t ≥ 2**;
6. it is **positive at 15 of 20 offsets**.

**Real but immaterial** (stage 4's definition): criterion 1 fails, but
the per re-timed order mean is ≥ 25 bp with a date-clustered t ≥ 3. It is
reported, the board is unchanged, and the rule is kept as an option for
the manual book. Anything else is **RECORD**.

A REPLACES does not change the live sell leg by itself. A live change
needs its own registration and the operator's go-ahead.

## Trials and prior

Three registered: cumulative **482 → 485** (tone-expiry registered
480 → 482, the newest plan on any research branch at registration).

Priors:

- G1: 10% on any criterion pass beyond 3 and 6, and 15% real but
  immaterial;
- G2: 10% and 10%;
- G3: 5% and 5%.

The likely finding is RECORD for all three on the floor, by the
arithmetic above. The sign of the per-order reading is the open
question: industry momentum at the daily horizon argues for G1, and
stage 4's 2024-2026 sells (the names kept falling) argue against.

## Order of work

1. This note is committed alone, before any code. It reaches GitHub
   with the build, through spark1, and its commit precedes the build's.
2. The build, with tests:
   - the peer groups, point in time (a test that tampering with prices
     after t leaves t's peer group unchanged);
   - the two rules on synthetic bars, and the deferral path;
   - the null case (a rule that never fires reproduces the control bit
     for bit);
   - the CLI, the payload and the verdicts, and an independent check
     script that recomputes the verdict figures from the payload's rows
     and the peer groups from the store with its own code.
3. A run script for spark1 (CPU, nice 19, outside 09:00-16:15 ET and
   never beside the nightly or a deploy): the null test first, then the
   study at 20 offsets, the check, and a local commit of the outputs.
   Not run on the night of registration. spark1's CPU is committed to
   studies already registered.

## Not in scope

- The decision to sell (the grade, the downgrade, the trim) is untouched.
- Buys are untouched.
- Peer groups do not enter the grade.
- A deferred sell is re-filled at t+2 by the control. The live desk would
  re-plan it at t+1's close, and a name regraded A that night would not
  be sold at all. The study does not model that re-plan, as S1b did not
  for buys.
