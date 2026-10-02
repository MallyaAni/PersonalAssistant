"""Independent acceptance for optional covariance sizing and funded research paths."""

from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import grading, policy_v5
from backend.cli.market_open_source_portfolio import main
from backend.market import open_source_portfolio as portfolio
from backend.market.allocation_controls import adjusted_open
from backend.market.allocation_replay import replay
from backend.market.research_journal import ResearchJournal
from backend.market.research_journal_replay import verify_snapshot


# Create a synthetic grid with independently declared covariance and membership.
def inputs(rows=300):
    rng = np.random.default_rng(71)
    symbols = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "SPY", "QQQ")
    dates = np.arange("2014-01-02", "2018-01-01", dtype="datetime64[D]")
    dates = dates[np.is_busday(dates)][:rows]
    shocks = rng.normal(0.0005, 0.01, (rows, len(symbols)))
    shocks[:, 0] *= 3
    shocks[:, 1] *= 2
    closes = 100 * np.cumprod(1 + shocks, axis=0)
    panel = SimpleNamespace(
        dates=dates,
        tickers=symbols,
        open=closes.copy(),
        close=closes.copy(),
        adj_close=closes.copy(),
    )
    grades = np.full(closes.shape, grading.ORDINAL[grading.A], dtype=int)
    eligible = np.ones(closes.shape, dtype=bool)
    eligible[:, -2:] = False
    provenance = {
        "price_basis": "close-ratio-adjusted",
        "eligibility_mode": "conditional-price-only",
        "source_hashes": {"fixture": "a" * 64},
    }
    return panel, grades, eligible, provenance


# Check fixed constants and keep unproven historical availability explicit.
def test_fixed_specification_has_one_candidate_and_no_adoption():
    spec = portfolio.specification()
    assert spec["lookback_sessions"] == 252
    assert spec["cap"] == policy_v5.HOLD_CAP == 0.25
    assert spec["cadence_sessions"] == 20
    assert spec["costs_bps"] == [10.0, 25.0]
    assert spec["adoption_eligible"] is False
    assert len(spec["controls"]) == 4


# Refuse malformed calendars and implicit membership/grade conversions.
@pytest.mark.parametrize(
    "defect",
    [
        "dates",
        "duplicate",
        "bool_grades",
        "numeric_membership",
        "index_member",
        "negative_price",
        "basis",
        "hash",
    ],
)
def test_snapshot_validation_refuses_ambiguous_inputs(defect):
    panel, grades, eligible, provenance = inputs()
    if defect == "dates":
        panel.dates = panel.dates.astype("datetime64[h]")
    elif defect == "duplicate":
        panel.dates[3] = panel.dates[2]
    elif defect == "bool_grades":
        grades = grades.astype(bool)
    elif defect == "numeric_membership":
        eligible = eligible.astype(int)
    elif defect == "index_member":
        eligible[:, -1] = True
    elif defect == "negative_price":
        panel.close[0, 0] = -1
    elif defect == "basis":
        provenance["price_basis"] = "raw"
    else:
        provenance["source_hashes"] = {"fixture": "invalid"}
    with pytest.raises(ValueError, match="required|must|cannot"):
        portfolio.validate(panel, grades, eligible, provenance)


# Preserve unavailable covariance opportunities without substituting another rule.
def test_missing_covariance_is_explicit_cash_without_calling_optimizer(monkeypatch):
    panel, grades, eligible, _ = inputs()
    panel.adj_close[200, 0] = np.nan

    # Catch any attempted fit when causal trailing inputs are incomplete.
    def forbidden(*args):
        raise AssertionError("must not optimize missing history")

    monkeypatch.setattr(portfolio, "optimize", forbidden)
    target, observation = portfolio.candidate_target(
        panel, grades, eligible, 260, np.zeros(8), 1.0
    )
    assert observation["status"] == "unavailable"
    assert observation["eligible_names"] == 6
    assert target.sum() == 0
    early, unavailable = portfolio.candidate_target(
        panel, grades, eligible, 200, np.zeros(8), 1.0
    )
    assert early.sum() == 0
    assert unavailable["reason"] == "insufficient trailing sessions"


