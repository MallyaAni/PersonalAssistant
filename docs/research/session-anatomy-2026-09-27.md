# Session anatomy, 2026-09-27: how the fifteen-minute bars build the day

First run of `python -m backend.cli.market_session_anatomy --root
data/market --workers 8` on spark1 from `f6228b7f`, on the consolidated SIP
store after the schema-2 rewrite (the closing-auction row) and the
2016-2018 calendar repair. Output `data/market/desk/session_anatomy.json`,
copied to `docs/research/scorecards/session_anatomy.json`. The hypotheses
H1-H4 are in the module docstring of `backend/market/session_anatomy.py`,
written before any of these numbers existed; the thresholds and check
slots were fixed there too. Every t is on the daily cross-sectional
average series, Newey-West at lag 5 (a book of correlated names on one
date is closer to one observation than to N). Choosing window 2016-2023;
2024-2026 reported, never tuned on.

Coverage: 98 cubes (94 book names, SPY/QQQ/SMH/IGV as benchmarks), the
point-in-time book restricted by the dated membership. 2016-2023: 38
names, 58,122 name-sessions on 1,997 dates. 2024-2026: 94 names, 28,615
name-sessions on 680 dates. Complete 26-slot sessions only; a liquid name
loses 21 early closes and 3-6 feed holes (2016-02-22, 2018-05-02/03).

## A. Where the day's variance and extremes are (H1: confirmed)

Share of the session's squared fifteen-minute returns by slot, book,
2016-2023 (2024-2026 in parentheses):

| slot | 09:30 | 09:45 | 10:00 | 10:15 | 10:30 | ... midday ... | 15:30 | 15:45 |
|---|---|---|---|---|---|---|---|---|
| share | 22.1% (26.4%) | 9.7% (10.7%) | 6.9% (8.0%) | 5.0% (5.9%) | 4.5% (4.2%) | 1.7-2.5% | 2.1% (1.7%) | 4.8% (3.8%) |

The session high is set in the first slot 32.8% of the time (34.8%) and
in the last slot 12.6% (12.0%); the low in the first slot 34.9% (36.5%)
and in the last 10.4% (10.0%). A uniform day would give 3.8% a slot. The
shape is a front-loaded U, not a symmetric one: the opening bar carries
five times the closing bar's variance for the book. SPY is flatter and
nearer symmetric (8.2% first, 9.6% last; high set in the first slot
18.8%, in the last 19.7%): the book's names open with their news, the
index closes with its flows.

## B. The first half-hour and the rest of the day (H2: confirmed null)

Slope of `r_rest` (10:00 close to 16:00 close) on `r1` (open to 10:00
close): +0.024, t +0.22 on 1,997 dates (2024-2026: +0.069, t +0.68). By
quintile of `r1` the mean `r_rest` runs +0.9, +1.4, +2.2, +2.3, +3.3 bp
from the worst opening to the best, none with |t| above 1.9. A 135 bp
opening drop or rise says nothing usable about the next five and a half
hours. SPY: -0.18 (t -0.9) and +0.26 (t +0.9), the two windows
disagreeing in sign.

## C. Dips and extensions (H3: confirmed, with one cell to watch)

Forward return from the check bar's close to the session close, for
sessions whose drawdown from the open had reached the threshold by that
bar, minus the unconditional mean. Book, bp, with t and the count of
name-sessions:

| dip by | 10:30 (slot 3) | 11:30 (slot 7) | 12:45 (slot 12) |
|---|---|---|---|
| -1% | -4.2 (t -0.2, n 12,501) | -2.0 (t -0.1, n 16,535) | -1.7 (t +0.4, n 18,965) |
| -2% | -5.8 (t -0.8, n 3,405) | **-3.4 (t -2.5, n 5,579)** | -3.1 (t -1.5, n 7,225) |
| -3% | +4.9 (t -1.3, n 1,104) | +7.3 (t -1.9, n 1,989) | +1.7 (t -1.9, n 2,882) |

