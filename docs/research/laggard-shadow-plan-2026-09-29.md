# The sequence model's A/A+ laggard, forward: pre-registration (2026-09-29)

**Why this exists.** Stage 3 recorded every candidate
([stage3-results-2026-09-29.md](stage3-results-2026-09-29.md)). The
post-hoc section of that note found one lead: the M3 T-S1 forecast's
lowest-scored A/A+ name lagged its book over the next 20 sessions. It
lagged by 1.1% on 2016-2023 (t −2.85) and by 3.3% on 2024-2026 (t −3.45),
in 8 of 9 years and at every book size tried.

Three things stop that from being evidence:

- **It was found after the verdicts,** by looking at the forecast in a way
  the registration did not name.
- **2024-2026 has now been read twice.**
- **The book has run 408 trials.** At that count the expected best null t
  is 2.99 (the plan's formula), and the lead's t sits at that level. What
  makes it worth testing is that it holds in both windows and at every
  book size, not its t.

Only sessions nobody has seen can settle it. This note fixes, before the
model is trained and before any forward session is scored, everything the
forward test uses. Nothing below is changed after the first forward date
is scored. A change is a new, counted trial.

## The question

On decision dates after 2026-09-28, does the frozen model's lowest-scored
A/A+ name do worse than the rest of its book over the next 20 sessions?

The shadow shows nothing on the board, places no order and touches no
file on the live path. It writes only under
`data/market/research/laggard_shadow/`.

## The frozen model

- **What it is.** M3 on T-S1, exactly as
  [stage3-plan-2026-09-29.md](stage3-plan-2026-09-29.md) registers it and
  its addendum amends it:
  - the architecture;
  - `SEQ_GRID` and `SEQ_FIXED`;
  - the seeds 0-4;
  - selection by validation IC, then early stopping with the best epoch
    kept.

  Nothing about the model is new.
- **Which fit.** The walk-forward's next refit. It is the fold whose test
  block begins after the last session of the 2026-09-28 export
  (`stage3_s1.npz` `7fa24f7e`, `stage3_seq.npz` `e6d1d823`). With S
  sessions in that export and the registered gap of 26 and validation of
  252:
  - validation is sessions [S−278, S−26);
  - the fit part is [0, S−304).

  Both use labelled rows only, the same rule every stage-3 fold used.
- **What is saved.** One file, whose sha256 is the model id:
  - every seed's weights;
  - the channel and daily-branch scaling (the fit part's medians and
    IQRs);
  - the chosen configuration;
  - the daily column names in order;
  - the export's sha256 and the code revision.
- **Parity before the first forward date.** The model reloaded from the
  file, on spark1's CPU, must reproduce the training run's GPU forecasts
  for the validation rows within 1e-4. It must also reproduce itself
  exactly on a second load. A failure stops the shadow until it is
  explained.
- **Refit.** Every 252 forward sessions, the registered cadence for
  `(seq, s1)`. Each refit uses the same procedure on the then-current
  export and gets a new model id. The statistic pools model ids and
  reports them separately.

## Each night

The job runs after the 20:30 ET SIP append, from a worktree pinned at the
commit that registers this note's code. Installing it on spark1 waits for
the operator's go-ahead, which was asked on 2026-09-29.

1. **Export.** It writes the T-S1 rows and the sequence tensor with the
   stage-3 export (`market_stage3_export --only s1,seq`, the same inputs
   as the 2026-09-28 run) into `laggard_shadow/export/`.
2. **Forecast.** For every export session d after 2026-09-28 that the
   ledger lacks, the frozen model forecasts d's rows. A missed night is
   filled from the next night's export: every input at d is known at d's
   close.
3. **Ledger.** It appends one line per date to `ledger.jsonl`:
   - d, the model id, the export's sha256 and the time of the forecast;
   - the book: the rows graded A or A+ (`grading.ORDINAL[A]` and above)
     with a finite forecast, each with its grade and forecast;
   - the laggard, the lowest forecast (ties go to the first ticker in the
     export's order);
   - the book names whose own session d has no complete cube, which make
     the date unclean.
4. **Score.** A ledger date is scored once tonight's export has a finite r
   for every book name. r(i, d) is `extra["r"]`: ln(O(d+21) / O(d+1))
   minus the date's mean. It records:
   - the spread, 1e4 × (r of the laggard − the book's mean r);
   - the frictionless gain, −spread / (n − 1) / 20 bp per session;
   - the top name's spread;
   - the IC inside the book.

   `summary.json` is rewritten each night.

## The statistic and the verdict, fixed now

- **Primary.** The mean spread over scored clean dates whose book has at
  least three names, in date order, with the Newey-West t at lag 20
  (`candidate_stats.hac_t`; neighbouring dates share 19 of their 20
  sessions). Three names is the smallest book the diagnostic read. It
  gives the most dates: 96% of 2016-2023 sessions and 90% of 2024-2026.
- **Looks.** The verdict is read twice: at 250 and at 500 scored primary
  dates.
  - **CONFIRMED** at the first look where t ≤ −2.24. That is a one-sided
    2.5% test split over the two looks.
  - At 500 dates without that: **NOT CONFIRMED**, and the lead is closed.
  - Between looks the summary reports the running numbers. Nothing is
    decided on them.
- **Secondary, reported and never decided on:**
  - books of at least four and five names;
  - the frictionless gain;
  - the top name's spread;
  - the IC inside the book and across every graded name;
  - each of these per model id.
- **What CONFIRMED changes: nothing by itself.** It opens a separately
  registered decision test of an overlay that can hold the laggard out
  under the live executor. That overlay drops it from the book, spreads
  its weight under the cap, and gates the breakout entry on the targets.
  That test's floor is fixed before it runs, and any live change needs
  the operator's go-ahead.
- **The trial count.** This is one test with two looks, already paid for
  in the 2.24. The cumulative count becomes 409.

## Power, stated plainly

The per-date standard deviations below come from the diagnostic's own t
at three names (the dates overlap, so they are effective values):

| If the true effect is | Effective sd per date | Primary dates for t = −2.24 |
|---|---|---|
| the 2024-2026 reading, −283 bp | 2,348 bp | about 340 |
| the 2016-2023 reading, −94 bp | 1,390 bp | about 1,100 |

The book has at least three names on about nine sessions in ten.

- **The first look** (250 dates, about 13 months) confirms an effect of
  about 2.0-3.3% per 20 sessions, depending on which period's noise
  holds. That is roughly the 2024-2026 reading or larger.
- **The second look** (500 dates, about 2.2 years) confirms one of about
  1.4-2.4%.
- **An effect the size of the 2016-2023 reading** would stay NOT
  CONFIRMED. This note accepts that: at that size the ceiling was below
  the stage-3 floor anyway.

## What would make this wrong to run

- **The export changes under the shadow.** A revision of the daily store
  or the cubes changes history, not only the new date. The ledger keeps
  each night's export sha256, and the forecast for d is made once, the
  first night d is available. A later export never rewrites it.
- **The live grades and the export's grades disagree.** The book is the
  export's grades, as in training. The ledger is not the board and is
  never compared with it for this question.
- **The model is retrained on a different machine or library.** Training
  runs once per refit on the RTX. Inference runs on spark1's CPU, checked
  by the parity rule above.

## Addendum 1 (2026-09-29, before the model was trained and before any forward date)

These are the build's decisions where the note above was silent. The first
concerns when a date counts as available:

- **A forward date with no cube session is not yet available.** The
  sequence tensor has no cube session for d when the SIP append has not
  run for anyone. Such a date is not forecast that night; the job says it
  is waiting and forecasts it the first night the tensor has d.
- **A partial cube is still available.** When d is in the tensor but some
  book names lack their own session, the date is forecast and recorded as
  unclean. This is "the first night d is available" read as "the first
  export whose tensor has session d".
- **The first night is chosen by schedule.** The job runs well after the
  append: 23:30 ET, since the 2026-09-28 append took about 70 minutes. A
  partial append is then rare.

The rest fix details of the build:

- **The frozen model stays with the registered code.** It lives in
  `backend/market/stage3_final.py`, which calls `stage3_nn`'s own task,
  scaling, training and prediction functions. The registered module is not
  edited.
- **Forward dates follow the saved model.** They are the export's dates
  after the saved model's own last training session (`meta.fold.last_session`),
  so a refit continues the ledger where its predecessor stopped.
- **The ledger stores the book in the export's row order.** That is
  ticker order, so the tie rule ("the first ticker") is the book's first
  entry.
