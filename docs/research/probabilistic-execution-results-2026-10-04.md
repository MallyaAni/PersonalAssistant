# Stock-conditioned execution probabilities

The research branch now implements a probabilistic buy/sell timing component.
It uses each stock's existing volatility and completed intraday-path forecasts,
then evaluates the distribution of waiting advantages at the funded trade size. It does
not set size by multiplying a probability, or use a fixed percentage entry.
Production is unchanged. Reliable live replacement remains unverified.

The supplied-input implementation passed 61 native and 61 pinned-image cases,
with no skips. A separate saved-artifact verifier passed 25 corruption cases in
both runtimes and authenticated the actual diagnostic without refitting models
or replaying accounts. A reproduced early-close boundary was corrected before
the diagnostic: a later regular open must precede the official session close.
One verifier source-list omission was reproduced and corrected by adding the
actual hashing/writer dependency; existing acceptance assertions were retained.

The diagnostic reused the two frozen monthly 15-minute mean heads and their
duration-matched second moment. Per-stock monthly residual distributions use
only preceding mature OOS observations, at least 252 distinct sessions within
756 session indices, equal total weight per date, and the August 17 freeze.
Original 10-session model purging remains unchanged. Calibration outcomes are
the actual same-session 15-minute waiting advantage, conservatively known at
the session close. Terminal clocks and benchmarks remain excluded.

There were 3,812,089 causal opportunities in the 2018-02-01–2026-09-30 report
window, across 94 stocks. Boosting had 3,253,836 available estimates; Ridge had
3,253,831. Cold starts and invalid/missing moments remain explicit. The full
2015 preparation grid contains 4,553,425 causal opportunities, including the
earlier model warm-up history; it is a different denominator.

Lower Brier is better. Each reference uses the exact same historical residual
rows and scoring support as its corresponding learned estimate. Metrics give
each measured session equal total weight; bars are not independent trials.

| Method | Full-period Brier | Paired reference Brier | 10–90 interval coverage |
|---|---:|---:|---:|
| Boosting | 0.251726 | 0.249846 | 81.24% |
| Ridge | 0.251310 | 0.249846 | 81.07% |

Both estimates have worse Brier than their historical reference in every fixed
aggregate window: 2018–20, 2021–26 and the explicitly reused recent slice.
Each method has one contradicted empirical certainty in the full period, so
its full-period log loss is infinite, represented by a null finite value and
an explicit count. No probability clipping or outcome-based tuning was used.
Near 80% interval coverage does not establish conditional confidence or useful
directional skill. Positive probability describes a lower later buy price;
it is not a probability of holding profit or an instruction to buy.

This measures forecast quality, not portfolio gain. It does not establish or
reject the full distribution's funded execution utility. The next economic
comparison must keep the allocation rule fixed to isolate timing, then test
jointly funded sizing and timing against SPY/QQQ. The earlier verified factorial
study already showed sizing can obscure timing: at 10 bp the same-allocation
timing contrast added 13.16 pp paired median cumulative gain, while changing
sizing with the original gate lost 212.86 pp. Those are overlapping component
schedules, not independent trials or exact live-policy reconstruction.

Historical grades/universe are current-vintage reconstructions. SIP history is
delayed retrospective evidence, with session-scaled synthetic next-open prices,
not contemporaneous IEX receipts or broker/midpoint fills. Earlier studies used
this history; the recent slice is not a fresh untouched holdout. No favorable
stock, method, window or cost was selected for deployment.

Evaluated source: 4e77c48163f1bb5ff1e610d42c9a46a12d704bf3.
Frozen protocol: 89887d34. The 2340-file source manifest is
188be7401b2e8f06a1ce44aa84c670383acbfdd1ad0a997686c0ab791164c23c.
Original report: 67084f65042a1defe87cfc5372ef5dd1de9e18e86a50b8c9d94b9d223681bf34.
Independent proof: c319fa57d520ae28189ba2158d2dc0b6f326f7dad1c671b6c3069ad9c34c2556.
Original report and proof are retained in the accompanying JSON.
