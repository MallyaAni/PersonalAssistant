"""The A2 statement-reading arithmetic, point-in-time rules and null test.

The pre-registration (`docs/research/statement-reading-preregistration-2026-11-01.md`)
fixes the packet, the label, the stance and the perturbation test. These
tests hold the implementation to those words on synthetic version sets:
the dimensionless packet, the six-of-eight sample rule, the first-filed
label, the flat band, the restatement dedupe, future versions not moving
the past, missing facts staying NA, and the scoring primitives.
"""

from __future__ import annotations

import json
import math
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from backend.market import fundamentals_asof as fa
from backend.market import statement_reading as sr

REVENUE = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
NET_INCOME = "us-gaap:NetIncomeLoss"
GROSS = "us-gaap:GrossProfit"
OCF = "us-gaap:NetCashProvidedByUsedInOperatingActivities"
CAPEX = "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
DECISION = date(2026, 8, 3)
LABEL_ASOF = date(2026, 10, 30)


# Quarter ends stepping back from 2026-06-30, oldest first.
def _ends(count: int = 20) -> list[date]:
    """Return `count` synthetic quarter ends, oldest first."""
    return [
        date(2026, 6, 30) - timedelta(days=91 * step)
        for step in range(count)
    ][::-1]


# One flow's synthetic versions: a quarter span per end, filed 45 days later.
def _flow(
    name: str,
    tag: str,
    base: float,
    growth: float,
    count: int = 20,
) -> list[fa.Version]:
    """Return `count` synthetic quarter versions for one fact."""
    out = []
    for index, end in enumerate(_ends(count)):
        start = end - timedelta(days=90)
        out.append(
            fa.Version(
                name=name,
                tag=tag,
                start=start,
                end=end,
                value=base * (1.0 + growth) ** index,
                filed=end + timedelta(days=45),
                accepted=None,
                accession=f"{name}-{end.isoformat()}",
                form="10-Q",
            )
        )
    return out


# A complete synthetic company.
def _versions() -> list[fa.Version]:
    """Return a complete five-fact synthetic version set."""
    return (
        _flow("revenue", REVENUE, 1000.0, 0.02)
        + _flow("net_income", NET_INCOME, 100.0, 0.03)
        + _flow("gross_profit", GROSS, 400.0, 0.02)
        + _flow("operating_cash_flow", OCF, 200.0, 0.02)
        + _flow("capex", CAPEX, 50.0, 0.02)
    )


# A packet from the complete set.
def _packet() -> sr.Packet:
    """Return the synthetic packet at DECISION."""
    packet = sr.build_packet(_versions(), DECISION)
    assert packet is not None
    return packet


# The packet is eight rows, dimensionless, and its latest row is the index base.
def test_packet_shape_and_index() -> None:
    packet = _packet()
    assert len(packet.rows) == 8
    assert [row.quarter for row in packet.rows] == [f"t-{7 - i}" for i in range(8)]
    assert packet.rows[-1].revenue_index == 100.0
    assert packet.anchor == date(2026, 3, 31)
    view = packet.view()
    assert view["packet_version"] == sr.PACKET_VERSION
    assert "2026" not in json.dumps(view)
    assert "AAPL" not in json.dumps(view)
    for row in packet.rows:
        for name in sr.COLUMNS:
            value = getattr(row, name)
            assert value is None or math.isfinite(value)
    expected = round(
        100.0 * (100.0 * 1.03**18) / (1000.0 * 1.02**18), 2
    )
    assert packet.rows[-1].net_margin_pct == pytest.approx(expected)


# A name with fewer than six net-income or revenue rows is missing, not neutral.
def test_sample_requires_six_rows() -> None:
    short = (
        _flow("revenue", REVENUE, 1000.0, 0.02, count=5)
        + _flow("net_income", NET_INCOME, 100.0, 0.03, count=5)
        + _flow("gross_profit", GROSS, 400.0, 0.02)
        + _flow("operating_cash_flow", OCF, 200.0, 0.02)
        + _flow("capex", CAPEX, 50.0, 0.02)
    )
    assert sr.build_packet(short, DECISION) is None


# A future version, however large, cannot move the packet.
def test_future_version_is_ignored() -> None:
    versions = _versions()
    future = replace(
        versions[1],
        end=date(2026, 6, 30),
        start=date(2026, 4, 1),
        value=1e12,
        filed=date(2026, 8, 15),
        accession="future",
    )
    baseline = sr.build_packet(versions, DECISION)
    shifted = sr.build_packet(versions + [future], DECISION)
    assert baseline is not None
    assert shifted is not None
    assert json.dumps(baseline.view(), sort_keys=True) == json.dumps(
        shifted.view(), sort_keys=True
    )


