# Desktop GPU replication — September 14, 2026

Bounded research-only replication; no strategy promotion or production deployment.
Source checkpoint: `bd2816c2` (explicit CPU/CUDA selection and five device tests).
CPU remains the default. Requested unavailable CUDA fails closed. Saved weights
remain portable CPU tensors; original input hashes and NAV tolerance are unchanged.

## Verified execution

- RTX 5080, driver 610.47, compute capability 12.0, PyTorch 2.14.0+cu130,
  CUDA 13.0; original desktop NumPy 2.5.1.
- Original transfer archive SHA256:
  `fbff766067d2e488478b05ff38b4171c2f74c566907d0db41ffaa6d8cf48dc60`.
  All 196 members validated before extraction; original artifacts preserved.
- One CUDA seed, two supervised epochs, two sequential RL episodes completed.
  Full invocation elapsed 4.876473 seconds; peak allocated 153,020,928 bytes,
  peak reserved 167,772,160 bytes. These are smoke checks, not performance claims.
- The smoke run's four learned-policy cost curves replayed successfully on CPU
  and on CUDA, with strict input hashes, exact decisions/dates and NAV atol 1e-10.
- Seventeen focused tests passed (3.42 seconds in the final run), including real
  CUDA forward/backward/optimizer execution and unavailable-device rejection.
  Ruff passed. Five existing NumPy timedelta deprecation warnings remain.

## Original frozen models: strict replay verified with frozen inputs

Original price hash matches:
`e2e3c6b32067aafb0c8949a6b7d9c27ef64fcd8e445677b11d6fd446b0f84900`.

Original feature hash:
`c232280a4d63a91cb5da17bb2be68d28a4989fbbb2c48752ab9f1b08ee625eef`.

Desktop feature hash:
`017797b4cfa94c95427569c50968b4905b078f1abc00b655f41f69f9aa3f57c9`.

Installing NumPy 2.5.2 in a separate research venv produced the same desktop
feature hash and the same strict replay rejection. The version mismatch alone
does not explain the discrepancy; the root numerical/platform cause is unverified.
No shared environment was upgraded and no hash check was weakened.

A separately labelled diagnostic loaded all six original weights against
desktop-derived features. All 12 original cost paths matched recorded NAV exactly
(maximum absolute difference 0), with identical decisions and dates. CPU and CUDA
also agreed on those paths. All 85 cash-state target baskets per model matched.
Maximum CPU/CUDA neural prediction differences by seed were 1.7881393432617188e-7,
2.384185791015625e-7 and 1.7881393432617188e-7. These small prediction differences
did not change the selected baskets. This diagnostic does not constitute a
hash-verified replay of the original inputs.

The final acceptance run exported exact original Dataset tensors on Spark,
checked them against the original manifest, and transferred them to the desktop.
Elementwise comparison found 7,633 differing finite feature elements, maximum
absolute difference 2.220446049250313e-16, and zero NaN-payload differences.
Prices, dates, ticker order and NaN positions matched. The low-level cause of
the recomputation difference remains unverified.

Using these frozen tensors, the unchanged `verify_artifacts` passed original
price and feature hashes and replayed all 12 original cost curves on CPU and
all 12 on CUDA. Decisions and dates matched exactly; NAV tolerance stayed 1e-10.
This resolves the original replay blocker without relaxing verification.

## Artifacts and reproduction

Desktop root: `E:/AgentWorkspace/growth-pilot-transfer-3dcce629`.
Original inputs: `market/`; original artifacts: `pilot/`; diagnostic:
`original-comparison.json` and `compare_original.py`.
Separate smoke artifacts: `gpu-smoke-bd2816c2/` (weights, manifest, results,
execution timing/memory JSON). Isolated NumPy check: `venv-numpy252/`, which
reuses the existing environment's other dependencies read-only through a .pth.

Frozen inputs: `growth-frozen-tensors.npz`, 14,821,699 bytes, SHA256
`f9b8d3729ab7ad79fdaa935c1b926255af69f79d061464ac36e5d496b76c3581`.
A durable copy is also stored in
`/home/animallya96/research/growth-pilot-20260914-3dcce629/` on Spark.
Desktop `verify-frozen-growth.py` validates the archive, compares recomputed
features and runs strict CPU/CUDA verification; `frozen-replay.json` records
the successful results. Run the helper from the source worktree using the same
desktop Python environment to repeat the final acceptance path.

From source checkpoint bd2816c2, using the existing desktop Python environment
with NumPy 2.5.1 and DEBUG=false:

```text
python -B -m backend.cli.market_growth_pilot --data-dir E:/AgentWorkspace/growth-pilot-transfer-3dcce629/market --output E:/AgentWorkspace/growth-pilot-transfer-3dcce629/gpu-smoke-bd2816c2 --asof 2026-09-14 --revision bd2816c2 --device cuda --verify
```

Repeat with `--device cpu` for the CPU replay. Training used the same arguments
without `--verify`, plus `--seeds 1 --epochs 2 --episodes 2`; use a new output
directory if retraining. Original replay uses `--output .../pilot` and currently
fails the strict feature check on this desktop under both tested NumPy versions.

Tests: `python -B -m pytest -q -p no:cacheprovider
backend/tests/test_growth_pilot.py backend/tests/test_growth_objective.py
backend/tests/test_growth_pilot_device.py`.

UNVERIFIED: strategy superiority, full desk equivalence, bitwise reproducibility
of recomputed features and production runtime behavior. No broker, account, dashboard or
Spark serving changes. Diagram impact: NONE — an internal execution-device
option adds no architectural component or data flow; no diagram edits made.
