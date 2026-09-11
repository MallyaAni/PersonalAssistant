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

import numpy as np

from backend.agents.trading.desk import actions, plainly
from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk.narrative import DeskNarrator, brief_text
from backend.cli import market_edgar, market_tone
from backend.cli.market_desk import _print_book, _print_grades, _print_regime
from backend.config.settings import settings
from backend.market import snapshot
from backend.market.macro import SERIES
from backend.market.store import MarketStore
from backend.market.universe import MARKET_INDICES, book_sides, build_universe

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
    parser.add_argument(
        "--challenger",
        action="store_true",
        help="write the shadow desk (the rule without its promoted input)",
    )
    parser.add_argument("--asof", type=date.fromisoformat, default=None)
    parser.add_argument(
        "--force",
        action="store_true",
        help="rewrite a session's record that already exists (the default "
        "refuses, so a day's decision is never silently replaced)",
    )
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
        "--read", nargs="*", default=[], help="tickers to write a read for"
    )
    parser.add_argument(
        "--read-book",
        action="store_true",
        help="write a read for every name in today's book",
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
        "--rebalance-now",
        action="store_true",
        help="rebalance the paper book to tonight's targets whatever the clock "
        "says, and restart the clock (the operator's one-time move)",
    )
    parser.add_argument(
        "--prune-days",
        type=int,
        default=0,
        help="drop bar and filing partitions older than this many days (0 keeps all)",
    )
    return parser


# The tickers the desk needs daily bars for: the book, the displayed
# benchmarks, the macro series.
def bar_tickers() -> tuple[str, ...]:
    """Return the tickers the daily refresh pulls bars for."""
    names = tuple(sorted(book_sides(build_universe())))
    return names + tuple(MARKET_INDICES) + tuple(SERIES.values())


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


# Ask the broker what became of the orders written down last session, and
# fold the answer back into the state.
#
# Orders are looked up by the id chosen before they were sent, not by
# comparing positions: a position moves for reasons that have nothing to
# do with this desk, so it cannot say whether this desk's order filled.
def _reconcile(client, state, store_root: Path, live: bool):
    """Return (state after settlement, what settled)."""
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    if not state.pending:
        return state, []
    since = min(str(row.get("session") or "") for row in state.pending)
    try:
        broker = client.orders_since(f"{since}T00:00:00Z")
    except alpaca_trading.AlpacaTradingError as exc:
        print(f"  could not read the broker's orders: {exc}")
        return state, []
    settled = paper.settle(state.pending, broker)
    if settled:
        counts: dict[str, int] = {}
        for row in settled:
            counts[row.status] = counts.get(row.status, 0) + 1
        print(
            "  last session's orders: "
            + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()))
        )
        for row in settled:
            if row.status not in ("filled", "open"):
                print(
                    f"    {row.side:4} {row.qty:5d} {row.symbol:6} "
                    f"{row.status} ({row.filled_qty} filled)"
                )
    updated = paper.apply_settlements(state, settled)
    if updated.last_rebalance != state.last_rebalance:
        print(
            "  the last rebalance did not fill; the clock is put back so the "
            "next session plans it again"
        )
    if live:
        paper.save_state(store_root, updated)
    return updated, settled


# The settled orders as record rows, each with its fill price and what the
# closing auction of the fill session would have paid instead. An order
# planned on session s fills at the open of the next session on the panel,
# so that session's close is the counterfactual.
def _settled_rows(settled, panel) -> list[dict]:
    from backend.agents.trading.desk import paper

    rows = []
    for s in settled:
        close = float("nan")
        planned = np.datetime64(s.session) if s.session else None
        if planned is not None and s.symbol in panel.tickers:
            later = np.flatnonzero(panel.dates > planned)
            if len(later):
                close = float(panel.close[later[0], panel.index(s.symbol)])
        rows.append(
            {
                "symbol": s.symbol,
                "side": s.side,
                "qty": s.qty,
                "status": s.status,
                "filled": s.filled_qty,
                "filled_price": s.filled_price,
                "close_shortfall_bps": paper.close_shortfall_bps(
                    s.side, s.filled_price, close
                ),
            }
        )
    return rows


