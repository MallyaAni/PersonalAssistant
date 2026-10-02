# Joint stock/context forecasts: fixed research runtime

This contribution runs native multivariate Chronos-2 and TimesFM-3 inference
using the existing reviewed checkpoint loaders. It does not activate a live
policy, change the original univariate evaluation, or establish a trading edge.
The study protocol was frozen at `1b145c90` before these joint forecasts.

The fixed cohort is AAPL, MSFT, NVDA, AVGO, AMD, AMZN, META, GOOGL, TSLA,
AAOI, SPY and QQQ, on all nineteen decisions September 3–30, 2026. Each
forecast sees 252 synchronized completed adjusted-close observations and ten
known future exchange-session dates. Its signal is the target's terminal
forecast return minus **SPY's forecast within the same joint group**. The
unchanged independent baseline excess return is recorded separately; these
different SPY forecasts must not be silently substituted for one another.

Root's `specialist_study.context_mapping()` supplies the declared evidence:
NVDA/AMD/AVGO use their other two economic peers; MSFT/AMZN/GOOGL/META use
their other three; AAPL/TSLA/AAOI use QQQ as a broad market proxy. SPY and QQQ
use the other benchmark. SPY is added to every group and duplicates are
removed. These are assumed research groups, **not** historical sector
membership. Their explicit assumed availability is September 3, 16:00 New
York. Missing, late or unsynchronized evidence produces retained unavailable
opportunities, never silently inferred context.

Native interfaces inspected and exercised:

