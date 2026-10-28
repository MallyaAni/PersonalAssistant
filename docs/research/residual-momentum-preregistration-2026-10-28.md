# Residual-momentum leader tilt on the installed rule: pre-registration — 2026-10-28

**Status: registered before any code or number for this arm.** This note fixes
the question, the tilt, the arms, the gate and the placebo before the first
run. It is a candidate for the 2027 review, not a live change. Nothing here
changes the live rule, and the rule stays frozen for 252 sessions
(`trading-program-2026-10-28.md`, P0).

## Why this arm

The installed rule's leader tilt is the only sizing lever with a measured
gain: +2.3 CAGR points at the same worst drawdown, with strength 0.5 the knee
and 1.0 jumping the drawdown to −42% (`trading-program-2026-10-28.md`). Its
signal is the raw trailing 63-session simple return, ranked across the A/A+
book and mapped to a 1±0.5 multiplier (`point_in_time.TILTS["leader"]`).

Two facts make a residual version the next honest test:

- On the book's names, raw 63-session momentum carries rank IC 0.042
  (t 1.6) over 60 sessions, while the beta-adjusted six-month residual
  measures 0.055 (t 2.2) (`baselines.residual_momentum` docstring). The
  residual signal is stronger on the same names.
- The raw-return tilt is exposed to the momentum crash: after a market
  rebound, high-beta past winners rebound least, and the tilt is largest in
  exactly those names (Daniel & Moskowitz 2016). Residual momentum subtracts
  the market's beta-scaled return, so a name is rewarded for what it did
  *relative to its own beta*, not for the beta it carried
  (Blitz, Huij & Martens 2011).

The external evidence and the internal IC point the same way, which is why
this is the first candidate in `top-tier-algorithms-2026-10-28.md`.

## The tilt

At each close `t`, for every name the installed rule can size, the leader
multiplier becomes `1 ± 0.5` by the cross-sectional rank of

```
residual_momentum(adj_close, length, skip=21, beta_lookback=120)[t]
```

where the score is the sum of beta-adjusted daily log returns over the last
`length` sessions ending `skip` sessions before `t`, divided by their
cross-sectional time-series standard deviation (`baselines.residual_momentum`,
unchanged). The rank mapping is the installed one: ascending score rank
`r = 0..n-1` becomes `1 + strength * (2r/(n-1) - 1)`, so the weakest score is
`1 - strength` and the strongest `1 + strength`. The P/E-history multiplier,
the volatility target, the exposure floor and the 25% cap are exactly the
installed rule's.

The score at `t` reads returns through `t - 21` only. The perturbation test
changes every close after a cutoff and asserts the scores before it are
identical.

**Implementation, one engine.** `policy_book.simulate` gains an optional
`leader_scores` (T, N) array, and `grade_led_leader_policy.leader_weights`
gains an optional `scores` vector that replaces the trailing-return rank when
given; both default to `None`, and the off null must reproduce the installed
book byte-identically. The production nightly never passes the new argument.
The parameter is inert, but it touches a bound source, so merging it takes the
release ceremony; it is not merged until the study passes and the owner
approves.

## Data and point-in-time rules

