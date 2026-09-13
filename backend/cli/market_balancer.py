"""The desk's intraday balancer: every fifteen minutes, what to buy right now.

The nightly record decides the book and its target weights. Between sessions
the grade is fixed but the price and the technical read move, so "best buys
for this moment, sized by the grade" is a live re-ranking of that fixed book
against the person's recorded holdings, refreshed on each fifteen-minute
candle. This job does that re-ranking headlessly and persists it - the ranked
buys, the rebalance plan against the holdings, and what changed since the
last run - to ``data/market/desk/intraday.json`` for the dashboard, plus a
one-line audit trail.

It decides nothing the nightly run does not already decide. Re-deciding the
book intraday is measured to lose a Sharpe point (`market_cadence`), so this
only re-reads the technical stance at the live price and re-ranks - exactly
what the board does, but persisted on the candle so the plan exists even when
no browser is open. It never submits a trade: the person executes on their
broker and records it with the board's Buy button.

    python -m backend.cli.market_balancer --data-dir data/market --equity 100000
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from backend.market import alpaca, deskrecord, holdings, live_quotes, live_technical
from backend.market.store import MarketStore

# The plan and its audit trail, both under the desk data root.
INTRADAY_FILE = "intraday.json"
INTRADAY_LOG = "intraday.log"
# The trading day is a New York date; the zone carries daylight saving, so
# the opening-hour rule is not a fixed offset from UTC.
NEW_YORK = ZoneInfo("America/New_York")

# The live snapshot: the candle's quotes and technical read, persisted beside
# the plan so the desk page's live endpoints can serve the candle instantly
# instead of fetching quotes and recomputing the analyst on every request.
LIVE_FILE = "live.json"


# What the live board says changed since the previous plan: a name's grade
# moved, or a buy fell out or into the ranked list. Compact, human-readable,
# and the whole point of persisting the plan on the candle.
def _changes(previous: dict | None, top_buys: list[dict]) -> list[str]:
    if not previous:
        return ["first plan of the session"]
    before = {b["ticker"]: b for b in previous.get("top_buys") or []}
    after = {b["ticker"]: b for b in top_buys}
    notes: list[str] = []
    for ticker, now in after.items():
        old = before.get(ticker)
        if old is None:
            notes.append(f"{ticker} entered the buys")
            continue
        old_grade = old.get("grade_live") or old.get("grade")
        new_grade = now.get("grade_live") or now.get("grade")
        if old_grade != new_grade:
            notes.append(f"{ticker}: {old_grade} -> {new_grade}")
    for ticker in before:
        if ticker not in after:
            notes.append(f"{ticker} left the buys")
    return notes or ["no change to the ranked buys"]


# The names the desk will not buy into tonight: a daily rejecting its upper
# Bollinger band, read with the exit analyst's own signal. The record
# carries the flag the nightly run stamped, on its action rows and its
# levels block; a record that predates the stamp falls back to recomputing
# it here from the store, so the ranked buys stay gated however old the
# record is. A record with neither (a report-only test fixture) leaves
# every name buyable, as it was before the blocker existed.
def _band_blocked(latest: dict, store: MarketStore) -> set[str]:
    """Return the tickers the desk refuses to buy on the record's session."""
    flags: dict[str, bool] = {}
    for source in (latest.get("actions"), latest.get("levels")):
        for row in source or []:
            if isinstance(row, dict) and row.get("ticker") and "rejecting_band" in row:
                flags[row["ticker"]] = bool(row["rejecting_band"])
    if flags:
        return {t for t, v in flags.items() if v}
    try:
        from backend.agents.trading.desk import exit as exit_analyst
        from backend.market import universe
        from backend.market.panel import build_panel

        book_universe = universe.build_universe()
        sides = universe.book_sides(book_universe)
        themes = {
            t: g for t, g in universe.theme_map(book_universe).items() if t in sides
        }
        panel = build_panel(
            store, list(sides), universe.MARKET_BENCHMARK, themes, asof=None
        )
        signal = exit_analyst.evidence(panel).signalled()
        last = len(panel.dates) - 1
        return {
            ticker
            for column, ticker in enumerate(panel.tickers)
            if signal[last, column]
        }
    except Exception:
        return set()


