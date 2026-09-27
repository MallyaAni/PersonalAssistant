# SIP fifteen-minute store: first backfill and acceptance, 2026-09-27

The consolidated raw-basis fifteen-minute store (`backend/market/intraday_sip.py`,
P0.3 of the volatile-book plan) was filled from Alpaca on spark1 overnight
2026-09-26/27 and reconciled against the daily store. This note records
what the backfill cost, what the acceptance gate found, the two defects
the gate exposed and their fixes, and the numbers the store now stands
on. Commands and logs are on spark1 under `/tmp/sip-*.log`.

## The backfill

98 names (the book's 94 plus SPY, QQQ, SMH, IGV), sessions 2016-01-04 to
2026-09-25, `--refresh --since 2016-01-01`. The dry run estimated 1,633
requests; the run made 9,115, because Alpaca pages the SIP feed at about
1,000 bars whatever `limit` asks for (999 observed with `limit=10000`):
about 95 requests for a thin name, 190 for a liquid one. The first
attempt would have stopped at the default cap of 2,000 after twenty
names; restarted at 20,000 (partitions already written are kept). The
estimator now divides by the observed page size (`13875ac`), and the
default cap is documented as sized for the nightly append.

Liquid names: 2,698 sessions each. Names with a listing inside the
window (ALAB, CRWV, NET, OKLO, SNOW, WULF, ZS) report their pre-listing
sessions as "empty" and ask for them again on every pass (2,066 for
ALAB), which costs one request a run and is harmless for the nightly.
Sessions the SIP feed carries for a symbol before the daily store's
history begins are a reused ticker, not this company: NBIS 2016-2022, Q
2016-2017, SNOW 2016-2017, TLN 2016, SMR 2020-2022, CORZ 2021-2022 (the
pre-bankruptcy listing) - 3,416 sessions in all, stored, excluded from
every cube by "no prior close", and flagged by the reconcile as "no
daily bar for the session".

## What the acceptance gate found

Gate: the session's first open, last close, high, low and summed volume
against the daily bar on the raw basis; |log close ratio| <= 0.5%,
volume within 20%, tolerances frozen before the run.

First reconcile (schema 1, before the fixes): 224,992 sessions, 157,740
passed, **70.1%**. Failures: 57,056 volume, 5,847 incomplete, 3,416 no
daily bar, 932 close, 1 unavailable. The volume failures were one-sided
(median -26.7%, 349 of 57,056 positive), grew by year (1,036 in 2016 to
10,269 in 2024), and clustered on the third Fridays (2026-09-18: 55 of 98
names). The close failures were small: median 0.71%, 90th percentile
1.38%, maximum 5.04%, concentrated in low-priced names (CIFR 152) where
half a percent is a tick.

### Defect 1: the closing auction was dropped

The consolidated tape stamps the closing cross at 16:00, so it lands in
the bar that *starts* at the close, which the store treated as
after-hours and dropped. Measured directly: AAPL 2026-09-18, daily volume
86.59M, SIP all-bars total 86.72M, of which the 16:00 bar 49.81M (a
rebalance Friday); AAPL 2026-09-15, 31.75M daily, 7.76M in the 16:00 bar;
AVGO 2026-09-15, 24.78M daily, 4.57M in the 16:00 bar. The daily bar's
close and volume include the cross, and so does the desk's "fill at the
close". Fix (`bd99763`): partition schema 2 keeps that bar after the
regular slots (`closing_auction`, `read_closing_auction`,
`read_session_full`); the reconcile compares the daily close to the
cross's first print and adds its volume; a partition without the row is
stale and the refresh rewrites it. The rewrite: 9,384 requests across
three parallel streams, 05:05-05:52Z.

### Defect 2: 2016-2018 half days cut at 16:00

The reviewed exchange calendar began at 2019, so the first run took every
2016-2018 close as 16:00; on the six 13:00 half days a liquid name's
after-hours prints filled slots 14-25 and the partition was marked
complete (SPY 2016-11-25: last "regular" bar 15:45, 7,239 shares). Fix:
the calendar now covers 2016-2018 from the official NYSE Group releases
(`13875ac`), a partition whose stored close disagrees with the calendar
is stale and rewritten (`ce85167`), and the repair ran (863 requests).
After it, SPY 2016-11-25 holds 14 bars. 1,720 sessions in 2016-2018 stay
incomplete, which is the feed: 2016-02-22 (slots 10:30-11:00 missing for
38 names), 2018-05-02 and 2018-05-03 (AAPL has one bar on 2018-05-02),
and the thin names' ordinary holes (AAOI 120).

## Where the store stands (schema 2)

Second reconcile, after both repairs (four parallel streams, 05:56-06:13Z): 224,992 sessions, 206,889 passed, **92.0%**; 93.4% of
the 221,576 sessions that belong to this company (the reused-ticker
sessions can never pass). Median name 95.5% (52 names at or above 95%);
QQQ 99.7%, SPY 99.7%, AMD 99.4%, AMZN 98.9%, NVDA 98.9%. What remains:

| reason | sessions | share | where |
|---|---|---|---|
| volume outside 20% | 8,636 | 3.8% | now two-sided (median +23%, 6,418 positive): SIP above the daily bar on expiration Fridays (AAPL 2016-12-16 +30%), below it on earnings days when the after-hours session carries the volume (AAPL 2016-04-26 -26%); half of it in 2021-2022 and in the thin SPAC-era names (POWL 39% pass, WULF 46%, OKLO 52%) |
| incomplete | 5,465 | 2.4% | the feed's holes: 2016-02-22, 2018-05-02/03 for about 38 names each; thin names' ordinary gaps (AAOI 120, IGV 145, WULF, OKLO) |
| no daily bar | 3,416 | 1.5% | reused tickers (NBIS, Q, SNOW, TLN, SMR, CORZ) and IGV/SMH's stale daily history |
| close outside 0.5% | 585 | 0.26% | median 0.75%, 90th percentile 1.6%, maximum 7.3%; low-priced names where the tolerance is a tick |

**Verdict: ACCEPTED for the fifteen-minute studies.** The price gate holds
on 99.7% of sessions; the volume residual is a difference between what
the daily source and the consolidated tape count on expiration and
earnings days, not a hole in the bars; the incomplete sessions are
excluded from every cube and counted. The tolerances stay as frozen. The
store is not yet a live input to any decision.

## Operating notes

- `--report` re-reconciles every session and costs as much as
  `--reconcile` (about 45 minutes for the book in one process); the two
  should share records. Reconcile and refresh both parallelise cleanly
  across disjoint `--tickers` sets; the request rate is the only shared
  limit.
- `completeness()` with `--include-incomplete` reads every partition's
  metadata (2,700 parquet reads a name); a rewrite pass is about two
  minutes a name in one stream.
- IGV and SMH daily bars end 2026-09-04: the nightly refreshes the book
  and SPY/QQQ, not the sector ETFs. Their last 14 SIP sessions reconcile
  as "no daily bar" for that reason.
- The nightly append (`~/desk_sip.sh` on spark1: `--refresh --since <10
  days ago>` then `--reconcile`) is drafted and not yet in cron; it goes
  in once this note's schema-2 numbers are in.
