# Trading program: the best system this desk can defend — 2026-10-28

Status: program of record. Research and planning only. The only live change
in flight is the FOMC retirement candidate, which is implemented, tested and
not yet installed.

This note exists because the owner asked for the project to be led, not for
another experiment. It fixes the objective, the honest baseline, what the
evidence says works, what is closed, and the order of work. It is deliberately
short enough to be read before every trading session.

## The honest baseline

The installed rule is `grade-led-leader-weight/1`: enter at A, hold while B,
1% minimum trade, equal A/A+ slots tilted 0.5x-1.5x by trailing 63-session
return rank, scaled to a 0.25 realised-volatility target with a 0.5 exposure
floor, 25% name cap, P/E-history tilt, value analyst at three votes, every
leg at the next open.

| line | universe | CAGR | worst DD | Sharpe | costs |
|---|---|---:|---:|---:|---|
| installed rule | today's 94-name book | 37.6% | −27.7% | 1.46 | 10 bp |
| installed rule | S&P 500, point in time | 14.8% | −34.7% | 0.90 | 10 bp |
| installed rule | S&P 500, point in time | 14.2% | −33.3% | 0.88 | 25 bp |
| installed rule | S&P IT + Communication, PIT | 19.5% | −35.7% | 0.96 | 10 bp |
| equal weight, no costs | S&P IT + Communication, PIT | 19.9% | −34.4% | 0.93 | — |
| value ×3 grading, A cut | S&P 500, PIT | 17.1% | −34.7% | 1.00 | 25 bp |
| SPY | — | 13.8% | −33.7% | 0.82 | — |
| QQQ | — | 19.0% | −35.1% | 0.91 | — |

Sources: `point-in-time-universe-2026-10-24.md`,
`value-weighted-grading-2026-10-22.md`, `account-simulator-rule-2026-10-24.md`.
The store holds bars only for today's names, so every PIT line is flattered by
survivorship; the rule-against-equal-weight comparison is the fair one.

**Read plainly.** The 37.6% headline is the choice of names, not the rule. On
the stocks that were actually available, the rule earns about SPY plus one to
three points, with a better Sharpe and a similar drawdown. Inside technology it
roughly matches equal weight and trails QQQ. The dominant return driver is the
AI-and-software mandate; that is a deliberate bet, not alpha.

## What the evidence says works

- **The valuation analyst.** The only analyst with a positive rank IC in every
  year since 2020 (+0.05 to +0.11); value at three votes lifts the PIT line from
  15.3% to 17.1% at 25 bp and passes the walk-forward test the ridge weights
  failed (`grade-quality-2026-10-22.md`, `value-weighted-grading-2026-10-22.md`).
- **The A+ grade.** +5.7% excess over QQQ at 60 sessions against A's +2.8%,
  B's +3.8% and C's +1.9%. A is the weakest upper grade; B is better than A.
- **The volatility target.** The only lever that has reliably moved drawdown:
  0.25 costs about a point of CAGR against the uncapped book and buys roughly
  fourteen points of worst drawdown; 0.20 is the cautious neighbour (two points
  less CAGR, four points less drawdown).
- **The leader tilt.** +2.3 CAGR points at the same worst drawdown; strength
  0.5 is the knee, 1.0 jumps the drawdown to −42%.
- **The 1% minimum trade.** Cuts 82,446 fills to 6,703 with no return cost.
- **Next-open execution.** No fill convention, including learned 15-minute
  timing, beat it within ±0.2 bp a session at t ≥ 2.5.

## What is closed

- **Timing.** 467 registered trials; chart-reading vision +3.0 bp with a 95%
  interval of [−12.8, +16.7]; mechanical comparators (session-VWAP limit +5.0
  bp, hourly EMA21 +5.2 bp) no better. Do not reopen without a new
  pre-registration and a forward shadow.
- **The pre-meeting FOMC cut.** Across 34 triggered meetings the book rose from
  the cut to the decision close in 20 (mean +0.48%); the ten-year lead-in is
  positive on average. Retired 2026-10-28; the open October cycle still
  restores at 15:45 ET today.
- **Learned rankers, day-type models, stops, trend gates, sector caps,
  conviction top-decile.** All measured and failed on the honest universe.
- **The B cut outside the theme.** It adds theme breadth on the book but loses
  on the broad market; the installed A entry / B hold is the compromise.

## Objective

Maximise forward, point-in-time, after-cost CAGR subject to:

- worst drawdown no deeper than about 35% (owner's dial; 0.20 vol target is
  the cautious setting);
- Sharpe at least 1.0 on the honest universe;
- long-only, no leverage, US large caps;
- turnover no more than about 2x a year (the 1% minimum trade already keeps it
  far below);