# Check that a candle belongs to the current regular session and is recent.
def _current_opening_candle(quote: dict, now: datetime) -> bool:
    try:
        bar = datetime.fromisoformat(str(quote.get("bar", "")))
        bar = bar.astimezone(NEW_YORK) if bar.tzinfo else None
    except ValueError:
        return False
    return (
        bar is not None
        and bar.date() == now.date()
        and bar.hour * 60 + bar.minute >= 570
        and 0 <= (now - bar).total_seconds() <= 1800
    )


# Persist the intention to hold a green opening before requesting cancellation.
def _green_day_skip(data_dir: Path, latest: dict, quotes: dict, log_path: Path) -> None:
    """Cancel pending sells for names trading up at the open; journal the holds."""
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    # Only 09:30-11:00 US Eastern: the rule is about the open, and a
    # stale or pre-market quote outside it must not cancel anything. The
    # New York zone carries daylight saving, where a fixed four-hour shift
    # from UTC is wrong half the year.
    now = datetime.now(UTC).astimezone(NEW_YORK)
    if not (570 <= now.hour * 60 + now.minute < 660) or now.weekday() >= 5:
        return
    state = paper.load_state(data_dir)
    pending_sells = [p for p in state.pending if p.get("side") == "sell"]
    action_rows = {r.get("ticker"): r for r in latest.get("actions") or []}
    clients = None
    skipped: list[str] = []
    for row in pending_sells:
        ticker = row.get("symbol", "")
        quote = quotes.get(ticker)
        if not _current_opening_candle(quote or {}, now):
            continue
        prior = (action_rows.get(ticker) or {}).get("last_close")
        # The rule is about the open, so it compares the session's opening
        # print against the prior close - exactly what the backtest's
        # green_day_skip walks (opens[t+1] > closes[t]). The latest tick
        # would let a name that opened down but rallied in the first hour
        # be held while the simulation sold it, and one that opened up then
        # faded be sold while the simulation held it.
        open_px = (quote or {}).get("open")
        if not open_px or not prior or open_px <= float(prior):
            continue
        # Cancel the broker's order by the id the desk chose, then write
        # the deliberate hold into the state so the rebalance concludes.
        # Only a confirmed cancel becomes a hold: an order the broker still
        # has working (pending_cancel can still fill) or one that already
        # filled is left in the state for the next reconcile to record what
        # actually happened, never journaled as a zero-fill hold.
        try:
            if clients is None:
                clients = alpaca_trading.client_from_env()
            # Save intent before the external action: an accepted cancel
            # may finish after this process exits. Reconciliation must know
            # why it was canceled without inventing or discarding fills.
            row["hold_requested"] = True
            paper.save_state(data_dir, state)
            outcomes = clients.cancel_orders([row["client_order_id"]])
        except alpaca_trading.AlpacaTradingError as exc:
            print(f"  green-day skip: could not cancel {ticker}: {exc}")
            continue
        if outcomes.get(row["client_order_id"]) != "cancelled":
            print(
                f"  green-day skip: {ticker} not held "
                f"(cancel {outcomes.get(row['client_order_id'])})"
            )
            continue
        state = paper.skip_sell(state, row["client_order_id"])
        skipped.append(f"{ticker} up at the open ({open_px:.2f} > {float(prior):.2f})")
    if skipped:
        paper.save_state(data_dir, state)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(
                f"{datetime.now(UTC).isoformat(timespec='seconds')} "
                f"session={latest.get('session')} green-day skipped: "
                f"{'; '.join(skipped)}\n"
            )
        for note in skipped:
            print(f"  - {note}")


