"""The desk's day: refresh the data, run the desk, write the record.

    python -m backend.cli.market_daily --refresh            # data, then the desk
    python -m backend.cli.market_daily                      # the desk on stored data
    python -m backend.cli.market_daily --refresh --brief SNDK CRWV

`--refresh` pulls daily bars for the book names, the benchmark and the
macro series, the EDGAR events and facts for the book names, and scores any
release not yet scored (only the new ones: earlier scores carry forward).
Then the desk runs and prints the regime, the grades and the book, and the
whole record is written to `data/market/desk/asof=DATE/desk.json` so a day
can be read back later exactly as it was seen.
"""

import argparse
import json
import shutil
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk import plainly
from backend.agents.trading.desk.narrative import DeskNarrator, brief_text
from backend.cli import market_edgar, market_tone
from backend.cli.market_desk import _print_book, _print_grades, _print_regime
from backend.config.settings import settings
from backend.market import snapshot
from backend.market.macro import SERIES
from backend.market.store import MarketStore
from backend.market.universe import MARKET_BENCHMARK, book_sides, build_universe

DESK_KIND = "desk"
# The layers a day re-fetches in full, so old partitions of them are
# only copies of what a newer one holds. Tone is never pruned: every
# score in it cost a model call, and desk records are the track record.
PRUNABLE = ("bars", "actions", "edgar_events", "edgar_facts")


# Build the CLI parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=settings.MARKET_DATA_ROOT)
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--skip-tone", action="store_true", help="refresh without scoring"
    )
    parser.add_argument("--llm-url", default="")
    parser.add_argument("--llm-model", default="")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument(
        "--brief", nargs="*", default=[], help="tickers to write briefs for"
    )
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument(
        "--brief-book",
        action="store_true",
        help="write briefs for every name in today's book",
    )
    parser.add_argument(
        "--paper-trade",
        action="store_true",
        help="submit the book to the Alpaca PAPER account for the next open",
    )
    parser.add_argument(
        "--paper-dry-run",
        action="store_true",
        help="print the paper orders and the account without submitting",
    )
    parser.add_argument(
        "--prune-days",
        type=int,
        default=0,
        help="drop bar and filing partitions older than this many days (0 keeps all)",
    )
    return parser


# The tickers the desk needs daily bars for: the book, the benchmark, the
# macro series.
def bar_tickers() -> tuple[str, ...]:
    """Return the tickers the daily refresh pulls bars for."""
    names = tuple(sorted(book_sides(build_universe())))
    return names + (MARKET_BENCHMARK,) + tuple(SERIES.values())


# The book names, for the filings and the releases.
def book_tickers() -> tuple[str, ...]:
    """Return the book's tickers."""
    return tuple(sorted(book_sides(build_universe())))


# Refresh every layer the desk reads, in the order it needs them.
def refresh(
    store: MarketStore,
    asof: date,
    *,
    skip_tone: bool = False,
    llm_url: str = "",
    llm_model: str = "",
    concurrency: int = 4,
    bars=snapshot.refresh,
    filings=market_edgar.refresh,
    tone=market_tone.refresh_tickers,
) -> None:
    """Pull bars, filings and new release scores into the as-of partition."""
    report = bars(store, bar_tickers(), asof=asof)
    print(
        f"bars: {report.stored_count} stored, {len(report.failed_tickers)} failed"
        + (
            " (" + ", ".join(report.failed_tickers) + ")"
            if report.failed_tickers
            else ""
        )
    )
    filings(store, book_tickers(), asof)
    if skip_tone:
        print("tone: skipped")
        return
    try:
        scored = tone(
            store,
            book_tickers(),
            asof,
            llm_url=llm_url,
            llm_model=llm_model,
            concurrency=concurrency,
        )
    except Exception as exc:  # the runtime being away must not stop the desk
        print(f"tone: not scored ({type(exc).__name__}: {exc}); earlier scores carry")
        return
    print(f"tone: {scored} new releases scored")