# Send the plan: each order as a day order queued for the next open, and
# what the broker said. Orders are day orders (see
# `alpaca_trading.submit_market_on_open`), so submitting while the market
# is open would fill them now, at whatever price, which is not the trade
# that was measured. The nightly run is after the close; a run by hand
# during the session is refused whole and told why.
def _submit(client, orders, session: str, live: bool) -> tuple[list[dict], list[str]]:
    """Return (submitted rows, refusals) after sending `orders` when `live`."""
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    submitted: list[dict] = []
    refused: list[str] = []
    market_open = False
    clock_known = False
    if live and orders:
        try:
            market_open = bool(client.clock().get("is_open"))
            clock_known = True
        except alpaca_trading.AlpacaTradingError as exc:
            print(f"  clock unavailable ({exc}); refusing to submit")
    for order in orders:
        line = f"  {order.side:4} {order.qty:5d} {order.symbol:6} {order.reason}"
        if not live:
            print(line + "  [dry run]")
            continue
        if not clock_known:
            # Fail closed: without the clock the desk cannot know whether a
            # market-on-open order would fill now instead of at the next
            # open, so nothing is submitted on a guess.
            refused.append(
                f"{order.side} {order.symbol}: the market clock is unavailable; "
                "refusing to queue orders for the next open"
            )
            print(line + "  REFUSED: market clock unavailable")
            continue
        if market_open:
            refused.append(
                f"{order.side} {order.symbol}: the market is open; "
                "orders are queued for the next open after the close"
            )
            print(line + "  REFUSED: the market is open")
            continue
        try:
            client.submit_market_on_open(
                order.symbol,
                order.qty,
                order.side,
                order.client_order_id
                or paper.order_id(session, order.symbol, order.side),
            )
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
            refused.append(f"{order.side} {order.symbol}: {exc}")
            print(line + f"  REFUSED: {exc}")
    return submitted, refused


# Which open orders belong to this desk, matched by the client order id
# prefix the desk chose for its own submissions. A person's own orders on
# the same account must never be withdrawn by the desk's cancel.
def _desk_open_order_ids(open_orders: list[dict]) -> list[str]:
    """Return the client order ids of the desk's own open orders."""
    return [
        str(o.get("client_order_id") or "")
        for o in open_orders
        if str(o.get("client_order_id") or "").startswith("anios-")
    ]


# Which names the desk will not buy or add to tonight: a daily rejecting
# its upper Bollinger band, read with the exit analyst's own signal (a
# bearish candle at the band, or price in the upper fifth of a wide band)
# at the planning session's close. A name in the set is held or trimmed
# but never bought, whatever its grade says. Measured on the book since
# 2015 this narrow blocker beat the ungated book on return, Sharpe and
# drawdown, where requiring a full dip-or-breakout trigger starved it.
def _band_blocked(report) -> tuple[set[str], dict[str, bool]]:
    """Return (blocked, {ticker: rejecting-the-band}) for the last session."""
    from backend.agents.trading.desk import exit as exit_analyst

    panel = report.panel
    last = len(panel.dates) - 1
    signal = exit_analyst.evidence(panel).signalled()
    blocked: set[str] = set()
    flags: dict[str, bool] = {}
    for column, ticker in enumerate(panel.tickers):
        flag = bool(signal[last, column])
        flags[ticker] = flag
        if flag:
            blocked.add(ticker)
    return blocked, flags


