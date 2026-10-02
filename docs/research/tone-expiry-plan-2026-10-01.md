# A5, tone expiry: should a stale release-tone reading expire? Pre-registration (2026-10-01)

**Status: registered before any code or number.** The sentiment analyst
grades a name from the tone of its newest scored earnings release, and
`language.tone_features` carries that reading forward until the next one
is read, with no expiry. Today's earnings-coverage check
(`backend/market/release_coverage.py`, live since `d17f1632`) found OKLO's
last release read on 2025-03-25: its later quarters came only as 10-Q and
10-K, so the analyst - and the board's grade detail - has been using a
555-day-old reading as if it were current. The board's standing rule is
"no false information". This note asks whether the reading should expire
and fixes the test before any code exists.

## The question

When a name's newest release reading is older than its usual gap between
releases allows, should the sentiment analyst stop grading on it, or weigh
it down, so that a grade and its explanation never rest on a reading the
coverage note already calls overdue? The change removes a stale input; it
is not expected to add return. So the question is registered as
**non-inferiority**: does expiring the reading cost the analyst's rank IC
or the book anything measurable?

## What is known before this note (disclosed)

- **The analyst.** Tone alone carries a beta-adjusted rank IC of 0.039
  (t 3.0) at 20 sessions and 0.029 (t 1.3) at 60 (`sentiment.py`); the
  edge survived the leak test (`tone-validity-results-2026-09-30.md`,
  0.037). Taken out of the desk entirely, the summed conviction's IC falls
  from 0.046 to 0.038 at 20 sessions.
- **The carry-forward.** `tone_features` aligns each scored release to its
  reaction session and carries it until the next release. A name with no
  scored release gets neutral fills and `has_tone = 0`, and the analyst
  then has no view of it: a NaN score, a conviction counted as 0 in the
  desk's sum, a held stance that relaxes to neutral under the existing
  three-session persistence. Nothing ages a reading.
- **The overdue rule, fixed by the coverage check and reused here.** A
  name's usual gap is the median gap between its consecutive scored
  releases (`own_cadence`, four or more releases), else the median of every
  such gap across the book (`book_cadence`); its reading is overdue when
  the days since it exceed 1.5 times that (`TOLERANCE`). Measured on
  today's frames (`3816b6f3`): 3,452 gaps; a gap is p95 1.15 and p99 1.38
  of its name's own median; every gap above 1.75 is a missed release.
  Replayed every 28 days since 2016 on today's frames (not vintage-exact),
  1.8% of 10,560 name-sessions read overdue, the repeats real holes (TLN's
  private years, CORZ's bankruptcy, SIMO, OKLO, ASML's refused year-end
  6-Ks, WULF).
- **What one analyst's vote is worth to the book.** S1g withdrew the
  technical vote on 14.6% of name-sessions and moved the T-S1 book by
  −0.19 bp a session (t −0.91) on 2016-2023: a grade rarely turns on one
  analyst. An expiry touches a few percent of the sentiment analyst's
  cells.
- Nothing has measured whether a stale reading still carries information.

## Definitions (fixed now)

For name j at session t, on the desk's panel:

- **Releases counted:** the distinct reaction dates of the name's scored
  releases (`edgar_tone`, the newest partition the desk reads) on or
  before t. A release dated after t never counts: not for the reading's
  age, not for the name's own gap, not for the book's.
- **The reading in use:** the newest counted release - exactly the record
  `tone_features` carries into t on the desk's (legacy) path.
- **Age a:** calendar days from that reaction date to t, as
  `release_coverage.assess` counts them.
- **Usual gap g:** `release_coverage.own_cadence` of the counted releases;
  with fewer than four, `release_coverage.book_cadence` of every panel
  name's counted releases (the panel's names less the benchmark: the names
  the nightly passes to the check). Unknown (no name has two counted
  releases): no expiry. The study calls the coverage check's functions and
  does not re-implement them, so the board's note and the study define
  "overdue" identically.
- **Overdue:** a > 1.5 g (`release_coverage.TOLERANCE`, strict, as the
  check).
- **The tone fields:** the five levels (guidance, demand, pricing, capex,
  supply constrained) and their five changes from the previous release;
  `has_tone` is the indicator.

## The arms (two trials)

