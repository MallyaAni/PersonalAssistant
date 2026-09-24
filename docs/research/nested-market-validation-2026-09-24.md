# Nested market study — implementation evidence, September 24, 2026

This records verification, not a new strategy's performance. The separate
[frozen protocol](nested-market-study-2026-09-24.md) was declared before market
outcomes and retains SHA256
`11898d28ad41c8e625a54a56f604b7daac508a91bc85dc6ba1a3ac4cfffec483`.

## Implementation acceptance

VERIFIED: **1,033 tests passed**, **1 deliberately deselected** completed-study
reproduction, **5 existing empty-slice warnings**, **24.86 seconds**. New source,
input and study suites contribute **126**, **186** and **47** cases respectively.
Scoped Ruff lint/format and `git diff --check` pass. No deployed-system gate or
model-serving test was needed for this offline, no-prompt change; full deployment
gates and deployed behavior remain UNVERIFIED. No deployment occurred.

Actual source-to-feature synthetic acceptance constructs all22 features, fits
real regressions, executes six matched accounts at10/25bp, retains the archive
and runs20 actual standalone journal-verifier subprocesses. A separate
independently supplied-input fixture runs20 more. It checks exact `/3` parity,
funded controls, real fold boundaries, cumulative-notional attribution,
future-prefix non-interference, raw-label retention and complete archive readback.
Synthetic results do not establish investment performance.

Three final-review gaps were reproduced and corrected before outcomes:

- Report grades could change after assembly, leaving candidate basket gross .15
  while the changed incumbent targeted0. Binding now covers consumed report
  arrays, regime exposure/tightening, sides, themes, configuration and assembly
  source; changes during assembly or before/after the run are rejected.
- The FOMC CSV and NYSE holiday JSON used by the unchanged event policy were not
  in source evidence. Both are now hashed/copied, and process-local cached holiday
  interpretation is refreshed before constructing the event path.
- Valid journals did not alone prevent altered summaries, curves or labels from
  being archived. A complete evidence digest now binds those values, actual arrays,
  fits/predictions/proofs and actual journal contents, with pre/post-archive checks.

The local runtime is Python3.12.14, NumPy2.5.3, pandas3.0.6, PyArrow25.0.0 and
exchange-calendars4.13.2, on the exact checkout mounted at `/app` in image
`sha256:63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`.
Optional research dependencies were installed in a disposable `/deps` directory,
not into a live service. Full final JUnit and retained synthetic archives:
`/private/tmp/anios-nested-market-acceptance.teTufe/acceptance-02.xml` and
`pytest-02/`. The earlier979-test proof remains in `acceptance-01.xml`/`pytest-01/`.

Exercised source SHA256:

- Inputs: `b126f2886adae265f9b4d7eb07694478d3e0035f5666ca001b7bed52bfcf547e`.
- Sources: `a2f9fab54d53f8e45e61e9edb850619cef11576c8e464411a28829a4e803e320`.
- Study: `9d0a602bd6d1cbbcc512c5b00a1b193504f6cacacfb5569545eb4d2899be89d7`.
- CLI: `1fd03c2505e6b198b9fdaa2b7a65187924701cb3104202495e470622d1a6b014`.

## Real source acceptance, without fitting

VERIFIED: pinned report and source manifest, **191/191** source file hashes,
**570/570** exact report/source field comparisons including NaNs, and all
**2,945 XNYS sessions**. Original report remains95 columns; execution panel96.
Assembly produces2,939 raw labels per target and2,739 after the fixed200-row
training warmup. First outer session is2020-01-06. No all-name intersection,
future-availability filtering or history interpolation is used.

The full loader proof is `source-loader-proof.json` in the same evidence folder,
SHA256 `6de5cd2501506361545b67f7c94e0936c3f64b087cd0a73b1c4fff0734b64515`.
All96 fetch timestamps follow the final exchange close, September18 20:00UTC.
**FAILED vendor OHLC consistency:** terminal Q open118.080001831 is below
low118.150001526, and TYL open340.859985352 is above high340.640014648.
These values are preserved and explicitly flagged, not repaired or claimed
harmless: terminal opens can affect fills and labels. Their hashes match the
frozen vintage. Historical membership, precomputed report causality, then-known
adjustments and complete financial-quality features remain UNVERIFIED.

## Documentation browser acceptance

Diagram impact: UPDATED — market-data. All32 source/render/page checks pass;
31 unrelated SVGs remain byte-identical. Browser acceptance covers19 labels,
7 changed-node bounds, SVG/source navigation and100/125/300% zoom/reset, with
zero page exceptions, console errors or failed requests. Root inspected the
focused research branch. Evidence:
`/private/tmp/anios-market-study-diagram.i2IPJH/`.

## Next acceptance path

Run the frozen CLI once on the pinned historical inputs, retaining command,
stdout/stderr and exit status even on failure. Independently verify every saved
account and archive hash before interpreting full, rolling, actual-fold and
causal-regime scorecards. No market outcome is asserted by this implementation
checkpoint, and no result can automatically promote the strategy.
