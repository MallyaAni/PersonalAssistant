# Value × residual-momentum blend on the installed rule: pre-registration — 2026-10-28

**Status: registered before any code or number for this arm.** This note
fixes the score, the arms, the gate and the placebo before the first run. It
is a candidate for the 2027 review, not a live change. Nothing here changes
the live rule, and the rule stays frozen for 252 sessions
(`trading-program-2026-10-28.md`, P0).

## Why this arm

C1, the residual-momentum leader tilt alone, failed its pre-registered gate:
R120 lost 0.0129 choosing-window Sharpe against the installed rule and
deepened the drawdown by 2.1 points
(`residual-momentum-results-2026-10-28.md`). The residual score is a weaker
sizing signal than the installed trailing-return rank at this horizon.

C2 is not a retry of C1. It tests a different hypothesis: value and momentum
are negatively correlated and complementary (Asness, Moskowitz & Pedersen
2013), and the desk's value leg is the only analyst with positive rank IC
every year since 2020. The installed rule already sizes with the P/E-history
tilt, which earned 34.9% against 33.0% at 25 bp on the account simulator and
37.6% against 34.9% in its installed form (18.8% against 16.9% to 2022,
74.8% against 72.9% after; `pe-history-tilt-2026-10-24.md`). The value ×3
study measured 17.1% against 15.3% on the S&P 500 point-in-time universe at
25 bp. The question is whether a second, cross-sectional value rank in the
leader slot adds anything beyond the existing P/E tilt, and whether blending
it with residual momentum beats either leg alone.

The residual-only arm is included as a control: it must reproduce C1, and
its expected failure is not a rescue. If the blend does not beat the best
single arm, the answer is to keep that single arm, not to tune the blend.

## The score

At each close `t`, every name gets two leg scores.

**Residual leg.** `baselines.residual_momentum(adj_close, length=120,
skip=21, beta_lookback=120)[t]`, the C1 score: the sum of beta-adjusted
daily log returns over the last 120 sessions ending 21 sessions before `t`,
divided by their cross-sectional time-series standard deviation. The score
at `t` reads returns through `t - 21` only.

**Value leg.** The cache's `tilt` matrix is the installed P/E-history
multiplier, `1 + 0.5 * (1 - 2h)`, where `h` is where the name's P/E sits in
its own trailing 756 sessions (0 the cheapest, 1 the richest; at least 250
readings; no positive earnings or too little history leaves the slot
unchanged at 1.0). The cache stores this multiplier for every name and
session, with no missing cells. Invert it exactly:

```
V = tilt - 0.5          # cheap is high; V in [0, 1], 0.5 is neutral
```

because `tilt = 1.5 - h`, so `V = 1 - h`. The installed P/E multiplier is
still applied separately to every arm as the rule's `extra` tilt; the value
leg here is a second, cross-sectional reading of the same evidence, which is
the double-counting risk this note measures rather than assumes away.

**Blend.** On each session, rank each leg cross-sectionally among the
universe's members (non-members set to NaN, so they do not enter the rank):

```
r = percentile_rank(R)     # baselines.percentile_rank
v = percentile_rank(V)
r[missing] = 0.5           # a name with no residual reading is neutral
v[missing] = 0.5           # no positive earnings or short history is neutral
B = 0.5 * r + 0.5 * v
```

This is `baselines.rank_blend` semantics with a neutral 0.5 for a missing
leg; `np.mean` on unfilled NaNs would rank a name with no reading as the
weakest, which is not what the installed P/E tilt does. The engine then
ranks `B` among the names it sizes and maps the rank with the installed
`1 + strength * (2q/(n-1) - 1)`, strength 0.5, exactly as C1 ranks the
residual score. The P/E-history multiplier, volatility target, exposure
floor and 25% cap are unchanged.

The score at `t` reads closes through `t` and P/E readings through `t`; the
residual leg stops at `t - 21`. The perturbation test changes every close
after a cutoff and asserts the blend scores before it are identical.

**Implementation, scratch only.** The C1 scratch engine
(`policy_book_resid.py`, `leader_resid.py`) already accepts a `leader_scores`
matrix and ranks it among the sized names. C2 passes `B` through that same
path; the production `policy_book.simulate` and
`grade_led_leader_policy.leader_weights` are unchanged and never receive a
score matrix. No bound source is merged for this study.

## Data and point-in-time rules

- **Cache.** `~/dsv41/pit2/cache.npz`, the frozen S&P 500 point-in-time
  cache used by C1 and the risk dial. It carries dates, tickers, benchmark,
  membership, sector, open, close, adj_close, grades, band and the P/E tilt.
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
  this study; the baseline is the installed hold-through path the risk dial
  measured.
