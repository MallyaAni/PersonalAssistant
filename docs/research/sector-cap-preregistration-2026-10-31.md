# Sector-factor exposure cap on the installed rule: pre-registration — 2026-10-31

**Status: registered before any code or number for this arm.** This note fixes
the question, the overlay, the arms, the gate and the placebo before the first
run. It is a research candidate for the 2027 review, not a live change. Nothing
here changes the live rule, the board, an order, or any prompt.

## Why this arm

The 2026-10-30 session was the concentration risk the owner named: the book's
94 names are 58 Information Technology and 2 Communication Services, and on the
GOOGL shock day the book's mean return was −5.49% against SPY's −1.77%. The
measured same-day sector correlation is high — 85–89% of AI peers fell on
mega-cap down days — while the forward continuation is about zero (the
event-shock study's A1 was stopped as underpowered and A2 found no contagion).
That evidence supports a standing concentration limit, not a post-shock sell
rule: a rule that sells after the event sells at the bottom and misses the
measured bounce. The open question is whether capping the book's weight in its
concentrated sector reduces the worst drawdown enough to justify the return it
gives up.

The prior risk studies bound the expectation. The catastrophe stop found every
price stop was a false alarm and cost 0.1–1.4 CAGR points; the chase guard
failed its honest-universe gate; the risk dial's exposure sweep (0.20/0.25/0.30)
was nearly flat. The installed rule already scales exposure to a 0.25
volatility target with a 0.5 floor, so this study tests a limit the vol target
does not express: a sector share of equity.

## The overlay

At each close `t`, after the ordinary leader target and the band block, let `S`
be the names whose GICS sector is in **Information Technology** or
**Communication Services** (the cache's `sector`; the empty label is not in
`S`). The cap is applied after the protected-holding adjustment: a protected
holding (`g < 0`, held at its weight) is never scaled down. Let `P` be the
protected weight in `S` and `U` the unprotected target weight in `S`. If
`P + U > sector_cap`, every unprotected name in `S` is scaled by
`max(0, sector_cap - P) / U`. Names outside `S` are unchanged. The freed
capital stays cash; the target is not renormalized into other names. If `P`
alone exceeds the cap, the unprotected sector names are scaled to zero and the
session is counted as one where protected holdings alone exceeded the cap.

The overlay reads only closes, grades, band and sector labels on or before `t`.
The perturbation test changes every close after a cutoff and asserts the capped
targets before it are identical.

## Data and point-in-time rules

- **Cache.** `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache
  used by the risk dial, the chase guard and the event-shock study. It carries
  dates, tickers, benchmark, membership, sector, open, close, adj_close, grades,
  band and tilt, 532 tickers and 2,970 sessions (2015-01-02..2026-10-23).
- **Universes.** The S&P 500 point-in-time membership (the gating universe),
  and its Information Technology and Communication Services subset (reported,
  not gated). The cap's sector set is the same two labels in both universes.
- **Costs.** 10 and 25 bp. The primary gate is at 25 bp; 10 bp is reported.
- **Windows.** Choosing 2016-2023, from the cache's first sizable session
  (`START = 64`, 2015-04-07) through 2023-12-29; reported 2024-01-02 through
  2026-10-23; all 2015-04-07 through 2026-10-23. The reported window is never
  tuned on.
- **Engine.** `policy_book.simulate` with the installed `Rule` and only the new
  `Rule.sector_cap` and `simulate(sector=...)` set: A entry / B hold, 1% minimum
  trade, band block, the installed FOMC path, 25% name cap, 0.5 exposure floor,
  0.25 volatility target, next-open fills.
- **Baseline.** The same run with `Rule.sector_cap=None`. It must reproduce the
  risk dial's 0.25/25 line exactly: S&P 500 PIT choosing
  10.6747% CAGR / −33.3296% worst drawdown / 0.6736 Sharpe; reported
  26.2893% / −19.1375% / 1.6743; all 14.2725% / −33.3296% / 0.8842. If it does
  not, the study stops.

## The arms

1. **Cap50 (primary).** `Rule(sector_cap=0.50)` on IT + Communication Services.
   The gate applies to this arm only.
2. **Cap60 (sensitivity, reported, not gated).** `Rule(sector_cap=0.60)`.
3. **Cap40 (sensitivity, reported, not gated).** `Rule(sector_cap=0.40)`.
4. **IT-only Cap50 (sensitivity, reported, not gated).** The cap's sector set is
   Information Technology only. It shows how much of any effect is the wider
   communication-services label.
5. **Random-group placebo (200 draws).** Each draw removes the same per-session
   **removed weight** as Cap50, but from a uniformly random subset of
   unprotected names with positive target (the subset may include sector names
   by chance) rather than the sector group. Seeds 20261031..20261230. At each
   session the draw computes Cap50's removed weight `R = max(0, P + U - cap)`
   and a random subset's weight `G`; it scales that subset by
   `max(0, G - R) / G`. If `G < R`, it removes all of `G` and the session's
   removed weight is recorded as short. The placebo is on S&P 500 PIT at 25 bp,
   choosing window. It uses the same engine, the same held definition and the
   same cash treatment; only the choice of names differs.
6. **Off null.** `Rule(sector_cap=None)` must reproduce the installed book
   exactly.
7. **Cap1 null.** `Rule(sector_cap=1.0)` must reproduce the installed book
   exactly: the target in `S` never exceeds unit capital, so the cap cannot
   bind. This is the parameter's no-op check.
8. **Cap0 null.** `Rule(sector_cap=0.0)` caps the sector group to zero. It is
   run once and reported with its sector holdings and its book; it is not read
   as a neutral score. If any sector name is bought after the cap, the cap is
   not working and the study stops.

## The gate

**Cap50 passes if, on S&P 500 PIT at 25 bp, choosing 2016-2023:**

- choosing-window worst drawdown is at least **2.0 percentage points shallower**
  than the installed rule's (−33.3296%, so no deeper than −31.3296%), and
- choosing-window CAGR is no worse than **1.0 percentage point below** the
  installed rule's (10.6747%, so at least 9.6747%), and
- choosing-window Sharpe is no worse than **0.02 below** the installed rule's
  (0.6736, so at least 0.6536), and
- the drawdown improvement (installed drawdown minus Cap50 drawdown) exceeds the
  **95th percentile of the 200 random-group placebos' drawdown improvements**,
  and
- the perturbation check passes, and
- the off null, the cap1 null and the cap0 null pass.

The reported window, the 10 bp result, the IT+Comm universe and the Cap60/Cap40/
IT-only sensitivities are reported but do not gate. A pass on the choosing window
with a worse full-period or reported result must be stated in the note; it does
not become a pass by silence.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent:

- `Rule(sector_cap=None)` produces equity, weights, trades, cash and the final
  plan byte-identical to the installed rule on the frozen cache and on the unit
  market.
- `Rule(sector_cap=1.0)` is byte-identical to the installed rule: the cap never
  binds.
- `Rule(sector_cap=0.0)` buys no unprotected sector name after the cap and
  holds no unprotected sector name at the end; the study reports any protected
  sector holdings and the book.
- The random-group arm with a fixed seed removes Cap50's per-session removed
  weight from a group that is not the sector group; a unit test asserts the
  removed weights match on a synthetic panel.
- The perturbation test changes every close after the 60% session and asserts
  the capped targets before it are identical; a unit test asserts it on a
  synthetic panel.

A failure stops the study.

## What is already known, disclosed before the run

- The live book is 58 Information Technology and 2 Communication Services of 94
  names; the PIT simulated book's realized sector weight is reported, not
  assumed. The cap binds only when the sector target exceeds 50% of equity, so
  it acts mainly when gross exposure is high; the fraction of sessions where it
  binds and the mean weight removed are reported.
- The cap moves capital to cash, not into other sectors: the desk's graded
  universe has no non-AI names with grades, so the PIT universe's other names
  are grade 0 and are not sized. A diversification benefit would need a wider
  graded universe; the C5 sector sleeve is a separate mandate and is not part
  of this test.
- The installed vol target and 0.5 floor already de-risk. The cap is a limit on
  concentration, not a volatility model, and the two can interact: in a
  high-volatility drawdown the book may already be at the floor and the cap may
  not bind. The study reports that interaction rather than assuming the cap is
  active in every drawdown.
- The cache is frozen at 2026-10-24; grades, band, tilt and membership are the
  desk as it stood then. Only the new cap parameter changes, so the comparison
  across arms is clean, but the absolute levels are not a fresh backtest of
  today's desk.
- The store holds bars only for names it carries today; the membership is dated
  but the price history is survivor-biased. The absolute levels are flattered;
  the comparison across arms is the point.
- The cap is not in the live sizing path. `policy_book` is the simulator; the
  live nightly plan sizes through `grade_led_leader_policy.size_report`. A pass
  here is a candidate for a shared helper in both paths, a release ceremony and
  a 252-session forward shadow, not a live change.
- The event-shock study did not support a post-shock sell rule. This study is
  not that rule: it is a standing exposure limit, evaluated on the same honest
  universe as the risk dial and the chase guard.

## What passing and failing mean

- **Pass:** a 2027 review candidate. The note records the gate, the reported
  window and the full-period result. No live change; the program's freeze
  stands. A live candidate would need the same helper in `size_report` and
  `policy_book`, the release ceremony, and a 252-session forward shadow.
- **Fail:** written down with its evidence in `docs/research/`; not retried
  without a new pre-registration. The cap is not added to the rule, the board,
  or any prompt.

## Amendments

None before the first run.