# Carry the desk's book to the paper account: cancel yesterday's unfilled
# orders, plan this session, submit the plan for the next open, then record
# the account. Returns the day's entry for the desk record.
def paper_trade(
    report, store_root: Path, session: str, live: bool, rebalance_now: bool = False
) -> dict:
    """Plan and (when `live`) submit the paper book; return the day's entry."""
    from backend.agents.trading.desk import actions, paper
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
    # What became of the last session's orders, before planning this one.
    # An accepted order is not a filled one, and a rebalance whose orders
    # did not fill has not happened - so this runs first and can put the
    # clock back before the plan is made.
    state, settled = _reconcile(client, state, store_root, live)
    # Nothing is passed for `finished`: the band exit that used to fill it
    # was measured inside the book's own rules and cost 3.0% a year. See
    # the note at the top of `desk/exit.py`.
    blocked, blocking_flags = _band_blocked(report)
    orders, new_state, what = paper.plan(
        session,
        state,
        account.equity,
        held,
        prices,
        targets,
        grades,
        force_rebalance=rebalance_now,
        entry_blocked=blocked,
    )
    print(
        f"\npaper book ({what}{', forced tonight' if rebalance_now else ''}), "
        f"equity {account.equity:,.0f}:"
    )
    held_back = sum(1 for o in orders if o.side == "buy" and o.symbol in blocked)
    if held_back:
        print(
            f"  {held_back} buy orders held back: "
            "the daily is rejecting its upper Bollinger band"
        )
    else:
        print(
            f"  buys blocked where the daily rejects its upper Bollinger band "
            f"({len(blocked)} names rejecting tonight)"
        )
    # The plan is written down before a single order is sent, with the id
    # each one will carry. A crash between sending and recording then
    # leaves a record the next session can ask the broker about, rather
    # than a gap that has to be guessed at from positions.
    if live and orders:
        new_state.pending = [
            {
                "client_order_id": o.client_order_id
                or paper.order_id(session, o.symbol, o.side),
                "symbol": o.symbol,
                "side": o.side,
                "qty": int(o.qty),
                "session": session,
                "reason": o.reason,
            }
            for o in orders
        ]
        if what == "rebalance":
            new_state.unconfirmed_rebalance = session
        paper.save_state(store_root, new_state)
        # Withdraw only what this desk wrote down and is still open; a broad
        # cancel would also withdraw an order the person placed by hand.
        desk_open = _desk_open_order_ids(client.open_orders())
        if desk_open:
            client.cancel_orders(desk_open)
    submitted, refused = _submit(client, orders, session, live)
    if not orders:
        print("  nothing to do")
    # A rebalance the broker would not take is not a rebalance. The clock
    # used to advance anyway, because the state was saved whatever the
    # broker said, so a session where every order bounced put the book
    # twenty sessions away from its next attempt at the targets it had
    # just failed to reach. The session is still recorded as seen, so
    # nothing is submitted twice; only the rebalance clock is rolled back,
    # and the next session plans the rebalance again.
    if refused and what == "rebalance":
        new_state.last_rebalance = state.last_rebalance
        new_state.sessions_since_rebalance = state.sessions_since_rebalance
        print(
            f"  {len(refused)} of {len(orders)} orders refused: the rebalance "
            f"clock is not advanced, so the next session tries again"
        )
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
    entry["refused"] = refused
    entry["plan"] = what
    entry["settled"] = _settled_rows(settled, panel)
    entry["until_rebalance"] = max(
        actions.REBALANCE - int(new_state.sessions_since_rebalance), 0
    )
    holdings = {
        p["symbol"]: actions.Holding(
            weight=float(p["market_value"]) / account.equity if account.equity else 0.0,
            entry_price=float(p["avg_entry_price"]) if p["avg_entry_price"] else None,
        )
        for p in positions
    }
    entry["actions"] = actions.build(
        report,
        targets,
        holdings,
        int(new_state.sessions_since_rebalance),
        {o.symbol: o.reason for o in orders},
    )
    # The band-rejection flag each action row decided on, so the record and
    # the board can show which names the desk refused to buy tonight.
    for row in entry["actions"]:
        row["rejecting_band"] = blocking_flags.get(row.get("ticker"), False)
    if live:
        paper.save_state(store_root, new_state)
    print(
        f"  equity {entry['equity']:,.0f}, P/L since the start "
        f"{entry['pl']:+,.0f} ({entry['pl_pct'] * 100:+.1f}%)"
    )
    return entry


