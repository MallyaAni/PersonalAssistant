# LLM financial-statement reading (A2): results (2026-10-01 run, written 2026-10-02)

**Verdict: RECORD.** The model's stance misses the registered IC floor on t:
+0.0275, but at t +1.78 where the floor needs t 2. The other two criteria
pass. Nothing changes on the board. No sixth analyst is proposed, and the
stance table does not go to the book gate.

The model also did not answer the question it was asked. On 1,124 of its
1,144 "down" calls, it gave a probability above 0.5, so the registered
stance (probability − 0.5) mostly measured confidence and not direction.
This is reported below. It does not change the registered verdict.

Plan: [`llm-statements-plan-2026-10-01.md`](llm-statements-plan-2026-10-01.md)
(`c3fe04ef`). Build: `d6852a8a`. Fix: `7ff4f249`. The run is committed as
`d6b6fea2`. Files are in `docs/research/scorecards/llm-statements/`.
Trial 478 (cumulative count 477 → 478).

## The verdict lines (verbatim, `evaluate.txt`)

```
null test (constant 0.5 reads as scoreless): PASS over 5 checks

=== criteria (primary horizon) ===
IC in-window +0.0275 (t +1.78); post +0.0112 (t +0.43); paired vs fundamental +0.0032 (t +0.14); role sixth analyst

=== direction accuracy (decides nothing) ===
all          n=2812 model 0.739 persistence 0.694 sequential 0.456 (paper 0.604)
post_window  n= 322 model 0.764 persistence 0.745 sequential 0.543 (paper 0.604)
in_window    n=2490 model 0.736 persistence 0.687 sequential 0.445 (paper 0.604)

VERDICT: RECORD
```

## The registered criteria (20 sessions)

| # | Criterion (fixed in the plan) | Measured | Result |
|---|---|---|---|
| 1 | In-window IC (2018-01..2025-05) ≥ 0.02 **with t ≥ 2** | +0.0275, t +1.78 (86 periods) | **fails on t** |
| 2 | Post-cutoff IC (2025-06 on) not negative at t ≤ −1 | +0.0112, t +0.43 (16 periods) | passes |
| 3 | Paired IC against the fundamental analyst not negative at t ≤ −1 | +0.0032, t +0.14 | passes |
| role | Mean rank correlation < 0.3 with both the fundamental and the value analyst | +0.144 / −0.030 in-window; +0.194 / −0.063 post | would be a sixth analyst (moot) |

All three criteria must hold. Criterion 1 does not, so the verdict is RECORD.

## Tables

**Rank IC on shared cells, beta-adjusted residual.** In-window has 104,817
cells and post-cutoff has 26,608.

| Horizon | Window | A2 statement reader | Fundamental analyst | Value analyst | A2 − fundamental (paired t) | Periods |
|---|---|---|---|---|---|---|
| 20 | in-window | **+0.0275 (t +1.78)**, net Sharpe +0.40 | +0.0243 (t +1.16) | +0.0334 (t +1.56) | +0.0032 (+0.14) | 86 |
| 20 | post-cutoff | **+0.0112 (t +0.43)**, net Sharpe +0.56 | −0.0251 (t −0.90) | +0.0759 (t +2.21) | +0.0363 (+0.91) | 16 |
| 60 | in-window | +0.0291 (t +1.31) | −0.0077 (t −0.23) | +0.0689 (t +1.73) | +0.0367 (+1.17) | 29 |
| 60 | post-cutoff | +0.0425 (t +0.87) | −0.0105 (t −0.16) | +0.0877 (t +1.94) | +0.0530 (+0.85) | 5 |

The 60-session rows are reported and decide nothing. On these cells the
value analyst beats the A2 reader in every window.

**Direction accuracy.** This decides nothing. "Always up" is the share of
quarters in which net income actually rose year over year.

| Window | n | Model | Persistence (Q8 vs Q4 repeats) | Always up | Sequential | Paper |
|---|---|---|---|---|---|---|
| all | 2,812 | 0.739 (2,078) | 0.694 (1,949 / 2,809) | 0.623 | 0.456 | 0.604 |
| in-window | 2,490 | 0.736 | 0.687 | 0.609 | 0.445 | 0.604 |
| post-cutoff | 322 | 0.764 (246) | 0.745 (239 / 321) | 0.736 | 0.543 | 0.604 |

The paper's 60.4% is not a like-for-like comparison. On this book, net
income rose 62% of the time, and simply repeating last year's direction is
right 69% of the time. The model beats persistence by 4.9 points in-window,
where the data is contaminated because the model has read these filings.
Post-cutoff it beats persistence by 1.9 points on 322 calls, which is well
inside one binomial standard error (about 2.4 points). It beats "always up"
by 2.8 points post-cutoff.

## Direction/probability disagreements: 1,124 of 2,916 (38.5%)

The prompt asks for "your probability, from 0 to 1, that Q9 is above Q5".
The table below covers the 86 stored names.

| Stated direction | Probability > 0.5 | Probability < 0.5 |
|---|---|---|
| up | 1,772 | 0 |
| down | **1,124** (inconsistent) | 20 |

