# Trading cleanup — 2026-10-01

Scope: prove unused or redundant code before deleting it. Starting branch
`codex/open-source-research-20261001`, source `f133cd88`; unrelated untracked
files and other agents' new modules were preserved. No policy, data, service,
deployment or order changes.

## Removed

**VERIFIED:** removed the unused private `_weekly_series` helper from
`backend/market/technical.py` (20 lines including comments and spacing).
Repository-wide text search found only its definition; an AST scan of Python
files under `backend/` and `scripts/` found no name or attribute references.
The module does not export or dynamically dispatch it. The feature builder
calls `_weekly_ema` directly for both weekly horizons.

The removed routine retained an obsolete Thursday-based weekly bucket and
treated the final panel row as a completed week. It was inactive; its removal
does not fix or alter current signals. The retained weekly EMA has separate
tests for Friday closes, carried weekly values and removal of future sessions.

## Acceptance

- Before deletion: 36 technical, live-technical and alpha tests passed.
- After deletion: **62 tests passed** across `test_market_technical.py`,
  `test_market_live_technical.py`, `test_market_alpha.py`,
  `test_trading_desk.py` and `test_trading_exit.py` in 2.88 seconds.
  Existing missing-data warnings remained; no assertions were changed.
- Actual frozen market input: the last 420 sessions across all 96 names,
  all 33 feature outputs, **1,330,560 values byte-identical** before and after,
  including missing values. Feature bytes SHA256
  `8076c8ca561531d709c665758189325e4a7e2ecfd766ab555b2cf63fcb3f7ae6`;
  input SHA256
  `8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58`.
  This establishes unchanged calculations, not economic improvement.
- Changed source SHA256
  `11bf94ad0a0e74ee7d859de204f1e89423a78605dc2a9dfd81569d306b29a742`.
  Ruff and `git diff --check` pass.

Tests exercised a read-only mount of the isolated Spark research checkout
`/home/animallya96/scratch/open-source-source-20261001`, network disabled,
`ANIOS_TEST_MODE=1`, container image `anios-functional-tests` SHA256
`c8964e1233e1142b77e6ac2b24fda67ee110a0f8e4c95482c4799d8617e17fb0`.
The temporary equivalence runner was
`/tmp/check-trading-cleanup-20261001.py`; it compared retained feature bytes
against a baseline saved before the edit. No live checkout was changed.

## Retained and limits

The initial scan covered 198 Python files in `backend/market/` and
`backend/agents/trading/desk/`; active new open-source integration modules
were excluded from removal. Zero-reference private top-level functions were
reviewed against repository callers and tests. It found only the helper
above. This is a bounded audit, not proof that every public function, class,
test or script is necessary: CLI entry points and optional research paths
cannot be classified as dead merely because production does not import them.

Legacy paper-order compatibility remains required by the active dispatcher
and recovery paths. Failed research implementations, preregistered protocols,
test assertions and result records remain intact. No further deletion met
the same evidence threshold in this pass. No new cleanup test was added:
the existing causality and live-path tests plus exact output comparison
cover this removal without adding a test that simply asserts a function is
absent.

Diagram impact: NONE — deleting an uncalled private helper changes no
component, dependency, ownership boundary, store or data flow.

**UNVERIFIED:** deployment and browser behavior; no user-interface behavior
changed, and this research branch was not deployed.
