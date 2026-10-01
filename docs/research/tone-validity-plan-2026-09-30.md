# Tone validity: is the release-tone edge real? Pre-registration (2026-09-30)

**Status: registered, not started.** It waits for the operator's go-ahead
on the downloads and the re-score batch listed under "Permissions".

## The question

The sentiment analyst reads each 8-K earnings release through an LLM
(`deepseek-v4-flash`, prompt `release_tone/3`) into five tone fields and
ranks four of them. Measured on the book it carries a rank IC of 0.039
(t 3.0) at 20 sessions, and it is the only analyst whose bullish stance
can make an A+.

All 3,451 stored scores were produced by one batch of that model and
prompt, reading releases dated 2015-2026. The model's training data
reportedly ends in May 2025 (one third-party source; unconfirmed), which
would put about 87% of the releases inside its training window. Three
recent papers show that LLM readings of in-window text are inflated: the
model can lean on what it later learned about the company, and masking the
company's name does not always stop it (Glasserman and Lin 2024; Lopez-Lira,
Tang and Zhu 2025; Gao, Jiang and Yan 2025).

So: **does the tone edge survive when the reader cannot know the company,
or when the model was trained only on text written before the release?**

## What is known before this note (disclosed)

- The analyst's IC of 0.039 (t 3.0) at 20 sessions and 0.029 (t 1.3) at
  60, and its liquidity gradient (`sentiment.py`).
- `market_release_eval` (2026-09-07): a general embedding (nomic-embed
  v1.5, the first 2,048 tokens) of the same 3,401 releases, walk-forward
  into ridge and trees, reached IC 0.013-0.031 (t 1.1-1.8) at 20 sessions,
  and adding it to the desk lowered the net Sharpe from 1.02 to 0.83. That
  embedder is not point-in-time either.
- The literature memo (`claude/text-signals-2026-09-29.md` in the project):
  text effects on large caps are next-day and mostly gone after costs.
- The post-cutoff window (June 2025 onward, about 460 releases) is too
  short to settle an IC of 0.04 on its own (standard error about 0.04).

## Arms

**A, the control:** the stored scores (`edgar_tone`, `release_tone/3`).

**B, masked re-read:** the same model and prompt on the same texts with the
issuer's name, tickers, product and people names, dates and fiscal-period
labels replaced by placeholders before the model sees them. The masking is
a deterministic pass (`release_mask`, to be built with tests) that reads
the EDGAR header and the store's name lists; it is checked before any score
is read by a **leak test**: on 200 masked releases the same model, asked
"which company and which quarter is this?", must name the company on fewer
than 5% and the year on fewer than 10%. If it fails, the masking is
tightened and the check re-run; the leak test is not a trial.

**C, point-in-time embedding:** ChronoBERT (`manelalab/chrono-bert-v1-<year>`,
the checkpoint whose cutoff precedes the release's reaction date, so it has
never seen the release or anything written after it), full text up to 8,192
tokens, mean-pooled, into a walk-forward ridge on the label below with the
`market_release_eval` folds (train 750, purge the horizon, 5-session
embargo). C is look-ahead-free by construction and is the arbiter if B's
masking is doubtful.

**D, general embedding, full text** (reported, not a trial): nomic-embed
v1.5 over the whole release at an 8,192-token context, closing the 09-07
study's caveat. It is not point-in-time.

Every arm is scored on the same (session, name) cells: the newest release
whose reaction date is on or before the session (`release_text.
active_index`), the label the desk is measured on (the 20-session
beta-adjusted residual forward return, `harness.evaluate_scores`), the
analyst's own stance rule (top and bottom 30%, 3-session persistence)
where a stance is compared.

## Criteria, fixed now

Let IC(X) be the arm's 20-session rank IC over 2016-01-04..2025-05-31 (the
in-window period) on the shared cells, and t the harness's t.

1. **Tone inflated** if IC(B) − IC(A) ≤ −0.015 with a paired t ≤ −2
   (the per-period IC differences), **or** IC(A) restricted to the
   post-window period (2025-06-01 onward) is below 0.01 while the in-window
   IC(A) is above 0.03 and C's in-window IC is below 0.02. Then the finding
   goes to the operator with the recommendation that A+ should not rest on
   sentiment until forward evidence exists; the change itself would be a
   separate registration.
2. **Incumbent stands** if |IC(B) − IC(A)| ≤ 0.010, or B is within noise
   and C reaches at least half of A's IC.
3. **A replacement is proposed** (B, or C) only by the book gate on the
   T-S1 scorecard: +2 bp of equity a session at 25 bp over `ew-redeploy`,
   NW t ≥ 2 on 2016-2023, not negative on 2024-2026, positive at 15 of 20
   offsets, deflated Sharpe at the cumulative trial count ≥ 0.95.

Anything else is RECORD, and the analyst stays as it is.

## Trials and prior

- Trials: B and C (D is reported only, the leak test is a check). The
  cumulative count goes from 452 to 454.
- Prior: about 40% that criterion 1 fires (tone inflated); about 10% that
  any arm passes the book gate.

## Order of work

1. This note is committed and pushed before any code.
2. The operator's go-ahead (below).
3. Build with tests: `release_mask`, the leak test, the ChronoBERT embedder
   on the RTX (`torch` 2.14, CUDA verified), the arm runner reusing
   `market_release_eval`'s folds and `evaluate_scores`.
4. The leak test, before any score is read.
5. Arms B (one DeepSeek batch on the Sparks, off-hours), C and D (RTX).
6. The comparison, the write-up, an independent check, the report.

## Permissions needed

- **Downloads to the RTX (E:, not C:, which has 8.9 GB free):** the eleven
  ChronoBERT checkpoints `manelalab/chrono-bert-v1-20141231` …
  `-20241231` (about 600 MB each, about 6.6 GB, MIT licence) and the nomic
  modelling code if the RTX copy lacks it (kilobytes).
- **The Sparks' DeepSeek servers** for one re-score batch of about 3,450
  masked releases, run outside market hours and outside the nightly's
  window, with the same budget the nightly uses.
- **SEC:** about 100 requests to top up releases missing from the desktop's
  text cache, at the declared user agent and under 10 requests a second.
- **Copying** the 27 MB of release texts from the desktop to the RTX
  working folder.

## Not in scope

Reading 6-K releases (ARM, ASML, NBIS, SIMO, TSM have no tone) is a data
fix, proposed separately. The universe-trained release model (the memo's
study 2) and call transcripts (study 3) wait on this result.
