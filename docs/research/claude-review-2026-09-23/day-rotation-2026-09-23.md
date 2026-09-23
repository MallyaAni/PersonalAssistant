# "In the volatile names on green days, in the index on red days" — measured 2026-09-23

The operator's idea: hold the volatile book on its green days and rotate into
an index on its potential red days; entering the volatile names at the right
time and price is the key. This measures what can be measured of that with
prices alone, on the 94-name book, 2016-01-04 to 2026-09-21, next-open fills,
10 bp a side, T-bill yield on cash. Harness: `run4.py`, `run5.py` (results in
the CSVs beside them). Same survivorship caveat as every backtest here: the
book is today's winners, so levels flatter; only the differences between rows
are read.

## The daily version: no causal signal, and the switching cost is fatal

Every rule below is decided at the close from data through that close and
executed at the next open. The book is the top decile by a price-only
momentum proxy, refreshed every 20 sessions.

| Rule for tomorrow | CAGR 2016–26 | max DD | Sharpe | turnover/yr |
|---|---:|---:|---:|---:|
| QQQ buy and hold | 20.4% | 35.1% | 0.95 | 0.1 |
| Always in the book (baseline) | 31.1% | 43.0% | 1.13 | 13 |
| Green today → stay; red today → QQQ | −1.8% | 53.3% | 0.05 | 215 |
| Red today → in (buy the dip); green → QQQ | 1.7% | 57.6% | 0.19 | 210 |
| QQQ above its 10-day mean → book, else QQQ | 18.6% | 39.0% | 0.83 | 75 |
| Book 5-day pullback → in, else QQQ | 12.3% | 45.0% | 0.63 | 80 |
| Realised-vol spike → QQQ | 24.8% | 45.3% | 0.97 | 31 |
| Book > 2σ stretched → QQQ | 30.6% | 43.0% | 1.11 | 14 |
| **Oracle: knows tomorrow (not causal)** | 112.9% | 22.6% | 3.45 | 210 |

The oracle row is what the idea would be worth if red days could be seen
coming: it is enormous, which is exactly why the market does not leave it
lying around. The causal rows all lose to staying in the book, in both halves
of the sample (2016–20 and 2021–26; see `run4.csv`). The reason is in the
conditional hit rates, measured on 2,693 sessions:

| Condition at the close | sessions | P(book beats QQQ next day) | mean excess |
|---|---:|---:|---:|
| unconditional | 2,693 | 53.9% | +8.7 bp |
| after a green book day | 1,527 | 54.3% | +10.2 bp |
| after a red book day | 1,165 | 53.4% | +6.6 bp |
| after a 5-day pullback | 1,023 | 54.0% | +9.7 bp |

Yesterday's colour carries no information about tomorrow's beyond the book's
own drift. A rule that switches on it trades ~200 times a year at ~20 bp a
round trip, which is about 40 points of return a year, and that is the whole
result. This matches the repo's earlier finding (`NEXT_SESSION.md`, 2026-09-06)
that every per-name timing rule trails holding the name.

## What survives of the idea

- **Be in the volatile names.** The book beats QQQ on this history in every
  configuration that stays invested; the return comes from being in, not from
  choosing days.
- **Rotate at the regime scale, with hysteresis, not daily.** A QQQ 200-session
  trend brake (risk-off below 0.97× the mean, back above 1.02×, halve the book)
  keeps the return and takes ten points off the drawdown when the released
  half goes to **cash**. Parking it in QQQ instead keeps the return but gives
  back the drawdown protection (QQQ falls in the same regimes):

| | CAGR 2016–26 | max DD | Sharpe |
|---|---:|---:|---:|
| Hold-20 book + next-day deployment of idle cash | 31.6% | 42.6% | 1.15 |
| + trend brake, released half to cash | 29.9% | 31.6% | 1.18 |
| + trend brake, released half to QQQ | 32.0% | 42.7% | 1.15 |

  The brake is now an opt-in simulator overlay (`simulate.run(trend_brake=True)`)
  so it can be run as a named shadow with the desk's real grades, per the gate in
  `TRADING_ROADMAP.md`. The bands were chosen, not fitted, but they were still
  read on this history; a shadow season decides.
- **Entry timing.** Waiting for a pullback to enter (5-day pullback rule above,
  and the repo's own 2026-09-15 intraday study) costs more in missed sessions
  than it saves in price. The measured edge of a dip entry is one week and
  small; the book's hold is twenty sessions. Enter at the next open when the
  grade says so.

## What is not authorised by this note

No live rule that switches the book on the previous day's colour, no daily
index rotation, and no retune of the brake bands on 2016–2026.
