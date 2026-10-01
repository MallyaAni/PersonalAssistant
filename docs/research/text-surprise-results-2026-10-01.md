# Text surprise (A1) results: the tone change and a point-in-time word surprise (2026-10-01)

**A1-1 change: RECORD. A1-3 word surprise: RECORD. A1-1 change_plus_level
and A1-1 change_gated: CANDIDATE (replacement of the tone input) on the
IC floor; the book gate is queued and decides them. Nothing moves on the
board until it has run.**

The registered test ([the plan](text-surprise-plan-2026-10-01.md),
committed at `f6493940` before any code) was built at `fb5b9b87` and ran
on spark1 at `fb5b9b87` (clean tree) on 2026-10-01 20:32-20:35Z (tests 38
passed; build, evaluate, check; results committed at `3830fcff`), on the
tone store at `~/scratch/tone/store` and the market store as of the
2026-09-30 session. Files under `docs/research/scorecards/text-surprise/`:

| File | What | sha256 |
|---|---|---|
| `text_surprise.json` | the payload: every window, horizon and arm; criteria; verdicts; null test | `516d777d90ce7cf93c303d95b220d8c7402f8d03141c60f0d6e55982a453a38a` |
| `stances/A1-1_change_plus_level.parquet` | the candidate's stance table for the book gate | `42b7cf9f02544f1d21701d44e6e97e8e8adbf322053692d1bbb5226ff7d71f70` |
| `stances/A1-1_change_gated.parquet` | the candidate's stance table for the book gate | `372ab927d0e0f154c6b26e793f707b7152cc73c69d20dd7bb7e50b0143e89bc2` |
| `stances/A1-1_change.parquet`, `stances/A1-3_word_surprise.parquet` | the RECORD arms' tables (not gated) | `b00ecafe…`, `3e4c52f8…` |

Logs: `run.txt`, `build.txt`, `evaluate.txt`, `check.txt`.

**The null test passed:** "null test (level legs reproduce A bit for bit):
PASS over 6 checks" (`evaluate.txt`), and the independent check
recomputed all 66 arm lines from the payload: "66 arm lines checked, 0
mismatches; payload null test: True" (`check.txt`; the null bit-equal
over 146 periods at 20 sessions and 48 at 60).

Inputs: A1-1, 3,548 tone releases over 94 names, 3,455 with a
predecessor. A1-3, 3,451 release texts, 3,439 labelled, 2,717 scored
walk-forward from 2018; C = 1.0 chosen on 2015-2017 only (in-sample AUC
0.637 against 0.597 at C = 0.1), refit each January.

## The verdicts

Criteria: 20-session rank IC on 2018-2025 ≥ 0.02 at t ≥ 2, **and** the
paired IC against the stored tone level not negative at t ≤ −1, **and**
the T-S1 book gate. Correlation with the tone level ≥ 0.3 makes an arm a
replacement candidate, below it a sixth analyst. A1-1 reads the in-window
cells (2018-01..2025-05, the reader's cutoff); A1-3 is point-in-time and
reads the whole window.

20-session horizon (A = the stored tone level on the same cells):

| Arm | Window | Rank IC | t | Net Sharpe | Paired vs A (t) | Corr. with A | Post-cutoff IC | IC floor |
|---|---|---|---|---|---|---|---|---|
| A stored tone | in-window | +0.0396 | +2.78 | +0.37 | | | +0.0290 | |
| A1-1 change | in-window | +0.0250 | +1.80 | +0.31 | −0.0146 (−1.03) | 0.585 | +0.0056 | fails (t, paired) |
| A1-1 change_plus_level | in-window | +0.0347 | +2.56 | +0.43 | −0.0049 (−0.64) | 0.873 | +0.0209 | **passes** |
| A1-1 change_gated | in-window | +0.0347 | +2.48 | +0.60 | −0.0049 (−0.30) | 0.477 | +0.0009 | **passes** |
| A1-3 word surprise | all | +0.0004 | +0.04 | −0.60 | −0.0355 (−2.20) | 0.040 | −0.0208 | fails |

At 60 sessions (in-window, A1-1 cells): A +0.0523 (t 2.27); change
+0.0384 (1.80); change_plus_level +0.0511 (2.41); change_gated +0.0383
(2.10). Post-cutoff at 60 (5 periods): A +0.0471; change −0.0162;
change_plus_level +0.0180; change_gated −0.0103.

The criteria and verdict lines, verbatim (`evaluate.txt`):

```
=== criteria (primary horizon) ===
A1-1 change: IC +0.0250 (t +1.80) on in_window, post +0.0056, paired vs A -0.0146 (t -1.03), corr +0.585 -> replacement candidate
A1-1 change_plus_level: IC +0.0347 (t +2.56) on in_window, post +0.0209, paired vs A -0.0049 (t -0.64), corr +0.873 -> replacement candidate
A1-1 change_gated: IC +0.0347 (t +2.48) on in_window, post +0.0009, paired vs A -0.0049 (t -0.30), corr +0.477 -> replacement candidate
A1-3 word surprise: IC +0.0004 (t +0.04) on all_window, post -0.0208, paired vs A -0.0355 (t -2.20), corr +0.040 -> sixth analyst

=== verdicts ===
A1-1 change: RECORD
A1-1 change_plus_level: CANDIDATE (replacement candidate): clears the IC floor on in_window; proposed as a stance only if the T-S1 book gate holds (pending)
A1-1 change_gated: CANDIDATE (replacement candidate): clears the IC floor on in_window; proposed as a stance only if the T-S1 book gate holds (pending)
A1-3 word surprise: RECORD
```

## What it means for the board

Nothing yet, and probably nothing. The tone *change* by itself does not
rank the book's names at 20 sessions (IC 0.025, t 1.8; post-cutoff
0.006). The learned word surprise ranks nothing (IC 0.0004) and is worse
than the tone level at t −2.2: what predicts the next-day reaction
(in-sample AUC 0.64) does not carry to 20 sessions, which is what the
plan's prior and the literature on large caps said. The two arms that
clear the floor do so by keeping the level in them (change_plus_level
correlates 0.87 with it) or by using the change only when it is large;
both score *below* the stored tone level on the same cells (0.0347
against 0.0396), not above it. Clearing the floor means they are not
significantly worse than the level, not that they are better; the book
gate decides, and the prior was 10%. change_gated's post-cutoff IC is
0.0009, so even a gate pass would rest on the in-window cells alone.

