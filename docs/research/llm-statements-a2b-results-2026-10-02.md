# LLM statement reading, second look (A2b): results (2026-10-02)

**Book gate (2026-10-02, after the close): FAILS → A2b is RECORD.** As a
sixth analyst on the point-in-time scorecard, A2b adds +0.46 bp a session
on 2016-2023 (t +0.71; the gate needs +2.00 at t ≥ 2), −0.30 bp on
2024-2026 (must not be negative), is above the control at 16 of 20
offsets (passes), and has a deflated Sharpe of 0.45 at 490 trials (needs
0.95). Nothing is proposed for the board. See "The book gate" below.

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

## The book gate (T-S1): FAILS, so A2b is RECORD

Run on spark1 on 2026-10-02, 20:41:57-20:56:53Z (**16:41-16:56 ET, after
the close**, before the 19:20-19:55 nightly window), by
`docs/research/scorecards/llm-statements/a2b_gate.sh` at nice 19 on CPU,
store `~/deploy/anios/data/market` (as of the 2026-10-01 session), read
only. Tree: `~/scratch/wt-a2b` at `19461329`, clean: `desk/stance-table`
(`e67213d1`) merged in at `7a517783`, then the runner and the pairing
script committed and pushed **before** the gate ran. No deploy or nightly
was running at the start.

**Steps, per `stance-table-gate.md`:**

1. **Null test** (`--stance-table stances/A2b.parquet --null-test`):
   "112098 rows, 112098 on the panel" (rows_used = 112,098, none dropped
   or redirected); "grades and scores equal: True / lines compared: 24 /
   verdict: PASS, reproduced to the bit". Table sha256
   `b784327212a62c07bbb1338deb56f0c3e79be15769195163b7e4821cfed22791`.
2. **Control**, fresh on the same tree and store (`--rank-ic`):
   `pit_scorecard_control.json`.
3. **Candidate**, `--stance-mode sixth --rank-ic`:
   `pit_scorecard_A2b.json` (arm `ew_graded_cap25 + stance_sixth`).
4. **Pairing**: `a2b_gate_pair.py`, the pattern of last night's A1 gate
   (`ts_gate_pair.py`, `research/text-surprise` `e1a8286e`), using
   `backend.market.vol_target`'s paired-difference and offset helpers
   from `research/vol-target` (`e6ff1ee2`). Rule line at 25 bp, median
   offset, Newey-West t at lag 20.

**The gate**, against the fresh control:

| Criterion | Needs | A2b | Result |
|---|---|---|---|
| Paired 2016-2023 | ≥ +2.00 bp a session at t ≥ 2 | **+0.46 bp (t +0.71)**, 2012 sessions | fails |
| Paired 2024-2026 | mean not negative | **−0.30 bp (t −0.18)**, 690 sessions | fails |
| CAGR above the control, 2016-2023 | ≥ 15 of 20 offsets | **16 of 20** (2024-2026: 12 of 20, reported) | passes |
| Deflated Sharpe at 490 | ≥ 0.95 | **0.45** | fails |

The verdict, verbatim (`gate_verdict.txt`):

```
T-S1 gate, A2b (sixth analyst) against ew_graded_cap25 as of 2026-10-01, 25 bp, trials 490, trial variance 3.38e-05 (pooled over 3 stance-gate candidates)
  pool: pit_scorecard_A1-1_change_plus_level 2016-2023 paired Sharpe +0.0060 (mean +0.22 bp, t +0.24)
  pool: pit_scorecard_A1-1_change_gated 2016-2023 paired Sharpe +0.0170 (mean +0.97 bp, t +0.77)
  pool: A2b 2016-2023 paired Sharpe +0.0147
A2b (ew_graded_cap25 + stance_sixth): paired 2016-2023 +0.46 bp/session (t +0.71, 2012 sessions); 2024-2026 -0.30 (t -0.18, 690); above the control at 16 of 20 (2024-2026: 12 of 20); DSR 0.45 at 490
  reported: DSR at the A1-only variance 6.07e-05: 0.34; PSR against zero (no trial penalty): 0.75
  2016-2023: CAGR +30.8% vs +28.3%; worst drawdown -46.1% vs -45.5%; Sharpe 1.04 vs 1.00
  2024-2026: CAGR +44.8% vs +47.0%; worst drawdown -26.7% vs -26.4%; Sharpe 1.25 vs 1.28
  GATE FAILS (+2 bp at t>=2 (2016-2023); not negative 2024-2026; DSR >= 0.95) -> RECORD
```

**CAGR and worst drawdown**, rule line at 25 bp, median of 20 offsets
(from `gate_control.txt` and `gate_A2b.txt`):