- **A5-hard.** An overdue reading is treated as missing: its ten tone
  fields are set to 0 and `has_tone` to 0 - the analyst's existing
  missing-reading handling (neutral fill and indicator), unchanged
  downstream.
- **A5-decay.** The ten tone fields are multiplied by w = 1 for a ≤ 1.0 g,
  w = 2 − a/g for 1.0 g < a < 2.0 g, and w = 0 for a ≥ 2.0 g. `has_tone`
  stays 1 while w > 0; at w = 0 the reading is treated as missing exactly
  as in A5-hard (a fully decayed reading is no reading, not a neutral one:
  the analyst's own rule that absence is visible to the grade).

**Where it acts.** A module flag, off by default
(`tone_expiry.TONE_EXPIRY = None | "hard" | "decay"`), applied on the
desk's tone loader (`model.load_tone_features`), the sentiment analyst's
only input. Unchanged in every arm: the expectations-gap learner's tone
features (`market_expectations`' strict path, so the value analyst's
blend is identical), the stored frames, the coverage check, the board and
every prompt. The flag is set only inside a scorecard run that asks for it
and is put back however the run ends.

**The null test.** The expiry path with an infinite horizon (every weight
1) must reproduce the incumbent to the bit - the grades, the desk's
scores, the sentiment analyst's scores and every scorecard line's daily
returns at two offsets and both costs (`market_pit_scorecard
--tone-expiry <arm> --null-test`) - for both arms, before any arm is read.
A failure stops the study.

## Measurement

**(i) The sentiment analyst's rank IC**, as the analysts are measured:
`harness.evaluate_scores` on the analyst's score (`sentiment.opine`) with
its defaults (beta-adjusted residual forward return, 20 names minimum, the
benchmark excluded) at 20 and 60 sessions, on the desk's panel. The arm is
evaluated on the incumbent's rebalance dates, so every period pairs; a
period belongs to the window that holds its rebalance date.

- *All cells:* per period, IC(arm) − IC(incumbent), each on its own
  cross-section; the mean and the plain t over the window's periods (the
  periods do not overlap, as for the harness's own IC t). When every
  difference is exactly zero, t = 0.
- *The affected cells* - the cells the arm changes (A5-hard: an expired
  reading; A5-decay: w < 1) among the incumbent's eligible names on each
  rebalance date. Each such cell has its centred cross-sectional
  percentile of residual forward return q and of score p, both within the
  date's whole cross-section (where the arm has no view of the name it
  sits at p = 0, the middle). Each side's IC on those cells is
  12 × mean(p × q) over the date's affected cells (the rank correlation's
  form for centred uniform ranks); the paired difference per date, and its
  plain t over the dates that have an affected cell. Under A5-hard the
  arm's side is 0 by construction, so this reads whether the expired
  readings still ranked names the right way. Reported; it does not decide.

**(ii) The book.** The T-S1 scorecard: `market_pit_scorecard
--graded-cap 0.25` (the live `graded-equal-weight/5` allocator at its 25%
hold cap), 20 offsets, 10 and 25 bp, the control with the flag off and
each arm with it on. Line `rule / point-in-time` at 25 bp: the paired
daily difference arm − control at the median offset with its Newey-West t
(lag 20), and the median CAGR across the 20 offsets, per window.

## Criteria, fixed now (non-inferiority)

An arm **REPLACES** the carry-forward if, on **both** 2016-2023 and
2024-2026: (1) the paired sentiment IC difference (all cells) has t ≥ −1
at 20 sessions and at 60 sessions; (2) the book's paired daily difference
has Newey-West t ≥ −1; and (3) the median CAGR falls by no more than 0.5
point against the control's. **RECORD** otherwise.

Registered as non-inferiority because the change removes a stale input the
board presents as current: it has to show that it costs nothing, not that
it earns something, and a positive difference is reported as a number,
never as a claim. If both arms REPLACE, **A5-hard** is the one proposed:
it expires a reading exactly when the board's coverage note calls it
overdue, so the grade and the note cannot disagree; A5-decay's reading is
recorded beside it.

## Reported, deciding nothing

- How many cells (name-sessions) and names each arm affects, per year and
  per window, on the panel and within the point-in-time book, with the
  share of name-sessions that carry a reading.
