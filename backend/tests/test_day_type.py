"""The day-type study labels regime-relative red days, sees only the past,
and finds skill exactly when the data carries it.

Two synthetic books: one whose volatility clusters (a GARCH-like process,
where yesterday's volatility genuinely predicts the chance of a tail
tomorrow) and one of independent draws with no structure. Skill must be
positive on the first and near zero on the second; the labels must be
relative to the trailing distribution; and no feature may look forward.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.cli import market_day_type as cli
from backend.market import day_type
from backend.market.panel import Panel
from backend.market.universe import AI_COMPUTE

NAMES = tuple(f"N{i}" for i in range(6))
T = 2200


# A book whose common factor has clustered volatility (clustered=True) or
# none (clustered=False).
def _report(clustered: bool, seed: int = 0) -> DeskReport:
    rng = np.random.default_rng(seed)
    n = len(NAMES)
    days = []
    d = date(2015, 1, 2)
    while len(days) < T:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    sigma = np.full(T, 0.012)
    factor = np.zeros(T)
    for t in range(1, T):
        if clustered:
            sigma[t] = np.sqrt(0.00001 + 0.25 * factor[t - 1] ** 2 + 0.72 * sigma[t - 1] ** 2)
        factor[t] = rng.normal(0.0004, sigma[t])
    idio = rng.normal(0, 0.006, size=(T, n))
    log = np.cumsum(factor[:, None] * 1.5 + idio, axis=0)
    spy = np.cumsum(factor + rng.normal(0, 0.003, size=T))
    close = 100.0 * np.exp(np.column_stack([log, spy]))
    open_ = close * np.exp(rng.normal(0, 0.002, size=close.shape))
    panel = Panel(
        dates=dates,
        tickers=NAMES + ("SPY",),
        open=open_,
        high=np.maximum(open_, close) * 1.005,
        low=np.minimum(open_, close) * 0.995,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in NAMES},
        benchmark="SPY",
    )
    grades = np.full((T, n + 1), grading.ORDINAL["A"], dtype=int)
    conviction = rng.normal(size=(T, n + 1))
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(0, 0, 0.5, 0, 0, 0, "ai", 0.1, 0, 1.0, 1.0, (), 0.0, False)
    view = regime.RegimeView([state] * T, Opinion("rotation", np.full((T, n + 1), np.nan)))
    return DeskReport(panel, {t: "ai" for t in NAMES}, {}, view, graded, graded.as_scores(), [])


def _mask():
    mask = np.ones((T, len(NAMES) + 1), dtype=bool)
    mask[:, -1] = False
    return mask


# Labels mark the bottom tenth of the trailing distribution, thresholds
# move with the regime, and forward returns start at tomorrow's open.
def test_labels_are_regime_relative_and_forward_looking():
    report = _report(clustered=True)
    mask = _mask()
    from backend.agents.trading.desk import simulate

    opens = simulate.adjusted_open(report.panel)
    fwd = day_type.forward_open_returns(opens, mask, 1)
    t = 500
    expect = np.mean(np.log(opens[t + 2, :6] / opens[t + 1, :6]))
    assert fwd[t] == pytest.approx(expect)
    assert np.isnan(fwd[-2:]).all()
    labels, thresholds = day_type.tail_labels(fwd)
    known = np.isfinite(labels)
    assert known.sum() > 1500
    assert 0.06 < labels[known].mean() < 0.14
    assert np.nanstd(thresholds) > 0  # the threshold moves with volatility


# Every feature is a trailing statistic: changing the future never changes
# today's row.
def test_features_are_causal():
    report = _report(clustered=True)
    mask = _mask()
    ahead = np.zeros(T)
    since = np.zeros(T)
    x = day_type.features(report.panel, mask, report.regime.states, ahead, since)
    assert x.shape == (T, len(day_type.FEATURE_NAMES))
    from dataclasses import replace

    tampered = report.panel.adj_close.copy()
    tampered[1001:] *= 3.0
    high = report.panel.high.copy()
    high[1001:] *= 3.0
    y = day_type.features(replace(report.panel, adj_close=tampered, close=tampered, high=high), mask, report.regime.states, ahead, since)
    np.testing.assert_array_equal(x[:1001], y[:1001])
    assert np.isfinite(x[1000]).all()


# Skill: clustered volatility is predictable (positive Brier skill on both
# models at h=1); iid returns are not (skill near zero or negative).
@pytest.mark.parametrize("model", ["logistic", "hgb"])
def test_walk_forward_finds_skill_only_where_it_exists(model):
    for clustered, expect in ((True, "skill"), (False, "none")):
        report = _report(clustered=clustered, seed=3)
        study = day_type.build(report, _mask(), np.zeros(T), np.zeros(T))
        verdict = day_type.walk_forward(study, 1, model)
        assert verdict.sessions > 800
        assert np.isnan(verdict.probability[: day_type.MIN_TRAIN]).all()
        if expect == "skill":
            assert verdict.skill > day_type.SKILL_FLOOR, verdict
        else:
            assert verdict.skill < day_type.SKILL_FLOOR, verdict
        diag = day_type.exposure_diagnostic(study, verdict)
        assert set(diag) == {"cagr_scaled", "cagr_always", "drawdown_scaled", "drawdown_always"}


# The CLI payload carries every (horizon, model, window) row and a verdict
# that follows the floor.
def test_cli_payload_and_verdict(monkeypatch):
    report = _report(clustered=True, seed=5)
    monkeypatch.setattr(cli.calendar, "fomc_decisions", lambda: [])
    payload = cli.build(report, _mask())
    assert len(payload["rows"]) == len(day_type.HORIZONS) * 2 * 2
    assert {r["window"] for r in payload["rows"]} == {"2016-2023", "2024-2026"}
    assert payload["verdict"].startswith("PASSED") or payload["verdict"] == "INSUFFICIENT EVIDENCE"
    text = cli.render(payload)
    assert "verdict:" in text and "logistic" in text
