# Cash funding audit

The cash-at-fill correction removes unmodeled borrowing; it is an accounting
repair, not evidence of a new return edge. The same reconstructed decisions,
selected universe and FOMC policy were replayed from January 2021 through
September 11, 2026. No broker orders or live position state were changed.

| Accounting / cost per side | Total return | CAGR | Worst drawdown | Negative-cash sessions | Maximum gross exposure |
| --- | ---: | ---: | ---: | ---: | ---: |
| Legacy / 10 bp | +678.54% | 43.64% | 33.20% | 220 / 1429 | 131.79% |
| Cash at fill / 10 bp | +552.33% | 39.23% | 30.85% | 0 / 1429 | 100.00% |
| Legacy / 25 bp | +643.14% | 42.47% | 33.60% | 220 / 1429 | 132.00% |
| Cash at fill / 25 bp | +526.70% | 38.25% | 31.20% | 0 / 1429 | 100.00% |

Each run completed 72 rebalances. Lower returns after removing borrowing are
expected; the earlier curve cannot be presented as a cash-funded result.
The selected June 18–September 11 evaluation period contains only 59 return
sessions and one completed FOMC meeting. Cash-at-fill returns were +2.80% at
10 bp and +2.54% at 25 bp, with respective drawdowns 6.61% and 6.64%. This
does not establish a causal effect of changing Fed communication.

The simulator now scales simultaneous buy quantities proportionally to cash
after costs. Same-time completed sales can fund purchases; closing sales cannot
fund that morning's buys. Unpriced holdings remain held. FOMC restoration does
not borrow to replace sold shares. An exhausted cash budget releases the cycle
instead of permanently blocking regular rebalancing. The paper path separately
records any whole-share remainder as cash-limited and unbought, after pending
orders resolve; missing prices preserve the unresolved cycle.

The unit acceptance covers opening gaps, cash conservation after fees,
competition for funding, future sale proceeds, missing prices, and restoration
completion with durable readback. The old strict funding xfail is now a passing
regression. The dashboard distinguishes new `cash-at-fill-v1` artifacts from
legacy curves; deploying code does not relabel an old stored performance curve.

Limitations: historical grades are reconstructed with the selected universe and
available historical inputs, not an untouched live holdout. Fills are fractional
and deterministic, with immediate access to completed sale proceeds. Settlement
delays, spreads, impact, liquidity limits, broker rejection and whole-share
rounding require a separate execution replay. Costs are assumptions. No new
technical entry or exit rule was promoted by this accounting comparison.

Evidence: [machine-readable comparison](cash-funding-audit-2026-09-13.json).
Frozen report SHA-256:
`7994c5df176913209b929e451e75f7700c6009d3bd8b0587ad1f8f5ef7acd582`.
Legacy simulator SHA-256:
`712219fb1b0b59e249f1695fecb6d4842dff9a034013ed62dace22a22a9512ee`.
Corrected simulator SHA-256:
`6be929db208adc7e3f947c558b0b90f2682784a652be7614d646fcdf2ec6e768`.
The final comparison loaded the frozen report and unchanged source files from
the isolated `/tmp/desk-fomc-live-e207` package on Spark1. The first comparison
overlapped source edits and is not used as revision evidence.
