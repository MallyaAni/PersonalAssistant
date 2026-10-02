# LLM statement reading, second look (A2b): the stored answers signed by the model's stated direction. Pre-registration (2026-10-02)

**Status: registered before any A2b code or number.** A follow-up to A2
([plan](llm-statements-plan-2026-10-01.md) `c3fe04ef`,
[results](llm-statements-results-2026-10-01.md) `db014bd6`, RECORD).
Nothing here changes the live book. **No model call is made:** A2b reads
the 2,916 answers A2 already stored (`edgar_statements`, partition
`asof=2026-10-02` on spark1, read-only) and re-measures them under a
different stance. No A2b statistic has been computed or seen when this
note is committed; the code that computes one is written after it.

## Why a second look, and why it is penalised (disclosed)

A2 registered the stance **probability − 0.5**, where the prompt asked for
"your probability, from 0 to 1, that Q9 is above Q5". The results showed
the model did not answer that question:

- 1,124 of its 1,144 "down" calls carry a probability above 0.5 (38.5% of
  all 2,916 answers); every disagreement has that form, and no "up" call
  carries a probability below 0.5.
- 2,896 of the 2,916 probabilities are above 0.5, 1,805 are exactly 0.62,
  and five values (0.62, 0.65, 0.55, 0.72, 0.78) cover 96%.

So the model reported its **confidence in its own call**, and A2's stance
ranked names by how sure the model sounded, positive for 98% of down calls.
The direction calls never entered the stance. A2's verdict (IC in-window
+0.0275, t +1.78; post-cutoff +0.0112, t +0.43; paired vs fundamental
+0.0032, t +0.14) stands as the test of the stance it registered.

A2b is a **second look at the same answers, made after seeing A2 fail**.
That is a researcher degree of freedom, and it is charged for:

1. **Trials.** Both A2b stances below count, in full, against the
   cumulative count, and any book gate's deflated Sharpe is computed at the
   new count.
2. **A two-look floor, reported.** Beside the registered t ≥ 2, the
   evaluate step reports whether the in-window t also clears **2.28**, the
   t at which the one-sided tail of the registered floor (2.28%) is split
   over the two looks (A2 and A2b) at these answers. It decides nothing;
   it is printed so that a pass between 2.00 and 2.28 is read as such.
3. **Post-cutoff decides.** The in-window period (2018-01..2025-05) is
   inside the reader's training window: the model has read these filings
   and may recognise a series from its numbers, and the stated direction
   is exactly the part of the answer memorisation would help most (A2's
   direction accuracy beat persistence by 4.9 points in-window and by 1.9
   points post-cutoff). The post-cutoff window (2025-06 on) is where that
   cannot help, so criterion 2 below is not a formality: whatever the
   in-window numbers, a post-cutoff IC negative at t ≤ −1 is RECORD, and
   the write-up reads a candidate's in-window IC as look-ahead-contaminated
   unless the post-cutoff point estimate has the same sign.

## The stance

Notation: on each stored answer, `d` = +1 if the stated direction is "up",
−1 if "down"; `p` = the stored probability.

**Primary (A2b, decides): `d × |2p − 1|`.** The stated direction signs the
stance; the distance of the stated number from one half sizes it. Carried
forward from the availability date exactly as A2's stance, ranked across
the book by `Opinion.ranks()` exactly as A2's.

Why this one, from the A2 evidence only:

- **The sign comes from the direction** because the direction is the only
  part of the answer that agrees with itself under every reading: all 1,772
  up calls have p > 0.5, and 1,124 of 1,144 down calls have p > 0.5, which
  is coherent only if p is confidence in the call.
- **The magnitude is |2p − 1|, not 2p − 1,** because of the 20 down calls
  with p < 0.5. Read as confidence, 2p − 1 would make those 20 positive,
  i.e. bullish on a stated "down", which no reading of the answer supports;
  read as P(up) (as the prompt asked), they are coherent down calls with
  confidence 1 − p. |2p − 1| gives them a negative stance with that
  confidence under either reading, and equals 2p − 1 on the other 2,896.
- **It is the minimal change from A2:** A2's stance was (2p − 1)/2; on the
  2,896 answers with p > 0.5 A2b changes only the sign of the 1,124
  inconsistent down calls (and on the 20 coherent down calls it is A2's
  stance doubled, same sign). The ranks are those of the A2 results'
  proposed `(+1 if up else −1) × |p − 0.5|` exactly. Everything except the
  sign that A2's audit found wrong is held fixed.

**Secondary (A2b-dir, reported, decides nothing): `d` alone (±1).** It
asks whether the coarse confidence (five values cover 96%) adds anything
beside the call. With two values per session its ranks are heavily tied
(average ranks), so under the analyst's 30% rule it will rarely or never
produce a bullish stance; its stance table is written but is not a gate
candidate in any outcome.

## Measurement (A2's, unchanged)