## The book gate (queued)

`desk/stance-table` (`e67213d1`) was merged into `research/text-surprise`
(`978143b5`, clean; its 67 tests and the A1 tests pass on the merged
tree). Per [stance-table-gate.md](stance-table-gate.md), a replacement
candidate replaces the tone input: `--stance-mode replace:sentiment`.
`~/scratch/ts_gate.sh` (nohup, nice 19, from `~/scratch/wt-ts`) waits for
2026-10-02 00:45Z (20:45 ET) and runs, in order, with `--root
~/deploy/anios/data/market --graded-cap 0.25` (20 offsets, 10 and 25 bp):

1. the null test for each table (`--stance-table … --null-test`); a
   failure aborts the run;
2. the control on the merged tree and tonight's store (`--rank-ic`,
   `pit_scorecard_control.json`);
3. each candidate, `--stance-mode replace:sentiment`
   (`pit_scorecard_A1-1_change_plus_level.json`,
   `pit_scorecard_A1-1_change_gated.json`);
4. the pairing (`~/scratch/ts_gate_pair.py`, reusing
   `backend.market.vol_target`'s paired-difference and offset code from
   `~/scratch/wt-vt`), written to `gate_verdict.txt`.

Log: `~/scratch/ts_logs/gate.txt`. How to read it:

- `null … exit 0` with `verdict: PASS, reproduced to the bit` and a
  non-zero `rows_used` for each table, or nothing after it counts.
- In `gate_verdict.txt`, per arm: the paired 2016-2023 difference must be
  ≥ +2.00 bp a session at NW t ≥ 2; the 2024-2026 mean must be ≥ 0; the
  candidate must be above the control at ≥ 15 of 20 offsets; DSR at 471
  ≥ 0.95. The line ends `GATE HOLDS` or `GATE FAILS (…) -> RECORD`.
- A HOLDS is a proposal to replace the tone input in the grade, for the
  operator; it is not deployed.

## Disclosed deviations

- The gate's pairing command does not exist on this branch
  (`stance-table-gate.md`: "a stance-table verdict command … is the
  follow-up"). `ts_gate_pair.py` applies the plan's T-S1 numbers with the
  vol-target branch's helpers; the DSR trial variance is the variance of
  the two candidates' paired Sharpes on 2016-2023 (two values), at the
  cumulative 471.
- The gate's model window is the scorecard's 2016-2023 (as S1g's was);
  the IC floor's window is 2018-2025.
- The gate runs on the market store after tonight's 19:30 ET nightly, a
  session later than the IC evaluation; control and candidates share
  that store, and the log records any store file changed during the run.
- The plan named 3,451 releases for 89+4 names; A1-1 used 3,548 releases
  over 94 names (the tone store after the 6-K backfill).

Trials: 4 registered; cumulative 467 → 471.
