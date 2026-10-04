"""Actual nightly policy inputs retain causal prices and original supplied grades."""

from dataclasses import replace

import numpy as np
import pytest

from backend.agents.trading.desk import actions, event_risk, live_policy
from backend.market import live_execution_inputs, live_policy_report
from backend.market.panel import Panel


# Supply split-adjusted archived prices and explicitly known current membership.
def fixture():
    dates = np.array(["2026-09-14", "2026-09-15", "2026-09-16"], dtype="datetime64[D]")
    names = ("AAA", "BBB", "CCC", "QQQ", "SPY")
    closing = np.full((3, 5), 50.0)
    panel = Panel(
        dates,
        names,
        closing.copy(),
        closing + 1,
        closing - 1,
        closing.copy(),
        closing - 2,
        np.ones_like(closing),
        {"AAA": ("growth",), "BBB": ("growth",)},
        "SPY",
    )
    grades = np.array(
        [[-1, 1, 2, 3, -1], [2, -1, 2, 3, -1], [3, 2, 2, 3, -1]], dtype=np.int16
    )
    eligible = np.ones((3, 5), dtype=bool)
    eligible[:, 2] = False
    arguments = dict(
        panel=panel,
        grades=grades,
        eligible=eligible,
        cubes={},
        actions={
            name: (
                [{"date": "2026-09-15", "kind": "split", "value": 2}]
                if name == "AAA"
                else []
            )
            for name in names
        },
        basis_as_of="2026-09-16",
        complete_through="2026-09-16",
        provenance={"original_source": "synthetic"},
    )
    return arguments


# Invoke the real raw adapter before building the nightly report.
def report(arguments, day):
    raw = live_execution_inputs.prepare(**arguments)
    return live_policy_report.build(
        arguments["panel"], raw, arguments["grades"], arguments["eligible"], day
    )


# Unknown and ineligible names remain explicit exclusions, never fabricated grades.
def test_current_book_uses_known_eligible_grades_and_excludes_qqq():
    result = report(fixture(), 1)
    assert result.panel.tickers == ("AAA", "SPY")
    assert result.graded.letter(1, 0) == "A"
    assert result.graded.grades[0, 0] == -1
    assert "SPY" not in result.sides
    assert {row["ticker"]: row["reasons"] for row in result.excluded} == {
        "BBB": ("grade_unavailable",),
        "CCC": ("not_declared_eligible",),
        "QQQ": ("non_stock_benchmark",),
    }
    assert live_policy.targets(result) == {"AAA": 0.25}
    assert np.isnan(result.graded.votes).all()
    assert result.graded.stances == {}
    board = actions.build(result, live_policy.targets(result), {}, 0)
    assert board[0]["grade"] == "A"
    assert np.isnan(board[0]["grade_margin"])
    assert board[0]["stances"] == {}
    assert board[0]["why"] == board[0]["reason"] == ""


# A pre-split decision rescales its whole history uniformly to current raw dollars.
def test_split_price_prefix_uses_current_share_basis_and_actual_panel_methods():
    args = fixture()
    args["grades"][0, 0] = 2
    before, after = report(args, 0), report(args, 1)
    assert before.panel.close[0, 0] == 100
    assert after.panel.close[:, 0].tolist() == [50, 50]
    assert after.panel.high[:, 0].tolist() == [51, 51]
    assert after.panel.adj_close[:, 0].tolist() == [48, 48]
    assert after.panel.log_returns()[1, 0] == 0
    assert after.panel.primary_theme("AAA") == "growth"
    assert np.isnan(after.panel.benchmark_returns()[0])
    assert event_risk.decision(after.panel)["session"] == "2026-09-15"


# Coherent later source changes cannot alter earlier report inputs or resulting actions.
def test_coherent_future_changes_preserve_prefix_and_action_outputs():
    args = fixture()
    first = report(args, 1)
    changed = fixture()
    p = changed["panel"]
    for field in ("open", "high", "low", "close", "adj_close", "volume"):
        getattr(p, field)[2] *= 3
    changed["grades"][2] = 0
    changed["eligible"][2] = False
    second = report(changed, 1)
    for field in ("dates", "open", "high", "low", "close", "adj_close", "volume"):
        np.testing.assert_array_equal(
            getattr(first.panel, field), getattr(second.panel, field)
        )
    np.testing.assert_array_equal(first.graded.grades, second.graded.grades)
    assert first.excluded == second.excluded
    assert live_policy.targets(first) == live_policy.targets(second)
    left = actions.build(first, live_policy.targets(first), {}, 0)
    right = actions.build(second, live_policy.targets(second), {}, 0)
    assert left[0]["action"] == right[0]["action"]
    assert left[0]["target_weight"] == right[0]["target_weight"]
    assert first.provenance["prefix_arrays"] == second.provenance["prefix_arrays"]


# A valid current grade without a closing mark stays unavailable rather than tradable.
def test_missing_current_close_is_retained_as_an_exclusion():
    args = fixture()
    for field in ("open", "high", "low", "close", "adj_close"):
        getattr(args["panel"], field)[1, 0] = np.nan
    result = report(args, 1)
    assert result.panel.tickers == ("SPY",)
    assert result.excluded[0] == {"ticker": "AAA", "reasons": ("close_unavailable",)}
    assert live_policy.targets(result) == {}


# Reports refuse stale source identity, changed grades, and absent membership evidence.
@pytest.mark.parametrize(
    "corruption", ["price", "grade", "membership", "provenance", "factor"]
)
def test_invalid_source_relationship_refuses(corruption):
    args = fixture()
    raw = live_execution_inputs.prepare(**args)
    if corruption == "price":
        args["panel"].close[1, 0] += 1
    elif corruption == "grade":
        args["grades"][1, 0] = 3
    elif corruption == "membership":
        args["eligible"] = np.ones((3, 5), dtype=float)
    elif corruption == "provenance":
        raw = replace(raw, provenance={})
    else:
        factors = raw.split_factors.copy()
        factors[1, 0] = 2
        raw = replace(raw, split_factors=factors)
    with pytest.raises(ValueError, match="required|identity|relationship"):
        live_policy_report.build(
            args["panel"], raw, args["grades"], args["eligible"], 1
        )


# The day must identify an existing completed-prefix row rather than a coerced boolean.
@pytest.mark.parametrize("day", [-1, 3, True, 1.0, "2026-09-15"])
def test_invalid_day_refuses(day):
    with pytest.raises(ValueError, match="day"):
        report(fixture(), day)


# Copied report arrays and themes cannot mutate the supplied original source.
def test_report_does_not_mutate_or_alias_source():
    args = fixture()
    copies = {
        field: getattr(args["panel"], field).copy()
        for field in ("open", "high", "low", "close", "adj_close", "volume")
    }
    result = report(args, 1)
    for field, original in copies.items():
        np.testing.assert_array_equal(getattr(args["panel"], field), original)
        assert not np.shares_memory(
            getattr(result.panel, field), getattr(args["panel"], field)
        )
    with pytest.raises(ValueError, match="read-only"):
        result.panel.close[0, 0] = 1
    result.panel.themes["AAA"] = ("changed",)
    assert args["panel"].themes["AAA"] == ("growth",)
    assert not hasattr(result, "book")
    assert not hasattr(result, "brief")
