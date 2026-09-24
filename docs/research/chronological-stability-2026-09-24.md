# Chronological stability of preserved accounts — September 24, 2026

The unchanged `cash-bounded-breakout-rotation/3` reconstruction exceeds SPY
and QQQ in all four evaluated blocks at both costs. This is a post-hoc stability
diagnostic of already examined, current-survivor accounts. It is not independent
validation or an achievable-return estimate.

The shape was fixed before reading block results: 126 reference sessions,
63 evaluation intervals, the original study's 21-session label horizon, and
five embargo sessions. `walk_forward_folds` supplies separated ranges. Reference
ranges were not used to refit anything and cannot prove historical training,
selection or availability. The completed study was not rerun or tuned.

Each block retains the continuous account's starting NAV and positions.
Adjacent blocks share one NAV mark and no return interval. No account restart,
extra entry or liquidation is simulated.

| Starting NAV session → ending NAV session | Incumbent, 10 bp | Incumbent, 25 bp | SPY | QQQ |
| --- | ---: | ---: | ---: | ---: |
| 2025-08-13 → 2025-11-11 | 74.38% | 73.17% | 6.20% | 7.23% |
| 2025-11-11 → 2026-02-12 | 25.84% | 25.36% | 0.04% | −3.24% |
| 2026-02-12 → 2026-05-14 | 46.41% | 45.72% | 10.12% | 19.99% |
| 2026-05-14 → 2026-08-14 | 16.82% | 16.03% | 4.03% | 1.68% |

These are net block returns. ETF returns coincide across costs because their
funded entry precedes these blocks; the original accounts retain those costs.
Price-only neural ranking beats incumbent only in block four. Its completed
full-period result remains rejected. The JSON retains all five accounts at both
costs, including equal weight, local drawdowns and regime attribution.

## Coverage and limits

All 428 original intervals reconcile: 152 in the reference/purge prefix, 252
in four evaluated blocks, and 24 in the incomplete tail. Prefix/tail coverage
and full-account performance remain visible.

| Prior-information regime | Evaluated blocks | Complete original sample |
| --- | ---: | ---: |
| Above 200-session mean, high volatility | 113 | 177 |
| Above 200-session mean, low volatility | 127 | 197 |
| Below 200-session mean, high volatility | 12 | 54 |
| Below 200-session mean, low volatility | 0 | 0 |
| Unknown or unavailable | 0 | 0 |

Bearish coverage is limited and the empty regime is unassessed. Four
nonoverlapping blocks do not constitute independent market trials. Survivor
membership, reconstructed grades, prior policy selection and previously observed
outcomes remain embedded in every block.

Regime indexing uses preceding observations, but the preserved SPY history was
retrieved from Yahoo on September 18, 2026. Its availability at each historical
decision is UNVERIFIED. Hash identity cannot repair that limitation. Raw cash
and fill journals were not retained; fold turnover, fees and exposure cannot be
recovered independently from NAV and remain unavailable. No policy is promoted.

## Reproduction and verification

From the repository with its market-research dependencies installed:

```bash
python -m backend.cli.market_chronological_diagnostic \
  --artifact-dir /home/animallya96/anios/data/market/research/neural-price-rule-20260924 \
  --spy-bars /home/animallya96/anios/data/market/bars/asof=2026-09-18/SPY.parquet
```

The command checks the separate checked-in receipt, five artifact hashes,
SPY hashes/metadata, complete XNYS calendars and saved full-sample arithmetic
before slicing. NumPy loading disables pickle. It reads files and prints JSON;
it cannot train, simulate, fetch prices or mutate an account.

VERIFIED: 76 related metric/harness/adapter tests and 14 CLI tests passed.
Root independently reran the 43-test metrics module and directly recomputed all
40 account/block returns and drawdowns from the saved NAV arrays. Exact source
hashes matched the report. Scoped Ruff/format and `git diff --check` pass. The
original nine run files and SPY parquet were byte-identical before/after.
Original study source: `1ad7e5996f57a46589a8f7585a030f7067c1e09c`.
The CLI used `exchange-calendars==4.13.2` in a disposable local test container.

Full report on Spark:
`data/market/research/chronological-stability-20260924.zcXplA/chronological.json`.
SHA256: `819e4bd49f0a5355ff48d6303a5f3bf5add84db43413f8478fcf0476ae1b6ccd`.
The copied Spark report's hash also matches. No deployed policy or service changed.
Diagram impact: NONE — calculations inside existing research components.
