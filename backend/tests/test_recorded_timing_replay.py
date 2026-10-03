"""Pin method selection and the funded historical account boundary."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.market import recorded_timing_replay as replay
from backend.market.sip_cube import SessionCube


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

    # Supply the declared ordered observations without running feature preparation.
    def packets(inputs):
        observations = [observe(None, None, None, None, clock) for clock in range(25)]
        for item in observations:
            item.received_at = "2026-10-01T09:45:00-04:00"
        return {"X": observations}

    monkeypatch.setattr(replay, "_packets", packets)
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


# Supply a mature synthetic context and a single explicit raw current session.
@pytest.fixture
def prefix_case():
    session = date(2026, 10, 1)
    dates = np.busday_offset(np.datetime64(session), np.arange(-300, 2))
    names = ("X", "SPY", "QQQ")
    prices = np.tile(10 * np.exp(np.arange(len(dates))[:, None] / 1000), (1, 3))
    context = SimpleNamespace(
        panel=SimpleNamespace(dates=dates, tickers=names, adj_close=prices),
        grades=np.full(prices.shape, 3),
        eligible=np.ones(prices.shape, dtype=bool),
        published_at={
            name: datetime(2026, 9, 30, 20, tzinfo=replay.calendar.NEW_YORK)
            for name in ("history", "grades", "membership")
        },
    )
    opened = (10 + np.arange(26) / 100)[None]
    cube = SessionCube(
        "X",
        np.array([session], dtype="datetime64[D]"),
        opened,
        opened + 0.05,
        opened - 0.05,
        opened + 0.01,
        np.full((1, 26), 100.0),
        np.array([10.0]),
        {},
        np.array([np.nan]),
        np.array([np.nan]),
    )
    return SimpleNamespace(
        session=session,
        context=context,
        cubes={"X": cube},
        intents=[dict(id="x", symbol="X", side="buy", qty=1)],
    )


# Pin every batched feature, validity and gate to the original cropped-prefix bridge.
def test_batched_prefixes_exactly_match_original_bridge(prefix_case):
    inputs = prefix_case
    before = inputs.context.panel.adj_close.copy()
    packets = replay._packets(inputs)["X"]
    for clock, batch in enumerate(packets):
        original = replay.shadow.observe(
            inputs.context.panel,
            inputs.context.grades,
            inputs.context.eligible,
            inputs.cubes["X"],
            clock,
            datetime.fromisoformat(batch.received_at),
            published_at=inputs.context.published_at,
            feed="sip",
        )
        np.testing.assert_array_equal(batch.features, original.features)
        assert batch.valid == original.valid
        assert batch.raw_price == original.raw_price
        assert batch.legacy_triggered == original.legacy_triggered
        assert batch.supported == original.supported
    np.testing.assert_array_equal(inputs.context.panel.adj_close, before)


# Later candles and future daily rows cannot change an earlier batched observation.
def test_batched_prefix_is_invariant_to_future_values(prefix_case):
    inputs = prefix_case
    original = replay._packets(inputs)["X"]
    for field in ("open", "high", "low", "close", "volume"):
        getattr(inputs.cubes["X"], field)[0, 8:] *= 100
    inputs.context.panel.adj_close[-1] *= 1000
    changed = replay._packets(inputs)["X"]
    for clock in range(8):
        np.testing.assert_array_equal(original[clock].features, changed[clock].features)
        assert original[clock].valid == changed[clock].valid
        assert original[clock].legacy_triggered == changed[clock].legacy_triggered


# A context published after the first decision cannot enter the batched preparation.
def test_batched_prefix_rejects_late_context(prefix_case):
    prefix_case.context.published_at["grades"] = datetime(
        2026, 10, 1, 10, tzinfo=replay.calendar.NEW_YORK
    ) + timedelta(seconds=1)
    with pytest.raises(ValueError, match="published"):
        replay._packets(prefix_case)