- one engine: backtest, charts and live plan are the same arithmetic;
- every change pre-registered, measured with costs at 10 and 25 bp, and
  forward-shadowed before it can go live.

"Top tier" here does not mean the highest backtest CAGR. It means a system
that beats SPY and QQQ on the honest universe with statistical confidence,
keeps its drawdown inside the owner's tolerance, survives 25 bp, and has a
forward record long enough to believe.

## The program

### P0 — Install and freeze (today)

Install the FOMC retirement after the 15:45 ET restoration fills. Then freeze
the rule. No further live rule changes for the next 252 sessions except
emergency correctness fixes. The system cannot be judged if it changes every
week; the forward record is the only out-of-sample evidence this desk will
ever have.

### P1 — Forward record (October 2026 – October 2027)

Run the paper account unchanged. Track, weekly: plan parity (OK/MISMATCH),
fill fidelity against the next open, slippage, turnover, exposure, and the
curve against SPY, QQQ and equal weight on the same names. No interim
performance decisions; the protocol's review is after 252 completed sessions.
This is the highest-priority workstream because everything else is a
hypothesis until it survives here.

### P2 — One selection bet: tone surprise (registered now)

The only analyst with a measured edge is valuation; the sentiment analyst's
tone level carries rank IC 0.039 at 20 sessions. The release-tone layer already
stores the change from the previous release for five fields, but the analyst
uses only the guidance change. The next registered study asks whether the
five-field surprise predicts 20/60-session excess returns and whether adding
it to the grade improves the honest book. Pre-registration:
`tone-surprise-preregistration-2026-10-28.md`. Historical test on 2016-2023,
placebo, 2024-2026 reported only. Passing buys a forward shadow, not a live
change.

### P3 — Estimate revisions (forward only)

The nightly Yahoo snapshots and the Alpha Vantage backfill now record analyst
estimates. The AV file is one retrieval with 7/30/60/90-day consensus fields,
not a decade of point-in-time history, so it cannot support a historical
backtest; the signal is forward-only. Record it nightly, evaluate after 252
sessions. The backfill is infrastructure, not evidence.

### P4 — Risk dial and core-satellite (owner decision)

Measure three settings of the installed rule (vol target 0.20, 0.25, 0.30) and
a core-satellite blend (the thematic book beside a broad index) on the honest
universe, and present CAGR, worst drawdown and Sharpe. The owner chooses the
risk setting; no change without the release ceremony. The research already
says the 0.25 target is the knee and that a sector cap only moves the book to
cash; this workstream is about the owner's tolerance, not about finding alpha.

### P5 — Reliability (parallel, no performance claim)

Fix the data and board defects that can make a grade wrong: the TSM ADR ratio,
multi-class share counts (BRK-B, ERIE, STZ), the 6-K classifier's refusals,
stale intraday prints shown as current, grade-parity drift banners, and
date-pinned test fixtures. These do not add return; they remove ways the live
loop can be wrong.

## Operating model for the owner

- The nightly runs at 19:30 ET. Review the desk panel after 20:00 ET; the
  orders are market-on-open for the next session.
- Most nights have no action. The 1% minimum trade means small target moves
  are not traded; do not improvise around them.
- The book holds roughly 15-25 names and is 50-100% invested; cash is the
  volatility target working, not a failure.
- If you trade manually, use the 15-minute trend and session VWAP for entry
  timing only. Do not change the target intraday; the measured edge in
  intraday timing is a few basis points and does not survive costs.
- Judge the system on the 12-month forward record and the quarterly review,
  not on nightly P&L.

## Decision rights

- I decide: research design, pre-registrations, code, tests, candidate
  preparation, and what the evidence supports.
- The owner decides: live installs, the risk dial, the mandate (thematic book
  versus broader tech/communication universe), and deployment timing.
- No live change without the release ceremony; no deploy during the 19:30 ET
  nightly; no deploy before today's 15:45 restoration.

## Immediate actions

1. After 15:45 ET today: install the FOMC retirement release, then confirm
   admission and the 19:30 nightly.
2. Commit the tone-surprise pre-registration before its first run; run the
   historical arm and write the result beside it.
3. Keep the estimate snapshots recording nightly; do not read them as evidence
   before 252 sessions.
4. Present the risk dial to the owner with the measured trade-off.

## What this program refuses

It refuses to keep searching for a timing edge that 467 trials have not found.
It refuses to quote the 37.6% book number as the system's return. It refuses to
adopt a signal because it looks good on the names that were chosen with
hindsight. It refuses to change the live rule during the forward record. Those
refusals are the program.
