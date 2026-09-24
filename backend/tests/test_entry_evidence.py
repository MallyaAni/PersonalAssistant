"""Price setups remain auditable independently of permission or personal fills."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_candidate
from backend.market import entry_evidence, intraday_research
from backend.tests.test_intraday_candidate import inputs


# Produce matched bullish grades and an extreme final bar without fitting thresholds.
def sample(price=70.0):
    record, snapshot, economic, panel, now = inputs()
    close = panel.adj_close.copy()
    close[-1, 0] = price
    panel = replace(panel, close=close, adj_close=close, high=close, low=close)
    snapshot["quotes"]["S0"]["last"] = price
    return (
        record,
        snapshot,
        panel,
        intraday_candidate.calculate(record, snapshot, economic, panel, now),
    )


# A Dip and an upper-band breakout must remain different opinions on the same name.
@pytest.mark.parametrize(
    ("price", "dip", "buy"), [(70.0, True, False), (180.0, False, True)]
)
def test_captures_distinct_rules_and_reproducible_band(price, dip, buy):
    record, _, panel, observed = sample(price)
    evidence = entry_evidence.capture(panel, record, observed)
    row = evidence["rows"]["S0"]
    assert row["common_eligible"]
    assert row["dip_entry_opinion"] is dip
    assert row["incumbent_entry_opinion"] is buy
    window = np.asarray(row["adjusted_band_closes"])
    assert row["band_z"] == pytest.approx(
        (window[-1] - window.mean()) / (2 * window.std())
    )
    json.dumps(evidence, allow_nan=False)


# Common blockers never erase the underlying setup and apply to both price rules.
@pytest.mark.parametrize(
    "blocked",
    [
        "event_pause",
        "grade_below_entry_floor",
        "rejecting_upper_band",
        "stale_decision",
    ],
)
def test_blocks_permission_without_rewriting_setup(blocked):
    record, _, panel, observed = sample()
    if blocked == "event_pause":
        observed["event_paused"] = True
    elif blocked == "grade_below_entry_floor":
        observed["grades"]["S0"]["grade_live"] = "B"
    elif blocked == "rejecting_upper_band":
        record["levels"] = {"S0": {"rejecting_band": True}}
    else:
        record["session"] = "2026-09-09"
    row = entry_evidence.capture(panel, record, observed)["rows"]["S0"]
    assert row["dip_setup"] is True
    assert blocked in row["blockers"]
    assert not row["dip_entry_opinion"]
    assert not row["incumbent_entry_opinion"]


# Missing price history is explicit unavailable evidence, not a valid negative result.
def test_missing_history_and_future_clock_are_not_fabricated():
    record, _, panel, observed = sample()
    panel.adj_close[-5, 0] = np.nan
    row = entry_evidence.capture(panel, record, observed)["rows"]["S0"]
    assert row["dip_setup"] is None
    assert "price_features_unavailable" in row["blockers"]
    json.dumps(row, allow_nan=False)
    future = replace(panel, dates=panel.dates + np.timedelta64(1, "D"))
    with pytest.raises(ValueError, match="Current unexpired"):
        entry_evidence.capture(future, record, observed)
    early = {
        **observed,
        "as_of": (
            entry_evidence.desk_freshness.timestamp(observed["bar"])
            + timedelta(minutes=10)
        ).isoformat(),
    }
    with pytest.raises(ValueError, match="completed"):
        entry_evidence.capture(panel, record, early)


# Repeat collection preserves the first receipt and supplied account data.
def test_entry_receipt_persists_immutably(tmp_path, monkeypatch):
    record, snapshot, panel, observed = sample()
    original = deepcopy(record)
    observed["entry_evidence"] = entry_evidence.capture(panel, record, observed)
    observed["record_sha256"] = intraday_research.record_hash(record)
    monkeypatch.setattr(intraday_research, "build", lambda *args: deepcopy(observed))
    first = intraday_research.publish(tmp_path, record, snapshot)
    path = next(tmp_path.rglob("decision-*.json"))
    saved = path.read_bytes()
    observed["entry_evidence"]["rows"]["S0"]["band_z"] = 99.0
    assert intraday_research.publish(tmp_path, record, snapshot) == first
    assert path.read_bytes() == saved
    assert record == original


# The actual research builder captures both opinions before immutable publication.
def test_real_builder_records_entry_inputs(tmp_path, monkeypatch):
    record, snapshot, economic, panel, now = inputs()
    length = int(np.searchsorted(panel.dates, np.datetime64(record["session"]))) + 1
    prior = replace(
        panel,
        dates=panel.dates[:length],
        **{
            field: getattr(panel, field)[:length].copy()
            for field in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    monkeypatch.setattr(intraday_research, "book_panel", lambda *args: (prior, {}))
    monkeypatch.setattr(intraday_research.economics, "load", lambda *args: economic)
    built = intraday_research.build(tmp_path, record, snapshot, now)
    assert built["entry_evidence"]["observed_at"] == built["as_of"]
    assert set(built["entry_evidence"]["rows"]) == set(record["grades"])
    assert len(built["policy_sha256"]) == 64
    for name, row in built["entry_evidence"]["rows"].items():
        assert row["price_setup"] == built["entry_states"][name]
        assert row["grade"] == built["grades"][name]["grade_live"]
    json.dumps(built, allow_nan=False)


# After the scheduled early close there cannot be a new regular-session signal.
def test_early_close_rejects_fictitious_afternoon_bar():
    record, _, panel, observed = sample()
    day = np.datetime64("2026-11-27")
    panel = replace(panel, dates=panel.dates + (day - panel.dates[-1]))
    record["session"] = "2026-11-25"
    observed.update(
        as_of="2026-11-27T18:16:00+00:00",
        bar="2026-11-27T18:00:00+00:00",
        valid_until="2026-11-27T18:30:00+00:00",
    )
    with pytest.raises(ValueError, match="completed"):
        entry_evidence.capture(panel, record, observed)


# Older candles remain explicitly unrecorded rather than gaining fabricated receipts.
def test_legacy_candle_does_not_gain_reconstructed_evidence(tmp_path, monkeypatch):
    record, snapshot, panel, observed = sample()
    observed["record_sha256"] = intraday_research.record_hash(record)
    monkeypatch.setattr(intraday_research, "build", lambda *args: deepcopy(observed))
    first = intraday_research.publish(tmp_path, record, snapshot)
    assert "entry_evidence" not in first
    path = next(tmp_path.rglob("decision-*.json"))
    original = path.read_bytes()
    observed["entry_evidence"] = entry_evidence.capture(panel, record, observed)
    repeated = intraday_research.publish(tmp_path, record, snapshot)
    assert "entry_evidence" not in repeated
    assert path.read_bytes() == original


# Changing personal or paper holdings cannot change this unfunded price comparison.
def test_account_data_is_neither_used_nor_captured():
    record, _, panel, observed = sample()
    original = entry_evidence.capture(panel, record, observed)
    record["paper"] = {"cash": 54321, "positions": [{"symbol": "S0", "qty": 9000}]}
    changed = entry_evidence.capture(panel, record, observed)
    assert changed == original
    assert "54321" not in json.dumps(changed)
