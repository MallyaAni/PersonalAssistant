# Trading scenarios: what the desk faces, what it does today, what is measured, what is not (2026-09-30)

**Status: catalogue and programme. Nothing here changes the live book by
itself.** Every rule proposed below is registered as its own plan before it
is run, gated as the others were, and reaches the board only if it clears
the gate. The catalogue is the standing list the desk is tested against; it
is added to whenever a session shows a case it does not cover.

## Why this exists

On 2026-09-30 AAOI opened at 101.39, ran to 103.96 in the first fifteen
minutes, was rejected there (its 21-day EMA sat at 104.4 and it was the
third session in a row with a high at 103.8-105), closed the bar at 99.27,
and kept falling. The board's rule read that bar as "1% under the open" and
bought. COHR and SMCI did the same. The desk had no reading of the level,
no reading of the three lower highs, and the nightly had graded AAOI A+ the
evening before. The operator's objection is the right one: a rule tuned on
averages has to be checked against every kind of day it will meet, not
only against the days that made the average.

## How the desk decides, in four questions

1. **What** to hold: the nightly grade (`graded-equal-weight/5`), five
   analysts on daily and quarterly inputs, A/A+ at equal weight, a 25% cap,
   a reset every 20 sessions, downgrade exits.
2. **When** to fill: the intraday leg (`dip_or_close`): a buy on the first
   completed 15-minute bar closing 1% under the open, a sell on the first
   bar 1% over it, else market-on-close. It reads the open and the bar
   closes; nothing else.
3. **How much**: equal weight of the A/A+ names, capped; no volatility or
   regime scaling.
4. **When out**: a downgrade, the reset, the FOMC pause; no stops (measured
   and lost), no structure exit.

Every scenario below is a way one of those four answers can be wrong on a
particular kind of day.

## The catalogue

Columns: what happens; what the desk does today; what has been measured
(with the verdict); the best candidate rule; its status. "Measured" means
a pre-registered run at 20 offsets on the 2016-2026 book with the gate the
other studies used (+2 bp of equity a session at 25 bp, NW t ≥ 2 on the
model window, not negative after, positive at 15 of 20 offsets, deflated
Sharpe at the cumulative trial count).

### A. Entry: the day the buy fills

| # | Scenario | Today | Measured | Best candidate | Status |
|---|---|---|---|---|---|
| A1 | **Rejection at resistance at the open** (AAOI 09-30): first bar tags the 21-EMA / 20-day high from below, closes back under, the 1% dip triggers on a falling bar | buys the bar | nothing | *Resistance guard:* a buy whose first bar tags a level from below and closes under it is deferred to the close, or skipped for the session (two variants) | **register today (S1)** |
| A2 | **Falling-knife first bar**: the bar closes on its low, 1% under the open, and the session keeps falling | buys the bar | stage 4 (RECORD) measured *waiting days*, not bar shape | *Hold-the-dip confirmation:* fill on the next bar only if it closes above the dip bar's low | register today (S1) |
| A3 | **Gap up then dip**: the name opens +4%, dips 1% from the open; the rule buys 3% above the decision price | buys | stage 5 (RECORD) measured the reverse (buy at the decision close) | *Reference the decision price, not the open:* the dip level is min(open, prior close) − 1%; a buy above the reference by more than 1σ waits for the close | register today (S1) |
| A4 | **Gap down > 2σ at the open** | buys the dip | E3 gap guard (RECORD: fires on 1% of buys, 5 differing fills) | none; the sample is too small to decide | closed for now |
| A5 | **Market-wide down open** (SPY −1.5%): every pending buy triggers at once on the first bar | buys all | nothing | *Market-relative dip:* trigger on the name's dip beyond the index's, not the raw 1% | register (S1) |
| A6 | **Slow grind up all day**, dip never reached | market-on-close | stage 4, execution-timing (neutral) | keep | done |
| A7 | **Buy into an event**: earnings or a 6-K/8-K inside the next 3 sessions | FOMC only (`event_execution`); earnings not read | nothing on earnings | *Earnings pause:* no new entry inside N sessions of a known report date (EDGAR calendar exists) | register (S2) |
| A8 | **Adding to a loser**: the add leg buys more of a name under its 21-EMA making lower highs | adds | nothing | belongs to C1 (the grade), not the fill | see C1 |
| A9 | **Halted / no bar / early close** | close window or skipped, logged | stage 5 coverage counts | keep | done |

### B. Exit: the day the sell fills

| # | Scenario | Today | Measured | Best candidate | Status |
|---|---|---|---|---|---|
| B1 | **Sell into resistance**: a pending sell waits for "1% over the open"; the name tags the 21-EMA / 20-day high and reverses | sells at the close, lower | nothing | *Sell at the tag:* a pending sell sends when the price reaches the level from below | register today (S1) |
| B2 | **Sell triggers early on a rise that continues** | sells at +1% | execution-timing (neutral on average) | *Trailing intraday:* after +1% hold until a bar closes under the prior bar's low | register (S2) |
| B3 | **Downgrade on a bounce day** | sells at +1% or the close | stage 4 (holding for a bounce paid until 2023, then did not: RECORD) | keep | done |
| B4 | **Earnings gap against a holding** | holds until the grade moves | catastrophe stop (RECORD: every stop lost); learned stops (lost) | *Event-conditioned exit* (only after a report, only on a gap beyond 2σ): a different question from a blanket stop | register (S2) |
| B5 | **Structure break while still graded A**: close under a falling 21-EMA after lower highs | holds | nothing (stops were price-level, not structure) | *Structure trim:* −½ notch to the grade (C1) so the name leaves at the next rebalance rather than on a stop | see C1 |

