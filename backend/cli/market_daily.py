"""The desk's day: refresh the data, run the desk, write the record.

    python -m backend.cli.market_daily --refresh            # data, then the desk
    python -m backend.cli.market_daily                      # the desk on stored data
    python -m backend.cli.market_daily --refresh --brief SNDK CRWV

`--refresh` pulls daily bars for all tracked stocks, benchmarks and the
macro series, EDGAR events and facts for all tracked stocks, and scores any
book release not yet scored (only the new ones: earlier scores carry forward).
Then the desk runs and prints the regime, the grades and the book, and the
whole record is written to `data/market/desk/asof=DATE/desk.json` so a day
can be read back later exactly as it was seen.
"""

import argparse
import json
import shutil
import time
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import actions, plainly
from backend.agents.trading.desk import desk as trading_desk
from backend.agents.trading.desk.narrative import brief_text
from backend.cli import market_edgar, market_tone
from backend.cli.market_desk import _print_book, _print_grades, _print_regime
from backend.config.settings import settings
from backend.market import deskrecord, prose, snapshot, tone_revisions
from backend.market.macro import SERIES
from backend.market.store import MarketStore
from backend.market.universe import (
    FOCUS,
    MARKET_INDICES,
    MEMBER,
    book_sides,
    build_universe,
    tickers_with_role,
)

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
        "--prose-budget-minutes",
        type=float,
        default=45.0,
        help="wall-clock limit for the model-written briefs and reads, after "
        "the record is saved; at the limit the request in flight is terminated, "
        "what was written is kept and the block says it timed out",
    )
    parser.add_argument(
        "--tone-budget-minutes",
        type=float,
        default=180.0,
        help="stop scoring releases after this long; unscored names carry "
        "their earlier scores (0 for no budget)",
    )
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


# Keep the entire research universe current, plus benchmarks and macro series.
def bar_tickers() -> tuple[str, ...]:
    """Return the tickers the daily refresh pulls bars for."""
    names = research_tickers()
    return names + tuple(MARKET_INDICES) + tuple(SERIES.values())


# The book names, for the filings and the releases.
def book_tickers() -> tuple[str, ...]:
    """Return the book's tickers."""
    return tuple(sorted(book_sides(build_universe())))


# Collect evidence systematically for all stock members, not just the themed book.
def research_tickers() -> tuple[str, ...]:
    return tuple(sorted(tickers_with_role(build_universe(), FOCUS, MEMBER)))


