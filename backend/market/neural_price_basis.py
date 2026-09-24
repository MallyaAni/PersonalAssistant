"""Separate research features with explicitly reconciled price/share units.

This module never changes frozen neural inputs or its prospective journal.
Corporate actions change units, not information availability: each share fact
keeps its original filing/acceptance dates while its value is expressed on the
declared price snapshot's split basis. Historical share counts filed after an
intervening split have ambiguous units and remain missing. Currency, ADR ratios
and the source fact unit still need independent verification; unknown units mask
all fundamentals.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from functools import lru_cache

import numpy as np

from backend.market import calendar
from backend.market import fundamentals_asof as fa
from backend.market import growth_pilot as gp
from backend.market import opportunity_learning as ol
from backend.market.panel import Panel
from backend.market.yahoo import TickerHistory

VERSION = "neural-price-basis/1"


# Bound same-session filing availability to years with reviewed close schedules.
@lru_cache(maxsize=1)
def _close_years():
    current = json.loads(calendar.EARLY_CLOSES_PATH.read_text())
    historical = json.loads(calendar.HISTORICAL_SESSIONS_PATH.read_text())
    return {int(year) for year in current["years"]} | {
        int(year) for year in historical["years"]
    }


class _PublicationVersion(fa.Version):
    """Keep source timestamps while applying the reviewed session-close boundary."""

    __slots__ = ()

    # Treat acceptance at/after early close as next-day; unknown schedules delay safely.
    @property
    def available(self):
        if self.accepted is None:
            return self.filed + timedelta(days=1)
        local = self.accepted.astimezone(fa.NEW_YORK)
        same_day = (
            local.year in _close_years()
            and local.time() < calendar.session_close(local.date())
        )
        return local.date() if same_day else local.date() + timedelta(days=1)


# Copy original filing fields into the isolated availability adapter without mutation.
def _publication_version(version):
    return _PublicationVersion(
        version.name,
        version.tag,
        version.start,
        version.end,
        version.value,
        version.filed,
        version.accepted,
        version.accession,
        version.form,
    )


@dataclass(frozen=True)
class PriceBasis:
    """Caller-attested source coverage and fundamental-unit compatibility.

    Coverage must describe the entire source history, not just the evaluation
    window. An empty action list is evidence of no splits only when its
    completeness is explicitly attested. This record does not verify ADR or
    currency units by itself; the caller must retain that supporting evidence.
    """

    source: str
    source_time: datetime
    action_coverage_start: date
    action_coverage_end: date
    actions_complete: bool
    fundamental_units_verified: bool = False
    price_basis: str = "split_normalized_close"


# Reject ambiguous instants before Python can infer the machine's local timezone.
def _aware(value: datetime, label: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone aware")


# Verify the supplied provenance describes this exact source and action interval.
def _validate_identity(symbol, history, basis):
    _aware(history.source_time, "history source_time")
    _aware(basis.source_time, "basis source_time")
    if history.ticker != symbol or history.source != basis.source:
        raise ValueError(f"{symbol}: price source/symbol mismatch")
    if history.source_time != basis.source_time:
        raise ValueError(f"{symbol}: price vintage mismatch")
    if basis.price_basis != "split_normalized_close":
        raise ValueError(f"{symbol}: unsupported price basis")
    if not history.bars:
        raise ValueError(f"{symbol}: empty source price history")
    source_days = [bar.session_date for bar in history.bars]
    if len(set(source_days)) != len(source_days):
        raise ValueError(f"{symbol}: duplicate source price date")
    vintage = history.source_time.astimezone(fa.NEW_YORK).date()
    if max(source_days) > vintage or history.complete_through > vintage:
        raise ValueError(f"{symbol}: future source price date")
    if max(source_days) > history.complete_through:
        raise ValueError(f"{symbol}: source includes an incomplete price session")
    if basis.action_coverage_start != min(source_days):
        raise ValueError(f"{symbol}: action coverage must start at first source bar")
    if basis.action_coverage_end != vintage:
        raise ValueError(f"{symbol}: action coverage must end at price vintage")


# Match every consumed price/volume input to source bytes without ratio calibration.
def _validate_panel_inputs(panel, column, history):
    symbol = panel.tickers[column]
    vintage = history.source_time.astimezone(fa.NEW_YORK).date()
    if len(panel.dates) and panel.dates[-1].astype(object) > vintage:
        raise ValueError(f"{symbol}: panel extends beyond price vintage")
    for panel_name, source_name in (
        ("close", "close"),
        ("adj_close", "adjusted_close"),
        ("volume", "volume"),
    ):
        source = {
            bar.session_date: (
                np.nan
                if getattr(bar, source_name) is None
                else float(getattr(bar, source_name))
            )
            for bar in history.bars
        }
        expected = np.asarray(
            [source.get(day, np.nan) for day in panel.dates.astype(object)]
        )
        if not np.array_equal(
            expected, getattr(panel, panel_name)[:, column], equal_nan=True
        ):
            raise ValueError(
                f"{symbol}: panel {panel_name} differs from supplied source history"
            )
        invalid = expected < 0 if panel_name == "volume" else expected <= 0
        if np.isinf(expected).any() or np.any(np.isfinite(expected) & invalid):
            raise ValueError(f"{symbol}: invalid source {source_name}")


# Canonicalize splits only inside the explicitly attested source interval.
def _splits_for(panel, column, history, basis):
    symbol = panel.tickers[column]
    _validate_identity(symbol, history, basis)
    _validate_panel_inputs(panel, column, history)
    vintage = basis.action_coverage_end
    splits = {}
    duplicates = future = 0
    for action in history.actions:
        if action.kind != "split":
            continue
        if action.action_date > vintage:
            future += 1
            continue
        if action.action_date < basis.action_coverage_start:
            raise ValueError(f"{symbol}: split outside declared action coverage")
        ratio = float(action.value)
        if not np.isfinite(ratio) or ratio <= 0:
            raise ValueError(f"{symbol}: split ratio must be finite and positive")
        if action.action_date in splits:
            if splits[action.action_date] != ratio:
                raise ValueError(f"{symbol}: conflicting split actions")
            duplicates += 1
        splits[action.action_date] = ratio
    return sorted(splits.items()), {
        "duplicate_splits_deduplicated": duplicates,
        "future_splits_excluded": future,
    }


# Align a dated share fact to the snapshot without moving its publication boundary.
def _aligned_versions(versions, splits, basis):
    aligned = []
    unavailable = ambiguous = 0
    for version in versions:
        if version.accepted is not None:
            _aware(version.accepted, "filing acceptance")
        version = _publication_version(version)
        if version.name != "shares":
            aligned.append(version)
            continue
        if version.start is not None:
            raise ValueError("Share facts must describe an instant, not a duration")
        value = float(version.value)
        # A later filing may restate the old period in post-split units. Its
        # period end does not establish those units, so do not multiply it
        # or infer a basis from the numeric value. Same-day filings are also
        # ambiguous because the action record has no effective intraday time.
        publication = max(
            version.filed,
            version.accepted.astimezone(fa.NEW_YORK).date()
            if version.accepted is not None
            else version.filed,
        )
        uncertain_basis = any(
            version.end < day <= publication for day, _ in splits
        )
        if (
            version.end < basis.action_coverage_start
            or version.end > basis.action_coverage_end
            or not np.isfinite(value)
            or value <= 0
        ):
            value = np.nan
            unavailable += 1
        elif uncertain_basis:
            value = np.nan
            unavailable += 1
            ambiguous += 1
        else:
            for day, ratio in splits:
                if version.end < day <= basis.action_coverage_end:
                    value *= ratio
            if not np.isfinite(value) or value <= 0:
                value = np.nan
                unavailable += 1
        aligned.append(replace(version, value=value))
    return aligned, unavailable, ambiguous


# Build the neural schema on supplied, verified units while retaining missing evidence.
def features(
    panel: Panel,
    versions_by_ticker: Mapping[str, Sequence[fa.Version]],
    histories_by_ticker: Mapping[str, TickerHistory],
    *,
    basis_by_ticker: Mapping[str, PriceBasis],
    audit: dict | None = None,
):
    """Return (dataset, 18 raw features, names), with optional per-ticker receipts.

    Missing coverage or unverified fundamental units remain NaN; malformed or
    contradictory supplied provenance raises. The caller can keep price-only
    eligibility, but must not describe imputed fundamentals as verified facts.
    """
    dates = np.asarray(panel.dates)
    if dates.ndim != 1 or dates.dtype != np.dtype("datetime64[D]"):
        raise ValueError("Daily panel dates are required")
    if np.isnat(dates).any() or np.any(dates[1:] <= dates[:-1]):
        raise ValueError("Sorted unique panel dates are required")
    data = gp.dataset(panel)
    levels = {name: np.full(panel.close.shape, np.nan) for name in fa.LEVEL_NAMES}
    for column, symbol in enumerate(panel.tickers):
        basis = basis_by_ticker.get(symbol)
        history = histories_by_ticker.get(symbol)
        versions = versions_by_ticker.get(symbol, ())
        detail = {"status": "unavailable", "reason": "missing price-basis evidence"}
        if basis is not None and history is not None:
            splits, counts = _splits_for(panel, column, history, basis)
            detail.update(counts)
            detail.update(
                source=basis.source,
                source_time=basis.source_time.isoformat(),
                action_coverage_start=basis.action_coverage_start.isoformat(),
                action_coverage_end=basis.action_coverage_end.isoformat(),
            )
            if basis.actions_complete is not True:
                detail["reason"] = "corporate-action coverage unverified"
            elif basis.fundamental_units_verified is not True:
                detail["reason"] = "fundamental currency/share/ADR units unverified"
            elif not versions:
                detail["reason"] = "no dated fundamental versions"
            else:
                adjusted, missing, ambiguous = _aligned_versions(
                    versions, splits, basis
                )
                found = fa.levels_for(adjusted, panel.dates)
                for name, series in found.items():
                    levels[name][:, column] = series
                detail.update(
                    status="aligned",
                    reason=None,
                    availability="reviewed-exchange-close-or-next-day",
                    share_versions_unavailable=missing,
                    share_versions_ambiguous_basis=ambiguous,
                    share_sessions_available=int(np.isfinite(found["shares"]).sum()),
                )
        if audit is not None:
            audit[symbol] = detail
    fundamentals = ol.ratios(panel.close, levels)
    values = np.concatenate((data.features, fundamentals), axis=-1)
    return data, values, (*gp.FEATURE_NAMES, *ol.FUNDAMENTAL_NAMES)