2024-2026, the same cells: -1% -5.5 / -4.4 / +0.3; -2% -3.2 / **-9.9 (t
-2.2)** / -1.6; -3% +2.7 / -11.4 / -0.5. Extensions (run-up from the open
of +1/+2/+3%): every cell within |t| 1.0 in both windows, differences of
-4 to +6 bp on 2016-2023 and up to +15 bp on 2024-2026 with t 0.4.

Reading: for the names the book holds, a two-percent dip by late morning
is followed, to the close, by slightly *less* than the unconditional
return, not more - the same sign in both windows, marginal in both, and
3-10 bp against a session standard deviation of 186-235 bp. The
instinct to buy an intraday dip is not paid at the session scale on this
data; neither is fading an extension. The one cell to re-test is the -2%
by 11:30 dip, recorded as a lead, never a rule: if the fifteen-minute
engine ever conditions on intraday drawdown, the prior is continuation,
not reversal. Where the pooled t sign and the cell mean disagree (the
-3% cells: positive mean, negative t) the daily average of the
difference is negative on most dates and a few large days carry the
mean, which is the usual shape of a small-n cell.

## D. What a fill costs against the open (H4: half confirmed)

Log cost of the fill against the session's open, bp, book:

| window | 2016-2023 mean / median / sd | 2024-2026 mean / median / sd |
|---|---|---|
| first-hour VWAP (proxy) | +1.2 / +1.2 / 98 | -0.7 / +0.3 / 137 |
| session VWAP (proxy) | +2.2 / +4.1 / 140 | -0.8 / +1.7 / 187 |
| last regular print | +4.1 / +7.4 / 186 | -0.4 / +4.0 / 235 |
| closing auction | +3.9 / +7.1 / 186 | -0.4 / +3.8 / 235 |

The first-hour VWAP is within a basis point of the open in expectation;
the median session drifts up 1 bp by the first hour and 7 bp by the
close on 2016-2023, and does nothing on 2024-2026. The half of H4 that
said the open fill costs more than a first-hour VWAP fill is not
supported: there is no expected saving in waiting, only 98-137 bp of
dispersion. The half that said the open-to-close standard deviation is
the scale every timing idea has to beat is the finding: 186-235 bp a
session for the book, 80-85 bp for SPY, against 1-4 bp of expected
difference between any two fill windows. The closing auction's first
print sits 0.2 bp from the last regular print in expectation.

Also on the record, not a hypothesis: the book's overnight gap averaged
+3.9 bp a session on 2016-2023 and +7.6 bp on 2024-2026, against
open-to-close means of +4.1 and -0.4 bp. On the recent window the book's
return came overnight. The next-open fill convention of the funded ledger
buys after the gap; this is the number to keep beside any proposal to
fill at the close instead.

## What this settles for the fifteen-minute layer

1. Execution timing within the session is worth about 1-4 bp a fill in
   expectation for these names, an order of magnitude below the 10-25 bp
   one-way cost the scorecard already charges. The next-open fill is not
   a headwind; the fidelity shadow's question (band entries, green-day
   skip) is about *which* sessions to fill, not *when* within them.
2. Intraday reversal is not a source of return at the session scale for
   the book: a dip continues slightly, an extension does nothing. A
   fifteen-minute rule that buys dips or takes profits on extensions has
   to find its edge below the session (in the first hour, where the
   variance is) or in a conditioning variable this study did not use; the
   pooled unconditional numbers give it nothing.
3. The first bar is a quarter of the day's variance and a third of its
   extremes. Anything measured "at the open" is measured at the noisiest
   print of the day; a rule keyed to the 09:30 bar is keyed to noise
   unless it is about that bar's own information.

Not measured here and next: the same tables conditioned on the desk's
own state (grade, regime, day-type) rather than pooled; the first-hour
structure at the bar level; and whether the overnight/intraday split of
the book's return is stable across years, which bears on the fill
convention more than any of the above.