# Refresh every layer the desk reads, in the order it needs them.
#
# `after_filings(report)` runs once bars and filings are on disk and before
# the release-tone scoring. The frozen ML observer goes there: it reads
# prices and filings only, and the tone step runs a model over every new
# release for hours, so an observer placed after it saw the session's
# date roll past midnight and refused, correctly, to backdate.
def refresh(
    store: MarketStore,
    asof: date,
    *,
    skip_tone: bool = False,
    llm_url: str = "",
    llm_model: str = "",
    concurrency: int = 4,
    tone_budget_minutes: float = 0.0,
    bars=snapshot.refresh,
    filings=market_edgar.refresh,
    tone=market_tone.refresh_tickers,
    after_filings=None,
    versions=None,
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
    filing_failures = filings(store, research_tickers(), asof) or ()
    _refresh_versions(store, asof, versions)
    if after_filings is not None:
        after_filings(report, filing_failures)
    if skip_tone:
        print("tone: skipped")
        return
    # Tone is scored for the book only. A release is fetched from EDGAR one
    # at a time under SEC pacing and read by the model, minutes per name; on
    # the 531-name research universe a rescoring ran past the next session
    # and the desk wrote no record. Breadth tone is a research refresh
    # (`market_tone --refresh --roles`), not the nightly's critical path.
    deadline = (
        time.monotonic() + 60.0 * tone_budget_minutes if tone_budget_minutes else None
    )
    try:
        scored = tone(
            store,
            book_tickers(),
            asof,
            llm_url=llm_url,
            llm_model=llm_model,
            concurrency=concurrency,
            deadline=deadline,
        )
    except Exception as exc:  # the runtime being away must not stop the desk
        print(f"tone: not scored ({type(exc).__name__}: {exc}); earlier scores carry")
        return
    print(f"tone: {scored} new releases scored")


# Every filed version of the book's facts, for the as-of comparison the
# record carries (`fundamentals_shadow`). A failure here is named and never
# stops the desk: the comparison is evidence, not an input to the book.
def _refresh_versions(store: MarketStore, asof: date, versions=None) -> list[str]:
    if versions is None:
        from backend.cli.market_fundamentals_asof import refresh as versions

    try:
        failed = list(versions(store, book_tickers(), asof) or ())
    except Exception as exc:  # noqa: BLE001 - the desk runs on what is stored
        print(f"filing versions: not refreshed ({type(exc).__name__}: {exc})")
        return []
    print(
        f"filing versions: {len(failed)} failed"
        + (" (" + ", ".join(failed) + ")" if failed else "")
    )
    return failed


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
    known = {row.get("client_order_id") for row in broker}
    # An event order the broker acknowledged (its execution carries the
    # broker's own timestamps) but no longer lists is an unknown outcome:
    # keep the intent. One the broker never acknowledged never traded, and
    # settles as missing like any other, or the pending list would block
    # every later plan forever.
    unknown = [
        row["client_order_id"]
        for row in state.pending
        if row.get("event_id")
        and row["client_order_id"] not in known
        and _acknowledged(row)
    ]
    if unknown:
        print(
            "  FOMC order outcome unknown; preserving intent for idempotent "
            f"recovery ({', '.join(unknown)})"
        )
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


# Whether the broker ever acknowledged a pending order: its execution block
# carries the broker's own timestamps only after a successful submission.
def _acknowledged(row: dict) -> bool:
    """Return True when the broker's acknowledgment was recorded for the row."""
    execution = row.get("execution") or {}
    return any(execution.get(k) for k in ("created_at", "submitted_at", "filled_at"))


# The pending desk orders withdrawn before a new plan is sent: every row
# from another session, and on a forced rerun this session's rows too, or
# the same delta goes on the market twice while the first batch still works.
def _ids_to_withdraw(state, session: str, force: bool = False) -> list[str]:
    """Return the client order ids the plan must cancel before it is sent."""
    return [
        row["client_order_id"]
        for row in state.pending
        if force or row.get("session") != session
    ]


# Compare aggregate fills with the broker's actual completion-session close.
def _settled_rows(settled, panel) -> list[dict]:
    from backend.agents.trading.desk import execution_evidence, paper

    rows = []
    for s in settled:
        close = float("nan")
        completed = execution_evidence.completion_session(s.execution)
        if completed is not None and s.symbol in panel.tickers:
            matched = np.flatnonzero(panel.dates == np.datetime64(completed))
            if len(matched):
                close = float(panel.close[matched[0], panel.index(s.symbol)])
        rows.append(
            {
                "symbol": s.symbol,
                "side": s.side,
                "qty": s.qty,
                "status": s.status,
                "terminal": s.terminal,
                "filled": s.filled_qty,
                "filled_price": s.filled_price,
                "client_order_id": s.client_order_id,
                "execution": s.execution,
                "completion_session": completed,
                "decision_shortfall_bps": execution_evidence.decision_shortfall_bps(
                    s.side, s.filled_price, s.execution.get("reference_price")
                ),
                "close_shortfall_bps": paper.close_shortfall_bps(
                    s.side, s.filled_price, close
                ),
            }
        )
    return rows


# Send the plan: buys as day orders queued for the next open, sells as
# market-on-close orders queued for the next session's closing auction, and
# what the broker said. Queued orders can fill late or fail; their actual
# outcomes and timestamps are recorded separately by reconciliation.
# The market-on-close sell can be cancelled up to the close, which the
# intraday green-day rule does for names trading up at the open.
# Submitting while the market is open would fill a day order now, at
# whatever price, which is not the trade that was measured. Explicit intraday
# recovery permits only event sells; all ordinary orders keep the nightly guard.
# Funded allocation orders and mandatory risk cuts retain their measured next-open
# execution, rather than inheriting the legacy closing-auction sell policy.
# The nightly run
# is after the close; a run by hand during the session is refused whole and
# told why.
def _submit(
    client, orders, session: str, live: bool, *, intraday_event_reduction=False
) -> tuple[list[dict], list[str]]:
    """Return (submitted rows, refusals) after sending `orders` when `live`."""
    from backend.agents.trading.desk import execution_evidence, paper
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
        if intraday_event_reduction and (
            not market_open or order.side != "sell" or not order.event_id
        ):
            refused.append(
                f"{order.symbol}: catch-up requires event sells in the regular session"
            )
            continue
        if market_open and not intraday_event_reduction:
            refused.append(
                f"{order.side} {order.symbol}: the market is open; "
                "orders are queued for the next open after the close"
            )
            print(line + "  REFUSED: the market is open")
            continue
        try:
            if (
                order.side == "sell"
                and not order.event_id
                and not order.priority
                and order.execution_timing != "next_open"
            ):
                response = client.submit_market_on_close(
                    order.symbol,
                    order.qty,
                    order.side,
                    order.client_order_id
                    or paper.order_id(session, order.symbol, order.side),
                )
            else:
                response = client.submit_market_on_open(
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
                    "client_order_id": order.client_order_id
                    or paper.order_id(session, order.symbol, order.side),
                    "execution": execution_evidence.broker_evidence(response),
                }
            )
            print(line)
        except alpaca_trading.AlpacaTradingError as exc:
            refused.append(f"{order.side} {order.symbol}: {exc}")
            print(line + f"  REFUSED: {exc}")
    return submitted, refused


