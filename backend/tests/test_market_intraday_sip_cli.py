"""The SIP fifteen-minute store's command: refresh under a cap, dry run, gate, report.

What has to hold: a dry run makes no request and says what it would fetch;
a refresh sends feed=sip and adjustment=raw, writes one partition per
session, and stops at the request cap with everything written so far kept;
the default tickers are the book plus the four benchmarks; reconcile and
report read the store and the daily store and print per-ticker numbers.
"""

import io
import json
from datetime import UTC, date, datetime, timedelta

from backend.cli import market_intraday_sip as cli
from backend.market import intraday_sip as sip
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory

MON, TUE, WED, THU, FRI = (date(2025, 12, 1) + timedelta(days=i) for i in range(5))
HEADERS = {"APCA-API-KEY-ID": "k", "APCA-API-SECRET-KEY": "s"}


# One session's 26 regular bars from 09:30 EST as Alpaca JSON rows.
def _rows(day: date, base: float) -> list[dict]:
    start = datetime(day.year, day.month, day.day, 14, 30, tzinfo=UTC)
    return [
        {
            "t": (start + timedelta(minutes=15 * i)).isoformat().replace("+00:00", "Z"),
            "o": base + i,
            "h": base + i + 0.5,
            "l": base + i - 0.5,
            "c": base + i,
            "v": 100.0,
        }
        for i in range(26)
    ]


# A fake Alpaca that answers every bars request from a fixed tape, and
# records the URLs it was asked for.
class FakeAlpaca:
    """Serve bars for the symbol and date range in the URL."""

    def __init__(self, tape: dict[str, dict[date, float]]):
        self.tape = tape
        self.urls: list[str] = []

    # Answer one request from the tape.
    def __call__(self, url: str, headers: dict) -> tuple[int, bytes]:
        self.urls.append(url)
        query = dict(part.split("=", 1) for part in url.split("?", 1)[1].split("&"))
        symbol = query["symbols"]
        start = date.fromisoformat(query["start"][:10])
        end = date.fromisoformat(query["end"][:10])
        rows = [
            row
            for day, base in sorted(self.tape.get(symbol, {}).items())
            if start <= day <= end
            for row in _rows(day, base)
        ]
        return (
            200,
            json.dumps({"bars": {symbol: rows}, "next_page_token": None}).encode(),
        )


# A daily history matching `_rows(day, base)` for the sessions given.
def _daily(ticker: str, bases: dict[date, float]) -> TickerHistory:
    return TickerHistory(
        ticker=ticker,
        bars=tuple(
            DailyBar(d, b, b + 25.5, b - 0.5, b + 25, b + 25, 2600)
            for d, b in sorted(bases.items())
        ),
        actions=(),
        complete_through=max(bases),
        source_time=datetime(2026, 9, 26, tzinfo=UTC),
    )


# A dry run makes no request, names the sessions it would fetch and
# estimates the requests; a refresh then fetches with feed=sip and
# adjustment=raw and writes one partition per session.
def test_dry_run_then_refresh_writes_one_partition_per_session(tmp_path):
    store = MarketStore(tmp_path)
    feed = FakeAlpaca({"AVGO": {MON: 100.0, TUE: 200.0, WED: 300.0}})
    dry = cli.refresh(
        store,
        ("AVGO",),
        MON,
        WED,
        max_requests=10,
        dry_run=True,
        include_incomplete=False,
        transport=feed,
        headers=HEADERS,
        sleep=lambda s: None,
        out=io.StringIO(),
    )
    assert feed.urls == []
    assert dry["tickers"]["AVGO"]["to_fetch"] == 3
    assert dry["tickers"]["AVGO"]["ranges"] == [("2025-12-01", "2025-12-03")]
    assert dry["estimated_requests"] == 1
    out = io.StringIO()
    live = cli.refresh(
        store,
        ("AVGO",),
        MON,
        WED,
        max_requests=10,
        dry_run=False,
        include_incomplete=False,
        transport=feed,
        headers=HEADERS,
        sleep=lambda s: None,
        out=out,
    )
    assert len(feed.urls) == 1
    assert "&feed=sip&adjustment=raw&" in feed.urls[0]
    assert "timeframe=15Min" in feed.urls[0]
    assert live["requests"] == 1
    assert live["tickers"]["AVGO"]["written"] == 3
    assert sip.sessions_available(store, "AVGO") == [MON, TUE, WED]
    assert sip.read_session(store, "AVGO", TUE)[1]["complete"] == "true"
    assert "3 written" in out.getvalue()
    # A second refresh has nothing to fetch and makes no request.
    again = cli.refresh(
        store,
        ("AVGO",),
        MON,
        WED,
        max_requests=10,
        dry_run=False,
        include_incomplete=False,
        transport=feed,
        headers=HEADERS,
        sleep=lambda s: None,
        out=io.StringIO(),
    )
    assert len(feed.urls) == 1
    assert again["tickers"]["AVGO"]["written"] == 0


