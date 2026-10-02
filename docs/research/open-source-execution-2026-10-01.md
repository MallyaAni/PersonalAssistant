# Independent execution replay

The optional NautilusTrader benchmark is implemented in
`backend/market/open_source_execution.py`. It runs the native matching engine
and funded cash ledger, while reusing the desk's actual `decide` and bounded
execution guards. Nothing imports it in production. No broker or provider calls,
model changes, deployment or automatic policy promotion occur.

## Fixed scope

- Pinned stable `nautilus_trader==1.231.0`, Python 3.12, CPU only. Its published
  wheels support Linux ARM64; the Intel Mac has no compatible binary wheel.
- One explicitly declared regular session, raw equity prices, whole-share quote
  quantities, a flat starting account and explicit costs. Nonzero initial
  holdings and multi-session raw corporate-action accounting are rejected.
- Both arms receive identical supplied opportunities, completed candles,
  point-in-time latch evidence, bid/ask event times and receipt times. The
  bounded arm uses each order's explicit contract budgets. The incumbent uses
  its unchanged timing decision, subject to the same quote evidence requirement.
- Native CASH/NETTING accounting, no borrowing or shorting; buys sized at their
  worst allowed price plus costs. Cash and holdings update from native fills.
- Distinct quote events update the book once; repeated snapshots cannot
  replenish liquidity. Conflicting event identities and out-of-order source
  events are refused. Unsupported price precision and size units remain missing.
- IOC partial fills terminate the attempt; remaining shares are not silently
  retried. Price-blocked, expired, unfunded and missing-quote opportunities remain
  in the output denominator. No observations also remains a retained opportunity.
- A native limit can consume displayed bid/ask size. This is explicitly a
  **conditional displayed-liquidity simulation**, not proof of broker execution,
  queue priority, midpoint fills or executable future liquidity. Bar and trade
  execution are disabled; no OHLC-to-quote conversion exists.
- The incumbent market-on-close window is reported as unsupported without
  closing-auction evidence. Ordinary native market attempts use IOC semantics;
  this is a timing-component comparison, not exact live transport reconstruction.

## Input and invocation

Frozen JSON uses `schema: "nautilus-quote-replay/1"`, `session`,
`price_basis: "raw"`, `quantity_unit: "shares"`, `starting_cash`, `cost_bps`,
`legacy_quote_age_seconds`, optional zero-valued `initial_holdings`, and
`opportunities`. Each opportunity contains `order` (the immutable fully bound
paper-order contract) and `observations` (possibly empty).

An observation contains `observed_at`, a causal optional `latch`, `candle`, and
optional `execution_quote`. A quote contains `symbol`, `bid`, `ask`, `bid_size`,
`ask_size`, `timestamp` (source market event), `received_at` (original receipt),
`source`, and `price_basis: "raw"`. Every timestamp must be timezone-aware.
No freshness, price, spread or expiry budget is selected from replay outcomes.

```sh
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 CUDA_VISIBLE_DEVICES='' \
python -m backend.cli.market_open_source_execution frozen-quotes.json \
  --output execution-comparison.json
```

The CLI prints or writes strict JSON with both input hashes, retained
opportunities, actual native attempt/fill statuses, quantities, commissions,
cash, holdings and final bid-marked equity. It does not change the input.

## Acceptance and limits

**VERIFIED:** 18 new cases plus 29 unchanged intraday cases passed together
(47 passed, 0 skipped, 0 failed; 0.92 seconds) in the isolated Spark runtime
`/home/animallya96/scratch/open-source-runtime-20261001/bin/python`, with
Nautilus 1.231.0 and GPU access disabled. Tests execute the real native engine:
10/25 bp fees, available cash, no shorting, partial IOC cancellation, exhausted
shared liquidity producing an unfilled IOC, expiry, unsupported/missing evidence,
source identity, empty denominators and rebound entry differences. Ruff passes
for the module, CLI and test. Upstream emits a pandas timestamp deprecation
warning; no assertion is relaxed or warning suppressed.

**VERIFIED CLI synthetic diagnostic:** frozen rebound input SHA256
`54a77ec062e2edffc5d1bc8b4e8b20f86cc9f7fbea5ed0f70bf7227c254a37a6`,
cash 1,000, buy plan 10 shares, observed bid/ask 109.90/110.00, zero added costs.
The incumbent simulated attempt buys 9 shares, ending cash 10 and bid-marked
equity 999.10. The bounded contract attempts none, ending cash/equity 1,000.
This verifies rebound protection; the spread difference is not an alpha result.
Artifacts are `/tmp/codex-nautilus-rebound-input-20261001.json` and
`/tmp/codex-nautilus-rebound-result-20261001.json` on Spark.

**UNVERIFIED:** historical execution superiority, broker fill fidelity, latency,
market impact, full closing-auction parity and multi-session funded P&L. The
current historical bar caches do not establish timestamped bid/ask liquidity.
Do not publish CAGR/Sharpe for this execution comparison from OHLC touches.
The next requirement is a frozen archive of original quotes, causal decisions,
contract budgets and account starting state, or an untouched forward shadow.

A broader existing bounded suite run in this optional runtime produced 98
passes and one environmental import failure: FastAPI is not installed in the
research environment. That is not a failed native behavior assertion; full API
acceptance belongs to the normal application test image.

## Primary sources

- [Pinned official PyPI release](https://pypi.org/project/nautilus-trader/1.231.0/)
- [Pinned engine source](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/engine.pyx)
- [Pinned fee model](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/nautilus_trader/backtest/models/fee.pyx)
- [Pinned native custom-data tests](https://github.com/nautechsystems/nautilus_trader/blob/v1.231.0/tests/unit_tests/backtest/test_engine.py)

Latest/nightly documentation can describe v2 release-candidate APIs. This
implementation follows and tests the stable v1.231.0 API instead.

Parent review added exclusive CLI artifact writes: frozen inputs and earlier
outcomes cannot be overwritten. The final native suite passed **49 cases**
(20 new plus 29 existing) in 1.35 seconds; Ruff passed. This is execution
acceptance, not a gain comparison: there is no archived quote dataset from
which to establish historical IOC returns against SPY or QQQ.