# Preserve execution policy and reference evidence before an order can be sent.
def _pending_orders(orders, session, prices, reference_session):
    from backend.agents.trading.desk import paper

    decision_at = datetime.now(tz=UTC).isoformat()
    return [
        {
            "client_order_id": order.client_order_id
            or paper.order_id(session, order.symbol, order.side),
            "symbol": order.symbol,
            "side": order.side,
            "qty": int(order.qty),
            "session": session,
            "reason": order.reason,
            "event_id": order.event_id,
            "priority": order.priority,
            "execution_timing": order.execution_timing,
            "execution": {
                "decision_at": decision_at,
                "reference_price": prices.get(order.symbol),
                "reference_session": str(reference_session),
                "reference_source": "daily panel close",
            },
        }
        for order in orders
    ]


# Save broker acknowledgments without treating accepted orders as confirmed fills.
def _remember_acknowledgments(state, submitted, root, live, orders):
    from backend.agents.trading.desk import paper

    if not live or not orders:
        return
    acknowledged = {row["client_order_id"]: row["execution"] for row in submitted}
    for row in state.pending:
        row["execution"] = {
            **row.get("execution", {}),
            **acknowledged.get(row["client_order_id"], {}),
        }
    paper.save_state(root, state)


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
def _downgraded(report, held: dict[str, float]) -> dict[str, str]:
    """Return {ticker: reason} for held names the desk no longer grades A.

    The desk holds a name while it grades A or better and rotates out when it
    does not. Measured over twelve start phases at this reset, against holding
    to the next weight reset: the same return, a better Sharpe and a 7.3 point
    shallower drawdown. The advantage is a function of how long the book holds
    - and it is largest at a SHORT reset, not a long one: +3.42 points of CAGR
    at a 20-session reset against -8.32 at 120, positive in twelve of fourteen
    start phases at 20 and none of fourteen at 120. The docstring here claimed
    the opposite for a day. At a long reset the rotation sells into a name the
    calendar was going to re-select anyway, so it earns its keep there as a
    de-risking device rather than a return one.
    """
    from backend.agents.trading.desk import paper as paper_rules

    letters = report.graded.grades
    last = len(report.panel.dates) - 1
    out: dict[str, str] = {}
    for column, ticker in enumerate(report.panel.tickers):
        if ticker == report.panel.benchmark or not held.get(ticker):
            continue
        grade = letters[last, column]
        letter = grade if isinstance(grade, str) else _GRADE_LETTER.get(int(grade))
        if letter not in paper_rules.ENTRY_MIN_GRADE:
            out[ticker] = f"graded {letter}; the desk wants the money elsewhere"
    return out


