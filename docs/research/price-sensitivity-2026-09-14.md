# Price sensitivity of grade and target weight — sensitivity analysis, 2026-09-04

**This is a sensitivity analysis, not a backtest.** One fixed, dated
information snapshot: the desktop store's last session (2026-09-04), its
filed fundamentals, every other analyst's stance and conviction, the other
names' scores, the realised volatilities and the regime. For each name only
its own close on that session is moved, from half to double. The valuation
analyst is recomputed on the whole book at each price (its cheapness is a
cross-sectional rank), the name is re-graded with the other analysts held
fixed, the summed-conviction score is rebuilt, and the desk's own sizing
runs on the original panel's volatilities, so the risk assumptions do not
move with the price. The live rule's expectations-gap blend is not included
here; it halves the value rank's weight and adds a price-implied growth
term, and does not change the shape of what follows. Tool:
`backend/cli/market_price_sensitivity.py`; data beside this note.

## The path, and where price enters

price → market cap = price × shares → price-to-sales (and P/E, P/B) →
cheapness against the side, size-neutral → **percentile rank across the
book** → value **stance** (+1 in the top 30% of ranks, −1 in the bottom
30%, else 0; a change must hold three sessions) and value **conviction**
(sign × |2·rank − 1|^½) → **votes** = Σ stances (rotation ½) → **grade**
(B at ≥ 0.5 votes; A at ≥ 2, or a bullish release with ≥ 1, or bullish
fundamental and technical with ≥ 1.5; A+ a bullish release with ≥ 2; any
bearish core analyst caps at B) → **score** = Σ convictions → **candidacy**
(grade above C) and **selection** (top tenth of the book by score) →
**engine weight** = inverse realised volatility, capped at 15% per name and
volatility-targeted → × **grade multiplier** (A+ 1.0, A 0.75, B 0.5) ×
regime exposure → the tightening tilt → the cap → dollars.

### ORCL — other analysts held at {'fundamental': -1, 'technical': -1, 'sentiment': 0, 'rotation': 0}

| price | P/S | P/E | value rank | stance now / held | value conviction | votes | grade | score | cut | engine | mult | target | dollars | target with tilt 0.5 | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 79.39 (0.50x) | 1.35 | 13.3 | 0.98 | +1 / +1 | +0.98 | -1.0 | C | +0.424 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 127.02 (0.80x) | 2.15 | 21.2 | 0.95 | +1 / +1 | +0.94 | -1.0 | C | +0.393 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 150.84 (0.95x) | 2.56 | 25.2 | 0.94 | +1 / +1 | +0.94 | -1.0 | C | +0.386 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 158.78 (1.00x) | 2.69 | 26.6 | 0.94 | +1 / +1 | +0.94 | -1.0 | C | +0.386 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 190.54 (1.20x) | 3.23 | 31.9 | 0.93 | +1 / +1 | +0.93 | -1.0 | C | +0.380 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 238.17 (1.50x) | 4.04 | 39.8 | 0.89 | +1 / +1 | +0.88 | -1.0 | C | +0.326 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |
| 317.56 (2.00x) | 5.39 | 53.1 | 0.83 | +1 / +1 | +0.81 | -1.0 | C | +0.262 | +1.748 | 0.0000 | 0.00 | 0.0000 | 0 | 0.0000 | grade C: not a candidate |

### ADBE — other analysts held at {'fundamental': 0, 'technical': 0, 'sentiment': 1, 'rotation': 0}

| price | P/S | P/E | value rank | stance now / held | value conviction | votes | grade | score | cut | engine | mult | target | dollars | target with tilt 0.5 | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 133.26 (0.50x) | 2.01 | 7.8 | 0.93 | +1 / +1 | +0.92 | 2.0 | A+ | +2.001 | +1.748 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1184 | inverse-volatility weight |
| 213.21 (0.80x) | 3.21 | 12.4 | 0.90 | +1 / +1 | +0.89 | 2.0 | A+ | +1.968 | +1.748 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1173 | inverse-volatility weight |
| 253.18 (0.95x) | 3.82 | 14.8 | 0.86 | +1 / +1 | +0.85 | 2.0 | A+ | +1.926 | +1.748 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1160 | inverse-volatility weight |
| 266.51 (1.00x) | 4.02 | 15.5 | 0.86 | +1 / +1 | +0.85 | 2.0 | A+ | +1.926 | +1.748 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1160 | inverse-volatility weight |
| 319.81 (1.20x) | 4.82 | 18.6 | 0.75 | +1 / +1 | +0.71 | 2.0 | A+ | +1.787 | +1.748 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1113 | inverse-volatility weight |
| 399.77 (1.50x) | 6.03 | 23.3 | 0.69 | +0 / +1 | +0.61 | 2.0 | A+ | +1.687 | +1.687 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1077 | inverse-volatility weight |
| 533.02 (2.00x) | 8.03 | 31.1 | 0.69 | +0 / +1 | +0.61 | 2.0 | A+ | +1.687 | +1.687 | 0.1038 | 1.00 | 0.1038 | 10,383 | 0.1073 | inverse-volatility weight |

### NTAP — other analysts held at {'fundamental': 1, 'technical': 1, 'sentiment': 0, 'rotation': 0}

