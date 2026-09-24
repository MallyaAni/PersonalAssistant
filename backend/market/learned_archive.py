"""Causal bridge from frozen desk observations to later, mature labels.

Decision features are read only from the file captured that night. A label
uses entry and exit adjusted opens from one fixed *later* bar vintage, after
the exit exists. That later vintage never supplies a decision feature.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

from backend.market import growth_pilot, language, learned_policy, opportunity_learning
from backend.market.store import MarketStore
from backend.market.yahoo import TickerHistory

NEW_YORK = ZoneInfo("America/New_York")
PRICE_COLUMNS = (*growth_pilot.FEATURE_NAMES, "range20_adjusted")
FUNDAMENTAL_COLUMNS = opportunity_learning.FUNDAMENTAL_NAMES
TONE_COLUMNS = language.FEATURE_NAMES
MARKET_COLUMNS = ("breadth", "return20", "vol20", "distance_ma60")
REGIME_COLUMNS = (
    "ai_drawdown",
    "ai_participation",
    "participation_percentile",
    "rotation_spread",
    "selection_confidence",
)
BRAKE_COLUMNS = (
    "breadth",
    "return20",
    "vol20",
    "distance_ma60",
    "ai_drawdown",
    "ai_participation",
    "participation_percentile",
)
FEATURE_COLUMNS = (
    *(f"price_{name}" for name in PRICE_COLUMNS),
    *(f"fundamental_{name}" for name in FUNDAMENTAL_COLUMNS),
    *TONE_COLUMNS,
    "desk_fundamental_rank",
    *(f"market_{name}" for name in MARKET_COLUMNS),
    *(f"regime_{name}" for name in REGIME_COLUMNS),
)


@dataclass(frozen=True)
class Label:
    """One outcome, or an explicit reason that it is not observable."""

    value: float | None
    recorded_on: date | None
    vintage: date | None
    reason: str


@dataclass(frozen=True)
class ArchiveData:
    """Model inputs, mature outcomes and observable coverage counts."""

    inputs: learned_policy.HistoricalInputs
    labels: np.ndarray
    labels_recorded_on: np.ndarray
    feature_names: tuple[str, ...]
    audit: dict[str, int]
    brake_features: np.ndarray
    brake_features_recorded_on: np.ndarray
    brake_labels: np.ndarray
    brake_labels_recorded_on: np.ndarray


@dataclass(frozen=True)
class ShadowFits:
    """Auditable forecasts; absent fits are missing rather than fabricated."""

    rank: learned_policy.Forecasts
    brake: learned_policy.Forecasts
    rank_scored: int
    brake_scored: int


# Derive the open on one adjusted basis from a single bar vintage.
def _adjusted_open(bar) -> float | None:
    values = (bar.open, bar.close, bar.adjusted_close)
    if any(value is None or not np.isfinite(value) or value <= 0 for value in values):
        return None
    return float(bar.open * bar.adjusted_close / bar.close)


# Require exactly one completed entry and exit bar in the selected vintage.
def _endpoints(history, entry: date, exit_session: date) -> tuple[float, float] | None:
    first = [bar for bar in history.bars if bar.session_date == entry]
    last = [bar for bar in history.bars if bar.session_date == exit_session]
    if len(first) != 1 or len(last) != 1:
        return None
    start, end = _adjusted_open(first[0]), _adjusted_open(last[0])
    return (start, end) if start is not None and end is not None else None


# Price a fixed next-open/eleventh-open label from the first mature vintage.
def realize_label(
    store: MarketStore,
    ticker: str,
    benchmark: str,
    calendar: tuple[date, ...],
    decision: int,
    data_as_of: datetime,
    *,
    _vintages: tuple[date, ...] | None = None,
    _histories: dict[tuple[str, date], TickerHistory | None] | None = None,
) -> Label:
    """Return a SPY-relative log outcome or a named missing-data reason."""
    if data_as_of.tzinfo is None:
        raise ValueError("data_as_of must be timezone-aware")
    end = decision + learned_policy.RANKER_LABEL_END
    if decision < 0 or end >= len(calendar):
        return Label(None, None, None, "immature")
    entry, exit_session = calendar[decision + 1], calendar[end]
    available = [
        day for day in (_vintages if _vintages is not None else store.asofs())
        if day >= exit_session
    ]
    if not available or available[0] > data_as_of.astimezone(NEW_YORK).date():
        return Label(None, None, None, "immature")
    vintage = available[0]
    cache = _histories if _histories is not None else {}

    # Read each ticker/vintage once across the whole evaluation cohort.
    def exact_history(name: str) -> TickerHistory | None:
        key = (name, vintage)
        if key not in cache:
            cache[key] = (
                store.read(name, vintage)
                if store.latest_asof(name, vintage) == vintage
                else None
            )
        return cache[key]

    stock, market = exact_history(ticker), exact_history(benchmark)
    if stock is None or market is None:
        return Label(None, None, vintage, "missing_same_vintage")
    sources = (stock, market)
    if any(
        item.complete_through < exit_session
        or item.source_time.tzinfo is None
        or item.source_time > data_as_of
        for item in sources
    ):
        return Label(None, None, vintage, "unavailable_source")
    stock_opens = _endpoints(stock, entry, exit_session)
    market_opens = _endpoints(market, entry, exit_session)
    if stock_opens is None or market_opens is None:
        return Label(None, None, vintage, "missing_endpoint")
    value = np.log(stock_opens[1] / stock_opens[0]) - np.log(
        market_opens[1] / market_opens[0]
    )
    published = max(
        vintage,
        *(item.source_time.astimezone(NEW_YORK).date() for item in sources),
    )
    return Label(float(value), published, vintage, "mature")


# Reject an incomplete or ambiguous QQQ close within the fixed outcome span.
def _qqq_window(history, days: tuple[date, ...]) -> np.ndarray | None:
    by_day = {}
    for bar in history.bars:
        by_day.setdefault(bar.session_date, []).append(bar)
    closes = []
    for day in days:
        bars = by_day.get(day, ())
        if len(bars) != 1 or bars[0].adjusted_close is None:
            return None
        close = float(bars[0].adjusted_close)
        if not np.isfinite(close) or close <= 0:
            return None
        closes.append(close)
    return np.asarray(closes)


# Observe a QQQ crash only after the entire twenty-session window is stored.
def realize_brake_label(
    store: MarketStore,
    calendar: tuple[date, ...],
    decision: int,
    data_as_of: datetime,
    *,
    _vintages: tuple[date, ...] | None = None,
    _histories: dict[tuple[str, date], TickerHistory | None] | None = None,
) -> Label:
    """Return the fixed 20-session QQQ drawdown outcome or missing reason."""
    if data_as_of.tzinfo is None:
        raise ValueError("data_as_of must be timezone-aware")
    end = decision + learned_policy.BRAKE_HORIZON
    if decision < 0 or end >= len(calendar):
        return Label(None, None, None, "immature")
    available = [
        day for day in (_vintages if _vintages is not None else store.asofs())
        if day >= calendar[end]
    ]
    if not available or available[0] > data_as_of.astimezone(NEW_YORK).date():
        return Label(None, None, None, "immature")
    vintage = available[0]
    cache = _histories if _histories is not None else {}
    key = ("QQQ", vintage)
    if key not in cache:
        cache[key] = (
            store.read("QQQ", vintage)
            if store.latest_asof("QQQ", vintage) == vintage
            else None
        )
    history = cache[key]
    if history is None:
        return Label(None, None, vintage, "missing_same_vintage")
    if (
        history.complete_through < calendar[end]
        or history.source_time.tzinfo is None
        or history.source_time > data_as_of
    ):
        return Label(None, None, vintage, "unavailable_source")
    values = _qqq_window(history, calendar[decision : end + 1])
    if values is None:
        return Label(None, None, vintage, "missing_endpoint")
    peaks = np.maximum.accumulate(values)
    label = float(np.min(values / peaks - 1) < -0.08)
    published = max(vintage, history.source_time.astimezone(NEW_YORK).date())
    return Label(label, published, vintage, "mature")


# Convert a nullable captured feature into a finite model value or NaN.
def _number(value) -> float:
    if value is None:
        return float("nan")
    result = float(value)
    return result if np.isfinite(result) else float("nan")


# Keep the feature order fixed across names, sessions and model refits.
def _features(snapshot: dict, stock: dict) -> np.ndarray:
    price = stock.get("price_features") or {}
    fundamental = stock.get("fundamental_features") or {}
    tone = stock.get("tone_features") or {}
    market = snapshot.get("market_features") or {}
    regime = snapshot.get("regime") or {}
    values = (
        *(_number(price.get(name)) for name in PRICE_COLUMNS),
        *(_number(fundamental.get(name)) for name in FUNDAMENTAL_COLUMNS),
        *(_number(tone.get(name)) for name in TONE_COLUMNS),
        _number(stock.get("desk_fundamental_rank")),
        *(_number(market.get(name)) for name in MARKET_COLUMNS),
        *(_number(regime.get(name)) for name in REGIME_COLUMNS),
    )
    return np.asarray(values, dtype=float)


# Keep market-wide brake features separate from individual stock evidence.
def _brake_features(snapshot: dict) -> np.ndarray:
    market = snapshot.get("market_features") or {}
    regime = snapshot.get("regime") or {}
    values = (
        *(_number(market.get(name)) for name in BRAKE_COLUMNS[:4]),
        *(_number(regime.get(name)) for name in BRAKE_COLUMNS[4:]),
    )
    return np.asarray(values, dtype=float)


# Verify that the supplied calendar has not omitted exchange sessions.
def _calendar(store: MarketStore, days: tuple[date, ...], as_of: datetime) -> None:
    if as_of.tzinfo is None or len(days) < 2 or any(
        left >= right for left, right in zip(days, days[1:], strict=False)
    ):
        raise ValueError("an aware as-of and ordered exchange calendar are required")
    market = store.read("SPY", as_of.astimezone(NEW_YORK).date())
    if (
        market is None
        or market.complete_through < days[-1]
        or market.source_time.tzinfo is None
        or market.source_time > as_of
    ):
        raise ValueError("a complete SPY calendar is required")
    observed = tuple(
        bar.session_date
        for bar in market.bars
        if days[0] <= bar.session_date <= days[-1]
    )
    if observed != days:
        raise ValueError("supplied calendar omits or invents SPY sessions")


# Read only same-session captures and reject contradictory saved evidence.
def _snapshots(root: Path, calendar: tuple[date, ...], data_as_of: datetime):
    snapshots: dict[date, dict] = {}
    audit = {
        "captured": 0,
        "late_capture": 0,
        "mature": 0,
        "immature": 0,
        "missing": 0,
        "brake_mature": 0,
        "brake_immature": 0,
        "brake_missing": 0,
    }
    for day in calendar:
        path = Path(root) / "learned_inputs" / f"asof={day.isoformat()}.json"
        if not path.exists():
            continue
        row = json.loads(path.read_text(encoding="utf-8"))
        captured = datetime.fromisoformat(row["captured_at"])
        if captured.tzinfo is None or row.get("session") != day.isoformat():
            raise ValueError(f"invalid archive observation: {path}")
        if captured > data_as_of:
            continue
        if captured.astimezone(NEW_YORK).date() != day:
            audit["late_capture"] += 1
            continue
        if (
            row.get("schema") != "desk-learned-inputs/1"
            or row.get("benchmark") != "SPY"
        ):
            raise ValueError(f"unknown archive schema or benchmark: {path}")
        source = Path(root) / "desk" / f"asof={day.isoformat()}" / "desk.json"
        if source.exists() and sha256(source.read_bytes()).hexdigest() != row.get(
            "record_sha256"
        ):
            raise ValueError(f"saved desk record differs from archive: {day}")
        snapshots[day] = row
        audit["captured"] += 1
    return snapshots, audit


# Assemble only observations genuinely captured on their decision session.
def load(
    root: Path,
    store: MarketStore,
    calendar: tuple[date, ...],
    data_as_of: datetime,
) -> ArchiveData:
    """Build aligned shadow inputs and outcome availability without fitting."""
    _calendar(store, calendar, data_as_of)
    snapshots, audit = _snapshots(root, calendar, data_as_of)
    names = tuple(
        sorted({name for row in snapshots.values() for name in row["stocks"]} | {"SPY"})
    )
    shape = (len(calendar), len(names))
    features = np.full((*shape, len(FEATURE_COLUMNS)), np.nan)
    published = np.full(features.shape, np.datetime64("NaT", "D"))
    members = np.full(shape, -1, dtype=int)
    member_when = np.full(shape, np.datetime64("NaT", "D"))
    labels = np.full(shape, np.nan)
    label_when = np.full(shape, np.datetime64("NaT", "D"))
    brake_x = np.full((len(calendar), len(BRAKE_COLUMNS)), np.nan)
    brake_x_when = np.full(brake_x.shape, np.datetime64("NaT", "D"))
    brake_y = np.full(len(calendar), np.nan)
    brake_y_when = np.full(len(calendar), np.datetime64("NaT", "D"))
    vintages = tuple(store.asofs())
    histories: dict[tuple[str, date], TickerHistory | None] = {}
    for t, day in enumerate(calendar):
        row = snapshots.get(day)
        if row is None:
            continue
        brake_x[t] = _brake_features(row)
        brake_x_when[t, np.isfinite(brake_x[t])] = np.datetime64(day)
        brake_outcome = realize_brake_label(
            store,
            calendar,
            t,
            data_as_of,
            _vintages=vintages,
            _histories=histories,
        )
        if brake_outcome.value is None:
            key = (
                "brake_immature"
                if brake_outcome.reason == "immature"
                else "brake_missing"
            )
            audit[key] += 1
        else:
            brake_y[t] = brake_outcome.value
            brake_y_when[t] = np.datetime64(brake_outcome.recorded_on)
            audit["brake_mature"] += 1
        for j, ticker in enumerate(names):
            stock = row["stocks"].get(ticker)
            if stock is None or ticker == "SPY":
                continue
            if not stock.get("current_bar_complete") or not stock.get("desk_grade"):
                continue
            members[t, j] = 1
            member_when[t, j] = np.datetime64(day)
            features[t, j] = _features(row, stock)
            published[t, j, np.isfinite(features[t, j])] = np.datetime64(day)
            outcome = realize_label(
                store,
                ticker,
                "SPY",
                calendar,
                t,
                data_as_of,
                _vintages=vintages,
                _histories=histories,
            )
            if outcome.value is None:
                audit["immature" if outcome.reason == "immature" else "missing"] += 1
                continue
            labels[t, j] = outcome.value
            label_when[t, j] = np.datetime64(outcome.recorded_on)
            audit["mature"] += 1
    dates = np.asarray(calendar, dtype="datetime64[D]")
    inputs = learned_policy.HistoricalInputs(
        dates,
        names,
        np.full(shape, np.nan),
        np.full(shape, np.datetime64("NaT", "D")),
        features,
        published,
        members,
        member_when,
    )
    learned_policy.validate(inputs)
    return ArchiveData(
        inputs,
        labels,
        label_when,
        FEATURE_COLUMNS,
        audit,
        brake_x,
        brake_x_when,
        brake_y,
        brake_y_when,
    )


# Run only the registered walk-forward fits over immutable archived inputs.
def fit_shadow(data: ArchiveData) -> ShadowFits:
    """Return rank and brake forecasts, or all-missing before enough history."""
    rank = learned_policy.walk_forward_ranker(
        data.inputs,
        observed_labels=data.labels,
        labels_recorded_on=data.labels_recorded_on,
    )
    empty = np.full(len(data.inputs.dates), np.nan)
    unpublished = np.full(len(empty), np.datetime64("NaT", "D"))
    brake = learned_policy.walk_forward_brake(
        data.brake_features,
        data.brake_features_recorded_on,
        data.inputs.dates,
        empty,
        unpublished,
        observed_labels=data.brake_labels,
        labels_recorded_on=data.brake_labels_recorded_on,
    )
    return ShadowFits(
        rank,
        brake,
        int(np.isfinite(rank.values).sum()),
        int(np.isfinite(brake.values).sum()),
    )
