# Installed-rule significance: results — 2026-11-02

**Verdict: FAIL on the pre-registered primary gate. The A hold is the better
point estimate and wins every offset, but its paired daily mean return is not
distinguishable from the B hold's at conventional significance. No live change;
the 252-session forward record remains the out-of-sample arbiter.**

This is the result of
`installed-rule-significance-preregistration-2026-11-02.md`, run after the note
was committed. It is a secondary analysis of the two frozen 25 bp scorecard
payloads; no new simulation, no live file and no rule change.

## The result

All sessions, 25 bp, 2,957 paired sessions, median offset:

| comparison | mean | Newey-West t (lag 20) | 95% month-block bootstrap |
|---|---:|---:|---:|
| A hold minus B hold | **+0.77 bp/day** | **1.02** | −0.73 .. +2.25 bp/day |
| A hold minus SPY | +0.86 bp/day | 0.85 | −1.14 .. +2.73 bp/day |
| A hold minus QQQ | −1.24 bp/day | −0.82 | −4.15 .. +1.78 bp/day |

The primary gate required a positive mean, t at least 2.0 and a bootstrap lower
bound above zero. The mean is positive, but the t is 1.02 and the interval
crosses zero, so the gate fails.

## What the point estimates say

| line | CAGR | worst drawdown | median Sharpe |
|---|---:|---:|---:|
| A hold (`/2`) | 17.1% | −34.7% | 1.00 |
| B hold (`/1`) | 14.4% | −38.3% | 0.87 |
| SPY | 13.9% | −33.7% | 0.83 |
| QQQ | 19.0% | −35.1% | 0.91 |

The A hold's advantage is a CAGR and risk effect, not a significantly higher
average daily return: it gives up less in the drawdown and compounds a slightly
better daily mean over eleven years. The A hold beats the B hold in **20 of 20
offsets**; the per-offset CAGR difference has a median of +2.76 points and a
worst case of +1.53 points. That unanimity is real, but it is a statement about
the 20 phase offsets of one history, not independent evidence.

## Sub-periods

| window | A minus B mean | HAC t | bootstrap |
|---|---:|---:|---:|
| 2016-2023 | +0.32 bp/day | 0.35 | −1.30 .. +1.88 |
| 2024-2026 | +1.69 bp/day | 0.96 | −1.62 .. +5.43 |

Both windows are positive and neither is significant. The 2024-2026 point
estimate is larger but the sample is shorter and the interval is wider.

## What this means

- The installed A hold is still the best verified configuration by point
  estimate, Sharpe and drawdown, and the owner chose it for the honest-universe
  robustness. Nothing here changes the live rule.
- The claim that it is **statistically distinguishable** from the B hold is not
  supported. The honest statement is: better in every offset and better on
  Sharpe and drawdown, but the daily mean-return difference is within noise.
- The benchmark rows say the same thing: the A hold is not distinguishable from
  SPY on mean daily return, and it does not beat QQQ on mean daily return. Its
  QQQ claim is a Sharpe and drawdown claim, not a CAGR claim.
- The 252-session forward record is now the only out-of-sample evidence that
  can settle the choice. The B hold remains the fallback at the 252-session
  review if the forward record does not support the A boundary.

## Gate fields

| field | value |
|---|---|
| primary mean > 0 | pass (+0.77 bp/day) |
| primary HAC t >= 2.0 | **fail (1.02)** |
| primary bootstrap lower > 0 | **fail (−0.73 bp/day)** |
| offset sign >= 15 of 20 | pass (20 of 20) |
| both sub-period means > 0 | pass (+0.32, +1.69) |
| **verdict** | **FAIL** |

A failure is not retried with a different lag, bootstrap, window or universe
without a new pre-registration saying what changed and why. The next research
step is a separate question, not a re-run of this one.
