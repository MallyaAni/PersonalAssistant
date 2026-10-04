"""Supplied-array raw-dollar inputs for whole-share live-policy research.

Dated splits reverse the daily archive's declared split adjustment only.
Dividend-adjusted closes and observed price ratios never set conversion factors.
Future action facts describe archive units, not historical feature availability.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType

import numpy as np

from backend.market import calendar
from backend.market.daily_arithmetic_bridge import _hash

DAILY_BASIS = "split_adjusted_daily_store"
CUBE_BASIS = "raw_session_dollars"


# Carry unchanged calendar and membership alongside explicit raw execution prices.
@dataclass(frozen=True)
class RawExecutionInputs:
    dates: np.ndarray
    tickers: tuple[str, ...]
    grades: np.ndarray
    eligible: np.ndarray
    daily_open: np.ndarray
    daily_high: np.ndarray
    daily_low: np.ndarray
    daily_close: np.ndarray
    observation_close: np.ndarray
    next_open: np.ndarray
    session_open: np.ndarray
    cube_present: np.ndarray
    full_session: np.ndarray
    status: np.ndarray
    split_factors: np.ndarray
    actions: Mapping
    provenance: Mapping


# Reject an unsupported source relationship before deriving any execution dollars.
def _require(condition, message):
    if not condition:
        raise ValueError(message)


# Parse explicit archive dates without truncating timestamps or assigning timezones.
def _day(value):
    if isinstance(value, np.datetime64):
        _require(
            value.dtype == np.dtype("datetime64[D]") and not np.isnat(value),
            "Explicit day dates required",
        )
        return value
    _require(not isinstance(value, datetime), "Explicit day dates required")
    if isinstance(value, str):
        value = date.fromisoformat(value)
    _require(isinstance(value, date), "Explicit day dates required")
    return np.datetime64(value, "D")


# Require a declared completeness and adjustment date for every retained symbol.
def _dates_by_name(value, names, description):
    if not isinstance(value, Mapping):
        value = dict.fromkeys(names, value)
    _require(set(value) == set(names), f"Per-name {description} required")
    return {name: _day(value[name]) for name in names}


# Validate monetary source arrays while preserving each supplied missing cell.
def _prices(value, shape, description, *, allow_zero=False):
    array = np.asarray(value)
    _require(
        array.shape == shape and array.dtype.kind in "fiu",
        f"Aligned numeric {description} required",
    )
    known = np.isfinite(array)
    _require(
        not np.isinf(array).any()
        and np.all(array[known] >= 0 if allow_zero else array[known] > 0),
        f"Positive finite-or-missing {description} required",
    )
    return array.astype(np.float64, copy=True)


# Refuse inconsistent OHLC units rather than using their ratios to repair prices.
def _ohlc(values, description):
    opening, high, low, closing = values
    for left, right in (
        (low, high),
        (opening, high),
        (closing, high),
        (low, opening),
        (low, closing),
    ):
        known = np.isfinite(left) & np.isfinite(right)
        _require(np.all(left[known] <= right[known]), f"Invalid {description} OHLC")


# Deep-freeze explicit caller provenance without claiming its provider authenticity.
def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    _require(
        value is None or isinstance(value, (str, int, float, bool)),
        "Plain supplied provenance values required",
    )
    _require(
        not isinstance(value, float) or np.isfinite(value),
        "Finite provenance values required",
    )
    return value


# Validate sourced child entitlements and an allocation available at the action clock.
def _distribution(row, names, day):
    child = row.get("child")
    numerator, denominator = row.get("numerator"), row.get("denominator")
    _require(
        child in names
        and all(
            isinstance(value, (int, np.integer))
            and not isinstance(value, (bool, np.bool_))
            and value > 0
            for value in (numerator, denominator)
        ),
        "Covered child and explicit positive integer distribution ratio required",
    )
    fraction = row.get("parent_basis_fraction")
    _require(
        isinstance(fraction, (int, float, np.integer, np.floating))
        and not isinstance(fraction, (bool, np.bool_))
        and np.isfinite(fraction)
        and 0 < fraction < 1,
        "Explicit distribution basis allocation required",
    )
    available = row.get("basis_available_at")
    _require(isinstance(available, str), "Aware distribution basis clock required")
    available = datetime.fromisoformat(available)
    opening = datetime.combine(
        day.astype(object), calendar.REGULAR_OPEN, calendar.NEW_YORK
    )
    _require(
        available.utcoffset() is not None and available <= opening,
        "Distribution basis cannot use later evidence",
    )
    receipt = row.get("source_receipt")
    _require(
        isinstance(receipt, Mapping)
        and bool(receipt)
        and row.get("fractional_policy") == "cash_in_lieu_unknown",
        "Explicit source receipt and unknown fractional cash policy required",
    )
    _require(
        row.get("share_basis") == "post_split_action_date_shares",
        "Explicit distribution share basis required",
    )
    return {
        "date": str(day),
        "kind": "stock_distribution",
        "child": child,
        "numerator": int(numerator),
        "denominator": int(denominator),
        "parent_basis_fraction": float(fraction),
        "basis_available_at": available.isoformat(),
        "source_receipt": _freeze(receipt),
        "fractional_policy": "cash_in_lieu_unknown",
        "share_basis": "post_split_action_date_shares",
    }


# Refuse same-day chains whose entitlement order is not established by the source.
def _validate_distribution_dependencies(normalized):
    parents_by_day = {}
    for name, rows in normalized.items():
        for row in rows:
            if row["kind"] == "stock_distribution":
                parents_by_day.setdefault(row["date"], set()).add(name)
    _require(
        all(
            row["child"] not in parents_by_day[row["date"]]
            for rows in normalized.values()
            for row in rows
            if row["kind"] == "stock_distribution"
        ),
        "Same-day chained distributions require additional entitlement evidence",
    )


# Separate archive price factors from dated economic share and cash entitlements.
def _actions(actions, names, dates, basis, through, dividend_basis):
    _require(
        isinstance(actions, Mapping) and set(actions) == set(names),
        "Explicit action history required for every symbol",
    )
    factors = np.ones((len(dates), len(names)), dtype=np.float64)
    normalized = {}
    for stock, name in enumerate(names):
        previous, seen, rows = None, set(), []
        _require(
            isinstance(actions[name], (list, tuple)),
            "Explicit ordered action record sequence required",
        )
        _require(
            through[name] >= basis[name] and through[name] >= dates[-1],
            "Corporate-action completeness must cover archive basis and sessions",
        )
        _require(
            basis[name] >= dates[-1], "Archive basis cannot precede daily sessions"
        )
        for row in actions[name]:
            _require(
                isinstance(row, Mapping) and {"date", "kind"} <= set(row),
                "Dated split/dividend action records required",
            )
            day, kind = _day(row["date"]), row["kind"]
            _require(
                kind
                in ("split", "dividend", "archive_adjustment", "stock_distribution"),
                "Explicit split/dividend units required",
            )
            _require(
                previous is None or day >= previous,
                "Chronological action records required",
            )
            _require(day <= through[name], "Action beyond declared completeness")
            key = (str(day), kind)
            _require(key not in seen, "Duplicate or conflicting corporate action")
            seen.add(key)
            previous = day
            if kind == "stock_distribution":
                _require(
                    row.get("child") != name, "Distinct distribution child required"
                )
                rows.append(_distribution(row, names, day))
                continue
            value = row.get("value")
            _require(
                isinstance(value, (int, float, np.integer, np.floating))
                and not isinstance(value, (bool, np.bool_)),
                "Explicit split/dividend units required",
            )
            value = float(value)
            _require(
                np.isfinite(value) and value > 0,
                "Positive corporate-action value required",
            )
            rows.append({"date": str(day), "kind": kind, "value": value})
            if kind in ("split", "archive_adjustment") and day <= basis[name]:
                with np.errstate(over="ignore", under="ignore"):
                    factors[dates < day, stock] *= value
        rows.sort(key=lambda row: (row["date"], row["kind"] != "split"))
        for row in rows:
            if row["kind"] != "dividend":
                continue
            _require(
                dividend_basis
                in (
                    "raw_ex_date_share_dollars",
                    "split_adjusted_archive_share_dollars",
                ),
                "Explicit supported dividend amount basis required",
            )
            row["source_value"] = row["value"]
            if dividend_basis == "split_adjusted_archive_share_dollars":
                for split in rows:
                    if split["kind"] in ("split", "archive_adjustment") and row[
                        "date"
                    ] < split["date"] <= str(basis[name]):
                        row["value"] *= split["value"]
            _require(
                np.isfinite(row["value"]) and row["value"] > 0,
                "Finite raw dividend amount required",
            )
        normalized[name] = tuple(MappingProxyType(row) for row in rows)
    _validate_distribution_dependencies(normalized)
    _require(
        np.isfinite(factors).all() and (factors > 0).all(),
        "Finite positive dated split factors required",
    )
    return factors, MappingProxyType(normalized)


# Map supplied raw full-session cubes onto the unchanged panel without bar filling.
def _cubes(cubes, names, dates, full_session):
    _require(
        isinstance(cubes, Mapping) and set(cubes) <= set(names),
        "Cube keys must belong to original panel symbols",
    )
    shape = (len(dates), 25, len(names))
    observed, following = np.full(shape, np.nan), np.full(shape, np.nan)
    opening = np.full((len(dates), len(names)), np.nan)
    present = np.zeros(opening.shape, dtype=bool)
    statuses = np.full(opening.shape, "missing_cube_session", dtype="U32")
    statuses[~full_session] = "unsupported_early_close"
    sources = {}
    for stock, name in enumerate(names):
        cube = cubes.get(name)
        if cube is None:
            sources[name] = {"provided": False}
            continue
        cube_dates = np.asarray(cube.dates)
        _require(
            cube.ticker == name
            and cube_dates.ndim == 1
            and cube_dates.dtype == np.dtype("datetime64[D]")
            and not np.isnat(cube_dates).any()
            and np.all(cube_dates[1:] > cube_dates[:-1]),
            "Ordered unique cube dates and matching ticker required",
        )
        years, sessions = calendar.reviewed_sessions()
        _require(
            all(day.astype(object).year in years for day in cube_dates)
            and np.is_busday(cube_dates, busdaycal=sessions).all(),
            "Reviewed cube session dates required",
        )
        cube_shape = (len(cube_dates), 26)
        values = [
            _prices(getattr(cube, field), cube_shape, f"cube {field}")
            for field in ("open", "high", "low", "close")
        ]
        _ohlc(values, "raw cube")
        _prices(cube.volume, cube_shape, "cube volume", allow_zero=True)
        _prices(cube.prior_close, (len(cube_dates),), "cube prior close")
        _prices(cube.auction_open, (len(cube_dates),), "cube auction open")
        _prices(
            cube.auction_volume,
            (len(cube_dates),),
            "cube auction volume",
            allow_zero=True,
        )
        indices = np.searchsorted(dates, cube_dates)
        inside = indices < len(dates)
        inside[inside] &= dates[indices[inside]] == cube_dates[inside]
        selected = np.flatnonzero(inside)
        rows = indices[selected]
        present[rows, stock] = True
        supported = full_session[rows]
        cube_rows, rows = selected[supported], rows[supported]
        observed[rows, :, stock] = values[3][cube_rows, :25]
        following[rows, :, stock] = values[0][cube_rows, 1:26]
        opening[rows, stock] = values[0][cube_rows, 0]
        complete = np.logical_and.reduce(
            [np.isfinite(value[cube_rows]).all(axis=1) for value in values]
        )
        statuses[rows, stock] = np.where(
            complete, "provided_full_grid", "provided_missing_bars"
        )
        sources[name] = {
            "provided": True,
            "outside_panel_rows": int((~inside).sum()),
            "excluded": dict(cube.excluded),
            "arrays": {
                field: _hash(np.asarray(getattr(cube, field)))
                for field in (
                    "dates",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "prior_close",
                    "auction_open",
                    "auction_volume",
                )
            },
        }
    return observed, following, opening, present, statuses, sources


# Preserve source selection, missingness and actions in raw execution units.
def prepare(
    panel,
    grades,
    eligible,
    cubes,
    actions,
    *,
    basis_as_of,
    complete_through,
    provenance,
    daily_price_basis=DAILY_BASIS,
    cube_price_basis=CUBE_BASIS,
    dividend_price_basis=None,
):
    _require(
        daily_price_basis == DAILY_BASIS and cube_price_basis == CUBE_BASIS,
        "Declared split-adjusted daily and raw cube units required",
    )
    _require(
        isinstance(provenance, Mapping) and bool(provenance),
        "Explicit supplied source provenance required",
    )
    dates, names = np.asarray(panel.dates), tuple(panel.tickers)
    _require(
        dates.ndim == 1
        and len(dates)
        and dates.dtype == np.dtype("datetime64[D]")
        and not np.isnat(dates).any()
        and np.all(dates[1:] > dates[:-1])
        and len(names) == len(set(names))
        and bool(names)
        and all(isinstance(name, str) and name for name in names),
        "Ordered original sessions and unique symbols required",
    )
    years, sessions = calendar.reviewed_sessions()
    _require(
        all(day.astype(object).year in years for day in dates)
        and np.is_busday(dates, busdaycal=sessions).all(),
        "Reviewed exchange session dates required",
    )
    shape = (len(dates), len(names))
    grades, eligible = np.asarray(grades), np.asarray(eligible)
    _require(
        grades.shape == shape
        and grades.dtype.kind in "iu"
        and np.isin(grades, (-1, 0, 1, 2, 3)).all()
        and eligible.shape == shape
        and eligible.dtype.kind == "b",
        "Original aligned ordinal grades and boolean membership required",
    )
    daily = [
        _prices(getattr(panel, field), shape, f"daily {field}")
        for field in ("open", "high", "low", "close")
    ]
    _ohlc(daily, "daily source")
    basis = _dates_by_name(basis_as_of, names, "split-adjustment basis")
    through = _dates_by_name(complete_through, names, "action completeness")
    factors, action_rows = _actions(
        actions, names, dates, basis, through, dividend_price_basis
    )
    with np.errstate(over="ignore", under="ignore", invalid="ignore"):
        raw_daily = [value * factors for value in daily]
    _require(
        all(
            not np.isinf(value).any() and np.all(value[np.isfinite(value)] > 0)
            for value in raw_daily
        ),
        "Raw daily conversion overflow or underflow",
    )
    full = np.array(
        [
            calendar.session_close(day.astype(object)) == calendar.REGULAR_CLOSE
            for day in dates
        ],
        dtype=bool,
    )
    observed, following, opening, present, statuses, cube_sources = _cubes(
        cubes, names, dates, full
    )
    dates, grades, eligible = dates.copy(), grades.copy(), eligible.copy()
    contract = _freeze(
        {
            "daily_price_basis": DAILY_BASIS,
            "cube_price_basis": CUBE_BASIS,
            "raw_conversion": (
                "daily_OHLC_times_product_of_splits_strictly_after_session_"
                "through_archive_basis"
            ),
            "dividend_adjustment": "adj_close_not_used_for_raw_prices",
            "dividend_source_basis": dividend_price_basis,
            "dividend_output_basis": "raw_ex_date_share_dollars",
            "dividend_cash_conversion": (
                "explicit_split_adjusted_amount_times_dated_splits_strictly_after_"
                "ex_date_through_archive_basis;_original_source_value_retained"
            ),
            "action_completeness": (
                "caller_supplied_not_independent_provider_verification"
            ),
            "future_actions": (
                "archive_units_and_accounting_only_not_historical_decision_features"
            ),
            "early_close": (
                "retained_dates_unavailable_original_full_session_cube_contract"
            ),
            "cube_clock": "observation_close_slots_0_to_24_next_open_slots_1_to_25",
            "auction": "never_used_as_a_regular_next_open_or_synthetic_fill",
            "basis_as_of": {name: str(basis[name]) for name in names},
            "complete_through": {name: str(through[name]) for name in names},
            "supplied": provenance,
            "cube_sources": cube_sources,
            "daily_source_arrays": {
                field: _hash(np.asarray(getattr(panel, field)))
                for field in ("dates", "open", "high", "low", "close", "adj_close")
            },
            "grade_sha256": _hash(grades),
            "eligible_sha256": _hash(eligible),
        }
    )
    for array in (
        dates,
        grades,
        eligible,
        *raw_daily,
        observed,
        following,
        opening,
        present,
        full,
        statuses,
        factors,
    ):
        array.flags.writeable = False
    return RawExecutionInputs(
        dates,
        names,
        grades,
        eligible,
        *raw_daily,
        observed,
        following,
        opening,
        present,
        full,
        statuses,
        factors,
        action_rows,
        contract,
    )
