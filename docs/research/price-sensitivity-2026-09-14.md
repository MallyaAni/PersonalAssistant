# Price sensitivity, extended — sensitivity analysis, 2026-09-04

**Not a backtest.** One fixed information snapshot (the desktop store's
last session, 2026-09-04), hypothetical prices, and these assumptions:
fundamentals, filings, every other analyst's stance and conviction, the
other names' scores, the engine's volatilities, the regime exposure and
the caps are held at the snapshot. The technical analyst would respond to
a three-session price level in reality; here it does not, by design. The
live rule's expectations-gap blend is not included. The proposed tilt is
disabled everywhere and appears only as a column. Tool:
`backend/cli/market_price_sensitivity.py`; data in the JSON beside this.

Two scenarios per price. **immediate**: the price is at the level on the
last session only, so the carried value stance is what persistence left
from the prior sessions. **persisted**: the price has sat at the level
for the rule's three sessions, so the stance the rank implies is the
stance carried.

Columns: P/S; cheap = log distance of P/S below the side's median; the
value rank across the book; the stance the rank implies / the stance
carried; the rank conviction (sign × |2·rank−1|^½); the bounded magnitude
(tanh of cheap over the book's median |cheap| that session); votes and
value's share of them; grade; the summed-conviction score, the same
without value, the book's selection cut, and whether the name clears the
cut without value; the engine weight (inverse volatility), the grade
multiplier, the target, the target if the tilt were on, dollars on
100,000, and the binding constraint.

### ORCL

Hard gates: in_book yes, price_known yes, volatility_known yes, valuation_data yes, regime_exposure_positive yes. Bearish opinions held fixed: fundamental, technical; other stances {'fundamental': -1, 'technical': -1, 'sentiment': 0, 'rotation': 0}.

| scenario | price | P/S | cheap | value rank | implied / carried | rank conviction | magnitude | votes | value share of votes | grade | score | score without value | cut | clears cut without value | engine | mult | target | with tilt 0.5 | dollars | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| immediate | 79.39 (0.50x) | 1.35 | +2.14 | 0.98 | +1 / +1 | +0.98 | +0.99 | -1.0 | -100% | C | +0.424 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| immediate | 111.15 (0.70x) | 1.89 | +1.80 | 0.97 | +1 / +1 | +0.97 | +0.99 | -1.0 | -100% | C | +0.418 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| immediate | 158.78 (1.00x) | 2.69 | +1.45 | 0.94 | +1 / +1 | +0.94 | +0.96 | -1.0 | -100% | C | +0.386 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| immediate | 206.41 (1.30x) | 3.50 | +1.18 | 0.90 | +1 / +1 | +0.89 | +0.93 | -1.0 | -100% | C | +0.340 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| immediate | 238.17 (1.50x) | 4.04 | +1.04 | 0.89 | +1 / +1 | +0.88 | +0.89 | -1.0 | -100% | C | +0.326 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| immediate | 317.56 (2.00x) | 5.39 | +0.75 | 0.83 | +1 / +1 | +0.81 | +0.78 | -1.0 | -100% | C | +0.262 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 79.39 (0.50x) | 1.35 | +2.14 | 0.98 | +1 / +1 | +0.98 | +0.99 | -1.0 | -100% | C | +0.424 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 111.15 (0.70x) | 1.89 | +1.80 | 0.97 | +1 / +1 | +0.97 | +0.99 | -1.0 | -100% | C | +0.418 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 158.78 (1.00x) | 2.69 | +1.45 | 0.94 | +1 / +1 | +0.94 | +0.96 | -1.0 | -100% | C | +0.386 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 206.41 (1.30x) | 3.50 | +1.18 | 0.90 | +1 / +1 | +0.89 | +0.93 | -1.0 | -100% | C | +0.340 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 238.17 (1.50x) | 4.04 | +1.04 | 0.89 | +1 / +1 | +0.88 | +0.89 | -1.0 | -100% | C | +0.326 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
| persisted | 317.56 (2.00x) | 5.39 | +0.75 | 0.83 | +1 / +1 | +0.81 | +0.78 | -1.0 | -100% | C | +0.262 | -0.552 | +1.748 | no | 0.0000 | 0.00 | 0.0000 | 0.0000 | 0 | grade C: not a candidate |
### ADBE

Hard gates: in_book yes, price_known yes, volatility_known yes, valuation_data yes, regime_exposure_positive yes. Bearish opinions held fixed: none; other stances {'fundamental': 0, 'technical': 0, 'sentiment': 1, 'rotation': 0}.

| scenario | price | P/S | cheap | value rank | implied / carried | rank conviction | magnitude | votes | value share of votes | grade | score | score without value | cut | clears cut without value | engine | mult | target | with tilt 0.5 | dollars | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| immediate | 133.26 (0.50x) | 2.01 | +1.74 | 0.93 | +1 / +1 | +0.92 | +0.98 | 2.0 | 50% | A+ | +2.001 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1184 | 10,383 | inverse-volatility weight |
| immediate | 186.56 (0.70x) | 2.81 | +1.40 | 0.93 | +1 / +1 | +0.92 | +0.96 | 2.0 | 50% | A+ | +2.001 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1184 | 10,383 | inverse-volatility weight |
| immediate | 266.51 (1.00x) | 4.02 | +1.05 | 0.86 | +1 / +1 | +0.85 | +0.90 | 2.0 | 50% | A+ | +1.926 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1160 | 10,383 | inverse-volatility weight |
| immediate | 346.46 (1.30x) | 5.22 | +0.78 | 0.72 | +1 / +1 | +0.67 | +0.80 | 2.0 | 50% | A+ | +1.744 | +1.076 | +1.744 | no | 0.1038 | 1.00 | 0.1038 | 0.1097 | 10,383 | inverse-volatility weight |
| immediate | 399.77 (1.50x) | 6.03 | +0.64 | 0.69 | +0 / +1 | +0.61 | +0.72 | 2.0 | 50% | A+ | +1.687 | +1.076 | +1.687 | no | 0.1038 | 1.00 | 0.1038 | 0.1077 | 10,383 | inverse-volatility weight |
| immediate | 533.02 (2.00x) | 8.03 | +0.35 | 0.69 | +0 / +1 | +0.61 | +0.46 | 2.0 | 50% | A+ | +1.687 | +1.076 | +1.687 | no | 0.1038 | 1.00 | 0.1038 | 0.1073 | 10,383 | inverse-volatility weight |
| persisted | 133.26 (0.50x) | 2.01 | +1.74 | 0.93 | +1 / +1 | +0.92 | +0.98 | 2.0 | 50% | A+ | +2.001 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1184 | 10,383 | inverse-volatility weight |
| persisted | 186.56 (0.70x) | 2.81 | +1.40 | 0.93 | +1 / +1 | +0.92 | +0.96 | 2.0 | 50% | A+ | +2.001 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1184 | 10,383 | inverse-volatility weight |
| persisted | 266.51 (1.00x) | 4.02 | +1.05 | 0.86 | +1 / +1 | +0.85 | +0.90 | 2.0 | 50% | A+ | +1.926 | +1.076 | +1.748 | no | 0.1038 | 1.00 | 0.1038 | 0.1160 | 10,383 | inverse-volatility weight |
| persisted | 346.46 (1.30x) | 5.22 | +0.78 | 0.72 | +1 / +1 | +0.67 | +0.80 | 2.0 | 50% | A+ | +1.744 | +1.076 | +1.744 | no | 0.1038 | 1.00 | 0.1038 | 0.1097 | 10,383 | inverse-volatility weight |
| persisted | 399.77 (1.50x) | 6.03 | +0.64 | 0.69 | +0 / +0 | +0.61 | +0.72 | 1.0 | 0% | A | +1.687 | +1.076 | +1.687 | no | 0.1038 | 0.75 | 0.0779 | 0.0809 | 7,787 | grade multiplier 0.75 |
| persisted | 533.02 (2.00x) | 8.03 | +0.35 | 0.69 | +0 / +0 | +0.61 | +0.46 | 1.0 | 0% | A | +1.687 | +1.076 | +1.687 | no | 0.1038 | 0.75 | 0.0779 | 0.0806 | 7,787 | grade multiplier 0.75 |
### NTAP

Hard gates: in_book yes, price_known yes, volatility_known yes, valuation_data yes, regime_exposure_positive yes. Bearish opinions held fixed: none; other stances {'fundamental': 1, 'technical': 1, 'sentiment': 0, 'rotation': 0}.

| scenario | price | P/S | cheap | value rank | implied / carried | rank conviction | magnitude | votes | value share of votes | grade | score | score without value | cut | clears cut without value | engine | mult | target | with tilt 0.5 | dollars | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| immediate | 92.79 (0.50x) | 2.25 | +1.61 | 0.93 | +1 / +1 | +0.92 | +0.98 | 3.0 | 33% | A | +3.184 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0961 | 8,473 | grade multiplier 0.75 |
| immediate | 129.91 (0.70x) | 3.15 | +1.27 | 0.88 | +1 / +1 | +0.87 | +0.94 | 3.0 | 33% | A | +3.131 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0946 | 8,473 | grade multiplier 0.75 |
| immediate | 185.59 (1.00x) | 4.50 | +0.92 | 0.73 | +1 / +1 | +0.69 | +0.85 | 3.0 | 33% | A | +2.945 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0892 | 8,473 | grade multiplier 0.75 |
| immediate | 241.27 (1.30x) | 5.85 | +0.65 | 0.69 | +0 / +1 | +0.61 | +0.73 | 3.0 | 33% | A | +2.871 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0870 | 8,473 | grade multiplier 0.75 |
| immediate | 278.38 (1.50x) | 6.75 | +0.51 | 0.67 | +0 / +1 | +0.59 | +0.62 | 3.0 | 33% | A | +2.851 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0865 | 8,473 | grade multiplier 0.75 |
| immediate | 371.18 (2.00x) | 9.00 | +0.22 | 0.58 | +0 / +1 | +0.40 | +0.30 | 3.0 | 33% | A | +2.655 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0809 | 8,473 | grade multiplier 0.75 |
| persisted | 92.79 (0.50x) | 2.25 | +1.61 | 0.93 | +1 / +1 | +0.92 | +0.98 | 3.0 | 33% | A | +3.184 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0961 | 8,473 | grade multiplier 0.75 |
| persisted | 129.91 (0.70x) | 3.15 | +1.27 | 0.88 | +1 / +1 | +0.87 | +0.94 | 3.0 | 33% | A | +3.131 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0946 | 8,473 | grade multiplier 0.75 |
| persisted | 185.59 (1.00x) | 4.50 | +0.92 | 0.73 | +1 / +1 | +0.69 | +0.85 | 3.0 | 33% | A | +2.945 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0892 | 8,473 | grade multiplier 0.75 |
| persisted | 241.27 (1.30x) | 5.85 | +0.65 | 0.69 | +0 / +0 | +0.61 | +0.73 | 2.0 | 0% | A | +2.871 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0870 | 8,473 | grade multiplier 0.75 |
| persisted | 278.38 (1.50x) | 6.75 | +0.51 | 0.67 | +0 / +0 | +0.59 | +0.62 | 2.0 | 0% | A | +2.851 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0865 | 8,473 | grade multiplier 0.75 |
| persisted | 371.18 (2.00x) | 9.00 | +0.22 | 0.58 | +0 / +0 | +0.40 | +0.30 | 2.0 | 0% | A | +2.655 | +2.260 | +1.748 | yes | 0.1130 | 0.75 | 0.0847 | 0.0809 | 8,473 | grade multiplier 0.75 |
### SNDK

Hard gates: in_book yes, price_known yes, volatility_known yes, valuation_data yes, regime_exposure_positive yes. Bearish opinions held fixed: none; other stances {'fundamental': 1, 'technical': 1, 'sentiment': 1, 'rotation': 0}.

| scenario | price | P/S | cheap | value rank | implied / carried | rank conviction | magnitude | votes | value share of votes | grade | score | score without value | cut | clears cut without value | engine | mult | target | with tilt 0.5 | dollars | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| immediate | 870.00 (0.50x) | 3.55 | +1.15 | 0.87 | +1 / +1 | +0.86 | +0.91 | 4.0 | 25% | A+ | +3.285 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0462 | 4,130 | inverse-volatility weight |
| immediate | 1218.00 (0.70x) | 4.97 | +0.82 | 0.73 | +1 / +1 | +0.69 | +0.80 | 4.0 | 25% | A+ | +3.114 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0435 | 4,130 | inverse-volatility weight |
| immediate | 1740.00 (1.00x) | 7.10 | +0.46 | 0.75 | +1 / +1 | +0.70 | +0.56 | 4.0 | 25% | A+ | +3.131 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0437 | 4,130 | inverse-volatility weight |
| immediate | 2262.00 (1.30x) | 9.24 | +0.20 | 0.61 | +0 / +1 | +0.48 | +0.27 | 4.0 | 25% | A+ | +2.907 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0403 | 4,130 | inverse-volatility weight |
| immediate | 2610.00 (1.50x) | 10.66 | +0.05 | 0.61 | +0 / +1 | +0.47 | +0.07 | 4.0 | 25% | A+ | +2.894 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0401 | 4,130 | inverse-volatility weight |
| immediate | 3480.00 (2.00x) | 14.21 | -0.20 | 0.55 | +0 / +1 | +0.33 | -0.27 | 4.0 | 25% | A+ | +2.757 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0380 | 4,130 | inverse-volatility weight |
| persisted | 870.00 (0.50x) | 3.55 | +1.15 | 0.87 | +1 / +1 | +0.86 | +0.91 | 4.0 | 25% | A+ | +3.285 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0462 | 4,130 | inverse-volatility weight |
| persisted | 1218.00 (0.70x) | 4.97 | +0.82 | 0.73 | +1 / +1 | +0.69 | +0.80 | 4.0 | 25% | A+ | +3.114 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0435 | 4,130 | inverse-volatility weight |
| persisted | 1740.00 (1.00x) | 7.10 | +0.46 | 0.75 | +1 / +1 | +0.70 | +0.56 | 4.0 | 25% | A+ | +3.131 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0437 | 4,130 | inverse-volatility weight |
| persisted | 2262.00 (1.30x) | 9.24 | +0.20 | 0.61 | +0 / +0 | +0.48 | +0.27 | 3.0 | 0% | A+ | +2.907 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0403 | 4,130 | inverse-volatility weight |
| persisted | 2610.00 (1.50x) | 10.66 | +0.05 | 0.61 | +0 / +0 | +0.47 | +0.07 | 3.0 | 0% | A+ | +2.894 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0401 | 4,130 | inverse-volatility weight |
| persisted | 3480.00 (2.00x) | 14.21 | -0.20 | 0.55 | +0 / +0 | +0.33 | -0.27 | 3.0 | 0% | A+ | +2.757 | +2.428 | +1.748 | yes | 0.0413 | 1.00 | 0.0413 | 0.0380 | 4,130 | inverse-volatility weight |

## Whole-book repricing

Every close × multiplier on the last three sessions, fundamentals
unchanged, volatilities held.

| name | multiplier | price | P/S | value rank | rank conviction | magnitude | grade | target | with tilt 0.5 | dollars | shares |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ORCL | 1.00 | 158.78 | 2.69 | 0.94 | +0.94 | +0.96 | C | 0.0000 | 0.0000 | 0 | 0.00 |
| ORCL | 1.50 | 238.17 | 4.04 | 0.94 | +0.94 | +0.96 | C | 0.0000 | 0.0000 | 0 | 0.00 |
| ORCL | 0.70 | 111.15 | 1.89 | 0.94 | +0.94 | +0.96 | C | 0.0000 | 0.0000 | 0 | 0.00 |
| ADBE | 1.00 | 266.51 | 4.02 | 0.86 | +0.85 | +0.90 | A+ | 0.1038 | 0.1160 | 10,383 | 38.96 |
| ADBE | 1.50 | 399.77 | 6.03 | 0.86 | +0.85 | +0.90 | A+ | 0.1038 | 0.1160 | 10,383 | 25.97 |
| ADBE | 0.70 | 186.56 | 2.81 | 0.86 | +0.85 | +0.90 | A+ | 0.1038 | 0.1160 | 10,383 | 55.66 |
| NTAP | 1.00 | 185.59 | 4.50 | 0.73 | +0.69 | +0.85 | A | 0.0847 | 0.0892 | 8,473 | 45.66 |
| NTAP | 1.50 | 278.38 | 6.75 | 0.73 | +0.69 | +0.85 | A | 0.0847 | 0.0892 | 8,473 | 30.44 |
| NTAP | 0.70 | 129.91 | 3.15 | 0.73 | +0.69 | +0.85 | A | 0.0847 | 0.0892 | 8,473 | 65.22 |
| SNDK | 1.00 | 1740.00 | 7.10 | 0.75 | +0.70 | +0.56 | A+ | 0.0413 | 0.0437 | 4,130 | 2.37 |
| SNDK | 1.50 | 2610.00 | 10.66 | 0.75 | +0.70 | +0.56 | A+ | 0.0413 | 0.0437 | 4,130 | 1.58 |
| SNDK | 0.70 | 1218.00 | 4.97 | 0.75 | +0.70 | +0.56 | A+ | 0.0413 | 0.0437 | 4,130 | 3.39 |

## What the trace shows

1. **Immediate versus persisted.** Within a session no price move changes
   a grade; only after three sessions at the level does a rank that
   crossed 0.7 take the value vote away. Where that happens the grade
   steps down and the weight follows the grade step, not the price.
2. **How much value already contributes.** Through the vote it is one
   stance in four and a half; through the score it is one conviction
   among five, and the "clears cut without value" column says whether
   the other analysts alone would have selected the name; through sizing
   it contributes nothing, because the engine weight is inverse
   volatility times a grade step. The tilt column is what a
   conviction-proportional size would do, within the book only.
3. **Whole-book repricing leaves every allocation unchanged.** A uniform
   move keeps every P/S distance from the side's median, every rank,
   every conviction and every magnitude the same, so votes, grades,
   selection, the engine weights and the gross-restored tilt are all
   identical; only the share count changes. The architecture is entirely
   relative: it has no notion of the book being expensive or cheap as a
   whole. The one place a level could enter is the realised-volatility
   target, which is held here.
4. **The magnitude input** keeps what the rank throws away. A halving
   adds log 2 to every name's distance; the cheapest name, saturated at a
   rank near 1, still moves in magnitude. It is bounded, scale-free
   across sessions (the scale is the book's own median distance that
   day), and it is a valuation magnitude, not an expected return: nothing
   in it says whether or how fast a multiple reverts, and it must not be
   read as one until calibrated on untouched sessions.

## Hard gates and bearish opinions, separated

Hard gates are facts that make a name untradeable or unmeasurable
regardless of anyone's view: not in the book, no price, no realised
volatility, no filed revenue or share count for the multiples, a regime
exposure of zero, the event pause, and the name and theme caps. Bearish
opinions are analysts' views: a falling trend, low reported growth, a
downbeat release, an expensive multiple. Today the grade rule treats two
bearish opinions like a gate (votes below 0.5 make a C, which is not a
candidate) and one bearish core opinion like a partial gate (the veto
caps at B). An attractive valuation can only ever add one vote.

## One minimal candidate design

Keep every analyst, the grades, the engine, the caps and the dashboard as
they are. Add one bounded input and change two decisions:

- **Input.** `m` = the value magnitude above, from the valuation analyst's
  own `cheap_vs_side` evidence, computed each session from that session's
  cross-section. No fit, no parameter beyond the tanh scale, which is the
  book's median distance that day.
- **Selection.** The score that orders candidates becomes
  `S = Σ w·conviction` with the value leg replaced by
  `w_value · (conviction + m) / 2`: half the rank, half the magnitude.
  Candidacy becomes `hard gates pass AND (grade above C OR S ≥ S_cut)`,
  where `S_cut` is the score of the weakest name the grade rule already
  admits that session, so the candidate set is the same size on an
  ordinary day and a name blocked only by bearish *opinions* can enter
  when its total conviction, magnitude included, is at least as strong as
  the weakest admitted name. The veto stays as a size limiter (the B
  multiplier), never as a candidacy block; hard gates stay absolute.
- **Sizing.** The engine's weight times the grade step, then
  `tilt_by_conviction` on `m` at a single fixed tilt of 0.5, gross
  restored, cap re-applied. Disabled until measured.

Assumptions, stated: cheapness against the side's median P/S is the
attractiveness proxy; the magnitude's scale is the book's own dispersion;
the equal split between rank and magnitude is a choice, not a fit; the
weakest-admitted-name cut ties candidacy to the existing rule's own
threshold rather than to a new number.

## Evaluation plan

The desk's own simulator (`simulate.run`) from 2018-06 with costs, the
rule against four variants, no sweep: (a) selection with the magnitude
score only; (b) plus the candidacy rule; (c) plus the tilt at 0.5; (d) the
tilt alone on today's selection, as the control that separates
"price-sensitive selection" from "more of what was already selected".
Report each at the rule's volatility, by year, with drawdown, turnover,
average cash and gross, and excess against SPY and the equal-weight
universe. Accept only a variant that beats the rule at matched volatility
in most years without a deeper drawdown, and then only into the shadow
track beside the rule, never straight to production. Before that run,
nothing here touches production: the tilt is off, and the score and
candidacy changes exist only in this note.
