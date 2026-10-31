# Intraday reaction to a shock on the book's 15-minute bars: a descriptive measurement — 2026-10-31

**Status: descriptive measurement. No overlay is proposed and nothing live
changed.** This is the intraday-bar study the approved path required before
considering an intraday reaction. It was measured before this note was written,
so it is **not a pre-registered gate** and is reported as description, like the
event-shock study's A3. The live rule, grades, orders and prompts are unchanged;
the earnings calendar and event-watch stay descriptive.

## The question

The owner asked whether a bad earnings release can be met immediately, instead
of waiting for the nightly decision and the next open. The live rule decides at
the close and fills at the next session's open, which is the first regular-session
price after an after-hours release. An intraday reaction would sell a held name
at the next 15-minute bar after an intraday shock. Does that fill beat the live
next-open fill?

## The measurement

For every book name and complete session in the cached 15-minute cubes:

- **Shock.** The first bar whose close is at least **5% below the prior close**,
  with the session's volume through that bar at least **2× the trailing
  20-session mean volume**, scaled to the same fraction of the session. The
  volume pace is a point-in-time proxy for "this move is on real volume."
- **Reaction fill.** The open of the next bar; for the last bar, the closing
  auction's first print (or the next session's open when the auction is absent).
- **Live baseline.** The next session's open, which is when the nightly rule
  fills a sale decided at the close.
- **Measurement.** `ln(reaction fill / next open)`, positive when reacting early
  sells higher. Costs are the same for both fills and are not modeled; a higher
  intraday cost would only make the reaction worse.

Data: `data/market/research/sip_cubes/<TICKER>.npz`, the cached
`SessionCube` for the **98 names the book carries today**, 2,699 complete
sessions per name from 2016-01-04 through 2026-10-30. The cubes exclude early
closes and incomplete partitions and carry the prior close on the session's raw
basis, so the shock return and the fills are on one basis.

## The result

**6,414 shock events on 1,667 sessions.** The reaction fill is **worse** than
the next open on average:

| window | n | mean | median | positive |
|---|---:|---:|---:|---:|
| all | 6,414 | **−28.75 bp** | −24.43 bp | 47.19% |
| choosing 2016-2023 | 3,061 | **−29.10 bp** | −28.01 bp | 46.52% |
| reported 2024-2026 | 3,353 | **−28.43 bp** | −20.08 bp | 47.81% |

The session-clustered bootstrap (5,000 draws, seed 20261031, resampling the
1,667 reaction sessions rather than the events) gives a 95% interval of
**[−68.40 bp, +10.48 bp]**. The point estimate is negative and the interval
spans zero: there is no measured edge, and the sign is against reacting early.

By year, the mean is positive in only three of eleven years:

| year | n | mean | median | positive |
|---|---:|---:|---:|---:|
| 2016 | 212 | +72.72 bp | +39.90 bp | 56.60% |
| 2017 | 159 | −3.13 bp | −31.56 bp | 45.28% |
| 2018 | 314 | −27.30 bp | +8.74 bp | 51.59% |
| 2019 | 280 | −15.20 bp | −40.35 bp | 43.57% |
| 2020 | 531 | −46.17 bp | −70.54 bp | 42.75% |
| 2021 | 346 | −97.74 bp | −72.93 bp | 38.73% |
| 2022 | 736 | +11.79 bp | +18.34 bp | 52.17% |
| 2023 | 483 | −85.93 bp | −44.83 bp | 42.03% |
| 2024 | 762 | −14.01 bp | −7.48 bp | 48.43% |
| 2025 | 1,161 | −36.36 bp | −12.60 bp | 49.01% |
| 2026 | 1,430 | −29.67 bp | −30.02 bp | 46.50% |

The choosing-window halves disagree: 2016-2019 is **+2.17 bp** (n=965) and
2020-2023 is **−43.49 bp** (n=2,096). That is not a stable edge in either
direction; it is year-to-year noise around a negative point estimate.

