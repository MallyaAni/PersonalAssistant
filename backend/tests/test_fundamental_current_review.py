"""Independent current-desk integration and source-contract regression checks."""

import json
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from backend.agents.trading.desk import desk, fundamental
from backend.cli import market_daily
from backend.market import fundamental_features as ff
from backend.market import fundamentals_asof as fa
from backend.market.store import MarketStore
from backend.market.universe import AI_COMPUTE, AI_SIDE, SOFTWARE, SOFTWARE_SIDE
from backend.tests.test_fundamental_current_path import _inputs, _score_panel
from backend.tests.test_fundamental_period_eligibility import (
    ALTERNATIVE,
    _history,
    _panel,
    _version,
)
from backend.tests.test_market_daily import _report
from backend.tests.test_trading_desk import torch_loaders  # noqa: F401

RECOVERY_DAYS = (
    "2026-04-27",
    "2026-04-28",
    "2026-04-29",
    "2026-05-04",
    "2026-05-05",
    "2026-05-06",
    "2026-05-07",
    "2026-05-08",
    "2026-05-11",
)


# Produce accepted growth beside rejected margins so name/date mixups are visible.
def _mixed_eligibility():
    versions = _history() + [
        _version("revenue", "2026-01-01", "2026-03-31", 150.0, filed="2026-05-01")
    ]
    return ff.current_features(_score_panel(), _inputs(versions))


# Reordering all named tensors consistently must not mislabel their saved decisions.
def test_reordered_named_features_keep_correct_serialized_eligibility():
    features = _mixed_eligibility()
    order = [3, 1, 2, 0, 4, 5, 6]
    reordered = replace(
        features,
        names=tuple(features.names[i] for i in order),
        values=features.values[..., order],
        period_ends=features.period_ends[..., order],
        eligibility=replace(
            features.eligibility,
            input_period_ends=features.eligibility.input_period_ends[..., order],
            reasons=features.eligibility.reasons[..., order],
        ),
    )
    original = fundamental.opine_current(features)
    changed = fundamental.opine_current(reordered)
    np.testing.assert_array_equal(changed.scores, original.scores)
    np.testing.assert_array_equal(changed.stance_resets, original.stance_resets)
    expected = fundamental.cited_eligibility(original, 3, 0)
    assert fundamental.cited_eligibility(changed, 3, 0) == expected


# Accepted values cannot be tagged current under an unrelated target reporting period.
def test_current_source_rejects_target_period_inconsistent_with_accepted_values():
    features = _mixed_eligibility()
    malformed = replace(
        features,
        eligibility=replace(
            features.eligibility,
            target_period_ends=np.full(
                features.available.shape, np.datetime64("2099-01-01", "D")
            ),
        ),
    )
    with pytest.raises(ValueError, match="eligibility|period"):
        fundamental.opine_current(malformed)


# Every /3 tensor must align before ranking or record serialization starts.
@pytest.mark.parametrize(
    "field",
    [
        "target_period_ends",
        "input_period_ends",
        "period_ends",
        "available",
        "staleness",
        "values",
    ],
)
def test_current_source_rejects_misaligned_tensor_shapes(field):
    features = _mixed_eligibility()
    if field in ("target_period_ends", "input_period_ends"):
        array = getattr(features.eligibility, field)
        malformed = replace(
            features,
            eligibility=replace(features.eligibility, **{field: array[:, :-1]}),
        )
    else:
        malformed = replace(features, **{field: getattr(features, field)[:, :-1]})
    with pytest.raises(ValueError, match="eligibility|shape|dimension"):
        fundamental.opine_current(malformed)


# Duplicate names cannot give two tensor columns the same financial identity.
def test_current_source_rejects_duplicate_feature_names():
    features = _mixed_eligibility()
    names = (features.names[1],) + features.names[1:]
    with pytest.raises(ValueError, match="names|feature"):
        fundamental.opine_current(replace(features, names=names))


# An unknown rejection label cannot become source-qualified recorded evidence.
def test_current_source_rejects_undeclared_eligibility_status():
    features = _mixed_eligibility()
    reasons = features.eligibility.reasons.copy()
    reasons[3, 0, features.names.index("gross_margin")] = "invented_reason"
    malformed = replace(
        features, eligibility=replace(features.eligibility, reasons=reasons)
    )
    with pytest.raises(ValueError, match="eligibility|status|reason"):
        fundamental.opine_current(malformed)


# Neither the original nor returned accepted period can disagree with its target.
@pytest.mark.parametrize("field", ["input_period_ends", "period_ends"])
def test_current_source_rejects_misdated_accepted_feature(field):
    features = _mixed_eligibility()
    owner = features.eligibility if field == "input_period_ends" else features
    dates = getattr(owner, field).copy()
    dates[3, 0, features.names.index("revenue_yoy")] = np.datetime64("2020-03-31")
    malformed = (
        replace(features, eligibility=replace(features.eligibility, **{field: dates}))
        if field == "input_period_ends"
        else replace(features, **{field: dates})
    )
    with pytest.raises(ValueError, match="eligibility|period"):
        fundamental.opine_current(malformed)


# Current and prior-source labels cannot be swapped in either direction when saving.
@pytest.mark.parametrize("current_opinion", [False, True])
def test_record_rejects_source_mismatch_in_both_directions(current_opinion):
    report = _report()
    features = ff.current_features(report.panel, {"SNDK": _history()})
    opinion = (
        fundamental.opine_current(features)
        if current_opinion
        else fundamental.opine_corrected(features)
    )
    mismatched = replace(
        report,
        opinions={fundamental.NAME: opinion},
        fundamentals_source=(
            fundamental.CORRECTED_SOURCE
            if current_opinion
            else fundamental.CURRENT_SOURCE
        ),
    )
    with pytest.raises(ValueError, match="fundamental source"):
        market_daily.record(mismatched)


