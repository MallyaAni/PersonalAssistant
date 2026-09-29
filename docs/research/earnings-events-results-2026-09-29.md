# Filing expectations: completed first gate

**DO_NOT_ADVANCE for both models. Nothing live changes.** The fixed experiment
was implemented and run, not merely specified. Code: `1ec0b0c`. Registration:
`e2054e6`, published to Spark and GitHub before extraction/training.

## Results

The original 94-company source packet yielded 1,554 eligible new-quarter
events. Models use strictly preceding financial snapshots, not current-quarter
facts, prices or consensus. Eligibility is narrow and some companies, including
NVDA, have no qualifying events under this declared revenue concept. This is
not a replacement for all live fundamental coverage.

| Model | Scored events / issuers | Scored years | MSE improvement vs persistence | MAE improvement | Verdict |
| --- | --- | --- | --- | --- | --- |
| Ridge | 1,215 / 72 | 2021–2026 | −5.91% | −0.92% | DO_NOT_ADVANCE |
| LightGBM | 1,028 / 71 | 2022–2026 | +0.89% | +0.06% | DO_NOT_ADVANCE |

Each comparison uses the model's own common rows with persistence. Different
coverage means the two absolute model MSEs must not be compared directly.
Both fail the registered 2% MSE/MAE improvements and positive lower bootstrap
bound. LightGBM improves both errors in three of five scored years; that alone
does not pass. Its paired squared-error benefit's 95% block-bootstrap interval
is [−0.00135, +0.00360]. Targets/test errors were not clipped or filtered after
inspection. There were eight absolute persistence errors above one log unit on
each model's scored support.

The post-filing gross diagnostic also offers no investment lead. On the 1,012
mature LightGBM events, actual-minus-model-forecast growth has Spearman 0.0055
with subsequent 20-session return minus SPY, and 0.0048 versus QQQ. Persistence
surprises on those identical events score 0.0344 and 0.0305. These are pooled
descriptive event correlations, not independent observations, funded P&L or
evidence of statistical significance. Sixteen recent events lack mature return
endpoints. No funded variant or live forecast was activated from this failed gate.

## Verification

Exact committed code passed Ruff and 168 tests, with two retained expected
failures in existing period machinery. Thirteen new tests exercise the actual
source parser, archive export/readback, real Ridge/LightGBM fitting, chronological
early stopping, changed-future-target invariance, invalid currency/conflicts,
missing prior disclosures, strict output creation and matched index endpoints.

A separate script with **no AniOS imports** checked all original archive hashes,
reconstructed financial arithmetic from raw JSON pointers and replayed saved
models: 94 original bodies, 44,078 signed source terms, 11,605 accepted financial
values, 827 explicit missing features, all 1,554 events, 1,215 Ridge predictions
and 1,028 LightGBM predictions passed. It verifies the stated construction, not
historical acquisition authenticity or the economic comparability of all issuers.

## Artifacts and limits

Spark: `/home/animallya96/scratch/earnings-events.QfGDif/`:

- `run-code/`: clean detached `1ec0b0c` used for the real run.
- `sources/`: retained original-byte archive copy, no provider calls.
- `events.json`: `f0d8df4a6c60d721e3be5dc840b8547d46396b1ee01106646d5a0e384e88f606`.
- `results/summary.json`: `09cc13f75f96e64bffc43ba323aeff171714488bcf0e0d556bf57a0037772da3`.
- `results/predictions.json`, `results/fits.json`: hashes in the summary.
- `audit.py`: independent source/arithmetic/prediction audit.

The compact summary is copied to `scorecards/filing_expectations_20260929.json`.
Current snapshots, current-selected issuers, conservative filing dates and a
single revenue concept limit inference. Filing disclosure is not necessarily
the earnings release. No evidence here supports removing the existing live
LightGBM augmentation either: that is a different pipeline and needs its own
matched decision test. No model retuning follows this result.

Next work is the separately registered, limited sequence-laggard weight test,
not another forecasting-family sweep. Its existing forward shadow remains frozen.
