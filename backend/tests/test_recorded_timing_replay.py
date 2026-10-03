"""Pin method selection and the funded historical account boundary."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import recorded_timing_replay as replay


# Keep opposite-side model decisions and the current gate distinct on the same prefix.
def test_selection_retains_duplicate_intentions_and_distinct_methods(monkeypatch):
    intents = [
        dict(id="a", symbol="X", side="buy", qty=2),
        dict(id="b", symbol="X", side="buy", qty=3),
        dict(id="c", symbol="X", side="sell", qty=1),
    ]
    inputs = SimpleNamespace(
        session=date(2026, 10, 1),
        intents=intents,
        cubes={"X": object()},
        context=SimpleNamespace(
            panel=None, grades=None, eligible=None, published_at={}
        ),
    )

    # Check that repeated orders share the same observed decision.
    def observe(*args, **kwargs):
        clock = args[4]
        return SimpleNamespace(
            clock=clock,
            valid=True,
            raw_price=100,
            supported=True,
            legacy_triggered={"buy": clock >= 7, "sell": clock >= 9},
        )

    # Make learned buying and selling occur at different predeclared clocks.
    def decide(observation, model, side):
        return {
            "state": "execute"
            if observation.clock >= (3 if side == "buy" else 5)
            else "wait"
        }

    monkeypatch.setattr(replay.shadow, "observe", observe)
    monkeypatch.setattr(replay.shadow, "decide", decide)
    selected, decisions = replay.select_attempts(inputs, None)
    assert selected == {
        "learned": {"a": 3, "b": 3, "c": 5},
        "gate": {"a": 7, "b": 7, "c": 9},
        "first_available": {"a": 0, "b": 0, "c": 0},
    }
    assert len(decisions) == 25


# A missing locked execution price must not turn into a favorable later retry.
def test_missing_price_locks_and_retains_denominator():
    opens = np.full(26, 50.0)
    opens[1] = np.nan
    result = replay.replay(
        100,
        {},
        [dict(id="a", symbol="X", side="buy", qty=2)],
        {"a": 0},
        {"X": opens},
        {"X": 50},
        {"X": 60},
        10,
        1,
    )
    assert result["ledger"][0]["status"] == "missing_execution_price"
    assert result["ledger"][0]["filled_qty"] == 0
    assert result["cash"] == 100
    assert result["net_gain"] == 0


# A sale cannot create initial-cash capacity for an otherwise unfunded buy.
def test_sale_does_not_fund_buys_and_fees_reconcile():
    intents = [
        dict(id="s", symbol="X", side="sell", qty=1),
        dict(id="b", symbol="Y", side="buy", qty=1),
    ]
    result = replay.replay(
        0,
        {"X": 1},
        intents,
        {"s": 0, "b": 1},
        {"X": np.full(26, 110), "Y": np.full(26, 20)},
        {"X": 100, "Y": 20},
        {"X": 115, "Y": 25},
        25,
        1,
    )
    assert [row["filled_qty"] for row in result["ledger"]] == [1, 0]
    assert result["fees"] == 0.275
    assert result["cash"] == 109.725
    assert result["end_wealth"] == 109.725


# Refuse a replacement archive before loading a model or producing any scores.
def test_cli_rejects_replacement_record_before_inference(tmp_path, monkeypatch):
    from backend.cli import market_recorded_timing as cli

    monkeypatch.setattr(
        "sys.argv",
        [
            "recorded",
            "--market-root",
            str(tmp_path),
            "--models",
            str(tmp_path),
            "--output",
            str(tmp_path / "output"),
        ],
    )

    # Return an unregistered archive while retaining the intended calendar dates.
    def load(root, session):
        return SimpleNamespace(
            session=date.fromisoformat(session),
            provenance={"record_sha256": "replacement"},
        )

    # Make unexpected model use fail independently of the record rejection.
    def model(root):
        pytest.fail("Replacement record reached inference")

    monkeypatch.setattr(cli.recorded_timing_inputs, "load", load)
    monkeypatch.setattr(cli.sequential_execution_shadow, "load_model", model)
    with pytest.raises(ValueError, match="preregistered"):
        cli.main()
    assert not (tmp_path / "output" / "report.json").exists()
