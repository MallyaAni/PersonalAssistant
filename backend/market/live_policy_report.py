"""Causal report inputs for replaying the actual nightly planner.

Recorded grades are supplied, not recomputed. Historical price prefixes use
today's raw-share units uniformly; current-vintage dividends and membership
are not evidence of historical publication or original analyst convictions.
"""

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from backend.agents.trading.desk.grading import Graded
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_execution_inputs import DAILY_BASIS, RawExecutionInputs
from backend.market.panel import Panel


# Carry only the fields the actual nightly policy and action display consume.
@dataclass(frozen=True)
class NightlyReport:
    panel: Panel
    graded: Graded
    sides: dict
    scores: np.ndarray
    excluded: tuple
    provenance: dict


# Refuse unsupported relationships before constructing any nightly decision inputs.
def _require(condition, message):
    if not condition:
        raise ValueError(message)


# Copy a supplied causal prefix without permitting writes into original source arrays.
def _prefix(array, day, columns, factors=None):
    value = np.asarray(array)
    result = (value[: day + 1] if value.ndim == 1 else value[: day + 1, columns]).copy()
    if factors is not None:
        result = result * factors
    result.flags.writeable = False
    return result


# Bind the raw adapter to the original panel and membership bytes before reuse.
def _validate(panel, raw, grades, eligible, day):
    _require(isinstance(panel, Panel), "Original Panel required")
    _require(isinstance(raw, RawExecutionInputs), "Raw execution adapter required")
    _require(
        isinstance(day, (int, np.integer))
        and not isinstance(day, (bool, np.bool_))
        and 0 <= day < len(panel.dates),
        "Existing integer report day required",
    )
    shape = (len(panel.dates), len(panel.tickers))
    _require(
        panel.benchmark == "SPY"
        and "SPY" in panel.tickers
        and len(set(panel.tickers)) == len(panel.tickers)
        and np.asarray(panel.dates).dtype == np.dtype("datetime64[D]")
        and np.array_equal(panel.dates, raw.dates)
        and panel.tickers == raw.tickers,
        "Aligned original sessions, symbols and SPY benchmark required",
    )
    _require(
        grades.shape == shape
        and grades.dtype.kind in "iu"
        and np.isin(grades, (-1, 0, 1, 2, 3)).all()
        and eligible.shape == shape
        and eligible.dtype.kind == "b"
        and np.array_equal(grades, raw.grades)
        and np.array_equal(eligible, raw.eligible),
        "Original grades and explicit membership required",
    )
    provenance = raw.provenance
    _require(
        isinstance(provenance, Mapping)
        and provenance.get("daily_price_basis") == DAILY_BASIS
        and isinstance(provenance.get("supplied"), Mapping)
        and bool(provenance["supplied"])
        and provenance.get("grade_sha256") == _hash(grades)
        and provenance.get("eligible_sha256") == _hash(eligible),
        "Authenticated raw adapter source relationship required",
    )
    source = provenance.get("daily_source_arrays", {})
    for field in ("dates", "open", "high", "low", "close", "adj_close"):
        value = np.asarray(getattr(panel, field))
        _require(
            source.get(field) == _hash(value), "Original daily array identity mismatch"
        )
        if field != "dates":
            _require(
                value.shape == shape, "Aligned original daily price arrays required"
            )
    _require(
        np.asarray(panel.volume).shape == shape
        and np.asarray(panel.volume).dtype.kind in "fiu"
        and not np.isinf(panel.volume).any()
        and np.all(panel.volume[np.isfinite(panel.volume)] >= 0)
        and raw.split_factors.shape == shape
        and np.isfinite(raw.split_factors).all()
        and (raw.split_factors > 0).all(),
        "Aligned volume and positive dated split factors required",
    )
    for field in ("open", "high", "low", "close"):
        expected = getattr(panel, field)[: day + 1] * raw.split_factors[: day + 1]
        _require(
            np.array_equal(
                getattr(raw, "daily_" + field)[: day + 1], expected, equal_nan=True
            ),
            "Raw daily price relationship mismatch",
        )


# Construct today's actual policy report with a causal, consistently scaled history.
def build(panel, raw_inputs, grades, eligible, day):
    grades, eligible = np.asarray(grades), np.asarray(eligible)
    _validate(panel, raw_inputs, grades, eligible, day)
    columns, excluded = [], []
    for column, name in enumerate(panel.tickers):
        reasons = []
        if name == "QQQ":
            reasons.append("non_stock_benchmark")
        elif name != "SPY":
            if grades[day, column] < 0:
                reasons.append("grade_unavailable")
            if not eligible[day, column]:
                reasons.append("not_declared_eligible")
            if not np.isfinite(panel.close[day, column]):
                reasons.append("close_unavailable")
        if reasons:
            excluded.append({"ticker": name, "reasons": tuple(reasons)})
        else:
            columns.append(column)
    names = tuple(panel.tickers[column] for column in columns)
    factors = raw_inputs.split_factors[day, columns]
    values = {
        field: _prefix(getattr(panel, field), day, columns, factors)
        for field in ("open", "high", "low", "close", "adj_close")
    }
    _require(
        all(not np.isinf(value).any() for value in values.values()),
        "Current-session share-unit conversion overflow",
    )
    prefix = Panel(
        _prefix(panel.dates, day, slice(None)),
        names,
        values["open"],
        values["high"],
        values["low"],
        values["close"],
        values["adj_close"],
        _prefix(panel.volume, day, columns),
        {name: tuple(panel.themes.get(name, ())) for name in names},
        "SPY",
    )
    ordinals = _prefix(grades, day, columns)
    benchmark = prefix.index("SPY")
    ordinals = ordinals.copy()
    ordinals[-1, benchmark] = 0
    ordinals.flags.writeable = False
    votes = np.full(ordinals.shape, np.nan)
    votes.flags.writeable = False
    scores = ordinals.astype(float)
    scores[ordinals < 0] = np.nan
    scores[:, benchmark] = np.nan
    scores.flags.writeable = False
    graded = Graded(ordinals, votes, {})
    return NightlyReport(
        prefix,
        graded,
        {name: "unavailable" for name in names if name != "SPY"},
        scores,
        tuple(excluded),
        {
            "session": str(panel.dates[day]),
            "price_basis": "entire_prefix_in_current_session_raw_share_dollars",
            "split_factors": dict(zip(names, factors.tolist(), strict=True)),
            "historical_availability": (
                "current_vintage_not_historical_publication_evidence"
            ),
            "adjusted_close": (
                "original_current_vintage_dividend_adjustment_scaled_"
                "to_current_share_units"
            ),
            "volume": "original_archive_volume_preserved_without_share_conversion",
            "analyst_votes_stances": "unavailable_not_reconstructed",
            "scores": "ordinal_grade_display_order_only_not_analyst_conviction",
            "benchmark_grade": "neutral_display_metadata_only_never_targeted",
            "historical_unknown_grades": "minus_one_preserved_not_a_letter_grade",
            "raw_source_arrays": dict(raw_inputs.provenance["daily_source_arrays"]),
            "prefix_arrays": {field: _hash(getattr(prefix, field)) for field in values},
            "prefix_grades_sha256": _hash(ordinals),
        },
    )
