"""Qualified inputs reach the actual desk and saved research evidence, never orders."""

import hashlib
import json
from dataclasses import replace
from datetime import UTC, date, datetime

import numpy as np
import pytest

from backend.agents.trading.desk import desk, fundamental
from backend.cli import market_daily, market_desk
from backend.market import fundamental_source_store as archive
from backend.market import fundamental_unit_sources as units
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore
from backend.market.universe import AI_COMPUTE, AI_SIDE, SOFTWARE, SOFTWARE_SIDE
from backend.tests.test_fundamental_current_path import _score_panel
from backend.tests.test_fundamental_period_eligibility import ALTERNATIVE, _history
from backend.tests.test_trading_desk import torch_loaders  # noqa: F401

ASOF = date(2026, 5, 7)
CAPTURED = datetime(2026, 5, 7, 18, tzinfo=UTC)


# Build original byte sources with independent canonical and legacy-tag histories.
def _source(peer=False, newer=False):
    versions = _history()
    facts = {}
    for version in versions:
        tag = ALTERNATIVE if version.name == "revenue" else version.tag
        value = (100 if version.name == "revenue" else 5) if peer else version.value
        row = {
            "start": str(version.start),
            "end": str(version.end),
            "val": value,
            "filed": str(version.filed),
            "accn": version.accession,
            "form": version.form,
        }
        facts.setdefault(tag.split(":")[1], {"units": {"USD": []}})["units"][
            "USD"
        ].append(row)
    # More old generic rows must not outrank the explicitly declared current concept.
    facts["Revenues"] = {
        "units": {
            "USD": [
                {
                    "start": "2024-01-01",
                    "end": "2024-03-31",
                    "val": 1,
                    "filed": "2024-05-01",
                    "accn": "older",
                    "form": "10-Q",
                },
            ]
        }
    }
    if newer:
        facts[ALTERNATIVE.split(":")[1]]["units"]["USD"].append(
            {
                "start": "2026-01-01",
                "end": "2026-03-31",
                "val": 150,
                "filed": "2026-05-01",
                "accn": "newer",
                "form": "10-Q",
            }
        )
    body = json.dumps({"cik": 2 if peer else 1, "facts": {"us-gaap": facts}}).encode()
    return units.parse(
        body,
        expected_sha256=hashlib.sha256(body).hexdigest(),
        expected_cik=2 if peer else 1,
    )


# Exercise archives alongside unchanged legacy versions in a temporary store.
def _store(root, newer=False):
    store = MarketStore(root)
    for ticker, peer in (("TEST", False), ("PEER", True)):
        source = _source(peer=peer, newer=newer and not peer)
        archive.save(store, ticker, ASOF, source, captured_at=CAPTURED)
        store.write_frame(
            fa.KIND, ASOF, ticker, fa.frame(fa.parse_versions(json.loads(source.body)))
        )
    return store


# Missing original archives cannot silently read the legacy unitless input contract.
def test_qualified_mode_refuses_legacy_only_inputs(tmp_path):
    store = MarketStore(tmp_path)
    store.write_frame(fa.KIND, ASOF, "TEST", fa.frame(_history()))
    with pytest.raises(fundamental.FundamentalSourceError, match="archive"):
        desk._fundamental_opinion(store, _score_panel(), ASOF, "qualified")


# A connected mode consumes persisted source bytes and records its distinct identity.
def test_qualified_store_to_opinion_never_calls_legacy_loader(tmp_path, monkeypatch):
    store = _store(tmp_path)

    # A hidden fallback would erase units and should fail this actual consumer path.
    def refuse(*args, **kwargs):
        raise AssertionError("qualified path read legacy versions")

    monkeypatch.setattr(fa, "load_versions", refuse)
    opinion = desk._fundamental_opinion(store, _score_panel(), ASOF, "qualified")
    assert opinion.meta["source"] == "fundamentals-qualified/1"
    assert desk._fundamental_source_id("qualified") == opinion.meta["source"]
    assert opinion.evidence["gross_margin"][-1, 0] == pytest.approx(0.3)
    assert np.isfinite(opinion.scores[-1, :2]).all()
    row = fundamental.cited_qualification(opinion, 5, 0)
    assert row["source_sha256"] == _source().sha256
    assert row["features"]["gross_margin"]["status"] == "accepted"
    assert row["features"]["gross_margin"]["period"] == {
        "start": "2025-10-01",
        "end": "2025-12-31",
        "unit": "USD",
    }
    assert row["historical_authenticity_verified"] is False
    assert row["archive"]["captured_at"] == CAPTURED.isoformat()