# Store a temporary loss of current inputs followed by same-concept valid recovery.
def _recovery_store(tmp_path):
    store = MarketStore(tmp_path)
    versions = _history() + [
        _version(
            "revenue",
            "2026-01-01",
            "2026-03-31",
            150.0,
            filed="2026-05-01",
            tag=ALTERNATIVE,
        ),
        _version("revenue", "2026-01-01", "2026-03-31", 150.0, filed="2026-05-06"),
        _version("gross_profit", "2026-01-01", "2026-03-31", 45.0, filed="2026-05-06"),
    ]
    for cutoff in (date(2026, 4, 29), date(2026, 5, 6), date(2026, 5, 11)):
        for ticker, rows in _inputs(versions).items():
            eligible_rows = [row for row in rows if row.filed <= cutoff]
            store.write_frame(
                fa.KIND,
                cutoff,
                ticker,
                fa.frame(eligible_rows),
                {"source": "synthetic-review"},
            )
    return store


# Replace book discovery while exercising actual store, feature, vote and grade paths.
def _run_review_desk(store, monkeypatch, days, mode):
    panel = _panel(days, tickers=("TEST", "PEER", "ABSENT", "SPY"))
    panel = replace(
        panel,
        themes={"TEST": (AI_COMPUTE,), "PEER": (SOFTWARE,), "ABSENT": (SOFTWARE,)},
    )
    sides = {"TEST": AI_SIDE, "PEER": SOFTWARE_SIDE, "ABSENT": SOFTWARE_SIDE}

    # Supply a fixed test universe while preserving the caller's real partition cutoff.
    def book_panel(store, asof=None):
        assert asof == date.fromisoformat(days[-1])
        return panel, sides

    monkeypatch.setattr(desk, "book_panel", book_panel)
    return desk.run(store, date.fromisoformat(days[-1]), inputs=(), fundamentals=mode)


# Full desk execution re-confirms votes after missing inputs and peer ranks return.
@pytest.mark.usefixtures("torch_loaders")
def test_full_current_desk_clears_missing_and_peer_rank_votes_then_recovers(
    tmp_path, monkeypatch
):
    store = _recovery_store(tmp_path)
    report = _run_review_desk(store, monkeypatch, RECOVERY_DAYS, "current")
    opinion = report.opinions[fundamental.NAME]
    assert (
        report.fundamentals_source
        == opinion.meta["source"]
        == fundamental.CURRENT_SOURCE
    )
    assert report.panel.tickers == ("TEST", "PEER", "ABSENT", "SPY")
    assert report.graded.stances[fundamental.NAME][:, 0].tolist() == [
        1,
        1,
        1,
        0,
        0,
        0,
        0,
        0,
        1,
    ]
    assert report.graded.stances[fundamental.NAME][:, 1].tolist() == [
        -1,
        -1,
        -1,
        0,
        0,
        0,
        0,
        0,
        -1,
    ]
    # PEER retains accepted raw inputs but cannot rank while it is the only name.
    assert np.isfinite(opinion.evidence["revenue_yoy"][:, 1]).all()
    assert np.isnan(opinion.scores[3:6, :2]).all()
    assert opinion.stance_resets[3:6, :2].all()
    assert np.isfinite(opinion.scores[6:, :2]).all()
    assert not opinion.stance_resets[6:, :2].any()
    assert np.isnan(opinion.scores[:, 2:]).all()
    assert opinion.stance_resets[:, 2:].all()
    np.testing.assert_array_equal(
        report.graded.stances[fundamental.NAME], opinion.stances()
    )
    assert report.brief("TEST")["stances"][fundamental.NAME] == 1
    assert report.brief("ABSENT")["stances"][fundamental.NAME] == 0


# New records retain rejected names without changing an already saved /2 history row.
@pytest.mark.usefixtures("torch_loaders")
def test_full_desk_saved_records_keep_all_names_and_do_not_relabel_history(
    tmp_path, monkeypatch
):
    store = _recovery_store(tmp_path)
    prior = _run_review_desk(store, monkeypatch, RECOVERY_DAYS[:3], "corrected")
    prior_path = market_daily.save(tmp_path, market_daily.record(prior))
    prior_bytes = prior_path.read_bytes()
    current = _run_review_desk(store, monkeypatch, RECOVERY_DAYS[:6], "current")
    data = market_daily.record(current)
    path = market_daily.save(tmp_path, data)
    saved = json.loads(path.read_bytes())
    assert set(saved["grades"]) == {"TEST", "PEER", "ABSENT"}
    assert set(saved["fundamental"]["dates"]) == {"TEST", "PEER", "ABSENT"}
    assert set(saved["fundamental"]["eligibility"]) == {"TEST", "PEER", "ABSENT"}
    assert saved["fundamental"]["eligibility"]["TEST"]["score_available"] is False
    assert saved["fundamental"]["eligibility"]["PEER"]["score_available"] is False
    assert saved["fundamental"]["eligibility"]["ABSENT"]["vote_reset"] is True
    for ticker in ("TEST", "PEER", "ABSENT"):
        assert saved["grades"][ticker]["stances"][fundamental.NAME] == 0
    assert prior_path.read_bytes() == prior_bytes
    previous = json.loads(prior_bytes)
    assert previous["fundamental"]["source"] == fundamental.CORRECTED_SOURCE
    assert "eligibility" not in previous["fundamental"]
    assert saved["fundamental"]["source"] == fundamental.CURRENT_SOURCE