def _price_entries(report) -> dict[str, float]:
    """Return {ticker: band position} for tonight's mid-cycle entry candidates.

    A name the desk grades A or better trading above `ENTRY_BAND_Z` on its own
    20-day band. The band replaced a distance from the 21-day average, which
    fired only after a name had already run 43% and so confirmed moves rather
    than finding them; the evidence and the harness figures are at the top of
    `desk/paper.py`. `entry.bollinger_z` is the same function the live read
    uses, so the page and the book cannot disagree about where the band is.
    """
    from backend.agents.trading.desk import entry as entry_analyst
    from backend.agents.trading.desk import paper as paper_rules

    panel = report.panel
    last = len(panel.dates) - 1
    close = panel.adj_close
    band = entry_analyst.bollinger_z(close)[last]
    letters = report.graded.grades
    out: dict[str, float] = {}
    for column, ticker in enumerate(panel.tickers):
        if ticker == panel.benchmark:
            continue
        value = float(band[column])
        if not np.isfinite(value) or value < paper_rules.ENTRY_BAND_Z:
            continue
        grade = letters[last, column]
        letter = grade if isinstance(grade, str) else _GRADE_LETTER.get(int(grade))
        if letter in paper_rules.ENTRY_MIN_GRADE:
            out[ticker] = value
    return out


# The ordinal the grader stores, back to the letter the paper rules name.
_GRADE_LETTER = {3: "A+", 2: "A", 1: "B", 0: "C"}


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
    report,
    store_root: Path,
    session: str,
    live: bool,
    rebalance_now: bool = False,
    force: bool = False,
) -> dict:
    from backend.agents.trading.desk import paper

    if not live:
        return _paper_trade(report, store_root, session, False, rebalance_now, force)
    with paper.transaction(store_root):
        return _paper_trade(report, store_root, session, live, rebalance_now, force)


# Reconcile and execute one nightly plan while holding the shared paper-state lock.
def _paper_trade(
    report,
    store_root: Path,
    session: str,
    live: bool,
    rebalance_now: bool = False,
    force: bool = False,
) -> dict:
    """Plan and (when `live`) submit the paper book; return the day's entry."""
    from backend.agents.trading.desk import actions, event_execution, event_risk, paper
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
    policy = event_risk.decision(panel)
    # Withdraw every pending leg before replacing it, this session's included
    # (a forced rerun), and wait for confirmed outcomes. A pending cancel can
    # still fill; never overwrite its durable intent.
    stale = _ids_to_withdraw(state, session, force)
    if live and stale:
        client.cancel_orders(stale)
        state, more = _reconcile(client, state, store_root, live)
        settled.extend(more)
    account = client.account()
    held = {p.symbol: p.qty for p in client.positions()}
    # `finished` carries the names the desk has turned against, and nothing
    # else. The band exit that used to fill it cost 3.0% a year and stays
    # retired; every price-based rule measured worse than holding, because a
    # price rule sells winners in an uptrend. A grade falling is different:
    # it is the analysts saying the thesis broke, not the chart looking tired.
    #
    # It is a ROTATION, not an exit. `paper._rotation_orders` puts the money
    # into the names the desk still wants; selling the same signal to cash
    # measured 24 points of CAGR a year worse than holding. See the table at
    # the top of `desk/exit.py`.
    blocked, blocking_flags = _band_blocked(report)
    event_active = bool(state.event_cycle) or policy.get("factor") == event_risk.REDUCED
    if state.pending or event_active or not policy["calendar_known"]:
        orders, new_state, what = event_execution.plan(
            session, state, held, prices, account.cash, policy
        )
    else:
        orders, new_state, what = paper.plan(
            session,
            state,
            account.equity,
            held,
            prices,
            targets,
            grades,
            finished=_downgraded(report, held),
            force_rebalance=rebalance_now,
            entry_blocked=blocked,
            entries=_price_entries(report),
            cash=account.cash,
        )
    print(
        f"\npaper book ({what}{', forced tonight' if rebalance_now else ''}), "
        f"equity {account.equity:,.0f}:"
    )
    held_back = sum(
        1 for o in orders if o.side == "buy" and o.symbol in blocked and not o.event_id
    )
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
        new_state.pending = _pending_orders(orders, session, prices, panel.dates[last])
        if what == "rebalance":
            new_state.unconfirmed_rebalance = session
        paper.save_state(store_root, new_state)
    submitted, refused = _submit(client, orders, session, live)
    _remember_acknowledgments(new_state, submitted, store_root, live, orders)
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
    entry["event_risk"] = {
        **policy,
        "plan": what,
        "cycle": new_state.event_cycle,
        "outcome": new_state.event_outcomes[-1] if new_state.event_outcomes else None,
    }
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


