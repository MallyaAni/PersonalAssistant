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

from backend.agents.trading.desk import actions, grading
from backend.agents.trading.desk.opinions import (
    BEARISH,
    BULLISH,
    SHARPNESS,
    STANCE_FRACTION,
    conviction_from_ranks,
)

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


# Why a name leaves the account: what you hold changes the answer. A name
# you do not hold has nothing to sell - the relevant line is how long it
# stays a buy. The desk's own exit is the grade check at a rebalance, so a
# held name's exit is that rule; a held name the desk dropped is sold.
def _exit_reason(holding: Holding | None, in_book: bool, target: float) -> str:
    if not in_book:
        return "your call: the desk does not cover it"
    if holding is None:
        return "a buy only while it holds an A grade"
    if target <= 0:
        return "sell everything: it no longer earns a place in the book"
    return "sell when its grade drops below A at a rebalance"


# The board against the person's holdings, from the latest record.
def board(
    record: dict,
    holdings: list[Holding],
    equity: float,
    quotes: dict,
    technical: dict | None = None,
) -> list[dict]:
    """Return action rows for every name held or targeted, best grade first.

    `technical` is {ticker: {"now": rank, "close": rank}} from the live
    read; where present the technical stance is re-read at the live rank
    and the grade and score re-made from it, so the order follows the
    candle. The evening decision (targets, actions) is unchanged by it.
    """
    technical = technical or {}
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
        live = _live_grade(grade, technical.get(ticker)) if in_book else None
        # A held name the desk does not cover has no liquidation decision: a
        # lack of coverage is not a sell. It gets an explicit review state
        # until the person assigns it to the strategy or closes it by hand.
        action = (
            "uncovered"
            if (holding is not None and not in_book)
            else actions.action_for(target, current)
        )
        # The band-reversal blocker: a name the nightly desk refused to buy
        # because its daily rejects its upper Bollinger band is not a buy or
        # an add here either - the paper planner holds every buy-side order
        # for it back, so presenting it as an actionable buy would tell the
        # person to place an order the strategy itself will not place. The
        # board carries the blocker's own verdict instead.
        blocked = bool(level.get("rejecting_band", False)) and action in ("buy", "add")
        if blocked:
            action = "blocked"
        # The paper book's countdown to its next rebalance, from the record's
        # paper block or the levels when it is absent.
        countdown = until if until is not None else level.get("until_rebalance")
        rows.append(
            {
                "ticker": ticker,
                "action": action,
                "blocked_reason": (
                    "the name's daily rejected its upper band, so the desk held the buy"
                    if blocked
                    else None
                ),
                "in_book": in_book,
                "grade": grade.get("grade", ""),
                "grade_live": live["grade"] if live else grade.get("grade", ""),
                "score_live": live["score"] if live else None,
                "technical_now": live["now"] if live else None,
                "technical_close": live["close"] if live else None,
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
                # Whether the nightly desk refused to buy the name tonight
                # because its daily is rejecting its upper Bollinger band.
                "rejecting_band": bool(level.get("rejecting_band", False)),
                "until_rebalance": countdown,
                # Whether the paper book's next session is a rebalance: only
                # then are the target-vs-held changes executable at the next
                # open. Otherwise they are targets for the next rebalance,
                # and the page must not present them as tomorrow's orders.
                "rebalance_due": countdown is None or int(countdown) <= 1,
                "leaves_if": _exit_reason(holding, in_book, target),
            }
        )
    # Best grade first, the live one where the candle has moved it, then
    # the live score; names the desk does not cover last.
    rows.sort(
        key=lambda r: (
            not r["in_book"],
            -grading.ORDINAL.get(r["grade_live"], -1),
            -(r["score_live"] if r["score_live"] is not None else -1e9),
            r["ticker"],
        )
    )
    return rows


# Every graded name re-graded at the candle, for the page's full list:
# the board carries only the names held or targeted, and the person reads
# the whole book by grade, so the other names must move with the candle
# too or the list is a mix of live and evening grades in one order.
def live_grades(record: dict, technical: dict | None) -> dict[str, dict]:
    """Return {ticker: live grade, score and technical ranks} where read."""
    out: dict[str, dict] = {}
    for ticker, grade in (record.get("grades") or {}).items():
        live = _live_grade(grade, (technical or {}).get(ticker))
        if live is None:
            continue
        out[ticker] = {
            "grade_live": live["grade"],
            "score_live": live["score"],
            "technical_now": live["now"],
            "technical_close": live["close"],
        }
    return out


# The grade re-made with the technical stance read at the live rank, the
# other analysts as the record left them, and the score moved by the
# technical conviction's change. None when there is no live read.
def _live_grade(grade: dict, tech: dict | None) -> dict | None:
    if not tech:
        return None
    now, close = float(tech.get("now", float("nan"))), float(
        tech.get("close", float("nan"))
    )
    if not (now == now and close == close):
        return None
    stances = {k: int(v) for k, v in (grade.get("stances") or {}).items()}
    if "technical" not in stances:
        return None
    # The live stance is the rule's own, persisted through the live bar,
    # when the read carries it; the bare threshold is the fallback for a
    # snapshot written before the stance was.
    if tech.get("stance") is not None:
        stances["technical"] = int(tech["stance"])
    else:
        stances["technical"] = (
            BULLISH
            if now >= 1.0 - STANCE_FRACTION
            else BEARISH if now <= STANCE_FRACTION else 0
        )
    letter, _votes = grading.grade_from_stances(stances, grading.ANALYST_WEIGHTS)
    moved = float(
        conviction_from_ranks(now, SHARPNESS) - conviction_from_ranks(close, SHARPNESS)
    )
    return {
        "grade": letter,
        "score": float(grade.get("score", 0.0)) + moved,
        "now": now,
        "close": close,
    }
