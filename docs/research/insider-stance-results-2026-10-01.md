# Insider trades (A4) results: net Form 4 buying over 90 sessions as a stance (2026-10-01)

**RECORD, both registered arms. No insider stance is proposed; the book
gate was not run.**

The registered test ([the plan](insider-stance-plan-2026-10-01.md),
committed at `0f47ae71` before any code) was built at `3f823048` and ran
on spark1 at `3f823048` (clean tree; `~/scratch/ins_spark_study.sh` via
`~/scratch/ins_run.log`, `~/research-venv`, CPU, nice 19). The build's 21
tests passed at 20:32Z; the run then waited for the SEC off-peak window
(after 21:00 New York) and fetched the SEC Insider Transactions Data Sets
at 01:02-01:05Z on 2026-10-02 (21:02-21:05 ET on 2026-10-01), built at
01:35-01:37Z, evaluated and checked by 01:38Z, and committed its outputs at
`afc5529f`. Store as of the 2026-10-01 session; insider partition
`edgar_insiders/asof=2026-10-02`. Files under
`docs/research/scorecards/insider-stance/`:

| File | What | sha256 |
|---|---|---|
| `insider_stance.json` | evaluation payload: windows, horizons, null test, criteria, verdicts | `ce0538e17b405f13eb4669048dee1e2e59c88e7cff35e2c52135888faa95ed37` |
| `insider_rows.parquet` | the 157,380 admitted, dated book rows | `0a826b818ad6d6b196e76b16d9e8164704d0a43438876bea4ff8678930819b87` |
| `signals.npz` | the two arms' per-session signals (2,954 sessions × 95 names) | `7b951a414971e292120672b8d69a04143755b45d707c879bf66dc22a37fdf90c` |
| `build.json` | row counts, refusals, classification, per-name coverage | `a6fdcc28e827cea77937063c9b413093ac97cf1eeee8c98479e543826392cd6f` |
| `stances/A4-opp_opportunistic_insiders.parquet` | stance table, opportunistic arm | `cf0bbcbbba74dd25666ac86ab29060fb7edd24de527be31e7dd9fee35e8f2468` |
| `stances/A4-all_all_insiders.parquet` | stance table, all-insiders arm | `26e81614a3b725e76bda29ee46d8807cac6916e4f98e41c031c9ece6a439a59a` |

Logs: `run.txt`, `fetch.txt`, `build.txt`, `evaluate.txt`, `check.txt`.

**The null test passed**, before either arm was read (`evaluate.txt`):
"null test (empty table: zero signal, rank 0.5, no stance, no IC): PASS
{'zero_where_denominator': True, 'nan_only_without_denominator': True,
'rank_half_everywhere': True, 'stances': 0, 'defined_ics': 0}". The
independent check (`insider_stance_check.py`, committed with the build)
re-derived the row dating (157,380 rows known strictly after their
filing date, 0 on or before), the sign of the dollars from the
transaction code, the null's zero defined ICs, and every cell count, IC
and t in the payload for both horizons and all four windows: "ALL OK".

## What was measured

From 82 quarterly SEC zips (2006q1-2026q2), 3,502,773 stored P/S rows;
202,250 on the book's issuers, 157,383 admitted (refused: 37,007 flagged
10b5-1 plan trades, 6,561 with no officer or director, 1,297 amendments
or non-Form-4, 2 without shares), 157,380 dated on the panel. Routine
classification of admitted rows: 16,109 opportunistic, 34,047 routine,
79,735 unclassifiable (fewer than three prior years of trades). The book
is a large-cap seller's book: 155,500 sales against 1,880 purchases, and
only 137 opportunistic purchases in twenty years. In 2018-2025 the
opportunistic signal is nonzero on 38% of defined cells and positive on
1.1%; the all-insiders signal is nonzero on 80% and positive on 4.4%. So
the cross-section is ranked almost entirely by how much insiders sold.

## The verdicts

Registered criteria: an arm is proposed as a stance if its 20-session
rank IC on 2018-01..2025-12 is ≥ 0.02 with t ≥ 2, **and** the halves
(2018-2021, 2022-2025) are not opposite in sign, **and** its paired IC
against the desk is not negative at t ≤ −1, **and** the T-S1 book gate
holds on its stance table. Anything else is RECORD.

The verdict lines, verbatim (`evaluate.txt`):

```
=== criteria (primary horizon) ===
A4-opp opportunistic insiders: IC -0.0061 (t -0.50) on in_window, halves +0.0034 / -0.0112, 2026 +0.0390, paired vs desk -0.0662 (t -3.22), corr -0.014 -> sixth analyst
A4-all all insiders: IC -0.0240 (t -1.54) on in_window, halves -0.0330 / -0.0067, 2026 +0.0178, paired vs desk -0.0841 (t -3.32), corr -0.134 -> sixth analyst

=== verdicts ===
A4-opp opportunistic insiders: RECORD
A4-all all insiders: RECORD
```

