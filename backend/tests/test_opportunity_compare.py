"""The old-versus-new comparison reads two runs and derives the same metrics.

What has to hold: turnover is the sum of the decisions' traded fraction,
cash exposure the mean of their target cash, gross its complement, and
excess returns are against the same run's SPY and equal-weight rows.
"""

import json

from backend.cli import market_opportunity_compare as cmp


def _run(tmp_path, name, neural_return, spy_return, equal_return):
    run = tmp_path / name
    run.mkdir()

    def result(total, decisions):
        return {
            "metrics": {
                "log_growth": 0.0,
                "total_return": total,
                "drawdown": -0.1,
                "transitions": 5,
            },
            "decisions": decisions,
        }

    results = {
        "validation_log_growth": {"neural": 0.1, "SPY": 0.05},
        "validation_winner": "neural",
        "neural_selection": {"selected_epoch": 10},
        "results": {
            "neural@10bps": result(
                neural_return,
                [
                    {"target_cash": 0.2, "turnover": 0.9},
                    {"target_cash": 0.0, "turnover": 0.5},
                ],
            ),
            "SPY@10bps": result(spy_return, [{"target_cash": 0.0, "turnover": 1.0}]),
            "equal@10bps": result(
                equal_return, [{"target_cash": 0.1, "turnover": 1.0}]
            ),
        },
    }
    (run / "results.json").write_text(json.dumps(results))
    (run / "manifest.json").write_text(
        json.dumps(
            {
                "source": "abc",
                "feature_sha256": "f" * 64,
                "price_sha256": "p" * 64,
                "financial_coverage": 0.8,
                "train_examples": 10,
                "test_first": "2025-01-02",
                "test_last": "2026-09-11",
            }
        )
    )
    return run


def test_summary_derives_turnover_exposure_and_excess(tmp_path):
    old = cmp.summarize(_run(tmp_path, "old", 0.30, 0.10, 0.20))
    row = old["policies"]["neural@10bps"]
    assert row["turnover_total"] == 1.4
    assert row["turnover_per_decision"] == 0.7
    assert row["cash_exposure"] == 0.1
    assert row["gross_exposure"] == 0.9
    assert row["excess_vs_spy"] == 0.30 - 0.10
    assert row["excess_vs_equal"] == 0.30 - 0.20
    assert old["fingerprints"]["fundamentals"] == "frozen"
    new = cmp.summarize(_run(tmp_path, "new", 0.25, 0.10, 0.20))
    text = cmp.render(old, new)
    assert text.startswith("RETROSPECTIVE")
    assert "neural" in text
