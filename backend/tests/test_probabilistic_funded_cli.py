"""Pin ex-ante price attribution and the fixed funded comparison schedule."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.cli import market_probabilistic_funded_timing as runner


# Supply a causal requested quantity deliberately different from its later fill.
def intent(*, side="buy", price=11.0, filled=1.0, symbol="AAA"):
    return {
        "intent_id": f"0/2026-09-01/{symbol}",
        "date": "2026-09-01",
        "symbol": symbol,
        "side": side,
        "initial_shares": 0 if side == "buy" else 8,
        "desired_shares": 8 if side == "buy" else 0,
        "realized_price": price,
        "filled_delta": filled,
    }


# Price attribution uses quantities known when planned, never favorable later fills.
@pytest.mark.parametrize(
    ("side", "cost", "expected"), [("buy", 10, 8.008), ("sell", 25, 7.98)]
)
def test_requested_quantity_attribution(side, cost, expected):
    old = intent(side=side, price=11 if side == "buy" else 10)
    new = intent(side=side, price=10 if side == "buy" else 11)
    result = runner.fixed_quantity_attribution(
        {"intent_trace": [old]}, {"intent_trace": [new]}, cost
    )
    assert result["paired_price_gain_initial_nav_units"] == pytest.approx(expected)
    assert result["rows"][0]["planned_quantity"] == 8
    assert result["rows"][0]["control_cash_limited_or_partial"]
    assert result["investable_counterfactual"] is False
    changed = deepcopy(new)
    changed["filled_delta"] = 0
    assert (
        runner.fixed_quantity_attribution(
            {"intent_trace": [old]}, {"intent_trace": [changed]}, cost
        )["paired_price_gain_initial_nav_units"]
        == result["paired_price_gain_initial_nav_units"]
    )


# Keep missing prices and opposite directions without fabricated gains.
@pytest.mark.parametrize(
    ("boundary", "status"),
    [
        ("absent", "no_candidate_plan"),
        ("opposite", "different_side"),
        ("control", "missing_control_price"),
        ("candidate", "missing_candidate_price"),
    ],
)
def test_missing_attribution_retained(boundary, status):
    old, new = intent(), intent(price=10)
    if boundary == "opposite":
        new["side"] = "sell"
    if boundary == "control":
        old["realized_price"] = None
    if boundary == "candidate":
        new["realized_price"] = None
    result = runner.fixed_quantity_attribution(
        {"intent_trace": [old]},
        {"intent_trace": [] if boundary == "absent" else [new]},
        10,
    )
    assert result["statuses"] == {status: 1}
    assert result["rows"][0]["price_component_gain"] is None
    assert result["paired_price_gain_initial_nav_units"] == 0


# A duplicated event cannot silently replace another in the attribution join.
def test_duplicate_candidate_rejected():
    with pytest.raises(ValueError, match="Duplicate"):
        runner.fixed_quantity_attribution(
            {"intent_trace": [intent()]}, {"intent_trace": [intent(), intent()]}, 0
        )


# Build all registered phase scores with explicit benchmark comparisons.
def schedule():
    rows = []
    for method in runner.METHODS:
        for cost in runner.primary.COSTS:
            for phase in range(20):
                scores = {}
                for name, gain in (
                    ("candidate", 3),
                    ("control", 2),
                    ("SPY", 1),
                    ("QQQ", 4),
                ):
                    scores[name] = {
                        "windows": [
                            {
                                "window": window,
                                "status": "measured",
                                "total_net_gain": gain,
                                "cagr": 0.2,
                                "max_drawdown_loss": 0.3,
                                "sharpe": 1,
                                "gross_traded_weight_per_year": 2,
                                "fees_initial_nav_units": 0.1,
                            }
                            for window in ("all", "2018-20", "2021-26", "reused_recent")
                        ]
                    }
                rows.append(
                    {
                        "method": method,
                        "cost_bps": cost,
                        "phase": phase,
                        "scores": scores,
                    }
                )
    return rows


# Preserve unfavorable benchmarks and every overlapping phase.
def test_complete_summary():
    result = runner.summarize(schedule())
    assert len(result) == 6
    for row in result:
        assert row["phases"] == 20
        for window in row["windows"]:
            assert window["paired_gain"]["control"]["positive_phases"] == 20
            assert window["paired_gain"]["QQQ"]["positive_phases"] == 0
            assert window["paired_gain"]["QQQ"]["median_gain_difference"] == -1


# Missing schedules or windows cannot disappear behind otherwise positive medians.
@pytest.mark.parametrize("boundary", ["missing", "reordered", "unavailable"])
def test_incomplete_summary_refused(boundary):
    rows = schedule()
    if boundary == "missing":
        rows.pop()
    elif boundary == "reordered":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0]["scores"]["candidate"]["windows"][2]["status"] = "unavailable"
    with pytest.raises(ValueError, match="fixed120|Missing window"):
        runner.summarize(rows)


# A prior output is refused before any historical input or account is touched.
def test_existing_output_not_restarted(tmp_path, monkeypatch):
    # Surface an accidental load or replay as a failure, not a passing mock assertion.
    def forbidden(*args, **kwargs):
        raise AssertionError("Historical account path must not run")

    monkeypatch.setattr(runner.primary, "load_inputs", forbidden)
    monkeypatch.setattr(runner.replay, "account", forbidden)
    with pytest.raises(ValueError, match="Fresh"):
        runner.evaluate(SimpleNamespace(output=tmp_path))


# Broken original diagnostic hashes stop before creating output or loading an account.
def test_evidence_failure_has_no_output(tmp_path, monkeypatch):
    # Preserve the real evidence reader while forbidding any account invocation.
    def forbidden(*args, **kwargs):
        raise AssertionError("No account may run after invalid evidence")

    monkeypatch.setattr(runner.replay, "account", forbidden)
    directory = tmp_path / "diagnostic"
    directory.mkdir()
    (directory / "report.json").write_text("{}")
    output = tmp_path / "output"
    args = SimpleNamespace(
        output=output, diagnostic=directory, probability_proof=tmp_path / "proof"
    )
    with pytest.raises(ValueError, match="Original bytes"):
        runner.evaluate(args)
    assert not output.exists()
