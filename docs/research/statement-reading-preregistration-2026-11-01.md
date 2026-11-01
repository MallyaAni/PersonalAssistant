# Statement reading: pre-registration — 2026-11-01

**Status: registered before any real packet was sent to the model or any
real label was read.** This note fixes the question, the packet, the prompt,
the arms, the gate and the placebo for A2 in
`docs/research/sota-survey-2026-10-01.md`. Nothing here changes the live
rule, the grades, the orders, the prompts or the risk dial.

The test window is historical (2026-08-03 to 2026-10-30), so this is not a
blind pre-registration in the strict sense. It is honest in the only way that
matters: before writing it, the only inspections were (a) coverage counts of
stored facts, (b) a synthetic-packet smoke test of the model endpoint, and
(c) the label-availability counts below. No real packet has been scored, no
model answer on real data has been read, and no accuracy number exists.

## Why this arm

The survey ranked A2 as "DeepSeek reads each name's last eight quarters of
standardised facts (no names, no dates) and emits a direction and a rationale;
scored as a stance." The published basis is Kim, Muhn and Nikolaev (2024):
GPT-4 reaches 60.35% accuracy predicting the direction of the next earnings
change against analysts' 52.71%; a tuned ANN reaches 60.4%, and an ANN fed
GPT's narrative reaches 63.2%. The statements were anonymised, and the
authors argue the accuracy is not training memory.

This desk already reads the same XBRL facts through `fundamentals_asof` and
scores every analyst with `harness.evaluate_scores`. What is new is the
narrative step: a model reading the shape of the record and committing to a
direction. The question is deliberately narrow: **does that direction, as a
cross-sectional stance, earn a rank IC on the desk's own honest universe, and
does the direction itself beat the analyst baseline?**

## Data and point-in-time rules

- **Store.** The live store at `data/market`, read-only. Fundamentals are the
  `edgar_facts_versions` frames; prices are the store's bars. No live file is
  written.
- **Decision dates.** The accuracy arm uses one decision date,
  **2026-08-03**, the start of the requested three-month window. The return
  arm uses every session from 2026-08-03 through the last session with a
  complete 20-session forward return (expected 2026-10-02). The pre-cutoff
  diagnostic uses **2024-08-01**.
- **As-of rule.** A `Version` enters the packet only when its `available`
  date is on or before the decision session. `available` is the desk's
  existing rule: the acceptance date in New York, moved to the next day when
  accepted at 16:00 ET or later, otherwise `filed + 1 day`. Future versions,
  restatements filed later, and versions whose acceptance is after the
  decision are excluded. This is the same rule `levels_for` uses.
- **Tag choice.** For each fact, the desk's per-session rank
  `fundamentals_asof._ranked_tags(name, by_tag, use_ytd=True)[0]` chooses one
  tag. The packet never mixes tags within a fact. The target's next-quarter
  net income is read under the **same net-income tag** chosen at the decision
  date; if that tag has no next-quarter value by the label's as-of date, the
  name has no label rather than borrowing a different measure.
- **Quarter series.** `fundamentals_asof._quarters` turns reported quarterly
  spans, YTD differences and annual remainders into `{quarter end: value}`.
  The stored series has gaps for some filers; the packet does not fabricate a
  zero to fill them.
- **Anchor.** The anchor is the latest net-income quarter end available by
  the decision date.
- **Rows.** The packet has eight calendar-quarter rows ending at the anchor.
  For each row, the value is the actual quarter value whose end is within
  **20 days** of that calendar quarter end; otherwise NA. This aligns a
  52/53-week fiscal calendar to the calendar row without printing a date. A
  row may be all NA when the filer did not report that quarter; the row stays
  so the model can see the gap.
- **Sample requirement.** A name enters a stance or accuracy sample only when
  the packet has at least **6 of 8** rows with net income and at least **6 of
  8** rows with revenue. The anchor's net income must be present. A name with
  fewer is missing, not neutral.
- **No future data.** The packet at session `t` reads only versions whose
  `available` date is on or before `t`. The mandatory perturbation test is in
  "The null test" below.

## The packet

The packet is dimensionless on purpose: no company name, ticker, sector,
industry, date, fiscal label, currency or absolute scale. Revenue is an index
with the most recent available quarter set to 100; every other field is a
ratio or a growth rate. This blunts memorisation more than the published
study's name-and-date removal, which kept absolute statements.

Each row carries:

| field | meaning |
|---|---|
| `quarter` | relative position, `t-7` … `t0`, oldest first |
| `revenue_index` | revenue / most recent available revenue × 100 |
| `revenue_yoy_pct` | revenue change against the quarter closest to 365 days earlier, divided by the absolute year-ago revenue |
| `revenue_qoq_pct` | revenue change against the previous packet row when the two actual ends are 75–105 days apart |
| `gross_margin_pct` | gross profit / revenue × 100 |
| `net_margin_pct` | net income / revenue × 100 |
| `ocf_margin_pct` | operating cash flow / revenue × 100 |
| `capex_pct_revenue` | capex / revenue × 100 |
| `net_income_yoy_pct` | net income change against the quarter closest to 365 days earlier, divided by the **absolute** year-ago net income |
| `net_income_qoq_pct` | net income change against the previous packet row, divided by the absolute prior value, when the two actual ends are 75–105 days apart |