# Drop partitions of the re-fetched layers older than `days`, keeping the
# newest partition of each layer whatever its age.
def prune(root: Path, asof: date, days: int) -> list[Path]:
    """Remove old bar and filing partitions; return what was removed."""
    if days <= 0:
        return []
    cutoff = asof - timedelta(days=days)
    removed: list[Path] = []
    for kind in PRUNABLE:
        base = Path(root) / kind
        if not base.exists():
            continue
        partitions = sorted(
            p for p in base.iterdir() if p.is_dir() and p.name.startswith("asof=")
        )
        for p in partitions[:-1]:
            try:
                stamp = date.fromisoformat(p.name[len("asof=") :])
            except ValueError:
                continue
            if stamp < cutoff:
                shutil.rmtree(p)
                removed.append(p)
    return removed


# Carry the desk's book to the paper account: cancel yesterday's unfilled
# orders, plan this session, submit the plan for the next open, then record
# the account. Returns the day's entry for the desk record.
def paper_trade(report, store_root: Path, session: str, live: bool) -> dict:
    """Plan and (when `live`) submit the paper book; return the day's entry."""
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    client = alpaca_trading.client_from_env()
    account = client.account()
    held = {p.symbol: p.qty for p in client.positions()}
    panel = report.panel
    last = len(panel.dates) - 1
    prices = {
        ticker: float(panel.close[last, column])
        for column, ticker in enumerate(panel.tickers)
        if panel.close[last, column] == panel.close[last, column]
    }
    targets = {s.position.ticker: s.weight for s in report.book}
    grades = {
        ticker: report.graded.letter(last, column)
        for column, ticker in enumerate(panel.tickers)
        if ticker != panel.benchmark
    }
    state = paper.load_state(store_root)
    # Nothing is passed for `finished`: the band exit that used to fill it
    # was measured inside the book's own rules and cost 3.0% a year. See
    # the note at the top of `desk/exit.py`.
    orders, new_state, what = paper.plan(
        session, state, account.equity, held, prices, targets, grades
    )
    print(f"\npaper book ({what}), equity {account.equity:,.0f}:")
    submitted = []
    if live and orders:
        client.cancel_open_orders()
    for order in orders:
        line = f"  {order.side:4} {order.qty:5d} {order.symbol:6} {order.reason}"
        if not live:
            print(line + "  [dry run]")
            continue
        try:
            client.submit_market_on_open(order.symbol, order.qty, order.side)
            submitted.append(
                {
                    "symbol": order.symbol,
                    "side": order.side,
                    "qty": order.qty,
                    "reason": order.reason,
                }
            )
            print(line)
        except alpaca_trading.AlpacaTradingError as exc:
            print(line + f"  REFUSED: {exc}")
    if not orders:
        print("  nothing to do")
    positions = [
        {
            "symbol": p.symbol,
            "qty": p.qty,
            "market_value": p.market_value,
            "avg_entry_price": p.avg_entry_price,
            "current_price": p.current_price,
            "unrealized_pl": p.unrealized_pl,
        }
        for p in client.positions()
    ]
    entry = paper.snapshot(new_state, session, account.equity, account.cash, positions)
    entry["orders"] = submitted
    entry["plan"] = what
    if live:
        paper.save_state(store_root, new_state)
    print(
        f"  equity {entry['equity']:,.0f}, P/L since the start "
        f"{entry['pl']:+,.0f} ({entry['pl_pct'] * 100:+.1f}%)"
    )
    return entry


