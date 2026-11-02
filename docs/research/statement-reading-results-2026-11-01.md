# Statement reading: results — 2026-11-01

**Status: A2 FAILED its pre-registered gate on coverage (G1) and stance
significance (G2). G3, G4 and G5 pass. The statement-reading stance is not
added to the live system; the idea is written down and not retried without a
new pre-registration. Nothing goes live.**
This is the result of `statement-reading-preregistration-2026-11-01.md`, run
after the note was committed. The live rule, grades, orders, prompts and risk
dial are unchanged.

## The question

Can the local model read one company's last eight anonymised quarters — no
name, ticker, sector, date or absolute scale — and commit to whether next
quarter's net income will be higher, lower or flat against the same quarter a
year earlier; and does that direction work as a cross-sectional stance against
20-session beta-adjusted residual returns on the honest PIT universe? The
accuracy arm is the mechanism check; the stance arm is the deployment check.
The book arm is a relevance check, not the honest test.

## The headline

The model read the table and committed to a direction on **73.0%** of the 378
labelled names. Its accuracy was **67.4%**, above chance and above the
label-shuffle placebo, but **below the 71.7% majority baseline** and below the
registered **80%** coverage gate. The stance's mean daily 20-session residual
IC was **0.0177**, below the **0.02** gate, with a Newey–West t of **0.68** and
a weekly-block-bootstrap lower bound of **−0.0222**. The calm window was
**+0.0423**; the earnings window was **−0.0411**. The book relevance check
passed at **0.0690**, but the book is survivor-biased and its bootstrap lower
bound is also negative. The pre-cutoff accuracy was **67.8%** and the
post-cutoff **67.4%**; the lookahead diagnostic shows no memorisation
advantage. The verdict is **FAIL**.

## What ran

- **Pre-registration.** `docs/research/statement-reading-preregistration-2026-11-01.md`,
  committed before the first real answer (`36eddfc8`). Packet
  `statement-reading-packet/1`, prompt `statement-reading-prompt/1`, schema
  `statement-reading-schema/1`, model `deepseek-v4.1-flash-1017`.
- **Implementation.** `backend/market/statement_reading.py` (packet, label,
  prompt, strict schema, stance, IC, Newey–West, block bootstrap, placebo,
  null test) and `backend/cli/market_statement_reading_research.py` (PIT
  packets, samples, model cache, scoring, gates).
- **Tests.** `backend/tests/test_statement_reading.py`: 20 passed. Ruff clean
  on all four changed Python files. The functional prompt test,
  `backend/tests/functional/test_statement_reading_behaviour.py`, passed in the
  Docker functional gate (1 passed, 11.40s) before the study.
- **Model.** Temperature 0, `max_tokens` 1500 with a single retry at 2500,
  reasoning effort `none`. The strict schema, the `finish_reason == "stop"`
  check and the served-model identity check were enforced. The final pass made
  **385 calls with 0 failures**.
- **Data.** PIT panel 294 sessions × 532 cached names, 2025-09-02 to
  2026-10-30, with the dated S&P 500 membership history; book panel 94 names
  plus SPY, survivor-biased by construction. Decision **2026-08-03**; label
  as-of **2026-10-30**; stance window 2026-08-03 to 2026-10-02.
- **Run.** The first pass was stopped at the 2-hour background limit after 930
  model calls. The resume completed the remaining packets from the cache: 1,374
  unique packets, 989 cache hits, 385 calls, 0 failures. The answers are the
  first pass's where cached; the cache is the record.

## The sample

At 2026-08-03 there were **499 PIT members**; **481** had a valid packet and
**378** had a same-tag next-quarter label. The labels were up 265, down 101
and flat 12. At 2024-08-01 the pre-cutoff sample had **418** labels. The book
has 94 names; 171 unique book packets. The PIT packets reduce to 957 unique
answers, the strict-alignment packets to 766, and the whole study to **1,374**
unique packets after deduplication.

The pre-registration's coverage probe expected about 436 packets, 344 labels,
43 daily IC sessions and 419 pre-cutoff labels. The registered implementation
found 481 packets, 378 labels, 44 sessions and 418 pre-cutoff labels. The probe
was a conservative coverage estimate under a stricter construction, not the
registered rule; the actual counts are used and clear the 300-label and
30-session minima. The 44th session is the inclusive 2026-08-03 to 2026-10-02
window.