("-> sixth analyst" is the role the correlation rule would assign, not a
proposal; both arms are RECORD.)

| Arm | IC ≥ 0.02, t ≥ 2 | Halves same sign | Paired vs desk not ≤ −1 t | Book gate |
|---|---|---|---|---|
| A4-opp | fails (−0.0061, t −0.50) | fails (+0.0034 / −0.0112) | fails (−0.0662, t −3.22) | not run |
| A4-all | fails (−0.0240, t −1.54) | passes (−0.0330 / −0.0067) | fails (−0.0841, t −3.32) | not run |

Horizon 20 (registered), beta-adjusted residual, 161,590 shared cells in
window:

| Window | Desk IC (t) | A4-opp IC (t) | A4-all IC (t) | Desk / opp / all net Sharpe | Periods |
|---|---|---|---|---|---|
| 2018-2025 | +0.0601 (+3.73) | −0.0061 (−0.50) | −0.0240 (−1.54) | +0.77 / +0.24 / −0.17 | 101 |
| 2018-2021 | +0.0715 (+3.20) | +0.0034 (+0.18) | −0.0330 (−1.39) | +0.70 / +0.04 / −0.47 | 51 |
| 2022-2025 | +0.0441 (+2.02) | −0.0112 (−0.87) | −0.0067 (−0.32) | +0.89 / +0.44 / +0.38 | 51 |
| 2026 (out of window) | +0.1611 (+2.20) | +0.0390 (+1.50) | +0.0178 (+0.44) | +2.86 / +1.61 / −0.60 | 9 |

Paired against the desk (2018-2025): A4-opp −0.0662 (t −3.22), rank
correlation with the desk −0.014; A4-all −0.0841 (t −3.32), correlation
−0.134.

Horizon 60 (reported): 2018-2025 desk +0.0618 (t +2.27), A4-opp −0.0018
(t −0.09), A4-all −0.0188 (t −0.71), 34 periods; 2026 A4-opp +0.0462
(t +3.37) on **3 periods**, which is not evidence of anything.

## What it means for the board

Nothing changes: no sixth analyst, no replacement, no stance table goes
to the book gate, and nothing is proposed for live. Because no arm
cleared the IC floor, the stance-table merge and the T-S1 book gate
(`docs/research/stance-table-gate.md`) were not launched, and there are
no book returns or drawdowns to compare with the control, SPY or QQQ for
this study.

In plain words: on these 94 large caps, knowing how much insiders bought
or sold over the last 90 sessions told you nothing about which names
would do better over the next month. The opportunistic filter, which is
where the published effect lives, leaves a signal that is mostly "sold
less than usual"; real opportunistic buying happened 137 times in twenty
years across the whole book. The all-insiders version leans slightly the
wrong way (heavy sellers did a little better, consistent with insiders
selling into strength in winners), at t −1.5. The plan's prior (15% that
an arm clears the IC floor) and its likely finding (IC near zero, thin
opportunistic residue) both held.

## Disclosed deviations and notes

- **Two quarters not fetched.** `fetch.txt`: 2026q3 and 2026q4 returned
  HTTP 404 on three attempts. 2026q4 has not happened and 2026q3 (closed
  2026-09-30) is not yet published; the SEC index listed 82 zips, as the
  plan recorded, and all 82 were stored. The run built on what was
  stored, as its script provides. Effect: filings from 2026-07-01 on are
  absent, so the 2026 out-of-window figures for sessions after early July
  read a trailing window missing its newest filings. The registered
  2018-2025 window is complete.
- **Four foreign private issuers have 2026 rows.** The plan expected TSM,
  ASML, ARM, NBIS and SIMO to file no Form 4 and sit at zero. ASML has no
  row; TSM (107 rows), ARM (22), NBIS (8) and SIMO (6) have officer and
  director filings dated 2026-03-24 to 2026-06-30, mapped by issuer CIK,
  consistent with Section 16 reporting reaching foreign private issuers'
  insiders in 2026. All are in the out-of-window period; the registered
  window has them at zero as planned.
- **The 10b5-1 flag exists only since the 2023 form change**, so plan
  trades before 2023 are admitted and left to the routine rule, as the
  plan disclosed; 37,007 flagged rows were refused after it.
- Three admitted rows (157,383 against 157,380) did not date on the
  panel (the build does not log which); the check and the signal use the
  157,380 dated rows.
- Runtime warnings (empty-slice means in `regime.py` and `levels.py`) are
  from the early, thin part of the panel, as in every desk run.
- The fetch wrote 82 `edgar_insiders` frames and zips into the shared
  store at 01:02-01:05Z, while the B2 regime-gross run and the
  text-surprise book gate were reading it; neither reads those frames,
  and no price, panel or desk file changed in that window (checked by
  mtime). The text-surprise gate's log notes "store files changed during
  the run: 82"; these are those files.

Trials: 2 registered; cumulative 478 → 480.
