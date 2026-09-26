# 0024 - One 15-minute signal engine for the paper account and the personal board

Date: 2026-09-26

## Status

Accepted as the design; nothing is built or live yet. Tracked in
[TRADING_VOLATILE_BOOK_ARCHITECTURE.md](../TRADING_VOLATILE_BOOK_ARCHITECTURE.md).

## Context

The desk's live policy `cash-bounded-breakout-rotation/3` decides once per
session after the close: buys fill at the next open, sells at the next close,
and a 15-minute job only cancels sells (the green-day skip). The personal board
computes its own intraday Buy from the live band, with no memory of what it has
already said, and a rule from 2026-09-22 kept the paper account's clock out of
the operator's personal instructions.

On 2026-09-25 the operator set the objective and its constraints:

- buy volatile names on opportunities that meet developed conditions, read from
  chart structure and from how 15-minute candles build the daily candle; take
  profits and exit on the same read, at any point in the day;
- SPY and QQQ are benchmarks only, and a defensive destination when volatile
  names are expected to crash (broad break → cash/SWVXX-as-cash; volatile-only
  break → SPY; never QQQ);
- the personal board and the paper account must show the same signals, because
  the operator places real trades by hand from the personal board.

The review behind the plan found that intraday timing, confirmation entries,
stops and price exits all measured at or below zero on this book; that most of
the book's measured edge over the benchmarks is universe choice and deployment;
and that a season of forward shadow cannot statistically detect a realistic
edge over QQQ.

## Decision

1. One engine, `desk-signals/1`, evaluates every completed 15-minute bar and
   the nightly plan, and emits events (BUY, ADD, TRIM, EXIT, WATCH) with an
   episode id, a target-weight change, a structural reason, a reference and
   midpoint-target price, and `valid_until`.
2. The paper executor and the personal board both consume that stream. Sizes
   are percentages of each account's own equity. This supersedes the
   2026-09-22 separation rule.
3. Only validated rules trade. A rule is validated by a gate committed before
   its run: all 20 reset offsets, 10 and 25 bp, the equal-weight-book hurdle,
   DSR/SPA/PBO for return claims (non-inferiority for execution changes), then
   a 4-6 week fidelity shadow. Unvalidated rules are shown as "not validated"
   and never trade.
4. Anti-overtrading is structural, not advisory: one action per name per
   episode, a cooldown in bars, no same-day reversal except a break or the hold
   limit, and a daily action cap.
5. In-session orders go through one narrow, guarded order class with an
   activation hash and a kill switch; every other order keeps the market-open
   refusal.

## Consequences

- The paper account becomes a live test of exactly what the operator trades.
- Live decisions run on real-time IEX bars (free); each day's decisions are
  replayed on delayed SIP bars and a rule whose agreement drops below 95% is
  disabled.
- The crash switch is advisory until it passes long-history tests and costs at
  most 1.5 CAGR a year.
- No index residual sleeve, no leverage, no standalone intraday sleeve.