`market_statements evaluate --stance-variant a2b` (and `a2b-direction`):
the same `harness.evaluate_scores` on the beta-adjusted residual,
`COST_BPS` 10, `MIN_NAMES` 15; the arm, the fundamental analyst (corrected
source, as the desk builds it) and the value analyst on their shared
(session, name) cells of the book; horizons **20 and 60** sessions
(20 primary); windows **in-window 2018-01-01..2025-05-31** and
**post-cutoff 2025-06-01 on**; the paired per-period IC against the
fundamental analyst; the mean per-session rank correlation with both
comparators; A2's constant-0.5 null test (a scoreless arm reads as no
defined period); a stance table under the analyst's own rule (top and
bottom 30%, three sessions' persistence) at `stances/A2b.parquet`
(`A2b-dir.parquet` for the secondary). The direction-accuracy report is
the same answers and the same counts as A2's and is not re-reported.

## Criteria (A2's, unchanged; primary stance, 20 sessions)

A2b is **proposed as a stance** if:

1. its rank IC in-window (2018-01..2025-05) is **≥ 0.02 with t ≥ 2**, **and**
2. its post-cutoff IC (2025-06 on) is **not negative at t ≤ −1**, **and**
3. its paired IC against the fundamental analyst on their shared periods
   is **not negative at t ≤ −1**.

**Role** (A2's rule): mean per-session rank correlation **below 0.3 with
both** the fundamental and the value analyst is a **sixth-analyst
candidate** (A2's role); otherwise a **replacement candidate** for the one
it correlates with, and the book gate runs in `replace:<analyst>` mode.
Anything else is **RECORD**. The 60-session numbers, the secondary stance
and the two-look line are reported and decide nothing.

## The null test (first, before any A2b number is read)

**A2 replayed through the A2b path.** `evaluate --stance-variant a2`
rebuilds A2's original stance (p − 0.5) through the new variant code and
must reproduce the committed A2 payload
(`docs/research/scorecards/llm-statements/llm_statements.json`,
`d6b6fea2`) **to the bit**: every arm's IC, t, net Sharpe, period and
defined-period counts and per-period ICs, every window's cell count, every
paired difference and every correlation, at both horizons and in both
windows, and the criteria and verdict. The CLI compares with
`--reproduce <payload>` and exits 1 on any difference. A failure (for
example a store or panel that changed since the A2 run) stops the study:
no A2b number is computed until the difference is explained and recorded
here as an addendum.

A2's own constant-0.5 null test runs inside every evaluate as before.

## The independent check

`docs/research/scorecards/llm-statements/llm_statements_check.py`, given
`--variant`, rebuilds the stance from the stored frames' `direction` and
`probability` columns with its own sign, carry-forward, percentile ranks,
schedule and Spearman (not the study's functions), recomputes every IC
line, cell count, the paired difference against the fundamental analyst
and the three criteria and the verdict, and compares them with the A2b
payload. Run on the A2 payload with `--variant a2` it is a second,
independent replay. A2's recorded check mismatch on names counted (86 vs
91, the five empty frames) is corrected by counting frames as the payload
does; the accuracy recount is not run for A2b (unchanged answers).

## Trials and prior

Two trials (the primary and the secondary). The newest plan on any research
branch at this registration is cluster-cap R1 (`d55927fd`, 485 → 488);
cumulative **488 → 490**. Prior: **~10%** that the primary clears the IC
floor with the post-cutoff window not contradicting it, **~3%** the book
gate. Expected: a stance more correlated with the fundamental analyst than
A2's (+0.144 in-window), because a year-over-year direction call is close
to the persistence of year-over-year growth the ratios already encode, and
a paired IC near zero. The model's post-cutoff edge over persistence was
1.9 points on 322 calls, inside one binomial standard error.

## If the primary clears the IC floor

The next step is the stance-table book gate per
`docs/research/stance-table-gate.md` (branch `desk/stance-table`,
`e67213d1`): merge `desk/stance-table` into the
study worktree, then **the scorecard's `--null-test` with
`stances/A2b.parquet` first** (PASS, reproduced to the bit, with
`rows_used` read), the control, and the candidate in the mode the role
names, at the T-S1 gate (+2 bp of equity a session at 25 bp over
`graded-equal-weight/5`, NW t ≥ 2 on the model window, not negative after,
15 of 20 offsets, deflated Sharpe at 490 ≥ 0.95). It runs **after 16:15 ET
only**, never during 19:20-19:55 ET, and is a separate step with its own
write-up. If the primary does not clear, no gate is run.

## Order of work and permissions

1. This note, committed alone and pushed.
2. Build: a `--stance-variant {a2,a2b,a2b-direction}` option on
   `market_statements evaluate` (default `a2`, A2's behaviour unchanged),
   `--reproduce`, the check's `--variant`, tests in the same commit.
3. On spark1 from `~/scratch/wt-a2b` at nice 19, CPU only, no model
   server: the null test, then the A2b evaluation (primary and secondary),
   then the independent check. CPU-light, so it may run in market hours;
   never 19:20-19:55 ET. The store is read, never written; nothing touches
   `~/deploy/anios` beyond reading or the running cluster-cap study.
4. Write-up with the verdict lines verbatim.
