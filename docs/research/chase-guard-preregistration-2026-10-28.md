# Chase guard on the installed rule: pre-registration — 2026-10-28

**Status: registered before any code or number for this arm.** This note fixes
the question, the overlay, the arms, the gate and the placebo before the first
run. It is a candidate for the 2027 review, not a live change. Nothing here
changes the live rule.

## Why this arm

The installed rule enters at A and holds while B. The signal audit of
2026-10-21 found that entries into names that had already run at least 25% over
the trailing 63 sessions lost to the benchmark: −1.7% at 60 sessions, 39% hit
rate, n = 110. Entries into names that had not run were +3% to +5%
(`leader-policy-signal-audit-2026-10-21.md`). On the book's 94 names with
point-in-time membership, the guard improved the minB arm's Sharpe from 1.07 to
1.13 and cut its worst drawdown from −32.8% to −31.2% with CAGR flat
(25.0% to 25.1%, 25 bp, 2016-2023). The audit's conclusion was that the
no-chase guard is the next thing to put in front of the owner, as a Sharpe
improvement rather than a return one, once the B cut has a forward record.

The B cut has no forward record, and the program freezes the live rule for 252
sessions (`trading-program-2026-10-28.md`, P0). This study is therefore
research for the 2027 review, not an install. The honest baseline's full-period
Sharpe is 0.884 at 25 bp, below the program's 1.0 objective. The guard is the
one measured lever that improved Sharpe on the book without adding return
risk, so it is the next honest-universe test.

## The overlay

At each close `t`, after the ordinary leader target and the band block, a name
that is not held at `t` (`shares == 0`) and whose trailing 63-session simple
return (`adj_close[t] / adj_close[t-63] - 1`) exceeds **0.25** has its target
set to **0**. Held names are untouched. The deferred capital stays cash; the
target is not renormalized. This is
`point_in_time.chase_guard_allocator(max_return=0.25, window=63)` adapted to
the `policy_book` engine's share-based held definition. The benchmark-hot
variant (`max_bench_return`) is not part of the primary arm.

The overlay reads only closes on or before `t`. The perturbation test changes
every close after a cutoff and asserts the deferral flags before it are
identical.

## Data and point-in-time rules

