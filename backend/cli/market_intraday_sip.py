"""Keep the raw-basis SIP fifteen-minute store current, and check it.

    python -m backend.cli.market_intraday_sip --refresh --dry-run
    python -m backend.cli.market_intraday_sip --refresh --since 2016-01-01
    python -m backend.cli.market_intraday_sip --refresh --tickers AVGO,SPY
    python -m backend.cli.market_intraday_sip --reconcile --report

Needs APCA_API_KEY_ID and APCA_API_SECRET_KEY in the environment (a free
Alpaca account; delayed consolidated history is served on the same key,
`feed=sip`). Each session lands as its own immutable `bars_15m_sip`
partition labelled by the New York session date; sessions already stored
are never fetched again, so a run that stopped at the request cap is
resumed by running it again.

The request cap (`--max-requests`, default 2000) counts every HTTP request
the run makes, including 429 retries, and stops the run before it exceeds
the free plan's allowance. A dry run prints what would be fetched and how
many requests that is likely to take, and makes no request at all.

The default tickers are the book (`universe.book_sides`) plus SPY, QQQ, SMH
and IGV: 98 names. Over 2016-2026 a full history is about 18 pages per
name (about 2,700 sessions at 64 extended-hours bars a day, 10,000 bars a
page), about 1,800 requests in all.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, TextIO
from zoneinfo import ZoneInfo

from backend.config.settings import settings
from backend.market import alpaca, calendar, intraday_sip
from backend.market.store import MarketStore
from backend.market.universe import book_sides, build_universe

NEW_YORK = ZoneInfo("America/New_York")
BENCHMARKS = ("SPY", "QQQ", "SMH", "IGV")
DEFAULT_MAX_REQUESTS = 2000
# Bars a session contributes to a paged SIP fetch: 04:00-20:00 extended
# hours at fifteen minutes. Used only to estimate requests for a dry run.
BARS_PER_SESSION_ESTIMATE = 64
# Minutes after the close before today's bars are treated as final: the
# delayed SIP feed is fifteen minutes behind, and the closing bar needs
# to have ended.
FINAL_BARS_LAG_MINUTES = 30


class RequestCapReachedError(RuntimeError):
    """The run made as many requests as it was allowed to."""


# A transport that counts every request and refuses to go past the cap,
# so a run cannot exceed the free plan however many sessions are missing.
class CappedTransport:
    """Wrap a transport with a hard request budget."""

    # `cap` requests are allowed; the next one raises RequestCapReached.
    def __init__(self, cap: int, transport: alpaca.Transport = alpaca.alpaca_transport):
        self.cap = cap
        self.transport = transport
        self.count = 0

    # Make one request, or refuse when the budget is spent.
    def __call__(self, url: str, headers: dict[str, str]) -> tuple[int, bytes]:
        if self.count >= self.cap:
            raise RequestCapReachedError(f"request cap of {self.cap} reached")
        self.count += 1
        return self.transport(url, headers)


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Build the parser for the SIP fifteen-minute store tool."""
    parser = argparse.ArgumentParser(
        description="Fetch, reconcile and report consolidated SIP 15-minute bars."
    )
    parser.add_argument("--refresh", action="store_true", help="fetch missing sessions")
    parser.add_argument(
        "--reconcile", action="store_true", help="run the acceptance gate per session"
    )
    parser.add_argument("--report", action="store_true", help="coverage per ticker")
    parser.add_argument(
        "--dry-run", action="store_true", help="print what --refresh would fetch"
    )
    parser.add_argument(
        "--tickers", default="", help="comma-separated; default: the book"
    )
    parser.add_argument("--since", type=date.fromisoformat, default=date(2016, 1, 1))
    parser.add_argument("--until", type=date.fromisoformat, default=None)
    parser.add_argument("--max-requests", type=int, default=DEFAULT_MAX_REQUESTS)
    parser.add_argument(
        "--include-incomplete",
        action="store_true",
        help="also fetch again the sessions stored incomplete",
    )
    parser.add_argument(
        "--data-dir", type=Path, default=Path(settings.MARKET_DATA_ROOT)
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


# The book's tickers plus the four benchmarks, or the ones asked for.
def select_tickers(spec: str) -> tuple[str, ...]:
    """Return the tickers a run applies to."""
    if spec:
        return tuple(
            dict.fromkeys(t.strip().upper() for t in spec.split(",") if t.strip())
        )
    book = sorted(book_sides(build_universe()))
    return tuple(dict.fromkeys([*book, *BENCHMARKS]))


# The last session the store should hold: today on the New York calendar
# once its bars are final (the calendar close plus the delayed feed's
# lag), otherwise yesterday, so a run during the session never stores a
# partial day that a later run would then leave alone. Never the UTC date.
def default_until(now: datetime | None = None) -> date:
    """Return the newest session date a refresh should ask for."""
    local = (now or datetime.now(tz=NEW_YORK)).astimezone(NEW_YORK)
    today = local.date()
    final = datetime.combine(
        today, calendar.session_close(today), NEW_YORK
    ) + timedelta(minutes=FINAL_BARS_LAG_MINUTES)
    return today if local >= final else today - timedelta(days=1)


# A rough request count for fetching `sessions` sessions in one run: one
# page per 10,000 bars, at least one request.
def estimate_requests(sessions: int) -> int:
    """Return the likely number of paged requests for a contiguous run."""
    if sessions <= 0:
        return 0
    return max(1, math.ceil(sessions * BARS_PER_SESSION_ESTIMATE / alpaca.PAGE_LIMIT))


# The sessions to hold for one ticker over [since, until]: the reviewed
# exchange calendar where it has the year, and for the years it has not
# reviewed (2016-2018 today) the session dates the daily store holds for
# that ticker, which are the sessions that actually traded.
def sessions_for(
    store: MarketStore, ticker: str, since: date, until: date
) -> list[date]:
    """Return the session dates a refresh asks for, for one ticker."""
    sessions, unreviewed = intraday_sip.calendar_sessions(since, until)
    if unreviewed:
        history = store.read(ticker)
        if history is not None:
            sessions.extend(
                b.session_date
                for b in history.bars
                if b.session_date.year in unreviewed
                and since <= b.session_date <= until
            )
    return sorted(set(sessions))


# Fetch the missing sessions of every ticker under the request cap. Stops
# at the cap or on a provider error for one ticker (the next ticker is
# still tried); partitions written before that remain, so a rerun resumes.
def refresh(
    store: MarketStore,
    tickers: tuple[str, ...],
    since: date,
    until: date,
    *,
    max_requests: int,
    dry_run: bool,
    include_incomplete: bool,
    transport: alpaca.Transport = alpaca.alpaca_transport,
    headers: dict[str, str] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    out: TextIO = sys.stdout,
) -> dict[str, Any]:
    """Refresh the store for the tickers and return a summary."""
    capped = CappedTransport(max_requests, transport)
    meta = intraday_sip.provenance_now()

    # One paged SIP request per contiguous run of sessions.
    def fetch(ticker: str, start: date, end: date) -> list[alpaca.IntradayBar]:
        return alpaca.fetch_bars(
            ticker,
            start,
            end,
            capped,
            headers,
            sleep,
            feed=intraday_sip.FEED,
            adjustment=intraday_sip.ADJUSTMENT,
            timeframe=intraday_sip.TIMEFRAME,
        )

    summary: dict[str, Any] = {
        "dry_run": dry_run,
        "max_requests": max_requests,
        "requests": 0,
        "estimated_requests": 0,
        "tickers": {},
        "stopped": None,
    }
    for ticker in tickers:
        try:
            result = intraday_sip.append_missing(
                store,
                ticker,
                sessions_for(store, ticker, since, until),
                fetch,
                meta,
                include_incomplete=include_incomplete,
                dry_run=dry_run,
            )
        except RequestCapReachedError as exc:
            summary["stopped"] = f"{ticker}: {exc}"
            print(f"{ticker:6} STOPPED {exc}", file=out, flush=True)
            break
        except alpaca.AlpacaUnavailableError as exc:
            summary["tickers"][ticker] = {"error": str(exc)}
            print(f"{ticker:6} FAILED  {exc}", file=out, flush=True)
            continue
        estimate = sum(
            estimate_requests(len([d for d in result.to_fetch if a <= d <= b]))
            for a, b in result.fetch_ranges
        )
        summary["estimated_requests"] += estimate
        summary["tickers"][ticker] = {
            "requested": result.requested,
            "already_stored": result.already_stored,
            "to_fetch": len(result.to_fetch),
            "ranges": [(a.isoformat(), b.isoformat()) for a, b in result.fetch_ranges],
            "estimated_requests": estimate,
            "written": len(result.written),
            "incomplete": [d.isoformat() for d in result.incomplete],
            "no_bars": len(result.no_bars),
        }
        if dry_run:
            print(
                f"{ticker:6} would fetch {len(result.to_fetch):5d} sessions in "
                f"{len(result.fetch_ranges):3d} range(s), ~{estimate:3d} requests"
                + (
                    f"  first {result.fetch_ranges[0][0]}"
                    if result.fetch_ranges
                    else ""
                ),
                file=out,
                flush=True,
            )
        else:
            print(
                f"{ticker:6} ok      {len(result.written):5d} written, "
                f"{result.already_stored:5d} kept, "
                f"{len(result.incomplete):3d} incomplete, "
                f"{len(result.no_bars):5d} empty; {capped.count} requests so far",
                file=out,
                flush=True,
            )
    summary["requests"] = capped.count
    return summary


# The acceptance gate over every stored session of each ticker: one line
# per failure, a pass rate per ticker, and the records in the summary.
def reconcile(
    store: MarketStore,
    tickers: tuple[str, ...],
    since: date,
    until: date,
    out: TextIO = sys.stdout,
) -> dict[str, Any]:
    """Reconcile every stored session in range and return the records."""
    summary: dict[str, Any] = {
        "close_tolerance": intraday_sip.DEFAULT_CLOSE_TOLERANCE,
        "volume_tolerance": intraday_sip.DEFAULT_VOLUME_TOLERANCE,
        "tickers": {},
    }
    for ticker in tickers:
        history = store.read(ticker)
        records = []
        for session in intraday_sip.sessions_available(store, ticker):
            if not since <= session <= until:
                continue
            records.append(
                intraday_sip.reconcile(store, ticker, session, daily=history)
            )
        passed = sum(1 for r in records if r.passed)
        for r in records:
            if not r.passed:
                print(f"{ticker:6} {r.session} FAIL {r.reason}", file=out, flush=True)
        rate = passed / len(records) if records else None
        print(
            f"{ticker:6} reconciled {len(records):5d}, passed {passed:5d}"
            + (f" ({rate:.1%})" if rate is not None else ""),
            file=out,
            flush=True,
        )
        summary["tickers"][ticker] = {
            "reconciled": len(records),
            "passed": passed,
            "pass_rate": rate,
            "failures": [
                intraday_sip.reconciliation_record(r) for r in records if not r.passed
            ],
        }
    return summary


# Coverage per ticker: sessions stored against the calendar, the complete
# share and the reconcile pass rate.
def report(
    store: MarketStore,
    tickers: tuple[str, ...],
    since: date,
    until: date,
    out: TextIO = sys.stdout,
) -> dict[str, Any]:
    """Print and return the coverage of every ticker over [since, until]."""
    rows: dict[str, dict[str, Any]] = {}
    for ticker in tickers:
        row = intraday_sip.coverage(store, ticker, since, until)
        rows[ticker] = row
        share = row["complete_share"]
        rate = row["reconcile_pass_rate"]
        stored = f"{row['sessions_stored']:5d}/{row['sessions_in_calendar']:5d}"
        line = (
            f"{ticker:6} stored {stored} calendar sessions, complete "
            + (f"{share:.1%}" if share is not None else "-")
            + ", reconcile pass "
            + (f"{rate:.1%}" if rate is not None else "-")
        )
        if row["calendar_unreviewed_years"]:
            line += f", calendar unreviewed {row['calendar_unreviewed_years']}"
        print(line, file=out, flush=True)
    return rows


# Run the tool.
def main(argv: list[str] | None = None, out: TextIO = sys.stdout) -> int:
    """Entry point: refresh, reconcile and/or report the SIP store."""
    args = build_parser().parse_args(argv)
    if not (args.refresh or args.reconcile or args.report):
        args.report = True
    tickers = select_tickers(args.tickers)
    store = MarketStore(args.data_dir)
    until = args.until or default_until()
    summary: dict[str, Any] = {
        "tickers": list(tickers),
        "since": args.since.isoformat(),
        "until": until.isoformat(),
    }
    if args.refresh:
        _sessions, unreviewed = intraday_sip.calendar_sessions(args.since, until)
        if unreviewed:
            print(
                f"calendar has no reviewed sessions for {unreviewed}; in those years "
                "the sessions asked for are the daily store's session dates per ticker",
                file=out,
            )
        headers = None if args.dry_run else alpaca.credentials()
        summary["refresh"] = refresh(
            store,
            tickers,
            args.since,
            until,
            max_requests=args.max_requests,
            dry_run=args.dry_run,
            include_incomplete=args.include_incomplete,
            headers=headers,
            out=out,
        )
        made = (
            summary["refresh"]["estimated_requests"]
            if args.dry_run
            else summary["refresh"]["requests"]
        )
        print(
            f"{'would make about' if args.dry_run else 'made'} "
            f"{made} requests (cap {args.max_requests})",
            file=out,
        )
    if args.reconcile:
        summary["reconcile"] = reconcile(store, tickers, args.since, until, out=out)
    if args.report:
        summary["report"] = report(store, tickers, args.since, until, out=out)
    if args.json:
        print(json.dumps(summary, indent=2, default=str), file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