A missing value is `NA`, never `0`. A zero denominator is `NA`, not an
infinite ratio. Values are rounded to two decimals.

## The prompt and schema

Prompt version **`statement-reading-prompt/1`**. The model is told:

- the table is an anonymised quarterly record for one company, oldest first,
  `t0` the most recent reported quarter;
- each row is a fiscal quarter and `NA` means not reported or not computable;
- the fields are dimensionless as defined above;
- negative net income is possible and the YoY/QoQ denominators are absolute;
- predict whether net income in the next reported quarter (`t+1`) is higher,
  lower or approximately equal to net income in the same quarter one year
  earlier (`t-3`), where `flat` means the change is within **1%** of the
  absolute year-ago value;
- answer `uncertain` only when the record does not support a direction;
- write a short analysis first, then the direction and a confidence in
  [0, 1];
- do not use outside knowledge about any company, industry, market or
  economy; base the answer only on the table.

Schema version **`statement-reading-schema/1`**, sent as `StrictSchema` with
`additionalProperties: false`:

```json
{
  "type": "object",
  "properties": {
    "analysis": {"type": "string", "minLength": 1},
    "direction": {"type": "string", "enum": ["up", "down", "flat", "uncertain"]},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1}
  },
  "required": ["analysis", "direction", "confidence"],
  "additionalProperties": false
}
```

The model is **`deepseek-v4.1-flash-1017`** at
`http://127.0.0.1:8000`, temperature **0**, `max_tokens` **1500**, reasoning
effort `none`. A call counts only when `finish_reason == "stop"`, the served
model id matches the requested id, and the content parses as JSON against the
schema. A `length` finish or an empty body is retried once at `max_tokens`
2500; a second failure is recorded as a runtime failure, and the stance is
missing rather than neutral.

## The target

For a decision date `D`, the anchor is the latest net-income quarter end
available by `D`. The next quarter is the first net-income quarter end after
the anchor under the same tag whose first public date is **after `D`** and on
or before the label as-of date. The year-ago quarter is the same tag's end
closest to 365 days before the next quarter, within 350–380 days. Both values
use the **first filed** value for their end (earliest `available`, then
`filed`, then accession), the number the market first saw.

The label is:

- `up` when `next - year_ago > 0.01 × |year_ago|`;
- `down` when `next - year_ago < -0.01 × |year_ago|`;
- `flat` otherwise;
- `flat` when `year_ago` is zero and `next` is zero, `up`/`down` otherwise.

If the next quarter is already available at `D`, or the year-ago value is
missing, the name has no label. The accuracy label as-of date is
**2026-10-30**; the pre-cutoff diagnostic's label as-of date is
**2024-12-31**.

## The arms

1. **Accuracy (primary mechanism check).** One packet per name at
   `D = 2026-08-03`, one model answer, one label. The sample is the PIT
   members at `D` with a valid packet and a same-tag label, expected about
   **344** names from the coverage probe. Accuracy excludes `uncertain`;
   coverage is the non-uncertain share.
2. **Stance (primary deployment check).** For every session from
   2026-08-03 to the last session with a complete 20-session forward return,
   each PIT member with a valid packet gets a stance: `+1` for `up`, `-1` for
   `down`, `0` for `flat`, missing for `uncertain` or no packet. The daily
   cross-sectional rank IC is `rank_correlation(stance, 20-session
   beta-adjusted residual forward return)` on names with both finite, minimum
   20 names. The primary statistic is the mean of the daily ICs; the
   Newey–West t uses lag **20**; the block bootstrap resamples the nine
   Monday–Friday weeks with replacement (2,000 draws).
3. **Book stance (deployment relevance).** The same daily stance on the 94
   live book names, no PIT membership mask, 20-session residual returns. This
   is the survivor-biased book, so it is a relevance check, not the honest
   test.
4. **Confidence-weighted stance (sensitivity).** `+confidence` / `-confidence`
   / `0` / missing instead of the sign. Reported, not gated.
5. **Strict alignment (sensitivity).** The packet is used from the session
   **after** its `available` date, not on it. Reported, not gated.
6. **Pre-cutoff diagnostic (lookahead).** The same packet, prompt and schema
   at `D = 2024-08-01`, label as-of 2024-12-31, expected about **419** names.
   The model's training cutoff is unverified; a much higher pre-cutoff
   accuracy is evidence consistent with memorisation, not proof of it.

The primary arms are 1 and 2. Arms 4–6 are sensitivities and diagnostics; no
result from them can turn a failed primary into a pass.

## The gate

**G1 — accuracy.** On the 2026-08-03 sample:

