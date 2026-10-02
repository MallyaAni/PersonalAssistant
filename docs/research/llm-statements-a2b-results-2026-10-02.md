# LLM statement reading, second look (A2b): results (2026-10-02)

**Verdict: CANDIDATE (sixth analyst), pending the book gate.** The stored
answers, re-signed by the model's stated direction (`d × |2p − 1|`), clear
all three registered criteria at 20 sessions: in-window IC **+0.0418
(t +2.38)**, post-cutoff **+0.0408 (t +1.73)**, paired against the
fundamental analyst **+0.0175 (t +0.89)**. The rank correlation is +0.223
with the fundamental analyst and −0.038 with the value analyst, both below
0.3, so the role is sixth analyst. Nothing changes on the board: under the
plan a candidate becomes a stance only if the T-S1 book gate holds, and
that gate has not been run.

Plan: [`llm-statements-a2b-plan-2026-10-02.md`](llm-statements-a2b-plan-2026-10-02.md)
(`4bd826fa`, committed alone and pushed before any A2b code or number).
Build: `a18d7846`. Run on spark1: `ea456e4f`. Files are in
`docs/research/scorecards/llm-statements/` (`*_a2b*`, `a2b_*`,
`check_a2_replay.txt`, `stances/A2b*.parquet`). Trials: 2 registered;
cumulative **488 → 490**.

## The verdict lines (verbatim, `evaluate_a2b.txt`)

```
null test (constant 0.5 reads as scoreless): PASS over 5 checks

=== criteria (primary horizon) ===
IC in-window +0.0418 (t +2.38); post +0.0408 (t +1.73); paired vs fundamental +0.0175 (t +0.89); role sixth analyst

second look (decides nothing): in-window t +2.38 against the two-look floor 2.28: clears

VERDICT: CANDIDATE (sixth analyst): clears the IC floor in-window, the post-cutoff window does not contradict it, not worse than the fundamental analyst; proposed as a stance only if the T-S1 book gate holds (pending)
```

The secondary (`evaluate_a2b_direction.txt`, decides nothing):

```
IC in-window +0.0255 (t +1.71); post +0.0486 (t +1.78); paired vs fundamental +0.0012 (t +0.06); role sixth analyst
second look (decides nothing): in-window t +1.71 against the two-look floor 2.28: does not clear
VERDICT: RECORD
```

## The null test: PASS, reproduced to the bit

`evaluate --stance-variant a2 --reproduce llm_statements.json` rebuilt A2's
original stance (p − 0.5) through the A2b code path. It compared the result
with the committed A2 payload (`d6b6fea2`) by the IEEE-754 bytes of every
number in `null_test`, `horizons` (every arm's IC, t, net Sharpe, periods
and per-period ICs, the cells, the paired differences and the
correlations, at both horizons and in both windows), `criteria`, `verdict`
and the counts:

```
reproduce docs/research/scorecards/llm-statements/llm_statements.json: PASS, reproduced to the bit
stance table A2 replayed: 71962 rows, committed 71962: IDENTICAL
```

The store was therefore the one A2 read. The `edgar_statements`
partition was last written at 00:59 ET, and the panel and comparators are
unchanged. A2's own constant-0.5 null test also passed (5 checks) in every
run.

## The registered criteria (primary stance, 20 sessions)

| # | Criterion (A2's, unchanged) | A2b measured | Result |
|---|---|---|---|
| 1 | In-window IC (2018-01..2025-05) ≥ 0.02 **with t ≥ 2** | +0.0418, t +2.38 (86 periods, 50 positive) | passes |
| 2 | Post-cutoff IC (2025-06 on) not negative at t ≤ −1 | +0.0408, t +1.73 (16 periods, 10 positive) | passes |
| 3 | Paired IC against the fundamental analyst not negative at t ≤ −1 | +0.0175, t +0.89 (86 periods) | passes |
| role | Mean rank correlation < 0.3 with both the fundamental and the value analyst | +0.223 / −0.038 in-window; +0.174 / −0.041 post | sixth analyst |

## Tables

**Rank IC on shared cells, beta-adjusted residual.** The cells are the
same as A2's: 104,817 in-window and 26,608 post-cutoff. The comparators'
numbers are A2's, as the replay shows.