| Line | 2016-2023 CAGR | Worst DD | Sharpe | 2024-2026 CAGR | Worst DD | Sharpe |
|---|---|---|---|---|---|---|
| Control (`ew_graded_cap25`) | +28.3% | −45.5% | 1.00 | +47.0% | −26.4% | 1.28 |
| A2b as sixth analyst | +30.8% | −46.1% | 1.04 | +44.8% | −26.7% | 1.25 |
| Difference | +2.5 pts | 0.6 pts deeper | +0.04 | −2.2 pts | 0.3 pts deeper | −0.03 |
| SPY | +13.2% | −33.7% | 0.76 | +20.3% | −18.8% | 1.27 |
| QQQ | +18.6% | −35.1% | 0.86 | +24.9% | −22.8% | 1.17 |

**What the sixth vote did to the grades** (the payload's
`stance_tables`; eligible name-sessions):

| Window | Moved | Up | Down | A+ before → after | A before → after |
|---|---|---|---|---|---|
| 2016-2023 | 10,258 of 58,794 (17%) | 5,972 | 4,286 | 8,318 → 8,053 | 4,922 → 5,792 |
| 2024-2026 | 3,661 of 29,551 (12%) | 2,140 | 1,521 | 2,060 → 1,906 | 1,382 → 1,695 |

### What this means in plain words

The LLM's reading of the quarterly statements does rank stocks a little
(the IC test), but adding it as a sixth vote does not make the book
better by a margin anyone could rely on. It changed about one grade in
six and, on 2016-2023, earned about half a basis point a day more than
the book without it. That is a quarter of the bar, and statistically
indistinguishable from zero (t 0.71). On 2024-2026 it earned slightly
less (−0.3 bp a day, −2.2 CAGR points). In both windows the worst fall
was slightly deeper. It beat the control's CAGR at 16 of 20 start dates
on 2016-2023, so the in-window gain is consistent across start dates, but
it is small. It reverses in the recent window, where the model could not
have read the future. **A2b is not worth proposing for live.**

### Disclosures

1. **The trial variance for the deflated Sharpe.** With one A2b
   candidate, there is no variance across its own candidates. The rule
   was fixed in `a2b_gate_pair.py` and committed (`19461329`) before any
   A2b book number existed. The rule is the sample variance of the
   2016-2023 paired Sharpes of every stance-table book-gate candidate run
   to date: A1-1 change_plus_level, A1-1 change_gated and A2b, each
   against its own control. That variance is 3.38e-05, giving a DSR of
   0.45. The result does not hinge on this choice: at A1's own variance
   (6.07e-05) the DSR is 0.34, and with no trial penalty at all (PSR
   against zero) it is 0.75. No trial variance would reach 0.95.
2. **The A1 payloads in the pool are not committed.** They come from last
   night's A1 gate (2026-10-02 00:45-01:10Z) on `~/scratch/wt-ts` at
   `e1a8286e`, and that gate's outputs are still untracked there. sha256:
   - control `8ce18f11742d6abc02aaccc227c1e9fddfe417df4f3061ee148e2d27361a3ff3`
   - change_plus_level `1d8196c3a54362c14f38a196bb42d426492102bc46d82379f13d90692fd8fdc3`
   - change_gated `04a69b45fa207b9b0678c97dba14428e0f381b2889a2971c0855d792a7ec337a`
3. **The control differs slightly from the A1 gate's control.** Both read
   the store as of 2026-10-01, on different trees. This control:
   2016-2023 +28.3% / −45.5% / Sharpe 1.00, 2024-2026 +47.0% / −26.4% /
   1.28. A1's: +28.0% / −45.5% / 0.98 and +46.7% / −26.4% / 1.26. The
   cause was not traced. The gate pairs A2b only with the control from
   its own run, on the same tree and store.
4. **Store writes during the run.** Four files changed, all under the live
   desk's state (`desk/intraday.json`, `desk/live.json`,
   `desk/intraday.log`, `desk/event-live.json`). The price bars and
   corporate actions were not written during the run.
5. **Files.** These are under `docs/research/scorecards/llm-statements/`:
   - `gate_run.txt`, `gate_null_A2b.txt`, `gate_control.txt`,
     `gate_A2b.txt` and `gate_verdict.txt`
   - `pit_scorecard_control.json` (sha256 `e64e5b5fc2c76d38f6ec7b03415445b1c586cd145389754ffa86a9ef3876ed32`)
   - `pit_scorecard_A2b.json` (sha256 `7f91f5ebe8896b7c25c776f9c050d05c79d1f77c5d20cc7b17e05937e2a7ac6d`)
   - `a2b_gate.sh` and `a2b_gate_pair.py`
6. **Trials.** None are added here. The gate is the book test of the
   registered A2b primary, and its deflated Sharpe is charged at the
   cumulative 490.
