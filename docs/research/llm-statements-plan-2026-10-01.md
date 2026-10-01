# LLM financial-statement reading (A2): a model reads eight anonymised quarters and calls the next earnings direction, as a point-in-time stance. Pre-registration (2026-10-01)

**Status: registered before any code or number.** Queue item A2 of
[the survey](sota-survey-2026-10-01.md). Nothing here changes the live
book. The model calls run on the Sparks' DeepSeek server (one batch,
off-hours); this note, the code and the tests are written before the
first call is made.

## The question

Kim, Muhn and Nikolaev (2024, "Financial Statement Analysis with Large
Language Models") give GPT-4 a company's standardised, anonymised balance
sheet and income statement — no name, no dates — and ask whether earnings
will rise or fall in the next period. The model is right 60.4% of the
time against 52.7% for analysts and about the same as a tuned neural
network; a network fed the model's narrative reaches 63.2%; the long-short
portfolios built on the calls earn a higher Sharpe than the comparators
(no number in the brief read). Does a local model reading this desk's
own filed facts, in the same anonymised form, rank the book's names
better than the fundamental analyst that already reads the same facts
as ratios, at the desk's horizons, and in particular on the quarters the
model cannot have trained on?

## What is known before this note (disclosed)

- **The fundamental analyst** reads the same facts store as ratios
  (revenue growth, sequential growth, gross margin, acceleration; the
  corrected as-of source `fundamentals-features/2`): beta-adjusted rank
  IC 0.021 (t 2.3) at 20 sessions on the book (`NEXT_SESSION.md`, the
  `9dbe052d` correction). **The value analyst**: 0.048 (t 3.6) at 20,
  0.077 (t 3.3) at 60; size-neutral 0.036 (t 2.3) (`desk/value.py`).
  The evaluate step reports both comparators' ICs again on exactly the
  cells A2 is scored on, and those re-measured numbers, not these, are
  the comparison.
- **The reader's cutoff.** `deepseek-v4-flash` has read every 10-Q of
  these companies to May 2025. A statement block carries no name and no
  date, but a model that has memorised a company's revenue series can
  recognise it from the numbers alone; the paper anonymises for the same
  reason and reports that its model does not identify the firm. The
  in-window numbers (2018-01..2025-05) are therefore reported as
  look-ahead-contaminated unless the post-cutoff window (2025-06 on)
  agrees; **post-cutoff decides**, as it did for Kronos.
- **The facts store** (`edgar_facts_versions`, `fundamentals_asof`) holds
  every filed value with its filing date and SEC acceptance time, for:
  revenue, gross profit, net income, diluted/basic EPS, operating cash
  flow, capital expenditure (flows) and assets, debt, cash, equity,
  shares (instants). It does **not** hold operating income or total
  liabilities (no tag is parsed for them); cost of revenue is revenue
  less gross profit and total liabilities is assets less equity, both
  derived and labelled as such. Operating income is shown as "n/a". A
  tag addition would need a re-fetch of 94 names from SEC and is out of
  scope for this study.
- **Trials so far: 477** (A1 471, B1 474, B2 477).

## The arm

**Observations.** For each book name, walk the stored filing versions
in order of availability (acceptance time, as `fundamentals_asof.Version
.available` defines it: the acceptance date when accepted before the New
York close, else the next day; a filing with no time, the next day).
After each availability date, rebuild each line's quarterly series from
the versions public by then (the same tag choice and the same reported,
year-to-date-difference and annual-remainder arithmetic the fundamental
analyst uses: `_quarters`). Whenever the latest quarter end of the anchor
line (net income; revenue where net income is not filed) advances, one
observation is made, dated by that availability date. A restatement
that does not advance the quarter makes no observation. An observation
needs **eight consecutive quarters** of the anchor line (75-105 days
apart) ending at the latest quarter; names and quarters with fewer are
not scored.

**The block.** One plain-text table, in millions of the reporting
currency (EPS in units), eight columns labelled **Q1 (oldest) to Q8
(latest)**, twelve rows: revenue, cost of revenue (derived), gross
profit, operating income (n/a), net income, diluted EPS, operating cash
flow, capital expenditure, total assets, total liabilities (derived),
cash, debt. A line with no filed value at a quarter reads "n/a".
Numbers carry thousands separators and one decimal, so no run of four
digits (no year) can appear. The block carries **no company name, no
ticker, no calendar date, no fiscal-year label, no currency name and
no prose** — `backend/market/statements.py` builds it and a test
asserts the absence of every ticker, every issuer name in the universe,
every four-digit run and every month name over synthetic and, when
present, real blocks.

**The prompt** (`prompts/trading/statement_reader.md`, version
`statements/1`, `backend/agents/trading/statement_reader.py`): the model
is told it is reading the standardised quarterly statements of one
company, labelled relatively, and is asked for the **direction of net
income in the next quarter (Q9) against the same fiscal quarter one year
earlier (Q5)** — up or down — with a probability that it is up and a
three-sentence rationale, in a JSON schema `{direction, probability,
rationale}`. Year-over-year rather than sequential, because quarterly
earnings are seasonal and the paper's target is the year-ahead change;
the sequential direction (Q9 against Q8) is reported beside it from the
same probability and decides nothing. Temperature 0; the same client
plumbing as the tone reader (`OpenAICompatibleInferenceProvider`, one
client per worker thread); the answer is validated against the schema
and a mismatch between the stated direction and the probability's side
is counted and the probability kept.

**The stance.** `probability − 0.5` on each observation, dated by its
availability date (the first session on or after it), carried forward
until the next observation of the name; NaN before the first. Ranked
across the book as every analyst's score is (`Opinion.ranks()`), so
the arm is measured exactly as a sixth analyst would be read.

**Storage.** Store kind `edgar_statements`, one immutable frame per name
per as-of partition (quarter end, availability date, direction,
probability, rationale, the block's SHA-256, lines present, model,
prompt version), with a per-name partial JSONL that a rerun picks up,
as the tone pipeline does. A change of prompt version or model starts
the name over.

## Measurement

`market_statements evaluate`, reusing the text-surprise study's
measure (`harness.evaluate_scores` on the beta-adjusted residual,
`COST_BPS` 10, `MIN_NAMES` 15; the paired per-period IC against a
comparator; the mean per-session rank correlation with it): the arm,
the fundamental analyst (corrected source, as the desk builds it) and
the value analyst on their shared (session, name) cells of the book, at
20 and 60 sessions, in the plan's windows: **in-window 2018-01..2025-05**
and **post-cutoff 2025-06 on**. A stance table (`stances/A2.parquet`,
the analyst's own rule: top and bottom 30%, three sessions'
persistence) is written for the book gate.

**The direction-accuracy report**, deciding nothing: on every observation
whose next quarter is on file, the fraction where the stated direction
matched the realised year-over-year sign of the anchor line, overall and
on the post-cutoff observations, beside the paper's 60.4% and beside the
naive persistence call (the sign of Q8 against Q4 repeats). The
sequential (Q9 vs Q8) accuracy is reported too.

**The null test.** A constant 0.5 probability (stance 0 everywhere a
name is observed) must reproduce the harness's reading of a scoreless
signal: every period's rank IC undefined, so the report's mean IC is
NaN with zero defined periods, and the stance table is empty (a rank of
0.5 is neutral under the analyst's rule). Run before any model output
is read; a failure makes every number below it invalid.

## Criteria, fixed now (the A1 criteria)

A2 is **proposed as a stance** if, at 20 sessions:

1. its rank IC on the in-window period (2018-01..2025-05) is **≥ 0.02
   with t ≥ 2**, **and**
2. its post-cutoff IC (2025-06 on) is **not negative at t ≤ −1**, **and**
3. its paired IC against the fundamental analyst on their shared periods
   is **not negative at t ≤ −1**.

Its role follows its correlation with the two analysts that read the same
facts: mean per-session rank correlation **below 0.3 with both** the
fundamental and the value analyst makes it a **sixth-analyst candidate**;
otherwise a **replacement candidate** for the one it correlates with. A
candidate goes to the T-S1 book gate through its stance table (+2 bp of
equity a session at 25 bp over `graded-equal-weight/5`, NW t ≥ 2 on the
model window, not negative after, 15 of 20 offsets, deflated Sharpe at the
cumulative count ≥ 0.95; the scorecard's `--stance-table` flag is the same
follow-up A1 recorded). Anything else is **RECORD**. The accuracy report
and the 60-session numbers are reported and decide nothing.

## Trials and prior

One trial (one prompt version, one stance rule, one model); cumulative
**477 → 478**. Prior: **20%** that A2 clears the IC floor with the
post-cutoff window not contradicting it, **5%** the book gate. The likely
finding is a direction accuracy near the paper's on the in-window
quarters (memorised series) that falls toward 50% post-cutoff, and an IC
that correlates with the fundamental analyst's and adds nothing beside
it. If instead the post-cutoff accuracy holds above 55% with the IC
clearing the floor, the narrative step is doing something the ratios do
not, which is the paper's own claim.

## Permissions and cost

One batch on the Sparks' DeepSeek server (`deepseek-v4-flash`, vLLM,
port 8000): about 94 names × ~35 quarters ≈ **3,300 calls** (the panel's
bars start 2015-01-01, so only observations available from then are
scored — `--since`; the first 2015 blocks need 2013 facts, which the
company-facts feed carries; `plan` prints the exact count before any
call), each a block of ~1,500 characters in and ≤ 500 tokens out. At the tone run's measured
pace (four workers, a few seconds a call) that is **2-4 hours**, run
**off-hours only**, started after the 19:30 ET nightly and the 20:30 ET
SIP append have finished and never overlapping either; it resumes from
partials if stopped. No SEC fetch: the facts are already stored. Nothing
is written outside the store's `edgar_statements` kind and the scorecard
directory.

## Order of work

1. This note, committed alone. 2. Build with tests: the block builder
(`backend/market/statements.py`, anonymity test on synthetic facts), the
reader and its prompt (`backend/agents/trading/statement_reader.py`,
functional test under `backend/tests/functional/`, skipped without the
runtime), the CLI (`backend/cli/market_statements.py`: `plan` counts the
calls, `score` resumably, `evaluate` with the null test, the criteria and
the accuracy report), an independent check under
`docs/research/scorecards/llm-statements/`. 3. Run on the Sparks
(`ls_spark_study.sh`). 4. Write-up, report.
