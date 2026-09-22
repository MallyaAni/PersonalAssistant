# Intraday 15-minute entry engine — locked contract — September 22, 2026

Research-only. This document fixes the single candidate rule, its states, and
its limits **before** any historical outcome is inspected, per the user's
requirement that entry/invalidation levels be supplied and the rule be locked,
with no threshold or window mining. The implementation is
`backend/market/intraday_entry.py`; its behavior is pinned by
`backend/tests/test_intraday_entry_structure.py`.

## Objective and scope

A portfolio-entry guide that gives a precise 15-minute entry from the session's
evolving candle structure, so repeated refreshes do not become repeated
recommendations and weak or repeated signals do not cause churn. The engine:

- retains the ordered **completed** 15-minute OHLCV bars, not merely the final
  daily OHLC;
- decides only from the completed prefix, so a partial candle never triggers
  and future bars cannot change an earlier decision;
- reports an explicit state, a trigger time/price, and an invalidation;
- is **isolated research-only**: no portfolio reads, no orders, no automatic
  rebalance, and no production caller is wired to it.

## The one locked candidate rule

**`reclaim_above_level/1`** — a pullback to a supplied level, then a reclaim
above it; anything else is a rejection or a failed break.

Supplied as external inputs from the existing daily strategy (never refitted,
never tuned here):

| level | meaning |
| --- | --- |
| `level` | the reference level being retested (e.g. a daily pivot / prior level from the existing strategy) |
| `entry_level` | a completed bar must **close at or above** this to trigger an entry |
| `invalidation_level` | a completed bar **closing at or below** this invalidates the setup |

The band is fixed as `invalidation_level < level < entry_level`; a caller
supplying any other band is refused with a clear error. These three values are
the only rule parameters, and they are supplied by the caller, never chosen by
scanning history.

### The causal sequence

Read bar by bar, in New York time, only completed bars:

1. **setup** (pullback / retest): a completed bar closes at or below `level`
   while the immediately preceding completed close was **strictly above** it —
   the level was being held from above and was broken. This is what makes a
   pullback a *retest* rather than an open below the level (a session that
   opens below `level` and never had an intraday close above it forms no setup).
   If that same bar's range touches both `entry_level` and `invalidation_level`
   it is **ambiguous** at once, and if it closes at or below
   `invalidation_level` it is **invalidated** immediately — a pullback that
   already closed through its invalidation cannot be resurrected by a later
   reclaim.
2. **reclaim** → **entry-ready**: a later completed bar closes at or above
   `entry_level`. Trigger price is that bar's close; trigger time is the **end
   of that bar's window**, when the confirming close becomes knowable (the
   candle's start is reported separately as `trigger_bar_start`).
3. **rejection / failed break** → **invalidated**: a later completed bar closes
   at or below `invalidation_level`. The retest failed. A completed
   invalidation *after* an entry also removes current readiness, while the
   entry event (identity, trigger) is retained for replay.
4. **ambiguous**: a bar in the setup whose range touches **both** `entry_level`
   (high at or above) and `invalidation_level` (low at or below) leaves the
   intra-bar order of the reclaim and the rejection unknown. The engine reports
   ambiguity; it never invents a winning fill.

### States

`unavailable` (no usable completed input), `wait` (no setup formed), `setup`
(retest underway), `entry_ready` (actionable signal), `invalidated`,
`ambiguous`, `historical` (an entry resolved by an already-closed session,
recorded for replay but not actionable), and `expired` (a setup still
unresolved at 16:00 New York). `entry_ready`, `invalidated`, `ambiguous` and
`expired` never resurrect: an entry followed by a completed invalidation
becomes `invalidated`, not a new entry, and a rejected, ambiguous or expired
setup stays that way. An entry whose session is already closed is reported as
`historical` with `recommendation = false`.

During an open session, `wait`, `setup` and `entry_ready` become `unavailable`
when the supplied prefix lacks the newest completed candle. An old trigger is
retained as an event with the same identity, but is not a current recommendation.
Already observed invalidation or ambiguity remains terminal even if later data is
missing. An unfinished next candle does not make the preceding completed one stale.

## Identity and no-repeat

Every signal carries an `identity` — a hash of symbol, session date, rule name
and version, the three levels, and the setup's first bar (or `no_setup`). The
same completed prefix read twice returns the identical signal; once a setup
exists its identity is frozen even as later bars arrive. `identity` is a
**dedupe key, not an acceptance record**: it does not by itself prevent
duplicate alerts. A caller that acts on an `entry_ready` signal must record the
identity *and* its own consumption state (e.g. "entered" vs "not entered") so a
refresh is not a repeated recommendation. The engine itself is pure: it keeps
no memory, holds no position, and recommends only when state is `entry_ready`.

## Data and causality rules

- A bar is **completed** when its 15-minute window has elapsed
  (`start + 15 min <= as_of`); everything else is ignored, so a partial candle
  can never trigger. Uncompleted bars — including ones that are corrupt,
  duplicated or on another session date — are excluded **before** any
  validation, so a future bar cannot disturb an earlier decision it was not yet
  available to influence.
