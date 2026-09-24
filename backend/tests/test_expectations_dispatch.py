"""Pin gap dispatch and plain-rule fallbacks without fitting any learner."""

import sys
from datetime import date
from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import desk
from backend.cli import market_expectations
from backend.market import challenger, language
from backend.market.store import MarketStore
from backend.market.universe import AI_SIDE, SOFTWARE_SIDE
from backend.tests.test_trading_desk import _desk_panel, _write_corrected_versions

REQUESTED_CUTOFFS = (None, date(2026, 2, 16))
NOT_FORWARDED = object()


# Exercise real desk assembly with stored corrected fundamentals and no model runtime.
@pytest.fixture
def dispatch_context(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    panel = _desk_panel()
    sides = {"N0": AI_SIDE, "N1": SOFTWARE_SIDE}
    _write_corrected_versions(store, date(2026, 2, 16))
    assembled = []
    forbidden = []
    real_assemble = desk.assemble

    # Supply the same synthetic book while leaving the requested cutoff untouched.
    def book_panel(received_store, asof=None):
        assert received_store is store
        return panel, sides

    # Return the actual empty-tone representation without importing torch.
    def load_tone_features(received_store, received_panel, asof=None):
        return language.tone_features(received_panel, {})

    # A dispatch test must never train a model or invoke an inference path.
    def forbid_fit(*args, **kwargs):
        forbidden.append("fit")
        raise AssertionError("learner fits are forbidden in dispatch tests")

    # Retain real reports so fallback and alternate identity are observable.
    def observe_assemble(*args, **kwargs):
        report = real_assemble(*args, **kwargs)
        assembled.append(report)
        return report

    monkeypatch.setattr(desk, "book_panel", book_panel)
    monkeypatch.setattr(desk, "assemble", observe_assemble)
    monkeypatch.setattr(market_expectations, "_fit_predict", forbid_fit)
    monkeypatch.setitem(
        sys.modules,
        "backend.market.model",
        SimpleNamespace(load_tone_features=load_tone_features),
    )
    return SimpleNamespace(
        store=store, panel=panel, assembled=assembled, forbidden=forbidden
    )


# Plain inputs must bypass the optional learner regardless of the requested cutoff.
@pytest.mark.parametrize("asof", REQUESTED_CUTOFFS, ids=("latest", "explicit-cutoff"))
def test_plain_inputs_bypass_gap(dispatch_context, monkeypatch, asof):
    calls = []

    # Make an accidental gap call observable even when the desk catches its exception.
    def forbidden_gap(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("plain inputs must not call the gap")

    monkeypatch.setattr(challenger, "expectations_gap", forbidden_gap)
    report = desk.run(dispatch_context.store, asof=asof, inputs=())

    assert calls == []
    assert len(dispatch_context.assembled) == 1
    assert report is dispatch_context.assembled[0]
    assert report.inputs == ()
    assert report.alternate is None
    assert dispatch_context.forbidden == []


# Preserve the actual plain report and caller's cutoff when the gap is unavailable.
@pytest.mark.parametrize("asof", REQUESTED_CUTOFFS, ids=("latest", "explicit-cutoff"))
@pytest.mark.parametrize("unavailable", ["exception", "nan"])
def test_unavailable_gap_preserves_plain_report(
    dispatch_context, monkeypatch, capsys, asof, unavailable
):
    calls = []

    # Return a controlled unavailable outcome without entering the learner pipeline.
    def unavailable_gap(received_store, received_panel, asof=NOT_FORWARDED):
        calls.append((received_store, received_panel, asof))
        if unavailable == "exception":
            raise RuntimeError("synthetic gap unavailable")
        return np.full(received_panel.adj_close.shape, np.nan)

    monkeypatch.setattr(challenger, "expectations_gap", unavailable_gap)
    report = desk.run(dispatch_context.store, asof=asof)

    assert len(dispatch_context.assembled) == 1
    assert report is dispatch_context.assembled[0]
    assert report.inputs == ()
    assert report.alternate is None
    assert "expectations_gap" not in report.opinions["value"].evidence
    output = capsys.readouterr().out
    if unavailable == "exception":
        assert "not computed (RuntimeError: synthetic gap unavailable)" in output
    else:
        assert "no values on the book; the plain rule stands in" in output
    assert len(calls) == 1
    assert calls[0][0] is dispatch_context.store
    assert calls[0][1] is dispatch_context.panel
    assert calls[0][2] is asof
    assert dispatch_context.forbidden == []


# Use real augmentation and retain the exact plain report when the gap is finite.
@pytest.mark.parametrize("asof", REQUESTED_CUTOFFS, ids=("latest", "explicit-cutoff"))
def test_finite_gap_augments_and_retains_plain_alternate(
    dispatch_context, monkeypatch, asof
):
    calls = []
    gap = np.tile([0.9, 0.1, np.nan], (len(dispatch_context.panel.dates), 1))

    # Measure dispatch with deterministic values and no model fit or inference.
    def finite_gap(received_store, received_panel, asof=NOT_FORWARDED):
        calls.append((received_store, received_panel, asof))
        return gap

    monkeypatch.setattr(challenger, "expectations_gap", finite_gap)
    report = desk.run(dispatch_context.store, asof=asof)

    assert len(dispatch_context.assembled) == 2
    plain, augmented = dispatch_context.assembled
    assert report is not plain
    assert report.alternate is plain
    assert plain.alternate is None
    assert plain.inputs == ()
    assert report.inputs == augmented.inputs == (desk.EXPECTATIONS_GAP,)
    assert report.panel is plain.panel is dispatch_context.panel
    assert report.fundamentals_source == plain.fundamentals_source
    assert report.opinions["fundamental"] is plain.opinions["fundamental"]
    assert report.opinions["technical"] is plain.opinions["technical"]
    assert report.opinions["sentiment"] is plain.opinions["sentiment"]
    assert report.opinions["value"] is not plain.opinions["value"]
    assert "expectations_gap" not in plain.opinions["value"].evidence
    np.testing.assert_equal(report.opinions["value"].evidence["expectations_gap"], gap)
    assert np.isfinite(report.opinions["value"].scores).any()
    np.testing.assert_equal(report.graded.grades, augmented.graded.grades)
    np.testing.assert_equal(report.scores, augmented.scores)
    assert len(calls) == 1
    assert calls[0][0] is dispatch_context.store
    assert calls[0][1] is dispatch_context.panel
    assert calls[0][2] is asof
    assert dispatch_context.forbidden == []
