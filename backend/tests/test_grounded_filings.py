"""Public-corpus acquisition stays bounded, fixed and separate from live state."""

from types import SimpleNamespace

import pytest

from backend.cli import market_grounded_filings as filings


# A fake event frame includes an unrelated 8-K and a filing beyond the cutoff.
def event_store():
    columns = {
        "filed": ["2022-11-01", "2026-08-01", "2026-09-29", "2026-10-01"],
        "accepted": [
            f"{day}T20:01:00+00:00"
            for day in ("2022-11-01", "2026-08-01", "2026-09-29", "2026-10-01")
        ],
        "accession": ["old", "current", "other", "future"],
        "items": ["2.02,9.01", "2.02,9.01", "5.02", "2.02"],
    }
    return SimpleNamespace(read_frame=lambda *args: (columns, {"cik": "123"}))


# Selection ignores non-earnings events and does not peek past either cutoff.
def test_fixed_selection_is_causal_and_twelve_rows():
    rows = filings.select_events(event_store())
    assert len(rows) == 12
    assert [row["accession"] for row in rows] == ["old", "current"] * 6


# Missing sources stay missing instead of being replaced by hand-picked examples.
def test_missing_events_remain_in_the_denominator():
    rows = filings.select_events(SimpleNamespace(read_frame=lambda *args: None))
    assert len(rows) == 12
    assert all(row["status"] == "missing_events" for row in rows)


# An exhibit link cannot redirect this collector to another issuer or private host.
@pytest.mark.parametrize(
    "url",
    [
        "http://www.sec.gov/Archives/edgar/data/123/file.htm",
        "https://example.com/Archives/edgar/data/123/file.htm",
        "https://www.sec.gov/Archives/edgar/data/999/file.htm",
    ],
)
def test_unapproved_archive_url_is_rejected_before_transport(url):
    with pytest.raises(ValueError, match="outside the selected"):
        filings.fetch_html(url, 123, None, None)


# Repeated retrieval failure ends acquisition after three requests, without retries.
def test_acquisition_stops_after_three_failures(monkeypatch):
    calls = []
    monkeypatch.setattr(filings.edgar.Pacer, "wait", lambda self: None)

    # Record a failed request without making a real network call.
    def unavailable(url):
        calls.append(url)
        return 403, b"refused"

    result = filings.collect(event_store(), unavailable)
    assert len(calls) == 3
    assert [row["status"] for row in result["rows"][:3]] == ["fetch_failed"] * 3
    assert all(
        row["status"] == "not_fetched_after_three_failures"
        for row in result["rows"][3:]
    )