- **Cache.** `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time cache
  used by the risk dial and the chase guard. It carries dates, tickers,
  benchmark, membership, sector, open, close, adj_close, grades, band and the
  P/E tilt.
- **Universes.** S&P 500 point-in-time membership, and its Information
  Technology and Communication Services subset. The primary gate is on the
  S&P 500 PIT universe; IT+Comm is reported for the owner's mandate decision
  and does not gate.
- **Costs.** 10 and 25 bp. The primary gate is at 25 bp; 10 bp is reported.
- **Windows.** Choosing 2016-2023, from the cache's first sizable session
  (2015-04-07) through 2023-12-29; reported 2024-01-02 through 2026-10-23.
  The reported window is never tuned on.
- **Engine.** `policy_book.simulate` with the installed `Rule` (A entry, B
  hold, 1% minimum trade, band block, the installed FOMC path, 25% name cap,
  0.5 exposure floor, 0.25 volatility target, next-open fills) and only the
  leader score source changed. The FOMC retirement candidate is not part of
  this study; the baseline is the installed policy the risk dial measured.
- **Baseline.** `Rule` with the installed leader tilt must reproduce the risk
  dial's 0.25/25 line exactly: S&P 500 PIT choosing 10.6747% CAGR / −33.3296%
  worst drawdown / 0.6736 Sharpe; reported 26.2893% / −19.1375% / 1.6743; all
  14.2725% / −33.3296% / 0.8842. If it does not, the study stops.

## The arms

1. **R120 (primary).** Residual score with `length=120`, `skip=21`,
   `beta_lookback=120`, strength 0.5. The gate applies to this arm only.
2. **R252 (sensitivity, reported beside the primary, not a second trial).**
   `length=252`. It shows horizon sensitivity; it is not gated and does not
   rescue a failed primary.
3. **Random tilt (placebo, 200 draws).** At each session, shuffle the R120
   scores across the sizable names (seeds 20261028..20261227) and apply the
   same rank mapping. The placebo is on S&P 500 PIT at 25 bp, choosing
   window. It uses the same engine and the same mapping; only the assignment
   of scores to names differs.
4. **Off null.** The installed leader tilt must reproduce the risk dial's
   line exactly, including the final plan.
5. **All-cash null.** A tilt of zero for every name is not a valid arm (the
   rank mapping is undefined); instead, a single run with `strength=0` must
   reproduce the equal-slot book, and its gross and cash are reported.

## The gate

**R120 passes if, on S&P 500 PIT at 25 bp, choosing 2016-2023:**

- choosing-window Sharpe is at least **0.05 above** the installed rule's
  (0.6736, so at least 0.7236), and
- choosing-window CAGR is no worse than **0.5 percentage points below** the
  installed rule's (10.6747%, so at least 10.1747%), and
- choosing-window worst drawdown is no deeper than **−31.3296%**, at least
  2.0 points shallower than the installed rule's −33.3296%, and never deeper
  than the owner's −35.0% tolerance, and
- the Sharpe improvement exceeds the **95th percentile of the 200 random
  tilts' Sharpe improvements**, and
- the perturbation check passes, and
- the off null reproduces the installed book exactly.

The reported window, the 10 bp result and the IT+Comm universe are reported
but do not gate. A pass on the choosing window with a worse full-period or
reported result must be stated in the note; it does not become a pass by
silence.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent:

- `leader_scores=None` produces equity, weights, trades, cash and the final
  plan byte-identical to the installed rule on the frozen cache and on the
  unit market.
- The R120 score array equals `baselines.residual_momentum` on a Panel built
  from the cache, for every finite cell; a unit test asserts it.
- The random tilt with a fixed seed permutes exactly the finite scores of the
  sizable names per session; a unit test asserts the multiset is unchanged.
- The perturbation test changes every close after the 60% session and asserts
  the scores before it are identical; a unit test asserts it on the unit
  market.
- The off null reproduces the risk dial line exactly. Any difference stops
  the study before an arm is read.

## Stop conditions

The study stops, with the failure written beside this note, if any of:

- the off null does not reproduce the risk dial line;
- R120 fails any gate component;
- the placebo's 95th percentile is not exceeded;
- the perturbation or the null tests fail.

A stop is a result. The arm is not retried with a different length, skip,
beta lookback, strength or window without a new pre-registration that says
what changed and why.

## What passing buys

A pass buys a forward shadow of the residual tilt beside the installed rule
for at least 60 sessions, not an install. The live rule is frozen through
October 2027; any change waits for the 252-session review and the owner's
decision. The shadow's job is to show the choosing-window gain survives the
reported window and live data before it can be considered for the next
release.

## References

- Blitz, Huij & Martens (2011), "Residual Momentum", Journal of Empirical
  Finance.
- Daniel & Moskowitz (2016), "Momentum Crashes", Journal of Financial
  Economics.
- Jegadeesh & Titman (1993), "Returns to Buying Winners and Selling Losers",
  Journal of Finance.
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C1.
- `docs/research/risk-dial-2026-10-28.md` for the baseline lines.
