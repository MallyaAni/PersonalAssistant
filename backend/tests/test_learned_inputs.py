"""Prospective learned inputs retain the observation, not a later replay."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pytest

from backend.market import language, learned_inputs
from backend.market.panel import Panel
from backend.market.store import MarketStore


# Build a long enough, single-vintage panel to exercise the real features.
def _panel() -> Panel:
    dates = np.arange("2026-01-02", "2026-07-03", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)]
    t = len(dates)
    prices = np.column_stack((100 + np.arange(t), 200 + np.arange(t) / 2))
    return Panel(
        dates=dates,
        tickers=("AAA", "SPY"),
        open=prices - 1,
        high=prices + 2,
        low=prices - 3,
        close=prices,
        adj_close=prices * 0.5,
        volume=np.full((t, 2), 1000.0),
        themes={},
        benchmark="SPY",
    )


# A release carries its own reaction date, accession and exact scored tone.
def _tone(accession: str, reaction: date, value: float) -> language.ToneRecord:
    return language.ToneRecord(
        accession=accession,
        reaction_date=reaction,
        guidance=value,
        demand=value,
        pricing=value,
        capex=value,
        supply_constrained=value,
        summary="fixture",
        model="fixture",
        prompt_version="tone/1",
        truncated=False,
    )


# Make a real desk-record file so capture can tie its bytes to the snapshot.
def _record_file(root: Path, session: str) -> tuple[Path, dict]:
    record = {
        "session": session,
        "written": f"{session}T22:00:00+00:00",
        "provenance": {"code_revision": "test-revision"},
        "grades": {"AAA": {"ranks": {"fundamental": 0.75}}},
        "regime": {"exposure": 0.5, "flags": []},
    }
    path = root / "desk.json"
    path.write_text(json.dumps(record), encoding="utf-8")
    return path, record


# Future releases cannot enter tonight's features; prior releases retain
# their score changes and source evidence, and raw range uses raw OHLC.
def test_capture_freezes_only_known_inputs_with_explicit_missingness(tmp_path):
    panel = _panel()
    session = str(panel.dates[-1])
    store = MarketStore(tmp_path)
    known = _tone("older", date(2026, 2, 2), 0.2)
    latest = _tone("latest", date(2026, 6, 1), 0.6)
    future = _tone("future", date(2026, 8, 1), 0.9)
    store.write_frame(
        language.TONE_KIND,
        date.fromisoformat(session),
        "AAA",
        language.tone_frame((known, latest, future)),
    )
    path, record = _record_file(tmp_path, session)
    captured = learned_inputs.capture(path, record, panel, store)
    snapshot = json.loads(captured.read_text())
    stock = snapshot["stocks"]["AAA"]
    assert snapshot["record_sha256"]
    assert snapshot["session"] == session
    assert snapshot["benchmark"] == "SPY"
    assert stock["tone"]["accession"] == "latest"
    assert stock["tone_features"]["tone_guidance"] == pytest.approx(0.6)
    assert stock["tone_features"]["tone_guidance_change"] == pytest.approx(0.4)
    assert stock["fundamental_features"]["earnings_yield"] is None
    assert stock["desk_fundamental_rank"] == pytest.approx(0.75)
    last = len(panel.dates) - 1
    expected_range = (
        panel.high[last - 19 : last + 1, 0].max()
        - panel.low[last - 19 : last + 1, 0].min()
    ) / panel.close[last, 0]
    assert stock["price_features"]["range20_raw"] == pytest.approx(expected_range)
    assert stock["price"]["adj_close"] == pytest.approx(panel.close[last, 0] / 2)
    assert stock["current_bar_present"] is True
    assert stock["current_bar_complete"] is False  # no certified source partition
    assert "historical index membership not established" in snapshot["membership_basis"]


# A second capture of the same record is a no-op; changed source bytes may
# never silently replace the observation originally published for the day.
def test_capture_is_idempotent_and_refuses_rewritten_record(tmp_path):
    panel = _panel()
    store = MarketStore(tmp_path)
    path, record = _record_file(tmp_path, str(panel.dates[-1]))
    first = learned_inputs.capture(path, record, panel, store)
    before = first.read_bytes()
    assert learned_inputs.capture(path, record, panel, store) == first
    assert first.read_bytes() == before
    path.write_text(path.read_text() + " ", encoding="utf-8")
    with pytest.raises(FileExistsError, match="differs"):
        learned_inputs.capture(path, record, panel, store)
    assert first.read_bytes() == before


# An observation is never backdated to a decision session it did not see.
def test_build_rejects_future_session_or_undated_capture(tmp_path):
    panel = _panel()
    store = MarketStore(tmp_path)
    _, record = _record_file(tmp_path, str(panel.dates[-1]))
    with pytest.raises(ValueError, match="observation timestamp"):
        learned_inputs.build(
            record, panel, store, "0" * 64, datetime(2026, 1, 1, tzinfo=UTC)
        )
    record["session"] = "2026-08-03"
    with pytest.raises(ValueError, match="panel session"):
        learned_inputs.build(
            record, panel, store, "0" * 64, datetime(2026, 8, 3, 23, tzinfo=UTC)
        )
