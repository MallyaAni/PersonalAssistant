"""The tone-surprise arm's arithmetic, alignment and no-look-ahead checks.

The pre-registration (`docs/research/tone-surprise-preregistration-2026-10-28.md`)
fixes the signal, the missing rule and the perturbation test. These tests
hold the implementation to those words on a synthetic panel: the sum over
the five fields, the first release having no view, the strict alignment
differing only on reaction-date sessions, future records not moving the
past, and a constant score producing no defined IC.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from backend.cli import market_tone_surprise_research as study
from backend.market import language
from backend.market.harness import evaluate_scores
from backend.market.panel import Panel

DAYS = [
    date(2024, 1, 2),
    date(2024, 1, 5),
    date(2024, 1, 8),
    date(2024, 1, 11),
    date(2024, 1, 15),
]


# A tiny panel: two names and a benchmark on the given sessions.
def _panel(days=DAYS) -> Panel:
    shape = (len(days), 3)
    close = np.full(shape, 100.0)
    return Panel(
        dates=np.asarray(days, dtype="datetime64[D]"),
        tickers=("AAA", "BBB", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full(shape, 1e6),
        themes={"AAA": ("ai",), "BBB": ("ai",)},
        benchmark="SPY",
    )


# One scored release with the five fields set explicitly.
def _record(when: date, guidance=0.0, demand=0.0, pricing=0.0, capex=0.0, supply=0.0):
    return language.ToneRecord(
        accession=f"A-{when.isoformat()}",
        reaction_date=when,
        guidance=guidance,
        demand=demand,
        pricing=pricing,
        capex=capex,
        supply_constrained=supply,
        summary="s",
        model="m",
        prompt_version="p",
        truncated=False,
    )


# The signal is the five-field change, carried to the next release.
def test_surprise_sums_five_changes_and_carries_forward():
    records = {
        "AAA": [
            _record(DAYS[0]),
            _record(DAYS[1], guidance=1, demand=1),
            _record(DAYS[2]),
        ],
        "BBB": [_record(DAYS[0], guidance=1)],
    }
    out = study.surprise_matrix(_panel(), records)
    aaa = out[:, 0]
    assert np.isnan(aaa[0])  # the first release has no previous release
    assert aaa[1] == 2.0
    assert aaa[2] == -2.0
    assert aaa[3] == -2.0
    assert aaa[4] == -2.0
    assert np.isnan(out[:, 1]).all()  # one release is a level, not a surprise


# Strict alignment differs only where a release's reaction date is the session.
def test_strict_alignment_differs_only_on_reaction_sessions():
    records = {
        "AAA": [
            _record(DAYS[0]),
            _record(DAYS[1], guidance=1),
            _record(DAYS[2], demand=1),
        ]
    }
    legacy = study.surprise_matrix(_panel(), records)
    strict = study.surprise_matrix(_panel(), records, strict=True)
    reaction = {DAYS[1], DAYS[2]}
    for index, day in enumerate(DAYS):
        same = np.array_equal(
            np.isnan(legacy[index]), np.isnan(strict[index])
        ) and np.allclose(
            np.nan_to_num(legacy[index]), np.nan_to_num(strict[index])
        )
        if day in reaction:
            assert not same, f"{day} should differ under strict alignment"
        else:
            assert same, f"{day} should be identical under strict alignment"


# Changing records after the cutoff leaves the past byte-identical.
def test_future_records_do_not_move_the_past():
    records = {
        "AAA": [
            _record(DAYS[0]),
            _record(DAYS[1], guidance=1),
            _record(DAYS[2], demand=1),
            _record(DAYS[4], pricing=1),
        ]
    }
    check = study.perturbation_check(_panel(), records, cutoff=3)
    assert check["future_identical"] is True
    assert check["newest_changes"] is True
    assert check["name"] == "AAA"


# A constant score has no rank correlation, so the null arm reports no IC.
def test_a_constant_score_produces_no_defined_ic():
    rng = np.random.default_rng(3)
    days = [date(2020, 1, 2) + timedelta(days=7 * k) for k in range(80)]
    names = tuple(f"N{k:02d}" for k in range(24)) + ("SPY",)
    shape = (len(days), len(names))
    close = 100.0 * np.exp(rng.normal(0.0004, 0.02, size=shape).cumsum(axis=0))
    panel = Panel(
        dates=np.asarray(days, dtype="datetime64[D]"),
        tickers=names,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full(shape, 1e6),
        themes={name: ("ai",) for name in names[:-1]},
        benchmark="SPY",
    )
    scores = np.zeros(shape)
    report = evaluate_scores(scores, panel, 20, beta_adjusted=True, min_names=20)
    stats = study.period_stats(report, 2016, 2023)
    assert stats["n"] == 0
    assert stats["mean_ic"] is None


# The period window keeps only the years it names.
def test_period_stats_filters_by_year():
    periods = tuple(
        SimpleNamespace(date=np.datetime64(f"{year}-06-01"), rank_ic=value)
        for year, value in ((2015, 0.10), (2020, 0.02), (2025, 0.05))
    )
    stats = study.period_stats(SimpleNamespace(periods=periods), 2016, 2023)
    assert stats["n"] == 1
    assert stats["mean_ic"] == pytest.approx(0.02)


# The HAC t refuses a series with no variance instead of dividing by zero.
def test_newey_west_t_refuses_a_constant_series():
    assert study._newey_west_t(np.full(10, 0.01), lag=1) is None
