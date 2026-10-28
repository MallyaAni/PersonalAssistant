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
  less CAGR, four points less drawdown). On the installed leader rule the dial
  is nearly flat on the broad universe (the book is already 95-97% invested);
  on the IT+Comm universe 0.20 buys 4.7 drawdown points for 1.2 CAGR points
  and 0.30 adds 3.3 drawdown points for 0.2 CAGR points.
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
- **Tone surprise.** The five-field release-tone change failed its
  pre-registered gate (20-session NW t 1.79 against 2.0; 60-session IC
  −0.016; 2024-2026 negative). The secondary S-added and S-blend arms were
  not run. Closed; not retried without a new pre-registration.
- **The no-chase guard.** The book's point-in-time Sharpe gain did not
  transfer to the honest S&P 500 PIT universe: choosing-window Sharpe
  +0.00004 at 25 bp against a +0.05 gate, below the random-deferral placebo's
  95th percentile; reported CAGR 26.29% to 23.45%, full period 14.27% to
  13.71%. The 0.40 sensitivity is worse. Closed; not retried without a new
  pre-registration (`chase-guard-results-2026-10-28.md`).

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

### P2 — One selection bet: tone surprise (run, failed)

The only analyst with a measured edge is valuation; the sentiment analyst's
tone level carries rank IC 0.039 at 20 sessions. The release-tone layer already
stores the change from the previous release for five fields, but the analyst
uses only the guidance change. The registered study asked whether the
five-field surprise predicts 20/60-session excess returns. It was run on
2016-2023 with the placebo and 2024-2026 reported only:
`tone-surprise-results-2026-10-28.md`. The twenty-session IC is +0.035, but
the Newey-West t is 1.79 against a 2.0 gate, the sixty-session choosing IC is
−0.016, and 2024-2026 is negative at both horizons. **S-only failed; the
secondary arms were not run.** The signal is not in the grade, the board, or
any prompt. Pre-registration: `tone-surprise-preregistration-2026-10-28.md`.

### P3 — Estimate revisions (forward only)

The nightly Yahoo snapshots and the Alpha Vantage backfill now record analyst
estimates. The AV file is one retrieval with 7/30/60/90-day consensus fields,
not a decade of point-in-time history, so it cannot support a historical
backtest; the signal is forward-only. Record it nightly, evaluate after 252
sessions. The backfill is infrastructure, not evidence.

### P4 — Risk dial and core-satellite (measured; owner decision pending)

The installed rule was run with only its volatility target changed, on the
frozen honest cache: `risk-dial-2026-10-28.md`. On the broad S&P 500 PIT
universe the dial is nearly flat (14.2%, 14.8% and 15.0% at 10 bp for 0.20,
0.25 and 0.30), because the book is already 95-97% invested. On the
IT+Comm PIT universe 0.20 gives up 1.2 CAGR points for 4.7 fewer drawdown
points and the best Sharpe (0.98); 0.30 adds 0.2 CAGR points for 3.3 deeper
drawdown points. **Recommendation: keep 0.25; 0.20 is the cautious
setting; 0.30 is not worth it.** A core-satellite 80/20 theme/SPY blend
cuts 2.2 drawdown points for 1.1 CAGR points with a flat Sharpe; deeper
blends trade return for risk roughly linearly. The owner chooses; no
change without the release ceremony.

### P5 — Reliability (parallel, no performance claim)

Fix the data defects that can make a grade wrong: multi-class share counts
(BRK-B, ERIE, STZ) and the remaining stale test fixtures (the tone loader
test assumed the expiry flag starts off; the desk default is `HARD`). The
refactored freshness path already marks a newly fetched old print stale
(`desk_freshness.quote_status`; `test_market_desk_freshness.py`), and the
parity banners are covered by `test_grade_parity.py`; both suites pass. These
do not add return; they remove ways the live loop can be wrong.

The TSM unit defect is fixed. Its NYSE close is per ADS representing five
common shares (20-F, accession 0001628280-26-025362), and its filings report
TWD. `levels_pit` now divides the filed count by the ADS ratio and withholds
revenue, earnings and equity for a non-USD reporter, because no FX series is
on file. The live value analyst already had no multiple for TSM, so no grade
moved. Tests: `backend/tests/test_listed_share_basis.py`.

The 6-K classifier refused genuine quarterly releases. ASML's results
releases for Q2 2013, Q4 2013, Q4 2015, Q1 2016, Q3 2018, Q4 2018, Q2 2019,
Q3 2019 and Q4 2019 were refused because the headline window around the
reporting verb also carried a dividend or buyback line, because the headline
said "sales" without "results" or "net sales", because a title outlook word
("raises full-year sales outlook") hid the dateline that publishes the
quarter's results, or because the period was a bare year before "results"
("reports 2013 results as guided"); the Q4 2010 and Q4 2014 releases were
refused the same way. `results_headline` now reads plain "sales" as a result
and as a period word, accepts a year before the figure ("2013 results"),
searches for the published-results phrase in the whole head so the dateline
can rescue an outlook title, and refuses a dividend or buyback word only
when no result word precedes it, so a standalone dividend or buyback
announcement is still refused. Re-decided against the real filings, the rule
admits eleven more ASML releases, restores four a year for every year from
2007 through 2026, and leaves no year above four; 2004-2006 remain short.
Tests: `backend/tests/test_market_edgar_6k.py`. Stored 6-K decisions are
cached, so the correction reaches the store only through a one-time
`python -m backend.cli.market_edgar --refresh --reclassify-6k --tickers ASML`
(and the other filers) run after this fix is deployed and before the 19:30
ET nightly; a partition is immutable, so a name today's partition already
holds is reported as failed and is not reclassified. After that the nightly
carries the corrected decisions forward.

The multi-class names remain open. The company-facts feed drops class
dimensions; BRK-B's only undimensioned count is from 2011 and below the
plausibility floor, and ERIE and STZ have none, so they have no market cap
and no value score in the research universe (none is in the live book). A
correct fix needs the cover-page XBRL instance with dimensions, which the
store does not fetch; a static multiplier would go stale and is refused.

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
2. The tone-surprise study is run and failed; its result is written beside
   the pre-registration. Do not retry it without a new pre-registration.
3. Keep the estimate snapshots recording nightly; do not read them as evidence
   before 252 sessions.
4. The risk dial is measured (`risk-dial-2026-10-28.md`); the owner's
   choice of 0.25 or 0.20 is pending.
5. The chase guard is run and failed on the honest universe
   (`chase-guard-results-2026-10-28.md`); do not retry it without a new
   pre-registration.

## What this program refuses

It refuses to keep searching for a timing edge that 467 trials have not found.
It refuses to quote the 37.6% book number as the system's return. It refuses to
adopt a signal because it looks good on the names that were chosen with
hindsight. It refuses to change the live rule during the forward record. Those
refusals are the program.
