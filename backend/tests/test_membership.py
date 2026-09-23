"""Membership history must fail closed against survivor hindsight."""

from dataclasses import replace
from datetime import date

import pytest

from backend.market import membership, universe


# A later entrant must never appear in an earlier simulated book.
def test_dated_entry_and_exit_bound_the_book():
    row = membership.MembershipRecord(
        "NEW",
        date(2024, 1, 3),
        date(2023, 12, 28),
        date(2025, 4, 2),
        date(2025, 3, 30),
        "dated filing",
        "listing rule",
    )
    assert "NEW" not in membership.members_as_of([row], date(2016, 6, 1))
    assert "NEW" in membership.members_as_of([row], date(2024, 1, 3))
    assert "NEW" not in membership.members_as_of([row], date(2025, 4, 2))


# A retrospective edit without a timely public source is invalid input.
def test_late_or_missing_publication_never_backfills_membership():
    row = membership.MembershipRecord(
        "NEW",
        date(2024, 1, 3),
        date(2024, 1, 3),
        None,
        None,
        "dated filing",
        "listing rule",
    )
    with pytest.raises(ValueError, match="announced after"):
        membership.validate_history([replace(row, entry_announced=date(2024, 1, 4))])
    with pytest.raises(ValueError, match="no timely announcement"):
        membership.validate_history([replace(row, exited=date(2025, 1, 3))])
    with pytest.raises(ValueError, match="source"):
        membership.validate_history([replace(row, source="")])


# Overlapping revisions cannot silently double-count a name in one session.
def test_overlapping_intervals_are_rejected():
    first = membership.MembershipRecord(
        "NEW",
        date(2024, 1, 3),
        date(2024, 1, 3),
        date(2025, 4, 2),
        date(2025, 3, 30),
        "dated filing",
        "listing rule",
    )
    second = replace(first, entered=date(2025, 4, 1), entry_announced=date(2025, 3, 31))
    with pytest.raises(ValueError, match="overlap"):
        membership.validate_history([first, second])


# A missing archive is a data gap rather than permission to use today's list.
def test_missing_history_file_has_no_fallback(tmp_path):
    with pytest.raises(FileNotFoundError):
        membership.load_history(tmp_path / "membership_history.csv")
    with pytest.raises(FileNotFoundError):
        universe.as_of(date(2016, 6, 1), tmp_path / "membership_history.csv")


# The public research helper reads only a cited interval file, never OVERLAY.
def test_universe_as_of_reads_the_historical_file(tmp_path):
    path = tmp_path / "membership_history.csv"
    path.write_text(
        "ticker,entered,entry_announced,exited,exit_announced,source,rule\n"
        "NEW,2024-01-03,2023-12-28,,,dated filing,listing rule\n",
        encoding="utf-8",
    )
    assert universe.as_of(date(2016, 6, 1), path) == frozenset()
    assert universe.as_of(date(2024, 1, 3), path) == frozenset({"NEW"})
