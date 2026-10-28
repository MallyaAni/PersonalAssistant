# 52-week-high proximity tilt on the installed rule: pre-registration — 2026-10-28

**Status: registered before any code or number for this arm.** This note
fixes the score, the arms, the dispersion stop, the gate and the placebos
before the first run. It is a candidate for the 2027 review, not a live
change. Nothing here changes the live rule, and the rule stays frozen for
252 sessions (`trading-program-2026-10-28.md`, P0).

## Why this arm

C1, residual momentum, and C2, the value × residual-momentum blend, both
failed their pre-registered gates
(`residual-momentum-results-2026-10-28.md`,
`value-momentum-blend-results-2026-10-28.md`). Neither a beta-adjusted past
return nor a second value rank improved the installed leader tilt at 25 bp.
C3 tests a different reading of momentum: how close the name is to its own
52-week high, not how much it has returned.

George & Hwang (2004) report that the 52-week-high strategy dominates
Jegadeesh–Titman momentum, and Bhootra & Hur (2013) report that the recency
of the high adds information. The mechanism is behavioural: nearness to the
high is a reference point that survives small reversals, while a raw
trailing return is dominated by the starting price. In a theme book where
betas are similar, this may be the more robust leader reading.

The risk is explicit: in a book where most names are near their highs, the
cross-sectional rank has little dispersion and the tilt is noise. The
choosing window's measured dispersion is not thin — the median
cross-sectional interquartile range of the score is 0.1203, the 10th
percentile 0.0745 and the minimum 0.0481 — but the study still fixes a
dispersion stop before reading the arm.

## The score

At each close `t`, for each name:

```
H[t] = adj_close[t] / max(adj_close[t - 251 : t + 1])
```

when the 252-session window has 252 finite adjusted closes; otherwise NaN.
The window includes `t`, ends at the decision close, and reads nothing
after it. The cache has no intraday high column, so the score uses the
highest adjusted close, not the highest intraday print; that proxy is
disclosed and fixed here. `H` is in (0, 1], with 1 at the high.

On each session, rank `H` cross-sectionally among the arm's universe
members with `baselines.percentile_rank` (non-members set to NaN), and give
a missing reading the neutral 0.5:

```
h = percentile_rank(H masked to members)
h[missing] = 0.5
```

The engine ranks `h` among the names it sizes and maps the rank with the
installed `1 + strength * (2q/(n-1) - 1)`, strength 0.5. The installed
P/E-history `extra` tilt, volatility target, exposure floor and 25% cap are
unchanged.

## Data and point-in-time rules

