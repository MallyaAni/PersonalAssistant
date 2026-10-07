# Learned live replacement: completed candidate evidence

The current candidate does **not yet justify live activation**. In the completed
zero-cost comparison it earns less than the incumbent over the full period,
despite a slightly smaller maximum drawdown. Matching 10/25 bp controls are
still running; their absence is not a candidate win or loss.

These are conditional carried-account results for 2018-02-01 through
2026-09-30, starting with $100,000, whole shares and no cash yield. The same
frozen 96-stock current-vintage inputs and archived grade permissions are used.
Raw next-open fills are conditional proxies, not broker fills. Dividend claims
contribute to wealth but remain unspendable without supported payment evidence.
This is not exact historical live reconstruction or an untouched holdout.

## Complete zero-cost comparison

| Policy | Total gain | CAGR | Maximum loss | Sharpe |
| --- | ---: | ---: | ---: | ---: |
| Learned candidate | 719.67% | 27.57% | 42.19% | 0.98 |
| Current rule | 763.51% | 28.34% | 43.09% | 0.99 |
| Existing boosting timing control | 787.70% | 28.76% | 43.30% | 1.01 |
| Existing ridge timing control | 711.32% | 27.42% | 43.59% | 0.97 |
| SPY | 190.50% | 13.14% | 32.59% | 0.77 |
| QQQ | 350.63% | 19.04% | 34.54% | 0.86 |

The candidate finishes about $43,847 below the current rule on the initial
$100,000 account. It beats SPY and QQQ in total gain but has greater drawdown.
Its cumulative realized turnover is 256.98 versus 184.21 for the rule;
these are full-period ratios, not annual turnover. Average end-session exposure
is 62.56% versus 85.43%.

## Fixed cost sensitivity

| Cost per side | Candidate total gain | CAGR | Maximum loss | Sharpe | Paid fees |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 bp | 719.67% | 27.57% | 42.19% | 0.98 | $0 |
| 10 bp | 460.74% | 22.09% | 44.81% | 0.82 | $32,147 |
| 25 bp | 416.72% | 20.94% | 47.10% | 0.81 | $45,035 |

All three accounts are complete with no missing NAV marks. Their allocations
and funded execution paths differ, so costs cannot be estimated by subtracting
fees from the zero-cost curve. No cost setting is selected from these outcomes.
The independent proof includes 66 completed controls and explicitly retains
234 pending controls. Matching 10/25 bp rule, SPY and QQQ comparisons are pending.

## Previously declared periods

| Zero-cost period | Candidate CAGR | Rule CAGR | SPY CAGR | QQQ CAGR |
| --- | ---: | ---: | ---: | ---: |
| 2018–20 | 15.83% | 29.35% | 11.89% | 24.41% |
| 2021–26 | 34.01% | 27.83% | 13.78% | 16.39% |

The stronger 2021–26 result does not justify a retrospective regime switch.
The reused recent 32-session window returns 1.02% for the candidate versus
5.37% for the rule, −1.42% for SPY and 1.26% for QQQ. It is development evidence,
not an independent test. The full-period weakness is concentrated in the early
period; aggregate exposure and turnover identify questions for causal receipt
review, not permission to tune thresholds or select profitable windows.

## Verification and live status

Original producer `756c0076acccad57e0ad034324d3b4d7c8fa6a7b` completed all three
accounts and authenticated its unchanged source and inputs. The first saved
verifier failed because NumPy strings and physical JSON strings had different
scalar types despite identical ordered names and dates. Correction
`99e9bdef2934a713cf51d03689563480144b0daa` normalizes string names once and rejects
nonstring names; ordered matching and all original acceptance checks remain.
Both reproduced failures pass, reordered symbols still fail, and 79 tests pass
without skips. No model, price bank, producer or account was modified or rerun.

The separately identified verifier is terminal0 in container
`fe6824c5192f0d5b98ed86d52d21f5a4f07ae70e964d08d0b299f6174b93c7e1` using original
image `5c6c560537b3e7c70202edd6dfc872d299e2a268aa302ec23c3f48a3f49d099d`.
It runs without network access, with source/data read-only and private output.
Saved calibration, physical account and objective checks pass, including
1,703/1,703/1,708 available target receipts at 0/10/25 bp respectively.
No fitting, prediction or account replay is allowed in this verification.

Private evidence root on Spark:
`/home/animallya96/scratch/market-verifier-symbols-20261007`.

- `proof/saved-results.json`: SHA256
  `839678806cc4d8cbf6e48fd71918ebf21f3d1331f7ec6658c95389fe8f020719`.
- `proof/saved-results.targets.json`: SHA256
  `be738453d8ba221ed4ab61a71351f5d0130e552db92dff49e71b6dcef58db885`.
- `independent-acceptance.json`: SHA256
  `c608ea9f986f7cfad141d2e2438179cb1ea44631243dd147d92f1e998913c795`.

Live remains the independently deployed incumbent at `92b11bb9`. Neither
learned selector is installed. Receipt arithmetic does not establish calibrated
forecast accuracy, reliable fills or live economic superiority. Continue the
original matching controls and review their saved evidence before deciding
whether this design can replace the live rule; do not activate from the
positive subperiod or the benchmark gains alone.