# Prove future prices, grades and membership cannot alter a prior sizing decision.
def test_completed_prefix_is_invariant_and_price_scale_is_equivalent(monkeypatch):
    panel, grades, eligible, _ = inputs()
    captured = []

    # Record the precise optimizer inputs without using any future observations.
    def record(returns, previous, gross, budget, forced):
        captured.append(returns.copy())
        return np.full(len(previous), gross / len(previous))

    monkeypatch.setattr(portfolio, "optimize", record)
    previous = np.zeros(8)
    first, evidence = portfolio.candidate_target(
        panel, grades, eligible, 260, previous, 1.0
    )
    changed = copy.deepcopy(panel)
    changed.adj_close[261:] *= 30
    altered_grades, altered_membership = grades.copy(), eligible.copy()
    altered_grades[261:] = grading.ORDINAL[grading.C]
    altered_membership[261:] = False
    second, evidence2 = portfolio.candidate_target(
        changed, altered_grades, altered_membership, 260, previous, 1.0
    )
    scaled = copy.deepcopy(panel)
    scaled.adj_close *= 10
    third, _ = portfolio.candidate_target(scaled, grades, eligible, 260, previous, 1.0)
    np.testing.assert_array_equal(first, second)
    np.testing.assert_array_equal(first, third)
    np.testing.assert_array_equal(captured[0], captured[1])
    np.testing.assert_allclose(captured[0], captured[2], atol=1e-14)
    assert captured[0].shape == (252, 6)
    assert evidence == evidence2
    assert evidence["information_through"] == str(panel.dates[260])


# Count mandatory exits in the exact feasible turnover budget when eligibility changes.
def test_turnover_relaxes_only_to_changed_simplex_minimum(monkeypatch):
    panel, grades, eligible, _ = inputs()
    eligible[260, 0] = False
    previous = np.array([0.25, 0.15, 0.15, 0.15, 0.15, 0.15, 0, 0])
    arguments = []

    # Independently inspect the full total constraint including removed names.
    def record(returns, selected_previous, gross, budget, forced):
        arguments.append((selected_previous, gross, budget, forced))
        return selected_previous + (gross - selected_previous.sum()) / len(
            selected_previous
        )

    monkeypatch.setattr(portfolio, "optimize", record)
    target, observation = portfolio.candidate_target(
        panel, grades, eligible, 260, previous, 0.1
    )
    assert target[0] == 0
    assert arguments[0][1:] == pytest.approx((1.0, 0.5, 0.25))
    assert observation["turnover_relaxed"]
    assert observation["target_turnover"] == pytest.approx(0.5)


# Keep the source-row cadence stable even when the requested account start is offset.
def test_all_control_paths_share_absolute_cadence(monkeypatch):
    panel, grades, eligible, _ = inputs(280)

    # Supply a valid declared basket to isolate timing and accounting from fitting.
    def equal(returns, previous, gross, budget, forced):
        return np.full(len(previous), gross / len(previous))

    monkeypatch.setattr(portfolio, "optimize", equal)
    paths, observations = portfolio.paths(panel, grades, eligible, 253)
    for rows in paths.values():
        assert len(rows) == 26
        assert [row.session for row in rows if row.rebalance] == [
            str(panel.dates[253]),
            str(panel.dates[260]),
        ]
        assert all(row.information_through <= row.session for row in rows)
    assert len(observations) == 2


# Independently replay funded fees and opening-gap cash constraints.
def test_funded_candidate_reconciles_journal_and_does_not_recycle_sales(monkeypatch):
    panel, grades, eligible, _ = inputs(280)

    # Isolate funded acceptance with deterministic valid allocation contracts.
    def equal(returns, previous, gross, budget, forced):
        return np.full(len(previous), gross / len(previous))

    monkeypatch.setattr(portfolio, "optimize", equal)
    paths, _ = portfolio.paths(panel, grades, eligible, 253)
    panel.open[254] *= 2.0
    journal = ResearchJournal(
        panel.dates,
        panel.tickers,
        adjusted_open(panel.open, panel.close, panel.adj_close),
        panel.adj_close,
        run_id="skfolio-funded-fixture",
        account_id="synthetic-account",
        policy_id=portfolio.POLICY,
        cost_bps=25.0,
        provenance={"evidence_basis": "synthetic-accounting-test"},
    )
    account = replay(
        panel, paths[portfolio.POLICY], first=253, cost_bps=25.0, journal=journal
    )
    proof = verify_snapshot(journal.snapshot())
    assert proof["ok"], proof["errors"]
    assert proof["accounting_verified"]
    assert np.all(account["cash"] >= -1e-12)
    assert account["cash"][1] < 1e-8
    assert account["nav"][1] < 0.6
    assert account["fees"].sum() > 0
    assert account["fees"].sum() == pytest.approx(proof["total_fees"])


