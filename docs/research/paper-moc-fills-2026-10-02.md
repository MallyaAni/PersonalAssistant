# Paper market-on-close orders expire: cause and fix (2026-10-02)

Branch `fix/paper-moc-fills`. It is the open leak recorded in
`docs/NEXT_SESSION.md` (2026-10-02, paper target tracking). It changes the
intraday leg's close-window order from market-on-close at 3:30 PM ET to a
day market order at 3:45 PM ET.

## Evidence: the broker's own order records

These come from the paper account's `GET /v2/orders?status=all&after=2026-09-28`
(read only, 62 orders). Times are ET. All the `cls` orders listed are
`type=market`, `time_in_force=cls` and `extended_hours=false`, and none has a
`failed_at`.

| Sent (ET) | Order | Status | Filled | Ended (ET) |
|---|---|---|---|---|
| 09-30 15:30:48 | BUY 1 MDB | expired | 0 | 16:01:30 |
| 09-30 15:30:48 | SELL 32 ANET | expired | 14 at 15:59:58 | 16:00:46 |
| 10-01 15:30:40 | BUY 10 INTC | expired | 0 | 16:01:34 |
| 10-01 15:30:40 | BUY 5 MDB | expired | 0 | 16:00:13 |
| 10-01 15:30:41 | BUY 3 MDB | expired | 0 | 16:00:36 |
| 10-01 15:30:41 | BUY 1 LITE | expired | 0 | 16:01:49 |
| 10-01 15:30:40 | SELL 18 ANET | expired | 0 | 16:00:19 |
| 10-02 15:30:37 | BUY 31 HPE | expired | 0 | 16:01:28 |
| 10-02 15:30:37 | BUY 21 SWKS | expired | 0 | 16:00:56 |
| 10-02 15:30:38 | BUY 2 ALAB | expired | 0 | 16:00:04 |
| 10-02 15:30:37 | BUY 4 SIMO | filled | 4 at 15:59:58 | |
| 10-02 15:30:37 | SELL 18 ANET | filled | 18 at 15:59:57 | |

The nightly queued one `cls` order itself before the switch: SELL 39 ANET
for 09-28. It filled 7 at 15:59:56 and the rest expired at 16:01:53.

Every intraday day market order the balancer sent filled within 3 seconds.
There were 23 from 09-30 to 10-02 (8, 10 and 5; on 10-02: MDB 09:45:39, AAOI
10:00:37, LITE 10:15:31, STX 11:00:33, INTC 11:30:35).

Of the 9 market-on-close buys the balancer sent, 8 expired and 1 filled. Of
its 3 such sells, 1 filled, 1 partly filled and 1 expired.

## Cause

Our parameters were valid, and the timing was too:

- Alpaca's documentation says `cls` orders are rejected between 3:50 PM and
  7:00 PM ET, and otherwise execute only in the closing auction, with any
  unfilled quantity cancelled after the close. Ours were sent at 15:30 ET,
  20 minutes before that cutoff. None was rejected, and none had
  `extended_hours` set.
- The paper venue does not run a closing auction. Alpaca staff said on the
  forum on 2026-06-24 that paper "treats MOC orders as standard market
  orders at close price", and that a "higher percentage of partial fills is
  intentionally introduced in paper trading". The records are consistent
  with that. The fills that happened came in the last 2-4 seconds before
  16:00 (15:59:56 to 15:59:58). Whatever had not filled by then expired at
  16:00:04 to 16:01:53. Order size is not the factor: ALAB 2 expired and
  HPE 31 expired, while SIMO 4 filled.
- This is the same failure the paper venue has with `opg`. The opening
  orders expired for the same reason, and `alpaca_trading.
  submit_market_on_open` already sends a day market order for that.

The cause is a limitation of the paper broker: it does not fill MOC orders
reliably. It is not wrong parameters or late submission. Alpaca staff also
said in the same thread that "MOC orders are not generally supported in
live trading unless one has chosen the elite smart router". That bears on
a live mirror and is not verified here.

## Fix

- `entry_timing.session_clock` gains `"final"` = close − 15 minutes
  (`FINAL_LEAD`), which is 3:45 PM ET on a 4:00 close and 12:45 PM on an
  early close. That is the last balancer run inside the session (the cron
  is `*/15 9-16`, and the 15:30 sends left at :37 s).
- `intraday_orders.decide`: an untriggered row in the close window sends
  nothing until `final`, then sends a day market order until the close.
  The old after-15:50 market fallback is inside that range. A dip- or
  pop-triggered row is unchanged: it goes to the market on its trigger at
  any time in the session, the close window included.
- `_submit` no longer sends market-on-close. `submit_market_on_close` stays
  for the nightly's off-switch path (`INTRADAY_EXECUTION = False`).
- An order an older build had already sent market-on-close is adopted as
  `moc`, so the board keeps calling it market-on-close.

## What the board says

| Where | Before | After |
|---|---|---|
| `entry_timing._close_text` (the board's BUY/SELL "at the close" reason) | "...; market-on-close before 3:50 PM ET" | "...; market order at 3:45 PM ET" |
| `intraday_orders._clock_status`, close window before 3:45 | due · "Close window · market-on-close due" | waiting · "Close window · market order at 3:45 PM ET" |
| the same, from 3:45 | due · "Close window · market-on-close due" (before 3:50) | due · "Close window · market order due" |
| an expired `cls` order | cancelled · "Not filled: the order was expired" | cancelled · "Not filled: the broker expired the market-on-close order at the close" |
| TradeBoard rule line, DeskPanel "When" and paper-account timing lines | "market-on-close from 3:30 PM ET" | "a market order at 3:45 PM ET" |

`rule_text` ("..., else at the close") is unchanged. The operator's rule is
still "at the close", and the line now says what is actually sent.

## An expired order is not treated as done

An expired order was already handled, before and after this change:

- `paper.settle` maps `expired` to `dead`, which is terminal. `dead` is not in
  `paper.DONE`, so a reset leg that died puts the rebalance clock back and
  is planned again.
- It is journalled as `dead`, and the nightly prints it under "last
  session's orders".
- The in-session board shows it as `cancelled`, which counts under "need
  attention". After the nightly, the record's Execution receipts show it as
  "closed without a fill".
- `due()` never re-sends a sent row.

`test_an_expired_market_on_close_order_is_not_done` pins all of this.

## Tests

`backend/tests/test_intraday_orders.py`:

- a minute-by-minute synthetic clock on a full day and an early close, for
  both sides;
- identity against the replaced rule for triggered rows;
- a whole session of balancer candles that never sends `cls`;
- `_submit`;
- the expired-MOC path, through the board, the balancer, `settle` and
  `apply_settlements`.

The existing tests moved to the new clock in `test_entry_timing`,
`test_board_level_gate`, `test_live_policy` and `test_market_daily`.

## Risks and what is not verified

- **One chance instead of two.** The market-on-close order was sent at 15:30
  and checked again at 15:45. The market order has only the 15:45 run. If
  that run fails, the row is settled `missing` that night and the next
  redeploy buys the cash, which is the same outcome as an expiry.
- **The price is not the close.** A market order at 15:45:30 fills about 14
  minutes before the close. The execution study measured the close, so the
  live fills now differ from the study by up to 15 minutes of drift.
  Whether that matters is not measured here.
- No fill has yet been observed under the new rule. Monday 10-05 is the
  first session.
