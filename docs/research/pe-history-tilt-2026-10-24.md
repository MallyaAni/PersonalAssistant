# Price-aware valuation on the account simulator: the P/E-history tilt (2026-10-24)

The owner asked for a valuation model that makes a stock more attractive to buy
at a certain price, and noted the grades may give too few signals. Ideas were
tested on the account-faithful simulator (`backend/market/policy_book.py`) with
the installed rule (enter at A, hold while B, 1% minimum trade) as baseline.
Research scripts and results: `~/dsv41/valuation/` on spark1.

## Data

- Forward P/E is not available: the store holds no analyst consensus
  estimates (`valuation.py` says so). The closest input, the expectations gap
  (a learned revenue-growth forecast against the growth the price implies), is
  already inside the value analyst.
- From filings, point in time: P/S, P/E (latest quarter x4, positive earnings
  only), P/B, P/S less growth; P/E exists for 60-70% of names graded B or
  better. P/S covers only 7-9% of name-days before 2018.

## A look-ahead bug found on the way

`levels_pit.split_adjusted_shares` applied a split to an older share count only
from the split day, while the stored closes are back-adjusted for every split on
file. Before each later split, market cap read too low by the split factor
(NVDA 40x too cheap before July 2021), mostly for the names that later won and
split. Fixed in the same change (`seen < day <= last session`); 10.4% of
historical grade cells move. The installed rule's backtest falls from 39.4% to
34.8% a year (to 2022 25.0% -> 19.1%); it still beats entering and holding at B
(31.4%, 16.3% to 2022, 68.6% after). Live grades on 2026-10-23 differ in one
name (CEG B -> C).

## Results (split-corrected grades, 10 bp)

| Variant | CAGR | Worst drawdown | Sharpe | 2015-22 | 2023-26 | Entries/yr |
|---|---|---|---|---|---|---|
| Baseline | 34.8% | -27.7% | 1.38 | 19.1% | 73.8% | 65 |
| Extra entries: B names cheap vs own P/S history (3 thresholds) | 34.2-34.9% | -28.8 to -29.4% | 1.36-1.38 | 17.5-18.0% | 74.5-77.7% | 76-84 |
| Extra entries: B names cheap vs own P/E history | 33.8-34.2% | | | 17.7-17.8% | 73.4-75.3% | 77-87 |
| Extra entries: cheap vs peers / for growth | 34.5-35.0% | | | 17.2-18.4% | 76.5-78.0% | 71-79 |
| Entry waits for a pullback, support or below the 20-day average | 33.6-35.4% | | | 17.2-19.2% | 71.6-76.3% | 48-59 |
| Extra entries on pullbacks above the 50-day average | 30.4-32.7% | | | 15.8-17.6% | 66.2-70.0% | 87-144 |
| Sizing tilt: P/S own history | 34.5-34.8% | | | 19.5-20.3% | 69.1-72.4% | 65 |
| Sizing tilt: peers, growth-adjusted | 34.8-35.3% | | | 18.7-19.2% | 74.7-76.7% | 64-65 |
| **Sizing tilt: P/E own history, strength 0.5** | **37.4%** | **-27.1%** | **1.45** | **21.2%** | **77.4%** | 65 |
| same at 25 bp (baseline 33.0%, 16.9% / 72.9%) | 35.2% | -27.6% | | 18.9% | 75.6% | |

31 rules were tried; only the P/E-history tilt led in both windows. The extra
entries add 10-30 trades a year whose median return is about +1% with 50-57%
wins, against +2.6% and 58% for the baseline's own entries: they spread the
same capital thinner. Waiting for a better price gave up entries without
improving them.

## The tilt

Each night every name the rule sizes gets its leader slot multiplied by
1 + 0.5 (1 - 2h), h being where its P/E sits in its own trailing 756 sessions
(at least 250 readings; 0 the cheapest, 1 the richest); no positive earnings
or too little history leaves the slot unchanged. The slots are renormalised;
the volatility target, floor, cap, band block, FOMC cycle and fills are
unchanged. It admits no name.

Robustness: returns rise steadily with the strength (0.25: 36.3%, 0.75: 38.2%,
1.0: 39.6%) in both windows and on both grade sets; a two-year window gives the
same; ahead in 8 of 11 years; against 30 seeds each of random scores and of the
real values shuffled across names, the real signal sits about 3.5 standard
deviations above the placebo mean to 2022 and about 2 after. Strength 0.5 was
fixed before the 2023-2026 results were read; 1.0 tested better but was seen
after, so it is not the pick.

What it measures: its cross-sectional rank correlation with year-on-year
earnings growth is -0.53, so it reads as "earnings have grown faster than the
price", closer to earnings momentum than to classic cheapness.

## Caveats

Survivor universe (no delisted names); the edge is top-heavy (removing the
three largest contributors removes most of it); latest-quarter-x4 earnings are
noisy; loss-makers (30-40% of names) are untouched. Expect a smaller edge live.
