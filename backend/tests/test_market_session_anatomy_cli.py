"""The session-anatomy command end to end on a temporary store.

What has to hold: cubes are loaded from the SIP store with their
exclusion counts printed, the point-in-time mask comes from the dated
membership file given, the payload lands at <root>/desk/session_anatomy.json
with counts everywhere and every table, the benchmark is reported apart
from the book, and the rendered text mentions each of the four tables.
"""

import io
import json
from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.cli import market_session_anatomy as cli
from backend.market import intraday_sip as sip
from backend.market import session_anatomy as sa
from backend.market.alpaca import IntradayBar
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory

PROVENANCE = sip.Provenance(
    fetched_at="2026-09-26T01:00:00+00:00", source_revision="abc"
)
SLOTS = 26


EARLY_CLOSE = date(
    2023, 7, 3
)  # 13:00 close: stored complete at 14 bars, excluded from cubes
HOLIDAYS = (date(2023, 6, 19), date(2023, 7, 4))


# `n` sessions starting from a Monday in June 2023 (EDT, so the session
# opens at 13:30 UTC), skipping weekends and the two holidays; the July
# 3rd early close is kept so a cube has something to exclude.
def _sessions(n: int, start: date = date(2023, 6, 5)) -> list[date]:
    out = []
    d = start
    while len(out) < n:
        if d.weekday() < 5 and d not in HOLIDAYS:
            out.append(d)
        d += timedelta(days=1)
    return out


# One session's 26 bars from `open0` with the given per-bar log returns.
def _bars(day: date, open0: float, returns: np.ndarray) -> list[IntradayBar]:
    start = datetime(day.year, day.month, day.day, 13, 30, tzinfo=UTC)
    out = []
    price = open0
    for i, r in enumerate(returns):
        close = price * float(np.exp(r))
        out.append(
            IntradayBar(
                start + timedelta(minutes=15 * i),
                price,
                max(price, close),
                min(price, close),
                close,
                1000.0,
            )
        )
        price = close
    return out


# Write one name's sessions to the SIP store and its daily bars to the
# daily store; returns the daily closes by date.
def _write(store: MarketStore, ticker: str, sessions: list[date], seed: int) -> None:
    rng = np.random.default_rng(seed)
    closes: dict[date, float] = {}
    open0 = 100.0
    prior = date(2023, 6, 2)
    closes[prior] = open0
    for day in sessions:
        bars = _bars(day, open0, rng.normal(0.0, 0.004, size=SLOTS))
        assert sip.write_session(store, ticker, day, bars, PROVENANCE)
        closes[day] = bars[-1].close
        open0 = bars[-1].close
    store.write(
        date(2026, 9, 26),
        TickerHistory(
            ticker=ticker,
            bars=tuple(
                DailyBar(d, c, c, c, c, c, 26000) for d, c in sorted(closes.items())
            ),
            actions=(),
            complete_through=max(closes),
            source_time=datetime(2026, 9, 26, tzinfo=UTC),
        ),
    )


# A membership history: AAA a member throughout, BBB from a later date.
def _membership(path, bbb_from: date) -> None:
    path.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        "AAA,2016-01-04,2016-01-04,,,test,test\n"
        f"BBB,{bbb_from},{bbb_from},,,test,test\n",
        encoding="utf-8",
    )


