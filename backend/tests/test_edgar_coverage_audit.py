"""Missing release coverage must not pass the stored-data audit."""

from datetime import UTC, date, datetime

import pytest

from backend.cli import market_edgar
from backend.market import edgar
from backend.market.store import MarketStore


# Store synthetic admissions and refusals without any provider calls.
def _store(tmp_path, days, refused=0):
    store = MarketStore(tmp_path)
    columns = {
        "accepted": [
            datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat() for d in days
        ],
        "filed": days,
        "accession": [f"accepted-{i}" for i in range(len(days))],
        "items": [""] * len(days),
        "form": ["6-K"] * len(days),
    }
    meta = {
        "classified_6k": edgar.decisions_to_metadata(
            {f"refused-{i}": False for i in range(refused)}
        )
    }
    store.write_frame("edgar_events", date(2026, 10, 1), "TEST", columns, meta)
    return store


# No admissions is missing coverage, including a frame full of refusals.
@pytest.mark.parametrize("refused", [0, 53])
def test_zero_admissions_fails(tmp_path, capsys, refused):
    store = _store(tmp_path, [], refused)
    assert not market_edgar.audit_6k(store, ("TEST",), date(2026, 10, 1))
    assert "CHECK no admitted 6-K releases" in capsys.readouterr().out


# The audit horizon is the requested date, not the newest admitted release.
def test_missing_trailing_full_year_fails(tmp_path, capsys):
    days = [date(2023, 10, 1)] + [date(2024, m, 15) for m in (1, 4, 7, 10)]
    store = _store(tmp_path, days)
    assert not market_edgar.audit_6k(store, ("TEST",), date(2026, 10, 1))
    output = capsys.readouterr().out
    assert "CHECK [2025]" in output
    assert "2025:0" in output


# A partial start year and current year do not establish full-year coverage.
def test_no_complete_year_is_unverified(tmp_path, capsys):
    store = _store(tmp_path, [date(2025, 10, 15), date(2026, 1, 15)])
    assert not market_edgar.audit_6k(store, ("TEST",), date(2026, 10, 1))
    assert "UNVERIFIED no complete filing year" in capsys.readouterr().out


# Complete intervening years pass; the current year is not required to have four yet.
def test_complete_year_counts_pass(tmp_path, capsys):
    days = [date(2023, 10, 1)] + [
        date(y, m, 15) for y in (2024, 2025) for m in (1, 4, 7, 10)
    ]
    store = _store(tmp_path, days + [date(2026, 1, 15)])
    assert market_edgar.audit_6k(store, ("TEST",), date(2026, 10, 1))
    assert "ok" in capsys.readouterr().out


# A frame's later admissions cannot influence an earlier requested horizon.
def test_frame_audit_excludes_future_filings():
    days = [date(2023, 10, 1), date(2025, 1, 1)]
    columns = {
        "accepted": [
            datetime(d.year, d.month, d.day, tzinfo=UTC).isoformat() for d in days
        ],
        "filed": days,
        "accession": ["a", "b"],
        "items": ["", ""],
        "form": ["6-K", "6-K"],
    }
    counts, short = market_edgar.audit_6k_frame(columns, through=date(2024, 12, 31))
    assert counts == {2023: 1}
    assert short == []