- **Cache.** `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time
  cache used by C1, C2 and the risk dial. It carries dates, tickers,
  benchmark, membership, sector, open, close, adj_close, grades, band and
  the P/E tilt. It does not carry high, low or volume.
- **Universes.** S&P 500 point-in-time membership, and its Information
  Technology and Communication Services subset. The primary gate is on the
  S&P 500 PIT universe; IT+Comm is reported and does not gate.
- **Costs.** 10 and 25 bp. The primary gate is at 25 bp; 10 bp is reported.
- **Windows.** Choosing 2016-2023, from the cache's first sizable session
  (2015-04-07) through 2023-12-29; reported 2024-01-02 through 2026-10-23.
  The reported window is never tuned on.
- **Engine.** `policy_book.simulate` with the installed `Rule` (A entry, B
  hold, 1% minimum trade, band block, the installed FOMC path, 25% name cap,
  0.5 exposure floor, 0.25 volatility target, next-open fills) and only the
  leader score source changed. The FOMC retirement candidate is not part of
  this study; the baseline is the installed hold-through path the risk dial
  measured.
- **Baseline.** `Rule` with the installed leader tilt must reproduce the
  risk dial's 0.25/25 line exactly: S&P 500 PIT choosing 10.6747% CAGR /
  −33.3296% worst drawdown / 0.6736 Sharpe; reported 26.2893% / −19.1375% /
  1.6743; all 14.2725% / −33.3296% / 0.8842. If it does not, the study
  stops.

## The dispersion stop

Before any arm is read, compute for every choosing-window session the
cross-sectional interquartile range of `H` among members with a finite
reading. If the **median** over the choosing window is below **0.05**, the
tilt is refused and the study stops without reading an arm: the rank would
be noise. Report the median, the 10th percentile, the minimum and the
fraction of sessions below 0.05. The threshold is fixed here and is not
tuned after seeing the result.

## The arms

1. **Baseline.** Installed raw trailing-return leader tilt, strength 0.5,
   with the installed P/E `extra` tilt.
2. **High only (primary).** `h` passed as the leader score, strength 0.5,
   with the installed P/E `extra` tilt.
3. **Reverse high (directional placebo, one run).** `1 - h` passed as the
   leader score: the farthest names from their highs get the top
   multiplier. This tests the sign of the signal, not its assignment.
4. **High + residual blend (sensitivity, not gated).** `0.5 * h +
   0.5 * r`, where `r` is the C1 residual score ranked among members with
   missing at 0.5. Reported beside the primary; it cannot rescue a failed
   primary.
5. **Random high (placebo, 200 draws).** At each session, shuffle the `h`
   scores across the S&P 500 PIT members (seeds 20261028..20261227) and
   apply the same engine path. The placebo preserves each session's finite
   score multiset; only the assignment of scores to names differs.
6. **Off null.** `leader_scores=None` must reproduce the installed book
   byte-identically, including the final plan.
7. **Strength-zero null.** A single run with strength 0 must reproduce the
   equal-slot book, with and without `h`; scores must be inert.

## The gate

The high-only arm passes if, on S&P 500 PIT at 25 bp, choosing 2016-2023:

- choosing Sharpe is at least **0.05 above** the installed rule's
  (0.6736, so at least 0.7236), and
- choosing CAGR is no worse than **0.5 percentage points below** the
  installed rule's (10.6747%, so at least 10.1747%), and
- choosing worst drawdown is no deeper than **−31.3296%**, at least 2.0
  points shallower than the installed rule's −33.3296%, and never deeper
  than the owner's −35.0% tolerance, and
- the Sharpe improvement exceeds the **reverse-high arm's improvement**
  over the same baseline, and
- the Sharpe improvement exceeds the **95th percentile of the 200 random
  high tilts' improvements**, and
- the perturbation check passes, and
- the off null reproduces the installed book exactly, and
- the placebo multiset and strength-zero equal-slot checks pass.

The reported window, the 10 bp result, the IT+Comm universe and the
high + residual blend are reported but do not gate. A pass on the choosing
window with a worse full-period or reported result must be stated in the
note; it does not become a pass by silence.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent:

- `leader_scores=None` produces equity, weights, trades, cash and the
  final plan byte-identical to the installed rule on the frozen cache.
- The high score equals `adj_close[t] / max(adj_close[t-251:t+1])` with
  the 252-finite-close condition, for every finite cell; a unit test
  asserts it.
- The reverse arm is exactly `1 - h` for every finite cell.
- The random high with a fixed seed permutes exactly the finite `h`
  scores of the members per session; a unit test asserts the multiset is
  unchanged.
- The perturbation test changes every close after the 60% session and
  asserts the high and blend scores before it are identical.
- The off null reproduces the risk dial line exactly. Any difference stops
  the study before an arm is read.

## Stop conditions

The study stops, with the failure written beside this note, if any of:

- the off null does not reproduce the risk dial line;
- the median dispersion is below 0.05;
- the high-only arm fails any gate component;
- the reverse-high arm is not worse than the high arm;
- the random placebo's 95th percentile is not exceeded;
- the perturbation or the null tests fail.

A stop is a result. The arm is not retried with a different high window
(251, 252 or 253 sessions), a different high definition (intraday versus
close), a different blend weight, strength, dispersion threshold or window
without a new pre-registration that says what changed and why.

## What passing buys

A pass buys a forward shadow of the high tilt beside the installed rule
for at least 60 sessions, not an install. The live rule is frozen through
October 2027; any change waits for the 252-session review and the owner's
decision. The shadow's job is to show the choosing-window gain survives
the reported window and live data before it can be considered for the next
release.

## References

- George & Hwang (2004), "The 52-Week High and Momentum Investing",
  Journal of Finance.
- Bhootra & Hur (2013), "The Timing of 52-Week High Signals", Journal of
  Banking & Finance.
- `docs/research/residual-momentum-results-2026-10-28.md` for C1's failure.
- `docs/research/value-momentum-blend-results-2026-10-28.md` for C2's
  failure.
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C3.
- `docs/research/risk-dial-2026-10-28.md` for the baseline lines.
