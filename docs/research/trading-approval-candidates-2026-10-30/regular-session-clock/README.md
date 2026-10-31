# Candidate: decide the nightly's market-open guard on the regular session

The nightly's `_submit` refused every ordinary order whenever the broker's
`/clock` reported `is_open`. That flag describes the broker's whole trading
day, not the regular session the desk's orders are measured against. From
Sunday 2026-12-06 Nasdaq moves to a 23-hour day: the day session runs
04:00-20:00 ET and the overnight session 21:00-04:00. At the 19:30 ET
nightly the broker clock would then say the market is open while the
regular session closed at 16:00, so the guard would refuse the whole book
and the account would stop rebalancing - the same silent stop the nightly
health checks were built to surface.

`_submit` now asks `calendar.exchange_status` whether the regular XNYS
session is open. During the regular session ordinary orders are still
refused; an unknown calendar year falls back to the broker's own flag; an
unreachable broker clock still fails closed. `intraday_event_reduction`
keeps its requirement of the regular session for event sells.

No rule, sizing, timing, model, cost or parameter changes. Before
2026-12-06 the broker flag and the calendar agree at 19:30 ET, so the
installed behaviour is unchanged until the new session starts.

Bound source changed (1): `backend/cli/market_daily.py`. New identity
`0f6c83272e26bf714badcaa8f467ca9beddfd67236d56fb3f8a66ed1e7687349`;
all other bound sources match the installed release.

Targeted tests: `backend/tests/test_market_daily.py` 47 passed, including
an extended-hours clock at 19:30 ET submitting, a 10:00 ET run refused
even when the broker clock says closed, and an unreachable clock still
refusing. The new check suites pass 37. The deploy gate runs the full
backend suite before the checkout moves.