| Horizon | Window | A2b `d × \|2p−1\|` | A2b-dir `d` | A2 `p − 0.5` (recorded) | Fundamental | Value | A2b − fundamental (paired t) | Periods |
|---|---|---|---|---|---|---|---|---|
| 20 | in-window | **+0.0418 (t +2.38)**, net Sharpe +0.13 | +0.0255 (t +1.71) | +0.0275 (t +1.78) | +0.0243 (t +1.16) | +0.0334 (t +1.56) | +0.0175 (+0.89) | 86 |
| 20 | post-cutoff | **+0.0408 (t +1.73)**, net Sharpe +1.93 | +0.0486 (t +1.78) | +0.0112 (t +0.43) | −0.0251 (t −0.90) | +0.0759 (t +2.21) | +0.0660 (+1.70) | 16 |
| 60 | in-window | +0.0103 (t +0.32) | −0.0124 (t −0.43) | +0.0291 (t +1.31) | −0.0077 (t −0.23) | +0.0689 (t +1.73) | +0.0180 (+0.53) | 29 |
| 60 | post-cutoff | +0.0810 (t +2.41) | +0.0865 (t +1.64) | +0.0425 (t +0.87) | −0.0105 (t −0.16) | +0.0877 (t +1.94) | +0.0915 (+1.63) | 5 |

The 60-session rows, the secondary and the A2 column are reported and
decide nothing.

**Stance tables** (the analyst's 30% / 3-session rule, rows on which the
stance is not neutral):

| Table | Rows | Bullish | Bearish |
|---|---|---|---|
| `stances/A2.parquet` (A2, recorded) | 71,962 | 42,203 | 29,759 |
| `stances/A2b.parquet` (gate candidate) | 112,098 | 53,745 | 58,353 |
| `stances/A2b-dir.parquet` (not a candidate) | 114,828 | 42,940 | 71,888 |

## The independent check: ALL OK, three times

`llm_statements_check.py --variant` rebuilt each stance from the frames'
`direction` and `probability` columns with its own sign rule,
carry-forward, ranks, schedule and Spearman. It also recomputed the paired
difference, both correlations, the three criteria, the role and the
verdict. Every line matched:

- `check_a2b.txt`: ALL OK. All 12 IC lines, 4 cell counts, the paired
  difference and t, both correlations, all three criteria, the role and
  the verdict (CANDIDATE) match.
- `check_a2b_direction.txt`: ALL OK (RECORD).
- `check_a2_replay.txt`: ALL OK on the committed A2 payload with
  `--variant a2`. This is a second, independent replay of A2.
- **A2's recorded "names scored 86 payload 91" line is fixed.** The check
  now counts every book name with a frame, as the payload does: 91,
  including 86 with answers. The accuracy recount was not run, because the
  answers are unchanged.

## Reading it (the plan's disclosures applied)

- **This is a second look at the same answers, made after A2 failed.** The
  plan charged for that before any number:
  - Two trials (490). The book gate's deflated Sharpe will be computed at
    490.
  - A reported two-look floor. The in-window t of 2.38 clears it (2.28),
    but only by 0.10. The per-period IC dispersion is about 0.163, so the
    margin over the registered t 2 is about 0.007 of IC. That is less than
    one A2b-vs-A2 difference.
- **Post-cutoff agrees in sign and in size.** The post-cutoff point
  estimate (+0.0408) matches the in-window one (+0.0418), and is positive
  in 10 of 16 periods. Under the plan's reading rule, the in-window IC is
  therefore not set aside as look-ahead. On its own the post-cutoff window
  is not significant (t 1.73, 16 periods). It is "does not contradict",
  which is what criterion 2 asks.
- **The sign fix is what moved the number.** Changing only the sign of the
  1,124 inconsistent down calls took the in-window IC from +0.0275 to
  +0.0418, and post-cutoff from +0.0112 to +0.0408. The stated direction
  carries information that A2's stance threw away.
- **The confidence adds in-window, not post-cutoff.** The sign alone gives
  +0.0255 in-window and +0.0486 post-cutoff.
