# Corrected-data comparison — September 14, 2026

One bounded rerun of the existing ridge, tree and neural configurations on
the versioned, as-of fundamentals, with the original seeds, splits, purge
rules, epoch-selection procedure and cost assumptions. No hyperparameter
search, no additional model. **Every test-period figure is retrospective**:
the period 2025-01-02 to 2026-09-11 was examined by the original research
and by the selection of the neural epoch. Nothing here is promoted; the
frozen production experiment is unchanged.

## Fingerprints

| | old (frozen fundamentals) | new (as-of fundamentals) |
|---|---|---|
| source | b92ca4ff46c60ae92b4b387df460cafeb0b26287 | 64dc1584816d0b1777bc4e196911904b684613ca |
| feature block sha256 | 35927c33bf226151561a7a5280c3bd787136ddceed01edc1988d6e9e4816c068 | a29c82ff1c370b5bca92d2df1b8fe2bce04cec264cdb6b5d79a9878a014f977e |
| price sha256 | e2e3c6b32067aafb0c8949a6b7d9c27ef64fcd8e445677b11d6fd446b0f84900 | e2e3c6b32067aafb0c8949a6b7d9c27ef64fcd8e445677b11d6fd446b0f84900 |
| fundamental versions sha256 | none (frozen path) | 3353f5104f84bd1aa5a988e0c13c183d9d886e894c9827730439370de4ea2003 |
| training examples | 22387 | 22387 |
| sales-yield coverage in test | 0.8429 | 0.8532 |
| test window | 2025-01-02..2026-09-11 | 2025-01-02..2026-09-11 |

Prices are byte-identical between the runs; only the fundamental block
changed. Configuration: ridge alpha 10; histogram boosting 100 iterations,
15 leaves, l2 10, min leaf 100, rate 0.05, no early stopping, seed 0; the
network from `market_growth_pilot` with AdamW 0.001 and weight decay 0.001,
torch seed 0, fifteen epochs, epoch chosen from 5, 10, 15 on 2024 net log
wealth; training 2018-2023 every fifth session with the 21-session label
endpoint purged; 20-session decisions; 10 and 30 bp per traded dollar;
next-close dollar allocation; 10% name cap; SPY fully invested and exempt.

## The data correction, on the 93 names

Filing versions fetched for every name; `market_fundamentals_asof --audit`
against the frozen path on the desktop store (2015-01-02 to
2026-09-04): 3,856 periods
restated with a different value; revenue levels differ on
31,763 of 165,791
sessions where both paths are known, of which
31,698 are availability, revision or tag
corrections and 263 are added coverage from
quarters derived from six- and nine-month spans; 23,362
of the differing sessions use a different tag from the snapshot-wide choice.
Earnings: 12,955 correction sessions,
387 coverage sessions.

## Validation, 2024 net log growth

| policy | old | new |
|---|---|---|
| neural | +0.9083 | +0.9199 |
| ridge | +0.8851 | +0.8967 |
| trees | +0.5630 | +0.4815 |
| valuation_rule | +0.7111 | +0.5122 |
| momentum20 | +0.6147 | +0.6147 |
| momentum120 | +0.6778 | +0.6778 |

Winner old: neural (epoch 10); new:
neural (epoch 15). The selection
procedure is unchanged; the epoch it picked is not.

### Test period at 10bps, retrospective, 423 transitions