- **Every disagreement has the same form:** a "down" call with p > 0.5. In
  practice, the model reported its confidence in its own call, not the
  probability of "up".
- **Post-cutoff:** 105 of the 406 post-cutoff answers disagree.
- **Unstored answers:** the partial answers of the three unstored names add
  40 more (META 11, MPWR 7, SWKS 22 of 46 each). The total across all 3,054
  answers is 1,164.
- **Which names:** only 3 of the 86 stored names have none. IBM (30 of 44)
  and WULF (28 of 39) have the most.
- **Coarse probabilities:** 2,896 of the 2,916 probabilities sit above 0.5,
  and 1,805 are exactly 0.62. Five values (0.62, 0.65, 0.55, 0.72 and
  0.78) cover 96% of the answers.

As the plan required ("the probability kept"), the registered stance is
probability − 0.5. That stance therefore ranks names mainly by how sure the
model sounded, and it is positive for 98% of down calls. **The 73.9%
direction accuracy and the +0.0275 IC measure different things. The
direction calls never entered the stance.** The registered result stands
as the test of the registered stance. A stance signed by the direction
would be a new trial (see Next).

## Coverage: the 3 missing names are META, MPWR and SWKS

- **Planned:** 94 book names. Five have no eight-quarter statement series
  in the store, so `plan` gives them no observation: ASML, NBIS, Q, SIMO
  and TSM. The plan therefore made 3,057 calls over 89 names. These five are "kept" with empty frames. They are
  not counted as missing.
- **Missing:** status reports "3 names missing of 94". These are **META,
  MPWR and SWKS**: 47 planned observations each, 141 in total, and
  3,057 − 141 = 2,916 scored.
  - Each name had exactly **one** call that returned no valid answer:
    - META, quarter ending 2016-06-30
    - MPWR, quarter ending 2022-03-31
    - SWKS, quarter ending 2018-06-29
  - It was not the deadline: scoring took 131 minutes of a 401-minute
    budget. The reason for each failure is not logged. `call_sync`
    returns None on an unusable reply.
  - By design, a name with a failure is not stored. Its 46 answers sit in
    `edgar_statements/asof=2026-10-02/<T>.partial.jsonl` and resume on the
    next run.
- **Evaluated:** 86 names. The payload's `names_scored` is 91, which is
  the 86 plus the 5 empty frames.

## The independent check: exit 1, 3 MISMATCHES, none touching the verdict

All 16 IC lines match (every arm, horizon and window, plus the cell counts),
as do the post-cutoff accuracy, the block digests (0 mismatched) and
anonymity (0 blocks with a four-digit run). The three counted failures are
as follows.

1. **`names scored 86 payload 91`.** This line prints without a MISMATCH
   label but is counted as a failure. It is the known count difference
   from the empty statement files. The check counts names with at least
   one record (86). The evaluator's `names_scored` also counts the five
   empty frames (ASML, NBIS, Q, SIMO, TSM). It is a definition
   difference, not a data difference.
2. **`accuracy all: 2074/2806 (payload 2078/2812)`.** This is a real but
   benign disagreement in the counting rule. The check reads the realised
   direction from the *rendered* block, in millions to one decimal place.
   The evaluator reads exact filed values. Nine next-quarter pairs render
   as ties: HPE 2016-10-31, MSI 2025-06-28, NOW 2015-06-30, SMCI
   2016-12-31, TRMB 2018-09-28 and WULF 2015-06-30, 2015-12-31,
   2016-03-31 and 2016-06-30.
   - In exact values, three of them are true ties, which both sides drop:
     HPE $267.0M, MSI $562.0M and TRMB $86.5M.
   - The other six are not ties, for example NOW −41.03 against −41.05,
     and SMCI 16.666 against 16.662. The check drops these six and the
     evaluator counts them.
   - So 2,806 + 6 = 2,812 exactly. Four of the six were correct calls,
     which matches 2,074 + 4 = 2,078. All six are pre-cutoff (2015-2016
     quarters), which is why the post-cutoff line agrees.
3. **`accuracy persistence: 1943/2799 (payload 1949/2809)`.** This has the
   same cause. It is the 6 pairs above, plus 4 of the 7 persistence calls
   whose own Q8 and Q4 render as ties but differ in exact values: NOW
   2015-09-30, SMCI 2017-03-31, WULF 2015-09-30 and WULF 2016-09-30.
   That gives 2,799 + 10 = 2,809 exactly.

The effect on the numbers is nil. Model accuracy is 0.7391 on the check
against 0.7390 in the payload. Persistence is 0.6942 against 0.6938. The
accuracy report decides nothing in any case. The evaluator's exact values
are the right ones. To match them, the check would need the exact values
from the store, not the rendered blocks. Both reconciliations were
recomputed from `blocks.jsonl` and from the store's exact values
(read-only).

**Null test: PASS over 5 checks.** A constant 0.5 gives no defined period
in any window or horizon (mean IC NaN), and its stance table is empty.

## Could the 3 missing names change the verdict? Not plausibly