# Exercise the actual optimizer's covariance, cap and total turnover constraints.
def test_real_skfolio_fit_obeys_contract_and_changes_correlated_weights():
    pytest.importorskip("skfolio")
    panel, grades, eligible, _ = inputs()
    previous = np.array([1 / 6] * 6 + [0, 0])
    target, observation = portfolio.candidate_target(
        panel, grades, eligible, 260, previous, 0.25
    )
    assert observation["status"] == "optimized"
    assert target.sum() == pytest.approx(1.0, abs=1e-8)
    assert target.min() >= 0
    assert target.max() <= 0.25 + 1e-8
    assert np.abs(target - previous).sum() <= 0.25 + 1e-8
    assert target[0] < previous[0]


# A zero turnover allowance holds previous targets without widening the budget.
def test_real_zero_turnover_is_binding():
    pytest.importorskip("skfolio")
    rng = np.random.default_rng(20)
    returns = rng.normal(0, [0.05, 0.01, 0.015, 0.012, 0.018], (252, 5))
    previous = np.full(5, 0.2)
    result = portfolio.optimize(returns, previous, 1.0, 0.0, 0.0)
    np.testing.assert_allclose(result, previous, atol=1e-8)


# Solve the mandatory-exit boundary as its exact monotone feasible set.
def test_real_minimum_feasible_turnover_handles_solver_boundary():
    pytest.importorskip("skfolio")
    rng = np.random.default_rng(90)
    returns = rng.normal(0, 0.02, (252, 7))
    previous = np.array([0, 0.06, 0.08, 0.25, 0.12, 0.05, 0.16])
    forced = 0.28
    total_budget = forced + 1.0 - previous.sum()
    result = portfolio.optimize(returns, previous, 1.0, total_budget, forced)
    assert result.sum() == pytest.approx(1.0, abs=1e-8)
    assert np.all(result >= previous - 1e-8)
    assert np.abs(result - previous).sum() + forced <= total_budget + 1e-8