| policy | net old | net new | DD old | DD new | turnover old | turnover new | cash new | excess vs SPY new | excess vs equal new |
|---|---|---|---|---|---|---|---|---|---|
| neural | +63.7% | +65.0% | -49.7% | -52.5% | 25.2 | 24.4 | -0.0% | +33.9% | -57.3% |
| ridge | +61.0% | +74.3% | -45.5% | -49.7% | 22.6 | 22.8 | -0.0% | +43.1% | -48.1% |
| trees | +121.1% | +172.4% | -46.8% | -44.4% | 27.4 | 24.5 | -0.0% | +141.2% | +50.1% |
| valuation_rule | +255.5% | +150.0% | -36.5% | -35.7% | 8.9 | 7.6 | -0.0% | +118.8% | +27.6% |
| momentum20 | +419.0% | +419.0% | -38.3% | -38.3% | 34.4 | 34.4 | -0.0% | +387.8% | +296.7% |
| momentum120 | +348.1% | +348.1% | -45.9% | -45.9% | 14.0 | 14.0 | -0.0% | +316.9% | +225.7% |
| equal | +122.4% | +122.4% | -33.9% | -33.9% | 3.3 | 3.3 | -0.0% | +91.2% | +0.0% |
| SPY | +31.2% | +31.2% | -18.8% | -18.8% | 1.0 | 1.0 | +0.0% | +0.0% | -91.2% |
| USD | +0.0% | +0.0% | +0.0% | +0.0% | 0.0 | 0.0 | +100.0% | -31.2% | -122.4% |

### Test period at 30bps, retrospective, 423 transitions

| policy | net old | net new | DD old | DD new | turnover old | turnover new | cash new | excess vs SPY new | excess vs equal new |
|---|---|---|---|---|---|---|---|---|---|
| neural | +55.7% | +57.2% | -50.1% | -52.8% | 25.1 | 24.3 | -0.0% | +26.3% | -63.7% |
| ridge | +53.9% | +66.5% | -45.9% | -50.1% | 22.6 | 22.8 | -0.0% | +35.6% | -54.4% |
| trees | +109.3% | +159.4% | -47.2% | -44.8% | 27.4 | 24.4 | -0.0% | +128.5% | +38.5% |
| valuation_rule | +249.2% | +146.2% | -36.7% | -35.7% | 8.9 | 7.6 | -0.0% | +115.2% | +25.3% |
| momentum20 | +384.5% | +384.5% | -38.8% | -38.8% | 34.4 | 34.4 | -0.0% | +353.5% | +263.6% |
| momentum120 | +335.7% | +335.7% | -46.0% | -46.0% | 14.0 | 14.0 | -0.0% | +304.8% | +214.9% |
| equal | +120.9% | +120.9% | -33.9% | -33.9% | 3.3 | 3.3 | -0.0% | +90.0% | +0.0% |
| SPY | +30.9% | +30.9% | -18.8% | -18.8% | 1.0 | 1.0 | +0.0% | +0.0% | -90.0% |
| USD | +0.0% | +0.0% | +0.0% | +0.0% | 0.0 | 0.0 | +100.0% | -30.9% | -120.9% |

Cash exposure is the mean target cash across decisions; every stock
strategy found ten qualifying names on every decision, so all are fully
invested and the excess returns are exposure-comparable. Momentum, equal
weight, SPY and USD use no fundamentals and are identical between runs,
which is the control that the price block and execution are unchanged.

## Reading

- The learned models move modestly: the network +63.7% → +65.0% at 10 bp,
  ridge +61.0% → +74.3%, trees +121.1% → +172.4%. Drawdowns stay near half
  the account for the network and ridge.
- The fixed valuation rule falls from +255.5% to +150.0%. Its old result
  rested on the frozen path's snapshot-wide tag choice and earliest-only
  values; with information restricted to what was available at each
  decision, a large part of it goes away.
- No learned model beats the equal-weight universe control after
  correction (network −57.3%, ridge −48.1% against it; trees +50.1% is the
  exception), and every one is far behind 20-session momentum. On this
  retrospective period the frozen network has no demonstrated edge over
  the simplest exposure-matched control.
- None of this is evidence for or against the production ledger, whose
  untouched record starts after 2026-09-11.

Artifacts: `E:/AgentWorkspace/opportunity-learning-asof-20260914`
(inputs.npz, manifest.json, results.json, ridge/trees joblib, neural.pt).
The comparison as data: `opportunity-learning-asof-2026-09-14.json`; the
audit totals: `fundamentals-asof-audit-2026-09-14.json`.
