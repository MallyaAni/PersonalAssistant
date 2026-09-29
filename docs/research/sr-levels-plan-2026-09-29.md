# Support and resistance across timeframes: pre-registration (2026-09-29)

The operator's hypothesis. The neural "structure" models failed partly
because they never saw support and resistance: their inputs were
scale-free returns (no price levels), a 60-session window (no yearly
levels), and none of the desk's level features (`backend/market/levels.py`)
or any intraday level. His claim: **a dip into a real multi-timeframe
support zone bounces; a dip into nothing continues.**

This note fixes, before any study code exists, how that claim is tested:
the levels and the moment each is known, the zone, the events, the matched
controls, the outcomes, the statistics, the trial count, and the one test
that could change the board with its kill criteria. The commit that adds
this note comes before the commit that adds `backend/market/sr_levels.py`.
Nothing below is tuned after the run.

## What is already measured

- **Dips continue on average.** Session anatomy
  ([session-anatomy-2026-09-27.md](session-anatomy-2026-09-27.md)): a 2%
  dip from the open by 11:30 is followed by -3.4 bp less return to the close
  than the unconditional mean (t -2.5) on 2016-2023 and -9.9 bp (t -2.2) on
  2024-2026.
- **Buying a fixed dip is neutral.** Fill timing
  ([execution-timing-2026-09-27.md](execution-timing-2026-09-27.md)): on the
  `/4` policy's own orders `dip_or_close` (buy at the first fifteen-minute
  bar close at least 1% under the session open, else at the close) is -0.1
  bp a session (t -0.2) against the next open on 2016-2023 and +1.0 (t 2.2)
  on 2024-2026.
- **The dip fill's sign flips with the regime.** ML entry level
  ([ml-entry-level-2026-09-28.md](ml-entry-level-2026-09-28.md)): a
  `dip_or_close` fill was 8.7 bp *worse* than that session's close on
  2016-2023 and 36 bp *better* on 2024-2026; no level set by volatility
  (forecast or trailing) beat the fixed 1%.

So a level can only matter if it **separates** dips that hold from dips
that do not. Every test below is built around that separation.

## Levels, and the earliest moment each is known

**Basis.** Every price is on the panel's adjusted basis: the desk's
`adj_close`, with daily highs and lows scaled by `adj_close / close` as
`levels.py` does. Cube bars (the SIP fifteen-minute cube, `CUBE_VERSION`
2, raw tape dollars) move onto that basis by `fill_timing`'s split-safe
scale, reused rather than restated: the ratio of the panel's adjusted close
to the cube's own official close (the closing auction's first print, else
the last regular bar's close) on the same session. That ratio is the
factor for splits and dividends after the session. The only price
information it carries is the residual between the cube's official close
and the daily store's close. That residual is zero where the two sources
agree; the SIP acceptance reconcile found them within 0.5% on 99.7% of
sessions. It moves every bar of a session by one common factor. So every
comparison inside a session (a bar against the opening range, the VWAP, a
zone edge, the open) is exact, and only comparisons of bars with daily
levels carry the residual. This is stated here, not corrected.

**Daily structure: known at the prior session's close, in force all
session.** All from the panel's rows up to and including the prior
session, which may be an early close the cube does not hold.

| level | definition |
|---|---|
| `swing_low_20`, `_60`, `_250` | The nearest confirmed swing low below the prior close among those confirmed in the last 20, 60, 250 sessions (`levels.swing_points` with `levels.SWING` = 5, so a swing is known 5 sessions after it prints; `levels._nearest`). |
| `swing_high_20`, `_60`, `_250` | The nearest confirmed swing high above the prior close, likewise. A swing found by several horizons is kept once, under its shortest horizon. |
| `sma_50`, `sma_200` | Simple mean of the 50 (200) adjusted closes through the prior close (`technical.sma`). |
| `wsma_21` | Simple mean of the last 21 *completed* weekly closes. A week runs Monday to Friday, and its close is its last adjusted close. A week is completed for a session when the session falls in a later week, so a Wednesday never sees its own week. |
| `high_52w`, `low_52w` | Highest adjusted high and lowest adjusted low of the 252 sessions through the prior close (`levels._rolling`). Where the name has less history inside the window, this is its high or low since listing. |
| `prior_day_high`, `_low`, `_close` | The prior session's adjusted high, low and close. |
| `prior_week_high`, `_low` | The highest high and lowest low of the most recent completed week. |
| `node_1`, `node_2`, `node_3` | High-volume nodes of the prior 20 complete cube sessions. Price bins are 0.25% wide in log price, anchored at 1. Each bar's volume is spread evenly over the bins its low-high range covers. A node is a local peak of that profile: above the bin below it, and at least the bin above it. The top three peaks by volume are nodes, each priced at its bin's geometric midpoint. Also known at the prior close. |

