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
import sys
from datetime import UTC, datetime
from pathlib import Path

from backend.market import alpaca, deskrecord, holdings, live_quotes, live_technical
from backend.market.store import MarketStore

# The plan and its audit trail, both under the desk data root.
INTRADAY_FILE = "intraday.json"
INTRADAY_LOG = "intraday.log"

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
    symbols = sorted(
        {h.ticker for h in held}
        | {r["ticker"] for r in latest.get("book") or []}
        | {r["ticker"] for r in latest.get("actions") or []}
    )
    quotes: dict = {}
    technical: dict = {}
    technical_detail: dict = {}
    try:
        found = live_quotes.quotes(symbols, headers=alpaca.credentials())
        quotes = {s: _quote_dict(q) for s, q in found.items()}
        if found:
            try:
                technical = live_technical.technical_now(store, found)
                # The detail shares the analyst's per-candle cache, so the
                # second read is cheap and the page never pays for it.
                technical_detail = live_technical.technical_detail(store, found)
            except Exception:  # the board stands without the live read
                technical = {}
    except alpaca.AlpacaUnavailableError:
        pass
    rows = holdings.board(latest, held, equity, quotes, technical)
    top_buys = [
        r
        for r in rows
        if r["in_book"] and r["target_weight"] > 0 and r["shares"] == 0
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
            "quotes": quotes,
            "technical": technical,
            "technical_detail": technical_detail,
        }
        (data_dir / "desk" / LIVE_FILE).write_text(
            json.dumps(live, indent=2), encoding="utf-8"
        )
    with (data_dir / "desk" / INTRADAY_LOG).open("a", encoding="utf-8") as handle:
        grades = ",".join(
            f"{b['ticker']}={b.get('grade_live') or b.get('grade')}" for b in top_buys[:5]
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
