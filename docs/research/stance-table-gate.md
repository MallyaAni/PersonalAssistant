# The stance-table gate: a proposed analyst's stance on the point-in-time scorecard (2026-10-01)

Branch `desk/stance-table`, from `95424784` (main). Built in the sandbox
and tested there; no run on real data (the desktop bridge to spark1 was
down). This is the shared piece the three stance studies recorded as
"the book gate needs a sixth-stance path on the scorecard": text surprise
(A1, `research/text-surprise`), LLM statement reading (A2,
`research/llm-statements`) and insider trades (A4,
`research/insider-stance`). Each of their `evaluate` steps writes a stance
table and records the command below in its payload under
`scorecard_follow_up`; the command now exists.

## What was built

- `backend/agents/trading/desk/stance_table.py`: reads a table, lays it
  onto a panel point in time, and re-grades a desk report with it.
- `backend/agents/trading/desk/grading.py`: `grade_stances` and `grade`
  take `extra`, further named stances that vote under the unchanged rule.
- `backend/cli/market_pit_scorecard.py`: `--stance-table FILE`
  (repeatable), `--stance-mode {sixth,replace:<analyst>}`, `--null-test`,
  and from `research/structure-rules` (`a3041068`) the same `--rank-ic`,
  `--membership`, `--output`, per-row `cagrs` and `worst_drawdown`, and
  the median-offset `curves` block, so a candidate payload can be paired
  with its control session by session the way S1g's was.
- Tests: `backend/tests/test_stance_table.py` (7, one parquet case
  skipped without pyarrow), the stance test in
  `test_market_pit_scorecard.py`, the `extra` test in
  `test_trading_grading.py`.

## The table

The three studies write the same long-form table, one row per (session,
name) on which the arm's own persisted stance (its 30%/3-session rule) is
not neutral, as parquet:

| column | meaning |
|---|---|
| `session` (or `date`) | the session the stance holds on, `YYYY-MM-DD` |
| `ticker` (or `name`, `symbol`) | the book name |
| `stance` | -1, 0 or 1 |
| `conviction` (optional) | in [-1, 1]; or `rank` in [0, 1], turned into one as the analysts' ranks are |

CSV is read the same way. The file's sha256 is recorded in every payload.

**The date rule.** A row dated `d` applies to the first panel session on
or after `d` and to that session only. Nothing is carried forward: the
tables are dense (the arm writes its stance on every session it holds,
and a session with no row is neutral), so carrying a row forward would
turn a stance the arm had dropped into one it still held. A row dated
after a session cannot touch it (`test_align_is_point_in_time_and_neutral_where_silent`
proves it for every session), a row dated on a weekend lands on the
Monday, a row after the panel's last session or before its first is
unused, a name the panel lacks (and the benchmark) is ignored, the later
of two rows on one cell wins, and every dropped or redirected row is
counted in the payload (`rows_used`, `rows_after_panel`,
`rows_before_panel`, `rows_unknown_name`, `rows_benchmark`,
`rows_mapped_forward`, `rows_overridden`). A table whose stance was
already persisted is not persisted again.

With no conviction column the stance itself is the conviction, so a
bullish row orders above a neutral one in the score that ranks the names;
under the graded equal-weight arms the order does not size anything (the
grade selects, equal weight sizes), so for the gate only the grade moves.

## The two modes

**`sixth`** (the default): each table is a further analyst in the grade,
named `table:<file stem>`, with a full vote. The thresholds in
`grading.grade_stances` do not move:

| grade | rule, unchanged |
|---|---|
| B | votes >= 0.5 |
| A | votes >= 2, or the release bullish and votes >= 1, or fundamental and technical both bullish and votes >= 1.5 |
| A+ | the release bullish and votes >= 2 |
| cap | a bearish fundamental, technical, sentiment or value analyst caps the grade at B |

The vote total runs over the five (rotation at half) plus the table at
1.0 (`analyst_weights` gives any name but rotation a full weight; with
`ANALYST_WEIGHTS` the five keep theirs, nothing is rescaled). So what a
sixth vote does to the counts:

- A **bullish** sixth vote lowers by one the votes a name needs from the
  five: alone it makes a B (one bull, nobody bearish); with one core bull
  an A (votes 2, where two were needed); with the release alone an A+
  (release and votes 2, where the release and one more core vote were
  needed). It never supplies the release clause or the fundamental-and-
  technical clause itself.
