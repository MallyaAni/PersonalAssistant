# Insider trades (Form 4) as a stance: net opportunistic open-market buying over 90 sessions. Pre-registration (2026-10-01)

**Status: registered before any code or number.** Queue item A4 of
[the survey](sota-survey-2026-10-01.md), the Form 4 arm only (analyst
revisions need a paid feed and are not registered).

## The question

Cohen, Malloy and Pomorski (JF 2012, "Decoding Inside Information") find
that *opportunistic* insider trades predict returns and *routine* ones do
not: an insider who trades in the same calendar month year after year is
following a liquidity or diversification schedule, and stripping those
traders out roughly doubles the information in the remaining trades
(their opportunistic long-short portfolio earns about 82 bp a month of
abnormal return against about 20 bp for routine trades). Does the net
open-market buying by a company's officers and directors, with the
routine traders removed, rank this book's names at the desk's horizons?

## What is known before this note (disclosed)

- **The literature.** The insider-trading anomaly is old (Seyhun 1986,
  Lakonishok and Lee 2001): purchases predict, sales mostly do not, and
  the effect is strongest in small firms. Cohen-Malloy-Pomorski add the
  routine/opportunistic split, which is where the predictability
  concentrates, and show it survives size and liquidity controls.
- **Nothing measured here.** The desk has never read a Form 4. No
  insider field exists in any analyst, the EDGAR layer reads 8-K/6-K
  events and company facts only.
- **The caveats this book carries.** Long-only, 94 US large caps.
  Large-cap insiders are net sellers almost always (option exercises
  followed by sales), so the cross-section will be ranked mostly by *how
  much* insiders sold, with the rare purchase at the top; the published
  effect is concentrated in purchases and in small firms. Five book
  names (TSM, ASML, ARM, NBIS, SIMO) are foreign private issuers exempt
  from Section 16: they file no Form 4 and will sit at zero (neutral).
- **Filing lag.** Since Sarbanes-Oxley (2002) a Form 4 is due within
  two business days of the transaction; the one quarter inspected
  (2024q1) shows a median lag of 2 days, p90 of 4, and a long tail of
  late filings (p99 711 days, a 2022-11 sale filed in 2024-01). Dating
  must therefore use the *filing* date, never the transaction date.

## Data source (decided here)

The SEC publishes the **Insider Transactions Data Sets**: one zip per
calendar quarter from 2006q1 (`https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets`),
each holding the structured content of every Form 3/4/5 filed in the
quarter as tab-separated tables (`SUBMISSION`, `REPORTINGOWNER`,
`NONDERIV_TRANS`, `DERIV_TRANS`, holdings, footnotes). One request per
quarter, 82 files as of today, against thousands of per-filing XML reads
per name on the per-filing path. Verified from the sandbox on
2026-10-01 with two requests under the repository's declared EDGAR
`User-Agent` (`backend/market/edgar.py`): the index page listed 82 zips
(`/files/structureddata/data/insider-transactions-data-sets/<yyyy>q<n>_form345.zip`;
the newest quarter sits under a different prefix,
`/files/datastandardsinnovation/...`, so the fetch reads the index
rather than assuming the pattern), and `2024q1_form345.zip` (13.9 MB)
holds 67,671 submissions, 111,404 non-derivative transaction rows and
71,738 owner rows. Its columns, as used:

- `SUBMISSION`: `ACCESSION_NUMBER`, `FILING_DATE` (DD-MON-YYYY),
  `DOCUMENT_TYPE` (4, 4/A, 3, 5, ...), `ISSUERCIK`,
  `ISSUERTRADINGSYMBOL`, `AFF10B5ONE` (the Rule 10b5-1 plan flag, values
  0/1/true/false/blank; populated only for filings since the 2023 form
  change).
- `NONDERIV_TRANS`: `TRANS_DATE`, `TRANS_CODE` (P purchase, S sale, F
  tax withholding, M option exercise, A grant, ...), `TRANS_SHARES`,
  `TRANS_PRICEPERSHARE` (blank on 0.14% of P/S rows),
  `TRANS_ACQUIRED_DISP_CD`, `DIRECT_INDIRECT_OWNERSHIP`,
  `TRANS_TIMELINESS` (E/L/blank).
- `REPORTINGOWNER`: `RPTOWNERCIK`, `RPTOWNER_RELATIONSHIP` (comma-joined
  from Officer, Director, TenPercentOwner, Other).

**What the bulk data lacks:** the acceptance *timestamp*. It carries the
filing date only. The dating rule below is therefore the conservative
one: a filing dated D is first usable on the first session strictly
after D (most Form 4s are accepted after the close; a morning filing
loses one session). If a per-filing acceptance time is ever wanted, the
submissions API already read by `edgar.py` has it, at one request per
filing.

