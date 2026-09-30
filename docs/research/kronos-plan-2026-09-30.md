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