# The day's record, as plain data.
# The shadow's block for tonight, or None when there is none: the live
# desk carries its alternate (the plain rule when the gap is live), and a
# live desk that fell back to the plain rule has no shadow to write.
def _challenger_block(store, report) -> dict | None:
    from backend.market import challenger

    shadow = getattr(report, "alternate", None)
    if shadow is None:
        print("\nchallenger: none (the live desk ran without its promoted input)")
        return None
    block = challenger.record_block(shadow)
    print(f"\nchallenger ({block['name']}): {len(block['book'])} names")
    for row in block["book"]:
        print(f"  {row['ticker']:6} {row['grade']:2} {row['weight']:.3f}")
    return block


def _strategy_name(report) -> str:
    from backend.market import challenger

    return challenger.strategy(report)


def record(
    report,
    briefs: dict[str, dict] | None = None,
    reads: dict[str, str | None] | None = None,
    paper: dict | None = None,
    challenger: dict | None = None,
    curve: dict | None = None,
    llm_model: str | None = None,
) -> dict:
    """Return the JSON-ready record of a DeskReport."""
    panel = report.panel
    last = len(panel.dates) - 1
    state = report.regime.today()
    grades = {}
    _, blocking_flags = _band_blocked(report)
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
            # The read is the model's plain-language version of the whole
            # evidence, written once a night for the names asked. The
            # deterministic lines below are only the fallback when the
            # runtime was away, so a missing read still answers "why".
            "read": (reads or {}).get(ticker),
            "reads": plainly.reads(view, scale),
            # Each analyst's rating: the name's rank across the book on that
            # analyst's evidence, 0 to 1, so the page can show the parts.
            "ranks": {
                k: round(float(v), 3)
                for k, v in (view.get("ranks") or {}).items()
                if v == v
            },
        }
    return {
        "session": str(panel.dates[last]),
        "written": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        # What produced this record, so a reported return can be traced to
        # the decision, code and data that made it: the checkout's revision,
        # the data window, the strategy's cadence and the model that wrote
        # the briefs and reads.
        "provenance": {
            "code_revision": _git_revision(),
            # The strategy the live book is, by name, so the scorecard can
            # price each strategy across the day its role changed.
            "rule": {
                "name": _strategy_name(report),
                "inputs": list(getattr(report, "inputs", ()) or ()),
            },
            "data": {
                "first_session": str(panel.dates[0]),
                "session": str(panel.dates[last]),
                "names": len(panel.tickers) - 1,
                "benchmark": panel.benchmark,
            },
            "strategy": {"rebalance_every": actions.REBALANCE},
            "model": llm_model or None,
        },
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
        # The track record the page draws: the rules walked forward against
        # SPY and QQQ, and the paper account's live equity since it started.
        # Absent on records written before this existed.
        "curve": curve,
        # The shadow desk, when one ran tonight: its book and grades, never
        # traded, priced forward by the scorecard beside the rule's.
        "challenger": challenger,
        # Levels for every book name, targeted or not, so the person's own
        # board can size a name the desk holds nothing of.
        "levels": {
            row["ticker"]: {
                k: row[k]
                for k in ("last_close", "high_20", "stops", "grade_margin", "rank")
            }
            | {"rejecting_band": blocking_flags.get(row["ticker"], False)}
            for row in actions.build(
                report,
                {t: 0.0 for t in report.sides},
                {},
                (
                    actions.REBALANCE
                    - int(paper.get("until_rebalance", actions.REBALANCE))
                    if paper
                    else 0
                ),
            )
        },
        "actions": (
            paper.get("actions")
            if paper and paper.get("actions") is not None
            else [
                {**row, "rejecting_band": blocking_flags.get(row.get("ticker"), False)}
                for row in actions.build(
                    report, {s.position.ticker: s.weight for s in report.book}, {}, 0
                )
            ]
        ),
    }


