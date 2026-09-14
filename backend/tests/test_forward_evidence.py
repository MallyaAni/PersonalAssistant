"""Prove future-only grade outcomes and conservative candidate accounting."""

import json
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import portfolio_candidate
from backend.market import forward_actions, forward_evidence, intraday_evaluation
from backend.tests.test_intraday_candidate import inputs


# Create immutable-shaped observations with known future stock and benchmark prices.
def observations():
    rows = []
    # September 14 to 21 is five trading sessions; the weekend is not counted.
    for day, minute, stock in [(14, 0, 10), (14, 15, 20), (21, 15, 22)]:
        bar = datetime(2026, 9, day, 14, minute, tzinfo=UTC)
        rows.append(
            {
                "version": "test/1",
                "policy_sha256": "one",
                "bar": bar.isoformat(),
                "as_of": (bar + timedelta(minutes=15, seconds=1)).isoformat(),
                "valid_until": (bar + timedelta(minutes=30)).isoformat(),
                "grades": {"AAPL": {"grade_live": "A+"}},
                "entry_states": {"AAPL": "wait"},
                "prices": {"AAPL": stock, "SPY": 100},
                "targets": {"AAPL": 0.1},
                "baseline_targets": {"AAPL": 0.1},
                "technical_targets": {"AAPL": 0.1},
            }
        )
    return rows


# A grade uses the later 20-dollar entry, never the favorable 10-dollar decision price.
def test_outcomes_include_waits_and_use_later_observed_prices():
    report = forward_evidence.outcomes(observations())
    row = report["grades"][0]
    assert row["horizon_sessions"] == 5
    assert row["mean_excess_return"] == pytest.approx(0.098)
    assert row["approximate_95_interval"] is None
    assert row["observations"] == 1
    assert report["entry_states"][0]["state"] == "wait"
    assert report["signal_count"] == 2
    assert report["missing_or_immature"][20] == 2


# Missing benchmarks and expired entries remain unavailable instead of creating winners.
def test_unknown_prices_and_expired_decisions_do_not_become_outcomes():
    rows = observations()
    del rows[-1]["prices"]["SPY"]
    assert not forward_evidence.outcomes(rows)["grades"]
    rows = observations()
    rows[0]["valid_until"] = rows[0]["as_of"]
    assert not forward_evidence.outcomes(rows)["grades"]


# Thousands of same-day names cannot masquerade as independent evidence.
def test_uncertainty_uses_nonoverlapping_dates():
    samples = [("2026-09-14", 0.1)] * 1000 + [("2026-09-15", 0.9)]
    result = forward_evidence.summarize(samples, 5)
    assert result["observations"] == 1001
    assert result["nonoverlapping_cohorts"] == 1
    assert result["approximate_95_interval"] is None


# Policy-code changes cannot share a series even with the same friendly version.
def test_versions_and_policy_hashes_stay_separate(tmp_path):
    rows = observations()
    rows[1]["policy_sha256"] = "two"
    with pytest.raises(ValueError, match="versions"):
        forward_evidence.outcomes(rows)
    with pytest.raises(ValueError, match="versions"):
        intraday_evaluation.evaluate(rows)
    folder = tmp_path / "desk/intraday-research"
    folder.mkdir(parents=True)
    for i, row in enumerate(rows):
        (folder / f"decision-{i}.json").write_text(json.dumps(row))
    report = forward_evidence.report(tmp_path, require_actions=False)
    assert len(report["versions"]) == 2


# Later policy prices mature older signals without replacing their original grades.
def test_old_grades_mature_using_new_policy_price_observations(tmp_path):
    rows = observations()
    rows[1]["policy_sha256"] = "new"
    rows[2]["policy_sha256"] = "new"
    rows[1]["grades"]["AAPL"] = {"grade_live": "C"}
    folder = tmp_path / "desk/intraday-research"
    folder.mkdir(parents=True)
    for i, row in enumerate(rows):
        (folder / f"decision-{i}.json").write_text(json.dumps(row))
    result = forward_evidence.report(tmp_path, require_actions=False)
    old = next(v for v in result["versions"] if v["version"].endswith("one"))
    grade = old["outcomes"][0]["grades"][0]
    assert grade["grade"] == "A+"
    assert grade["mean_excess_return"] == pytest.approx(0.098)
    assert old["decision_count"] == 1


# Correlated positions can only shrink; the candidate cannot borrow or evade name caps.
def test_correlation_cap_releases_cash_without_redistribution():
    _, _, _, panel, _ = inputs()
    names = panel.tickers[:4]
    # Identical return paths create a known cluster without fitting an example.
    for i in range(1, 4):
        panel.adj_close[:, i] = panel.adj_close[:, 0] * (i + 1)
    weights = {name: 0.15 for name in names}
    result = portfolio_candidate.calculate(panel, weights)
    assert result["status"] == "available"
    assert sum(result["targets"].values()) == pytest.approx(
        portfolio_candidate.CLUSTER_CAP
    )
    assert all(0 <= result["targets"][name] <= weights[name] for name in names)
    panel.adj_close[-60:, 0] = np.nan
    assert portfolio_candidate.calculate(panel, weights)["status"] == "unavailable"


# A split and dividend preserve economic value instead of creating a price-chart loss.
def test_grade_outcomes_account_for_splits_and_dividends():
    rows = observations()
    rows[-1]["prices"]["AAPL"] = 9.5
    actions = {
        "AAPL": [
            {"date": "2026-09-16", "kind": "split", "value": 2},
            {"date": "2026-09-16", "kind": "dividend", "value": 0.5},
        ]
    }
    result = forward_evidence.outcomes(rows, corporate_actions=actions)
    assert result["grades"][0]["mean_excess_return"] == pytest.approx(-0.002)


# Dividends without known pay dates accrue to equity but cannot buy shares.
def test_portfolio_does_not_spend_unpaid_dividends():
    rows = observations()[:2]
    for minute in (15, 30):
        bar = datetime(2026, 9, 15, 14, minute, tzinfo=UTC)
        rows.append(
            {
                **rows[0],
                "bar": bar.isoformat(),
                "as_of": (bar + timedelta(minutes=15, seconds=1)).isoformat(),
                "valid_until": (bar + timedelta(minutes=30)).isoformat(),
                "prices": {"AAPL": 9.5, "SPY": 100},
            }
        )
    for row in rows:
        for arm in intraday_evaluation.ARMS:
            row[arm] = {"AAPL": 1.0}
    actions = {
        "AAPL": [
            {"date": "2026-09-15", "kind": "split", "value": 2},
            {"date": "2026-09-15", "kind": "dividend", "value": 0.5},
        ]
    }
    result = intraday_evaluation.evaluate(rows, 0, actions)
    for arm in result["arms"].values():
        assert arm["return"] == pytest.approx(0)
        assert arm["cash"] == pytest.approx(0)
        assert arm["dividend_receivable"] == pytest.approx(5000)


# An absent corporate-action dataset is not evidence that no action occurred.
def test_action_coverage_is_required(tmp_path):
    with pytest.raises(ValueError, match="history unavailable"):
        forward_actions.load(tmp_path, ["AAPL"])