# The request cap stops the run: the first ticker's sessions are kept,
# the second is not started, and the summary says why.
def test_request_cap_stops_the_run_and_keeps_what_was_written(tmp_path):
    store = MarketStore(tmp_path)
    feed = FakeAlpaca({"AVGO": {MON: 100.0}, "SPY": {MON: 500.0}})
    out = io.StringIO()
    summary = cli.refresh(
        store,
        ("AVGO", "SPY"),
        MON,
        MON,
        max_requests=1,
        dry_run=False,
        include_incomplete=False,
        transport=feed,
        headers=HEADERS,
        sleep=lambda s: None,
        out=out,
    )
    assert len(feed.urls) == 1
    assert summary["requests"] == 1
    assert summary["stopped"].startswith("SPY: request cap of 1 reached")
    assert sip.sessions_available(store, "AVGO") == [MON]
    assert sip.sessions_available(store, "SPY") == []
    assert "STOPPED" in out.getvalue()


# 429 retries count against the cap too: a feed that keeps throttling
# cannot make the run exceed its budget.
def test_throttled_retries_count_against_the_cap(tmp_path):
    store = MarketStore(tmp_path)
    calls = []

    def throttling(url, headers):
        calls.append(url)
        return 429, b""

    summary = cli.refresh(
        store,
        ("AVGO",),
        MON,
        MON,
        max_requests=3,
        dry_run=False,
        include_incomplete=False,
        transport=throttling,
        headers=HEADERS,
        sleep=lambda s: None,
        out=io.StringIO(),
    )
    assert len(calls) == 3
    assert summary["requests"] == 3
    assert summary["stopped"] is not None


# The default tickers are the book plus SPY, QQQ, SMH and IGV, 98 names,
# and an explicit list is upper-cased and de-duplicated.
def test_default_tickers_are_the_book_plus_the_benchmarks():
    tickers = cli.select_tickers("")
    assert len(tickers) == 98
    assert tickers[-4:] == ("SPY", "QQQ", "SMH", "IGV")
    assert "AVGO" in tickers
    assert "IWM" not in tickers
    assert cli.select_tickers("avgo, spy,AVGO") == ("AVGO", "SPY")


# For years the calendar has not reviewed, the sessions asked for come
# from the daily store's session dates; for reviewed years, the calendar.
def test_sessions_for_uses_the_daily_store_before_the_calendar_coverage(tmp_path):
    store = MarketStore(tmp_path)
    old = date(2014, 12, 31)
    store.write(date(2026, 9, 26), _daily("AVGO", {old: 50.0, date(2015, 1, 2): 60.0}))
    sessions = cli.sessions_for(store, "AVGO", date(2014, 12, 30), date(2015, 1, 5))
    assert sessions == [old, date(2015, 1, 2), date(2015, 1, 5)]
    assert cli.sessions_for(store, "NOPE", date(2014, 12, 30), date(2014, 12, 31)) == []


