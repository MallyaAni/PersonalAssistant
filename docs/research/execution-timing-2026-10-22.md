# Execution timing: the open against later clocks — 2026-10-22

## Why

On 2026-10-22 the account's trims filled into a gapped-down open (HPE at
55.74 at 09:30, 56.6 two minutes later) and the owner asked whether buying
and selling at the open, without waiting for the price to settle, is a flaw.
The policy trades market-on-open because that is the one price the backtest
can model exactly. This measures what the clock is worth.

Data: the SIP fifteen-minute store (`bars_15m_sip`), every session 2016-01-04
to 2026-10-21, the 98 book names; `~/dsv41/universe/intraday_prices.py`
extracts the 09:30 open and the price at 09:45, 10:00, 10:30, 11:00, 12:00,
13:00, 15:00 and 16:00 (219,261 session-name pairs). Studies:
`~/dsv41/universe/exec_timing.py`, `exec_close.py`; outputs
`exec_timing_desc.json`, `exec_timing_scores.json`, `exec_close_scores.json`.

## What the price does after the open (mean bp from the 09:30 open, book names)

| overnight gap | n | 09:45 | 10:00 | 10:30 | 11:00 | 12:00 | 16:00 |
|---|---|---|---|---|---|---|---|
| below −3% | 6,357 | +10 | +26 | +30 | +31 | +43 | +22 |
| −3% to −1% | 21,485 | +3 | +3 | +5 | +2 | +3 | +8 |
| −1% to +1% | 116,305 | 0 | +1 | 0 | −1 | +1 | +3 |
| +1% to +3% | 24,520 | −4 | −3 | −1 | −3 | 0 | +5 |
| above +3% | 39,599 | 0 | 0 | +1 | −2 | +1 | +4 |
| all | 208,266 | 0 | +1 | +1 | 0 | +3 | +5 |

On the sessions the installed rule (B cut) trades: its buys gain nothing by
waiting (−1 bp at 09:45, +1 bp at 10:30, 0 at the close over 7,823 buys);
its sells are worth +6 bp more at the close than at the open over 8,046
sells, and after a gap down much more (+23 bp by 11:00 and +54 bp by the
close after a >3% gap, n=147; +12 / +30 bp after a 1–3% gap, n=598).

## The whole rule rescored with its trades at a later clock

Every trade priced at the clock instead of the open (buys and sells alike;
the simulator's open replaced by the panel's open times the intraday ratio,
so raw pre-split intraday prices never meet the adjusted panel). B cut,
book, 25 bp, 20 offsets:

| trades priced at | CAGR | worst DD | Sharpe |
|---|---|---|---|
| the open (installed) | 26.0% | −34.3% | 1.11 |
| 10:00 | 26.0% | −34.8% | 1.10 |
| 10:30 | 26.2% | −34.9% | 1.11 |
| 11:00 | 26.3% | −35.0% | 1.11 |
| the close | 26.1% | −35.7% | 1.11 |
| 10:30 only after a gap down >1% | 26.1% | −34.5% | 1.11 |
| 10:30 only after a gap up >1% | 26.1% | −34.6% | 1.11 |
| 11:00 only after a gap down >3% | 26.0% | −34.4% | 1.11 |

Buys at the open with sells at the close through the simulator's own
`exit_at_close` scored 22.9% / −35.9% / 1.09 — worse, but not because of
prices: with sells at the close the open's buys are paid from cash on hand
and the unpaid part is deferred, the same sequencing the live account has
(see below). It is a mechanics result, not a timing one.

## Reading

The clock is a wash. Over ten years and 16,000 trades, pricing at any
later time moves the result by under ±0.3% a year; the +30 bp recoveries
after a gap down are real but rare, and the 0.5–2% a stock moves in a day
swamps them. A perfect timing model has a ceiling of roughly 0.3% a year on
this rule. Thresholds like "wait until 10:30 after a 3% gap" are numbers
read off a table and do not earn their place; a learned timing model would
have to beat "no rule" out of sample, for a prize that small.

Where the owner's observation does point at a real cost is sequencing, not
the clock: the nightly sizes the open's buys against the cash on hand while
the same open's sells release the proceeds, so new names are bought a day
late (today: TSM and COHR bought 1 share each against 5.1% and 2.4% targets
while ~$54k of trims filled). That is an execution change to a bound
source, worth doing on its own.
