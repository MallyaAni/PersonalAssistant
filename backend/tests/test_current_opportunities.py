"""Preserve chart-prefix, policy and freshness boundaries for current judgments."""

import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.agents.trading import current_setup
from backend.core.llm import StrictSchema
from backend.market import current_opportunities as current
from backend.market.alpaca import IntradayBar


# Supply one authentic-shaped graded snapshot with an exact completed regular grid.
def evidence():
    now = datetime(2026, 10, 14, 14, 1, tzinfo=UTC)
    record = {
        "session": "2026-10-13",
        "grades": {
            "AAA": {
                "grade": "A+",
                "stances": {"fundamental": 1, "technical": 1, "sentiment": 1},
                "ranks": {"fundamental": 0.9, "technical": 0.9, "sentiment": 0.9},
            }
        },
    }
    snapshot = {
        "decision_session": record["session"],
        "as_of": "2026-10-14T14:00:20Z",
        "quotes": {"AAA": {"last": 102, "bar": "2026-10-14T13:45:00Z"}},
        "technical": {"AAA": {"now": 0.9, "close": 0.9, "stance": 1}},
        "technical_detail": {
            "AAA": {
                "short": {"support_level": 196, "support_distance": 0.04},
                "medium": {},
                "long": {},
            }
        },
    }
    bars = {
        "AAA": [
            IntradayBar(
                datetime(2026, 10, 14, 13, 30, tzinfo=UTC) + timedelta(minutes=15 * i),
                100,
                104,
                99,
                102,
                100,
            )
            for i in range(3)
        ]
    }
    return now, record, snapshot, bars


# Supply a controlled judgment without any broker or numerical-model call.
def judgment(fact):
    return {
        "ticker": fact["ticker"],
        "entry": "ready",
        "exit": "hold",
        "entry_priority": "high",
        "exit_priority": "low",
        "reason": "Buyers held the pullback above support.",
        "confirmation": "hold_above",
        "confirmation_ref": "vwap",
        "invalidation_ref": "support",
    }


# A partial candle is excluded and exact raw completed levels are conserved.
def test_current_facts_conserve_completed_prefix_and_sources():
    now, record, snapshot, bars = evidence()
    original = deepcopy(snapshot)
    facts = current.facts_for(record, snapshot, bars, now)
    assert len(facts) == 1
    assert len(facts[0]["candles"]) == 2
    assert facts[0]["levels"]["vwap"]["price"] == 102
    assert facts[0]["levels"]["session_low"]["price"] == 99
    assert facts[0]["levels"]["support"]["price"] == pytest.approx(97.92)
    assert snapshot == original
    assert current.facts_for(record, snapshot, bars, now + timedelta(minutes=15)) == []


# Missing or malformed grids never receive a current chart judgment.
@pytest.mark.parametrize("bad", ["missing_open", "missing_last", "bad_range"])
def test_current_facts_reject_incomplete_or_malformed_prices(bad):
    now, record, snapshot, bars = evidence()
    if bad == "missing_open":
        bars["AAA"] = bars["AAA"][1:]
    elif bad == "missing_last":
        bars["AAA"] = bars["AAA"][:1]
    else:
        bars["AAA"][0] = IntradayBar(bars["AAA"][0].start, 100, 90, 99, 102, 100)
    assert current.facts_for(record, snapshot, bars, now) == []


# Expire judgments without restamping their clocks or grade evidence.
def test_current_reader_expires_and_rejects_changed_sources(tmp_path):
    now, record, snapshot, bars = evidence()
    fact = current.facts_for(record, snapshot, bars, now)[0]
    folder = tmp_path / "desk/current-opportunities"
    folder.mkdir(parents=True)
    row = {
        **judgment(fact),
        "levels": fact["levels"],
        "price": fact["price"],
        "bar": fact["bar"],
        "valid_until": fact["valid_until"],
        "generated_at": now.isoformat(),
    }
    payload = {
        "version": current.VERSION,
        "source_id": current.identity(record, snapshot),
        "status": "complete",
        "rows": {"AAA": row},
    }
    (folder / "latest.json").write_text(json.dumps(payload))
    (folder / "inputs").mkdir()
    (folder / "inputs/latest.json").write_text(
        json.dumps({"source_id": payload["source_id"], "facts": [fact]})
    )
    original = (folder / "latest.json").read_bytes()
    assert current.read(tmp_path, record, snapshot, now)["rows"]["AAA"] == row
    assert (
        current.read(tmp_path, record, snapshot, now + timedelta(minutes=15))["rows"]
        == {}
    )
    changed = deepcopy(snapshot)
    changed["quotes"]["AAA"]["last"] += 1
    assert current.read(tmp_path, record, changed, now)["rows"] == {}
    assert (folder / "latest.json").read_bytes() == original


# Reject invented references, duplicate names, numbers and blocked entries.
@pytest.mark.parametrize("bad", ["reference", "duplicate", "number", "permission"])
def test_current_model_validation_rejects_ungrounded_answers(bad):
    now, record, snapshot, bars = evidence()
    fact = current.facts_for(record, snapshot, bars, now)[0]
    row = judgment(fact)
    rows = [row]
    if bad == "reference":
        row["confirmation_ref"] = "invented"
    elif bad == "duplicate":
        rows.append(row)
    elif bad == "number":
        row["reason"] = "Buy at a made-up price of 999 dollars."
    else:
        fact["entry_permitted"] = False
    with pytest.raises(
        ValueError,
        match=(
            "Unknown stock level|Incomplete judgment universe|"
            "Ungrounded judgment prose|Entry policy violation"
        ),
    ):
        current_setup.validate(rows, [fact])