# A later restatement of the same span wins; the earlier one no longer counts.
def test_restatement_dedupe() -> None:
    versions = _versions()
    anchor = next(
        version
        for version in versions
        if version.name == "net_income" and version.end == date(2026, 3, 31)
    )
    restated = replace(
        anchor,
        value=anchor.value * 2.0,
        filed=date(2026, 7, 1),
        accession="restated",
    )
    packet = sr.build_packet(versions + [restated], DECISION)
    assert packet is not None
    assert packet.rows[-1].net_margin_pct == pytest.approx(
        round(100.0 * (200.0 * 1.03**18) / (1000.0 * 1.02**18), 2)
    )
    earlier = replace(anchor, value=1.0)
    altered = [
        earlier if version is anchor else version
        for version in versions + [restated]
    ]
    same = sr.build_packet(altered, DECISION)
    assert same is not None
    assert json.dumps(packet.view(), sort_keys=True) == json.dumps(
        same.view(), sort_keys=True
    )


# The label is the first quarter after the anchor, first filed after the decision.
def test_label_first_public_after_decision() -> None:
    packet = _packet()
    label = sr.build_label(_versions(), packet, DECISION, LABEL_ASOF)
    assert label is not None
    assert label["next_end"] == date(2026, 6, 30)
    assert label["next_available"] == date(2026, 8, 15)
    assert label["label"] == "up"


# A next quarter already public at the decision gives no label, not the quarter after.
def test_label_refuses_already_public_next_quarter() -> None:
    versions = _versions()
    next_quarter = next(
        version
        for version in versions
        if version.name == "net_income" and version.end == date(2026, 6, 30)
    )
    published = replace(
        next_quarter,
        filed=date(2026, 7, 1),
        accession="published",
    )
    altered = [
        published if version is next_quarter else version
        for version in versions
    ]
    packet = sr.build_packet(altered, DECISION)
    assert packet is not None
    assert sr.build_label(altered, packet, DECISION, LABEL_ASOF) is None


# A change inside one percent of the absolute year-ago value is flat.
def test_label_flat_band() -> None:
    versions = _versions()
    packet = _packet()
    first = sr.build_label(versions, packet, DECISION, LABEL_ASOF)
    assert first is not None
    year_ago = first["year_ago_value"]
    next_quarter = next(
        version
        for version in versions
        if version.name == "net_income" and version.end == date(2026, 6, 30)
    )
    near = replace(next_quarter, value=year_ago * 1.005, accession="near")
    altered = [near if version is next_quarter else version for version in versions]
    label = sr.build_label(altered, packet, DECISION, LABEL_ASOF)
    assert label is not None
    assert label["label"] == "flat"


# Without a year-ago quarter in the registered window, the name has no label.
def test_label_needs_year_ago() -> None:
    versions = [
        version
        for version in _versions()
        if not (version.name == "net_income" and version.end == date(2025, 7, 1))
    ]
    packet = sr.build_packet(versions, DECISION)
    assert packet is not None
    assert sr.build_label(versions, packet, DECISION, LABEL_ASOF) is None


# The null test passes on the complete set.
def test_perturbation_check() -> None:
    result = sr.perturbation_check(_versions(), DECISION)
    assert result["future_identical"] is True
    assert result["newest_changes"] is True
    assert result["missing_is_na"] is True


# Removing gross profit leaves every gross margin NA, not zero.
def test_missing_gross_profit_is_na() -> None:
    versions = [version for version in _versions() if version.name != "gross_profit"]
    packet = sr.build_packet(versions, DECISION)
    assert packet is not None
    assert all(row.gross_margin_pct is None for row in packet.rows)
    assert sr.perturbation_check(versions, DECISION)["missing_is_na"] is True


# The schema is strict and carries the registered enum and bounds.
def test_schema_shape() -> None:
    text = json.dumps(sr.SCHEMA)
    assert sr.SCHEMA["additionalProperties"] is False
    assert set(sr.SCHEMA["required"]) == {"analysis", "direction", "confidence"}
    assert sr.SCHEMA["properties"]["direction"]["enum"] == list(sr.DIRECTIONS)
    assert sr.SCHEMA["properties"]["confidence"]["minimum"] == 0
    assert sr.SCHEMA["properties"]["confidence"]["maximum"] == 1
    assert "analysis" in text


# A valid answer parses; bad directions, confidence and empty analysis do not.
def test_parse_answer() -> None:
    answer = sr.parse_answer(
        '{"analysis":" revenue is rising ","direction":"up","confidence":0.6}'
    )
    assert answer == {
        "analysis": "revenue is rising",
        "direction": "up",
        "confidence": 0.6,
    }
    for bad in (
        '{"analysis":"x","direction":"maybe","confidence":0.5}',
        '{"analysis":"x","direction":"up","confidence":1.5}',
        '{"analysis":"","direction":"up","confidence":0.5}',
        '{"analysis":"x","direction":"up"}',
        "[]",
    ):
        with pytest.raises(
            ValueError, match="direction|confidence|analysis|answer"
        ):
            sr.parse_answer(bad)