Cost: about 82 zips at 3-15 MB each (older quarters are smaller), about
0.7-1.2 GB, one request per quarter at the EDGAR pacer's spacing;
download-bound, minutes rather than hours. Stored once, immutably, as
`edgar_insiders` frames (one per quarter, keyed by the quarter label in
the ticker slot, holding the P and S rows of every issuer with the
columns above, about 33,000 rows a quarter, and the zip's SHA-256 in the
frame's metadata); the raw zips are kept beside the store under
`<root>/edgar_insiders_zips/` so a re-parse never re-fetches. A re-run
skips every quarter the partition holds, so a throttled run resumes.

## The signal, fixed now

Per name, per session t, from the stored rows:

1. **Admitted rows.** Form 4 originals only (`DOCUMENT_TYPE` = 4;
   amendments restate a filing already counted and are refused rather
   than double-counted; Forms 3 and 5 carry no open-market trade or a
   deferred one). `TRANS_CODE` P or S. At least one reporting owner whose
   relationship includes Officer or Director (the first such owner's CIK
   identifies the insider; pure 10% owners and "Other" are refused). Not
   flagged as a 10b5-1 plan trade where the data marks it (`AFF10B5ONE`
   in {1, true}); filings before the flag existed are admitted as they
   are, and this is disclosed. Shares present and positive. Price from
   `TRANS_PRICEPERSHARE`; when blank, the name's close on the session the
   row becomes known.
2. **Dating.** A row becomes known on the first session strictly after
   its `FILING_DATE`. The transaction date is used for the routine rule
   (which is about *when insiders trade*) and for nothing else.
3. **The routine rule (Cohen-Malloy-Pomorski), point in time.** For an
   insider (issuer CIK, owner CIK) filing in calendar year y: the
   insider's prior P/S transactions filed before this row's filing date
   are grouped by (transaction year, transaction month). The insider is
   *classifiable* when each of years y−1, y−2 and y−3 holds at least one
   trade, and *routine* when some calendar month holds a trade in each
   of those three years. The **opportunistic arm** admits a row only when
   its insider is classifiable and not routine; the **all-insiders arm**
   admits every row of step 1.
4. **The window.** Over the trailing 90 sessions (rows known on sessions
   t−89..t): net dollars = Σ P shares × price − Σ S shares × price.
5. **The scale (one, fixed).** Net dollars divided by the name's median
   daily dollar volume (close × volume) over the same 90 sessions; NaN
   when fewer than 45 of those sessions have a bar. A name with a
   denominator and no admitted row scores exactly 0, never NaN, so a
   quiet name stays in the cross-section as neutral.
6. **The stance.** The percentile rank of the signal across the book on
   each session (`Opinion.ranks`); the stance table applies the
   analysts' own rule (top and bottom 30%, three sessions' persistence).

Two registered arms: **A4-opp** (opportunistic only) and **A4-all** (all
insiders). Both are measured through `harness.evaluate_scores` on the
book's names at 20 sessions (60 reported), beta-adjusted residual, on the
cells shared with the comparison arm.

**The comparison arm** is the desk's five analysts as they stand: the
plain rule's summed conviction (`desk.run(inputs=())`, `DeskReport.scores`),
ranked. The paired IC and the correlation are against it.

## Criteria, fixed now (A1's, with the halves)

An arm is **proposed as a stance** (a sixth analyst when its mean
per-session rank correlation with the desk is below 0.3, else a
replacement candidate) if its 20-session rank IC on 2018-01..2025-12 is
≥ 0.02 with t ≥ 2, **and** the ICs of the two halves (2018-2021,
2022-2025) are not opposite in sign, **and** its paired IC against the
desk is not negative at t ≤ −1, **and** the T-S1 book gate holds on its
stance table (+2 bp of equity a session at 25 bp over
`graded-equal-weight/5`, NW t ≥ 2 on the model window, not negative
after, 15 of 20 offsets, deflated Sharpe at the cumulative trial count ≥
0.95). 2026 is reported beside as out-of-window. Anything else is
**RECORD**.

**The null test**, run before either arm is read: an empty transaction
table through the same pipeline must give exactly 0 on every cell with a
denominator, a rank of 0.5 everywhere, an empty stance table and no
defined IC in any period, which is what a sixth analyst with no view
contributes to a grade. A pipeline that turns "nothing on file" into NaN
or into a rank would be measuring its own coverage.

## Trials and prior

Two trials (the two arms; the scale, window and rule are fixed above and
not searched); cumulative 478 → 480. Prior: 15% that an arm clears the
IC floor, 5% the book gate. The likely finding is that large-cap
insiders sell on schedule, the opportunistic residue is thin on 94
names, and the IC sits near zero with a wide t.

## Order of work

1. This note, committed alone. 2. Build with tests: `backend/market/insiders.py`
(the zip into a per-name transaction frame, the routine rule, the
trailing-window signal, dating by filing), `backend/cli/market_insiders.py`
(`fetch`: paced, resumable, SHA-256 recorded, skipping what the
partition holds; `build`: the signal tables; `evaluate`: as the
text-surprise study measures, writing the stance tables and the
scorecard follow-up command), an independent check under
`docs/research/scorecards/insider-stance/`. Tests on synthetic tables:
the routine rule across three years, the window arithmetic, filing-date
dating (a late-filed trade must not appear before its filing), net of
buys and sells, the null. 3. Fetch on spark1 at the SEC's pace, then
build, evaluate and check, niced, outside market hours. 4. Write-up.