# Where the day's record lives.
def record_path(root: Path, session: str) -> Path:
    """Return the path of the desk record for a session."""
    return Path(root) / DESK_KIND / f"asof={session}" / "desk.json"


# Whether the day is already decided: a record for the session exists and the
# run is not deliberately rewriting it. Called before any brief, read, or
# trade, so a same-session rerun places no orders and persists no pending
# state it would then be told to keep.
def refuse_existing_record(root: Path, session: str, force: bool = False) -> bool:
    """Return True, having said so, when the session's record already exists."""
    if force:
        return False
    path = record_path(root, session)
    if not path.exists():
        return False
    print(f"\na record for {session} already exists at {path}")
    print("refusing to re-run the day (pass --force to rewrite); nothing was changed")
    return True


# The checkout's revision, so a record says exactly which code produced it;
# "unknown" when the revision cannot be read (no git, or not a checkout).
def _git_revision() -> str:
    try:
        import subprocess

        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        rev = out.stdout.strip()
        return rev or "unknown"
    except Exception:  # noqa: BLE001 - a record must never fail on this
        return "unknown"


# Write the record and return its path.
#
# The record is the day's decision, immutable: a second run for the same
# session must not silently replace it, or the track record no longer says
# what was decided. An existing record is refused unless the caller says
# it is deliberately rewriting it (`allow_overwrite`), and every record
# carries the revision and settings that produced it so a reported return
# can be traced back to the decision that made it.
def save(root: Path, data: dict, allow_overwrite: bool = False) -> Path:
    """Write the day's record as JSON, refusing to clobber an existing one."""
    path = record_path(root, data["session"])
    if path.exists() and not allow_overwrite:
        raise FileExistsError(
            f"a record for {data['session']} already exists at {path}; "
            "refusing to overwrite it (pass --force to rewrite)"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, default=float), encoding="utf-8")
    return path


# The track record as a curve: the desk's own rules walked forward against
# SPY and QQQ, with the headline numbers. Computed once at record time so
# the page shows what the rules actually earned without running the desk
# again (the backend serving the page has no torch).
def curve_block(report, store) -> dict | None:
    """Return the backtest curve block, or None when it cannot be drawn."""
    from backend.agents.trading.desk import scorecard, simulate

    panel = report.panel
    try:
        sim = simulate.run(report, use_exits=False)
    except Exception:
        return None
    if len(sim.dates) < 2 or sim.equity is None or not np.isfinite(sim.equity[0]):
        return None
    start = int(np.searchsorted(panel.dates, sim.dates[0]))
    dates = [str(d) for d in sim.dates]
    equity = np.asarray(sim.equity, dtype=float)
    base = equity[0] if equity[0] > 0 else 1.0
    rules = [float(e / base - 1.0) for e in equity]
    with np.errstate(all="ignore"):
        simple = np.expm1(panel.log_returns())
    bench = panel.index(panel.benchmark)
    # The strategy is first invested at the close of `sim.dates[0]`, so its
    # first return is the period from that close to the next; the benchmark
    # must start there too, or it earns the return into the base date the
    # strategy never held (the leading NaN pad only hides this when the sim
    # happens to start at the panel's first row). Both curves are normalised
    # to 0 at the same base date as the rules.
    spy = simple[start + 1 : start + len(dates), bench]
    spy = np.nan_to_num(spy, nan=0.0)
    spy_curve = [0.0] + [float(v - 1.0) for v in np.cumprod(1.0 + spy)]
    qqq = scorecard.index_returns(store, "QQQ", sim.dates)
    if qqq is not None and len(qqq) and np.isfinite(qqq).any():
        # The curve stays aligned to `dates`: a wholly missing series must
        # not render as a flat 0% line, so it is dropped instead.
        qqq_curve = [
            float(v - 1.0) for v in np.cumprod(1.0 + np.nan_to_num(qqq, nan=0.0))
        ]
    else:
        qqq_curve = []
    stats = sim.stats()
    return {
        "label": "these rules run over the history: a backtest, not a record",
        "asof": str(panel.dates[-1]),
        "dates": dates,
        "rules": rules,
        "spy": spy_curve,
        "qqq": qqq_curve,
        "stats": {k: (None if v != v else float(v)) for k, v in stats.items()},
    }