- The decision at any time is a pure function of the completed prefix.
  Evaluating a prefix within a longer stream equals evaluating that prefix
  alone; an uncompleted later bar cannot change an earlier decision, and a
  *completed* later bar that closes through invalidation removes current
  readiness while the earlier entry event is retained (tested).
- The completed prefix must be **contiguous, unique and on the 15-minute
  grid**, starting at the 09:30 opening bar. A gap, a missing opening bar or an
  off-grid bar is rejected, because a missing bar can conceal an invalidation
  and must not be bridged into a readiness claim. Out-of-order bars are still
  sorted first (safe once the completed prefix is contiguous and unique).
- Duplicate bar starts and corrupt bars — non-finite prices or volume, prices
  outside the reported high/low envelope, high below low, negative volume —
  **raise** rather than guess.
- The regular session is 09:30–16:00 New York on the supplied session date.
  Extended-hours bars (outside that clock window) are ignored; a completed bar
  on another date raises rather than mix days.
- Timestamps are New York wall-clock and unambiguous: a naive `start`/`as_of`
  is treated as New York local (`America/New_York`), never UTC or the host
  timezone.
- No future pivots, no completed daily labels, and no partial candles are ever
  consulted. The session's evolving context is reported from **all** completed
  observations, including after the first signal — session open, high, low,
  latest completed close and volume keep developing rather than freezing at the
  trigger. The bar-weighted mean of (high+low+close)/3 is reported under the
  honest name `bar_weighted_typical`: it is an OHLCV proxy, **not** a traded
  volume-weighted average price, which a 15-minute OHLC bar cannot reconstruct.

## Verification

`python -m pytest backend/tests/test_intraday_entry_structure.py` — all
passing:

- identical daily OHLC with different intraday paths reach different states;
- future bars cannot change an earlier decision (prefix invariance, tested by
  evaluating a prefix within a longer stream and asserting equality, and by
  appending uncompleted invalidating bars and asserting the entry stands);
- an incomplete bar cannot trigger;
- a close-confirmed trigger is known only at the end of its candle;
- a setup bar already closing through invalidation invalidates immediately;
- repeated reads keep one identity and one trigger;
- invalidated, expired, ambiguous and historical setups do not resurrect;
- a completed invalidation after an entry removes readiness while retaining the
  entry event;
- a bar touching both trigger and invalidation is ambiguous, never a fill;
- gaps, missing opening bars, off-grid, duplicate, corrupt, extended-hours and
  other-date bars and the session/time boundaries are handled explicitly;
- the session context (open/high/low/latest close/volume/typical price)
  continues to evolve after the trigger;
- a historical (already-closed-session) entry is never actionable.

Static checks: `ruff check` and `ruff format --check` clean; `mypy --strict`
clean. No production caller, model service, portfolio or order path is touched.

Root review also reproduced and corrected stale readiness when the newest
completed candle is missing. The engine retains the observed trigger and identity
but reports unavailable until current evidence arrives; unfinished candles do not
cause premature expiry. The three entry test modules now cover 39 cases, and the
combined entry/quote/intraday/pilot/context run passes **80 tests**. Log on Spark1:
`/tmp/codex-entry-integrated-20260922.log`. This verifies research-library behavior,
not deployed guidance, performance superiority or actual fills.

## Limits — read before trusting an entry

- **No profitability claim.** The engine is a structural state machine, not a
  measured edge. Earlier studies tested particular timing variants under their
  stated data and cost assumptions (`docs/research/intraday-timing-2026-09-15.md`
  and `docs/research/conditional-entry-pilot-2026-09-20.md`). Their results neither
  establish this candidate's performance nor reject all 15-minute timing methods.
  Nothing here has been shown to beat unchanged current momentum.
- **The rule is unproven by construction.** The single candidate rule and its
  levels are locked here and were not measured against any historical outcome;
  no threshold or window was mined. A future comparison must be a separate,
  reviewed step against unchanged current momentum, with identical causal inputs,
  decision times and a predeclared execution proxy after confirmation. The user's
  primary scenario is zero added costs. Any next-bar-open proxy must disclose its
  availability/latency assumptions and must not be relabelled a midpoint fill.
  That comparison is **not** performed by this task.
- **Quote-fill limits are honest.** A reclaim is confirmed by a completed-bar
  *close*. `trigger_price` records that observation and does not imply a fill.
  IEX 15-minute bars are one venue, not consolidated quotes, and carry no spread,
  queue position, partial-fill or impact history. Historical OHLC cannot prove a
  midpoint fill, and a bar touching both the trigger and the invalidation is
  reported ambiguous rather than assumed filled.
- **Half days** (13:00 close) and **extended hours** are out of scope; the
  regular-session window is fixed at 09:30–16:00 New York. A scheduled early
  close is a documented limitation, not a handled mode.
- **One setup per session.** A rejected or ambiguous setup is terminal, so a
  later re-pullback in the same session does not re-arm. This is a deliberate
  conservatism against repeated signals, not a claim that re-entries cannot pay.
