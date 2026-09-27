# Fill timing inside the session: results (2026-09-27)

Pre-registration: [execution-timing-plan-2026-09-27.md](execution-timing-plan-2026-09-27.md).
Run on spark1 from `8ebbd4e` (`python -m backend.cli.market_fill_timing
--root data/market --workers 8 --offsets 20 --cost 10`), payload
`docs/research/scorecards/fill_timing.json`. The orders are the ones
`graded-equal-weight/4` generates on the point-in-time book on the
simulator's own 20-session clock; every convention fills them from the SIP
store's bars for the fill session, scaled to the panel's adjusted basis by
the session's own official close, and marks at the daily adjusted close.
The engine's `next_open` reproduces `simulate.run` on the real store to a
mean 0.09 bp a day (the SIP first print against the daily open; worst day
30 bp), so the control is the scorecard's line. (A first run scaled fills
by `adj_close / close`, which does not undo splits; it read 13.6% for the
control and was discarded - CHANGELOG, same date.)

## The table (median CAGR across 20 offsets; bp/d and t are the paired daily difference against `next_open` at the median offset, Newey-West lag 20)

| convention | 2016-2023 CAGR | vs open bp/d (t) | offsets above | 2024-2026 CAGR | vs open bp/d (t) |
|---|---|---|---|---|---|
| next_open (control) | 29.2% | — | — | 48.0% | — |
| first_hour_vwap | 29.6% | +0.0 (+0.3) | 11/20 | 47.5% | +0.3 (+1.3) |
| session_vwap | 29.8% | -0.0 (-0.2) | 12/20 | 47.2% | +0.5 (+1.4) |
| next_close | 29.5% | -0.1 (-0.3) | 13/20 | 46.8% | +0.5 (+1.1) |
| dip_or_close | 29.3% | -0.1 (-0.2) | 11/20 | 47.9% | +1.0 (+2.2) |
| late_day | 29.5% | -0.1 (-0.5) | 13/20 | 46.8% | +0.5 (+1.1) |
| breakout_gate | 29.3% | +0.1 (+1.2) | 10/20 | 46.8% | -0.0 (-0.1) |

About 945 fills per offset; the band gate deferred 50 of them; four fills
per offset fell back to the daily open for want of a complete cube session.

**Verdict: RECORDED, NOT ACTED ON.** No convention beats the next open by
5 bp a session, or by any amount with t >= 2.5, on the choosing window;
the whole spread of seven conventions is within ±0.2 bp a day of the
control, and 0.6 CAGR points across them. On 2024-2026 `dip_or_close`
earns +1.0 bp a day (t 2.2, deflated Sharpe 0.97 against seven trials):
reported, below the floor, not acted on.

## Reading it

1. When the nightly decision fills does not matter on this book, to the
   first decimal of a CAGR point. That is the session-anatomy finding
   (1-4 bp of expected difference between fill windows against a 186 bp
   session standard deviation) confirmed on the policy's actual orders
   with costs: the orders are few (about one a name a month), so even a
   real timing edge per fill would be worth little a year.
2. "Buy the dip" as a fill rule is a wash on the choosing window and a
   basis point a day in the recent one. It is not the wrong idea; it is a
   small one, and the fallback to the close is what keeps it from being
   negative.
3. `breakout_gate` in isolation - only buys wait for the band, sells and
   everything else at the open - is neutral (+0.08 bp a day, t 1.2). So
   the 4.4 CAGR points the *full* live execution policy costs the `/4`
   book (NEXT_SESSION 2026-09-27 addendum) do not come from the band gate
   on buys. They come from the rest of the live conventions: the
   mid-cycle band entries sized by the breakout rule, the deferred-buy
   leg with buys paid from cash on hand, the green-day skip and the
   sells at the close - each built for the concentrated `/3` book. That
   is the next measurement: the live policy's options switched off one
   at a time on the `/4` book, each a registered trial.
4. The operator's question - why the clock and not the price - now has a
   measured answer for the fill leg: because on this book the price at
   which a nightly decision fills is noise around the open, and no price
   rule tried recovers more than a basis point of it. The place price and
   structure could matter is the *decision*, not the fill, and the
   decision layer has no intraday signal yet (deep-intraday stage 1).