- **Cache.** `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache
  used by the risk dial on 2026-10-24. It carries dates, tickers, benchmark,
  membership, sector, open, close, adj_close, grades, band and tilt.
- **Universes.** The S&P 500 point-in-time membership, and its Information
  Technology and Communication Services subset. The primary gate is on the
  S&P 500 PIT universe; IT+Comm is reported for the owner's mandate decision
  and does not gate.
- **Costs.** 10 and 25 bp. The primary gate is at 25 bp; 10 bp is reported.
- **Windows.** Choosing 2016-2023, from the cache's first sizable session
  (2015-04-07) through 2023-12-29; reported 2024-01-02 through 2026-10-23. The
  reported window is never tuned on.
- **Engine.** `policy_book.simulate` with the installed `Rule` and only
  `Rule.chase` set: A entry / B hold, 1% minimum trade, band block, the
  installed FOMC path, 25% name cap, 0.5 exposure floor, 0.25 volatility
  target, next-open fills. The FOMC retirement candidate is not part of this
  study, so the baseline is the installed policy the risk dial measured.
- **Baseline.** The same run with `Rule.chase=None`. It must reproduce the
  risk dial's 0.25/25 line exactly: S&P 500 PIT choosing
  10.6747% CAGR / −33.3296% worst drawdown / 0.6736 Sharpe; reported
  26.2893% / −19.1375% / 1.6743; all 14.2725% / −33.3296% / 0.8842. If it does
  not, the study stops.

## The arms

1. **Chase25 (primary).** `Rule(chase=0.25)`. The gate applies to this arm
   only.
2. **Chase40 (sensitivity, reported beside the primary, not a second trial).**
   `Rule(chase=0.40)`. It shows the threshold sensitivity the audit saw; it is
   not gated and does not rescue a failed primary.
3. **Random deferral (placebo, 200 draws).**
   `Rule(chase=0.25, chase_random=seed)`: at each session, count the names the
   guard would defer and defer a uniformly random subset of the same count
   from all entering names (positive target, no shares). Seeds
   20261028..20261227. The placebo is on S&P 500 PIT at 25 bp, choosing
   window. The random arm uses the same engine, the same held definition and
   the same cash treatment; only the choice of names differs.
4. **Off null.** `Rule(chase=None)` must reproduce the installed book exactly.
5. **All-defer null.** `Rule(chase=-1.0)` defers every entering name, because
   every positive-price simple return is greater than −1.0. It is run once and
   reported with its deferred count and its book; it is not read as a neutral
   score.

## The gate

**Chase25 passes if, on S&P 500 PIT at 25 bp, choosing 2016-2023:**

- choosing-window Sharpe is at least **0.05 above** the installed rule's
  (0.6736, so at least 0.7236), and
- choosing-window CAGR is no worse than **1.0 percentage point below** the
  installed rule's (10.6747%, so at least 9.6747%), and
- choosing-window worst drawdown is no deeper than **−35.0%**, the owner's
  tolerance, and
- the Sharpe improvement exceeds the **95th percentile of the 200 random
  deferrals' Sharpe improvements**, and
- the perturbation check passes, and
- the off null reproduces the installed book exactly.

The reported window, the 10 bp result and the IT+Comm universe are reported
but do not gate. A pass on the choosing window with a worse full-period or
reported result must be stated in the note; it does not become a pass by
silence.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent:

- `Rule(chase=None)` produces equity, weights, trades, cash and the final plan
  byte-identical to the installed rule on the frozen cache and on the unit
  market.
- `Rule(chase=-1.0)` defers every entering name; the study reports the count
  and the book. If the book still enters names, the guard is not deferring
  entries and the study stops.
- The random arm with a fixed seed defers exactly the guard's count per
  session and only names that are entering; a unit test asserts both.
- The perturbation test changes every close after the 60% session and asserts
  the deferral flags before it are identical; a unit test asserts it on a
  synthetic panel.

A failure stops the study.

## What is already known, disclosed before the run

- The guard's book-PIT result is a Sharpe improvement with CAGR flat and a
  shallower drawdown on the minB arm, but the audit's installed A cut showed a
  slightly deeper drawdown (−34.2% to −35.4%) with the same Sharpe gain. The
  honest universe may show either pattern; the drawdown gate is the owner's
  −35% tolerance, not the baseline's −33.3%.
- The guard is a momentum filter on entries, not an exit rule. It does not
  change held names, so it cannot rescue a name already owned.
- The cache is frozen at 2026-10-24; grades, band, tilt and membership are the
  desk as it stood then. Only `Rule.chase` changes, so the comparison across
  arms is clean, but the absolute levels are not a fresh backtest of today's
  desk.
- The store holds bars only for names it carries today; the membership is
  dated but the price history is survivor-biased. The absolute levels are
  flattered; the comparison across arms is the point.
- The choosing leg starts at the cache's first sizable session (2015-04-07),
  not 2016-01-01. The desk's grades are effective from 2016, so the first
  months are mostly cash; the program's 2016-2023 label is approximate.
- The guard is not in the live sizing path. `policy_book` is the simulator;
  the live nightly plan sizes through `grade_led_leader_policy.size_report`.
  A pass here is a candidate for a shared helper in both paths, a release
  ceremony and a 252-session forward shadow, not a live change.

## What passing and failing mean

- **Pass:** a 2027 review candidate. The note records the gate, the reported
  window and the full-period result. No live change; the program's freeze
  stands. A live candidate would need the same helper in `size_report` and
  `policy_book`, the release ceremony, and a 252-session forward shadow.
- **Fail:** written down with its evidence in `docs/research/`; not retried
  without a new pre-registration. The guard is not added to the rule, the
  board, or any prompt.

## Amendments

**2026-10-28, before the first run.** The all-defer null is `chase=-1.0`, not
`chase=0.0`: a simple return above −1.0 is the only threshold that defers every
entering name on positive prices. No gate, arm or window changed.
