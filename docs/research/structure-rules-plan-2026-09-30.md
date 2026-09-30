# Structure rules S1: resistance, the first bar's shape, the reference price, the market's dip, selling at the level, and the grade under a falling EMA. Pre-registration (2026-09-30)

**Status: registered before any code or fill is read.** This is batch S1
of [the scenario catalogue](trading-scenarios-2026-09-30.md).

## The question

On 2026-09-30 the board bought AAOI, COHR and SMCI on their first
15-minute bars because each closed 1% under the open. AAOI's bar had run
to 103.96 and been rejected under its 21-day EMA (104.4) for the third
session running; all three bars closed near their lows and the names kept
falling. The fill rule reads the open and the bar closes and nothing else;
the grade reads six-month momentum and the 60-day range and had AAOI at
A+. Six rules that read structure are registered here. Each is the
operator's reading of the tape written down as a rule, not a searched one.

## What is known before this note (disclosed)

- Stages 3-5 and the adaptive-entry study: every dumb variation of the
  fill rule (waiting, sigma-scaled dips, the decision close, a gap guard)
  is RECORD against `dip_or_close`; the rule fills about 3.4 bp a buy
  better than the next open and the dip is reached on 41% of buy sessions
  (`adaptive-entry-results-2026-09-30.md`).
- Stops: seven price-level stops on the `/4` book all lost
  (`catastrophe-stop-2026-09-27.md`); stage 4's learned exits lost.
- The technical analyst's rank IC and the stage-4 literature memo on
  structure (`stage4-lit-structure-2026-09-29.md`): moving-average
  crossovers and trend filters have thin, regime-dependent evidence on
  large caps; the memo's own reading was that they mostly help drawdown,
  not return.
- Nothing has measured a level-aware fill or a structure-aware grade on
  this book. The 09-30 fills are three observations and are reported as a
  case, not used as a criterion.

## Definitions (fixed now)

- **EMA21(t):** the 21-session exponential moving average of the adjusted
  close through session t (span 21, `adjust=False`). **Falling** if
  EMA21(t) < EMA21(t−5).
- **H20(t):** the highest daily high over sessions t−19..t.
- **Level L(t+1):** for a buy in session t+1, the nearer of EMA21(t) and
  H20(t) that lies above the close of t (if neither does, no level).
- **Tag:** the first completed 15-minute bar of t+1 has high ≥ L × 0.995
  while close(t) < L. **Rejected:** a tag whose bar close < L.
- **Lower highs:** high(t) < high(t−1) < high(t−2) on daily bars, or the
  daily high within 1% of L on three consecutive sessions with the close
  under L.
- **σ:** stage 4's, the standard deviation of the last 20 daily log
  returns through t.

## The candidates

Fill rules run in session t+1 on stage 4's machinery (`adaptive_entry`'s
candidate interface: a function of the session's bars, the open, the
reference close, σ and the levels; the `/5` allocator's orders at 20
offsets; the official close as the fallback), priced against the control
`dip_or_close`:

- **S1a, resistance guard (defer):** the control, except that a buy whose
  first bar is *rejected* at L is filled at the close.
- **S1b, resistance guard (skip):** as S1a, but the buy is not filled in
  t+1 at all; it is re-planned for t+2 as the desk's deferred-buy leg
  already does for unfilled orders (`OrderJournal.deferred_units`), and
  filled there by the control rule. Reported with the drift adjustment
  the stage-5 study used for a one-session wait.
- **S1c, hold-the-dip:** when the first bar reaches the 1% dip, the buy is
  sent at the close of the *next* bar only if that bar closes above the
  dip bar's low; otherwise the rule keeps watching (any later bar that
  closes 1% under the open and above the prior bar's low), else the close.
- **S1d, decision-price reference:** the dip level is min(open(t+1),
  close(t)) × 0.99, so a gap-up session does not buy 3% above the
  decision price on a 1% wiggle; and when open(t+1) > close(t) × (1 + σ)
  the buy waits for the close.
- **S1e, market-relative dip:** the trigger is the bar's return from the
  open at or under −1% *in excess of* SPY's return from its open over the
  same bar (the index cube exists in `bars_15m_sip`); with no SPY bar the
  control applies.
