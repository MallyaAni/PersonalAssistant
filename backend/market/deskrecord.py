"""The desk's daily records, and what changed between two of them.

`market_daily` writes one JSON record per session under
`<root>/desk/asof=<session>/desk.json`. This reads them back and turns two
consecutive records into the list an operator acts on: which names were
upgraded into the book or downgraded out of it, how each held weight
moved, and which regime flags appeared or cleared. The page and the
trading agent's card read only these files, so they cannot show a state
the desk did not write.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

DESK_KIND = "desk"
GRADE_ORDER = {"A+": 3, "A": 2, "B": 1, "C": 0}


# The sessions with a record, oldest first.
def sessions(root: Path) -> list[str]:
    """Return the session dates that have a desk record."""
    base = Path(root) / DESK_KIND
    if not base.exists():
        return []
    out = []
    for p in base.iterdir():
        if p.is_dir() and p.name.startswith("asof=") and (p / "desk.json").exists():
            out.append(p.name[len("asof=") :])
    return sorted(out)


# One session's record, or None.
def load(root: Path, session: str) -> dict | None:
    """Return the record for `session`."""
    path = Path(root) / DESK_KIND / f"asof={session}" / "desk.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# The newest record and the one before it, either may be None.
def latest_pair(root: Path) -> tuple[dict | None, dict | None]:
    """Return (latest, previous) records."""
    found = sessions(root)
    latest = load(root, found[-1]) if found else None
    previous = load(root, found[-2]) if len(found) > 1 else None
    return latest, previous


@dataclass(frozen=True)
class Order:
    """One thing to do at the next open, with the reason."""

    ticker: str
    action: str  # "buy", "sell", "add", "trim"
    weight_from: float
    weight_to: float
    grade_from: str | None
    grade_to: str | None
    reason: str


@dataclass(frozen=True)
class Changes:
    """What moved between two records."""

    since: str | None
    upgrades: list[dict] = field(default_factory=list)
    downgrades: list[dict] = field(default_factory=list)
    orders: list[Order] = field(default_factory=list)
    flags_raised: list[str] = field(default_factory=list)
    flags_cleared: list[str] = field(default_factory=list)

    # As plain data for the API.
    def to_dict(self) -> dict:
        """Return the changes as JSON-ready data."""
        return {
            "since": self.since,
            "upgrades": self.upgrades,
            "downgrades": self.downgrades,
            "orders": [o.__dict__ for o in self.orders],
            "flags_raised": self.flags_raised,
            "flags_cleared": self.flags_cleared,
        }


# Weights held per ticker in a record's book.
def _weights(record: dict | None) -> dict[str, float]:
    if not record:
        return {}
    return {row["ticker"]: float(row["weight"]) for row in record.get("book", [])}


# Grades per ticker in a record.
def _grades(record: dict | None) -> dict[str, str]:
    if not record:
        return {}
    return {t: g["grade"] for t, g in record.get("grades", {}).items()}


# The difference between the previous record and the latest: grade moves,
# the orders that turn the previous book into the latest one, and the
# regime flags that changed. With no previous record every held name is a
# buy and every grade is new.
def changes(latest: dict, previous: dict | None, min_trade: float = 0.005) -> Changes:
    """Return the Changes from `previous` to `latest`."""
    before, after = _grades(previous), _grades(latest)
    upgrades, downgrades = [], []
    for ticker, grade in after.items():
        old = before.get(ticker)
        if old is None or old == grade:
            continue
        move = {"ticker": ticker, "from": old, "to": grade}
        (upgrades if GRADE_ORDER[grade] > GRADE_ORDER[old] else downgrades).append(move)
    held_before, held_after = _weights(previous), _weights(latest)
    orders: list[Order] = []
    for ticker in sorted(set(held_before) | set(held_after)):
        w0, w1 = held_before.get(ticker, 0.0), held_after.get(ticker, 0.0)
        if abs(w1 - w0) < min_trade:
            continue
        if w0 == 0.0:
            action, reason = "buy", f"enters the book at grade {after.get(ticker, '?')}"
        elif w1 == 0.0:
            action = "sell"
            reason = f"leaves the book (grade {after.get(ticker, '?')})"
        elif w1 > w0:
            action, reason = "add", "weight raised on the rebalance"
        else:
            action, reason = "trim", "weight lowered on the rebalance"
        orders.append(
            Order(ticker, action, w0, w1, before.get(ticker), after.get(ticker), reason)
        )
    orders.sort(key=lambda o: -abs(o.weight_to - o.weight_from))
    old_flags = set((previous or {}).get("regime", {}).get("flags", []))
    new_flags = set(latest.get("regime", {}).get("flags", []))
    return Changes(
        since=(previous or {}).get("session"),
        upgrades=sorted(upgrades, key=lambda m: -GRADE_ORDER[m["to"]]),
        downgrades=sorted(downgrades, key=lambda m: GRADE_ORDER[m["to"]]),
        orders=orders,
        flags_raised=sorted(new_flags - old_flags),
        flags_cleared=sorted(old_flags - new_flags),
    )


# A compact summary of a record for a card: counts, gross, the top names.
def summary(record: dict) -> dict:
    """Return the headline facts of a record."""
    counts: dict[str, int] = {"A+": 0, "A": 0, "B": 0, "C": 0}
    for g in record.get("grades", {}).values():
        counts[g["grade"]] = counts.get(g["grade"], 0) + 1
    book = record.get("book", [])
    return {
        "session": record.get("session"),
        "counts": counts,
        "gross": round(sum(float(r["weight"]) for r in book), 3),
        "names": [r["ticker"] for r in book],
        "flags": list(record.get("regime", {}).get("flags", [])),
        "selection_confidence": record.get("regime", {}).get("selection_confidence"),
        "exposure": record.get("regime", {}).get("exposure"),
    }