### C. Selection: what the grade does not see

| # | Scenario | Today | Measured | Best candidate | Status |
|---|---|---|---|---|---|
| C1 | **A+ while under distribution** (AAOI: three lower highs under a falling 21-EMA, −4% on the 28th, graded A+ on the 29th) | technical analyst reads 6-month momentum, 60-day range, nearest support; nothing faster | stage 3 and 4 learned models (RECORD); the technical analyst's own IC | *Structure notch:* a name under its 21-EMA with a falling EMA and lower 20-day highs cannot be A+ (−½ grade); tested as a change to the technical analyst, not a new rule outside it | **register today (S1)** |
| C2 | **Grade lags a regime turn** (all AI names down together) | `regime.py`, `day_type.json` exist as features; they do not gate | day-type study (features built; no gate measured) | *Regime gross:* gross 0.7 when the day-type model's tail probability is high; measured against the drawdown, not only CAGR | register (S3) |
| C3 | **Concentrated book** (semis and AI, 94 names) | 25% cap; the universe study says the wide cohort is smoother but 13-28 CAGR points worse | universe expansion (RECORD) | keep the book; the cap is the tool | done |
| C4 | **Data-vintage change** (6-K tone lands, five names regrade) | grade-parity banner | tone-6k built | deploy tonight; watch the banner | in flight |

### D. Sizing

| # | Scenario | Today | Measured | Best candidate | Status |
|---|---|---|---|---|---|
| D1 | **Volatile name at full weight** | equal weight | vol sizing (RECORD: every variant lost to equal weight) | keep | done |
| D2 | **Book too big for the size** (0.5% trade floor, MIN_TRADE) | floor | universe study limit 1 | not a live problem at 94 names | note |
| D3 | **Cap binding on a few names** | 25% | cap sweep | keep | done |

### E. Data, clock and operations

| # | Scenario | Today | Measured | Best candidate | Status |
|---|---|---|---|---|---|
| E1 | **The board's price lags the tape** (the 15-minute feed is 10-15 minutes behind a live screen) | the row shows the quote's age; the chart the bar | session-price specs | *Show the age in the action cell too*, and never call a 15-minute close "now" | board change (S0) |
| E2 | **Order sent, run dies before it is written** | adopted on the next run by client id | tested | keep | done |
| E3 | **Broker down / market closed** | nothing sent, logged | tested | keep | done |
| E4 | **Deploy during market hours** | forbidden by protocol | — | keep | done |
| E5 | **Desktop link down** (09-30, six hours) | research waits; the live loop is on spark1 and unaffected | — | keep | done |
| E6 | **FOMC day** | event orders next-open, pause | fomc-gate, restoration | keep | done |

## What goes on the board now (S0, display only, no decision logic)

The operator trades his real account from the board, so the first thing is
to let him *see* the structure the desk does not act on yet:

- each row: the 21-day EMA and the 20-day high, the distance to each, and
  the EMA's slope over 5 sessions;
- a flag when the session's first bar tagged either level from below and
  closed back under it ("rejected at 21-EMA 104.4, 3rd day"), and the count
  of consecutive sessions with a high at the level;
- the ticker chart draws both levels;
- the action cell shows the age of the price it was computed from.

This is a display change (`TradeBoard`, `TickerChart`, the balancer's
row payload), gated and deployed after 16:15 ET.

## The programme

**S1 (register today, run tonight on the ten-year cube, 20 offsets):** A1
resistance guard (defer / skip), A2 hold-the-dip, A3 decision-price
reference, A5 market-relative dip, B1 sell at the tag, C1 structure notch.
The fill rules run through the adaptive-entry harness (`adaptive_entry.py`
takes a candidate as a function of the session's bars); C1 runs through the
technical analyst and the point-in-time scorecard. Six trials: 457 → 463.
Every rule has a prior written in its plan, and the AAOI/COHR/SMCI fills of
09-30 are reported as a case, not used as a criterion.

**S2 (after S1):** A7 earnings pause, B2 trailing intraday sell, B4
event-conditioned exit.

**S3:** C2 regime gross.

**What is not on the list, and why:** a trained intraday model (stages 1-4
measured four families and none beat the rule), price-level stops (seven
variants, all lost), volatility sizing (lost), a wider universe (lost on
return). Those are closed unless new evidence reopens them.

## Disclosed

- The 09-30 fills that prompted this were 4 AAOI, 1 COHR and 2 SMCI on a
  $100k paper book: the loss is a few dollars. The catalogue is about the
  rule, not the day.
- The levels (21-EMA, 20-day high) are the ones the operator reads; a
  study may find another level works better, but the registered candidate
  is the one named here, not a searched one.