# The paper account's live equity history, for the same chart: the only
# genuinely out-of-sample sample the desk has.
def paper_curve_block(root: Path) -> dict | None:
    """Return the paper account's equity history, or None before it has any."""
    from backend.agents.trading.desk import paper

    state = paper.load_state(root)
    history = [h for h in state.history if h.get("equity") is not None]
    if not history:
        return None
    return {
        "label": "paper account (live)",
        "sessions": [str(h.get("session")) for h in history],
        "equity": [float(h.get("equity")) for h in history],
        "pl_pct": [float(h.get("pl_pct") or 0.0) for h in history],
    }


# Both curves for the record, each guarded: the record must be written
# whatever the chart could not draw, so a failure here is a missing
# block and a line in the log, never a lost record.
def curves(report, store, root: Path) -> dict:
    """Return {"backtest": block or None, "paper": block or None}."""
    backtest = None
    paper_curve = None
    try:
        backtest = curve_block(report, store)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(f"\ncurve: the backtest could not be drawn ({type(exc).__name__}: {exc})")
    try:
        paper_curve = paper_curve_block(root)
    except Exception as exc:  # noqa: BLE001 - reported, never fatal
        print(
            f"\ncurve: the paper history could not be read "
            f"({type(exc).__name__}: {exc})"
        )
    return {"backtest": backtest, "paper": paper_curve}


# One session of a name's history, as JSON-safe plain data.
def _history_row(row) -> dict:
    """Return a JSON-safe row from a desk HistoryRow."""
    forward = float(row.forward)
    residual = float(row.forward_residual)
    return {
        "date": str(row.date),
        "grade": row.grade,
        "votes": float(row.votes),
        "stances": {k: int(v) for k, v in row.stances.items()},
        "exposure": float(row.exposure),
        "confidence": float(row.confidence),
        "forward": None if forward != forward else round(forward, 6),
        "forward_residual": None if residual != residual else round(residual, 6),
        "earnings": bool(row.earnings),
    }


# A name's backtest, as JSON-safe plain data.
def _backtest_dict(bt) -> dict:
    """Return a JSON-safe NameBacktest."""

    def num(value):
        value = float(value)
        return None if value != value else round(value, 6)

    return {
        "ticker": bt.ticker,
        "min_grade": bt.min_grade,
        "sessions": int(bt.sessions),
        "sessions_in": int(bt.sessions_in),
        "switches": int(bt.switches),
        "rule_return": num(bt.rule_return),
        "hold_return": num(bt.hold_return),
        "benchmark_return": num(bt.benchmark_return),
        "in_annualised": num(bt.in_annualised),
        "out_annualised": num(bt.out_annualised),
    }


# One history file per book name, so the drill-down reads a single name's
# file rather than rebuilding the whole desk to answer one question.
def write_history(store, report, horizon: int = 20) -> int:
    """Write the per-name history files; return how many were written."""
    base = Path(store.root) / "history"
    base.mkdir(parents=True, exist_ok=True)
    count = 0
    for ticker in sorted(report.sides):
        rows = trading_desk.history(report, ticker, horizon)
        backtest = trading_desk.name_backtest(report, ticker)
        payload = {
            "ticker": ticker,
            "asof": str(report.panel.dates[-1]),
            "horizon": horizon,
            "rows": [_history_row(r) for r in rows],
            "backtest": _backtest_dict(backtest),
        }
        (base / f"{ticker}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8"
        )
        count += 1
    return count


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


