"""Account proposals must stay distinct from learned forecasts and cash funding."""

import numpy as np
import pytest

from backend.market.retention_replay import RetentionAdapter


# Supply a fixed B holding, A recipient and separately available market forecast.
def _adapter(*, own=0.10, recipient=0.0, spy=0.0, unconditional=False):
    return RetentionAdapter(
        ("BETA", "ALPHA"),
        np.ones((1, 2), dtype=bool),
        np.array([[own, recipient]]),
        np.array([spy]),
        10,
        unconditional=unconditional,
    )


# A retained ordinary B exit is removed and purchase-blocked, never added to.
def test_midcycle_compares_actual_rotation_and_blocks_retained_additions():
    adapter = _adapter()
    finished, blocked, caps = adapter.midcycle(
        0,
        {"BETA": 10, "ALPHA": 10},
        {"BETA": 1, "ALPHA": 1},
        {"BETA": "B", "ALPHA": "A"},
        {"BETA": "grade rotation"},
        set(),
        100,
        80,
    )
    assert finished == {}
    assert blocked == {"BETA"}
    assert caps == {"BETA": 1}
    assert adapter.events[-1]["reason"] == "retain"


# An unavailable stock or required cash forecast preserves the original exit.
@pytest.mark.parametrize(
    ("own", "recipient", "spy"), [(np.nan, 0, 0), (0.1, np.nan, 0), (0.1, 0, np.nan)]
)
def test_unavailable_forecast_keeps_incumbent_proposal(own, recipient, spy):
    adapter = _adapter(own=own, recipient=recipient, spy=spy)
    finished = {"BETA": "grade rotation"}
    actual = adapter.midcycle(
        0,
        {"BETA": 10, "ALPHA": 10},
        {"BETA": 1, "ALPHA": 1},
        {"BETA": "B", "ALPHA": "A"},
        finished,
        set(),
        100,
        80,
    )
    assert actual == (finished, set(), {})


# Stronger recipients and mandatory exits continue through the ordinary planner.
@pytest.mark.parametrize(
    ("reason", "recipient"), [("grade rotation", 0.5), ("thesis failed", 0)]
)
def test_replacement_or_mandatory_exit_is_preserved(reason, recipient):
    adapter = _adapter(recipient=recipient)
    finished = {"BETA": reason}
    assert adapter.midcycle(
        0,
        {"BETA": 10, "ALPHA": 10},
        {"BETA": 1, "ALPHA": 1},
        {"BETA": "B", "ALPHA": "A"},
        finished,
        set(),
        100,
        80,
    ) == (finished, set(), {})


# The mechanical control retains B without supplying fictitious model predictions.
def test_unconditional_control_does_not_need_forecasts():
    adapter = _adapter(own=np.nan, recipient=np.nan, spy=np.nan, unconditional=True)
    actual = adapter.midcycle(
        0,
        {"BETA": 10, "ALPHA": 10},
        {"BETA": 1, "ALPHA": 1},
        {"BETA": "B", "ALPHA": "A"},
        {"BETA": "grade rotation"},
        set(),
        100,
        80,
    )
    assert actual == ({}, {"BETA"}, {"BETA": 1})


# Reset retention reserves the held B and retains the original A basket's cap.
def test_reset_reserves_without_fabricating_sale_cash():
    adapter = _adapter()
    actual = adapter.reset(
        0,
        np.array([0, 0.25]),
        np.array([10, 10]),
        np.array([1, 1]),
        80,
        np.array([1, 2]),
        np.zeros(2, dtype=bool),
    )
    np.testing.assert_array_equal(actual, [0.1, 0.25])


# Missing forecasts must preserve even unusual valid incumbent target bytes exactly.
def test_reset_unavailable_is_exact_passthrough():
    adapter = _adapter(own=np.nan)
    target = np.array([0, 0.23456789012345])
    actual = adapter.reset(
        0,
        target,
        np.array([10, 10]),
        np.array([1, 1]),
        80,
        np.array([1, 2]),
        np.zeros(2, dtype=bool),
    )
    assert actual.tobytes() == target.tobytes()


# Unconditional retention works when no eligible A destination exists.
def test_reset_cash_only_can_preserve_eligible_b():
    adapter = _adapter(unconditional=True)
    actual = adapter.reset(
        0,
        np.zeros(2),
        np.array([10, 10]),
        np.array([1, 0]),
        90,
        np.array([1, 0]),
        np.zeros(2, dtype=bool),
    )
    np.testing.assert_array_equal(actual, [0.1, 0])


# A name above the hold cap is trimmed and a known blocked recipient stays cash.
def test_retention_caps_and_cash_forecast_are_account_relative():
    adapter = _adapter(own=0.2)
    actual = adapter.midcycle(
        0,
        {"BETA": 10, "ALPHA": 10},
        {"BETA": 4, "ALPHA": 1},
        {"BETA": "B", "ALPHA": "A"},
        {"BETA": "grade rotation"},
        {"ALPHA"},
        100,
        50,
    )
    assert actual == ({}, {"ALPHA", "BETA"}, {"BETA": 2.5})


# An existing purchase-blocked A remains reserved without receiving fresh capital.
@pytest.mark.parametrize("unconditional", [False, True])
def test_reset_keeps_blocked_a_reserve(unconditional):
    adapter = _adapter(unconditional=unconditional)
    actual = adapter.reset(
        0,
        np.array([0, 0.1]),
        np.array([10, 10]),
        np.array([1, 1]),
        80,
        np.array([1, 2]),
        np.array([False, True]),
    )
    np.testing.assert_array_equal(actual, [0.1, 0.1])


# Unavailable learned inputs preserve complete funded event histories across costs.
@pytest.mark.parametrize("cost", [0, 10, 25])
def test_unavailable_adapter_has_identical_funded_journal(cost):
    from backend.agents.trading.desk import simulate
    from backend.market.research_journal import ResearchJournal
    from backend.market.research_journal_replay import verify_snapshot
    from backend.tests.test_learned_retention_simulator_hook import (
        options,
        report_fixture,
    )

    report = report_fixture()
    panel = report.panel
    eligible = np.ones(panel.close.shape, dtype=bool)
    eligible[:, -1] = False
    adapter = RetentionAdapter(
        panel.tickers,
        eligible,
        np.full(panel.close.shape, np.nan),
        np.full(len(panel.dates), np.nan),
        cost,
    )
    snapshots = []
    for hook in (None, adapter):
        journal = ResearchJournal(
            panel.dates,
            panel.tickers,
            simulate.adjusted_open(panel),
            panel.adj_close,
            run_id="fallback",
            account_id="same",
            policy_id="same",
            cost_bps=cost,
            provenance={"fixture": "funded-unavailable"},
        )
        args = options(report)
        args["cost_bps"] = cost
        simulate.run(report, **args, journal=journal, retention_adapter=hook)
        snapshot = journal.snapshot()
        assert verify_snapshot(snapshot)["ok"]
        snapshots.append(snapshot)
    assert snapshots[0] == snapshots[1]