- at least **300** labelled names;
- directional accuracy at least **55.0%**;
- exact one-sided binomial p-value against **52.7%** below **0.05**;
- non-uncertain coverage at least **80%**;
- accuracy above the **95th percentile of 200 label-shuffle placebos**.

The placebo shuffles the model's direction answers across names, preserving
the answer distribution; it is the check that the model is not merely
exploiting the sample's base rate.

**G2 — stance.** On the PIT daily stance:

- at least **30** sessions with a defined IC;
- mean daily 20-session residual IC at least **0.02**;
- Newey–West t at lag 20 at least **2.0**;
- 95% lower bound of the weekly block bootstrap above **0**;
- mean IC above the **95th percentile of 200 within-day stance-shuffle
  placebos**.

The placebo shuffles the stance across names within each session, preserving
the missing mask.

**G3 — book.** The book's mean daily 20-session residual IC is at least
**0.0**. This is a relevance check, not a significance test.

**G4 — null test.** The perturbation and schema checks in "The null test"
pass.

**G5 — runtime.** Fewer than **2%** of model calls fail the finish-reason,
model-identity or schema checks.

**Pass = G1 and G2 and G3 and G4 and G5.** If the accuracy sample is below
300 or the stance has fewer than 30 defined sessions, the verdict is
**INCONCLUSIVE**, not a pass and not a fail. A failed primary is a fail even
if a sensitivity arm looks better.

## The null test

Before any real answer is read, the implementation must pass:

- **Future versions ignored.** Change every version whose `available` date is
  after `D` (value +1, or add a fake version); the packet at `D` must be
  byte-identical.
- **Newest past version read.** Change the newest version on or before `D`
  that contributes to the packet; the packet must change.
- **Missing is NA.** Remove every gross-profit version; `gross_margin_pct`
  must be `NA` for every row, not `0`.
- **No lookahead in the label.** The next-quarter value must have first
  public date strictly after `D`; a name whose next quarter was already
  public at `D` has no label.
- **Schema.** The schema serialises, has `additionalProperties: false`, and
  requires `analysis`, `direction` and `confidence`.

A failure stops the study.

## Regime splits (descriptive, not gates)

- **Calm:** 2026-08-03 to 2026-09-15.
- **Earnings:** 2026-09-16 to 2026-10-02, the last usable 20-session day.
- **Shock:** 2026-10-29 to 2026-10-30. These sessions have no complete
  20-session forward return by the as-of date, so they are reported as a
  stance distribution and next-session return, not as an IC.
- **Accuracy by filing month:** next-quarter first public date in August,
  September or October 2026.
- **Accuracy by sector:** the PIT cache's sector tag, technology/communication
  versus the rest.

The primary gate is on the full usable window. The splits answer the
operator's "different regimes" question without creating extra trials.

## What is already known, disclosed before the run

- Coverage at 2026-08-03: 499 PIT members; 436 with at least 6 of 8 net
  income and revenue rows; 344 with a same-tag next-quarter label. At
  2024-08-01: 464 members, 424 packets, 419 labels. The book has 94 names and
  a smaller packet sample.
- The store's quarterly tag series has gaps for some filers. The calendar-row
  packet and NA handling are the response; a gap is visible, not filled.
- The PIT panel is built from the store's bars over the 532 cached universe
  tickers, 2025-09-02 to 2026-10-30, with the dated S&P 500 membership
  history. The book panel is survivor-biased by construction.
- The model endpoint answered a synthetic packet under the strict schema in
  about 3 seconds. The served id was `deepseek-v4.1-flash-1017`.
- The checkpoint's training cutoff is unverified. The 2026 window may be in
  training. The dimensionless packet, the post-cutoff window and the
  pre-cutoff comparison are the mitigations, not a proof.
- The three-month window gives 43 daily IC observations but only nine
  independent weeks. The block bootstrap is the honest standard error; the
  Newey–West t is reported beside it.
- The accuracy sample is conditional on early Q3 reporters: a name that
  reports Q3 after 2026-10-30 has no label and is excluded. This is a
  selection caveat on G1, not a stance caveat.
- The model's `analysis` is stored but not scored. A qualitative audit of 20
  rationales checks for company names, tickers, dates or specific events;
  leakage is reported, not automatically a fail.

## What passing and failing mean

- **Pass:** a **252-session forward shadow** as a sixth stance, recorded
  nightly with the packet hash and the model answer, scored beside the live
  rule. No live change, no grade change, no order change, no prompt change,
  no risk-dial change before the shadow.
- **Fail:** written down with its evidence in `docs/research/`; not retried
  without a new pre-registration. The stance is not added to the grade, the
  board or any prompt.
- **Inconclusive:** written down with the coverage or label reason; a new
  pre-registration may widen the sample, but the current window is not
  re-read as a second trial.

## Amendments

None before the first result. If an amendment is needed before the first
result, it is written here and dated; after the first result, no amendment is
allowed.