# Certify the captured narrow-bound solution against an independent active-set optimum.
def test_captured_covariance_boundary_has_independent_optimality_certificate(
    monkeypatch,
):
    pytest.importorskip("skfolio")
    cp, cov, _ = portfolio.dependencies()
    covariance = np.array(
        [
            [
                0.00035957770526274694,
                0.0001647035108142004,
                8.618543601102278e-05,
                0.0003124976159647045,
                0.00021113704130013168,
                0.0002301878566875669,
                0.00012719866302757915,
            ],
            [
                0.0001647035108142004,
                0.00025237279827618387,
                7.843793526632941e-05,
                0.0002442518743705811,
                0.00015191365701980024,
                0.00021458231852347208,
                0.0001304551811046089,
            ],
            [
                8.618543601102278e-05,
                7.843793526632941e-05,
                0.00018072375481923875,
                0.00010216161244917276,
                7.926275758421918e-05,
                9.388416434504537e-05,
                5.452515073788385e-05,
            ],
            [
                0.0003124976159647045,
                0.0002442518743705811,
                0.00010216161244917276,
                0.0008846840721638191,
                0.00029226027787451314,
                0.000362732895935545,
                0.00019759977021572946,
            ],
            [
                0.00021113704130013168,
                0.00015191365701980024,
                7.926275758421918e-05,
                0.00029226027787451314,
                0.0008233329586985278,
                0.00016399298398134027,
                0.0001273268913100854,
            ],
            [
                0.0002301878566875669,
                0.00021458231852347208,
                9.388416434504537e-05,
                0.000362732895935545,
                0.00016399298398134027,
                0.0005600127697108972,
                0.00016591662925853902,
            ],
            [
                0.00012719866302757915,
                0.0001304551811046089,
                5.452515073788385e-05,
                0.00019759977021572946,
                0.0001273268913100854,
                0.00016591662925853902,
                0.00018397780434220289,
            ],
        ]
    )
    previous = np.array(
        [
            0.03936291046779894,
            0.19166279906622835,
            0.24999999913305163,
            9.245302759481132e-10,
            0.018974297413685694,
            0.0,
            0.24999999825204344,
        ]
    )
    gross, budget, forced = 0.9999999999999999, 0.4999999894853233, 0.24999999474266174

    class CapturedPrior:
        # Supply the covariance fitted from the immutable 252-by-seven failure.
        def __init__(self, **kwargs):
            self.return_distribution_ = SimpleNamespace(covariance=covariance)

        # Isolate the captured quadratic geometry from a second covariance fit.
        def fit(self, values):
            return self

    # Keep the actual CVXPY solver while replaying the exact captured covariance.
    def captured_dependencies():
        return cp, cov, CapturedPrior

    monkeypatch.setattr(portfolio, "dependencies", captured_dependencies)
    result = portfolio.optimize(np.zeros((252, 7)), previous, gross, budget, forced)
    assert np.linalg.eigvalsh(covariance).min() > 0
    fixed, free = np.array([1, 2, 3, 6]), np.array([0, 4, 5])
    optimum = previous.copy()
    optimum[[1, 2, 6]] = 0.25
    system = np.block(
        [
            [2 * covariance[np.ix_(free, free)], np.ones((3, 1))],
            [np.ones((1, 3)), np.zeros((1, 1))],
        ]
    )
    rhs = np.r_[
        -2 * covariance[np.ix_(free, fixed)] @ optimum[fixed],
        gross - optimum[fixed].sum(),
    ]
    solution = np.linalg.solve(system, rhs)
    optimum[free] = solution[:-1]
    reduced = 2 * covariance @ optimum + solution[-1]
    assert np.max(np.abs(reduced[free])) < 1e-15
    assert np.all(reduced[[1, 2, 6]] < 0)
    assert reduced[3] > 0
    assert np.all(optimum >= previous)
    assert np.all(optimum <= 0.25)
    assert optimum.sum() == pytest.approx(gross, abs=1e-15)
    np.testing.assert_allclose(result, optimum, atol=2e-6, rtol=0)
    gradient = 2 * covariance @ result
    linear_minimum = previous.copy()
    remaining = gross - previous.sum()
    for j in np.argsort(gradient):
        allocation = min(remaining, 0.25 - linear_minimum[j])
        linear_minimum[j] += allocation
        remaining -= allocation
    assert abs(remaining) < 1e-15
    assert float(gradient @ (result - linear_minimum)) < 1e-10
    assert float(result @ covariance @ result - optimum @ covariance @ optimum) < 1e-10


# Never accept feasible weights when the solver cannot establish optimality.
def test_solver_inaccurate_status_is_refused(monkeypatch):
    pytest.importorskip("skfolio")
    cp, _, _ = portfolio.dependencies()

    # Return a failed qualification from the actual quadratic solve boundary.
    def unqualified_solve(problem, **kwargs):
        problem._status = "optimal_inaccurate"

    monkeypatch.setattr(cp.Problem, "solve", unqualified_solve)
    returns = np.random.default_rng(20).normal(0, 0.01, (252, 5))
    with pytest.raises(RuntimeError, match="optimal solution"):
        portfolio.optimize(returns, np.zeros(5), 1.0, 1.0, 0.0)


# Refuse dependency absence without returning the incumbent under a candidate label.
def test_missing_dependency_is_a_failure(monkeypatch):
    panel, grades, eligible, provenance = inputs()

    # Stand in for an absent optional installation at the explicit dependency boundary.
    def absent():
        raise RuntimeError("skfolio unavailable")

    monkeypatch.setattr(portfolio, "dependencies", absent)
    with pytest.raises(RuntimeError, match="unavailable"):
        portfolio.backtest(
            panel, grades, eligible, provenance, start=str(panel.dates[260])
        )


