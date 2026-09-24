# Price-only neural ranking: fixed results, September 24, 2026

Decision: do not adopt this candidate. It loses to the unchanged live-rule
reconstruction in return, drawdown and turnover at both costs. This does not
evaluate the separate frozen nightly neural model.

**These are historical reconstructed accounts on current survivor membership,**
**not achievable-return estimates, actual personal returns or an untouched holdout.**
The 2025+ period was already examined. All financial inputs were missing;
the network was retrained on price/volume features with a fixed architecture.

Window: 2025-01-02 through 2026-09-18, NAV1, zero cash yield. No tuning
after outcomes. Training used 22,685 eligible examples, with every label
ending by 2023-12-27. Source: `1ad7e5996f57a46589a8f7585a030f7067c1e09c`.

| Cost | Account | Total return | CAGR | Worst drawdown | Sharpe | Annual turnover* |
|---|---|---:|---:|---:|---:|---:|
| 10 bp | Live-rule reconstruction | 399.9% | 157.9% | -31.7% | 2.26 | 16.36× |
| 10 bp | Price-only neural ranking | 242.2% | 106.3% | -37.1% | 1.84 | 20.80× |
| 10 bp | Equal weight | 134.7% | 65.3% | -33.5% | 1.61 | 0.95× |
| 10 bp | SPY | 31.7% | 17.6% | -18.8% | 1.03 | unavailable |
| 10 bp | QQQ | 41.4% | 22.6% | -22.8% | 1.02 | unavailable |
| 25 bp | Live-rule reconstruction | 380.4% | 152.0% | -32.2% | 2.21 | 16.33× |
| 25 bp | Price-only neural ranking | 226.8% | 100.8% | -37.4% | 1.78 | 20.78× |
| 25 bp | Equal weight | 134.1% | 65.0% | -33.5% | 1.61 | 0.95× |
| 25 bp | SPY | 31.5% | 17.5% | -18.8% | 1.03 | unavailable |
| 25 bp | QQQ | 41.2% | 22.5% | -22.8% | 1.02 | unavailable |

*Turnover is cumulative bought-plus-sold notional divided by mean account
NAV and session-years. It is not the sum of each trade divided by its own NAV.
Index controls did not preserve traded notional, so it is unavailable.

At 10 bp the candidate beats the incumbent in 8.7% of 366 overlapping
63-session windows and 0% of 177 overlapping 252-session windows.
Overlapping windows are not independent trials.

Execution: both rule accounts keep the live buy/sell timing, FOMC handling
and funding rules. Only scheduled ranking changes; midcycle rules stay.
Equal weight rebalances every21 sessions without grade/FOMC overlays.
SPY/QQQ use funded constant-exposure next-open accounts. Midpoint fills
are not demonstrated. No live strategy or frozen journal was changed.

The JSON artifact contains both costs, continuous calendar-year slices,
rolling comparisons and exact model/input/curve fingerprints. Persistent
run directory: `/home/animallya96/anios/data/market/research/neural-price-rule-20260924`. Original files are unchanged.
