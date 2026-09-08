"""The person's own positions, and the board computed against them.

The desk's board is computed against the paper account. The person
trades their own account, so the board has to be computable against
what they actually hold: ticker, shares, the price and date they paid.
They are kept beside the records, written by the API when the person
saves them, and never touched by the nightly run.

`board(record, holdings, equity, quotes)` turns the latest record and
the holdings into rows in the same shape as the record's own action
board: the action against the person's weights, the grade and its
margin where the desk rates the name, the levels and stops where the
record has them, and P&L on the person's entry. A name the desk does not
rate gets a row too, marked outside the book, so the exit question is
answered for it from the risk facts alone.
"""

import json
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from backend.agents.trading.desk import actions

FILE = "holdings.json"


@dataclass(frozen=True)
class Holding:
    """One position in the person's own account."""

    ticker: str
    shares: float
    entry_price: float
    entry_date: str  # ISO date


# Where the holdings live: beside the desk records.
def holdings_path(root: Path) -> Path:
    """Return the holdings file's path under `root`."""
    return root / "desk" / FILE


# Validate and normalise rows from the API: tickers upper-case, positive
# shares and prices, a real date. Bad rows raise ValueError with a reason.
def parse(rows: list[dict]) -> list[Holding]:
    """Return the Holdings in `rows`, or raise ValueError on the first bad one."""
    out: list[Holding] = []
    seen: set[str] = set()
    for row in rows:
        ticker = str(row.get("ticker", "")).strip().upper()
        if (
            not ticker
            or len(ticker) > 8
            or not ticker.replace(".", "").replace("-", "").isalnum()
        ):
            raise ValueError(f"bad ticker {ticker!r}")
        if ticker in seen:
            raise ValueError(f"{ticker} listed twice")
        try:
            shares = float(row.get("shares", 0))
            price = float(row.get("entry_price", 0))
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"{ticker}: shares and entry price must be numbers"
            ) from exc
        if shares <= 0 or price <= 0:
            raise ValueError(f"{ticker}: shares and entry price must be positive")
        when = str(row.get("entry_date", "")).strip()
        try:
            date.fromisoformat(when)
        except ValueError as exc:
            raise ValueError(f"{ticker}: entry date must be YYYY-MM-DD") from exc
        seen.add(ticker)
        out.append(Holding(ticker, shares, price, when))
    return out


def load(root: Path) -> list[Holding]:
    """Return the saved holdings, empty when none were saved."""
    path = holdings_path(root)
    if not path.exists():
        return []
    return parse(json.loads(path.read_text(encoding="utf-8")))


def save(root: Path, holdings: list[Holding]) -> Path:
    """Write the holdings and return the path."""
    path = holdings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([asdict(h) for h in holdings], indent=2), encoding="utf-8"
    )
    return path


# The board against the person's holdings, from the latest record.
def board(
    record: dict, holdings: list[Holding], equity: float, quotes: dict
) -> list[dict]:
    """Return action rows for every name held or targeted, most urgent first."""
    grades = record.get("grades") or {}
    targets = {row["ticker"]: float(row["weight"]) for row in record.get("book") or []}
    levels = dict(record.get("levels") or {})
    for row in record.get("actions") or []:
        levels.setdefault(row["ticker"], row)
    ranked = sorted(grades, key=lambda t: -float(grades[t].get("score", 0.0)))
    rank = {t: i + 1 for i, t in enumerate(ranked)}
    held = {h.ticker: h for h in holdings}
    # The rebalance clock is the paper book's; the levels carry none.
    until = (record.get("paper") or {}).get("until_rebalance")
    rows = []
    for ticker in sorted(set(targets) | set(held)):
        holding = held.get(ticker)
        quote = quotes.get(ticker) or {}
        level = levels.get(ticker) or {}
        last = float(quote.get("last") or level.get("last_close") or 0.0)
        if holding is not None:
            price = last or holding.entry_price
            current = holding.shares * price / equity if equity > 0 else 0.0
        else:
            current = 0.0
        target = targets.get(ticker, 0.0)
        grade = grades.get(ticker) or {}
        in_book = ticker in grades
        rows.append(
            {
                "ticker": ticker,
                "action": actions.action_for(target, current),
                "in_book": in_book,
                "grade": grade.get("grade", ""),
                "rank": rank.get(ticker),
                "score": float(grade.get("score", 0.0)) if in_book else None,
                "stances": grade.get("stances") or {},
                "ranks": grade.get("ranks") or {},
                "why": (
                    grade.get("headline", "")
                    if in_book
                    else "the desk does not cover this name, so it has no view on it"
                ),
                "reason": grade.get("reason", "") if in_book else "",
                "target_weight": target,
                "current_weight": current,
                "delta_weight": target - current,
                "shares": holding.shares if holding else 0.0,
                "entry_price": holding.entry_price if holding else None,
                "entry_date": holding.entry_date if holding else None,
                "last": last or None,
                "pl_pct": (
                    (last / holding.entry_price - 1.0) if holding and last else None
                ),
                "last_close": level.get("last_close"),
                "high_20": level.get("high_20"),
                "stops": level.get("stops") or {},
                "grade_margin": level.get("grade_margin"),
                "until_rebalance": (
                    until if until is not None else level.get("until_rebalance")
                ),
                "leaves_if": (
                    "sell when its grade drops below A"
                    if target > 0
                    else (
                        "your call: the desk does not cover it"
                        if not in_book
                        else "sell everything: it no longer earns an A"
                    )
                ),
            }
        )
    rows.sort(
        key=lambda r: (actions.ORDER[r["action"]], -abs(r["delta_weight"]), r["ticker"])
    )
    return rows