# Pin snapshot bytes and preserve existing artifacts on a repeated CLI call.
def test_snapshot_hash_and_exclusive_output(tmp_path):
    panel, grades, eligible, provenance = inputs()
    source = tmp_path / "source.npz"
    np.savez(
        source,
        dates=panel.dates,
        symbols=np.array(panel.tickers),
        open=panel.open,
        close=panel.close,
        adj_close=panel.adj_close,
        grades=grades,
        eligible=eligible,
    )
    metadata = tmp_path / "source.json"
    provenance["snapshot_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata.write_text(json.dumps(provenance))
    loaded = portfolio.load_snapshot(source, metadata)
    np.testing.assert_array_equal(loaded[0].dates, panel.dates)
    provenance["snapshot_sha256"] = "b" * 64
    metadata.write_text(json.dumps(provenance))
    with pytest.raises(ValueError, match="SHA256"):
        portfolio.load_snapshot(source, metadata)
    output = tmp_path / "already.json"
    output.write_text("original")
    with pytest.raises(SystemExit, match="already exists"):
        main(
            [
                "--snapshot",
                str(source),
                "--provenance",
                str(metadata),
                "--output",
                str(output),
            ]
        )
    assert output.read_text() == "original"


# Run real fits and all funded controls through the hash-bound command-line entrypoint.
def test_real_cli_backtest_reports_costs_coverage_and_common_curves(tmp_path):
    pytest.importorskip("skfolio")
    panel, grades, eligible, provenance = inputs(280)
    source = tmp_path / "source.npz"
    np.savez(
        source,
        dates=panel.dates,
        symbols=np.array(panel.tickers),
        open=panel.open,
        close=panel.close,
        adj_close=panel.adj_close,
        grades=grades,
        eligible=eligible,
    )
    provenance["snapshot_sha256"] = hashlib.sha256(source.read_bytes()).hexdigest()
    metadata = tmp_path / "source.json"
    metadata.write_text(json.dumps(provenance))
    output = tmp_path / "result.json"
    assert (
        main(
            [
                "--snapshot",
                str(source),
                "--provenance",
                str(metadata),
                "--output",
                str(output),
                "--start",
                str(panel.dates[253]),
            ]
        )
        == 0
    )
    result = json.loads(output.read_text())
    assert result["adoption_eligible"] is False
    assert result["historical_availability_verified"] is False
    assert result["specification_sha256"] == portfolio.digest(portfolio.specification())
    assert [cost["cost_bps"] for cost in result["costs"]] == [10.0, 25.0]
    assert len(result["dates"]) == 27
    for cost in result["costs"]:
        assert set(cost["curves"]) == set(portfolio.LINES)
        for curve in cost["curves"].values():
            assert curve["nav"][0] == curve["cash"][0] == 1.0
            assert len(curve["nav"]) == len(result["dates"])
            assert min(curve["cash"]) >= 0
            assert sum(curve["fees"]) > 0
        for line in cost["results"]:
            assert line["windows"][0]["sessions"] == 26
            assert line["windows"][1]["status"] == "unavailable"
            assert line["rolling_252_against"] == {}


# Count unknown eligible grades instead of treating a missing reading as a recorded C.
def test_unknown_grades_preserve_coverage_and_realized_funding():
    pytest.importorskip("skfolio")
    panel, grades, eligible, provenance = inputs(280)
    grades[253:, 0] = -1
    result = portfolio.backtest(
        panel, grades, eligible, provenance, start=str(panel.dates[253])
    )
    assert result["eligible_unknown_grade_cells"] == 27
    assert result["candidate_observations"][0]["eligible_names"] == 5
    assert result["candidate_unavailable_resets"] == 0


# Required source outages remain opportunities in the complete account denominator.
def test_unavailable_candidate_is_measured_as_cash_not_deleted():
    pytest.importorskip("skfolio")
    panel, grades, eligible, provenance = inputs(280)
    panel.adj_close[150, 0] = np.nan
    result = portfolio.backtest(
        panel, grades, eligible, provenance, start=str(panel.dates[253])
    )
    assert result["candidate_unavailable_resets"] == 2
    candidate = result["costs"][0]["curves"][portfolio.POLICY]
    assert candidate["nav"] == [1.0] * 27
    assert candidate["fees"] == [0.0] * 27
    assert result["costs"][0]["results"][0]["windows"][0]["sessions"] == 26