**Intraday: known only once formed.**

| level | definition | known from |
|---|---|---|
| `or_high`, `or_low` | High and low of the first two bars (09:30-10:00). | the 10:00 bar close |
| `vwap` | Running session VWAP. The proxy: sum(bar close × bar volume) / sum(bar volume) over the session's bars so far. The cube has no per-bar VWAP, and a bar's close is its last print, not its average. The level in force *during* bar s is the VWAP at the close of bar s-1. | each bar close |

That is 22 levels in 12 families: `swing_20`, `swing_60`, `swing_250`,
`sma_50`, `sma_200`, `wsma_21`, `range_52w`, `prior_day`, `prior_week`,
`volume_node`, `opening_range`, `vwap`. The levels in force during bar s
are known at the close of bar s-1. A level that is not defined yet (too
little history, no volume) is simply absent. It is never filled in.

**Zone.** Around every level L the zone is [L - w, L + w], where
w = max(0.25 × ATR14, 0.3% of the prior close). ATR14 is the simple mean of
the adjusted true range over the 14 sessions through the prior close
(`backtest._atr`). w is fixed for the session. "Two zone-widths" below
means 2w.

**Confluence.** The confluence of a zone is the number of distinct level
prices inside [L - w, L + w], L itself included. Identical prices count
once: a prior-day low that is also the prior week's low is one level, and
it is recorded under both families.

## Events

Events are the bars from slot 2 on: 10:00-10:15, the first bar after the
opening range is known, through 15:45-16:00. They are taken on every
session where the name is a point-in-time member of the book (the dated
membership file, `point_in_time`; the benchmark is excluded). Early
closes and incomplete partitions are not in the cube.

A **support touch** at bar s:

- P is the close of bar s-1.
- A support level is one in force with L + w < P: the level is below the
  prior bar's close, and that bar closed above its zone.
- The touch happens when bar s's low enters the zone: low_s ≤ L + w.
- The touched zone is that of the *highest* such level (the first zone
  price meets on the way down).
- The event records the families of every level inside that zone, and
  its confluence.

A bar before 10:00 is never a touch. A bar entering a zone from below is
never a support touch.

A **resistance touch** mirrors it. The levels are those with L - w > P,
the bar's high reaches L - w, and the touched zone is the *lowest* such
level's.

## Matched controls

For each support touch, the controls are **non-level dips**: bars of the
**same name** in the **same calendar year** and the **same hourly bucket**
(10:00-11:00, 11:00-12:00, ..., 15:00-16:00, by bar start) that meet all
of these:

- on another member session;
- the bar traded below the prior bar's close (low < P);
- no level in force lies in [low - 2w, P): nothing within 2w beneath the
  bar's low, and nothing it passed through;
- its close is within ±0.25 percentage points of the touch bar's close,
  both measured as the return from the session open.

The control outcome is the mean over all matched control bars. If the
same name and year has none, the controls come from the pooled same-year
set: every member name's candidate bars in that year and bucket, on other
dates, under the same depth window. A touch with no control either way is
dropped.

The **match rate** is reported per side and window: own name, pooled, and
unmatched. The median number of controls per touch is reported too.

Resistance touches mirror all of this: run-ups with no level in (P, high
+ 2w], matched on the same return from the open.

## Outcomes, from the touch bar's close

1. `r_close`: log return to the session close, in bp. "The close" is the
   closing auction's first print where the cube has it, else the last
   regular bar's close (15:45-16:00). The count of each is reported.
2. `bounce` and `break`, in percentage points.
   - Support: bounce means the session close is above the zone's upper
     edge (L* + w); break means it is below the lower edge (L* - w).
   - Resistance: bounce means the close is below the lower edge (turned
     back); break means it is above the upper edge.
   - A control has no zone of its own. It is scored against the touch's
     zone edges, as ratios to its own bar close. So bounce and break are
     the same thresholds on the same return.
3. `r_next` and `r_5`: the log returns from the session's adjusted close
   to the next session's close and to the close five sessions on, in bp.
   These come from the panel. Outcome 1 plus outcome 3 is the whole path
   from the touch.

## Statistics

- For each touch and outcome, the difference D is the touch's outcome
  minus its controls' mean.
- Each cell reports the mean of the **daily** average of D (each date's
  touches across names averaged first) with a Newey-West t at lag 10. Lag
  10 covers the four-session overlap of `r_5`. The t is reported only
  with at least 30 dates.
- Each cell also reports the touch and control means, the number of
  touches and of dates, and the event-weighted mean of D.
- Windows: 2016-2023 is the choosing window; 2024-2026 is reported and
  never tuned on.
- Populations:
  - every member session;
  - the names the desk graded A or A+ at the prior close. That is the
    grade the `/4` order filling that session was decided on, from the
    restricted report. Their touches keep the same matched controls.
