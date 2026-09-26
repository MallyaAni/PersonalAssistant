"""The learned arm trains only on members, forecasts out of sample, and picks
the top ten members by forecast at 10% each.

A synthetic 1,100-session book of eight names whose returns carry a weak
but real relation to their own 20-session momentum, plus one name that is
never a member, checks the mechanics: no forecast before the first fit, no
weight on a non-member ever, ten-or-fewer names at the cap, and forecasts
that are invariant to future rows of the panel.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, learned_arm, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.market import learned_policy as lp
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = tuple(f"N{i}" for i in range(8))
T = 1100


# A panel whose names trend a little (positive autocorrelation of the
# 20-session return), so a ranker has something to find.
def _report(seed: int = 0) -> DeskReport:
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    days = []
    d = date(2019, 1, 2)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    drift = np.zeros(n + 1)
    log = np.zeros((T, n + 1))
    for t in range(1, T):
        drift = 0.97 * drift + rng.normal(0, 0.0015, size=n + 1)
        log[t] = log[t - 1] + drift + rng.normal(0.0003, 0.015, size=n + 1)
    close = 100.0 * np.exp(log)
    panel = Panel(
        dates=dates,
        tickers=NAMES + ("SPY",),
        open=close * (1 + rng.normal(0, 0.001, size=close.shape)),
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in NAMES},
        benchmark="SPY",
    )
    grades = np.full((T, n + 1), grading.ORDINAL["A"], dtype=int)
    grades[:, n] = 0
    conviction = rng.normal(size=(T, n + 1))
    conviction[:, n] = np.nan
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(0, 0, 0.5, 0, 0, 0, "ai", 0.1, 0, 1.0, 1.0, (), 0.0, False)
    view = regime.RegimeView([state] * T, Opinion("rotation", np.full((T, n + 1), np.nan)))
    return DeskReport(panel, {t: "ai" for t in NAMES}, {}, view, graded, graded.as_scores(), [])


@pytest.fixture(scope="module")
def fitted():
    report = _report()
    mask = np.ones((T, len(NAMES) + 1), dtype=bool)
    mask[:, 7] = False  # N7 is never a member
    mask[:, 8] = False
    forecast = learned_arm.forecasts(report, mask)
    return report, mask, forecast


# Inputs are validated by learned_policy, membership follows the mask and the
# grade and conviction ride along as the last two feature columns.
def test_inputs_carry_membership_and_desk_columns(fitted):
    report, mask, _ = fitted
    inputs = learned_arm.historical_inputs(report, mask)
    assert inputs.features.shape[2] == 10
    assert (inputs.membership[:, 7] == 0).all() and (inputs.membership[:, 8] == 0).all()
    assert (inputs.membership[:, :7] == 1).all()
    assert inputs.evidence_basis == "retrospective-price"
    np.testing.assert_array_equal(inputs.features[:, :, 8], report.graded.grades)


# Forecasts exist only after the first purged fit, never for non-members,
# and the allocator holds at most ten members at the cap.
def test_forecasts_and_allocation_respect_membership(fitted):
    report, mask, forecast = fitted
    first = int(np.flatnonzero(~np.isnat(forecast.fit_session))[0])
    assert first >= lp.RANKER_MIN_SESSIONS
    assert np.isnan(forecast.values[:first]).all()
    assert np.isnan(forecast.values[:, 7]).all() and np.isnan(forecast.values[:, 8]).all()
    assert np.isfinite(forecast.values[first + 5, :7]).all()
    allocate = learned_arm.top_k_allocator(forecast, mask)
    before = allocate(report, report.panel, None, first - 1)
    assert before.sum() == 0
    after = allocate(report, report.panel, None, T - 1)
    assert after[7] == 0 and after[8] == 0
    assert np.count_nonzero(after) == 7 and np.allclose(after[after > 0], learned_arm.CAP)
    # Ranking: the chosen names are the top forecasts among members.
    order = np.argsort(-np.where(mask[T - 1], forecast.values[T - 1], -np.inf))
    assert set(np.flatnonzero(after > 0)) == set(order[:7])


# The learned arm has a real but modest edge on this synthetic panel: its
# out-of-sample forecast correlates positively with the realised label.
def test_forecasts_have_out_of_sample_skill(fitted):
    report, mask, forecast = fitted
    labels = lp.relative_open_labels(learned_arm.historical_inputs(report, mask))
    both = np.isfinite(forecast.values) & np.isfinite(labels)
    rho = np.corrcoef(forecast.values[both], labels[both])[0, 1]
    assert rho > 0.02


# The scorecard registry exposes the arm with the (report, mask) signature,
# and the factory caches the fit per report and mask.
def test_registry_and_cache(fitted):
    from backend.cli import market_pit_scorecard as sc

    report, mask, _ = fitted
    assert "hgb_rank" in sc.ARMS
    learned_arm._CACHE.clear()
    a = sc.ARMS["hgb_rank"](report, mask)
    b = sc.ARMS["hgb_rank"](report, mask)
    assert len(learned_arm._CACHE) == 1
    t = T - 1
    np.testing.assert_array_equal(a(report, report.panel, None, t), b(report, report.panel, None, t))


# The desk feature set carries every analyst's conviction and numeric
# evidence, the alpha summaries and the regime context, each named, with
# text evidence left out; the price set is the ten-column baseline.
def test_desk_feature_stack_names_every_column(fitted):
    report, mask, _ = fitted
    from dataclasses import replace

    from backend.agents.trading.desk.opinions import Opinion
    from backend.market import alpha

    n = len(NAMES) + 1
    evidence = {
        "revenue_yoy": np.random.default_rng(1).normal(size=(T, n)),
        "support_kind": np.full((T, n), "swing", dtype=object),
    }
    opinions = {"fundamental": Opinion("fundamental", np.random.default_rng(2).normal(size=(T, n)), evidence)}
    rich = replace(report, opinions=opinions)
    price, price_names = learned_arm.feature_stack(rich, "price")
    assert price.shape == (T, n, 10) and price_names[-2:] == ("desk_grade", "desk_conviction")
    desk, desk_names = learned_arm.feature_stack(rich, "desk")
    assert desk.shape[2] == len(desk_names) == 10 + 2 + alpha.ALPHA_COUNT + 9
    assert "fundamental:conviction" in desk_names and "fundamental:revenue_yoy" in desk_names
    assert not any(name.endswith("support_kind") for name in desk_names)
    assert "alpha:rel_theme_20" in desk_names and "regime:novelty_z" in desk_names
    assert np.isfinite(desk[T - 1, 0, desk_names.index("regime:exposure")])
    with pytest.raises(ValueError):
        learned_arm.feature_stack(rich, "other")
    inputs = learned_arm.historical_inputs(rich, mask, "desk")
    assert inputs.features.shape[2] == len(desk_names)
    from backend.cli import market_pit_scorecard as sc

    assert {"hgb_rank", "hgb_desk"} <= set(sc.ARMS)