- **What still argues for caution:**
  - The in-window 60-session IC is only +0.0103 (t +0.32), against A2's
    +0.0291. The 20-session edge does not persist to 60 sessions on the
    contaminated window.
  - The in-window net Sharpe is +0.13, below the fundamental analyst's
    +0.15 and the value analyst's +0.54. The quarterly re-signing turns
    the book over.
  - On every window, the value analyst is still the stronger reader of the
    same facts.

  None of these points is a registered criterion. The book gate is the
  measure that prices all of them.
- **The correlation with the fundamental analyst rose, as the plan
  expected** (+0.144 for A2, +0.223 for A2b). It is still below 0.3.
- **One statement in the plan was wrong.** The plan said the secondary
  (±1) "will rarely or never produce a bullish stance" under the 30% rule.
  It produced 42,940 bullish rows. When fewer than about 60% of a
  session's names are "up" calls, the tied up-block's average rank clears
  0.7. The secondary decides nothing, so this changes nothing.
- **Coverage is as A2's.** It covers 86 names and 2,916 answers. META,
  MPWR and SWKS each lack one call and are not stored. The A2 results bound
  how much three names could move a 56-name cross-section.

## Is a book gate warranted? Yes

The primary clears the IC floor and the other two criteria, so the plan's
next step applies: the stance-table book gate per
`docs/research/stance-table-gate.md` (branch `desk/stance-table`,
`e67213d1`), in **sixth** mode (the role). It is not run here. The rules
for running it:

- **When:** after 16:15 ET only, never during 19:20-19:55 ET, and not on
  top of the running cluster-cap study.
- **Order:**
  1. Merge `desk/stance-table` into `~/scratch/wt-a2b`.
  2. Run `market_pit_scorecard --graded-cap 0.25 --stance-table
     docs/research/scorecards/llm-statements/stances/A2b.parquet
     --null-test` first. It must print "PASS, reproduced to the bit", and
     `rows_used` must be read before trusting the PASS.
  3. Run the control.
  4. Run the candidate (`--stance-mode sixth --rank-ic --output
     .../pit_scorecard_A2b.json`).
- **The T-S1 gate** (from the plan):
  - +2 bp of equity a session at 25 bp over `graded-equal-weight/5`;
  - NW t ≥ 2 on the model window, and not negative after;
  - 15 of 20 offsets;
  - deflated Sharpe at **490** ≥ 0.95.
- **The pairing verdict command still has to be written** (the gate doc's
  open follow-up). The payloads carry the `curves` and `cagrs` it needs.

The plan's prior for the gate was about 3%. The A2b stance table holds
112,098 non-neutral name-sessions (53,745 bullish, 58,353 bearish). As a
sixth vote each one moves grades: a bull lowers by one the votes a name
needs, and a bear raises it by one without a veto. So the gate is a real
test, not a formality.

## Run record

- **Sandbox:** worktree `/home/claude/wt-a2b` from
  `origin/research/llm-statements` (`db014bd6`), on the new branch
  `research/llm-statements-a2b`.
  - The plan `4bd826fa` was bundled and pushed to GitHub from spark1
    (`~/dspark-commit`) before any code was written. The sandbox's own
    push is refused by its git proxy.
  - Build `a18d7846` passes 43 tests (statements, reader, CLI; 5 new) and
    `ruff check` and `ruff format` are clean.
- **spark1, `~/scratch/wt-a2b` at `a18d7846`** (clean tree), run by
  `~/scratch/a2b_spark_study.sh` at nice 19 with
  `PYTHONPATH=$PWD CUDA_VISIBLE_DEVICES= SECRET_KEY=a2b-research-only
  MARKET_DATA_ROOT=~/deploy/anios/data/market`. The deploy `.env` was not
  sourced. No model server was used and nothing was written to the store.
  The timeline (UTC, from `a2b_run.txt`):

  | Time (UTC) | Step | Result |
  |---|---|---|
  | 18:45:04 | start | rev `a18d7846` |
  | 18:45:05 | tests | 43 passed |
  | 18:45:35 | null test | PASS to the bit |
  | 18:45:35 to 18:46:25 | the two evaluations | both exit 0 |
  | 18:46:48 to 18:47:32 | the three checks | ALL OK each |

  It started at 14:45 ET, in market hours, which the plan permits for this
  CPU-light step. The cluster-cap study (`cc_spark_study_now.sh`) was
  running alongside and was not touched.
- **The outputs** were committed on spark1 as `ea456e4f`, fetched back by
  bundle, and pushed with this note.