# The frozen ML observer, gated on the data it needs: today's bars for
# every name in the frozen universe. A bar that failed to refresh would
# leave that name without a price at the close, and the observer must not
# read a session that is only partly there. The observer's own checks
# (the session must be today's, every forecast finite) still apply after
# this gate; nothing here backdates or relaxes them. Lives in this module
# so the shadow module, whose source is part of the experiment
# fingerprint, is untouched.
def observe_ml_forward(
    root: Path, current: bool, bar_failures=(), filing_failures=()
) -> dict | None:
    """Observe the frozen ML accounts once the required data is on disk.

    Bars are required fresh: a frozen-universe name whose bars failed to
    refresh stops the observation. Filings are point in time by filing
    date and change a few times a year, so a name whose filing refresh
    failed is observed on its last successful filing snapshot, and the
    run says so by name; a successful refresh that found no new filing
    is not a failure and is not reported. The revision the observation
    runs from is the checkout's, printed here, because the nightly runs
    from the checkout and not from the deployed container.
    """
    from backend.market import opportunity_shadow

    if not current:
        return None
    try:
        with np.load(opportunity_shadow.BUNDLE, allow_pickle=False) as saved:
            frozen = set(saved["tickers"].tolist())
    except (OSError, ValueError, KeyError) as exc:
        # A missing or unreadable bundle is the experiment's problem, not
        # the desk's: say so and write the record without an observation.
        print(f"ML forward: skipped, bundle unreadable ({type(exc).__name__}: {exc})")
        return None
    missing = sorted(frozen & set(bar_failures))
    if missing:
        print(f"ML forward: skipped, today's bars incomplete for {', '.join(missing)}")
        return None
    stale = sorted(frozen & set(filing_failures))
    if stale:
        print(
            "ML forward: filings for "
            + ", ".join(stale)
            + " did not refresh today; their last successful filing snapshot is used"
        )
    print(f"ML forward: code revision {_git_revision()} (the nightly's checkout)")
    return opportunity_shadow.observe_if_current(root, True)


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


# The registered reversal shadows, advanced on tonight's panel: evidence
# for a rule the desk does not run. Never a reason to stop.
def _reversal_shadows(store, report) -> None:
    from backend.market import reversal
    from backend.market.calendar import fomc_decisions

    try:
        panel = report.panel
        members = set(report.sides)
        reversal.write_both(Path(store.root), panel, fomc_decisions(), members)
    except Exception as exc:  # noqa: BLE001
        print(f"\nreversal shadows: not written ({type(exc).__name__}: {exc})")


# The as-of fundamentals comparison for tonight's record; a failure is
# printed and the record is written without it.
def _fundamentals_block(store, report, asof) -> dict | None:
    from backend.market import fundamentals_shadow

    try:
        return fundamentals_shadow.block(store, report, asof)
    except Exception as exc:  # noqa: BLE001 - evidence, never a reason to stop
        print(f"\nas-of fundamentals: not compared ({type(exc).__name__}: {exc})")
        return None


def _strategy_name(report) -> str:
    from backend.market import challenger

    return challenger.strategy(report)


# The fundamental analyst's block for the record: the data source it read
# and each name's cited fiscal period ends on the last session. A name with
# no fundamental opinion on the last session is omitted; a record whose
# report carries no fundamental analyst gets an empty dates map.
def _fundamental_block(report) -> dict:
    """Return {"source": ..., "dates": {ticker: {feature: end}}} for the record."""
    from backend.agents.trading.desk import fundamental

    opinion = report.opinions.get(fundamental.NAME)
    panel = report.panel
    last = len(panel.dates) - 1
    dates = {}
    if opinion is not None:
        for column, ticker in enumerate(panel.tickers):
            if ticker == panel.benchmark:
                continue
            if not np.isfinite(opinion.scores[last, column]):
                continue
            dates[ticker] = fundamental.cited_dates(opinion, last, column)
    return {
        "source": getattr(report, "fundamentals_source", "") or "",
        "dates": dates,
    }