# The day's record, as plain data.
def record(
    report, briefs: dict[str, dict] | None = None, paper: dict | None = None
) -> dict:
    """Return the JSON-ready record of a DeskReport."""
    panel = report.panel
    last = len(panel.dates) - 1
    state = report.regime.today()
    grades = {}
    # Every name carries its own reason, written from the same evidence the
    # grade came from. The model's brief covers only the names held, so
    # without this the view answers "what" for ninety names and "why" for
    # eight. Nothing here calls a model, so it costs nothing and cannot
    # invent a figure.
    scale = plainly.spreads(report)
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        view = report.brief(ticker)
        grades[ticker] = {
            "grade": report.graded.letter(last, column),
            "votes": float(report.graded.votes[last, column]),
            "stances": {
                k: int(v[last, column]) for k, v in report.graded.stances.items()
            },
            "score": float(report.scores[last, column]),
            "side": report.sides.get(ticker, ""),
            "headline": plainly.headline(view),
            "reason": plainly.reason(view, scale),
        }
    return {
        "session": str(panel.dates[last]),
        "written": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "regime": {
            k: (v if not isinstance(v, tuple) else list(v))
            for k, v in state.__dict__.items()
        },
        "grades": grades,
        "book": [
            {
                "ticker": s.position.ticker,
                "grade": s.grade,
                "weight": s.weight,
                "engine_weight": s.position.weight,
                "volatility": s.position.volatility,
                "exposure": s.exposure,
            }
            for s in report.book
        ],
        "briefs": briefs or {},
        "paper": paper,
    }


# Where the day's record lives.
def record_path(root: Path, session: str) -> Path:
    """Return the path of the desk record for a session."""
    return Path(root) / DESK_KIND / f"asof={session}" / "desk.json"


# Write the record and return its path.
def save(root: Path, data: dict) -> Path:
    """Write the day's record as JSON."""
    path = record_path(root, data["session"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=float), encoding="utf-8")
    return path


# Write and print the briefs for some names through the local model.
def briefs_for(report, tickers, narrator: DeskNarrator) -> dict[str, dict]:
    """Return {ticker: brief fields} for the names the model could brief."""
    out: dict[str, dict] = {}
    for ticker in tickers:
        if ticker not in report.panel.tickers:
            print(f"\n{ticker}: not in the book")
            continue
        grade = report.brief(ticker)["grade"]
        brief = narrator.brief_sync(brief_text(report, ticker), grade)
        if brief is None:
            print(f"\n{ticker}: no brief (runtime away or the answer did not fit)")
            continue
        out[ticker] = {
            "stance": brief.stance,
            "verdict": brief.verdict,
            "reasoning": brief.reasoning,
            "risks": brief.risks,
            "watch": brief.watch,
        }
        print(f"\n{ticker} ({grade}, {brief.stance}): {brief.verdict}")
        print(f"  {brief.reasoning}")
        print(f"  risks: {brief.risks}")
        print(f"  watch: {brief.watch}")
    return out


# Run the day.
def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    store = MarketStore(args.data_dir)
    asof = args.asof or datetime.now(tz=UTC).date()
    if args.refresh:
        refresh(
            store,
            asof,
            skip_tone=args.skip_tone,
            llm_url=args.llm_url,
            llm_model=args.llm_model,
            concurrency=args.concurrency,
        )
    report = trading_desk.run(store, args.asof)
    panel = report.panel
    print(f"\ndesk as of {panel.dates[-1]} on {len(panel.tickers) - 1} names")
    _print_regime(report.regime.today())
    _print_grades(report, args.top)
    _print_book(report)
    briefs: dict[str, dict] = {}
    wanted = list(args.brief)
    if args.brief_book:
        wanted += [
            s.position.ticker for s in report.book if s.position.ticker not in wanted
        ]
    if wanted:
        readers, _model = market_tone.clients(args.llm_url, args.llm_model, 1)
        briefs = briefs_for(report, wanted, DeskNarrator(readers[0].writer))
    entry = None
    if args.paper_trade or args.paper_dry_run:
        session = str(panel.dates[-1])
        try:
            entry = paper_trade(
                report, Path(store.root), session, live=args.paper_trade
            )
        except Exception as exc:  # the account being away must not lose the record
            print(f"\npaper book: not traded ({type(exc).__name__}: {exc})")
    path = save(Path(store.root), record(report, briefs, entry))
    print(f"\nrecord written: {path}")
    removed = prune(Path(store.root), asof, args.prune_days)
    if removed:
        print(f"pruned {len(removed)} old partitions")


if __name__ == "__main__":
    main()