- **S1f, sell at the tag:** for sells and trims, the control (1% over the
  open, else the close), except that a sell is sent at the first bar whose
  high reaches L from below, at L (a limit at the level, filled if the bar
  traded through it; else the control continues).

A grade rule, run through the technical analyst and the point-in-time
scorecard, not the fill harness:

- **S1g, structure notch:** a name whose close is under a *falling* EMA21
  with *lower highs* has its technical stance capped at neutral (0) that
  session, so it cannot be A+ and an A needs the other analysts; the
  stance returns when either condition clears. This is a change to
  `technical.py`'s stance, measured as the analysts are (rank IC, the
  book gate on the T-S1 scorecard against `graded-equal-weight/5`, 20
  offsets), and the null test (the notch never firing reproduces the
  incumbent bit for bit).

Seven candidates. Reported beside them, deciding nothing: how often each
fires, the fills by bar, the reading by grade and by leg, the oracle
capture, and, for S1g, the names and sessions it notched in 2026.

## Criteria, fixed now

A fill rule **REPLACES** its side of the board's rule if, at the median
offset: (1) the model-window (2018-01-02..2023-12-29) mean gain over the
control is at least +2.0 bp of equity a session with a Newey-West t (lag
20) ≥ 2.0; (2) the next-bar run holds the same floor; (3) 2024-2026 is not
negative; (4) the deflated Sharpe at N = 7 is ≥ 0.95; (5) the
drift-adjusted mean (for S1b, the only one that waits) is ≥ +1.0 bp at
t ≥ 2; (6) positive at 15 of 20 offsets. **Real but immaterial** as stage
4 defines it (clustered t ≥ 3 on the re-timed orders, below the floor):
reported, the board unchanged, the rule kept as an option for the manual
book.

S1g **REPLACES** the technical stance if the T-S1 book gate holds
(+2 bp a session at 25 bp over the incumbent, NW t ≥ 2 on 2016-2023, not
negative on 2024-2026, positive at 15 of 20 offsets, deflated Sharpe at
the cumulative count ≥ 0.95) **or** if it lowers the median worst drawdown
by 3 points on both windows with a CAGR difference inside ±1 point (a
drawdown rule is allowed to win on drawdown, since that is what it is
for). Anything else is **RECORD**.

## Trials and prior

Seven registered; cumulative 457 → 464. Priors: S1a/S1b 25% (the
mechanism is the one the tape showed; the base rate of rejections is
unknown), S1c 15%, S1d 20% (it fixes a real asymmetry but on few sessions),
S1e 15%, S1f 20%, S1g 20% on the drawdown criterion and 10% on the return
gate. The likely overall finding: one or two rules are real but immaterial
on the paper book's size, and S1g moves drawdown more than return.

## Order of work

1. This note is committed and pushed before any code.
2. Build with tests: the level definitions (shared with the board's
   `structure.py`, so the study and the display cannot disagree), the six
   fill candidates on `adaptive_entry`, S1g in `technical.py` behind a
   flag, the CLI, payload and verdicts, an independent check script.
3. Run on spark1 (CPU, niced, outside market hours where it competes with
   the balancer). Write-up, independent recomputation, report.

## Not in scope

Earnings pauses, trailing intraday sells, event-conditioned exits (S2) and
the regime gross (S3) wait for this batch.

## Addendum 1 (2026-09-30, 12:50 ET, before any run): what the notch does to the grade

The build showed that "cannot be A+" was loosely worded. The grading rule
makes A+ from a bullish release with two or more votes, and fundamental,
sentiment and value can supply those without the technical analyst. S1g
therefore does exactly one thing: while the name is under a falling EMA21
with lower highs, the technical stance and conviction are capped at
neutral, so the technical vote is withdrawn. A name can still be A+ on the
other three. The criteria are unchanged; the write-up reports how many
notched sessions kept A+ on the other analysts.

Two build conventions, recorded here: H20 requires a full 20-session
window (younger names have no H20 level; the board answers for them as
`structure.py` does), and the study runs on the panel's adjusted basis
while the board compares an adjusted EMA with raw quotes, a dividend
factor apart. S1f fills at the open when the session opens through L.