def record(
    report,
    briefs: dict[str, dict] | None = None,
    reads: dict[str, str | None] | None = None,
    paper: dict | None = None,
    challenger: dict | None = None,
    curve: dict | None = None,
    llm_model: str | None = None,
    fundamentals: dict | None = None,
    ml_forward: dict | None = None,
    revisions: dict[str, dict] | None = None,
) -> dict:
    """Return the JSON-ready record of a DeskReport."""
    from backend.agents.trading.desk import event_risk

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
            # A release re-read under a new prompt since the last session:
            # a vote can move on it without any news, and the page says so.
            "revision": (revisions or {}).get(ticker),
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
                # Which data source the fundamental analyst read, so a figure
                # in this record is never presented under a source it was not
                # measured with. Empty on records written before this existed.
                "fundamentals": getattr(report, "fundamentals_source", "") or "",
            },
            "strategy": {
                "rebalance_every": actions.REBALANCE,
                "event_risk": event_risk.VERSION,
            },
            "model": llm_model or None,
            # What the frozen ML observer did tonight: its status, sequence
            # and session, or None when it did not observe, so a lost
            # observation is visible in the record and not only in a log.
            "ml_forward": ml_forward,
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
        "event_risk": {
            **event_risk.decision(panel),
            "outcome": ((paper or {}).get("event_risk") or {}).get("outcome"),
            "execution_pending": bool(
                ((paper or {}).get("event_risk") or {}).get("cycle")
            ),
        },
        # The track record the page draws: the rules walked forward against
        # SPY and QQQ, and the paper account's live equity since it started.
        # Absent on records written before this existed.
        "curve": curve,
        # The shadow desk, when one ran tonight: its book and grades, never
        # traded, priced forward by the scorecard beside the rule's.
        "challenger": challenger,
        # The plain rule on as-of filing versions against the frozen path:
        # which grades, scores and weights the corrected data would change
        # tonight. Evidence for switching the value analyst's input; never
        # traded. Absent before this existed or when no versions are stored.
        "fundamentals_asof": fundamentals,
        # The fundamental analyst's data source and each name's cited fiscal
        # period ends on the last session, so a corrected figure can be
        # traced to the quarter it refers to. The `fundamentals_asof` block
        # above is the value analyst's shadow and stays separate.
        "fundamental": _fundamental_block(report),
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


# Save the core record, then produce the prose beside it. The prose step
# runs under its own budget and its failure, however it fails, leaves the
# saved decision untouched and a prose block that says why.
def finish(root: Path, core: dict, enrichment, allow_overwrite: bool = False) -> Path:
    """Return the record's path, having saved it and then attempted the prose."""
    path = save(root, core, allow_overwrite=allow_overwrite)
    print(f"\nrecord written: {path}")
    enrich_prose(root, core, enrichment)
    return path


# The prose step on its own, after the decision is on disk: whatever the
# enrichment does or fails to do, the block beside the record says so, and
# every name that failed is named in the log.
def enrich_prose(root: Path, core: dict, enrichment) -> tuple[str, str]:
    """Return the prose block's (state, detail), having written it."""
    session = core["session"]
    revision = (core.get("provenance") or {}).get("code_revision", "unknown")
    started = time.monotonic()
    try:
        briefs, reads, status, failures = enrichment()
    except Exception as exc:  # noqa: BLE001 - prose never touches the decision
        briefs, reads, failures = {}, {}, []
        status = ("unavailable", f"{type(exc).__name__}: {exc}")
    elapsed = time.monotonic() - started
    landed = prose.write(root, session, revision, briefs, reads, status, elapsed)
    print(
        f"\nprose: {status[0].replace('_', ' ')}: {status[1]} ({len(briefs)} briefs, "
        f"{len(reads)} reads, {elapsed / 60:.1f} min)"
        + ("" if landed else "; the block was NOT written")
    )
    for line in failures:
        print(f"  {line}")
    return status


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
# The revision this process started from. The checkout can move under a
# running nightly (the intraday cron and a deploy both pull main), and on
# 2026-09-15 a record written by code from one revision named the next;
# what produced the record is the code that was loaded, so it is read once
# at import and not again.
_STARTED_FROM: str | None = None


