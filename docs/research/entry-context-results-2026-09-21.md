# Ten-session context experiment: result and morning handoff

The corrected quarterly features did not establish a useful incremental timing
edge. Do not promote this model, retune on these periods, or escalate to a
larger neural model merely because the GPU is available. This conclusion is
specific to the fixed experiment; it does not establish that ML cannot help
other trading decisions.

## Verified experiment

Protocol: [fixed design](entry-context-protocol-2026-09-21.md). Source revision
48853b6e. Run completed on the desktop from 07:01:38 to 07:03:16 UTC on
2026-09-21, return code 0, with four CPU threads. All 54 saved account paths
passed automatic replay: artifact hashes, model predictions, exact decisions,
and NAV tolerance 1e-10. The 29 supporting context/pilot tests passed with no
skips; the earlier corrected-feature suite passed 22 tests with no skips.

Training: 63,188 observations from 2020–2023 after label purging. Evaluated
2,420 opportunities in 2024 and 4,032 in 2025–2026. The pooled window contains
6,547 opportunities: it includes cross-year holdings that the isolated annual
window excludes at its exit boundary. It is one continuously funded account,
not a sum of the isolated accounts. Prices end 2026-09-04.

At 10 bps execution cost per side, context minus price-only:

| Window | Timing-only mean daily difference, bp | 95% block interval, bp |
|---|---:|---:|
| 2024 | +0.207 | [-0.067, +0.498] |
| 2025–data end | -0.018 | [-0.294, +0.262] |
| Pooled | +0.072 | [-0.130, +0.269] |

Pooled timing results at 5 and 20 bps costs are essentially the same, and
their intervals also include zero. Context timing versus always-enter is
+0.130 bp/day [-0.238, +0.471]; versus always-wait it is -0.078
[-0.556, +0.411]. There is no demonstrated improvement over the simple controls.

Allowing context to skip opportunities reduced exposure. In the later window,
its difference versus always-enter was -22.803 bp/day [-40.577, -6.785],
with average exposure 56.3% versus 86.6%. Against price-only skip, the pooled
difference was -1.130 bp/day [-6.321, +3.681]. Lower drawdown alone cannot
establish a superior decision rule when exposure and missed upside differ.

The large absolute retrospective returns are not forecasts. The universe is
selected with hindsight, the report periods have already informed earlier
research, and IEX bar-open execution omits historical spreads and impact.
Cash earns zero and drawdown is measured at daily closes. The intervals are
descriptive 20-session block-bootstrap intervals, not proof of fresh out-of-
sample significance after repeated research.

Artifacts: `E:/AgentWorkspace/entry-timing-pilot-20260920/context-run-01/`.
Dataset SHA256:
`02a1e45e8565b37a4a72e1b0e55db5ebfdd9f08cc97054a8b024998b5da39c31`.
The manifest pins source and artifact hashes; summary.json holds every cost,
period and mode. Runtime status and log are in the parent folder. Replay:

```powershell
.venv/Scripts/python.exe -m backend.cli.market_entry_context --verify --output E:/AgentWorkspace/entry-timing-pilot-20260920/context-run-01
```

## What is ready, and what is not

- **Deployed and browser-verified:** one table containing all 93 live names,
  BUY/HOLD/SELL-only plan cells, shared cash-aware order planning and planned
  buy caps, separation of research targets from adopted targets, and corrected
  strategy-report statistics. Gateway deployed at 8c17e72a. Backend checkpoint
  e1f2a87c passed 3,779 unit tests (24 skips) and 100 routing tests; actual
  authenticated desk browser acceptance covered desktop/mobile and errors.
- **Implemented and independently verified, research only:** corrected
  versioned quarterly features (0a796a0c), including NaN missingness and
  feature-specific fiscal dates, and reproducible ten-session ablation
  (48853b6e). These modules do not change live grades or orders. Their test
  results are not a claim that production has switched to corrected features.
- **GPU research already performed:** the earlier RTX5080 ridge/tree/GRU
  five-session pilot did not show a robust timing improvement. CUDA replay
  passed; strict cross-device numerical replay did not. This overnight
  ablation supplied no new reason for another GPU search or RL promotion.
- **Unresolved:** the live fundamental analyst still uses the legacy
  zero-filled/earliest-filing feature path. Migration needs its own reviewed
  comparison; the new research adapter is not that migration. Historical
  survivor bias remains. Forward evidence cannot be created overnight.
  Position caps constrain planned buys, not continuous weights after price
  drift; whole-share paper and fractional historical fills are not identical.

The supervised coding and fixed experiment are complete. The system is
stronger and more testable, but an "absolute best" trading solution has not
been established. Retain the incumbent policy; do not describe the new
research code as a deployed trading improvement. No real-money trades were
placed and no paid data was purchased during this work.