| Model | Actual call | Native shape for the NVDA proof |
|---|---|---|
| [Chronos-2](https://github.com/amazon-science/chronos-forecasting) | `predict_quantiles([tensor(n_variates,252)], prediction_length=10, quantile_levels=[0.5], cross_learning=False)` | input `(4,252)`, quantiles `(4,10,1)` |
| [TimesFM-3](https://github.com/google-research/timesfm) | `predict_batch([array(n_variates,252)], horizon=10, return_quantiles=True, use_symmetric_averaging=False, univariate=False)` | input `(4,252)`, quantiles `(4,10,9)` |

These use native within-group multivariate attention. Chronos's
`cross_learning=False` prevents cross-group mixing; it does not flatten the
variates into independent series. TimesFM explicitly uses `univariate=False`.
The median is retained, with seed zero and CPU deterministic algorithms.
There are no future price covariates, fine tuning, new provider requests or
outcome-selected hyperparameters. Groups above 32 variates are rejected to
avoid implicit TimesFM group splitting.

`specialist_forecasts.run(...)` returns the full Cartesian opportunity set;
each record retains model, symbol, decision, context evidence/hash, channel
identities, native dimensions, horizon session, original baseline forecasts,
and joint channel forecasts or the actual unavailable/error reason.
`validate_artifact(payload, artifact, contexts, baseline)` authenticates the
checkpoint, profile, input/baseline identities, full opportunity denominator,
causal contexts, dimensions and relative-price arithmetic before evaluation.
The caller independently authenticates the frozen input's byte hash. An
artifact validator proves content consistency; the actual runtime receipts
below supply model execution evidence.

Pinned weights and licensing remain unchanged:

| Model | Immutable checkpoint revision | License |
|---|---|---|
| Chronos-2 | `29ec3766d36d6f73f0696f85560a422f50e8498c` | Apache-2.0 |
| TimesFM-3 | `43046b85ec22d584a13f8098c2ed39c889e129c2` | Noncommercial/nonproduction |

TimesFM source is `e51928e27119cb17bebc005be2696b75e0a9e688`. Its license also
restricts production use of its outputs; both loading and this runner require
explicit noncommercial research mode. The production selector must never use
its forecasts. Neither model is promoted by this contribution.

The frozen input `forecasts-v2.json` has SHA256
`e880fad45d38a1d52880f3aae54b7a306b49a7372661d58cd777553d424e6e13`.
It has 5,244 rows, twelve symbols and known calendar dates through October
16, with no future price rows. `data_mode=reconstructed_snapshot` and
`availability_mode=session_close_assumed` describe the evidence accurately:
session-completion timestamps are assumed, not recorded original publication.
Original vendor metadata remains top-level in the input, authenticated by its
byte hash. Volume is provider-reported; this close-only study does not infer
split or dividend volume conversions. Checkpoint release gating is enforced,
but training-data cutoffs remain unverified and the implementation is newer
than the decisions. This is conditional post-checkpoint retrospective
research, not exact point-in-time live reconstruction.

The mapping was serialized before inference to
`/home/animallya96/scratch/specialist-forecast-artifacts-20261001/context-mapping.json`,
SHA256 `5d58da268ceeee0d6cae2a56bbcce73036af0fdd0576e634fbf1112a42b01040`.
Source module SHA256
`b5c67991840dc19cd301cbe56d2d9908f9897cfaee31bcf9cf0e73ef2badf35e`;
test module SHA256
`cdfb56f262e519b6730f87295ddfe3fa5696290827137f4a5776ea5a01be229b`.

Verification: eighteen focused tests pass on both Mac and the isolated Spark
runtime; Ruff passes. They cover future-prefix invariance, missing evidence,
late membership, synchronized prices, baseline identity, forged omissions,
relative units, channel/dimension tampering and TimesFM licensing. These
synthetic checks do not replace actual inference.

Actual Chronos-2 CPU proof passed on the fixed September 3/18/30 NVDA groups.
After clearing the forecast cache, inference after mutation of future price
rows was bit-identical at every date. All 228 requested Chronos opportunities
then produced valid forecasts; the artifact validator passed. Total wall time
including the six proof inferences was 26.16 seconds. TimesFM passed the same
three native proof pairs and all 228 opportunities in 65.28 seconds. Its
actual native quantile shape was `(4,10,9)` at each NVDA proof. All 456 joint
forecasts are retained, with no unavailable rows or model errors. No GPU was
used and no model service was changed. These counts establish execution and
causality checks, not forecast quality or profitable trading.

Runtime: Python 3.12, Torch `2.11.0+cu130` with CUDA hidden, NumPy `2.5.2`,
chronos-forecasting `2.3.2`, TimesFM `3.0.2`, Transformers `5.17.0`,
safetensors `0.8.0`, pandas `3.0.6`, huggingface-hub `1.32.0`. CPU inference
uses two threads; existing exact-revision cached checkpoints are used offline.

All runtime outputs are exclusive new files under
`/home/animallya96/scratch/specialist-forecast-artifacts-20261001`:

| Artifact | SHA256 |
|---|---|
| `joint-chronos2.json` | `3dcb1fe70879f3f0d81544c97c1d5c6de9fecfc37978b9878ed61a571fcee216` |
| `proof-chronos2.json` | `12932c894d0f5a4770b7c749d7b965774206d092a7f481c35a60a4d074622d6a` |
| `joint-timesfm3.json` | `f5ec7a36d068b5eadd402ee905693f037230254b7b3fbd19cc631cdc66637604` |
| `proof-timesfm3.json` | `ad966edb11144fde3a93b78533a926d8337fce9b46567dcbea62a934f1b86b34` |

Exact unchanged checkpoint bytes (config / safetensors):

| Model | Config SHA256 | Weights SHA256 |
|---|---|---|
| Chronos-2 | `ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031` | `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42` |
| TimesFM-3 | `ff17bbc07b792c5a904cca265b8468579d736a4fe84981da25eb871b0a125bc6` | `a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da` |

TimesFM license SHA256
`3e36db7240d23adb6ac6d7d931892dcc5706a14a7d31581f08c35d2f25736dfd`.

Reproduction from the isolated scratch checkout uses the retained runner:

```bash
CUDA_VISIBLE_DEVICES='' OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
  HF_HOME=/home/animallya96/scratch/open-source-hf-20261001 HF_HUB_OFFLINE=1 \
  PYTHONPATH=. /home/animallya96/scratch/open-source-runtime-20261001/bin/python \
  /home/animallya96/scratch/specialist-forecast-artifacts-20261001/runner.py chronos2
```

The runner writes with exclusive creation and refuses to overwrite completed
artifacts; a deliberate reproduction needs a new output location. The funded
scorecard belongs to the separately frozen root evaluator: next-open entries,
10/25 bp costs, common eligibility and retained immature outcomes. Forecast
accuracy, native inference success and profitable compounded gain are
different claims. Existing negative foundation-model evidence is preserved;
this small September comparison cannot establish long-run superiority.