def _git_revision() -> str:
    global _STARTED_FROM
    if _STARTED_FROM is None:
        _STARTED_FROM = _read_git_revision()
    return _STARTED_FROM


def _read_git_revision() -> str:
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
    from backend.agents.trading.desk import event_risk, scorecard, simulate
    from backend.agents.trading.desk import paper as paper_rules

    panel = report.panel
    try:
        # The published curve runs the live execution policy - the band
        # blocker on buys, sells at the close, the green-day hold - not the
        # bare rebalance, so what the page shows is what the account runs.
        # At the cadence the account actually runs. `simulate.run` defaults to
        # `simulate.REBALANCE` (20) and this call did not override it, so the
        # track record on the page was a different strategy from the one in
        # the book: measured across start phases, the same rules at 20 earn
        # about 38% a year at Sharpe 1.44 and at the live 120 about 29% at
        # 1.13. The page was showing the better one.
        sim = simulate.run(
            report,
            use_exits=False,
            rebalance=paper_rules.REBALANCE_EVERY,
            event_exposure=event_risk.live_path(panel),
            event_lifecycle=True,
            **simulate.LIVE_POLICY,
        )
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
        "label": "historical simulation with cash-limited fills; not a live record",
        "funding_model": simulate.FUNDING_MODEL,
        "strategy_policy": paper_rules.POLICY_VERSION,
        # The data source the simulation's analysts read, kept separate from
        # the execution policy above, so the curve is never presented as
        # measured under corrected inputs when it predates them.
        "fundamentals_source": getattr(report, "fundamentals_source", "") or "",
        "event_policy": event_risk.VERSION,
        "evaluation_periods": event_risk.evaluation_slices(sim),
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
            "fundamentals_source": getattr(report, "fundamentals_source", "") or "",
            "rows": [_history_row(r) for r in rows],
            "backtest": _backtest_dict(backtest),
        }
        (base / f"{ticker}.json").write_text(
            json.dumps(payload, indent=1), encoding="utf-8"
        )
        count += 1
    return count


# The prose job: the evidence text (and grade, for a brief) of every name
# asked for that is in the book. A name outside the book is skipped and said.
def _prose_job(report, args) -> dict:
    """Return {briefs: [...], reads: [...]} for the child process."""

    def items(names, with_grade):
        out = []
        for ticker in names:
            if ticker not in report.panel.tickers:
                print(f"\n{ticker}: not in the book")
                continue
            item = {"ticker": ticker, "text": brief_text(report, ticker)}
            if with_grade:
                item["grade"] = report.brief(ticker)["grade"]
            out.append(item)
        return out

    return {
        "briefs": items(_wanted_tickers(report, args.brief, args.brief_book), True),
        "reads": items(_wanted_tickers(report, args.read, args.read_book), False),
    }


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
# Run the day.
def main() -> None:
    """Entry point: one run at a time under the store's lock."""
    from backend.market import nightly_lock

    args = build_parser().parse_args()
    _git_revision()  # read now, before anything can move the checkout
    store = MarketStore(args.data_dir)
    lock = nightly_lock.acquire(Path(store.root) / DESK_KIND)
    if lock is None:
        raise SystemExit(75)  # EX_TEMPFAIL: cron sees a refused run, not a silent one
    try:
        _run(args, store)
    finally:
        nightly_lock.release(lock)


# The names whose release reading was re-scored since the previous session
# without a new release, printed and carried into the record; never fatal.
def _tone_revisions(store: MarketStore, report) -> dict[str, dict]:
    dates = report.panel.dates
    if len(dates) < 2:
        return {}
    try:
        session = date.fromisoformat(str(dates[-1])[:10])
        previous = date.fromisoformat(str(dates[-2])[:10])
        names = [t for t in report.panel.tickers if t != report.panel.benchmark]
        found = tone_revisions.detect(store, names, session, previous)
    except Exception as exc:  # noqa: BLE001 - reporting must not stop the record
        print(f"tone revisions: skipped ({type(exc).__name__}: {exc})")
        return {}
    if found:
        names_read = ", ".join(sorted(found))
        print(f"tone revisions: {len(found)} re-read since {previous}: {names_read}")
    else:
        print("tone revisions: none")
    return found


