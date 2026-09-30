# Kronos on the book's bars: a pre-trained K-line model as a feature. Pre-registration (2026-09-30)

**Status: registered before any weight is downloaded or any forecast made.**
Operator's go-ahead: "go ahead with kronos" (2026-09-30, 14:40 ET). The
operator's question, answered in the note that proposed this: is a
specialised model the next best step? No, batch S1 of the scenario
catalogue is (rules that read structure, running tonight). Kronos is the
one open-source specialist worth RTX time, run in parallel as a *feature
test*, never as a decision-maker.

## The question

Kronos (Shi et al., AAAI 2026; `NeoQuasar/Kronos-base`, 102M parameters,
MIT) tokenises OHLCV bars and predicts the next bars autoregressively. Its
own headline is a RankIC of 0.025 on Chinese A-shares. Our analysts carry
rank ICs of 0.03-0.04 on this book, and every price-only model measured
here (stage 1: ridge, CNN, PatchTST, a frozen Chronos-Bolt; IC 0.011-0.013,
zero on 2024-2026) failed the gate. Does a model pre-trained on 12 billion
bars from 45 exchanges read this book's bars better than those did, and
does its forecast of the *next session's path* make a better fill than the
fixed 1% dip?

## What is known before this note (disclosed)

- Stage 1 (`deep-intraday-stage1-2026-09-27.md`): eight price-only models
  on the 81,612-row export (94 names, 2016-02..2026-09), IC at most 0.013
  (t 2.3) on 2016-2023, none on 2024-2026, every book negative against the
  hurdle. Stages 2-4: RECORD.
- Kronos's repository carries no US out-of-sample evidence and says it is
  not a production system; its training data spans 45 exchanges and
  (per the paper) runs into 2024. **Contamination:** on any session before
  the model's data cutoff it may have seen the bars it is asked to
  forecast. The deciding window is therefore *after* the cutoff, and the
  cutoff is recorded from the paper/model card before the run (Addendum 1
  if it cannot be established; then every in-window number is reported as
  contaminated and only the post-cutoff window decides).
- Kronos-base's context is 512 tokens: about 19 sessions of 15-minute
  bars, or two years of daily bars.

## Arms

Both arms run on the RTX 5080 from the stage-1 export path
(`market_stage3_export` conventions: adjusted bars, the 94 names, the
sessions the book graded), forecasts written as parquet, evaluated on
spark1 with the existing harnesses. No fine-tuning: the pre-trained
checkpoint only, so there is nothing to overfit.

- **K1, daily forecast as a stance:** context = the last 512 daily bars
  through session t; predict 20 sessions; feature = the predicted
  20-session log return, and the predicted path's max drawdown. Evaluated
  as the analysts are: rank IC against the 20-session beta-adjusted
  residual on `harness.evaluate_scores`' cells (in-window 2018-01..cutoff,
  post-cutoff separately), and the book gate on the T-S1 scorecard as a
  sixth analyst with the technical analyst's stance rule (top/bottom 30%,
  3-session persistence).