- **Baseline.** `Rule` with the installed leader tilt must reproduce the
  risk dial's 0.25/25 line exactly: S&P 500 PIT choosing 10.6747% CAGR /
  −33.3296% worst drawdown / 0.6736 Sharpe; reported 26.2893% / −19.1375% /
  1.6743; all 14.2725% / −33.3296% / 0.8842. If it does not, the study
  stops.

## The arms

1. **Baseline.** Installed raw trailing-return leader tilt, strength 0.5,
   with the installed P/E `extra` tilt.
2. **Residual only (control).** `R` passed as the leader score, strength
   0.5, with the installed P/E `extra` tilt. It must reproduce C1's R120
   line exactly; a difference is a bug, not a result.
3. **Value only.** `V` passed as the leader score, strength 0.5, with the
   installed P/E `extra` tilt. This is the double-value arm.
4. **Blend (primary).** `B` passed as the leader score, strength 0.5, with
   the installed P/E `extra` tilt.
5. **Random blend (placebo, 200 draws).** At each session, shuffle the `B`
   scores across the S&P 500 PIT members (seeds 20261028..20261227) and
   apply the same engine path. The placebo preserves each session's finite
   score multiset; only the assignment of scores to names differs.
6. **Off null.** `leader_scores=None` must reproduce the installed book
   byte-identically, including the final plan.
7. **Strength-zero null.** A single run with strength 0 must reproduce the
   equal-slot book, with and without `B`; scores must be inert.

## The gate

The reference is the **best single arm** on the choosing window: the
highest Sharpe among the baseline, residual-only and value-only arms,
computed in the same run. The blend passes if, on S&P 500 PIT at 25 bp,
choosing 2016-2023:

- blend Sharpe is at least **0.05 above** the reference Sharpe, and
- blend CAGR is no worse than **0.5 percentage points below** the
  reference CAGR, and
- blend worst drawdown is at least **2.0 points shallower** than the
  reference drawdown and never deeper than the owner's −35.0% tolerance,
  and
- the blend's Sharpe improvement over the reference exceeds the **95th
  percentile of the 200 random blend tilts' improvements** over the same
  reference, and
- the perturbation check passes, and
- the off null reproduces the installed book exactly, and
- the placebo multiset and strength-zero equal-slot checks pass.

The reported window, the 10 bp result and the IT+Comm universe are reported
but do not gate. A pass on the choosing window with a worse full-period or
reported result must be stated in the note; it does not become a pass by
silence.

## The null tests

Before any arm is read, the implementation must reproduce the incumbent and
the control:

- `leader_scores=None` produces equity, weights, trades, cash and the final
  plan byte-identical to the installed rule on the frozen cache.
- The residual-only arm reproduces C1's R120 choosing line exactly
  (10.2836% CAGR / −33.4361% drawdown / 0.6607 Sharpe). Any difference is a
  bug in the C2 runner.
- The value leg equals `tilt - 0.5` for every finite cell; a unit test
  asserts it, including the neutral 0.5 for the cache's missing-P/E 1.0.
- The blend equals `0.5 * percentile_rank(R) + 0.5 * percentile_rank(V)`
  with missing legs at 0.5, over the arm's universe members; a unit test
  asserts it.
- The random blend with a fixed seed permutes exactly the finite blend
  scores of the members per session; a unit test asserts the multiset is
  unchanged.
- The perturbation test changes every close after the 60% session and
  asserts the blend scores before it are identical.
- The off null reproduces the risk dial line exactly. Any difference stops
  the study before an arm is read.

## Stop conditions

The study stops, with the failure written beside this note, if any of:

- the off null does not reproduce the risk dial line;
- the residual-only control does not reproduce C1;
- the blend fails any gate component;
- the placebo's 95th percentile is not exceeded;
- the perturbation or the null tests fail.

A stop is a result. The arm is not retried with a different blend weight,
strength, length, skip, beta lookback, value transform or window without a
new pre-registration that says what changed and why.

## What passing buys

A pass buys a forward shadow of the blend beside the installed rule for at
least 60 sessions, not an install. The live rule is frozen through October
2027; any change waits for the 252-session review and the owner's decision.
The shadow's job is to show the choosing-window gain survives the reported
window and live data before it can be considered for the next release.

## References

- Asness, Moskowitz & Pedersen (2013), "Value and Momentum Everywhere",
  Journal of Finance.
- `docs/research/residual-momentum-results-2026-10-28.md` for C1's failure.
- `docs/research/pe-history-tilt-2026-10-24.md` for the installed P/E tilt.
- `docs/research/top-tier-algorithms-2026-10-28.md`, candidate C2.
- `docs/research/risk-dial-2026-10-28.md` for the baseline lines.