- Groups: all touches; by family (a touch counts in every family inside
  its zone); by confluence (1, 2, ≥3).

**Trials.** 2 sides × 2 populations × 2 windows × 16 groups (all, 12
families, 3 confluence buckets) × 5 outcomes = **640 cells**. The
Bonferroni threshold for a family-wise 5%, two-sided, is **|t| ≥ 3.95**,
printed beside every raw t.

**The primary test** is one cell, registered here: support touches, every
member, 2016-2023, all touches, `r_close`. The operator's claim predicts
touch minus control **> 0**. SUPPORTED needs t ≥ 2.0 there and the same
sign on 2024-2026. The event study explains; it cannot change the board.

## The decision test: what could change the board

Two conventions are registered in `backend/market/fill_timing.py`. The
engine is extended, not forked, and every existing convention's prices
stay byte-identical.

- **`level_dip`**: a buy fills at the first bar close from the 10:15 close
  on that lies inside the zone of a level below the prior bar's close,
  while below the session open; else it fills at the official close. A
  sell fills at the first close inside the zone of a level above the prior
  bar's close, while above the open; else at the close. The levels are
  all 22, in force as defined above.
- **`level_dip_confluence`**: the same, counting only zones of
  confluence ≥ 2.

They are priced on the `/4` policy's own orders exactly as every other
convention:

- the plain simulator's orders and the `simulate._Book` ledger;
- 10 bp one way;
- fills scaled by the session's official close;
- marks at the panel's adjusted close;
- a fill session with no cube session fills at the panel's open, counted;
- 20 offsets, paired at the median offset, Newey-West lag 20.

