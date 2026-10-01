# Gross-risk execution correction — research only

Implementation: `647d289f`, on `fix/research-gross-execution-20261001`,
based on `research/regime-gross` at `bb5f0e61`. Do not merge this research
branch into live main as a strategy promotion.

## Defect and correction

The simulator discarded `_gross_target`'s change flag. Under `LIVE_POLICY`,
ordinary mid-cycle planning then replaced a requested gross-risk cut;
green-open sell suppression and close-only sells could also postpone it.

Gross changes now take precedence over those ordinary legs and execute at
the next open. A new risk target discards older deferred buys, so recovery
does not replay an obsolete basket. The unchanged all-ones control retains
exact returns, equity and trades. No future gross-path value changes prior
holdings or returns.

`gross_path` with `event_lifecycle=True` is explicitly rejected. The FOMC
lifecycle returns before this ordinary planning path and restores its own
baseline. A shared ceiling and recovery policy are not implemented; silently
accepting the combination would still produce misleading results.

## Verified evidence

The new regression file initially reproduced lost cuts and re-entry under
legacy live flags. After the correction, 54 tests passed on Spark using
the exact source copy at `/home/animallya96/scratch/gross-fixes.rVHK62`:

```sh
CUDA_VISIBLE_DEVICES= OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 \
  /home/animallya96/research-venv/bin/python -m pytest -p no:cacheprovider -q \
  backend/tests/test_gross_live_execution.py \
  backend/tests/test_vol_target.py backend/tests/test_regime_gross.py \
  backend/tests/test_trading_simulate.py
```

The 11 new cases cover flat/green-open cuts to half/zero, repeated cuts,
re-entry, exact inert-path parity, chronology, unsupported FOMC refusal,
independent cash/NAV/fee reconciliation at 25 and 100 basis points, and
discarding an unfunded old reset basket before recovery. The independent
journal verifier reconciles every closing value and confirms risk trades
occur at the open. Ruff and whitespace checks passed. Five existing NaN
warnings arise from synthetic trading-simulator fixtures.

## Not established

No historical market study was rerun, no old artifact was overwritten,
and no improvement over `/5`, SPY or QQQ is claimed. Prior artifacts keep
their original code identity; results with affected options require a
separately identified corrected run before comparison. The legacy daily
simulator does not reproduce the current intraday paper executor. The next
research boundary is coordinated FOMC/gross handling with an all-ones null
test under the same execution assumptions, before any promotion decision.

Diagram impact: NONE — an internal research execution correction; no change
to components, stores, deployment boundaries or cross-component flows.
