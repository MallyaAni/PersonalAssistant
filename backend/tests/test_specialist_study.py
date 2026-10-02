"""Synthetic contribution tests prove accounting and causality, not model alpha."""

from copy import deepcopy

import numpy as np
import pytest

from backend.market import open_source_forecast_evaluation as frozen
from backend.market import open_source_forecasts as baseline
from backend.market import specialist_forecasts as joint
from backend.market import specialist_study as study
from backend.tests.test_open_source_forecast_evaluation import fixture


class SyntheticBaseline:
    # Supply synthetic predictions without claiming pretrained inference.
    def __init__(self, name):
        self.name = name
        self.runtime = {
            "kronos_source_revision": baseline.CODE_REVISIONS["kronos"],
            "timesfm_source_revision": baseline.CODE_REVISIONS["timesfm3"],
            "mocked": "test-only",
        }

    # Supply fixed synthetic targets in each model's declared units.
    def predict(self, rows, future):
        return np.repeat(
            1e-4
            if self.name == "ttm"
            else rows[-1]["close"] * (1 if rows[-1]["symbol"] == "SPY" else 1.02),
            10,
        )


class SyntheticJoint:
    # Bind each mocked model identity and expose only synthetic native dimensions.
    def __init__(self, name):
        self.spec = baseline.CHECKPOINTS[name]
        self.runtime = {"mocked": "test-only"}
        self.shapes = {}

    # Mock the joint interface; verify real inference independently.
    def predict(self, contexts, future):
        count = len(contexts)
        self.shapes = {
            "input": [count, 252],
            "native_output": [count, 10, 9 if self.spec.name == "timesfm3" else 1],
            "median_output": [count, 10],
        }
        return np.array(
            [
                np.repeat(
                    rows[-1]["close"] * (1 if rows[-1]["symbol"] == "SPY" else 1.03), 10
                )
                for rows in contexts
            ]
        )


# Reuse the synthetic price contract for all specialist opportunities.
def evidence():
    payload, _, panel, grades, eligible = fixture()
    artifacts = []
    for name in baseline.CHECKPOINTS:
        artifact = baseline.run(
            payload,
            name,
            list(frozen.COHORT),
            research_only=True,
            forecaster=SyntheticBaseline(name),
        )
        artifact["input_sha256"] = frozen.SOURCE_SHA256
        artifacts.append(artifact)
    return payload, artifacts, panel, grades, eligible


# Preserve funding, benchmarks, eligibility and the no-history fallback.
def test_components_share_funded_ledger_and_selector_fallback():
    payload, baselines, panel, grades, eligible = evidence()
    joints = [
        joint.run(
            payload,
            name,
            list(frozen.COHORT),
            study.context_mapping(),
            baseline=next(a for a in baselines if a["checkpoint"]["name"] == name),
            input_sha256=frozen.SOURCE_SHA256,
            research_only=True,
            forecaster=SyntheticJoint(name),
        )
        for name in joint.MODELS
    ]
    result = study.evaluate(
        payload,
        baselines,
        joints,
        panel,
        grades,
        eligible,
        {"snapshot_sha256": "synthetic"},
        source_sha256=frozen.SOURCE_SHA256,
    )
    assert result["requested_joint_opportunities"] == 456
    assert result["adoption_eligible"] is False
    assert result["exact_live_strategy"] is False
    for cost in ("10", "25"):
        assert (
            result["costs"]["combined"][cost]["nav"]
            == result["costs"]["incumbent"][cost]["nav"]
        )
        assert all(
            np.isfinite(result["costs"][name][cost]["nav"]).all()
            for name in result["costs"]
        )
    assert all(
        row["selector"]["incumbent_weight"] == 1
        for row in result["decisions"]
        if row["reset"]
    )
    assert set(result["costs"]) >= {
        "SPY",
        "QQQ",
        "risk-gross-control",
        "joint-gross-control",
    }
    assert result["paired_forecast_diagnostics"]["chronos2"]["requested"] == 228
    assert result["paired_forecast_diagnostics"]["chronos2"]["immature_labels"] > 0


# Refuse an omitted research model before a partial comparison can look complete.
def test_complete_model_set_required():
    payload, baselines, panel, grades, eligible = evidence()
    with pytest.raises(ValueError, match="All four"):
        study.evaluate(
            payload,
            baselines[:3],
            [],
            panel,
            grades,
            eligible,
            {},
            source_sha256=frozen.SOURCE_SHA256,
        )


# Refuse arbitrary utilities as authenticated funded history.
def test_unattested_selector_history_refused():
    payload, baselines, panel, grades, eligible = evidence()
    with pytest.raises(ValueError, match="authenticated funded archive"):
        study.evaluate(
            payload,
            baselines,
            [],
            panel,
            grades,
            eligible,
            {},
            source_sha256=frozen.SOURCE_SHA256,
            selector_history=[{"utilities": {}}],
        )


# Keep absent cohort holdings excluded instead of manufacturing historical grades.
def test_missing_cohort_grade_stays_unknown():
    payload, _, panel, grades, eligible = evidence()
    old = list(panel.tickers).index("TSLA")
    reduced = deepcopy(panel)
    reduced.tickers = tuple(s for s in panel.tickers if s != "TSLA")
    for key in ("open", "close", "adj_close"):
        setattr(reduced, key, np.delete(getattr(panel, key), old, axis=1))
    expanded, new_grades, members = study.cohort_panel(
        payload,
        reduced,
        np.delete(grades, old, axis=1),
        np.delete(eligible, old, axis=1),
    )
    assert np.isfinite(expanded.adj_close[:, old]).all()
    assert np.all(new_grades[:, old] == -1)
    assert not members[:, old].any()


# Neither a positive forecast nor incomplete availability may add an ineligible stock.
def test_ranking_preserves_grade_intent_and_unavailable_fallback():
    base = np.zeros(12)
    base[0] = base[1] = 0.25
    records = {
        ("2026-09-03", s): {
            "status": "forecast",
            "predicted_excess_return": 100 if s == "TSLA" else 0.01,
        }
        for s in frozen.COHORT
    }
    weights, _ = study.joint_weights(base, records, "2026-09-03")
    assert weights[frozen.COHORT.index("TSLA")] == 0
    records[("2026-09-03", "AAPL")]["status"] = "unavailable"
    weights, status = study.joint_weights(base, records, "2026-09-03")
    np.testing.assert_array_equal(weights, base)
    assert status == "unavailable_incumbent_fallback"


# The fixed CLI refuses a missing model independently of generic subset fixtures.
def test_fixed_forecast_cli_requires_four_artifacts(monkeypatch):
    from backend.cli.market_open_source_forecast_evaluation import main

    monkeypatch.setattr(
        "sys.argv",
        ["score", "input", "portfolio", "provenance", "one", "--output", "out"],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2


# Partial timing evidence cannot produce a falsely complete specialist scorecard.
def test_specialist_cli_requires_complete_timing_inputs(monkeypatch):
    from backend.cli.market_specialist_study import main

    monkeypatch.setattr(
        "sys.argv",
        [
            "score",
            "input",
            "portfolio",
            "provenance",
            "--baselines",
            "a",
            "b",
            "c",
            "d",
            "--joint",
            "e",
            "f",
            "--timing-manifest",
            "g",
            "--output",
            "out",
        ],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
