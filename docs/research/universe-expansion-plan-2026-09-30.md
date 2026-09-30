# A reshaped: grading a larger point-in-time universe. Pre-registration (2026-09-30)

**Status: registered, not started.** It waits for the operator's go-ahead on
the two downloads and the membership rule under "Permissions".

## The question

`graded-equal-weight/5` holds every A/A+ name of the 94-name book at equal
weight, capped at 25%, reset every 20 sessions. The cap binds when fewer
than five names qualify: on 10.9% of sessions in 2016-2017, 19.0% in
2018-2023 and 42.5% in 2024-2026 (operator's brief). The median session has
seven A/A+ names on 2016-2023 and five on 2024-2026 (cap sweep). On those
sessions the book is one to four names and the rest is cash.

**Would the same desk, grading a larger point-in-time universe, give more
A/A+ candidates, a less concentrated book, and equal or better return,
measured exactly as the live policy is?** Timing and the chart CNN are out
of scope; the allocator is `/5` unchanged in every arm.

## What is known before this note (disclosed)

**The store (spark1, `data/market`, as of 2026-09-29).**

- `build_universe()` has 531 stock members (503 S&P 500 constituents dated
  2026-09-05, 28 overlay names with no GICS). 94 form the book
  (`book_sides`: five sub-industries or the overlay).
- Daily bars: all 531; 474 from 2016-01-04 or earlier, 57 list later
  (4-8 a year). Of the book, 65 of 94 have bars from 2016-01-04.
- EDGAR events and facts: 531 of 531. Versioned facts
  (`edgar_facts_versions`, what the corrected fundamental analyst reads):
  **94 only**. Release tone: **267 names**, 11,461 scored releases: the 94
  book names (3,451 rows, `release_tone/3`) and 173 non-book names (7,614
  rows at `/3`, 396 at `/1`, partitions 2026-09-05/14, produced for the
  expectations gap). 264 non-book names have no tone.
- So of the five analysts: technical runs on all 531; value and the
  expectations gap run on all 531 (the gap already builds the 531-name
  panel and projects onto the book); sentiment on 267; fundamental on 94
  until versions are fetched; the rotation analyst and the value peer group
  need a "side", which only book names have (`regime.opine`, `value.opine`
  are gated on `sides`).
- A name with no tone gets stance 0, not a bear: it can be graded A but
  never A+ (`grading.grade_stances`). Stances are the top and bottom 30% of
  each analyst's cross-sectional rank (`opinions.STANCE_FRACTION`), so the
  A count scales with the cross-section: about 17% of eligible names on the
  book, roughly 80 a session on 500 names, and the cap would never bind.

**Membership.** `membership_history.csv` (110 intervals, 94 names) is built
by `market_membership` from the 2026-09-05 constituent file walked backward
through the Wikipedia change table (`sp500_changes_wikipedia.csv`, 244
changes since 2016-01-04) and filtered to the book sub-industries; overlay
names enter on their commit date (all September 2026).
`point_in_time.eligibility` makes a name eligible from `max(entered,
entry_announced)` to `exited`; announced is set equal to effective, so
entries are late, never early. The same table dates the whole index: about
336 of today's 503 were in it on 2016-01-04, 167 entered later; **216 names
that left the index during the window have no bars in the store**. The
book's control has the same hole (16 exits, BRCM to PAYC, none with bars).

**Prior results.** The point-in-time arms (2026-09-26): EW of every
eligible book name 27.7% CAGR 2016-2023, A/A+ uncapped 29.9% (t 1.5 vs
EW): the grade selects a little. The cap sweep: `/5`'s 25% cap 28.7%
(2016-2023) and 48.5% (2024-2026) at 25 bp. `universe.py` records that
adding the 19 regulated utilities to today's hindsight book measured 38.45%
against 34.12% (not point-in-time, not a trial). The coverage audit
(2026-09-25) rejected the community `fja05680/sp500` history as
ready-to-use membership and put name choice on the hindsight book at 19
CAGR points a year. Cumulative trial count: 454.

## Arms

All arms: `desk.run` with `EXPECTATIONS_GAP`, the `/5` allocator
(A/A+, equal weight, cap 0.25, gross 1.0), the point-in-time mask.

- **Control, book-94.** The live policy on the live membership file. Its
  lines are the scorecard's `rule / point-in-time` and `equal weight /
  point-in-time`, re-run on the same store day as the candidates.
- **U-sector (the candidate).** The 503 constituents graded by the same
  five analysts, with the cross-section for every analyst's rank and for the
  value peer group being the name's **GICS sector** (11 groups; overlay
  names keep the book's side and count in Information Technology). Stances
  are then "top 30% of its sector", the grade keeps its meaning, and the A
  count scales with sectors, not with N. The rotation analyst's stance is
  applied only to book sides (it is a view about AI vs software); all other
  names get 0. Tone is used where it exists and absent where it does not
  (stance 0), which is the desk's existing rule. This is the primary arm.
- **U-flat.** The same 503 with one universe-wide cross-section, as the
  desk works today: the literal "grade more names", expected to be an
  ~80-name EW portfolio and roughly index-like.
- **U-tone.** U-sector restricted to the 267 names with tone (94 + 173), so
  A+ is possible everywhere. The 173 were chosen by the gap's coverage, not
  by returns: a coverage subset, not a selection. Shows what completing
  tone would be worth.

Three trials (U-sector, U-flat, U-tone). Fundamentals: the candidate needs
versioned facts for 437 names (see Permissions); if refused, the fundamental
analyst is absent outside the book and the arm is **RECORD**, not a trial.

## The point-in-time membership rule for the candidate

A separate file, `membership_history_sp500.csv`, in the same schema, built
by `market_membership` with the sub-industry filter removed: every current
constituent from `max(2016-01-04, index entry effective date)` to its exit
if any, announced = effective; overlay names as today. The same
`eligibility`, `restrict` and `equal_weight_allocator` read it.

**The look-ahead risks, named.**

1. **Survivorship of the exited: the main trap.** 216 names left the
   index 2016-2026 and have no bars. On 2016-01-04 the candidate holds
   ~336 of the ~500 real constituents, the ones that stayed: a winners'
   subset. The control has the same defect at smaller scale (16 of ~50).
   The candidate's rule line and its EW-PIT hurdle share the bias, so the
   **paired difference** (grade vs EW on the same names) is the readable
   number; the **absolute CAGR is inflated** and reported as such.
   Recovering exited names needs delisted price history, and no free,
   licence-clean source was found (Norgate USD 630/yr; CRSP licensed):
   a stated limit, not a task.
2. **Ticker reuse.** A current ticker that belonged to another company
   earlier (Q, DAY) is excluded for that interval; renames the table lacks
   (FLT→CPAY) are dropped by `index_intervals` and reported.
3. **Classification drift.** Today's GICS sector is carried backward; the
   2018 and 2023 reclassifications move some peer groups by up to two
   years. Accepted: the sector is a rank group, not a signal.
4. **Announcement vs effective.** Entries are dated effective, after the
   announcement: conservative.

**Data to obtain** (free, licence-clean): none for membership; the change
table and dated constituent file are committed. Versioned facts for 437
names come from SEC `companyfacts` (one paced request per CIK, ~10
minutes). Tone for the 264 names without it is optional (~9,000 releases
on the local model server). Only the facts are required for U-sector to be
a trial.

## The measurement

`market_pit_scorecard` with `--graded-cap 0.25`, given a universe and a
membership file: the lines `rule / point-in-time`, `equal weight /
point-in-time`, SPY and QQQ, at 20 reset offsets, at 10 and 25 bp, median
and worst across offsets, offsets above EW-PIT and above QQQ, paired daily
difference at the median offset with Newey-West t (lag 20) and PSR, worst
drawdown from the starting NAV, the concentration block (largest weight
median/max, effective names, cash median, worst single-name day on the
`lagged-simple/2` basis), and, added for this study, the median and 10th
percentile of the A/A+ count per session and the share of sessions with
fewer than five. The control is re-scored on the same store day.

## Windows

2016-2023 (deciding) and 2024-2026 (already seen; can only veto), as the
live policy's scorecard. The candidate's names are new to the desk and its
numbers have never been read.

## Criteria, fixed now

**PASS** for U-sector if all of these hold at 25 bp:

1. CAGR above the control's `rule / point-in-time` line on **both** windows
   by at least 2.0 points, median across offsets.
2. Paired daily difference against the control at the median offset has
   Newey-West t ≥ 2.0 on 2016-2023.
3. Above the control on at least 15 of 20 offsets on 2016-2023.
4. Worst drawdown (all) not worse than the control by more than 3 points;
   worst single-name day not worse than the control's on either window.
5. Sessions with fewer than five A/A+ names below 5% on both windows
   (this is the mechanism claimed; without it a PASS is a different story).
6. Deflated Sharpe of the paired difference at 457 cumulative trials ≥ 0.95.

Anything else is **RECORD**. U-flat and U-tone are reported against the
same criteria but cannot pass on their own: U-flat because it changes what
a grade means, U-tone because its subset is not a rule a live desk can
apply until tone is complete.

**What a PASS does.** It lets a `/6` policy with the larger universe be
proposed to the operator. It is a change of mandate (the book is AI and
software by his decision), so the go-ahead is his in chat, after the
write-up and an independent check; the paper account does not move on this
note.

## Trials and prior

- Trials: three. The cumulative count goes from 454 to 457.
- Prior, about 25% for a PASS. For: the cap-binding sessions are a fifth of
  the deciding window and two fifths of the recent one, and idle cash was
  measured at a point a year per 5% of cap; more candidates spend it. The
  utilities measurement points the same way. Against: the grade's own
  selection is two points at t 1.5 on the book; averaging it over eleven
  sectors dilutes the AI-and-software drift that gave EW-PIT its 9 points
  over QQQ, and the recent window's 48.5% is a concentrated bet the larger
  book cannot make. Most likely outcome: fewer cap-bound sessions, lower
  drawdown, and a lower CAGR on 2024-2026, a RECORD that prices
  diversification rather than a PASS.

## Compute

`desk.run` on the book is 321 s; the expectations gap inside it already
builds and features the 531-name panel, so that part does not grow. The
per-name loaders (versions, levels, tone) and the analysts grow with N: an
estimate of 2-3× per run, under 20 minutes on CPU, to be timed on the first
run and recorded (not the 5× a linear scaling would give). `simulate.run`
per offset is O(T×N) and small. One evening on spark1, CPU only, after the
tone re-score batch has finished.

## Permissions (the operator's OK)

1. Outbound HTTP from spark1 to `data.sec.gov` for 437 `companyfacts`
   fetches (`market_fundamentals_asof --refresh --tickers ...`), or the
   fetch done elsewhere and copied in.
2. Optional: the tone batch for 264 names on the local model server, after
   the current re-score is done.
3. The membership rule above, and its file, committed before any score is
   read.
4. A `--universe` / `--membership` option on the scorecard and a
   sector-grouped rank in the desk, with tests and a null test: the book-94
   run through the new path must reproduce the control to the bit.

## Order of work

1. This note committed and pushed before any code.
2. Fetch the facts; build the file; null test.
3. Run the control and three arms; write the payloads to
   `docs/research/scorecards/universe_<arm>.json`.
4. Write-up, independent check, operator's report.
