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
Equal weight rebalances every 21 sessions without grade/FOMC overlays.
SPY/QQQ use funded constant-exposure next-open accounts. Midpoint fills
are not demonstrated. No live strategy or frozen journal was changed.

The JSON artifact contains both costs, continuous calendar-year slices,
rolling comparisons and exact model/input/curve fingerprints. Persistent
run directory: `/home/animallya96/anios/data/market/research/neural-price-rule-20260924`. Original files are unchanged.

## Independent verification and regime decomposition

Independent verification reproduced every displayed metric and rolling count,
verified 191 source hashes and training-only normalization, and found no artifact
change. Receipt: `/tmp/neural-study-artifact-review-20260924.json`. The raw trade
and cash journals were not saved: turnover's denominator was independently
verified, but raw funding was not replayed independently. In particular, the
candidate's turnover intensity is higher; its absolute cumulative traded
notional is lower because its account grew less.

The existing fixed regime definitions were reused on these saved curves: each
return interval uses only the preceding SPY close versus its trailing 200-day
mean, and trailing 20-day volatility versus its trailing 252-observation median.
No refitting, new threshold choice, account restart or switching policy.

| Regime | Intervals | Observed months | Episodes | Candidate minus incumbent log growth, 10 bp | At 25 bp |
|---|---:|---:|---:|---:|---:|
| Above 200-day mean, high volatility | 177 | 15 | 14 | −0.14877 | −0.15078 |
| Above 200-day mean, low volatility | 197 | 17 | 11 | −0.18650 | −0.19308 |
| Below 200-day mean, high volatility | 54 | 5 | 3 | −0.04360 | −0.04156 |
| Below 200-day mean, low volatility | 0 | 0 | 0 | Unassessed | Unassessed |

Contributions reconcile across all 428 return intervals. The candidate trails
the incumbent in every observed regime, although it exceeds SPY and QQQ in
each. These are descriptive decompositions of previously examined outcomes;
the months and episodes are not independent confidence bounds. There is no
evidence here supporting a regime switch into this candidate. Full results and
reproduction script are preserved as `regimes.json` and `regime_replay.py` beside
the original run; the original model, inputs and curves remain unchanged.

The user's primary objective is total portfolio gain and outperformance of both
SPY and QQQ. Drawdown and turnover remain diagnostic checks on how that gain is
achieved. This candidate does not improve that primary objective; nothing in
this report establishes that the incumbent is universally optimal.
