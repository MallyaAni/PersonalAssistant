"""Point-in-time research membership; no fallback to today's constituents.

A reconstructed change date alone is insufficient: each entry and exit must
also have a dated public announcement. Missing history remains an explicit
data failure so a retrospective book cannot silently select survivors.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class MembershipRecord:
    """One name's continuous eligible interval with public source dates."""

    ticker: str
    entered: date
    entry_announced: date
    exited: date | None
    exit_announced: date | None
    source: str
    rule: str


# Refuse an interval whose membership was assigned using later knowledge.
def validate_history(records: list[MembershipRecord]) -> None:  # noqa: C901
    """Validate source, publication and interval chronology for each name."""
    by_ticker: dict[str, list[MembershipRecord]] = {}
    for row in records:
        if not row.ticker or not row.source or not row.rule:
            raise ValueError("each membership interval needs ticker, source and rule")
        if row.entry_announced > row.entered:
            raise ValueError(f"{row.ticker}: entry was announced after it began")
        if row.exited is not None:
            if row.exited <= row.entered:
                raise ValueError(f"{row.ticker}: exit must follow entry")
            if row.exit_announced is None or row.exit_announced > row.exited:
                raise ValueError(f"{row.ticker}: exit has no timely announcement")
        elif row.exit_announced is not None:
            raise ValueError(f"{row.ticker}: exit announcement has no exit date")
        by_ticker.setdefault(row.ticker, []).append(row)
    for ticker, intervals in by_ticker.items():
        ordered = sorted(intervals, key=lambda row: row.entered)
        for previous, following in zip(ordered, ordered[1:], strict=False):
            if previous.exited is None or previous.exited > following.entered:
                raise ValueError(f"{ticker}: membership intervals overlap")


# Load only a dated, cited history; a missing file never implies today's list.
def load_history(path: str | Path) -> list[MembershipRecord]:
    """Read validated intervals from a research history CSV."""
    rows: list[MembershipRecord] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            rows.append(
                MembershipRecord(
                    ticker=item["ticker"].strip(),
                    entered=date.fromisoformat(item["entered"]),
                    entry_announced=date.fromisoformat(item["entry_announced"]),
                    exited=date.fromisoformat(item["exited"])
                    if item["exited"]
                    else None,
                    exit_announced=(
                        date.fromisoformat(item["exit_announced"])
                        if item["exit_announced"]
                        else None
                    ),
                    source=item["source"].strip(),
                    rule=item["rule"].strip(),
                )
            )
    if not rows:
        raise ValueError("historical membership is empty")
    validate_history(rows)
    return rows


# Include a name only after its dated entry and before its dated exit.
def members_as_of(records: list[MembershipRecord], session: date) -> frozenset[str]:
    """Return names with a published active interval on one session."""
    validate_history(records)
    return frozenset(
        row.ticker
        for row in records
        if row.entry_announced <= session
        and row.entered <= session
        and (row.exited is None or session < row.exited)
    )
