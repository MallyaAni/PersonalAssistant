"""Frozen price-only gate inputs; no historical availability or quality claim.

The dated stock basket still comes from the unchanged reconstructed desk report.
Only the new gate's features are price-only. See the frozen study protocol for
the distinction between these gross proxy labels and funded account returns.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import risk, simulate
from backend.market.allocation_controls import adjusted_open
from backend.market.nested_allocation import STOCK_CADENCE
from backend.market.nested_ridge import RegressionInputs
from backend.market.panel import Panel

WARMUP_ROWS = 200
LABEL_EXIT_OFFSET = 6
FEATURE_NAMES = tuple(
    name
    for symbol in ("SPY", "QQQ")
    for name in (
        *(f"{symbol}_log_return_{h}" for h in (1, 5, 20, 63, 126)),
        f"{symbol}_log_volatility_20",
        f"{symbol}_log_close_sma_200",
        f"{symbol}_log_drawdown_63",
    )
) + (
    *(f"stock_log_return_{h}" for h in (1, 5, 20, 63)),
    "stock_log_volatility_20",
    "stock_invested_fraction",
)
PRICE_FIELDS = ("open", "high", "low", "close", "adj_close", "volume")
ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class StudyInputs:
    """Original report plus independent execution, learning and audit evidence."""

    report: object
    panel: Panel
    regression: RegressionInputs
    stock_weights: np.ndarray
    equal_weights: np.ndarray
    raw_labels: np.ndarray
    label_end_on: np.ndarray
    audit: dict


# Copy derived evidence onto immutable bytes so callers cannot rewrite a fit input.
def _owned(values):
    return np.frombuffer(values.tobytes(order="C"), dtype=values.dtype).reshape(
        values.shape
    )


# Validate complete panel shapes without making missing individual histories disappear.
def _panel(value):
    dates = np.asarray(value.dates)
    if (
        dates.dtype != np.dtype("datetime64[D]")
        or dates.ndim != 1
        or not len(dates)
        or np.isnat(dates).any()
        or np.any(dates[1:] <= dates[:-1])
    ):
        raise ValueError("panel needs unique increasing daily dates")
    symbols = value.tickers
    if (
        not isinstance(symbols, tuple)
        or not symbols
        or any(not isinstance(s, str) or not s or s.strip() != s for s in symbols)
        or len(set(symbols)) != len(symbols)
    ):
        raise ValueError("panel needs an ordered unique ticker tuple")
    arrays = {}
    for name in PRICE_FIELDS:
        values = np.asarray(getattr(value, name))
        if values.shape != (len(dates), len(symbols)) or values.dtype.kind not in "iuf":
            raise ValueError(f"{name} must be a real session by ticker matrix")
        with np.errstate(over="ignore", invalid="ignore"):
            values = values.astype(float)
        if np.isinf(values).any():
            raise ValueError(f"{name} contains infinity or overflow")
        known = np.isfinite(values)
        bad = values < 0 if name == "volume" else values <= 0
        if np.any(known & bad):
            raise ValueError(f"{name} contains invalid observed values")
        arrays[name] = _owned(values)
    return replace(value, dates=_owned(dates), **arrays)


# Refuse execution panels that alter the incumbent's symbols, calendar or observations.
def _aligned(report, panel):
    original = _panel(report.panel)
    execution = _panel(panel)
    if original.benchmark != "SPY" or execution.benchmark != "SPY":
        raise ValueError("both panel benchmarks must be SPY")
    if "SPY" not in original.tickers or "QQQ" in original.tickers:
        raise ValueError("original report must contain SPY but not QQQ")
    if set(execution.tickers) != set(original.tickers) | {"QQQ"}:
        raise ValueError("execution panel must add only QQQ to the original symbols")
    if not np.array_equal(original.dates, execution.dates):
        raise ValueError("execution and original report dates differ")
    columns = [execution.index(symbol) for symbol in original.tickers]
    for name in PRICE_FIELDS:
        if not np.array_equal(
            getattr(original, name),
            getattr(execution, name)[:, columns],
            equal_nan=True,
        ):
            raise ValueError(f"execution panel differs from original {name}")
    _report_shapes(report, original)
    return execution, columns


# Check dated decision arrays before any call to the unchanged sizing engine.
def _report_shapes(report, original):
    shape = (len(original.dates), len(original.tickers))
    for name, values in (("scores", report.scores), ("grades", report.graded.grades)):
        values = np.asarray(values)
        if values.shape != shape or values.dtype.kind not in "iuf":
            raise ValueError(f"report {name} does not align with its original panel")
        if np.isinf(values).any():
            raise ValueError(f"report {name} contains infinity")
    if len(report.regime.states) != shape[0]:
        raise ValueError("report regime states do not align with its original panel")


# Build decision-time stock and equal-weight compositions on one source-global clock.
def _compositions(report, panel, columns):
    shape = panel.adj_close.shape
    stocks = np.zeros(shape)
    equal = np.zeros(shape)
    non_index = np.array([s not in ("SPY", "QQQ") for s in panel.tickers])
    for t in range(shape[0]):
        if t % STOCK_CADENCE:
            stocks[t] = stocks[t - 1]
            equal[t] = equal[t - 1]
            continue
        weights = np.asarray(
            simulate._targets(report, report.panel, risk.BOOK_CONFIG, t)
        )
        if (
            weights.shape != (len(columns),)
            or weights.dtype.kind not in "iuf"
            or not np.isfinite(weights).all()
            or np.any(weights < 0)
            or weights.sum() > 1 + 1e-12
        ):
            raise ValueError(
                "desk targets must be finite nonnegative cash-bounded weights"
            )
        stocks[t, columns] = weights
        if np.any(stocks[t, ~non_index] != 0):
            raise ValueError("stock composition must not contain SPY or QQQ")
        eligible = (
            non_index & np.isfinite(panel.adj_close[t]) & (panel.adj_close[t] > 0)
        )
        if eligible.any():
            equal[t, eligible] = 1.0 / int(eligible.sum())
    return stocks, equal


# Calculate one cash-preserving endpoint proxy without discarding missing held names.
def _basket_return(prices, weights, start, stop):
    used = weights > 0
    if not used.any():
        return 0.0
    endpoints = prices[[start, stop]][:, used]
    if not np.isfinite(endpoints).all():
        return np.nan
    with np.errstate(all="raise"):
        try:
            cash = max(0.0, 1.0 - float(weights.sum()))
            wealth = cash + float(np.sum(weights[used] * endpoints[1] / endpoints[0]))
            result = float(np.log(wealth))
        except FloatingPointError as exc:
            raise ValueError("basket proxy arithmetic is not finite") from exc
    if not np.isfinite(result):
        raise ValueError("basket proxy arithmetic is not finite")
    return result


# Derive the eight declared index features using only complete trailing windows.
def _index_features(prices, t):
    result = np.full(8, np.nan)
    for column, horizon in enumerate((1, 5, 20, 63, 126)):
        if t >= horizon and np.isfinite(prices[[t - horizon, t]]).all():
            result[column] = np.log(prices[t]) - np.log(prices[t - horizon])
    if t >= 20:
        window = prices[t - 20 : t + 1]
        if np.isfinite(window).all():
            result[5] = np.std(np.diff(np.log(window)), ddof=0)
    if t >= 199:
        window = prices[t - 199 : t + 1]
        if np.isfinite(window).all():
            # Scaling before averaging avoids an intermediate overflow in the sum.
            result[6] = np.log(prices[t]) - np.log(np.sum(window / 200))
    if t >= 62:
        window = prices[t - 62 : t + 1]
        if np.isfinite(window).all():
            result[7] = np.log(prices[t]) - np.log(np.max(window))
    return result


# Describe the current basket's history rather than inventing its past trading returns.
def _features(panel, weights):
    features = np.full((len(panel.dates), len(FEATURE_NAMES)), np.nan)
    for t in range(len(panel.dates)):
        for block, symbol in enumerate(("SPY", "QQQ")):
            features[t, block * 8 : (block + 1) * 8] = _index_features(
                panel.adj_close[:, panel.index(symbol)], t
            )
        for column, horizon in enumerate((1, 5, 20, 63), start=16):
            if t >= horizon:
                features[t, column] = _basket_return(
                    panel.adj_close, weights[t], t - horizon, t
                )
        if t >= 20:
            daily = np.array(
                [
                    _basket_return(panel.adj_close, weights[t], day - 1, day)
                    for day in range(t - 19, t + 1)
                ]
            )
            if np.isfinite(daily).all():
                features[t, 20] = np.std(daily, ddof=0)
        features[t, 21] = weights[t].sum()
    if np.isinf(features).any():
        raise ValueError("derived features must not contain infinity")
    return features


# Keep gross open-to-open outcomes and actual endpoints separate from training masks.
def _labels(panel, weights):
    rows = len(panel.dates)
    labels = np.full((rows, 3), np.nan)
    ends = np.full((rows, 3), np.datetime64("NaT", "D"))
    opens = adjusted_open(panel.open, panel.close, panel.adj_close)
    if np.isinf(opens).any() or np.any(np.isfinite(opens) & (opens <= 0)):
        raise ValueError("adjusted open derivation overflowed or became nonpositive")
    for t in range(rows - LABEL_EXIT_OFFSET):
        entry, exit_row = t + 1, t + LABEL_EXIT_OFFSET
        ends[t] = panel.dates[exit_row]
        labels[t, 0] = _basket_return(opens, weights[t], entry, exit_row)
        for column, symbol in enumerate(("SPY", "QQQ"), start=1):
            values = opens[[entry, exit_row], panel.index(symbol)]
            if np.isfinite(values).all():
                labels[t, column] = np.log(values[1]) - np.log(values[0])
    return labels, ends


# Validate an explicit cash-bounded stock basket before using its economic meaning.
def _weights(panel, weights):
    values = np.asarray(weights)
    if values.shape != panel.adj_close.shape or values.dtype.kind not in "iuf":
        raise ValueError("stock weights must be real values aligned with the panel")
    with np.errstate(over="ignore", invalid="ignore"):
        values = values.astype(float)
    if (
        not np.isfinite(values).all()
        or np.any(values < 0)
        or np.any(values.sum(axis=1) > 1 + 1e-12)
    ):
        raise ValueError("stock weights must be finite nonnegative cash-bounded values")
    if "SPY" not in panel.tickers or "QQQ" not in panel.tickers:
        raise ValueError("execution panel requires SPY and QQQ")
    if np.any(values[:, [panel.index("SPY"), panel.index("QQQ")]] != 0):
        raise ValueError("stock weights must exclude SPY and QQQ")
    return _owned(values)


# Expose the unchanged desk's symbol-mapped compositions for independent inspection.
def stock_compositions(report, panel):
    execution, columns = _aligned(report, panel)
    stocks, _equal = _compositions(report, execution, columns)
    return _owned(stocks)


# Return the complete ordered feature matrix for a validated current-basket path.
def price_features(panel, weights):
    execution = _panel(panel)
    values = _weights(execution, weights)
    return _owned(_features(execution, values)), FEATURE_NAMES


# Return unmasked gross proxy labels with their actual endpoint and availability dates.
def forward_labels(panel, weights):
    execution = _panel(panel)
    values = _weights(execution, weights)
    labels, ends = _labels(execution, values)
    return _owned(labels), _owned(ends), _owned(ends)


# Bind every report field consumed by sizing and /3 to the actual assembly source.
def binding(report):
    arrays = {
        "scores": report.scores,
        "grades": report.graded.grades,
        "dates": report.panel.dates,
        **{name: getattr(report.panel, name) for name in PRICE_FIELDS},
    }
    description = {
        "arrays": {},
        "tickers": list(report.panel.tickers),
        "benchmark": report.panel.benchmark,
        "themes": {key: list(value) for key, value in report.panel.themes.items()},
        "sides": dict(report.sides),
        "regime_states": [
            {"exposure": float(state.exposure), "tightening": bool(state.tightening)}
            for state in report.regime.states
        ],
    }
    for name, values in arrays.items():
        array = np.asarray(values)
        if array.dtype.hasobject:
            raise ValueError("report binding cannot contain object arrays")
        description["arrays"][name] = {
            "shape": list(array.shape),
            "dtype": array.dtype.str,
            "sha256": hashlib.sha256(array.tobytes(order="C")).hexdigest(),
        }
    encoded = json.dumps(description, sort_keys=True, allow_nan=False).encode()
    sources = {}
    for directory in ("backend/market", "backend/agents/trading/desk"):
        for path in sorted((ROOT / directory).rglob("*.py")):
            sources[str(path.relative_to(ROOT))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return {
        "schema": "nested-market-assembly-binding/1",
        "report_consumed_state_sha256": hashlib.sha256(encoded).hexdigest(),
        "assembly_source_hashes": sources,
        "book_config": asdict(risk.BOOK_CONFIG),
        "scope": (
            "prices, scores, grades, regime exposure/tightening, sides, "
            "themes and Python source"
        ),
    }


# Assemble auditable proxy learning evidence without fitting or running any account.
def assemble(report, panel: Panel) -> StudyInputs:
    execution, columns = _aligned(report, panel)
    before = binding(report)
    stock_weights, equal_weights = _compositions(report, execution, columns)
    features = _features(execution, stock_weights)
    raw_labels, label_end_on = _labels(execution, stock_weights)
    feature_dates = np.broadcast_to(execution.dates[:, None], features.shape).copy()
    feature_dates[~np.isfinite(features)] = np.datetime64("NaT", "D")
    training_labels = raw_labels.copy()
    training_labels[:WARMUP_ROWS] = np.nan
    regression = RegressionInputs(
        dates=execution.dates,
        features=features,
        feature_available_on=feature_dates,
        labels=training_labels,
        label_end_on=label_end_on,
        label_available_on=label_end_on,
        feature_names=FEATURE_NAMES,
    )
    audit = {
        "schema": "nested-market-inputs/1",
        "feature_scope": "price-only gate over reconstructed desk stock baskets",
        "training_warmup_rows": WARMUP_ROWS,
        "label_entry_offset": 1,
        "label_exit_offset": LABEL_EXIT_OFFSET,
        "label_basis": "gross adjusted-open endpoint proxy, not funded account P&L",
        "stock_cadence": STOCK_CADENCE,
        "stock_cadence_anchor": "global source row zero",
        "book_config": asdict(risk.BOOK_CONFIG),
        "feature_names": list(FEATURE_NAMES),
        "finite_features": np.isfinite(features).sum(axis=0).tolist(),
        "finite_raw_labels": np.isfinite(raw_labels).sum(axis=0).tolist(),
        "finite_training_labels": np.isfinite(training_labels).sum(axis=0).tolist(),
        "historical_availability_verified": False,
        "historical_membership_verified": False,
        "quality_features_complete": False,
        "adoption_eligible": False,
        "assembly_binding": before,
    }
    if before != binding(report):
        raise ValueError("report or source changed during input assembly")
    return StudyInputs(
        report,
        execution,
        regression,
        _owned(stock_weights),
        _owned(equal_weights),
        _owned(raw_labels),
        _owned(label_end_on),
        audit,
    )


# Authenticate pinned local sources before constructing this fixed experiment's inputs.
def load(report_path: Path, store_root: Path, manifest_path: Path) -> StudyInputs:
    from backend.market import nested_market_sources

    report, panel, provenance = nested_market_sources.load(
        report_path, store_root, manifest_path
    )
    result = assemble(report, panel)
    return replace(result, audit={**result.audit, "sources": provenance})