## The splits

Pre-specified only as description; none is a gate.

| subset | n | mean | median | positive |
|---|---:|---:|---:|---:|
| shock 09:30-11:00 | 5,438 | −30.94 bp | −24.43 bp | 47.68% |
| shock 11:00-12:45 | 613 | −22.66 bp | −27.66 bp | 43.88% |
| shock 12:45-14:30 | 160 | −26.49 bp | −47.14 bp | 41.25% |
| shock 14:30-16:00 | 203 | +9.83 bp | −1.62 bp | 48.77% |
| depth 5-7.5% | 5,059 | −26.01 bp | −22.97 bp | 47.12% |
| depth 7.5-10% | 834 | −53.07 bp | −53.38 bp | 45.56% |
| depth over 10% | 521 | −16.43 bp | +4.09 bp | 50.48% |

The late-day and deepest subsets have positive means but negative medians and
positive fractions near one half; they are not a signal. The largest subset,
the first 90 minutes, is the most negative and is 85% of the events.

## What this means

- **Immediate intraday selling does not beat the live next-open fill.** The
  point estimate is −28.75 bp per event, the clustered interval spans zero, and
  the yearly means are negative in eight of eleven years.
- **The sign is consistent with the event-shock study's bounce.** After a large
  negative reaction, the average name outperformed SPY over the next 20 and 60
  sessions; the price path into the next open is part of that bounce. Selling at
  the next bar sells into it.
- **The live rule already reacts at the first regular-session opportunity.** For
  an after-hours release, the next open is that opportunity; for an intraday
  release, the nightly decision and next open are later, but the measured price
  difference does not justify moving earlier.
- **No overlay is proposed.** The intraday reaction step is closed with a
  descriptive measurement, not a gate result. It is not retried with a different
  drop, volume multiple, time-of-day filter or horizon without a new
  pre-registration saying what changed and why.

## Disclosures

- **Descriptive, not pre-registered.** The measurement was run before this note.
  It is reported as a description and cannot be presented as a gate pass or
  fail. The event-shock study's A3 set the precedent for a descriptive arm that
  never gates.
- **The universe is the current book.** The cubes are the 98 names the desk
  carries today, not the point-in-time S&P 500; the history is survivor-biased.
  The measurement is about the live book's names, which is the relevant
  execution universe, but the absolute levels are flattered in the same way as
  every other book-level study.
- **The event is a price shock, not an earnings-specific shock.** It is the
  reaction leg the owner described, not a filing-time event. The store's 8-K
  accepted timestamps are a lagging filing clock, not the press-release clock,
  so an earnings-only intraday study would need a different event source.
- **The volume pace is a proxy.** It compares the session's cumulative volume
  through the bar with the trailing 20-session mean scaled by the fraction of
  the session elapsed. It is point-in-time and mechanical, not a liquidity
  model.
- **Costs are equal and not modeled.** Both fills are sells at a bar open; the
  comparison is the price difference. A wider intraday spread would make the
  reaction worse, not better.
- **It is an execution difference, not a portfolio result.** The live rule may
  not sell the name at the next open at all. The measurement answers "if a sale
  happens, which fill is better"; it does not model whether the rule would sell.
  The event-shock bounce argues the rule should hold, which makes the overlay
  worse, not better.
- **The cubes exclude some sessions.** Early closes and incomplete partitions
  are excluded and counted on each cube; the measurement uses complete 26-slot
  sessions only.

## Artifacts

- Measurement script: `~/dsv41/pit2/intraday_shock.py` (outside git, research
  only).
- Payload: `~/dsv41/pit2/intraday_shock.json`.
- Cubes: `data/market/research/sip_cubes/<TICKER>.npz`, built from
  `data/market/bars_15m_sip` as of 2026-10-30.

**Closed.** No intraday reaction overlay is added to the rule, the balancer, the
board or any prompt. The next candidate is not this arm; a different intraday
question needs its own pre-registration.