# The sign stance and the confidence-weighted stance map the four directions.
def test_stance_mapping() -> None:
    up = {"direction": "up", "confidence": 0.8}
    down = {"direction": "down", "confidence": 0.3}
    flat = {"direction": "flat", "confidence": 0.9}
    uncertain = {"direction": "uncertain", "confidence": 0.2}
    assert sr.stance(up) == 1.0
    assert sr.stance(down) == -1.0
    assert sr.stance(flat) == 0.0
    assert np.isnan(sr.stance(uncertain))
    assert np.isnan(sr.stance(None))
    assert sr.confidence_stance(up) == 0.8
    assert sr.confidence_stance(down) == -0.3
    assert sr.confidence_stance(flat) == 0.0
    assert np.isnan(sr.confidence_stance(uncertain))


# Coverage counts the non-uncertain answers over the labelled sample.
def test_accuracy_stats() -> None:
    rows = [
        {"answer": {"direction": "up"}, "label": {"label": "up"}},
        {"answer": {"direction": "down"}, "label": {"label": "up"}},
        {"answer": {"direction": "uncertain"}, "label": {"label": "down"}},
        {"answer": None, "label": {"label": "flat"}},
    ]
    stats = sr.accuracy_stats(rows)
    assert stats["labelled"] == 4
    assert stats["answered_with_model"] == 3
    assert stats["answered"] == 2
    assert stats["coverage"] == 0.5
    assert stats["correct"] == 1
    assert stats["accuracy"] == 0.5
    assert stats["uncertain"] == 1


# The exact binomial tail matches the closed form at small n.
def test_binomial_tail() -> None:
    assert sr.binomial_tail(0, 0) == 1.0
    assert sr.binomial_tail(2, 2, 0.5) == pytest.approx(0.25)
    assert sr.binomial_tail(1, 2, 0.5) == pytest.approx(0.75)
    assert sr.binomial_tail(0, 2, 0.5) == pytest.approx(1.0)


# A stance in the same order as the forward return earns a perfect daily IC.
def test_daily_ic_perfect_and_constant() -> None:
    forward = np.array(
        [
            [0.1, 0.2, 0.3, np.nan],
            [0.1, 0.2, 0.3, np.nan],
        ]
    )
    stance = np.array(
        [
            [1.0, 2.0, 3.0, np.nan],
            [1.0, 1.0, 1.0, np.nan],
        ]
    )
    ics = sr.daily_ic(stance, forward, benchmark=3, min_names=3)
    assert ics[0] == pytest.approx(1.0)
    assert np.isnan(ics[1])


# Newey-West returns None for a constant series and a finite t otherwise.
def test_newey_west() -> None:
    assert sr.newey_west_t(np.array([0.1, 0.1, 0.1]), 1) is None
    values = np.array([0.1, 0.2, 0.15, 0.25, 0.05, 0.3])
    t = sr.newey_west_t(values, 2)
    assert t is not None
    assert math.isfinite(t)


# The weekly block bootstrap resamples whole weeks and returns a finite interval.
def test_block_bootstrap() -> None:
    values = np.array([0.1, 0.2, 0.1, 0.2])
    weeks = [(2026, 1), (2026, 1), (2026, 2), (2026, 2)]
    result = sr.block_bootstrap(values, weeks, draws=100, seed=7)
    assert result["draws"] == 100
    assert result["mean"] == pytest.approx(0.15)
    assert result["lower"] is not None
    assert result["upper"] is not None
    assert result["lower"] <= result["mean"] + 1e-12 <= result["upper"] + 1e-12


# The stance placebo preserves the missing mask and returns a percentile.
def test_stance_placebo() -> None:
    forward = np.array([[0.1, 0.2, 0.3, np.nan]] * 2)
    stance = np.array([[1.0, 2.0, 3.0, np.nan], [1.0, 2.0, 3.0, np.nan]])
    window = np.array([True, True])
    result = sr.stance_placebo(
        stance,
        forward,
        benchmark=3,
        sessions=window,
        draws=20,
        min_names=3,
    )
    assert result["draws"] == 20
    assert result["p95"] is not None
    empty = np.full_like(stance, np.nan)
    empty_result = sr.stance_placebo(
        empty,
        forward,
        benchmark=3,
        sessions=window,
        draws=5,
        min_names=3,
    )
    assert empty_result["draws"] == 0


# ISO week ids group the sessions into independent weeks.
def test_week_ids() -> None:
    days = [date(2026, 8, 3), date(2026, 8, 7), date(2026, 8, 10)]
    weeks = sr.week_ids(days)
    assert weeks[0] == weeks[1]
    assert weeks[0] != weeks[2]
