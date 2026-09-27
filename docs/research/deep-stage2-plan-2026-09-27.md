# Deep sequence models, stage 2: inputs first, targets that matter to the decision (2026-09-27)

Pre-registration, written before any model of this stage is trained. Stage 1
([deep-intraday-plan-2026-09-27.md](deep-intraday-plan-2026-09-27.md),
[results](deep-intraday-stage1-2026-09-27.md)) ended INSUFFICIENT EVIDENCE
for the return head (IC 0.012, untradable) and a volatility head that beats
trailing volatility (R² 0.27) but loses as a sizing input
([vol-sizing-2026-09-27.md](vol-sizing-2026-09-27.md)).

## The operator's two points

1. **"Are we discarding the CNN and PatchTST for learning structure?"** No.
   Both are kept as written - the same architectures, the same fixed
   training constants - and a fourth arm is added that asks the structure
   question directly: a PatchTST encoder pretrained by masked-patch
   reconstruction on the bars alone, then read out by a linear probe. If
   the bars carry structure the encoder can learn without labels, the probe
   will show it; if the probe is no better than the ridge on the raw bars,
   the encoder learned nothing a line could not.
2. **"ML experiment success is very dependent on input data and
   features."** Stage 1 gave the models five sessions of one name's bars
   and three scalars. Stage 2 changes the inputs before it changes
   anything else: twelve times the context, the market's bars beside the
   name's, the desk's own evidence as inputs, and targets the live policy
   would actually act on. The models are the constant in this experiment;
   the inputs are the variable.

## Inputs, one row per (name, session t)

- **Universe.** Point-in-time book membership (`membership_history.csv`,
  `point_in_time.eligibility`), complete 26-slot sessions from the
  raw-basis SIP cubes, as stage 1.
- **Sequence, `K = 60` sessions of bars, 1,560 steps, six channels.** The
  name's bar log return, bar volume share of the session, bar range over
  close (stage 1's three), plus the same-session bar log returns of three
  market benchmarks - SPY, QQQ, SMH - as three more channels aligned step
  for step with the name's bars (a benchmark session the store lacks is a
  zero row, and the export counts how many). The 60 sessions are the last
  60 complete sessions in the cube ending at t, required to span at most
  66 exchange sessions (early closes are excluded from the cubes, so a
  strictly consecutive 60 would rarely exist); t + 1 must be the next
  exchange session and complete, as in stage 1.
- **Scalars.** Stage 1's gap, trailing 20-session return and trailing
  20-session realized volatility; **breadth** (the share of that day's
  members whose adjusted close rose); the **desk's regime** on t
  (exposure, selection confidence, participation percentile, AI basket
  drawdown, whether the rotation leader is AI, whether money is
  tightening); the **grade letter** as a four-way one-hot; every
  **analyst stance** on the name; the name's **band z** (the 20-session
  Bollinger position the live entry rule reads). Everything is known at
  the close of t; the no-lookahead test tampers session t + 1 and asserts
  row t's inputs unchanged.
- **Size.** About 81k rows x 1,560 x 6 float32 is 3.0 GB in memory; the
  export writes the sequence as float16 (1.5 GB before compression; bar
  returns below 6e-5 lose relative precision, which the models'
  standardization does not care about) and the trainer widens it back to
  float32 on load.

## Targets

- `rank` - stage 1's next-session open-to-close return, rank-normalized
  within the date. Kept as the anchor: if the new inputs move nothing
  here, that is a finding too.
- `downgrade20` - for a name graded A or A+ on t, 1 if the desk grades it
  below A on any of the next 20 sessions, else 0; undefined (not trained
  or scored) for names below A on t. This is the event the live policy
  acts on: a downgrade is a forced sale.
- `drawdown20` - min over j = 1..20 of adj_close[t + j] / adj_close[t] - 1:
  negative when the name trades below today's close at any point in the
  horizon, positive when it never does (not censored at zero, so the head
  can rank names that never dip too). The loss a holder of the name eats
  before the grade reacts.
- `vol20` - log realized variance of the next 20 sessions' daily log
  returns; baseline the same over the trailing 20 sessions.

The 20-session targets and the decision test's forward return are read
from the desk's daily panel (adjusted close, all exchange sessions); rows
whose horizon runs past the panel are NaN on those targets.

## Models, one fixed configuration each, no search

- `ridge` - stage 1's closed-form ridge (alpha 10) on the flattened inputs:
  1,560 x 6 + scalars, about 9.4k features; one fit per target.
