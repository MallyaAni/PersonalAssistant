"""Protect research exports against changed price bases and fabricated availability."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_open_source_inputs as exporter


# Construct daily store units with a dividend factor and untouched reported volume.
def history():
    return SimpleNamespace(bars=[SimpleNamespace(
        session_date=date(2026, 9, 3), open=101.0, high=105.0, low=99.0,
        close=100.0, adjusted_close=90.0, volume=12345,
    )])


# Require every OHLC field to share the adjusted-close basis without inventing volume.
def test_forecast_price_basis_and_availability():
    rows = exporter.forecast_rows({"AAPL": history()})
    assert len(rows) == 1
    row = rows[0]
    assert row["open"] == pytest.approx(90.9)
    assert row["high"] == pytest.approx(94.5)
    assert row["low"] == pytest.approx(89.1)
    assert row["close"] == 90
    assert row["volume"] == 12345
    assert row["available_at"] == "2026-09-03T16:00:00-04:00"


# Missing histories and grades remain distinct from a known low-quality grade.
def test_portfolio_unknowns_remain_missing(monkeypatch):
    monkeypatch.setattr(
        exporter.point_in_time, "eligibility",
        lambda days, symbols: np.ones((len(days), len(symbols)), dtype=bool),
    )
    days, arrays = exporter.portfolio_arrays(
        ["AAPL", "MISSING", "SPY", "QQQ"], {"SPY": history(), "AAPL": history()},
        {"AAPL": {"rows": [{"date": "2026-09-03", "grade": "A+"}]}},
    )
    assert days.astype(str).tolist() == ["2026-09-03"]
    assert arrays["grades"][0, 0] == 3
    assert arrays["grades"][0, 1] == -1
    assert np.isnan(arrays["close"][0, 1])
    assert arrays["eligible"][0, 1]
    assert not arrays["eligible"][0, 2:].any()


# Only committed exchange dates may extend forecast covariates beyond the price cutoff.
def test_future_calendar_has_no_weekends_or_price_data():
    result = exporter.future_sessions()
    assert result[0] == "2026-10-01"
    assert result[-1] == "2026-10-16"
    assert len(result) == 12
    assert all(date.fromisoformat(day).weekday() < 5 for day in result)


# Existing artifacts and any output inside the source store must be refused unchanged.
@pytest.mark.parametrize("inside_source", [False, True])
def test_output_boundary_preserves_source(tmp_path, inside_source):
    source = tmp_path / "market"
    source.mkdir()
    original = source / "source.json"
    original.write_text("frozen source")
    output = source / "result" if inside_source else tmp_path / "prior-result"
    if not inside_source:
        output.mkdir()
    with pytest.raises((ValueError, FileExistsError)):
        exporter.export(source, output, "fixed-source")
    assert original.read_text() == "frozen source"
