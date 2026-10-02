# Pinned pretrained forecasts: research contract

Scope: isolated CPU inference, no training, no live allocation/order changes.
The fixed cohort is AAPL, MSFT, NVDA, AVGO, AMD, AMZN, META, GOOGL, TSLA,
AAOI, SPY, QQQ; decisions September 3–30, 2026. Missing contexts are kept.

| Model | Immutable weights revision | License | Fixed inference |
|---|---|---|---|
| [Chronos-2](https://huggingface.co/amazon/chronos-2) | `29ec3766d36d6f73f0696f85560a422f50e8498c` | Apache-2.0 | 252 closes, median, 10 sessions |
| [Kronos-small](https://huggingface.co/NeoQuasar/Kronos-small) | `901c26c1332695a2a8f243eb2f37243a37bea320` | MIT | 252 OHLCV bars, seed 0, 8 samples, temperature 1, top-p 0.9 |
| [TimesFM-3](https://huggingface.co/google/timesfm-3.0-pytorch) | `43046b85ec22d584a13f8098c2ed39c889e129c2` | Noncommercial/nonproduction | 252 closes, median, symmetric averaging off |
| [TTM r2.1 daily](https://huggingface.co/ibm-granite/granite-timeseries-ttm-r2/tree/90-30-ft-r2.1) | `6e5cb8ee51e0634a45637490f5db43148b2fa6be` | Apache-2.0 | 90 squared log returns, observed-context standardization, daily frequency token 8 |

Kronos tokenizer revision: `0e0117387f39004a9016484a186a908917e22426`.
The official Kronos source is pinned to
`67b630e67f6a18c9e9be918d9b4337c960db1e9a`; this is not a similarly named
PyPI package. TimesFM official source is pinned to
`e51928e27119cb17bebc005be2696b75e0a9e688` (September 29, 2026).
Dependencies: `chronos-forecasting==2.3.2`, `granite-tsfm==0.3.9`, official
TimesFM source above, PyTorch and NumPy versions recorded in each result.

The price-model forecast target is `forecast_close[t+10] / close[t] - 1`
minus the same model's independent SPY forecast return. The parent evaluator
uses one separately registered ranking/allocation rule and the actual
next-open-to-terminal-close funded ledger, with 10/25 bp costs. Forecast
errors and portfolio returns are different evidence. TTM forecasts the mean
of the next ten squared daily log returns; its constant baseline is the mean
of the preceding twenty. TTM is risk-only: no inferred portfolio advantage.

Input JSON declares `price_basis=adjusted_ohlcv`, `source_revision`,
`availability_mode` (`recorded` or `session_close_assumed`), `data_mode`,
`volume_basis`, ordered unique exchange-session `calendar`, requested
`decisions`, and `rows`. Each row has `symbol`, `session`, aware
`available_at`, `open`, `high`, `low`, `close`, `volume`; original fetch/source
metadata remains in the export's top-level `original_vendor_metadata`. No
duplicate filling, interpolation, zero
padding, or future price/covariate reads. The ten future *calendar dates*
are known calendar inputs, not future observations. All price fields must
share the declared adjusted basis; provider-reported volume is retained,
never transformed using the dividend factor. Kronos results under that
volume convention are conditional diagnostics.

The latest pinned weights become eligible the day after their observed
revision timestamps: Chronos June 6, 2026; Kronos September 10, 2025;
TimesFM September 3, 2026; TTM February 27, 2025. This blocks pre-checkpoint
scoring; it does **not** establish a training-data cutoff or historic live
tradability. Newer inference code and reconstructed snapshot adjustments
make the September comparison explicitly retrospective. Assumed regular
session completion timestamps do not prove original data publication.

Weights download only immutable configuration and safetensors; no remote
code loader or pickle artifact. CPU-only inference uses two Torch threads.
No Spark service is stopped and no GPU memory is requested. TimesFM-3's
[license](https://huggingface.co/google/timesfm-3.0-pytorch/blob/43046b85ec22d584a13f8098c2ed39c889e129c2/LICENSE)
also restricts production use of outputs: it must never enter dashboard
recommendations or live/commercial decisions without a separate license.

Command (one model per process; output must be new):

```bash
CUDA_VISIBLE_DEVICES='' python -m backend.cli.market_open_source_forecasts \
  --input /absolute/frozen-input.json --output /absolute/new-result.json \
  --model chronos2 --symbols AAPL,MSFT,NVDA,AVGO,AMD,AMZN,META,GOOGL,TSLA,AAOI,SPY,QQQ
```

For TimesFM isolated benchmarking only, add `--noncommercial-research`.
For Kronos add the reviewed official checkout to `PYTHONPATH`.

Verification so far: 15 contract tests pass, including future-prefix
invariance, explicit provenance, duplicates, late publication, licensing,
relative scale equivalence and missing dependencies. These use mocked
forecasts and do **not** prove checkpoint behavior.

Real CPU inference now independently passed for Chronos-2, Kronos and
TimesFM-3: each emitted ten finite positive forecasts on the first fixed
AAPL context, and a second actual inference after clearing the result cache
was bit-identical. Cold-start smoke wall times were 18.48, 13.73 and 14.74
seconds respectively (downloads included where required). TTM's actual
risk inference passed in 4.43 seconds with ten finite nonnegative forecasts
and the same cache-cleared exact repeat. All four models completed all 228
requested model/symbol/decision opportunities: 912 forecasts, no unavailable
rows or model errors. The 15 contract tests also passed in the isolated
Spark research runtime in 0.14 seconds. These counts prove inference, not
forecast accuracy or profitable trading; no model is promoted.
Kronos's full-run log interval was 986 seconds (16 minutes 26 seconds),
with observed RSS around 0.8 GiB; no GPU training is required for this run.

Runtime: Torch `2.11.0+cu130` (CUDA hidden, CPU only), NumPy `2.5.2`,
Transformers `5.17.0`, safetensors `0.8.0`, pandas `3.0.6`,
huggingface-hub `1.32.0`, chronos-forecasting `2.3.2`, granite-tsfm `0.3.9`,
TimesFM `3.0.2` from the pinned official Git revision. Source module SHA256
`4c495cbe0b4fb45046fa08564602fa4bb09d88afb7f8ca83fb57c1c1aa7f6d3c`,
CLI SHA256 `1fd7d3dede1e5990cdcc423db31cc82beb195d65cd90a69c2d9b3263d713973f`.
Input `forecasts-v2.json` SHA256
`e880fad45d38a1d52880f3aae54b7a306b49a7372661d58cd777553d424e6e13`.
The frozen export has 5,244 bars, twelve names, nineteen decision dates;
known exchange dates extend through October 16 without future price rows.
Outputs remain under `/home/animallya96/scratch/open-source-inputs-20261001`:

| Artifact | SHA256 |
|---|---|
| `forecast-chronos2.json` | `87e395d0b1e6453b99b7f5acf1dbda80b90537c9bff3092bf88de907a27b64de` |
| `forecast-kronos.json` | `8eaf4e51d11b6914f1135f693f97fdf691e9044ce409cf7618a2c520c28fc8f8` |
| `forecast-timesfm3.json` | `f2f308583dabf3a751075079f4d01d1b99d66d66404d702aa1fba8f211fc3485` |
| `forecast-ttm.json` | `b94a258c0c1fe0c663a3e360db382a56b89649000dd6126ee9603c2d924e7fb0` |

Downloaded artifact SHA256 values (config / `model.safetensors`):

| Artifact | Config | Weights |
|---|---|---|
| Chronos-2 | `ef1143bfdc9c0376d9a056eefca46cb4b1ec3d0ffacd541ff56feb40fb708031` | `ddcda3c7508bf2528087723e98a20707cc04b7f370ae275a9fd88078ddba4f42` |
| Kronos-small | `5e0f6a605d5f81b5c9b559fe5cf716a1acb041c744e6f41bd05b097b7a685396` | `b082dfcbd8e8c142a725c8bbb99781802f38fec81210e13479effb32b3c3e020` |
| Kronos tokenizer | `2366e7ccfec76cbc19cf3c4c1b9c5d901be336ca1e83f2d2292c9bff381b77a2` | `59d85f6af76a2c3b8240ea06cb21db4213b4eeca053f246b23e29cf832fc6bee` |
| TimesFM-3 | `ff17bbc07b792c5a904cca265b8468579d736a4fe84981da25eb871b0a125bc6` | `a7592b0a8432baee54483254e5647856911ce69e09d09a9bb65904b2d98f17da` |
| TTM daily r2.1 | `abf1b5a26903f1d6b8eb62e66a72bf85bb0ced591b5ffaa655ec031b4d1ec326` | `17cdd864fa419e5aad8665789a92b6347e97f137ac2ff3c605887225f503f491` |

TimesFM-3 license file SHA256:
`3e36db7240d23adb6ac6d7d931892dcc5706a14a7d31581f08c35d2f25736dfd`.

Prior negative foundation-model evidence in
[the existing survey](sota-survey-2026-10-01.md) remains applicable. This is
a separately registered target/cohort diagnostic, not a reset of its trial
history. Adoption depends on actual funded, costed, compounded net gain
against SPY and QQQ, with missing outcomes retained, not inference counts
or directional accuracy alone. The small September sample cannot establish
long-run superiority even if its point estimates are favorable.
