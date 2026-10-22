# Candidate: the valuation analyst carries three votes — 2026-10-22

Status: IMPLEMENTED on branch `value-weighted-grading`, tested, NOT merged,
NOT installed. Awaiting the owner's word. Not a bound-source release
(`grading.py` is not pinned by the trading approval), but it changes every
grade the desk writes, so it is held to the same bar: evidence first, the
owner decides, then merge and deploy; the first grades under it are the
next nightly's.

## The change

`grading.ANALYST_WEIGHTS["value"]` goes from 1 to 3; the other analysts
stay at 1, rotation at ½. `analyst_weights` scales the set to the same
total as equal votes, so the grade thresholds keep their meaning:
fundamental, technical and sentiment carry 0.69 each, valuation 2.08,
rotation 0.35. Consequences on one name: a bullish valuation alone now
reaches A; growth with trend alone stops at B (1.38, under the 1.5 the
f-and-t rule asks for); a bearish valuation against three bullish analysts
drops the grade to C (0.0 votes), where it was the vetoed B. The desk guide
text and three unit tests say so (`test_trading_grading`,
`test_market_holdings`).

## Why valuation

Per-analyst rank IC of the score against the next sixty sessions' excess
return over SPY, on every S&P 500 member point in time
(`~/dsv41/universe/analyst_ic.py`, output `analyst_ic.json`):

| year | fundamental | technical | sentiment (coverage) | valuation | blended |
|---|---|---|---|---|---|
| 2017 | +0.13 | +0.03 | +0.13 (0.43) | +0.14 | +0.14 |
| 2018 | +0.01 | +0.01 | −0.04 (0.43) | −0.03 | −0.01 |
| 2019 | +0.02 | −0.04 | +0.02 (0.45) | −0.03 | −0.02 |
| 2020 | −0.01 | +0.02 | −0.05 (0.44) | +0.02 | +0.02 |
| 2021 | +0.03 | −0.08 | −0.04 (0.45) | +0.09 | +0.01 |
| 2022 | −0.03 | 0.00 | −0.01 (0.45) | +0.05 | +0.01 |
| 2023 | +0.02 | −0.01 | +0.02 (0.45) | +0.03 | +0.03 |
| 2024 | 0.00 | +0.01 | −0.01 (0.46) | +0.01 | +0.01 |
| 2025 | 0.00 | +0.02 | −0.01 (0.46) | +0.11 | +0.06 |
| 2026 | +0.01 | −0.05 | +0.02 (0.47) | +0.08 | +0.02 |

Valuation (which carries the expectations gap when the live desk runs) is
the only analyst positive in every year since 2020 and the only one with a
reading above +0.05 since 2017. Its coverage reached 0.9 of names in 2019
as the levels filled in; before that its vote was mostly absent. The
fundamental analyst was strong in 2015 and 2017 and has been ~0 since;
technical ~0 or negative; sentiment covers under half the names and reads
~0.

## What the grade change does to the rule

Scorecard, 25 bp, 20 offsets, medians (`~/dsv41/universe/regrade.py`;
payloads `regrade_*.json`):

| grading | universe | CAGR | worst DD | Sharpe | 2016–2023 | 2024–2026 |
|---|---|---|---|---|---|---|
| equal votes, A cut | book | 22.0% | −35.2% | 0.98 | 23.1% | 27.9% |
| **valuation ×3, A cut** | book | **25.0%** | −34.1% | **1.11** | 26.0% | 32.4% |
| equal votes, A cut | S&P 500 PIT | 15.3% | −37.3% | 0.91 | 13.1% | 23.8% |
| **valuation ×3, A cut** | S&P 500 PIT | **17.1%** | −34.7% | **1.00** | 14.8% | 26.0% |
| equal votes, B cut (installed) | book | 26.0% | −34.3% | 1.11 | 25.0% | 39.9% |
| valuation ×3, B cut | book | 26.6% | −33.4% | 1.11 | 27.5% | 34.8% |
| equal votes, B cut | S&P 500 PIT | 13.9% | −38.4% | 0.84 | 13.3% | 18.7% |
| valuation ×3, B cut | S&P 500 PIT | 14.4% | −38.3% | 0.87 | 14.0% | 19.4% |
| SPY | | 13.9% | −33.7% | 0.83 | 13.2% | 20.4% |

Year by year (A cut, book): valuation ×3 beats equal votes in 9 of 11 years
(not 2016, 2018); on the S&P 500, 9 of 11 (not 2018, 2019). Weights 4 and 5
score the same as 3; 2 keeps half the gain; sentiment dropped loses it
(21.0%); fundamental-and-value only is worse (18.8%).

## The walk-forward test (the one the ridge set failed)

`grading.py` records a ridge fit toward value-heavy weights that looked
better across the whole history and worse walk-forward from 2018. The same
test here: each year from 2019, the weight chosen from {1, 2, 3, 4} by the
Sharpe of the years before it, scored on that year (`/tmp/wf.py`, from the
payloads' median-offset curves):

| | chosen weights | walk-forward 2019–2026 | equal votes 2019–2026 |
|---|---|---|---|
| book, A cut | 2 in 2019, then 3 | 23.8% / Sharpe 0.95 / DD −33.4% | 19.6% / 0.82 / −34.1% |
| S&P 500, A cut | 4 throughout | 18.3% / 0.98 / −31.5% | 16.0% / 0.88 / −31.8% |

The choice settles and stays; the gain is there without the benefit of
hindsight on the weight. The grid itself was chosen after seeing the
all-window results — a weaker claim than a grid fixed in advance — but the
surface is a plateau from 3 up, not a knife edge.

## What changes on the board

On the 2026-10-21 close, 18 of 94 grades move (`grade_diff.log`): ACN,
ADBE, APLD, GEN, GLXY, IBM, ORCL, Q, TRMB C→B; ANET, FTNT, MRVL, PLTR B→C;
ALAB, GEV, SNPS, TSM A→B; INTC B→A. A or better: 8+3 names → 5+3; over the
history 14.2 → 11.8 names a session at A or better. Under the installed B
cut the book widens slightly (32 → 37 names at B or better today).

## Install

Merge `value-weighted-grading` to main, deploy (unit gate), nothing to
install under the trading approval. The next nightly (19:30 ET) writes the
first record under it; charts' replay (`market_policy_replay_research`)
regrades the whole history with the live engine, so rerun it after the
nightly. The desk guide text names the weights.
