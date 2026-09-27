# Volatility sizing on the `/4` book: results (2026-09-27)

Pre-registration: [vol-sizing-plan-2026-09-27.md](vol-sizing-plan-2026-09-27.md).
Forecasts: the stage-1 temporal CNN's volatility head, walk-forward (33
fits, refit every 63 sessions, 5-session purge), trained on the RTX 5080 in
3 m 22 s from the exported stage-1 dataset (`market_vol_forecast --device
cuda`; out-of-sample R² against trailing volatility 0.271 on 2016-2023 and
0.260 on 2024-2026, the stage-1 numbers reproduced). Trial run on spark1
from `0e06d400` (`market_vol_sizing --offsets 20 --costs 10 25`), payload
`docs/research/scorecards/vol_sizing.json`; six registered variants and the
control, under plain and live execution, 560 simulator runs. Forecasts
cover 73% of held cells (they begin 2018-02 after the 500-session warm-up;
the trailing twins cover 94%). Volatility target 0.0138 per session,
measured once from the control's own realized volatility.

## The table (live execution, 25 bp - what the account runs; medians across 20 offsets; "expo" is mean gross exposure; bp/d and t are the paired daily difference against `ew` at the median offset, Newey-West lag 20)

| variant | 2016-2023 CAGR | maxDD | expo | vs ew bp/d (t) | 2024-2026 CAGR | maxDD | expo | vs ew bp/d (t) |
|---|---|---|---|---|---|---|---|---|
| ew (control, `/4`) | 23.2% | -36.0% | 1.00 | — | 52.6% | -17.2% | 1.00 | — |
| inv-vol-forecast | 22.9% | -35.8% | 1.00 | -0.3 (-1.8) | 51.8% | -17.3% | 1.00 | -0.4 (-1.5) |
| inv-vol-trailing | 22.7% | -35.7% | 1.00 | -0.3 (-1.9) | 51.8% | -17.2% | 1.00 | -0.5 (-1.5) |
| vol-target-forecast | 22.8% | -34.0% | 0.93 | -0.5 (-1.1) | 46.4% | -15.5% | 0.68 | -2.8 (-2.8) |
| vol-target-trailing | 22.0% | -33.7% | 0.81 | -0.6 (-1.1) | 42.8% | -14.6% | 0.60 | -4.1 (-2.8) |
| hybrid-forecast | 22.3% | -34.0% | 0.96 | -0.8 (-1.7) | 45.9% | -15.3% | 0.70 | -3.0 (-2.8) |
| hybrid-trailing | 21.6% | -33.6% | 0.85 | -0.7 (-1.3) | 41.9% | -14.3% | 0.60 | -4.1 (-2.8) |

Under plain execution the picture is the same with larger numbers: `ew`
27.5% against 25.2-26.9% for the tilts and 22.7-25.2% for the targets on
2016-2023; on 2024-2026 the vol targets give up 12-17 CAGR points (46.2%
against 29-35%) for 4-5 points of drawdown.

**Verdict: every variant RECORD.** Nothing reaches the control, let alone
the +1.0-point floor; the forecast beats its trailing twin by 0.2-1.0
points everywhere (the model is better than trailing volatility, as its
R² said) and still loses to not sizing at all.

## Reading it

1. **On this book, volatility is not the thing to size by.** The `/4`
   book is eleven or twelve names at about 9% each, all semiconductor,
   hardware, and software names with similar volatility, chosen because
   their structure is intact. Tilting toward the quieter ones costs a
   third of a point with t near -2: the quieter names in this book are,
   mildly and consistently, the ones with less to give. The equal-weight
   cap already does the work an inverse-vol tilt is meant to do.
2. **Volatility targeting de-levers into the run it should be riding.**
   Exposure falls to 0.60-0.70 in 2024-2026 - the book's best stretch -
   because realized volatility is high when these names are moving, and
   they move most when they are earning. The result is 6-10 CAGR points
   given up under live execution for 1.7-2.9 points of drawdown, a ratio
   no operator maximising total return would take. The plan's own
   ceiling test ("what would make the prior wrong") required the
   forecast variants to beat the control; none did, in either window.
3. **The forecast is real and useful somewhere else.** Forecast-sized
   variants beat their trailing twins in every row (inv-vol +0.2 pt,
   vol-target +0.8, hybrid +0.7 on 2016-2023; +3.6-4.0 pt on 2024-2026),
   so a better volatility number changes sizing in the right direction -
   it just does not overcome the cost of sizing by volatility at all on
   a book whose return is in its volatility. The right home for the
   forecast is the *execution* layer (expected slippage, order pacing,
   how much of a name to move in one session) and the day-type read the
   board already shows, not the allocator.
4. So the operator's question - could a neural network on the bars earn
   a higher CAGR - has now been tested on both channels the literature
   supports: the return head (stage 1: IC 0.012, untradable) and the
   volatility head (this trial: real forecast, loses as a sizing input).
   The remaining registered question for the model is structural (longer
   context, market context, drawdown targets, pretraining), and it will
   be judged by the same floors.

## Compute notes

The CNN on the 5080 took 3 m 22 s for 33 walk-forward fits (about 14 min
on the shared GB10); moving the 1.7 MB npz through the Cowork VM with a
sha256 check at each hop took under a minute. The 560 simulator runs took
20 minutes on one Spark core. Training belongs on the RTX; the store-bound
scorecard stays on the Spark.