# Change only the display store; never re-infer a successful candle.
def test_current_collector_publishes_and_deduplicates(tmp_path, monkeypatch):
    now, record, snapshot, bars = evidence()
    (tmp_path / "desk").mkdir()
    (tmp_path / "desk/live.json").write_text(json.dumps(snapshot))
    monkeypatch.setattr(current.deskrecord, "latest_pair", lambda root: (record, None))
    calls = []

    # Return controlled model output shaped by the exact supplied facts.
    class Writer:
        model = "controlled-model"

        # Record each inference so a duplicate pass cannot masquerade as persistence.
        def chat(self, messages, max_tokens, response_schema, temperature):
            assert isinstance(response_schema, StrictSchema)
            assert temperature == 0.0
            facts = json.loads(messages[-1]["content"])["stocks"]
            calls.append(facts)
            return {
                "content": json.dumps(
                    {"rows": {fact["ticker"]: judgment(fact) for fact in facts}}
                )
            }

    # Confirm the only provider request uses free raw IEX observations.
    def fetch(symbols, start, end, **kwargs):
        assert symbols == ["AAA"]
        assert kwargs == {"feed": "iex", "adjustment": "raw"}
        return bars

    original = (tmp_path / "desk/live.json").read_bytes()
    assert current.collect(tmp_path, Writer(), now=now, fetch=fetch)["rows"] == 1
    assert (
        current.read(tmp_path, record, snapshot, now)["rows"]["AAA"]["entry"] == "ready"
    )
    assert (
        current.collect(tmp_path, Writer(), now=now, fetch=fetch)["status"]
        == "unchanged"
    )
    assert len(calls) == 1
    assert (tmp_path / "desk/live.json").read_bytes() == original


# Recover partial inference without rerunning successful names.
def test_current_collector_failed_inference_can_recover(tmp_path, monkeypatch):
    now, record, snapshot, bars = evidence()
    (tmp_path / "desk").mkdir()
    (tmp_path / "desk/live.json").write_text(json.dumps(snapshot))
    monkeypatch.setattr(current.deskrecord, "latest_pair", lambda root: (record, None))
    calls = []

    # Fail once, then publish a grounded response from the same evidence.
    class Writer:
        model = "controlled-model"

        # Retain failed inference evidence without upgrading it into a judgment.
        def chat(self, messages, max_tokens, response_schema, temperature):
            assert isinstance(response_schema, StrictSchema)
            assert temperature == 0.0
            calls.append(1)
            if len(calls) == 1:
                raise TimeoutError()
            facts = json.loads(messages[-1]["content"])["stocks"]
            return {
                "content": json.dumps(
                    {"rows": {fact["ticker"]: judgment(fact) for fact in facts}}
                )
            }

    writer = Writer()
    assert (
        current.collect(tmp_path, writer, now=now, fetch=lambda *args, **kwargs: bars)[
            "rows"
        ]
        == 0
    )
    assert current.read(tmp_path, record, snapshot, now)["rows"] == {}
    assert (
        current.collect(
            tmp_path,
            writer,
            now=now + timedelta(seconds=61),
            fetch=lambda *args, **kwargs: bars,
        )["rows"]
        == 1
    )
    assert len(calls) == 2


# A missing provider grid is explicit and can recover without re-inferring successes.
def test_current_collector_recovers_missing_grid_and_keeps_original_facts(
    tmp_path, monkeypatch
):
    now, record, snapshot, bars = evidence()
    record["grades"]["BBB"] = deepcopy(record["grades"]["AAA"])
    for field in ("quotes", "technical", "technical_detail"):
        snapshot[field]["BBB"] = deepcopy(snapshot[field]["AAA"])
    (tmp_path / "desk").mkdir()
    (tmp_path / "desk/live.json").write_text(json.dumps(snapshot))
    monkeypatch.setattr(current.deskrecord, "latest_pair", lambda root: (record, None))
    calls = []

    # Record the supplied universe and return a grounded strict structured response.
    class Writer:
        model = "controlled-model"

        # Keep the inference receipt tied to only the names still missing a judgment.
        def chat(self, messages, max_tokens, response_schema, temperature):
            assert isinstance(response_schema, StrictSchema)
            assert temperature == 0.0
            facts = json.loads(messages[-1]["content"])["stocks"]
            calls.append([fact["ticker"] for fact in facts])
            return {
                "content": json.dumps(
                    {"rows": {fact["ticker"]: judgment(fact) for fact in facts}}
                )
            }

    writer = Writer()
    first = current.collect(tmp_path, writer, now=now, fetch=lambda *a, **k: bars)
    assert first == {"status": "collected", "rows": 1, "unavailable": 1}
    original = current.read(tmp_path, record, snapshot, now)["rows"]["AAA"]
    corrected = {"AAA": deepcopy(bars["AAA"]), "BBB": deepcopy(bars["AAA"])}
    old = corrected["AAA"][0]
    corrected["AAA"][0] = IntradayBar(old.start, 100, 105, 98, 101, 300)
    second = current.collect(
        tmp_path,
        writer,
        now=now + timedelta(seconds=61),
        fetch=lambda *a, **k: corrected,
    )
    assert second == {"status": "collected", "rows": 2, "unavailable": 0}
    result = current.read(tmp_path, record, snapshot, now + timedelta(seconds=61))
    assert result["rows"]["AAA"] == original
    assert set(result["rows"]) == {"AAA", "BBB"}
    assert calls == [["AAA"], ["BBB"]]
    assert current.read(tmp_path, record, snapshot, now + timedelta(minutes=15)) == {
        "status": "stale",
        "rows": {},
        "unavailable": {},
    }
