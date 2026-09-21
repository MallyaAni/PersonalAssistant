# Portfolio allocation decision protocol (2026-09-21)

Scope: the pure decision only. A decision is computed from prices, unscaled
desired stock weights, actual held weights, and absolute equity ceilings. It
makes no orders, touches no ledger, and reads no broker. Execution is a later
milestone. No fitting, no search, no model, no I/O.

The incumbent default (policy "off") is untouched by this module. Only the
two fixed predeclared alternatives are implemented here:

- `vol` — benchmark-relative volatility budget, residual SPY, no trend ceiling.
- `vol_trend` — the same budget plus a broad trend ceiling.

QQQ is a risk benchmark only; it is never selected as a residual asset in
these candidates. SPY is the only index that may fill residual capacity, and
only when the caller says it is eligible.

## Inputs

- `dates` — ordered (T,) session dates (strictly ascending).
- `prices` — (T, N) adjusted-close matrix; tickers must include `SPY` and `QQQ`.
- `tickers` — (N,) ticker names.
- `t` — decision index; only rows `<= t` may be used (internally the matrix may
  carry future rows; the computation slices at `t`).
- `desired` — {ticker: weight} unscaled desired stock weights (fractions of
  equity, each `>= 0`, total `<= 1`).
- `held` — {ticker: weight} actual held weights (fractions, total `<= 1`).
- `regime_cap`, `event_cap` — absolute total-equity ceilings in `[0, 1]`.
- `policy` — `"vol"` or `"vol_trend"`.
- `index_eligible` — whether SPY may fill residual equity capacity.

Unknown values are never treated as zero: a desired/held ticker absent from
`tickers` is a caller error; a NaN price for a positive-weight component makes
the volatility evidence incomplete (unavailable), never a fabricated zero
return.

## Algorithm (fixed before results)

### 1. Candidate composition

1. Cap each desired stock weight at the existing 15% company cap
   (`paper.ENTRY_NAME_CAP`).
2. Let `S` be the sum of the capped stock weights. If `S > regime_cap`, scale
   every stock weight by `regime_cap / S` so the stock book never exceeds the
   regime equity cap. Otherwise leave the stock weights as given.
3. Residual index: `index = max(0, regime_cap - S)` when `index_eligible`,
   else `0` (the capacity stays cash). QQQ is never the residual.
4. Candidate sum `S_c = S + index`.

### 2. Volatility budget

Simple returns `r[t, i] = prices[t, i] / prices[t-1, i] - 1`, NaN on the first
row. Only rows `<= t` are used.

For a series `x`, the risk estimate is

```
risk(x, t) = max(std20, std60) * sqrt(252)
```

where `std20`/`std60` are the population standard deviations of the last
20 / last 60 completed returns through `t`. A window must be complete (all
its returns finite); otherwise the estimate is unavailable.

- Portfolio risk: the candidate-weighted sum of the component simple returns
  (the fixed candidate weights over the positive-weight components, which
  preserves covariance in the weighted sum). Every positive-weight component
  must have 60 complete returns through `t`; if any does not, the portfolio
  risk is unavailable. A valid zero portfolio risk (e.g. two perfectly
  negatively correlated legs) is not missing — it needs no reduction.
- Benchmark risk: `risk(SPY, t)` and `risk(QQQ, t)` by the same formula.
- Budget `B = min(risk(SPY, t), risk(QQQ, t))`.
- Risk scale `risk_scale = min(1, B / portfolio_risk)` when portfolio risk is
  positive; `risk_scale = 1` for zero portfolio risk. Never above 1, so no
  leverage.

### 3. Absolute ceilings and combination

- Trend ceiling (policy `vol_trend` only): the fraction of `SPY`/`QQQ` whose
  close is above its own trailing 200-session adjusted-close mean,
  `(above_SPY + above_QQQ) / 2`, which takes the values `0`, `0.5`, `1`. It is
  known only when both histories are complete through `t`; a missing trend is
  unavailable and is never classified bearish.
- The absolute total-equity ceiling `C = min(known ceilings)` over
  `{regime_cap, event_cap, trend}` — a minimum, never a multiplication.
- Final scalar `final = min(risk_scale, C / S_c, 1)` for positive `S_c`;
  an empty candidate has zero equity weight without division.
- Desired weights = candidate weights `* final`; cash `= 1 - sum(desired)`.

A missing trend is excluded from the minimum (not treated as `0`); a missing
`C` is never treated as `0` either.

### 4. Missing policy evidence

When volatility evidence is incomplete, or `vol_trend` lacks its complete
200-price trend (`available = false`), no new risk is inferred from missing
data. An empty candidate still requests all cash, even when diagnostics are
unavailable. This is a target, not a claim that missing-price holdings sold.
For a nonempty candidate:

1. Start from the actual held weights.
2. If the held exposure exceeds the known absolute ceiling `C`, cut all held
   weights proportionally to `C`.
3. Otherwise retain the actual held weights and cash.

This is a proportional cut of what is held, so a newly listed stock without 60
returns cannot block a known market-risk cut, and recovery into new exposure
waits for all evidence required by the selected policy. Returns require two
finite positive price endpoints; trend requires finite positive prices.

### 5. Stability

Every valid decision returns absolute targets computed from the original
unscaled desired composition. Yesterday's reduced target is never used as
today's desired input, so repeated identical stress produces identical targets
and a single stress is never re-halved.

## Output

`AllocationDecision` with `version`, `as_of`, `desired_weights`, `cash`,
`available`, `reasons`, `missing`, `volatility` diagnostics and `binding`.

## Evaluation convention

Candidates and SPY/QQQ are compared on one identical executable window after
a common 252-session warmup (`panel.dates[252]`). Historical warmup data may
inform the first decision but pre-warmup returns are not evaluated. This is an
evaluation convention, not an additional live decision rule.