- `cnn` - stage 1's temporal CNN (32 channels, kernel 5, dilations 1, 2,
  4, hidden 32) on the longer, wider sequence, with **one head per
  target** trained jointly: MSE on the standardized continuous targets,
  binary cross-entropy on `downgrade20`, each head's loss masked to the
  rows where its target is defined. Adam 1e-3, 20 epochs, batch 512,
  dropout 0.1, weight decay 1e-4 - stage 1's constants.
- `patchtst` - stage 1's PatchTST (patch 13, so 120 patches per channel,
  d_model 64, 4 heads, 2 layers, ff 128), the same four heads, the same
  constants.
- `patchtst-pretrained` - the same encoder, first trained for a fixed 5
  epochs on the fold's training rows to reconstruct 40% randomly masked
  patches (MSE on the standardized bars, a learned mask token, a linear
  reconstruction head), then frozen. The read-out is a **linear probe**:
  the mean-pooled embedding of every row, concatenated with the scalars,
  fitted to each target by the same closed-form ridge. No fine-tuning, no
  epoch or learning rate to choose beyond the fixed 5.

## Walk-forward

Stage 1's schedule: the first fit after 500 sessions, a refit every 63
sessions on an expanding window, predictions only out of sample. **The
purge is 20 sessions** (stage 1 used 5) because the 20-session targets of
the last training rows would otherwise overlap the test block. The same
purge is used for every target, including `rank`, so the four heads of a
network train on the same rows. For the pretrained arm the reconstruction
pretraining uses only the fold's training rows, so nothing after the
fold's train end is seen by any parameter.

## Metrics

- `rank`: stage 1's - daily cross-sectional Spearman IC with Newey-West t
  at lag 20, the 10 bp top-quintile portfolio against the equal-weight
  hurdle, the same on A/A+ names.
- `downgrade20`: out-of-sample AUC, and the **decision test**: each day,
  the graded book (equal weight of every A/A+ member) against the same
  book with the A/A+ names whose predicted downgrade probability is in
  the top decile that day dropped, both earning the next 20 sessions'
  return; the paired daily difference in bp per session (the 20-session
  difference over 20), Newey-West t at lag 20, net of 10 bp one way on the
  extra turnover the drops cause. This is what would change the live
  policy.
- `drawdown20`: daily Spearman IC of predicted against realized
  drawdown, and the same decision test dropping the top decile by
  predicted drawdown (the most negative).
- `vol20`: out-of-sample R² against the trailing 20-session realized
  variance.

## Kill criteria, fixed now

A target is **INSUFFICIENT EVIDENCE** unless its decision test earns at
least **+2 bp per session** (about 5 CAGR points on a fully invested book)
with **t >= 2.0 on 2016-2023** *and* the paired difference is **not
negative on 2024-2026**. AUC, IC and R² alone never pass: they are
reported so a failure can be read (no signal, or a signal the decision
cannot use). `rank` has no decision test of its own and is scored against
stage 1's floors for the record; it cannot pass stage 2. `vol20` is
reported against its baseline and cannot pass either. Only `downgrade20`
and `drawdown20` can produce a PASSED verdict, and PASSED names the model
and the target and is never a trading verdict: a pass means the live
policy gets a pre-registered trial on the point-in-time scorecard with
that model's forecast as the drop rule.

**Trials counted: 4 models x 4 targets = 16**, the pretraining variant
included as one of the four models. A payload counts the pairs it ran
against 16.

## Budget

One RTX 5080 run: the export on the Spark from the store (minutes to tens
of minutes for the cubes, the desk once, the row assembly), the file moved
once, the four models on the GPU in hours - not a week. The CNN at 1,560
steps and six channels is roughly 25x stage 1's arithmetic (3 m 22 s on
the 5080), so under two hours; PatchTST's attention over 120 patches is
the long pole and is the arm most likely to need the batch reduced if it
overflows 16 GB. Batch 512 is stage 1's and fits: the largest activation
is PatchTST's attention, 512 x 6 channels x 4 heads x 120 x 120 floats,
about 0.7 GB per layer.

## What would make me wrong

A `downgrade20` or `drawdown20` decision test at +5 bp per session with
t > 4 on the choosing window that holds on 2024-2026. That would say the
bars and the desk's evidence together see a downgrade coming a week
before the grade does, and the drop rule would be worth a live trial.