# Losing one scored input resets the prior vote even while enough growth legs survive.
def test_qualified_input_loss_resets_actual_persisted_stance(tmp_path):
    opinion = desk._fundamental_opinion(
        _store(tmp_path, newer=True), _score_panel(), ASOF, "qualified"
    )
    assert opinion.stance_resets[:, 0].tolist() == [
        False,
        False,
        False,
        True,
        False,
        False,
    ]
    assert opinion.stances()[:, 0].tolist() == [1, 1, 1, 0, 0, 1]
    assert np.isfinite(opinion.scores[:, 0]).all()
    assert np.isnan(opinion.evidence["gross_margin"][3:, 0]).all()


# The real report assembler and record writer retain both accepted and rejected names.
@pytest.mark.usefixtures("torch_loaders")
def test_actual_qualified_desk_record_roundtrip_preserves_old_records(
    tmp_path, monkeypatch
):
    store = _store(tmp_path / "store", newer=True)
    panel = _score_panel()
    panel = replace(panel, themes={"TEST": (AI_COMPUTE,), "PEER": (SOFTWARE,)})
    # Synthetic prices isolate filings; every downstream grade path is real.
    monkeypatch.setattr(
        desk,
        "book_panel",
        lambda *args: (panel, {"TEST": AI_SIDE, "PEER": SOFTWARE_SIDE}),
    )
    old = desk.run(store, ASOF, inputs=(), fundamentals="current")
    old_data = market_daily.record(old)
    old_path = market_daily.save(tmp_path / "previous", old_data)
    original = old_path.read_bytes()
    current = desk.run(store, ASOF, inputs=(), fundamentals="qualified")
    data = market_daily.record(current)
    assert data["fundamental"]["source"] == "fundamentals-qualified/1"
    assert set(data["fundamental"]["qualification"]) == {"TEST", "PEER"}
    assert set(data["fundamental"]["dates"]) == {"TEST", "PEER"}
    rejected = data["fundamental"]["qualification"]["TEST"]["features"]["gross_margin"]
    assert rejected["value"] is None
    assert rejected["status"] != "accepted"
    path = market_daily.save(tmp_path / "qualified", data)
    saved = path.read_bytes()
    assert json.loads(path.read_text())["fundamental"] == data["fundamental"]
    assert old_path.read_bytes() == original
    with pytest.raises(FileExistsError):
        market_daily.save(tmp_path / "qualified", data)
    assert path.read_bytes() == saved


# A distinct research source must never be saved under a current or legacy source label.
def test_qualified_record_rejects_mismatched_source(tmp_path):
    from backend.tests.test_market_daily import _report

    opinion = desk._fundamental_opinion(
        _store(tmp_path), _score_panel(), ASOF, "qualified"
    )
    report = replace(
        _report(),
        opinions={fundamental.NAME: opinion},
        fundamentals_source="fundamentals-features/3",
    )
    with pytest.raises(ValueError, match="source"):
        market_daily.record(report)


# The mode is deliberate and cannot change existing CLI or nightly defaults.
def test_qualified_cli_is_explicit_and_existing_modes_keep_their_identity():
    parser = market_desk.build_parser()
    assert (
        parser.parse_args(["--fundamentals", "qualified"]).fundamentals == "qualified"
    )
    assert parser.parse_args([]).fundamentals == "corrected"
    assert desk.run.__defaults__[-1] == "corrected"
    assert desk._fundamental_source_id("current") == "fundamentals-features/3"
    assert desk._fundamental_source_id("corrected") == "fundamentals-features/2"


# A new profile cannot silently activate a learner trained on different inputs.
def test_qualified_mode_refuses_legacy_learned_augmentations_before_loading(tmp_path):
    with pytest.raises(ValueError, match="inputs"):
        desk.run(MarketStore(tmp_path), ASOF, fundamentals="qualified")
    assert list(tmp_path.iterdir()) == []