| price | P/S | P/E | value rank | stance now / held | value conviction | votes | grade | score | cut | engine | mult | target | dollars | target with tilt 0.5 | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 92.79 (0.50x) | 2.25 | 12.2 | 0.93 | +1 / +1 | +0.92 | 3.0 | A | +3.184 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0961 | grade multiplier 0.75 |
| 148.47 (0.80x) | 3.60 | 19.4 | 0.81 | +1 / +1 | +0.79 | 3.0 | A | +3.051 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0922 | grade multiplier 0.75 |
| 176.31 (0.95x) | 4.28 | 23.1 | 0.77 | +1 / +1 | +0.73 | 3.0 | A | +2.988 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0904 | grade multiplier 0.75 |
| 185.59 (1.00x) | 4.50 | 24.3 | 0.73 | +1 / +1 | +0.69 | 3.0 | A | +2.945 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0892 | grade multiplier 0.75 |
| 222.71 (1.20x) | 5.40 | 29.2 | 0.71 | +1 / +1 | +0.65 | 3.0 | A | +2.909 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0881 | grade multiplier 0.75 |
| 278.38 (1.50x) | 6.75 | 36.5 | 0.67 | +0 / +1 | +0.59 | 3.0 | A | +2.851 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0865 | grade multiplier 0.75 |
| 371.18 (2.00x) | 9.00 | 48.6 | 0.58 | +0 / +1 | +0.40 | 3.0 | A | +2.655 | +1.748 | 0.1130 | 0.75 | 0.0847 | 8,473 | 0.0809 | grade multiplier 0.75 |

### SNDK — other analysts held at {'fundamental': 1, 'technical': 1, 'sentiment': 1, 'rotation': 0}

| price | P/S | P/E | value rank | stance now / held | value conviction | votes | grade | score | cut | engine | mult | target | dollars | target with tilt 0.5 | binding |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 870.00 (0.50x) | 3.55 | 4.6 | 0.87 | +1 / +1 | +0.86 | 4.0 | A+ | +3.285 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0462 | inverse-volatility weight |
| 1392.00 (0.80x) | 5.68 | 7.4 | 0.79 | +1 / +1 | +0.76 | 4.0 | A+ | +3.189 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0446 | inverse-volatility weight |
| 1653.00 (0.95x) | 6.75 | 8.8 | 0.77 | +1 / +1 | +0.74 | 4.0 | A+ | +3.164 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0443 | inverse-volatility weight |
| 1740.00 (1.00x) | 7.10 | 9.2 | 0.75 | +1 / +1 | +0.70 | 4.0 | A+ | +3.131 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0437 | inverse-volatility weight |
| 2088.00 (1.20x) | 8.53 | 11.1 | 0.69 | +0 / +1 | +0.61 | 4.0 | A+ | +3.039 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0424 | inverse-volatility weight |
| 2610.00 (1.50x) | 10.66 | 13.8 | 0.61 | +0 / +1 | +0.47 | 4.0 | A+ | +2.894 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0401 | inverse-volatility weight |
| 3480.00 (2.00x) | 14.21 | 18.5 | 0.55 | +0 / +1 | +0.33 | 4.0 | A+ | +2.757 | +1.748 | 0.0413 | 1.00 | 0.0413 | 4,130 | 0.0380 | inverse-volatility weight |

## Where the price sensitivity is lost

1. **Candidacy by vote count.** ORCL: value votes +1 at every price from 79
   to 318, because it is among the cheapest names in the book at all of
   them, but fundamental and technical are −1 each, so the votes are −1,
   the grade is C, and the target is zero over a four-fold price range.
   Value is one vote in four and a half; no price can carry a name past
   two bearish analysts. The veto would cap it at B even if it could.
2. **Rank saturation.** The cheapness is a percentile rank across the book.
   A name far cheaper than its peers stays in the top 30% however its
   price moves: ORCL's rank goes 0.98 → 0.83 over a doubling; ADBE's
   0.93 → 0.69. Most of the price move never reaches the stance.
3. **A binary stance with three-session persistence.** ADBE's rank crosses
   the 0.7 line at 1.5×, NTAP's at 1.3×, SNDK's at 1.2×, and the stance the
   rule carries stays +1 in every row: a single session's price cannot
   change a grade, by design.
4. **Selection is a cut, not a slope.** A name above the book's cut (here
   +1.748, the ninth-best score) takes its full engine weight whether it
   clears the cut by a mile or a hair.
5. **The engine weight ignores the score.** Within the book a name's weight
   is its inverse realised volatility times a grade step. ADBE at 133 and
   ADBE at 533 both get 10.38%; NTAP 8.47% at 93 and at 371; SNDK 4.13%
   throughout. The last of the price information is discarded here.
6. **Grade multipliers are three steps**, and the conviction's square-root
   shape compresses the extremes mildly (rank 0.98 → 0.98, 0.83 → 0.81).

## The smallest correction, implemented and tested, off in production

`risk.tilt_by_conviction` (`ATTRACTIVENESS_TILT = 0.0`): after the grade
and regime multipliers, scale each selected name's target by
(1 + tilt × value conviction), restore the gross the grade and regime
chose, and re-apply the name cap. Nothing else in the path changes; at
tilt 0 the book is today's exactly. At tilt 0.5 on this snapshot the
weights become continuous in price: ADBE 11.84% at half price → 10.73% at
double, NTAP 9.61% → 8.09%, SNDK 4.62% → 3.80%, gross unchanged. Tests
cover the identity at zero, the ordering, the gross and the cap.

What it does not do: it cannot make ORCL a candidate. Points 1 to 3 are
the grading rule's own choices (votes, ranks, persistence), and changing
them is a rule change to be measured walk-forward before adoption, not a
correction. The tilt is the one change that keeps the grade rule, the
engine and the caps as they are and lets the size follow the price within
the book. Its value is unmeasured; it goes nowhere near production until
the simulator has run it at matched volatility.