- The names affected in 2026: per name and reading, the reading's date,
  the first and last affected session, the sessions affected, the usual
  gap and whether it is the name's own or the book's, the largest a/g and
  (A5-decay) the smallest weight.
- What each arm does to the grades: eligible name-sessions whose letter
  moves, up and down, and the A+ counts before and after, per window; how
  many of the affected cells moved.
- The 10 bp lines, the median and worst drawdowns, the offsets above the
  control, and the scorecard's graded-score rank IC.
- The words the board's grade detail would show (below), for every name
  affected on the panel's last session.

## The board's words for an expired reading (drafted now)

Today the grade detail cites the carried reading's tone ("upbeat on
outlook; upbeat on demand") with no date, whatever its age. Under A5-hard
an expired reading would leave the analyst nothing to cite, and
`plainly.reason` would drop its line without a word. Neither tells the
reader the reading went stale. Drafted now, built with the study
(`tone_expiry.expired_words`, `tone_expiry.weighted_words`) and shown
nowhere unless an arm is adopted:

- **Expired** (A5-hard; A5-decay at w = 0), led by the recorded stance's
  mark like every grade-detail line:

  `· Sentiment: no current earnings reading (last release read 2025-03-25, 555 days ago; usually every 91 days across the book)`

  "across the book" appears only when the usual gap is the book's; the gap
  is in whole days, rounded as the coverage note rounds it.
- **Weighted down** (A5-decay, 0 < w < 1): the release's own words as the
  board writes them today, then its date, its age, the usual gap and the
  weight. The cited words describe the release as read, never the shrunk
  number. A synthetic example:

  `+ Sentiment: upbeat on outlook; upbeat on demand (release read 2026-06-14, 109 days ago, usually every 91 days; weighted 80% for its age)`

- No advice words (trade, buy, sell, should, avoid, safe, consider,
  recommend, own, wait), as the coverage note.

## Trials and prior

Two trials (A5-hard and A5-decay; the horizon, the decay band and the rule
are fixed above and not searched); cumulative 480 → 482 (A4, the insider
stance, registered 478 → 480). Prior: **~60%** that an arm is
non-inferior on every criterion; **~5%** that one is better (the book's
paired difference at Newey-West t ≥ 2 on 2016-2023 and not negative on
2024-2026). The likely finding: a few percent of cells change, the IC and
the book move by noise, and the question is settled by the board's rule
rather than by return.

## Order of work

1. This note, committed alone.
2. Build with tests: the rule (`backend/market/tone_expiry.py`, calling
   `release_coverage.own_cadence`, `book_cadence` and `TOLERANCE`), the
   flag on the desk's tone loader, `--tone-expiry {hard,decay}` with
   `--null-test` on `market_pit_scorecard` (with the shared `--rank-ic`,
   `--membership`, `--output`, per-offset CAGRs and median-offset curves),
   the study block in the payload, the verdict command pairing the control
   with both arms, and an independent check under
   `docs/research/scorecards/tone-expiry/`.
3. The unit gate on spark1.
4. Run on spark1 (CPU, niced, outside market hours and the nightly): both
   null tests (stop on failure), the control, A5-hard, A5-decay, the
   verdict, the check.
5. Write-up and report.

## Not in scope

Reading 10-Q or 10-K text for a name whose releases stopped (OKLO's later
quarters exist only there: a data change, separate); changing the
coverage check, its 1.5, the board or any prompt; ageing any other
analyst's input; the strict (before-session) tone path.

## Disclosed

- "A5" is the operator's label for this question; the survey's A5
  (options-market signals) was closed on the literature and never
  registered.
- The run reads the store as it stands on the night it runs, after
  tonight's 6-K re-read (which may admit ASML's year-end, SIMO's 2025 and
  NBIS's releases and so change which cells are overdue). The control and
  both arms read the same store; the verdict refuses payloads from
  different sessions or whose incumbent IC series differ.
- Reaction-date alignment is publication alignment, not proof of
  model-time availability (`language.py`); the study inherits it, as every
  tone study has.
- The IC is measured on today's book back through time, as the analysts'
  documented ICs are; the book is point in time.
- The 60-session criterion is a non-inferiority bound only: tone carries
  no significant edge at 60 sessions on its own.