- **K2, intraday path as a fill rule:** context = the last 512 15-minute
  bars through session t; predict session t+1's 26 bars; the buy's dip
  level is the predicted session low (capped at open × 0.97 and floored at
  the control's open × 0.99), else the close; through the adaptive-entry
  harness at 20 offsets against `dip_or_close`, the S1 criteria. Sells:
  the mirror with the predicted high.
- **K3 (reported, no trial):** K1's feature added to the stage-1 ridge
  and the marginal IC over the stage-1 set, to say whether Kronos knows
  anything the simple models did not.

Two trials (K1, K2); cumulative 464 → 466.

## Criteria, fixed now

K1 **is proposed as a sixth analyst** only if its post-cutoff rank IC is
≥ 0.02 with t ≥ 2 on at least 60 post-cutoff periods (if the post-cutoff
window is shorter than that, the study is RECORD by construction and says
so) *and* the book gate holds (T-S1: +2 bp a session at 25 bp over `/5`,
NW t ≥ 2 on the model window, not negative after, 15 of 20 offsets,
deflated Sharpe at the cumulative count ≥ 0.95). K2 **REPLACES** the buy
rule under the S1 fill criteria, with the model window restricted to
post-cutoff sessions. Anything else is **RECORD**; the in-window numbers
are reported and labelled contaminated.

## Prior

K1 clearing the post-cutoff IC floor: 15%; the book gate: 5%. K2: 10%.
The likely finding is that Kronos reads volatility (as stage 4's models
did, |g| at IC 0.2-0.3) and not direction, and that the post-cutoff
window is too short to decide much. That is still worth knowing before
anyone hosts a "specialised model" for this desk.

## Permissions and compute

- Downloads to the RTX (E:, not C:): `NeoQuasar/Kronos-Tokenizer-base`
  and `NeoQuasar/Kronos-base` from Hugging Face (about 0.5 GB), the
  `shiyu-coder/Kronos` repository (MIT) for the model code.
- Compute: about 250k forward passes of 512 tokens for K2 and 250k for
  K1; batched on the 5080 this is under two hours. No Spark GPU time.
- Data: the stage-1 export from spark1 to `E:\AgentWorkspace\rtx-data\kronos`
  (the same path stage 1 used).

## Order of work

1. This note committed and pushed. 2. Record the data cutoff (Addendum 1).
3. Download; smoke-test the checkpoint on one name; build the export, the
inference script and the two evaluation adapters with tests. 4. Run; read
no number before both forecast files are complete. 5. Write-up,
independent check, report.

## Addendum 1 (2026-09-30, before any download): the data cutoff

Read before any weight was downloaded or any forecast made.

- **Paper** (arXiv 2508.02739v1, HTML, appendix "Task Implementation
  Details / Forecasting Task Setup"): "The pre-training data for Kronos
  extends up to June 2024. Consequently, our test period for all tasks
  begins in July 2024 to ensure a strict temporal separation between
  training and evaluation." The corpus table lists the Nasdaq Stock
  Exchange (8,725 assets, 2,478,662,459 observations, timeframes T, 5T,
  15T, 30T, H, D, W, start 2000/1/1) and the New York Stock Exchange
  (7,073 assets, 2,133,143,549 observations, the same timeframes, start
  2000/1/1). NASDAQ (XNAS) is named an "in-distribution" exchange for the
  evaluation. So both this book's daily bars and its 15-minute bars up to
  June 2024 may be in the corpus.
- **Model card** (`NeoQuasar/Kronos-base`, README on the Hub, read the
  same day): repeats "over 12 billion K-line records from 45 global
  exchanges" and states no cutoff. It gives the Model Zoo (Kronos-base:
  Kronos-Tokenizer-base, context 512, 102.3M) and the `KronosPredictor`
  API; the checkpoint's `config.json` carries no date.
- **Cutoff recorded: 2024-06-30.** In-window = 2018-01-02..2024-06-30
  (contaminated; reported, never deciding). Post-cutoff = 2024-07-01
  onwards (the paper's own test convention), which decides.
- **Arithmetic consequence, stated now:** the post-cutoff window holds
  about 565 sessions through 2026-09, so `harness.evaluate_scores` at
  20 sessions has about 28 non-overlapping periods there, under the 60
  the K1 IC criterion requires. **K1 is RECORD by construction** on the
  IC floor, as the criteria section foresaw; its post-cutoff IC and t
  are still computed and reported, and the book gate is still run so
  the number is on record. K2's model window (post-cutoff sessions) is
  about 565 sessions, enough for the S1 fill criteria, which are judged
  as registered.
- Sampling defaults, from the repository README's `predict` example
  (recorded here so the run cannot choose them): `T=1.0`, `top_p=0.9`,
  `sample_count=1`, `top_k=0`; the model samples (`sample_from_logits`
  with `sample_logits=True`, `torch.multinomial`), so the run fixes a
  seed. The paper's Table 6 uses T 0.6, top-p 0.90, N 10 for price
  forecasting; this study uses the README's defaults as its instruction
  says, and reports that the paper's setting is different.

## Addendum 2 (2026-09-30, after the smoke test, before any study forecast): build choices

Written before the export was run and before any forecast of the book
was read. The smoke test the plan's order calls for (one name, NVDA's
daily bars, the checkpoint as downloaded) is disclosed here in full.

**Install.** `shiyu-coder/Kronos` at `67b630e` (master), checkpoints
`NeoQuasar/Kronos-Tokenizer-base` (model.safetensors 15,842,368 bytes)
and `NeoQuasar/Kronos-base` (409,264,008 bytes) under
`E:\AgentWorkspace\rtx-data\kronos\hf`. The repository's own regression
tests (`tests/test_kronos_regression.py`, four cases at context 256 and
512 against stored reference outputs) pass on the RTX venv (torch
2.14.0+cu130), so the install reproduces the authors' numbers.

**The model call** (`backend/research/kronos_forecast.py`): batches
normalised exactly as `KronosPredictor.predict_batch` normalises each
series (per-column mean/std over the context, clip 5, amount = volume x
mean OHLC), `KronosPredictor.generate(x, x_stamp, y_stamp, pred_len,
T=1.0, top_k=0, top_p=0.9, sample_count=1, verbose=False)`, de-normalised
per series; verified to reproduce `predict()` on the same context and
seed to 7e-5. fp32 throughout (no autocast: the repository's decode
returns a tensor `.numpy()` cannot take in bf16, and TF32 would change
the sampled tokens against the regression fixtures). `torch.manual_seed`
per (name, batch) from seed 0. Time stamps: daily bars at midnight,
15-minute bars at their New York start times.

**Throughput (smoke, NVDA, 512-bar context, 20 steps):** 9.0 cells/s at
batch 128 (3.7 GiB), 9.3 at 256 (6.9 GiB); batch 384 oversubscribes the
16 GB card and stalls. The run uses batch 192 for K1 and 128 for K2 (26
steps). At about 9 cells/s a 150k-cell arm is about 4.5 hours; the two
registered arms run overnight, K1 first.

**What the smoke test showed, disclosed:** on NVDA with the registered
512-bar daily context the model's forecasts are strongly and uniformly
bearish - on 40 random cells across 2017-2026 the predicted 20-session
log return averaged -0.53 (sd 0.51) against a realised +0.05 (sd 0.13),
the predicted first-step return -13%; a 5-seed spread at one cell of
-0.30 to -0.43 (T 1.0, N 1) and -0.27 to -0.30 (the paper's T 0.6,
N 10). The bias grows with the context: mean predicted 20-session log
return -0.09 at 64 bars, -0.12 at 128, -0.20 at 256, -0.33 at 400,
-0.53 at 512. The paper's own daily forecasting setting (Table 8) is a
look-back of 40 with a horizon of 12, and 160/32 for 15-minute bars. A
uniform bias cancels in a cross-sectional rank IC; a bias that scales
with each name's own trend does not, and it is the model's reading
either way. **The registered arms stay as registered (512 bars).** One
secondary, disclosed set is added before the run so the paper's own
setting is on record beside it: **K1c40** - context 40 daily bars, the
same 20-session horizon and features, the same cells, evaluated by the
same harness and criterion, labelled in the payload as a secondary set.
It is a disclosed extra trial: the count is now three (K1, K2, K1c40;
cumulative 464 -> 467), and the deflated Sharpe in K2's payload is
computed at the registered two with the cumulative 466 beside it as the
code was written; the results doc reports both counts. K2 keeps its 512
bars only (compute), with the paper's 160-bar setting registered as a
follow-up, not run.

**Cells.** The graded, member (session, name) pairs from 2018-01-02 (the
in-window start) through the last stored session; a cell whose name has
fewer than 512 prior daily rows (K1) or 512 prior 15-minute bars through
t (K2) is not forecast and is counted. Daily bars are the panel's
adjusted OHLC (the dividend factor on open/high/low, the adjusted close);
15-minute bars are the cube's 26 regular bars scaled onto the adjusted
basis by `stage4_labels.cube_scale`, so a split inside a context is not
a jump. The closing auction bar is not part of the context.

**K1 evaluation** (`backend/market/kronos_eval.py`): `harness.
evaluate_scores` at 20 sessions, 10 bp, at least 15 names (the analysts'
measurement), on the cells every arm scores per window; the arms are the
predicted 20-session log return and the predicted path's maximum
drawdown (higher = shallower), and the desk's own graded score
(`report.scores`) is measured on the same cells as the reference, with
paired per-period differences. Windows: in-window 2018-01-02..2024-06-30
(contaminated), post-cutoff 2024-07-01 on (decides). **The book gate**
(a sixth analyst through the T-S1 scorecard with the technical
analyst's stance rule) is registered as follow-up and not run in this
pass: the sixth-analyst path needs `grading.grade_stances` and
`desk.assemble` to take an extra stance and the scorecard's paired
curves and per-offset CAGRs, which live on the unmerged
`research/structure-rules` branch; and with the scorecard's 2016-2023
deciding window entirely inside the contaminated period it could not
decide anything before the post-cutoff window has 60 periods (about
2029). K1's verdict is therefore RECORD in this pass whatever the IC,
and the payload says why.

**K2 evaluation** (`backend/market/kronos_fill.py`): adaptive entry's
harness with two candidates. `K2_buy`: level = t+1's open x clip(predicted
low / predicted open, 0.97, 0.99), the first bar close at or below it,
else the official close; `K2_sell`: the mirror on the predicted high in
[1.01, 1.03]. No forecast: the control's fill, counted. Model window =
post-cutoff decision sessions (2024-07-01 on); the contaminated window
2018-01-02..2024-06-30 is reported. Criterion 3 ("2024-2026 not
negative") is read on the contaminated window, the only other window;
the deflated Sharpe at N = 2 uses the across-candidate variance of the
two candidates' model-window Sharpe ratios. Twenty offsets, executed
basis, `graded-equal-weight/5`, 25 bp, as the S1 study.

**K3** (`evaluate_k3`): K1's two columns appended to the stage-1
dataset's scalars (`~/scratch/stage1_dataset.npz` on spark1, the file
the stage-1 reruns used) on the rows that have a forecast; the stage-1
ridge walked forward with and without them; the daily IC of each per
window and the paired difference with a Newey-West t at lag 20.

**Independent check:** `docs/research/scorecards/kronos/kronos_check.py`
recomputes K1's mean IC and t from the per-period ICs and K2's window
means, HAC t and per-order g from the payload's rows, with numpy only.
