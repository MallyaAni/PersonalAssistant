# Tone validity results: the release-tone edge is not a look-ahead artifact (2026-09-30)

**Verdict by the registered letter: RECORD.** Criterion 2 ("incumbent
stands") needs arm B, and arm B could not be made leak-free. **What the
two tests that could run say:** the "tone inflated" criterion does not
fire on either of them. A model trained only on text written before each
release reaches 90% of the stored tone's rank IC, and the stored tone's IC
after the reader's reported training cutoff equals its IC before it.

The plan is [tone-validity-plan-2026-09-30.md](tone-validity-plan-2026-09-30.md).
The code is `backend/market/release_mask.py`, `tone_leak.py`,
`chrono_embed.py`, `backend/cli/market_tone_validity.py` and
`market_tone_rescore.py` (branch `research/tone-validity`, unit gate 8,157
passed at `c9be87e`). The files are under `scorecards/tone-validity/`:
`tone_validity.json` (the payload), `evaluate.txt`, `mask_summary.json`,
`leak_result.json` and `leak_result_min40.json` with the answers.

## The leak test (registered check, run before any score was read)

The masking pass replaced the issuer's names and tickers, every date,
period, quarter and year, datelines, wire tags, people ("said X, CEO"),
e-mails, the About section and the contact trailer, and every
capitalised or alphanumeric token that occurs in fewer than 15 issuers'
releases (21,806 such tokens; 2.1% of the tokens of a release). Residual
issuer names, months and years: 0 of 3,451 releases.

The same reader (`deepseek-v4-flash`) was then asked, on 200 sampled
masked releases, which company and which quarter each one is.

| Masking | Answered | Named the company | Named the year | Passes (< 5% / < 10%) |
|---|---|---|---|---|
| Rare-token threshold 15 issuers | 200 | **64.5%** | 39.0% | no |
| Tightened: threshold 40 issuers (3.9% of tokens masked) | 174 | **68.4%** | 43.7% | no |

The model recognises the company from its figures and its business
(revenue $4.73 billion up 57%, "Data Center" and "Gaming" segments, is
NVIDIA to it). Tightening the mask did not help. This is what Lopez-Lira,
Tang and Zhu (2025) report: masking does not reliably stop memorisation.
**Arm B was therefore not run** (the plan: "C is look-ahead-free by
construction and is the arbiter if B's masking is doubtful"). The
re-score batch on the Sparks was not spent.

## Arm C: a point-in-time reader

ChronoBERT (`manelalab/chrono-bert-v1-<year>`, MIT licence, downloaded to
the RTX at 20:49-20:52 ET): for each release, the checkpoint whose training
text ends before the release's reaction date embeds the full text (up to
8,192 tokens, mean-pooled, 768 wide; 3,451 releases, 11 checkpoints, on the
RTX 5080). The vectors go through the 2026-09-07 study's walk-forward
ridge (`market_release_eval`: train 750 sessions, test 126, the 20-session
label purged, 5-session embargo, λ ∈ {100, 1000}), and every arm is scored
by `harness.evaluate_scores` on the same cells: the newest release on or
before the session, 20-session beta-adjusted residual, the book's names.

The in-window cells begin on 2018-01-31 (the first test fold) and end
2025-05-31; the post-window cells run from 2025-06-01.

| Arm, horizon 20 | In-window: cells 136,107, 93 periods | Post-window: cells 26,438, 15 periods |
|---|---|---|
| **A, the stored tone** (`release_tone/3`) | IC **+0.0368**, t 2.42, net Sharpe 0.26 | IC **+0.0390**, t 1.40, net Sharpe 0.68 |
| C, ChronoBERT ridge λ 1000 | IC **+0.0329**, t 2.09, net Sharpe 0.61 | IC +0.0048, t 0.11 |
| C, ChronoBERT ridge λ 100 | IC +0.0158, t 1.01 | IC +0.0099, t 0.23 |
| C (λ 1000) − A, paired on periods | **−0.0040**, t −0.22 | −0.034, t −0.82 |

At horizon 60 (reported): A +0.047 (t 2.0) in-window and +0.071 (t 2.7,
four periods) after; C +0.009 to +0.020.

## Reading

- **No fade after the cutoff.** If the reader's scores leaned on knowing
  what happened after each release, the IC of releases it cannot have seen
  in training (June 2025 onward) should fall. It is +0.039 against +0.037.
  The post-window is short (15 periods, standard error about 0.04), so it
  cannot rule out a modest fade on its own; it rules out a collapse.
- **A leak-free model matches it.** ChronoBERT never saw any of the
  releases or anything written after them, and a ridge on its vectors
  reaches +0.033 in-window against the tone's +0.037, a paired difference
  of −0.004 (t −0.2). Whatever the tone captures, a model with no way to
  know the outcome captures nearly as much of it. That is the plan's
  arbiter, and it says the edge is in the text.
- **The 2026-09-07 caveat is closed from the other side.** That study's
  general embedding read a quarter of each release and reached +0.013 to
  +0.031; the point-in-time full-text embedding reaches +0.033 with a
  higher net Sharpe (0.61 against 0.26 for the tone), because a
  continuous score churns less than four ranked integer fields.
- **Nothing replaces the analyst.** No arm beats A in-window, so criterion
  3's book gate was not run. C's post-window IC is near zero on 15 periods,
  which is inside noise but is not evidence for it.
- **The formal verdict is RECORD** because criterion 2 was written to read
  arm B. The registered fallback (C as arbiter) and the post-window
  reading both say "not inflated"; I do not upgrade the label, and I record
  the reading.

## Trials

Two registered (B and C); B could not be evaluated. The cumulative count
goes to 454.

## What this means for the desk

The A+ grade may keep resting on the sentiment analyst. The one live
change this line motivates is coverage, not the reader: five book names
file 6-Ks and have no tone at all (`trading/tone-6k`, built and gated,
not deployed).

## Disclosed

- The masking thresholds (15 and 40 issuers) were the plan's tightening
  rule; no score of any arm was read before the leak test result.
- The ridge's λ set is the 09-07 study's, fixed before this run; both are
  reported.
- The post-window cutoff, 2025-05-31, is the reader's reported training
  cutoff from a single third-party source, unconfirmed.
- The 09-07 texts were re-fetched from EDGAR on 2026-09-29 (3,451 releases,
  94 names, 1,301 s at SEC's pace) so that GLW and the releases since
  09-07 are included; the count equals the stored tone's.