- **Arithmetic of criterion 1.** In-window, IC +0.0275 at t 1.78 over 86
  periods implies a per-period IC standard deviation of 0.143. Reaching
  t 2 at the same dispersion needs a mean of **+0.0309**, a gain of
  0.0034.
- **What the three names would need.** About 56 names share a session
  (104,817 cells over the in-window sessions), so 3 more names are about
  5% of each cross-section. To lift the mean by 0.0034, those three names
  would need an IC of **about +0.08 to +0.09** on their own. The lower
  figure allows for the slight fall in per-period noise from wider
  cross-sections. That is roughly three times what the other 86 names
  did, and above the value analyst's in-window +0.033.
  - This is an approximation: a Spearman IC is not an exact weighted sum
    over names.
- **Why that is unlikely.** Their partial answers show the same confidence
  coding (40 of 138 inconsistent), so there is no reason to expect them to
  differ.
- **If it happened anyway,** the result would be a book-gate candidate,
  not a stance. The post-cutoff IC (t +0.43, 16 periods) adds no support.

## Run record and disclosures

- **22:12 ET 2026-10-01: the qwen configuration failure.**
  - What happened:
    - The first run (`d6852a8a`) sourced the deploy `.env` *after* the
      runner had set the registered model. The `.env`'s `LLM_MODEL`
      (`qwen/qwen3.5-4b`) therefore replaced `deepseek-v4-flash`.
    - The server serves only deepseek-v4-flash, so every call failed and
      0 observations were scored in 0.8 min.
    - The evaluate step still ran on nothing (every IC NaN). The check
      exited 1 with 1 MISMATCH, and the runner committed the empty result
      with a "VERDICT: RECORD" line.
    - That run also stored empty frames for the five no-observation names,
      stamped with the qwen model.
  - The fixes:
    - (a) At 22:46 ET the runner (`~/scratch/ls_spark_study.sh`, outside
      the repository) was changed to keep the study's `LLM_MODEL`/`LLM_URL`
      across the `.env` source.
    - (b) Commit **`7ff4f249`**, "an empty statements frame is compatible
      with any model". Before it, `current_frame_exists` refused the five
      qwen-stamped empty frames, so the rerun would have stopped at ASML.
      A non-empty frame under another model is still refused. Unit tests
      38 passed at `7ff4f249`.
- **The false result commit is kept, not published.** `ec609478`
  ("A2 run on the Sparks at d6852a8a", qwen, 0 observations) is held at
  the local ref **`refs/attic/llm-statements-qwen-run-1001`**. The branch
  runs `d6852a8a` → `7ff4f249` → `d6b6fea2`. `ec609478` is not on it and
  is not a result.
- **22:47 ET: guard stop.** A run at `7ff4f249` stopped before scoring
  because "a nightly or tone process is alive". The run 70 s later
  (22:48 ET) passed the guard and is the one reported here.
  - Scoring ran 22:48 to 00:59 ET, under deepseek-v4-flash at
    concurrency 4.
  - Evaluate and check ran at 00:59 to 01:00 ET, and the outputs were
    committed as `d6b6fea2`.
- **Run log message (not printed here).** The run log shows a
  `command not found` message from line 110 of the deploy `.env` when it
  is sourced. That line is not a valid shell assignment. It did not affect
  the run, but it should be corrected; its contents are not reproduced.
- **Functional test not run.** The reader's functional test
  (`test_statement_reader_behaviour.py`) has not been run. It skips without
  the runtime, and the 3,054 real answers stand in for it.

## What it means for the board

Nothing changes:

- No new analyst.
- No change to the fundamental or value analysts.
- No stance-table gate run for A2.

A local model reading eight anonymised quarters of a company's statements
ranks the book's names about as well as the fundamental analyst already
does: slightly better, by an amount that is noise. It is not reliably
better than nothing over 20 sessions. On the quarters it cannot have
memorised, it is no better than "last year's direction repeats". The value
analyst remains the stronger reader of the same facts.

## Next

1. **Optional, cheap: score the three missing calls.** This is 3 model
   calls, off-hours only (runner `STAGE=all` resumes from partials, then
   evaluate). It completes the record; it is not expected to move the
   verdict (see the bound above).
2. **If anything, register A2b before running it.** A2b would use the
   direction-signed stance, (+1 if up else −1) × |p − 0.5|, on the stored
   answers. It needs no new model calls (evaluate only), would be trial
   479, and should be registered before any number is seen.
   - The prior should be low (about 10% for the IC floor). The calls'
     edge over persistence is 1.9 points post-cutoff, and persistence of
     year-over-year growth is what the fundamental analyst's ratios already
     encode. Expect a higher correlation with the fundamental analyst and
     a paired IC near zero.
   - Alternatively, fix the prompt so that p is the probability of "up"
     (or ask for the confidence explicitly). That is a new prompt version,
     about 3,000 calls and another night on the Sparks, and is not worth
     it unless A2b shows something.
3. **Check correction (optional).** Count names the way the payload does
   (or exclude empty frames from `names_scored`), and read exact values
   for the accuracy recount. The check would then exit 0 on this run.
