"""Fixed comparison denominators and compounded gain summary acceptance."""

import pytest

from backend.cli import market_normalized_continuation as cli


# Construct all declared phases with known complete window metrics.
def rows():
    output = []
    for cost in cli.primary.COSTS:
        for phase in range(20):
            metrics = {
                "total_net_gain": 0.2,
                "cagr": 0.1,
                "max_drawdown_loss": 0.05,
                "sharpe": 1.5,
                "turnover_one_way": 2.0,
                "fees_initial_nav_units": 0.01,
            }
            own = {"windows": [dict(metrics) for _ in range(4)]}
            output.append(
                {
                    "cost_bps": cost,
                    "phase": phase,
                    "candidate": {"score": own},
                    "comparison_scores": {
                        name: {
                            "windows": [
                                {**metrics, "total_net_gain": 0.1} for _ in range(4)
                            ]
                        }
                        for name in (
                            "control",
                            "linear",
                            "first_available",
                            "SPY",
                            "QQQ",
                        )
                    },
                }
            )
    return output


# Report paired account gain instead of model accuracy or selected winning phases.
def test_all_costs_phases_and_compounded_gain():
    result = cli.summarize(rows())
    assert [row["cost_bps"] for row in result] == [0, 10, 25]
    for cost in result:
        assert cost["phases"] == 20
        for window in cost["windows"]:
            assert window["median_candidate"]["max_drawdown_loss"] == 0.05
            for pair in window["paired"].values():
                assert pair["median_gain_difference"] == pytest.approx(0.1)
                assert pair["positive_phases"] == 20


# Refuse a missing phase rather than reporting a favorable subset as completion.
def test_missing_phase_rejected():
    with pytest.raises(ValueError, match="twenty"):
        cli.summarize(rows()[:-1])


# Require original saved control bytes before reading accounts or fitting models.
def test_first_control_byte_contract(tmp_path):
    path = tmp_path / "report.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Original completed"):
        cli.first_accounts(path, [], {})
