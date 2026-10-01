# Text surprise (A1): the release's tone *change* and a learned word-surprise as point-in-time stances. Pre-registration (2026-10-01)

**Status: registered before any code or number.** Queue item A1 of
[the survey](sota-survey-2026-10-01.md). The transcript arm (A1-2) is
not registered here: no licence-clean free source of call transcripts
exists (`claude/text-signals-2026-09-29.md`, study 3); it waits for a
licensed feed and its own registration.

## The question

PEAD.txt (Meursault, Liang, Ross, Zhu 2021) finds that a *surprise*
measured from earnings text drifts for a year and decays less than the
earnings-number surprise. The desk's tone analyst scores each release's
*level* (guidance, demand, pricing, capex, supply). Does the *change* in
tone against the company's previous release, or a learned word-surprise
fitted to the one-day reaction, rank the book's names better than the
level does, at the desk's horizons?

## What is known before this note (disclosed)

- Tone level: rank IC 0.037 at 20 sessions on the book (t 2.4), 0.047
  at 60 (t 2.0); not a look-ahead artefact (ChronoBERT matched it).
- The 09-07 generic-embedding study: IC 0.013-0.031; nothing added.
- The literature says large-cap text effects are mostly next-day; the
  20-session tone IC may be a slow characteristic rather than drift.
- The releases: 3,451 scored 8-K/6-K texts for 89+4 names, 2015-2026,
  plus tonight's 6-K backfill (ARM, ASML, SIMO, TSM; NBIS none).

## Arms

- **A1-1, tone surprise:** for each release, each of the four ranked
  tone fields minus the same field on the company's previous release
  (NaN when there is none), averaged as the analyst averages them;
  carried forward until the next release as the level is. Three
  variants, fixed now: the change alone; the change plus the level
  (equal weight); the change only when |change| ≥ 0.5.
- **A1-3, learned word-surprise (point-in-time):** a regularised
  logistic regression (L2, C ∈ {0.1, 1}) from the release's tf-idf
  unigrams and bigrams (min 20 documents) to the sign of the one-day
  beta-adjusted reaction (close before the release to close after),
  fitted on an expanding window with a 20-session purge and walk-forward
  refits each calendar year from 2018 (train 2015-2017 first); the
  score is the fitted log-odds on the release, dated by its reaction
  session. The reaction label uses the desk's daily bars; nothing after
  the reaction session enters the fit.

Both arms are scored on the harness's cells (`harness.evaluate_scores`:
the newest release on or before the session, 20- and 60-session
beta-adjusted residual, the book's names), in-window 2018-01..2025-05
and post-cutoff (2025-06 on) separately for A1-1 because it inherits the
reader's cutoff; A1-3 is point-in-time by construction and reports both
windows as one.

## Criteria, fixed now

An arm is **proposed as a stance** (sixth analyst or a replacement of
the tone input, decided by its correlation with the tone level: below
0.3 a sixth analyst, else a replacement candidate) if its 20-session
rank IC on 2018-2025 is ≥ 0.02 with t ≥ 2 **and** its paired IC against
the tone level is not negative at t ≤ −1, **and** the T-S1 book gate
holds (+2 bp of equity a session at 25 bp over `graded-equal-weight/5`,
NW t ≥ 2 on the model window, not negative after, 15 of 20 offsets,
deflated Sharpe at the cumulative count ≥ 0.95). Anything else is
**RECORD**.

## Trials and prior

Four trials (three A1-1 variants, one A1-3 at the best C, chosen on
2015-2017 only); cumulative 467 → 471. Prior: 25% that a variant clears
the IC floor, 10% the book gate. The likely finding is that the change
carries the next-day reaction and little at 20 sessions.

## Order of work

1. This note, committed and pushed. 2. Build with tests: the surprise
fields from the stored tone records, the point-in-time text model, the
evaluation CLI reusing `market_tone_validity evaluate`, the null test
(the level alone reproduces the stored tone's IC bit for bit), an
independent check. 3. Run on spark1 (CPU). 4. Write-up, report.
