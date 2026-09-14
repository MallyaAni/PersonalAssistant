"""Economic facts retain known-at dates and never invent missing comparisons."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.market import economics


# A sparse series deliberately omits the preceding month.
def source():
    return (
        "observation_date,CPIAUCSL,CPILFESL,PPIFIS,PCEPI,PCEPILFE\n"
        "2025-07-01,100,,,,\n2026-07-01,103,,,,\n"
    )


# Compare exact calendar periods and mark absent series as missing.
def test_month_gaps_are_not_monthly_changes():
    now = datetime(2026, 9, 14, tzinfo=UTC)
    snapshot = economics.facts_from_csv(source(), now)
    cpi = snapshot["facts"][0]
    assert cpi["year_change_pct"] == pytest.approx(3)
    assert cpi["month_change_pct"] is None
    assert cpi["release_at"] is None
    assert snapshot["observed_at"] == now.isoformat()
    assert all(f["status"] == "missing" for f in snapshot["facts"][1:])


# Preserve archived observations and withhold stale assessments.
def test_archive_and_stale_readback(tmp_path):
    now = datetime(2026, 9, 14, tzinfo=UTC)
    snapshot = economics.facts_from_csv(source(), now)
    snapshot["assessment"] = {"pressure": "mixed"}
    economics.save(tmp_path, snapshot)
    assert economics.load(tmp_path, now)["assessment"] == {"pressure": "mixed"}
    stale = economics.load(tmp_path, now + timedelta(hours=37))
    assert stale["collection_stale"]
    assert stale["assessment"] is None
    assert stale["observed_at"] == snapshot["observed_at"]
    with pytest.raises(FileExistsError):
        economics.save(tmp_path, snapshot)
    assert len(list((tmp_path / "desk" / "economics").glob("*.json"))) == 2


# Wrong payloads and future data cannot become plausible-looking observations.
@pytest.mark.parametrize(
    "payload",
    [
        "<html>oops</html>",
        source().replace("2026-07-01", "2027-01-01"),
        source().replace("103", "NaN"),
    ],
)
def test_invalid_sources_are_rejected(payload):
    with pytest.raises(ValueError, match="economic|Economic"):
        economics.facts_from_csv(payload, datetime(2026, 9, 14, tzinfo=UTC))