- A **bearish** sixth vote raises them by one and **does not veto**: the
  release with two core bulls stays A+ at three votes; the release with
  one core bull falls from A+ to A (release and votes >= 1), not to B. The
  veto stays with the four core analysts.
- A neutral table leaves every cell exactly as it was, which is the null.

The one-name rule the board re-grades with (`grade_from_stances`) gives
the same letter with the table's stance added to the dict, cell for cell;
`test_regrade_sixth_is_another_analysts_vote` asserts that over a whole
panel. Several `--stance-table` flags in `sixth` mode are several votes
(a combined test of two arms), each recorded.

**`replace:<analyst>`** (`fundamental`, `technical`, `sentiment`,
`rotation` or `value`): the one table takes that analyst's place entirely:
its stance, its conviction in the score, and that analyst's role in the
rule. Replacing `sentiment`, a bullish row is the bullish release and a
bearish row vetoes; replacing `rotation`, the table carries the half
weight. The other four are untouched. This is the mode for a "replacement
candidate" (an arm whose correlation with the analyst it reads the same
facts as is 0.3 or more).

## The null test

Before any table is read: `--stance-table FILE --null-test` re-grades the
book with the same rows, every stance and conviction set to zero, in
`sixth` mode, and compares it with the plain desk: grades and scores to
the bit, and every line's dates and returns to the bit at two offsets and
every cost (`null_test`, as S1g's). It prints the table's sha256 and row
audit and `PASS, reproduced to the bit` or `FAIL`, exit 0 or 1. A table
whose rows all land outside the panel also passes, which is why the row
audit is printed with it: read `rows_used` before reading the verdict.

## The commands, per study

All three studies recorded the same template in their payload's
`scorecard_follow_up` (`SCORECARD_FOLLOW_UP` in `market_text_surprise.py`,
`market_statements.py`, `market_insiders.py`):

    python -m backend.cli.market_pit_scorecard --graded-cap 0.25 --rank-ic \
        --stance-table {table} --output {output}

That command runs as recorded on this branch; `--stance-mode` defaults to
`sixth`, so no study branch needs editing. What the template leaves out
and the gate needs: the null test first, a control run on the same tree
and store, and `--root` on spark1 (`~/deploy/anios/data/market`, as the
study runners set `ROOT`). The full sequence for one table, run from the
study's worktree on spark1 with `PYTHONPATH=$PWD`:

    ROOT=~/deploy/anios/data/market
    OUT=docs/research/scorecards/<study>
    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 \
        --stance-table "$OUT/stances/<arm>.parquet" --null-test
    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 \
        --rank-ic --output "$OUT/pit_scorecard_control.json"
    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 \
        --rank-ic --stance-table "$OUT/stances/<arm>.parquet" \
        --stance-mode sixth --output "$OUT/pit_scorecard_<arm>.json"

The payload's `stance_tables` block carries the mode, each table's path,
sha256, grade name and row audit, and per window the eligible
name-sessions at A+/A/B/C before and after and how many moved up or down;
`arm` reads `ew_graded_cap25 + stance_sixth` (or
`stance_replace_<analyst>`). The control is the same command without the
table, which is exactly the incumbent `ew_graded_cap25` payload (S1g's
`notch_control.json` is one, on the tree and store of that run; a control
must be re-run on the same tree and store as its candidate).

### A1 text surprise (`research/text-surprise`, `fb5b9b87`)

`market_text_surprise evaluate --tables $OUT` writes
`$OUT/stances/<arm>.parquet` for every arm but A and the level null, with
`$OUT=docs/research/scorecards/text-surprise`:

| arm | table |
|---|---|
| A1-1 change | `stances/A1-1_change.parquet` |
| A1-1 change_plus_level | `stances/A1-1_change_plus_level.parquet` |
| A1-1 change_gated | `stances/A1-1_change_gated.parquet` |
| A1-3 word surprise | `stances/A1-3_word_surprise.parquet` |

Run the gate only for an arm whose verdict line reads CANDIDATE. Its
`role` decides the mode: `sixth analyst` (correlation with the tone level
below 0.3) is `--stance-mode sixth`; `replacement candidate` replaces the
tone input, `--stance-mode replace:sentiment`.

    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 --rank-ic \
        --stance-table docs/research/scorecards/text-surprise/stances/A1-3_word_surprise.parquet \
        --output docs/research/scorecards/text-surprise/pit_scorecard_A1-3_word_surprise.json

### A2 LLM statement reading (`research/llm-statements`, `d6852a8a`)

`market_statements evaluate --out $OUT/llm_statements.json` writes
`$OUT/stances/A2.parquet` and records the command already formatted, with
`output=$OUT/pit_scorecard_A2.json`, `$OUT=docs/research/scorecards/llm-statements`:

    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 --rank-ic \
        --stance-table docs/research/scorecards/llm-statements/stances/A2.parquet \
        --output docs/research/scorecards/llm-statements/pit_scorecard_A2.json

The plan's role: correlation below 0.3 with both the fundamental and the
value analyst is a sixth analyst (`--stance-mode sixth`); otherwise a
replacement for the one it correlates with, `--stance-mode
replace:fundamental` or `replace:value`.

### A4 insider trades (`research/insider-stance`, `3f823048`)

`market_insiders evaluate --tables $OUT` writes one table per arm,
`$OUT=docs/research/scorecards/insider-stance`:

| arm | table |
|---|---|
| A4-opp opportunistic insiders | `stances/A4-opp_opportunistic_insiders.parquet` |
| A4-all all insiders | `stances/A4-all_all_insiders.parquet` |

    python -m backend.cli.market_pit_scorecard --root "$ROOT" --graded-cap 0.25 --rank-ic \
        --stance-table docs/research/scorecards/insider-stance/stances/A4-opp_opportunistic_insiders.parquet \
        --output docs/research/scorecards/insider-stance/pit_scorecard_A4-opp.json

The plan names a sixth analyst (correlation with the desk below 0.3) or
"a replacement candidate" without naming which analyst it would replace;
`sixth` is the mode to run, and a replacement would need the operator to
name the analyst in `--stance-mode replace:<analyst>` before the run.

## The verdict after the run

The T-S1 gate the plans state (+2 bp of equity a session at 25 bp over
`graded-equal-weight/5`, Newey-West t >= 2 on the model window, not
negative after, above the control at 15 of 20 offsets, deflated Sharpe at
the cumulative trial count >= 0.95) is a pairing of the candidate payload
against the control payload, which the scorecard does not do within one
run. The payloads carry what the pairing needs: `curves` (every line's
daily returns at the median offset) and each row's `cagrs` per offset.
`research/structure-rules` judges S1g from exactly these two blocks
(`backend/market/structure_rules.notch_verdict`, `market_structure_rules
--notch CONTROL CANDIDATE`); it is not on this branch, and its trial count
and variance are S1's. A stance-table verdict command, with each study's
trial count, is the follow-up to write once a run has produced a payload
to read; the numbers it needs are in the files.

## Merge order

This branch changes `grading.py`, `market_pit_scorecard.py` and their
tests, and adds `stance_table.py`; the three study branches touch none of
these, so it merges into each without conflict. It must be in the tree
the gate runs on, and the study's own code must be too, so **either**
merge `desk/stance-table` into `main` and then `main` into each study
branch, **or** merge `desk/stance-table` straight into the study worktree
on spark1 before running (`git -C ~/scratch/wt-<study> merge
desk/stance-table`). A payload records `membership` and the tables'
sha256s, not the tree; record the HEAD the run used beside it, as S1's
results did.

Four other branches also changed `market_pit_scorecard.py` since
`95424784`'s ancestor and each added a `--null-test` tied to its own flag:
`research/structure-rules` (`--structure-notch`),
`research/universe-expansion` (`--universe`), `research/vol-target`
(`--gross-target`) and `research/regime-gross` (on vol-target). This
branch's `--rank-ic`, `--membership`, `--output`, `cagrs`,
`worst_drawdown` and `curves` are the structure-rules hunks verbatim.
`git merge-tree` of this branch with each of the three studies is clean;
with `research/structure-rules` and `research/vol-target` it conflicts
in `market_pit_scorecard.py` (and structure-rules' test file) where both
sides insert at the same points: the import list, the helpers before
`build`, the `add_argument` block and the `main()` branch that decides
what the null is. Resolve by keeping both sides' insertions and giving
each flag its own null behind its own flag (a notch with its mask
cleared, a cohort that is the book, a gross target of infinity, a table
of zeros), once, on `main`, before any of them is run again from a merged
tree.
