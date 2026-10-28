# Tone surprise: pre-registration — 2026-10-28

**Status: registered before any code or number for this arm.** This note fixes
the question, the signal, the arms, the gate and the placebo before the first
run. It is the P2 selection bet in
`trading-program-2026-10-28.md`. Nothing here changes the live rule.

## Why this arm

The sentiment analyst reads the level of the newest release's tone. Its score
carries a beta-adjusted rank IC of 0.039 (t 3.0) at twenty sessions and 0.029
(t 1.3) at sixty; the edge survived the leak test
(`docs/research/tone-validity-results-2026-09-30.md`, 0.037). The release-tone
layer already stores, for each of five fields, the change from the previous
release (`language.tone_features`, `tone_*_change`), but the analyst uses only
`tone_guidance_change`. The survey of 2026-10-01 ranked release-text surprise
first among selection candidates because the data and the harness already
exist and the published evidence is strong (Meursault, Liang, Ross and Zhu,
Philadelphia Fed WP 21-07: text surprise earns 8.0% cumulative abnormal return
at one year against 4.6% for classic SUE drift, and decays less).

The question is deliberately narrow: does the *change* in what the company
said, not the level, predict the next twenty and sixty sessions' excess return
on this desk's panel?

## Data and point-in-time rules

- **Releases.** The scored release records in `edgar_tone` for every panel
  name, read through the desk's existing loader. A release counts at session
  `t` only if its reaction date is on or before `t`, using the desk's legacy
  alignment (`side="left"`, the same as `language.tone_features`); the strict
  variant (`strict_before_session=True`) is reported beside it as a
  sensitivity, not as a second trial.
- **Current and previous.** For name `j` at session `t`, the current release is
  the newest counted one; the previous is the one before it. A name with no
  counted release has no view. A name with exactly one counted release has a
  level but **no surprise**: it is missing, not zero. The existing
  `tone_*_change` fields set the first release's change to 0; this study does
  not use that convention for the first release.
- **The five fields.** `guidance`, `demand`, `pricing`, `capex`,
  `supply_constrained`, each scored -1/0/+1 by the release reader.
- **The signal.**
  `s_j(t) = sum over the five fields of (current_field - previous_field)`,
  an integer in [-10, +10], carried forward from the release's reaction
  session until the next release, exactly as the level fields are carried.
  Missing where the name has no current or no previous release.
- **No future data.** The signal at `t` reads only releases whose reaction
  date is on or before `t`. The perturbation test is mandatory: change every
  tone record after `t` and the signal at `t` is byte-identical; change the
  newest record on or before `t` and it changes.

## The arms (three trials, one primary)

1. **S-only (primary).** The signal itself is the analyst score. Evaluate it
   with `harness.evaluate_scores` on the desk's panel, beta-adjusted residual
   forward returns, `min_names=20`, benchmark excluded, at 20 and 60 sessions.
   The choosing window is 2016-2023; 2024-2026 is reported and never tuned on.
2. **S-added (secondary, run only if S-only passes).** Add the signal as a
   sixth equal analyst vote, with the existing weights scaled to the same
   total so the grade thresholds keep their meaning. Score the installed rule
   on the honest point-in-time universe with `market_pit_scorecard`, 25 bp,
   20 offsets, 2016-2023; 2024-2026 reported.
3. **S-blend (secondary, run only if S-only passes).** Blend the surprise with
   the sentiment analyst's existing score (equal rank blend), leaving the
   other four analysts unchanged. Same scorecard and windows.

The primary is fixed now. If S-only fails, the secondary arms are not run;
that is the trial-count discipline, not a choice made after seeing results.

## The gate

**S-only passes if, on 2016-2023 at 20 sessions:**

- mean rank IC is at least **0.02**, and
- the Newey-West t at lag 20 is at least **2.0**, and
- the IC exceeds the **95th percentile of 200 placebo draws** made by shuffling
  the signal across names within each session while preserving the missing
  mask.

The 60-session result is reported but does not gate. A pass at 20 sessions
with a negative or flat 60-session result is still a pass for the book,
because the desk rebalances every twenty sessions; the note must say so.

**S-added or S-blend passes if, on 2016-2023 at 25 bp, 20 offsets:**

- the median CAGR is higher than the installed rule's on the same universe,
  and
- the worst drawdown is no deeper than the installed rule's by more than two
  points, and
- 2024-2026 is not worse than the installed rule on both CAGR and drawdown.

Passing either integration arm buys a **forward shadow of 252 sessions**, not
a live change. The shadow records the arm's grades and hypothetical book
nightly; the live rule is untouched.

## The null test

Before any arm is read, the implementation must reproduce the incumbent:

- S-added with the sixth vote's weight set to zero must produce grades
  byte-identical to the installed grading on every session of the panel.
- S-only with every signal value set to missing must produce no IC and no
  trades, not a neutral score that silently ranks names.
- The strict-alignment sensitivity must differ from the legacy alignment only
  on sessions where a release's reaction date is the session itself; every
  other session must be identical.

A failure stops the study.

## What is already known, disclosed before the run

- The sentiment analyst's level score is positive and significant at twenty
  sessions; the change fields have not been measured as a group.
- The guidance-change field is already one of the analyst's four scored legs,
  so S-blend is not independent of the incumbent; the note must report the
  overlap.
- The release reader is a modern language model reading historical text. The
  text is historical; the reader is not. The tone-validity leak test is the
  precedent for accepting a historical reading, and the post-cutoff window is
  not available for a ten-year test. This caveat stays attached to every
  number.
- Coverage: 3,451 scored releases; a name's first release has no surprise, so
  the early panel is thinner than the level study's.
- The book's names are chosen with hindsight; the PIT universe is the honest
  test for the integration arms. The S-only IC is measured on the panel and is
  reported beside the PIT result.

## What passing and failing mean

- **Pass:** a forward shadow, recorded nightly for 252 sessions, then a
  decision. No live change before the shadow.
- **Fail:** written down with its evidence in `docs/research/`; not retried
  without a new pre-registration. The signal is not added to the grade, the
  board, or any prompt.

## Amendments

None. If an amendment is needed before the first result, it is written here
and dated; after the first result, no amendment is allowed.