# The command runs on a store with two names and a benchmark, writes the
# payload and renders every table.
def test_cli_end_to_end(tmp_path):
    store = MarketStore(tmp_path)
    sessions = _sessions(40)
    assert EARLY_CLOSE in sessions
    full = [d for d in sessions if d != EARLY_CLOSE]
    _write(store, "AAA", sessions, 1)
    _write(store, "BBB", sessions, 2)
    _write(store, "SPY", sessions, 3)
    # One incomplete partition for AAA, to be excluded and counted.
    extra = _sessions(41)[-1]
    sip.write_session(
        store, "AAA", extra, _bars(extra, 100.0, np.zeros(SLOTS))[:20], PROVENANCE
    )
    membership = tmp_path / "membership.csv"
    _membership(membership, sessions[20])

    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--tickers",
            "AAA,BBB,SPY",
            "--membership",
            str(membership),
        ]
    )
    assert cli.run(args, out) == 0
    text = out.getvalue()

    target = tmp_path / "desk" / "session_anatomy.json"
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["study"] == "session_anatomy"
    assert payload["book_tickers"] == ["AAA", "BBB"]
    assert payload["benchmark_tickers"] == ["SPY"]
    assert payload["exclusions"]["AAA"] == {
        "early_close": 1,
        "incomplete": 1,
        "no_prior_close": 0,
    }
    assert payload["exclusions"]["SPY"] == {
        "early_close": 1,
        "incomplete": 0,
        "no_prior_close": 0,
    }
    assert payload["sessions_per_ticker"] == {"AAA": 39, "BBB": 39, "SPY": 39}
    assert payload["asof"] == str(sessions[-1])
    # The mask: AAA on every full session, BBB from its entry on session 20.
    bbb = len([d for d in full if d >= sessions[20]])
    book = payload["book"]["2016-2023"]
    assert book["names"] == 2
    assert book["sessions"] == len(full) + bbb
    assert book["dates"] == len(full)
    assert payload["book"]["2024-2026"]["sessions"] == 0
    bench = payload["benchmarks"]["SPY"]["2016-2023"]
    assert bench["sessions"] == len(full)
    # Every table is present with counts.
    assert len(book["variance_shares"]) == SLOTS
    assert abs(sum(book["variance_shares"]) - 1.0) < 1e-9
    assert len(book["high_slot_shares"]) == SLOTS
    assert len(book["open_drive"]["quintiles"]) == sa.QUINTILES
    assert sum(q["n"] for q in book["open_drive"]["quintiles"]) == len(full) + bbb
    assert book["open_drive"]["dates"] == len(full)
    assert len(book["dips"]) == 9
    assert len(book["extensions"]) == 9
    assert all("n" in c and "t" in c and "difference" in c for c in book["dips"])
    assert book["fill_costs"]["close"]["n"] == len(full) + bbb
    assert book["fill_costs"]["first_hour_vwap"]["n"] == len(full) + bbb
    # Strict JSON: no NaN written.
    assert "NaN" not in target.read_text(encoding="utf-8")

    # The rendered text names the cubes, the exclusions and each table.
    assert "AAA" in text
    assert "excluded: early_close 1, incomplete 1, no_prior_close 0" in text
    assert "book, 2016-2023" in text
    assert "benchmark SPY, 2016-2023" in text
    assert "A. variance share by slot" in text
    assert "A. session high set in slot 0:" in text
    assert "B. open drive: slope" in text
    assert "quintile of r1" in text
    assert "C. dips" in text
    assert "C. extensions" in text
    assert "D. fill cost" in text
    assert "first-hour VWAP" in text
    assert f"wrote {target}" in text


# `--json` prints the payload only, and an empty store exits 1.
def test_cli_json_and_empty_store(tmp_path):
    store = MarketStore(tmp_path)
    out = io.StringIO()
    args = cli.build_parser().parse_args(["--root", str(tmp_path), "--tickers", "AAA"])
    assert cli.run(args, out) == 1
    assert "nothing to study" in out.getvalue()
    sessions = _sessions(5)
    _write(store, "AAA", sessions, 1)
    membership = tmp_path / "membership.csv"
    _membership(membership, date(2016, 1, 4))
    out = io.StringIO()
    args = cli.build_parser().parse_args(
        [
            "--root",
            str(tmp_path),
            "--tickers",
            "AAA",
            "--membership",
            str(membership),
            "--json",
        ]
    )
    assert cli.run(args, out) == 0
    payload = json.loads(out.getvalue())
    assert payload["book"]["2016-2023"]["sessions"] == 5
    assert payload["benchmarks"] == {}
    # The default ticker list is the book plus the four benchmarks.
    defaults = cli.build_parser().parse_args([])
    assert defaults.root == "data/market"
    assert defaults.tickers == ""


# Cubes built across worker processes are the cubes built in this one:
# same sessions, same arrays, same exclusion counts, same order.
def test_load_cubes_in_a_process_pool_matches_the_serial_build(tmp_path):
    store = MarketStore(tmp_path)
    sessions = _sessions(12)
    _write(store, "AAA", sessions, 1)
    _write(store, "BBB", sessions, 2)
    serial, serial_lines = cli.load_cubes(store, ("AAA", "BBB"), workers=1)
    for path in (tmp_path / "research" / "sip_cubes").glob("*.npz"):
        path.unlink()
    pooled, pooled_lines = cli.load_cubes(store, ("AAA", "BBB"), workers=2)
    assert list(pooled) == list(serial) == ["AAA", "BBB"]
    assert pooled_lines == serial_lines
    for ticker in serial:
        np.testing.assert_array_equal(pooled[ticker].dates, serial[ticker].dates)
        np.testing.assert_array_equal(pooled[ticker].close, serial[ticker].close)
        assert pooled[ticker].excluded == serial[ticker].excluded
    assert cli.DEFAULT_WORKERS >= 1
    assert cli.build_parser().parse_args(["--workers", "3"]).workers == 3