## Accuracy (arm 1, G1)

| sample | labelled | answered (non-uncertain) | coverage | correct | accuracy | binomial p vs 52.7% | majority | placebo p95 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2026-08-03 | 378 | 276 | **73.0%** | 186 | **67.4%** | 5.1e-7 | **71.7%** | 54.7% |

The 102 `uncertain` answers are the binding constraint on G1: coverage is
**73.0%** against the **80%** gate. The accuracy itself clears the 55% floor,
the exact one-sided binomial p against 52.7% is far below 0.05, and 67.4%
beats the placebo's 95th percentile of 54.7%. But the model's accuracy is
**below the 71.7% majority baseline** on the answered rows: always answering
`up` would have been more accurate than the model's mix. The model's answered
directions were up 156, down 107 and flat 13; the answered labels were up 198,
down 72 and flat 6. The model was more pessimistic than the labels.

The label-shuffle placebo (200 draws) had mean 50.8% and p95 54.7%; the model's
67.4% is above it, so the accuracy is not merely the sample's base rate. It is
still below the base rate of the answered sample, which is the stronger
diagnostic.

**By filing month (the next quarter's first public date):**

| month | labelled | answered | accuracy | coverage |
|---|---:|---:|---:|---:|
| August 2026 | 193 | 137 | 64.96% | 71.0% |
| September 2026 | 19 | 14 | 64.29% | 73.7% |
| October 2026 | 166 | 125 | 70.40% | 75.3% |

Every filing month is below the 80% coverage gate. The October reporters — the
later Q3 filers — are the most accurate at 70.4%, but still below the 80%
coverage gate and below the sample's majority.

**By sector:**

| group | labelled | answered | accuracy | coverage |
|---|---:|---:|---:|---:|
| technology / communication | 66 | 53 | 73.58% | 80.3% |
| other | 312 | 223 | 65.92% | 71.5% |

The model is more accurate and more willing to commit inside technology and
communication (73.6% accuracy, 80.3% coverage on 66 names) than outside it
(65.9%, 71.5%). The tech/communication slice alone would clear the coverage
gate; the full sample does not, and the sector split is descriptive, not a
second trial.

**Selection caveat.** The accuracy sample is conditional on early Q3 reporters:
a name that reported Q3 after 2026-10-30 has no label and is excluded. This is
a caveat on G1, not on the stance window.

## Stance (arm 2, G2)

| arm | sessions | defined | weeks | mean IC | NW t (lag 20) | bootstrap 95% | placebo p95 |
|---|---:|---:|---:|---:|---:|---|---:|
| PIT, sign stance | 44 | 44 | 9 | **0.0177** | **0.68** | **−0.0222 .. +0.0588** | 0.0138 |
| PIT, confidence-weighted | 44 | 44 | 9 | 0.0235 | 0.63 | −0.0370 .. +0.0832 | 0.0144 |
| PIT, strict alignment | 44 | 44 | 9 | 0.0171 | 0.64 | −0.0245 .. +0.0599 | 0.0126 |
| book, sign stance | 44 | 44 | 9 | **0.0690** | 1.12 | −0.0099 .. +0.1458 | 0.0280 |

G2 fails on all three primary significance conditions: the mean IC is below
0.02, the Newey–West t is below 2.0, and the weekly block bootstrap's 95% lower
bound is below zero. The mean is above the within-day stance-shuffle placebo's
95th percentile (0.0177 vs 0.0138), so the stance is not a pure missing-mask
artefact, but the placebo check alone does not carry the gate.

The confidence-weighted sensitivity raises the mean to 0.0235, above the 0.02
floor, but its Newey–West t is 0.63 and its bootstrap lower bound is −0.0370;
it does not turn the failed primary into a pass, and the pre-registration
forbids using a sensitivity to do so. The strict-alignment sensitivity is
essentially the primary (0.0171). Neither is a new trial.

The stance distribution over the window was up 9,855, down 5,605, flat 539 and
missing 5,932 member-session cells. The missing share is 27.0%, the same as the
accuracy sample's uncertain rate.

## Regimes (descriptive, not gates)

| regime | sessions | defined | mean IC |
|---|---:|---:|---:|
| calm, 2026-08-03 .. 2026-09-15 | 31 | 31 | **+0.0423** |
| earnings, 2026-09-16 .. 2026-10-02 | 13 | 13 | **−0.0411** |
| full window | 44 | 44 | +0.0177 |

The stance's sign flipped across the operator's "different regimes" question:
positive in the calm window, negative through the earnings window. The full
window's small positive mean is the calm period's carry, not a stable edge.
This is the clearest descriptive result in the study and the reason the
full-window gate is the right one: a regime-conditional stance is not a
standalone stance.

The shock sessions, 2026-10-29 and 2026-10-30, have no complete 20-session
forward return by 2026-10-30. Their stance distribution was up 453, down 268,
flat 28 and missing 245. The next-session beta-adjusted residual by stance was
up **+0.095%** (226 names), down **+0.413%** (132 names) and flat **+1.638%**
(16 names): the names the model called down did not fall faster than the names
it called up on the first shock session. The sample is two sessions; this is
description only.

## Book relevance (arm 3, G3)

The book's mean daily 20-session residual IC was **0.0690** over 44 sessions,
above the G3 floor of 0.0, so G3 passes. It is not a significance result: the
Newey–West t is 1.12, the bootstrap lower bound is **−0.0099**, and the book is
the survivor-biased 94-name universe, not the honest PIT universe. The book's
stance distribution was up 2,131, down 1,015, flat 44 and missing 946 cells.
The positive book mean is a relevance signal worth remembering, not evidence
that the stance would have improved the live book.

## Pre-cutoff lookahead (arm 6)

| decision | labelled | answered | coverage | correct | accuracy | majority | placebo p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2024-08-01 | 418 | 292 | 69.9% | 198 | **67.8%** | 60.3% | 49.7% |
| 2026-08-03 | 378 | 276 | 73.0% | 186 | **67.4%** | 71.7% | 54.7% |

The full-sample accuracy is **0.42 percentage points lower** than the
pre-cutoff accuracy (difference −0.00417). If the checkpoint's training window
includes 2024 but not 2026, the lookahead diagnostic shows no post-cutoff
advantage: the model was not more accurate on the window it may have seen. The
training cutoff is unverified, so this is evidence consistent with no
memorisation advantage, not proof. The pre-cutoff sample's majority was 60.3%
and the model's 67.8% beat it; the 2026 sample's majority was 71.7% and the
model's 67.4% did not. The label mix, not the model's skill, explains much of
the difference.

## Null test and rationale audit

The registered null test passed on the first accuracy name, A:

- future versions, however large, leave the packet byte-identical:
  `future_identical = true`;
- a material change to the newest anchor net-income version moves the packet:
  `newest_changes = true`;
- removing gross profit leaves every gross margin `NA`:
  `missing_is_na = true`;
- the schema is strict: `schema_ok = true`.

The packet's anchor for A was 2026-04-30 under `us-gaap:NetIncomeLoss`.

A qualitative audit of 20 cached rationales found no company names, tickers,
dates or specific events. The only uppercase tokens were field abbreviations
(`NI`, `OCF`); the two occurrences of "may" were the modal verb, not the month.
The rationales were grounded in the packet's own quantities — `t-3`,
`revenue_index`, margins and the YoY/QoQ fields — and several explicitly
computed a relative net-income proxy from `revenue_index × net_margin_pct`.
Leakage is reported, not automatically a fail; none was found in the sample.

## The gate

| gate | criterion | actual | result |
|---|---|---|---|
| G1 | labelled ≥300; accuracy ≥55%; binomial p<0.05; coverage ≥80%; accuracy > placebo p95 | 378; 67.4%; 5.1e-7; **73.0%**; 67.4% > 54.7% | **FAIL (coverage)** |
| G2 | defined sessions ≥30; mean IC ≥0.02; NW t ≥2.0; bootstrap lower >0; mean IC > placebo p95 | 44; **0.0177**; **0.68**; **−0.0222**; 0.0177 > 0.0138 | **FAIL** |
| G3 | book mean IC ≥0.0 | 0.0690 | pass |
| G4 | null test | all four checks | pass |
| G5 | failure rate <2% | 0 of 385 calls | pass |

**Verdict: FAIL.** The sample is not inconclusive — 378 labels clear the
300-name minimum and 44 defined sessions clear the 30-session minimum. A failed
primary is a fail even though the book relevance check and the confidence
sensitivity look better; the pre-registration says no sensitivity can turn a
failed primary into a pass.

## What this means

- **No live change.** The statement-reading stance is not added to the grade,
  the board, any prompt or the live rule. The installed
  `grade-led-leader-weight/1` remains frozen for its 252-session window.
- **The idea is closed.** It is written down here with its evidence and is not
  retried without a new pre-registration. The prompt, gate and sample are not
  being tuned after reading the answers.
- **What the evidence supports.** The model can read the table and commit to a
  direction; its rationales are grounded; its accuracy is above chance and
  above the label-shuffle placebo. That is not enough: 27% uncertainty breaks
  the coverage gate, the accuracy is below the majority baseline, and the
  stance's full-window IC is not significant. The calm/earnings sign flip is
  the most useful diagnostic for any future design: a stance that only works
  outside earnings season is not a standalone stance.
- **What is not supported.** A 2026-only or calm-window reading of the stance
  would be a second trial on the same answers. The pre-registration forbids
  it; this note does not do it.

## Caveats and disclosures

- **Runtime interruption.** The first pass was stopped by the 2-hour background
  limit after 930 calls; the resume completed the remaining 385 calls from the
  cache. The final pass had 0 failures. The answers are the first pass's where
  cached, so the study is conditional on those answers.
- **Nondeterminism.** The endpoint answered the same real packet differently
  in two earlier probes (ticker A: `up` in the single smoke test, `flat` in the
  eight-worker warm-up) despite temperature 0. The cache fixes the answers used
  here; a fresh run could produce a different sample. This is a runtime
  property, not a prompt or gate change.
- **Training cutoff.** The checkpoint's cutoff is unverified. The 2026 window
  may be in training. The dimensionless packet, the post-cutoff window and the
  pre-cutoff comparison are mitigations, not proof.
- **Selection.** The accuracy sample is conditional on early Q3 reporters; the
  filing-month split is reported. The stance window has 44 sessions but only
  nine independent weeks; the weekly block bootstrap is the honest standard
  error and the Newey–West t is reported beside it.
- **Book survivor bias.** The 94-name book is today's book; its 0.0690 mean IC
  is a relevance check, not the honest PIT test. Its bootstrap lower bound is
  negative and its Newey–West t is 1.12.
- **Analysis not scored.** The model's `analysis` is stored but not scored; the
  20-rationale audit is qualitative. A different 20 could contain leakage the
  sample did not.
- **Failure-rate definition.** G5 counts packets that failed the finish-reason,
  model-identity or schema checks after the registered retry; the final pass
  had 385 packets and 0 failures. The first pass's successful answers are the
  cache; any first-pass failure was retried by the resume.

## Files and verification

- Pre-registration: `docs/research/statement-reading-preregistration-2026-11-01.md`.
- Implementation: `backend/market/statement_reading.py`,
  `backend/cli/market_statement_reading_research.py`.
- Tests: `backend/tests/test_statement_reading.py` (20 passed);
  `backend/tests/functional/test_statement_reading_behaviour.py` (passed in
  the Docker functional gate).
- Result: `docs/research/scorecards/statement-reading/result.json`.
- Test wiring: the `functional-tests` service in `docker-compose.yml` carries
  `STATEMENT_READING_URL` and `STATEMENT_READING_MODEL`, so the prompt test
  cannot silently skip under `ANIOS_REQUIRE_FUNCTIONAL=1`.
- Ruff clean on the four changed Python files.

## Next

The A2 study is finished. The P1 forward record is the highest-priority
workstream: the week of 2026-11-02 is written after the week closes on Friday
2026-11-06, with no interim performance decisions. The ordinary nightly on
2026-11-02 fills the three 10-30 orders at the open and produces the first
parity row after the 2026-11-01 deploy. C5 sector rotation and positive-shock
drift remain owner-blocked. No live rule, grade, order, prompt or risk-dial
change follows from this study.