# Build the plan for the person's own account from the latest record, their
# recorded holdings, and the live read, and write it with the audit line.
def run(data_dir: Path, equity: float) -> Path:
    """Recompute the intraday plan and persist it; return the written path."""
    store = MarketStore(data_dir)
    latest, _ = deskrecord.latest_pair(data_dir)
    path = data_dir / "desk" / INTRADAY_FILE
    held = holdings.load(data_dir)
    if latest is None:
        plan = {
            "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
            "session": None,
            "equity": equity,
            "top_buys": [],
            "rows": [],
            "changed": ["no evening record yet"],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
        return path
    # Every graded name, not only the board's: the page's full list is
    # re-graded at the candle from this same snapshot.
    symbols = sorted(
        {h.ticker for h in held}
        | {r["ticker"] for r in latest.get("book") or []}
        | {r["ticker"] for r in latest.get("actions") or []}
        | set(latest.get("grades") or {})
    )
    quotes: dict = {}
    technical: dict = {}
    value: dict = {}
    technical_detail: dict = {}
    try:
        found = live_quotes.quotes(symbols, headers=alpaca.credentials())
        quotes = {s: _quote_dict(q) for s, q in found.items()}
        if found:
            try:
                technical = live_technical.technical_now(store, found)
                value = live_technical.value_now(store, found)
                # The detail shares the analyst's per-candle cache, so the
                # second read is cheap and the page never pays for it.
                technical_detail = live_technical.technical_detail(store, found)
            except Exception:  # the board stands without the live read
                technical = {}
    except alpaca.AlpacaUnavailableError:
        pass
    rows = holdings.board(latest, held, equity, quotes, technical, value)
    # Only names the desk is willing to start: a name can earn a target
    # weight and still be rejecting its upper Bollinger band tonight, and
    # buying it then is buying into a move that is already rolling over -
    # SNDK bought the morning after a 12% spike while its daily rejected
    # the band. The nightly plan blocks the same names. Measured on the
    # book since 2015 this narrow blocker beat the ungated book on return,
    # Sharpe and drawdown; requiring a full entry trigger starved it.
    blocked = _band_blocked(latest, store)
    top_buys = [
        r
        for r in rows
        if r["in_book"]
        and r["target_weight"] > 0
        and r["shares"] == 0
        and r["ticker"] not in blocked
    ]
    previous: dict | None = None
    if path.exists():
        try:
            previous = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            previous = None
    plan = {
        "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
        "session": latest.get("session"),
        "equity": equity,
        "top_buys": top_buys,
        "rows": rows,
        "changed": _changes(previous, top_buys),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2), encoding="utf-8")
    # The live snapshot alongside the plan: the same quotes and technical read
    # the plan was built from, so the API's live endpoints serve the candle
    # without a fresh quote fetch or analyst run of their own. A run with no
    # quotes (keys unavailable) leaves the previous snapshot standing rather
    # than clobbering it with an empty one the API would serve.
    if quotes:
        live = {
            "as_of": datetime.now(UTC).isoformat(timespec="seconds"),
            "decision_session": latest.get("session"),
            "quotes": quotes,
            "technical": technical,
            "value": value,
            "technical_detail": technical_detail,
        }
        (data_dir / "desk" / LIVE_FILE).write_text(
            json.dumps(live, indent=2), encoding="utf-8"
        )
        # The green-day rule runs on the same candle: a pending sell for a
        # name trading up at the open is cancelled and the position held.
        _green_day_skip(data_dir, latest, quotes, data_dir / "desk" / INTRADAY_LOG)
    with (data_dir / "desk" / INTRADAY_LOG).open("a", encoding="utf-8") as handle:
        grades = ",".join(
            f"{b['ticker']}={b.get('grade_live') or b.get('grade')}"
            for b in top_buys[:5]
        )
        handle.write(
            f"{plan['as_of']} session={plan['session']} buys=[{grades}] "
            f"changed={'; '.join(plan['changed'])}\n"
        )
    return path


# A Quote to a JSON-safe dict, as the API does for the board.
def _quote_dict(quote: object) -> dict:
    from dataclasses import asdict

    return asdict(quote)


def build_parser() -> argparse.ArgumentParser:
    """Return the CLI parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data/market", help="desk data root")
    parser.add_argument("--equity", type=float, default=100_000.0, help="account size")
    return parser


def main() -> None:
    """Entry point."""
    args = build_parser().parse_args()
    path = run(Path(args.data_dir), args.equity)
    plan = json.loads(path.read_text(encoding="utf-8"))
    print(f"intraday plan written: {path}")
    print(f"session={plan['session']} buys={[b['ticker'] for b in plan['top_buys']]}")
    for note in plan["changed"]:
        print(f"  - {note}")
    if not plan["top_buys"] and plan["session"] is not None:
        print("  no names are buys right now")


if __name__ == "__main__":
    main()