# The ML observer's receipt for the record, whichever way it was reached.
# The observer returns its ledger state either way, so the receipt says
# whether that state is tonight's session or an earlier one it fell back to.
def _ml_forward_receipt(row: dict | None, session: str | None = None) -> dict | None:
    if not row:
        return None
    return {
        **{k: row.get(k) for k in ("status", "sequence", "session")},
        "observed_tonight": bool(session) and row.get("session") == session,
    }


def _run(args, store: MarketStore) -> None:  # noqa: C901
    asof = args.asof or datetime.now(tz=UTC).date()
    current = args.asof is None
    observed: dict = {}
    if args.refresh:
        refresh(
            store,
            asof,
            skip_tone=args.skip_tone,
            llm_url=args.llm_url,
            llm_model=args.llm_model,
            concurrency=args.concurrency,
            tone_budget_minutes=args.tone_budget_minutes,
            after_filings=lambda report, filing_failures: observed.update(
                row=observe_ml_forward(
                    Path(store.root), current, report.failed_tickers, filing_failures
                )
            ),
        )
    else:
        observed["row"] = observe_ml_forward(Path(store.root), current)
    # The record always reads the corrected as-of filing versions. The legacy
    # frozen block is only for the read-only comparison CLI (`market_desk`),
    # never for this writer: this run writes a record and can paper-trade.
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
    entry = None
    if args.paper_trade or args.paper_dry_run:
        try:
            entry = paper_trade(
                report,
                Path(store.root),
                session,
                live=args.paper_trade,
                rebalance_now=args.rebalance_now,
                force=args.force,
            )
        except Exception as exc:  # the account being away must not lose the record
            print(f"\npaper book: not traded ({type(exc).__name__}: {exc})")
    shadow = None
    if args.challenger:
        shadow = _challenger_block(store, report)
    fundamentals = _fundamentals_block(store, report, args.asof)
    if args.paper_trade:
        from backend.market import execution_quality, fomc_gate

        fomc_gate.write(Path(store.root), store)
        execution_quality.write(Path(store.root))
    _reversal_shadows(store, report)
    curve = curves(report, store, Path(store.root))
    revisions = _tone_revisions(store, report)
    core = record(
        report,
        paper=entry,
        challenger=shadow,
        curve=curve,
        llm_model=args.llm_model,
        fundamentals=fundamentals,
        ml_forward=_ml_forward_receipt(observed.get("row"), session),
        revisions=revisions,
    )

    # The prose, after the record: model-written briefs and reads under one
    # total budget, stored beside the decision and never inside it.
    def enrichment():
        return prose.run_with_deadline(
            _prose_job(report, args),
            deskrecord.folder(Path(store.root), session),
            60.0 * args.prose_budget_minutes,
            args.llm_url,
            args.llm_model,
            args.concurrency,
        )

    try:
        path = save(Path(store.root), core, allow_overwrite=args.force)
    except FileExistsError as exc:
        print(f"\n{exc}")
        print("the existing record is kept; nothing was changed")
        return
    print(f"\nrecord written: {path}")
    # The cheap work that belongs with the record lands before the prose,
    # so a drill-down never shows tonight's grades over yesterday's history
    # and a kill during the prose wait loses nothing but prose.
    written = write_history(store, report)
    if written:
        print(f"history: {written} names written")
    removed = prune(Path(store.root), asof, args.prune_days)
    if removed:
        print(f"pruned {len(removed)} old partitions")
    enrich_prose(Path(store.root), core, enrichment)
    # Current collection stays outside historical decisions and portfolio
    # sizing; it uses the model runtime, so it follows the prose.
    from backend.cli import market_economics

    market_economics.refresh_if_current(
        Path(store.root),
        args.refresh and args.asof is None,
        args.llm_url,
        args.llm_model,
    )


if __name__ == "__main__":
    main()