Each is measured against `dip_or_close` (the board's rule) and
`next_open`. Also reported, from the median offset's orders:

- the **fill rate at a level**: the share of orders filled at a level
  before the close;
- the **per-fill improvement over the session close**: the level fill's
  price against that session's official close, in bp, positive when
  better for the trader;
- the same improvement over every order.

**Kill criteria, fixed now.** A level convention **REPLACES** the board's
rule only if both hold:

1. On 2016-2023 it beats `dip_or_close` by at least **2 bp a session**,
   with paired Newey-West **t ≥ 2.0**.
2. It is **not worse** on 2024-2026: the mean paired difference against
   `dip_or_close` is ≥ 0.

Anything else is **RECORD**. Two trials are counted, and the best is
reported with its deflated Sharpe against two. A REPLACES verdict changes
the board only as a separate, registered change with the operator's
go-ahead: the live path is frozen at the checkpoint.

## Prior

The anatomy and fill-timing results say dips continue on average, and on
2016-2023 a fill at a 1% dip was worse than the close. The literature has
some support for levels, but not this one:

- Osler (2000, FRBNY Economic Policy Review) found that support and
  resistance levels published by firms predicted intraday trend
  interruptions in FX better than arbitrary levels.
- Osler (2003, Journal of Finance) traced that to clustered take-profit
  and stop-loss orders around round numbers.
- George and Hwang (2004, Journal of Finance) found the 52-week high
  anchors returns, at monthly horizons.
- Kavajecz and Odders-White (2004, Review of Financial Studies) found
  support and resistance levels coincide with limit-order-book depth:
  liquidity, not a forecast of returns.

There is little for single-stock intraday support and resistance after
costs.

**Expected.**

- The event study: a separation of at most a few bp on `r_close`,
  possibly concentrated in confluence ≥ 3 zones and the longer-horizon
  families (`swing_250`, `range_52w`, `sma_200`). Nothing beyond the
  Bonferroni line. The primary cell is more likely than not NOT SUPPORTED.
- The decision test: both conventions RECORD. A 2 bp session edge needs
  upwards of 60 bp per order on average, which is 2 bp ÷ (about 0.35
  orders a session × a 9% slice), the arithmetic of the entry-level
  plan. No fill rule on these orders has shown more than a few bp.

## What would make the prior wrong

- The primary cell positive with t ≥ 2.0 on 2016-2023 and positive on
  2024-2026. It would be stronger still if the difference rose with
  confluence (1 < 2 < ≥3), the break rate fell for touches, and some
  cell cleared |t| ≥ 3.95. That would say a level separates dips that
  hold from dips that do not, and the level features would become
  candidate inputs for the structure models: a new, registered question.
- A level convention clearing both kill criteria. It would show first as
  a positive per-fill improvement over the close where `dip_or_close`'s
  is -8.7 bp on 2016-2023.

## Known limits, stated before the run

- **The intraday levels sit near the price by construction.** The VWAP
  tracks it, and the opening range and the prior close bracket the open.
  So a large share of touches will be VWAP or opening-range touches, and
  `level_dip` will fill often and early. `level_dip_confluence` is the
  selective rule. A separation concentrated in the `vwap` family is
  "distance from VWAP" at least as much as "support".
- **Controls are what remains when nothing is beneath.** With 22 levels,
  a bar with no level within 2w below its low is often a trend-day bar.
  The matching on depth from the open, time of day, name and year is what
  keeps the comparison fair. The match rate says how often a control
  existed.
- The basis residual above.
- Grades are the restricted report's: point in time for membership, not
  for the grading code.
- Every touch in a session shares that session's close. Averaging each
  day first handles the cross-section; many touches on one day count as
  one date.

## Not in this trial

- The structure models' inputs do not change. If the primary is
  SUPPORTED, adding level features to them is a later, registered
  question.
- w, the clearance of 2w, the ±0.25-point depth window, the hourly
  buckets, the 22 levels, the families and the floors are fixed here and
  not tuned after the run.
- What is held and when it is decided are unchanged. The live board keeps
  `dip_or_close` unless the verdict says REPLACES, and even then only as
  a separate change.

## Run

On the Spark, from a worktree of this branch, with `.env` exported,
`PYTHONPATH` at the worktree and `MARKET_DATA_ROOT` at the market store:

    python -m backend.cli.market_sr_study --root "$MARKET_DATA_ROOT" --workers 8
    python -m backend.cli.market_fill_timing --root "$MARKET_DATA_ROOT" \
        --workers 8 --offsets 20 --cost 10 --only level_dip,level_dip_confluence

The first writes `<root>/desk/sr_study.json`. The second prices
`next_open`, `dip_or_close` and the two level conventions (80 ledger
walks) and writes `<root>/desk/sr_level_fill.json`, leaving
`fill_timing.json` alone.

## Addendum (2026-09-29, before any run on market data): the match slot and the t

The event study was built after this note was committed. Before its first
run it was checked on synthetic **null worlds**:

- 12 names and 1,600 sessions each;
- every fifteen-minute bar a pure random walk, and daily bars built from
  those bars;
- so no level means anything, and every outcome is unpredictable.

Two registered details failed that check. Both are changed here, before
any market data is read. Nothing else in this note changes: not the
levels, the zone, the events, the outcomes, the estimate, the cells, the
Bonferroni line, the primary test, or the decision test and its criteria.

1. **Controls are matched on the same fifteen-minute slot, not the same
   hour.** At 10:00-10:15 the opening range comes into force right beside
   the price. So almost no bar in that slot has 2w of clearance, and the
   hourly bucket's controls came from its later slots: 0% of controls sat
   at 10:00-10:15, against 24% of touches. Those controls had less time to
   the close than their touches. That biases bounce and break, and it
   would pick up any real time-of-day drift. The same slot gives every
   control the same time left, and a name has one bar per slot per
   session, so a same-name control is always from another session. The
   pooled fallback is by year and slot.
2. **The t is clustered by calendar month on every observation, not
   Newey-West on the daily averages of the differences.** Every touch of
   a name in a year and slot averages the same few control bars, often a
   handful of trend days. The registered statistic filed that shared noise
   under each touch's own date, where a lag-10 kernel cannot see it. The
   estimate stays exactly as registered: the mean over dates of the daily
   average of touch minus control. That estimate is a weighted sum over
   every touch and every control bar, and each enters in its own session's
   month. The month clusters also absorb the same-date cross-section, the
   same-session pairs and most of `r_5`'s overlap. A t needs at least 30
   dates and 12 months. The registered t is still written into every cell
   as `t_daily_hac`, for the record. The primary test and the Bonferroni
   count read the new t.

On 16 null worlds (5,120 cells of the choosing window):

| statistic | cells beyond \|t\| 2 | headline "all" cells beyond \|t\| 2 | cells beyond 3.95 |
|---|---|---|---|
| registered: Newey-West on daily averages, hourly bucket | 26.6% | — | 193 |
| new: month-clustered, same slot | 8.1% | 2.5% | 4 |

The nominal rate is 5%. The residual excess sits in small subgroup cells,
where a cluster-robust variance on few months runs low. So a subgroup cell
near the Bonferroni line is read with that in mind; the primary test is a
headline cell.

Also found while building: the Brownian-bridge cubes of the fill-timing
tests pin each session's close to an independent daily close. That makes
path shape predictive by construction: the primary cell read -7.9 bp
there, t -3.3 month-clustered and -7.4 registered. So they are not a null
for this study; its null tests use the random-walk worlds. The real market's intraday path is not a pure random
walk either. Touches and controls are matched on depth, time and name,
not on how the price got there. So any intraday momentum or reversal that
depends on the path, not the level, loads onto the touch-minus-control
difference. The family and confluence splits are where a level effect
would show as distinct from it.
