# Intraday timing — two studies registered 2026-09-15, before the run

The operator's observation: flushes and gaps happen inside the session,
and a name often stabilises in a range, retests its short EMAs and then
resolves. Two questions follow, and each gets a study with its measure
fixed here. Data: the 15-minute IEX bars already on the research store
(`data/market/bars_15m`, 2020-07 to 2026-09-04) cleaned by
`backend/market/intraday.py` to complete regular sessions, plus the daily
store for the official open and adjusted closes. IEX is one venue; its
closes are used for the intraday references, the daily store's open for
the opening print, and every intraday price is rescaled onto the daily
adjusted close of its session so entry and exit sit on one scale.

## Study 1 — where in the session the desk should trade

For every book name and complete session since 2021-01-04 with a known
prior close: the log distance from the opening print to the close of
the first 15-minute bar, the 30th minute, the 60th minute, the first
30 minutes' volume-weighted price, and the session close. Positive
means the price rose after the open, so a buyer who waited paid more;
negative means the open was the worst print and waiting helped. The
sell side is the mirror.

Conditions fixed now: the overnight gap (open against the prior close)
at or below −2%, within ±2%, at or above +2%; and a flush, the first
15-minute bar closing 2% or more below the open. Statistics are on the
series of per-session cross-sectional means, so correlated names do not
count as independent evidence.

What would change execution: a mean of at least 20 basis points in one
direction, with t above 3 on the session series, in an unconditional or
a conditional cell with at least 200 sessions. Below that the open stays
the entry, since it is the simplest fill to get and to audit.

## Study 2 — which timeframe confirms a reversal entry

On the 95 any-day episodes and 45 meeting episodes already registered
(`post-decision-reversal-2026-09-15.md`), the same basket and the same
exit (the close ten sessions after the entry session), with the entry
on the session after the signal chosen five ways:

1. the open print (the registered baseline);
2. the first 15-minute close above the 15-minute 9-bar EMA;
3. the first 30-minute close above the 30-minute 9-bar EMA;
4. the first 60-minute close above the 60-minute 9-bar EMA;
5. the first 15-minute close above the prior session's low.

EMAs are seeded from the previous three sessions' bars. A name that is
never confirmed by 15:45 is not entered that day (its capital sits in
cash at zero return), so a confirmation is also a filter. Returns are
beta-adjusted, after 30 basis points per side, averaged per episode;
each variant is compared with the open-print baseline as a paired
difference across episodes.

What would count: a paired mean improvement over the open entry of at
least 50 basis points per episode with t above 2 on both episode sets,
or on the any-day set alone with t above 2.5. That would make the
confirmed entry the registered reversal specification's shadow entry
from the next cycle; it would not make the reversal itself tradable,
which still needs its own bar.

## What neither study can say

IEX prints are thin; the 9:30 bar on IEX is not the consolidated open,
which is why the daily store's open is used for the print. Neither study
models limit orders, queue position or partial fills. Study 2 shares the
survivorship of the reversal universe.

## Results — run once on 2026-09-15 after the registration above

Code: `backend/cli/market_intraday_timing.py`; JSON beside this file.
1,413 sessions from 2021-01-04 to 2026-09-04, all 93 book names with
15-minute bars.

### Study 1 — where in the session to trade

Log distance from the official open to each later reference, mean of
the per-session cross-sectional means, in basis points (positive: a
buyer who waited paid more):

| cell | sessions | 15-min close | 30-min close | 60-min close | 30-min VWAP | session close |
|---|---|---|---|---|---|---|
| all sessions | 1,413 | −0.4 (t −0.3) | −0.0 (t −0.0) | −0.6 (t −0.3) | −0.1 (t −0.1) | +2.0 (t +0.5) |
| gap down ≤ −2% | 1,010 | −2.2 (t −0.4) | −0.5 (t −0.1) | −11.0 (t −1.3) | −2.9 (t −0.5) | −9.2 (t −0.7) |
| gap within ±2% | 1,412 | −0.6 (t −0.5) | −0.2 (t −0.1) | −0.6 (t −0.3) | −0.4 (t −0.2) | +1.9 (t +0.5) |
| gap up ≥ +2% | 1,100 | −8.9 (t −1.5) | −9.5 (t −1.3) | −11.7 (t −1.4) | −6.7 (t −1.1) | +1.4 (t +0.1) |

Nothing reaches the registered 20 bp with t above 3. The open is, on
average, as good a print as any in the first hour, on flat days, on
gap-downs and on gap-ups; the largest cell, gap-ups fading about 10 bp
over the first hour, is a tenth of the bar and not significant. **The
registered "flush" cell is degenerate and is discarded:** it conditions
on the first 15-minute bar closing 2% below the open and then measures
that same bar, so its −318 bp is the condition, not a finding. A usable
flush condition would have to be known before the reference it is
measured against.

**Decision: the open stays the entry.** There is no execution timing
edge to implement.

### Study 2 — which timeframe confirms a reversal entry

Beta-adjusted basket return after 30 bp per side, mean per episode, and
each confirmed entry paired against the open entry on the same episodes.
A name never confirmed by 15:30 sits in cash for that episode.

| entry | any day (95): mean | paired vs open | t | confirmed | meetings (45): mean | paired vs open | t | confirmed |
|---|---|---|---|---|---|---|---|---|
| open print | +1.24% | | | 100% | +1.10% | | | 100% |
| first 15-min close above 15-min 9-EMA | +0.74% | −0.51% | −0.8 | 77% | +0.34% | −0.76% | −1.1 | 76% |
| first 30-min close above 30-min 9-EMA | +0.64% | −0.60% | −0.9 | 62% | −0.27% | −1.38% | −1.7 | 62% |
| first 60-min close above 60-min 9-EMA | −0.17% | −1.41% | −1.7 | 41% | −0.91% | −2.01% | −2.1 | 48% |
| first 15-min close above the prior low | +0.63% | −0.62% | −0.9 | 63% | −0.29% | −1.40% | −1.8 | 66% |

Every confirmation is worse than the open, and the coarser the bar the
worse: the reversals that pay happen in the gap and the first bars, so
waiting for a close above an average buys after the move and skips the
names that ran without pulling back. On the meetings the hourly
confirmation is significantly worse. The registered improvement bar
(+50 bp paired, t above 2) is not approached by any variant.

**Decision: no confirmation, no intraday timeframe.** The registered
reversal specification keeps its open-print entry. Nothing here is a
reason to trade the reversal, which failed its own bar; it says only
that if it is ever traded, it is traded at the open.

### What this says about intraday trading here

The operator's observation is right about what prices do inside a
session and wrong about what it offers this desk: the flushes and gaps
are real, but by the time a bar has confirmed a turn, the move that
mattered has happened. Daily decisions with open-print entries remain
the best execution measured. An intraday rule that acts before
confirmation is a rule that acts on noise, and every such rule measured
here so far has cost more in turnover than it earned.

