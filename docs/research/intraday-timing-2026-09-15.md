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
