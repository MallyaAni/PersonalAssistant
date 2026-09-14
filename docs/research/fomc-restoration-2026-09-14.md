# FOMC restoration comparison

The adopted rule restores confirmed event reductions after the meeting, within
available cash. A candidate extended the reduced state until SPY's existing
daily and weekly trend readings were both nonnegative. Unknown readings kept
it reduced. This uses the same causal level features as the desk, not a new LLM
prompt or an invented target price.

The pinned September 11, 2026 input cut used the desk's default expectations-gap
inputs and its funded event-lifecycle simulator. The reproduction script and
eight raw result rows are adjacent to this file. On Spark, run the script with
the research environment and the repository on PYTHONPATH; it reads
`~/anios/data/market` and submits no orders. Earlier-period results are a stress
test, not evidence for the user's guidance-removal hypothesis.

| Period / cost | Calendar CAGR | Trend-gated CAGR | Calendar max drawdown | Trend-gated max drawdown |
|---|---:|---:|---:|---:|
| 2021–Sep 11, 2026 / 10 bp | 39.86% | 42.50% | 24.80% | 27.01% |
| 2021–Sep 11, 2026 / 25 bp | 38.46% | 41.19% | 25.18% | 27.36% |

Maximum observed position weight also rose from about 17.5% to 24.4%. Extending
the event changes the rebalance timing, so the return increase is not proof
that the benchmark condition times re-entry better.

The June 18–September 11 slice has **one completed meeting, July 29**. The two
methods are identical: +1.52% total return at 10 bp and +1.30% at 25 bp. Do not
annualize that small sample into a claim of superiority. These runs restart
the account at each period's start; they are separate comparisons, not a
continuous live-return attribution. The data cut uses currently stored data,
which is not a complete historical vintage archive.

Decision: retain the adopted restoration policy. The candidate has a mixed
historical tradeoff and no distinguishing evidence in the requested newer
period. It is not promoted. The operational missed-reduction recovery is a
separate fix; intraday recovery fills are observed broker outcomes and are not
represented by this next-open simulator.