# Reconcile prints a failure line with its reason and a pass rate per
# ticker; report prints coverage against the calendar.
def test_reconcile_and_report_print_per_ticker_numbers(tmp_path):
    store = MarketStore(tmp_path)
    feed = FakeAlpaca({"AVGO": {MON: 100.0, TUE: 200.0}})
    cli.refresh(
        store,
        ("AVGO",),
        MON,
        TUE,
        max_requests=10,
        dry_run=False,
        include_incomplete=False,
        transport=feed,
        headers=HEADERS,
        sleep=lambda s: None,
        out=io.StringIO(),
    )
    store.write(date(2026, 9, 26), _daily("AVGO", {MON: 100.0, TUE: 205.0}))
    out = io.StringIO()
    gate = cli.reconcile(store, ("AVGO",), MON, FRI, out=out)
    assert gate["tickers"]["AVGO"]["reconciled"] == 2
    assert gate["tickers"]["AVGO"]["passed"] == 1
    assert gate["close_tolerance"] == 0.005
    assert gate["volume_tolerance"] == 0.2
    text = out.getvalue()
    assert "AVGO   2025-12-02 FAIL close differs" in text
    assert "passed     1 (50.0%)" in text
    out = io.StringIO()
    rows = cli.report(store, ("AVGO",), MON, FRI, out=out)
    assert rows["AVGO"]["sessions_in_calendar"] == 5
    assert rows["AVGO"]["sessions_stored"] == 2
    assert rows["AVGO"]["complete_share"] == 1.0
    assert rows["AVGO"]["reconcile_pass_rate"] == 0.5
    assert (
        "AVGO   stored     2/    5 calendar sessions, "
        "complete 100.0%, reconcile pass 50.0%"
    ) in out.getvalue()


# The command line: --report is the default action, --json prints the
# summary, and --dry-run --refresh needs no credentials.
def test_main_runs_report_by_default_and_dry_run_needs_no_keys(tmp_path, monkeypatch):
    monkeypatch.delenv("APCA_API_KEY_ID", raising=False)
    monkeypatch.delenv("APCA_API_SECRET_KEY", raising=False)
    out = io.StringIO()
    assert (
        cli.main(
            [
                "--tickers",
                "AVGO",
                "--data-dir",
                str(tmp_path),
                "--since",
                "2025-12-01",
                "--until",
                "2025-12-05",
                "--json",
            ],
            out=out,
        )
        == 0
    )
    summary = json.loads(out.getvalue().split("\n", 1)[1])
    assert summary["report"]["AVGO"]["sessions_stored"] == 0
    out = io.StringIO()
    assert (
        cli.main(
            [
                "--refresh",
                "--dry-run",
                "--tickers",
                "AVGO",
                "--data-dir",
                str(tmp_path),
                "--since",
                "2025-12-01",
                "--until",
                "2025-12-05",
            ],
            out=out,
        )
        == 0
    )
    assert "would fetch     5 sessions" in out.getvalue()
    assert "would make about 1 requests (cap 2000)" in out.getvalue()


# The default --until is today in New York once the session's bars are
# final, yesterday before that, and it follows the early close.
def test_default_until_waits_for_the_close():
    ny = cli.NEW_YORK
    assert cli.default_until(datetime(2025, 12, 1, 15, 0, tzinfo=ny)) == date(
        2025, 11, 30
    )
    assert cli.default_until(datetime(2025, 12, 1, 16, 29, tzinfo=ny)) == date(
        2025, 11, 30
    )
    assert cli.default_until(datetime(2025, 12, 1, 16, 30, tzinfo=ny)) == date(
        2025, 12, 1
    )
    # 22:00 UTC on Dec 1 is 17:00 New York: still Dec 1, not the UTC date.
    assert cli.default_until(datetime(2025, 12, 2, 3, 0, tzinfo=UTC)) == date(
        2025, 12, 1
    )
    # The early close on Nov 28 is final at 13:30.
    assert cli.default_until(datetime(2025, 11, 28, 13, 31, tzinfo=ny)) == date(
        2025, 11, 28
    )
    assert cli.default_until(datetime(2025, 11, 28, 13, 29, tzinfo=ny)) == date(
        2025, 11, 27
    )


# The request estimate uses the page size Alpaca actually serves on the
# SIP feed (about 1,000 bars), not the 10,000 the query asks for: the
# first backfill (2026-09-27) was estimated at 1,633 requests and needed
# about 95 for a thin name and 190 for a liquid one, and stopped at the
# default cap after twenty names.
def test_estimate_requests_uses_the_observed_page_size():
    assert cli.SIP_PAGE_BARS_OBSERVED == 1000
    assert cli.estimate_requests(0) == 0
    assert cli.estimate_requests(1) == 1
    assert cli.estimate_requests(2698) == 173
    assert cli.estimate_requests(2698) * 98 > cli.DEFAULT_MAX_REQUESTS
