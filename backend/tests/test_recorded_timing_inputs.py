"""Pin strict recorded identities and explicit raw SIP reference proxies."""

import hashlib
import json
from datetime import datetime, time, timedelta
from types import SimpleNamespace

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market import calendar
from backend.market import recorded_timing_inputs as inputs


# Persist a synthetic parquet file with its original explicit metadata.
def write_table(path, columns, metadata=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table(columns)
    if metadata is not None:
        table = table.replace_schema_metadata(
            {key.encode(): value.encode() for key, value in metadata.items()}
        )
    pq.write_table(table, path)


# Supply a complete raw session whose optional closing row has a different price.
def write_sip(path, symbol, day, last):
    opening = datetime.combine(day, time(9, 30), calendar.NEW_YORK)
    starts = [(opening + timedelta(minutes=15 * i)).isoformat() for i in range(27)]
    prices = [10.0] * 26 + [999.0]
    prices[25] = last
    metadata = {
        "ticker": symbol,
        "kind": "bars_15m_sip",
        "source": "alpaca-sip",
        "feed": "sip",
        "adjustment": "raw",
        "timeframe": "15Min",
        "session_date": str(day),
        "session_close": "16:00:00",
        "bars_expected": "26",
        "bar_count": "26",
        "complete": "true",
        "schema": "2",
        "auction_bar": "true",
        "source_revision": "fixture-revision",
        "fetched_at": (opening + timedelta(hours=11)).isoformat(),
    }
    write_table(
        path,
        {
            "start": starts,
            **dict.fromkeys(("open", "high", "low", "close"), prices),
            "volume": [1.0] * 27,
        },
        metadata,
    )


# Build an archived account while isolating the already-tested daily context loader.
@pytest.fixture
def market(tmp_path, monkeypatch):
    prior = datetime.fromisoformat("2026-09-30").date()
    session = datetime.fromisoformat("2026-10-01").date()
    plan = {
        "symbol": "AAA",
        "side": "buy",
        "qty": 1,
        "execute_on": str(session),
        "reason": "original reason",
        "kind": "redeploy",
    }
    record = {
        "session": str(prior),
        "written": "2026-09-30T23:45:49+00:00",
        "paper": {
            "session": str(prior),
            "written": "2026-09-30T23:45:03+00:00",
            "cash": 100.0,
            "positions": [{"symbol": "AAA", "qty": 2.0}],
            "planned": [plan, dict(plan)],
        },
    }
    path = tmp_path / "desk" / f"asof={prior}" / "desk.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(record))
    for symbol in ("AAA", "SPY", "QQQ"):
        for day, last in ((prior, 11.0), (session, 12.0)):
            write_sip(
                tmp_path / "bars_15m_sip" / f"asof={day}" / f"{symbol}.parquet",
                symbol,
                day,
                last,
            )
        write_table(
            tmp_path / "actions" / f"asof={session}" / f"{symbol}.parquet",
            {
                "action_date": pa.array([], type=pa.string()),
                "kind": pa.array([], type=pa.string()),
                "value": pa.array([], type=pa.float64()),
            },
        )

    # Assert the wrapper uses prior-specific context and a labelled historical clock.
    def context(record_path, partition, requested, captured):
        assert record_path == path
        assert partition.name == "asof=2026-09-30"
        assert requested == session
        assert captured == datetime.combine(session, time(9, 45), calendar.NEW_YORK)
        return SimpleNamespace(provenance={"sources": {}})

    monkeypatch.setattr(inputs.history, "load_context", context)
    return tmp_path, session, path


# Preserve duplicates and never use the optional closing row as an anchor or mark.
def test_strict_recorded_basket_and_reference_proxies(market):
    root, session, path = market
    before = {file: file.read_bytes() for file in root.rglob("*") if file.is_file()}
    result = inputs.load(root, session)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert result.holdings == {"AAA": 2}
    assert result.initial_cash == 100.0
    assert [row["id"] for row in result.intents] == [f"{digest}:0", f"{digest}:1"]
    assert [row["reason"] for row in result.intents] == ["original reason"] * 2
    assert [row["kind"] for row in result.intents] == ["redeploy"] * 2
    assert result.initial_marks == dict.fromkeys(("AAA", "QQQ", "SPY"), 11.0)
    assert result.final_marks == dict.fromkeys(("AAA", "QQQ", "SPY"), 12.0)
    assert result.cubes["AAA"].prior_close[0] == 11.0
    assert np.isnan(result.cubes["AAA"].auction_open).all()
    assert not result.cubes["AAA"].close.flags.writeable
    assert result.provenance["context_clock_is_synthetic"] is True
    assert result.provenance["historical_prefix_receipts_available"] is False
    assert result.provenance["training_prior_anchor_equivalent"] is False
    assert result.provenance["corporate_actions_publication_verified"] is False
    assert result.provenance["absence_of_corporate_actions_proven"] is False
    assert before == {file: file.read_bytes() for file in before}


# Reject any invalid account or planned row rather than silently selecting a subset.
@pytest.mark.parametrize(
    "change",
    ["fractional_position", "duplicate_position", "cash", "qty", "side", "session"],
)
def test_invalid_recorded_rows_rejected(market, change):
    root, session, path = market
    record = json.loads(path.read_text())
    paper = record["paper"]
    if change == "fractional_position":
        paper["positions"][0]["qty"] = 2.5
    elif change == "duplicate_position":
        paper["positions"].append(dict(paper["positions"][0]))
    elif change == "cash":
        paper["cash"] = -1
    elif change == "qty":
        paper["planned"][1]["qty"] = True
    elif change == "side":
        paper["planned"][1]["side"] = "unknown"
    else:
        paper["planned"][1]["execute_on"] = "2026-10-02"
    path.write_text(json.dumps(record))
    with pytest.raises(
        ValueError, match="whole|Duplicate|cash|quantity|side|actual session"
    ):
        inputs.load(root, session)


# Reject malformed, duplicate or reordered source grids before feature preparation.
@pytest.mark.parametrize(
    "change",
    ["duplicate", "unordered", "price", "numeric_string", "adjusted", "late_prior"],
)
def test_invalid_sip_evidence_rejected(market, change):
    root, session, _ = market
    day = "2026-09-30" if change == "late_prior" else str(session)
    path = root / "bars_15m_sip" / f"asof={day}" / "AAA.parquet"
    table = pq.ParquetFile(path).read()
    columns = table.to_pydict()
    metadata = {
        key.decode(): value.decode() for key, value in table.schema.metadata.items()
    }
    if change == "duplicate":
        columns["start"][1] = columns["start"][0]
    elif change == "unordered":
        columns["start"][0], columns["start"][1] = (
            columns["start"][1],
            columns["start"][0],
        )
    elif change == "price":
        columns["low"][0] = 0.0
    elif change == "numeric_string":
        columns["open"] = [str(value) for value in columns["open"]]
    elif change == "adjusted":
        metadata["adjustment"] = "all"
    else:
        metadata["fetched_at"] = "2026-10-01T14:00:00+00:00"
    write_table(path, columns, metadata)
    with pytest.raises(ValueError, match="SIP|grid|publication"):
        inputs.load(root, session)


# An action in the consumed basis interval prevents a unsupported raw-basis comparison.
def test_action_affected_interval_rejected(market):
    root, session, _ = market
    write_table(
        root / "actions" / f"asof={session}" / "AAA.parquet",
        {"action_date": [str(session)], "kind": ["split"], "value": [2.0]},
    )
    with pytest.raises(ValueError, match="Corporate action"):
        inputs.load(root, session)


# Final readback detects changing records instead of mixing two account snapshots.
def test_concurrent_source_change_rejected(market, monkeypatch):
    root, session, path = market
    original = inputs.history._check_unchanged

    # Change the parsed synthetic source to exercise the immutable-byte guard.
    def changed(sources):
        path.write_text(path.read_text() + " ")
        original(sources)

    monkeypatch.setattr(inputs.history, "_check_unchanged", changed)
    with pytest.raises(ValueError, match="Concurrent source"):
        inputs.load(root, session)