# Write and print the reads for some names through the local model. A read
# is the whole desk's evidence in plain words, so the page can show every
# trigger without the model at the edge omitting or inventing one.
def reads_for(report, tickers, narrator: DeskNarrator) -> dict[str, str | None]:
    """Return {ticker: read text} for the names the model could read."""
    out: dict[str, str | None] = {}
    for ticker in tickers:
        if ticker not in report.panel.tickers:
            print(f"\n{ticker}: not in the book")
            continue
        read = narrator.read_sync(brief_text(report, ticker))
        if read is None:
            print(f"\n{ticker}: no read (runtime away or empty)")
            continue
        out[ticker] = read
        print(f"\n{ticker}: {read[:160]}")
    return out


# The names a step should process: the ones named, plus every name in the
# book when the whole book was asked for.
def _wanted_tickers(report, named: list[str], whole_book: bool) -> list[str]:
    """Return the tickers to process for one model-written step."""
    wanted = list(named)
    if whole_book:
        wanted += [
            s.position.ticker for s in report.book if s.position.ticker not in wanted
        ]
    return wanted


# The model-written briefs and reads the run asked for, or empty dicts when
# the runtime is away: the day still runs, just without prose.
def _wanted_briefs_and_reads(
    report, args
) -> tuple[dict[str, dict], dict[str, str | None]]:
    """Return the briefs and reads the run asked for."""
    briefs: dict[str, dict] = {}
    wanted = _wanted_tickers(report, args.brief, args.brief_book)
    read_wanted = _wanted_tickers(report, args.read, args.read_book)
    reads: dict[str, str | None] = {}
    if wanted or read_wanted:
        readers, _model = market_tone.clients(args.llm_url, args.llm_model, 1)
        narrator = DeskNarrator(readers[0].writer)
        if wanted:
            briefs = briefs_for(report, wanted, narrator)
        if read_wanted:
            reads = reads_for(report, read_wanted, narrator)
    return briefs, reads


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
    # The record is the day's decision. If it already exists and the run is
    # not deliberately rewriting it, the day has been decided. Refusing here,
    # before any brief, read, or trade, is what makes a same-session rerun
    # harmless: the old code ran paper_trade first and then refused to save,
    # having already placed orders and persisted pending state it would call
    # "nothing was changed".
    session = str(panel.dates[-1])
    if refuse_existing_record(Path(store.root), session, args.force):
        return
    briefs, reads = _wanted_briefs_and_reads(report, args)
    entry = None
    if args.paper_trade or args.paper_dry_run:
        try:
            entry = paper_trade(
                report,
                Path(store.root),
                session,
                live=args.paper_trade,
                rebalance_now=args.rebalance_now,
            )
        except Exception as exc:  # the account being away must not lose the record
            print(f"\npaper book: not traded ({type(exc).__name__}: {exc})")
    shadow = None
    if args.challenger:
        shadow = _challenger_block(store, report)
    curve = curves(report, store, Path(store.root))
    try:
        path = save(
            Path(store.root),
            record(
                report,
                briefs,
                reads,
                entry,
                shadow,
                curve,
                llm_model=args.llm_model,
            ),
            allow_overwrite=args.force,
        )
    except FileExistsError as exc:
        print(f"\n{exc}")
        print("the existing record is kept; nothing was changed")
        return
    print(f"\nrecord written: {path}")
    written = write_history(store, report)
    if written:
        print(f"history: {written} names written")
    removed = prune(Path(store.root), asof, args.prune_days)
    if removed:
        print(f"pruned {len(removed)} old partitions")


if __name__ == "__main__":
    main()
