# Earnings-expectations baseline scale

## Scope and finding

The research CLI's naive expectation means repeating the last known revenue
growth rate. Its feature, `revenue_yoy`, is log growth (`log(new / old)`),
whereas `_dataset` targets ordinary growth (`new / old - 1`), clipped to
`[-0.9, 5.0]`. The old main routine passed the log feature directly to
`_accuracy` and `_after`, comparing different numerical units.

This is a research-reporting defect, not a conversion needed by the model.
For a synthetic company repeatedly growing 100%, the old baseline is about
0.693147 rather than 1.0. It incurs about 30.685 percentage points of
artificial error. Comparing correlation alone does not repair the issue:
inverse-log conversion is nonlinear and can also change surprise ordering.

## Targeted correction

`main` now builds a separate array:

```python
naive = np.clip(np.expm1(x[:, NAMES.index("revenue_yoy")]), -0.9, 5.0)
```

Only the naive accuracy and after-report surprise diagnostics consume it.
The feature array, target, fitted forecast path, before-report study,
valuation-gap blending, grades and allocations retain their existing inputs.
No saved results, model parameters or historical accounts were rewritten.

The original study's naive comparison claims in the module and historical
CHANGELOG are explicitly qualified. Those figures do not establish superiority
over a correctly scaled baseline; the corrected historical comparison is
**UNVERIFIED**. The separate old funded-book figures were not recomputed and
are not qualified performance evidence by this repair.

## Verification

Starting clean main: `6702db7eb37bd096fe91f1983e1ece7b6c90fd19`.
The pre-edit pull was current. Backend code is exercised from the checkout,
mounted read-only in image
`63056fccae989b0ef65bb198bc913da58c87648169a50c1e2422b9b3c267d8ca`,
with network disabled, temporary filesystems and synthetic credentials.
No production service, external provider or actual model was called.

The new regression suite builds synthetic quarterly filings through the real
`edgar_features` → `_block` → `_release_windows` → `_dataset` path. Seven
per-company growth rates span negative, zero, positive and target-clipped
values. Those rows are repeated only to cross main's 500-row guard; they are
not additional independent observations or real training data. A synthetic
target vector replaces the fitted forecast so the real accuracy formatter
can be exercised without model training. The real `main` assignment must:

- match the simple-growth target within the source float32 precision;
- report rounded naive MAE 0.000 and correlation +1.000 for repeated growth;
- preserve features, targets and the supplied forecast without sharing the
  new baseline's memory with the feature array;
- leave optional study dispatch and its model input arrays unchanged;
- preserve an injected NaN and apply the target's lower/upper clipping;
- supply correctly scaled surprises to the real trailing `_fifths` helper.

**FAILED before the correction:** four product assertions, four passes,
0.55 seconds. The earlier first run additionally found two incorrect test
harness `_leg` argument indices; both original XMLs remain retained. No
production change was made until the corrected harness reproduced the four
scale failures. **VERIFIED after correction:** all eight targeted tests pass.
The wider relevant suite passed 88 tests with one existing missing-LightGBM
skip; its model-fitting path remains **UNVERIFIED**. Final evidence details
are in the receipt below. Independent review found no outstanding blocking
findings; its separate numerical check recovered the seven float32-derived
rates within `1.524e-08`.

This suite stubs `_after` and separately sends main's baseline into the real
`_fifths`; it does not exercise a complete post-report return study or P&L.
The test's expected vector is synthetic, not a forecast-quality result.

## Still unresolved

EDGAR zero-fills missing/nonfinite growth before the expectations feature
block. Neither `x == 0` nor its current-revenue presence flag can establish
whether the prior-year denominator existed. Preserving an injected NaN at
this later boundary does not restore that lost source provenance; the real
dataset also excludes rows with a nonfinite first feature. This correction
fixes numerical units only, not baseline coverage, label eligibility or
financial-data accuracy. A missing-growth fix needs a separate upstream
contract and measurement because it could change training and live inputs.

No historical fit, strategy replay, provider request, account operation or
deployment was performed. No laptop settings or access changes were needed.
**Diagram impact: NONE — one local research-reporting conversion.**

Evidence: `/private/tmp/anios-expectations-baseline-fix.N0ONQd/RECEIPT.md`.
Original read-only finding:
`/private/tmp/anios-expectations-scale.VCqmzGYZ/RECEIPT.md`
(SHA256 `c15d44fcd96bc7ccc95f8b55969f985d4558571e74701c0d3361a37734561b72`).
