"""The A2 statement-reading arm: an anonymised packet, a direction, a stance.

A packet is the last eight quarters of standardised facts for one name,
built only from versions available at the decision session, with no name,
ticker, sector, date, fiscal label, currency or absolute scale. A local
model reads it and commits to the direction of the next reported quarter's
net income against the same quarter a year earlier. The answer is scored
two ways: as a direction against the first-filed label, and as a
cross-sectional stance against beta-adjusted residual returns.

Registered in `docs/research/statement-reading-preregistration-2026-11-01.md`.
Research only: this module writes nothing and changes no live path.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import math
import time
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import numpy as np

from backend.core.llm import StrictSchema
from backend.market import fundamentals_asof as fa
from backend.market import harness

PACKET_VERSION = "statement-reading-packet/1"
PROMPT_VERSION = "statement-reading-prompt/1"
SCHEMA_VERSION = "statement-reading-schema/1"
DIRECTIONS = ("up", "down", "flat", "uncertain")
FACTS = ("revenue", "gross_profit", "net_income", "operating_cash_flow", "capex")
ROW_COUNT = 8
MIN_ROWS = 6
MATCH_DAYS = 20
QUARTER_LOW, QUARTER_HIGH = 75, 105
YEAR_AGO_LOW, YEAR_AGO_HIGH = 350, 380
FLAT_FRACTION = 0.01
BENCHMARK_IC = 0.02
BENCHMARK_ACCURACY = 0.527
MIN_ACCURACY_NAMES = 300
MIN_STANCE_DAYS = 30
MIN_STANCE_NAMES = 20
MODEL = "deepseek-v4.1-flash-1017"
BASE_URL = "http://127.0.0.1:8000"
TEMPERATURE = 0.0
MAX_TOKENS = 1500
RETRY_TOKENS = 2500

# The table columns the model sees, in order. `quarter` is relative; the
# internal actual end never reaches the prompt.
COLUMNS = (
    "revenue_index",
    "revenue_yoy_pct",
    "revenue_qoq_pct",
    "gross_margin_pct",
    "net_margin_pct",
    "ocf_margin_pct",
    "capex_pct_revenue",
    "net_income_yoy_pct",
    "net_income_qoq_pct",
)


@dataclass(frozen=True, slots=True)
class PacketRow:
    """One relative quarter in the packet, with its internal actual end."""

    quarter: str
    end: date | None
    revenue_index: float | None
    revenue_yoy_pct: float | None
    revenue_qoq_pct: float | None
    gross_margin_pct: float | None
    net_margin_pct: float | None
    ocf_margin_pct: float | None
    capex_pct_revenue: float | None
    net_income_yoy_pct: float | None
    net_income_qoq_pct: float | None

    # The row as the model sees it: no actual date, no raw level.
    def view(self) -> dict[str, object]:
        """Return the model-facing row."""
        return {
            "quarter": self.quarter,
            **{name: getattr(self, name) for name in COLUMNS},
        }


@dataclass(frozen=True, slots=True)
class Packet:
    """The eight-row packet plus the internal anchor and chosen tag."""

    anchor: date
    net_income_tag: str
    rows: tuple[PacketRow, ...]

    # The model-facing packet: only the relative rows.
    def view(self) -> dict[str, object]:
        """Return the packet as sent to the model."""
        return {
            "packet_version": PACKET_VERSION,
            "rows": [row.view() for row in self.rows],
        }

    # The stable identity of the model-facing packet, used as the cache key.
    def digest(self) -> str:
        """Return the SHA-256 of the canonical model-facing packet."""
        payload = json.dumps(self.view(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Move a date by whole months, clamping the day to the target month's last
# day. Fiscal quarter ends are within a few days of these targets.
def _shift_months(day: date, months: int) -> date:
    """Return `day` shifted by `months`, clamped to the month's last day."""
    year = day.year + (day.month - 1 + months) // 12
    month = (day.month - 1 + months) % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


# The actual quarter end nearest a target, and its value, within `days`.
def _closest(
    series: Mapping[date, float], target: date, days: int = MATCH_DAYS
) -> tuple[date | None, float | None]:
    """Return (actual end, value) nearest `target` within `days`, or (None, None)."""
    best: tuple[int, date, float] | None = None
    for end, value in series.items():
        gap = abs((end - target).days)
        if gap <= days and (
            best is None or gap < best[0] or (gap == best[0] and end > best[1])
        ):
            best = (gap, end, value)
    if best is None:
        return None, None
    return best[1], best[2]


# The value closest to 365 days before `end`, within the registered window.
def _year_ago(series: Mapping[date, float], end: date | None) -> float | None:
    """Return the year-ago value for `end`, or None."""
    if end is None:
        return None
    candidates = [
        (abs((end - other).days - 365), other, value)
        for other, value in series.items()
        if YEAR_AGO_LOW <= (end - other).days <= YEAR_AGO_HIGH
    ]
    if not candidates:
        return None
    return min(candidates)[2]


# A percentage change against the absolute prior value, rounded; None when
# either side is missing or the prior is zero.
def _growth(current: float | None, prior: float | None) -> float | None:
    """Return 100 * (current - prior) / |prior|, or None."""
    if current is None or prior is None or prior == 0:
        return None
    return _round((current - prior) / abs(prior) * 100.0)


# A ratio as a percentage of the denominator, rounded; None when either side
# is missing or the denominator is zero.
def _ratio(numerator: float | None, denominator: float | None) -> float | None:
    """Return 100 * numerator / denominator, or None."""
    if numerator is None or denominator is None or denominator == 0:
        return None
    return _round(numerator / denominator * 100.0)


# Two decimals, with negative zero normalised away.
def _round(value: float) -> float:
    """Return `value` rounded to two decimals."""
    rounded = round(float(value), 2)
    return 0.0 if rounded == 0 else rounded


# The chosen tag and its quarter series for one fact at one decision date.
def _series_for(
    versions: Sequence[fa.Version], name: str, decision: date
) -> tuple[str | None, dict[date, float]]:
    """Return (tag, {quarter end: value}) for one fact as of `decision`."""
    by_tag: dict[str, dict[tuple[date | None, date], fa.Version]] = defaultdict(dict)
    for version in versions:
        if version.name != name or version.start is None:
            continue
        if version.available > decision:
            continue
        held = by_tag[version.tag].get((version.start, version.end))
        if held is None or (version.filed, version.accession) >= (
            held.filed,
            held.accession,
        ):
            by_tag[version.tag][(version.start, version.end)] = version
    if not by_tag:
        return None, {}
    ranked = fa._ranked_tags(name, by_tag, True)
    if not ranked:
        return None, {}
    tag = ranked[0]
    return tag, fa._quarters(by_tag[tag], True)


# Build the registered packet at `decision`; None when the name has fewer
# than six net-income or six revenue rows.
def build_packet(
    versions: Sequence[fa.Version], decision: date
) -> Packet | None:
    """Return the anonymised packet available at `decision`, or None."""
    tags: dict[str, str | None] = {}
    series: dict[str, dict[date, float]] = {}
    for name in FACTS:
        tags[name], series[name] = _series_for(versions, name, decision)
    net_income = series["net_income"]
    if not net_income or tags["net_income"] is None:
        return None
    anchor = max(net_income)
    targets = [
        _shift_months(anchor, -3 * step)
        for step in range(ROW_COUNT - 1, -1, -1)
    ]
    rows: list[PacketRow] = []
    revenue_values: list[float | None] = []
    net_income_values: list[float | None] = []
    previous_revenue: float | None = None
    previous_net_income: float | None = None
    previous_revenue_end: date | None = None
    previous_net_income_end: date | None = None
    for index, target in enumerate(targets):
        revenue_end, revenue = _closest(series["revenue"], target)
        net_income_end, income = _closest(net_income, target)
        _, gross = _closest(series["gross_profit"], target)
        _, cash_flow = _closest(series["operating_cash_flow"], target)
        _, capex = _closest(series["capex"], target)
        revenue_qoq = None
        if (
            revenue is not None
            and previous_revenue is not None
            and revenue_end is not None
            and previous_revenue_end is not None
            and QUARTER_LOW
            <= (revenue_end - previous_revenue_end).days
            <= QUARTER_HIGH
        ):
            revenue_qoq = _growth(revenue, previous_revenue)
        income_qoq = None
        if (
            income is not None
            and previous_net_income is not None
            and net_income_end is not None
            and previous_net_income_end is not None
            and QUARTER_LOW
            <= (net_income_end - previous_net_income_end).days
            <= QUARTER_HIGH
        ):
            income_qoq = _growth(income, previous_net_income)
        revenue_yoy = _growth(revenue, _year_ago(series["revenue"], revenue_end))
        income_yoy = _growth(income, _year_ago(net_income, net_income_end))
        rows.append(
            PacketRow(
                quarter=f"t-{ROW_COUNT - 1 - index}",
                end=net_income_end,
                revenue_index=None,
                revenue_yoy_pct=revenue_yoy,
                revenue_qoq_pct=revenue_qoq,
                gross_margin_pct=_ratio(gross, revenue),
                net_margin_pct=_ratio(income, revenue),
                ocf_margin_pct=_ratio(cash_flow, revenue),
                capex_pct_revenue=_ratio(capex, revenue),
                net_income_yoy_pct=income_yoy,
                net_income_qoq_pct=income_qoq,
            )
        )
        revenue_values.append(revenue)
        net_income_values.append(income)
        previous_revenue = revenue
        previous_net_income = income
        previous_revenue_end = revenue_end
        previous_net_income_end = net_income_end
    if sum(value is not None for value in revenue_values) < MIN_ROWS:
        return None
    if sum(value is not None for value in net_income_values) < MIN_ROWS:
        return None
    base = next(
        (value for value in reversed(revenue_values) if value is not None), None
    )
    indexed = tuple(
        replace(
            row,
            revenue_index=(
                _round(value / base * 100.0)
                if value is not None and base is not None and base != 0
                else None
            ),
        )
        for row, value in zip(rows, revenue_values, strict=True)
    )
    return Packet(
        anchor=anchor,
        net_income_tag=tags["net_income"],
        rows=indexed,
    )


# The first-filed value and public date for every quarter end under one tag.
def _first_filed(
    versions: Sequence[fa.Version], tag: str
) -> dict[date, tuple[float, date]]:
    """Return {end: (first value, first available)} under `tag`."""
    first: dict[date, tuple[float, date]] = {}
    ordered = sorted(
        versions,
        key=lambda version: (version.available, version.filed, version.accession),
    )
    for version in ordered:
        if version.name != "net_income" or version.tag != tag:
            continue
        if (
            version.start is None
            or fa.span_kind(version.start, version.end) != "quarter"
        ):
            continue
        if not np.isfinite(version.value):
            continue
        first.setdefault(version.end, (version.value, version.available))
    return first


# The first-filed next quarter and its year-ago, labelled up/down/flat.
def build_label(
    versions: Sequence[fa.Version], packet: Packet, decision: date, asof: date
) -> dict[str, object] | None:
    """Return the registered next-quarter label, or None when it cannot be built."""
    first = _first_filed(versions, packet.net_income_tag)
    later = [end for end in first if end > packet.anchor]
    if not later:
        return None
    next_end = min(later)
    next_value, next_available = first[next_end]
    # The first quarter after the anchor is the only candidate. If it was
    # already public at the decision, the name has no label; the study does
    # not skip ahead to a later quarter.
    if not decision < next_available <= asof:
        return None
    prior = [
        end
        for end in first
        if end < next_end and YEAR_AGO_LOW <= (next_end - end).days <= YEAR_AGO_HIGH
    ]
    if not prior:
        return None
    year_ago_end = min(prior, key=lambda end: abs((next_end - end).days - 365))
    year_ago_value, year_ago_available = first[year_ago_end]
    if year_ago_available > decision or year_ago_available > asof:
        return None
    tolerance = FLAT_FRACTION * abs(year_ago_value)
    change = next_value - year_ago_value
    if year_ago_value == 0:
        label = "flat" if next_value == 0 else ("up" if change > 0 else "down")
    elif change > tolerance:
        label = "up"
    elif change < -tolerance:
        label = "down"
    else:
        label = "flat"
    return {
        "label": label,
        "next_end": next_end,
        "next_available": next_available,
        "next_value": next_value,
        "year_ago_end": year_ago_end,
        "year_ago_value": year_ago_value,
        "change": change,
        "tolerance": tolerance,
    }


# The registered prompt for one packet, with the table rendered as NA where
# a value is missing.
def render_prompt(packet: Packet) -> str:
    """Return the registered prompt for `packet`."""
    header = "| quarter | " + " | ".join(COLUMNS) + " |"
    rule = "|" + "---|" * (len(COLUMNS) + 1)
    lines = [header, rule]
    for row in packet.view()["rows"]:
        cells = [row["quarter"]]
        for name in COLUMNS:
            value = row[name]
            cells.append("NA" if value is None else f"{value:.2f}")
        lines.append("| " + " | ".join(cells) + " |")
    table = "\n".join(lines)
    return (
        "The table below is an anonymised quarterly record for one company. "
        "Rows are in chronological order, oldest first; t0 is the most recent "
        "reported quarter. Each row is a fiscal quarter. NA means the item was "
        "not reported or cannot be computed. All values are dimensionless: "
        "revenue_index sets the most recent available quarter's revenue to 100; "
        "margins and growth rates are percentages. Negative net income is "
        "possible, so net_income_yoy_pct and net_income_qoq_pct divide by the "
        "absolute value of the prior value.\n\n"
        f"{table}\n\n"
        "Predict whether net income in the next reported quarter (t+1) will be "
        "higher, lower, or approximately equal to net income in the same quarter "
        "one year earlier (t-3). \"flat\" means the change is within 1% of the "
        "absolute year-ago value. Answer \"uncertain\" only if the record does "
        "not support a direction.\n\n"
        "Write a short analysis first, then the direction and a confidence "
        "between 0 and 1. Do not use outside knowledge about any company, "
        "industry, market, or economy. Base the answer only on the table."
    )


SCHEMA = StrictSchema(
    {
        "type": "object",
        "properties": {
            "analysis": {"type": "string", "minLength": 1},
            "direction": {"type": "string", "enum": list(DIRECTIONS)},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
        "required": ["analysis", "direction", "confidence"],
        "additionalProperties": False,
    }
)


# Parse and validate the model's strict-schema answer.
def parse_answer(content: str) -> dict[str, object]:
    """Return the validated answer, raising ValueError on a bad shape."""
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("answer is not a JSON object")
    analysis = data.get("analysis")
    direction = data.get("direction")
    confidence = data.get("confidence")
    if not isinstance(analysis, str) or not analysis.strip():
        raise ValueError("analysis is empty")
    if direction not in DIRECTIONS:
        raise ValueError(f"direction is not registered: {direction!r}")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("confidence is not a number")
    value = float(confidence)
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("confidence is outside [0, 1]")
    return {
        "analysis": analysis.strip(),
        "direction": direction,
        "confidence": value,
    }


# One model call: greedy, strict schema, finish-reason and model-identity
# checks, with one retry at a larger token budget.
def ask(
    provider: Any,
    packet: Packet,
    max_tokens: int = MAX_TOKENS,
    retry_tokens: int = RETRY_TOKENS,
) -> dict[str, object]:
    """Return the validated answer and call metadata for one packet."""
    prompt = render_prompt(packet)
    messages = [{"role": "user", "content": prompt}]
    started = time.monotonic()
    try:
        result = provider.chat(
            messages,
            max_tokens=max_tokens,
            response_schema=SCHEMA,
            temperature=TEMPERATURE,
        )
    except ValueError:
        result = provider.chat(
            messages,
            max_tokens=retry_tokens,
            response_schema=SCHEMA,
            temperature=TEMPERATURE,
        )
    choice = result.get("choices", [{}])[0] if result.get("choices") else {}
    finish = choice.get("finish_reason")
    served = result.get("model")
    if finish == "length":
        result = provider.chat(
            messages,
            max_tokens=retry_tokens,
            response_schema=SCHEMA,
            temperature=TEMPERATURE,
        )
        choice = result.get("choices", [{}])[0] if result.get("choices") else {}
        finish = choice.get("finish_reason")
        served = result.get("model")
    if finish != "stop":
        raise ValueError(f"finish_reason is {finish!r}, not 'stop'")
    if served != provider.model:
        raise ValueError(f"served model is {served!r}, not {provider.model!r}")
    answer = parse_answer(result["content"])
    return {
        "answer": answer,
        "finish_reason": finish,
        "served_model": served,
        "latency": time.monotonic() - started,
        "usage": result.get("usage"),
        "content": result["content"],
        "prompt": prompt,
    }


# The cache key for one packet and one runtime configuration.
def cache_key(packet: Packet, model: str = MODEL) -> str:
    """Return the SHA-256 cache key for `packet`."""
    payload = json.dumps(
        {
            "packet": packet.view(),
            "prompt_version": PROMPT_VERSION,
            "schema_version": SCHEMA_VERSION,
            "model": model,
            "temperature": TEMPERATURE,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# +1 up, -1 down, 0 flat, NaN uncertain: the registered stance.
def stance(answer: Mapping[str, object] | None) -> float:
    """Return the sign stance for one answer."""
    if answer is None:
        return float("nan")
    direction = answer.get("direction")
    if direction == "up":
        return 1.0
    if direction == "down":
        return -1.0
    if direction == "flat":
        return 0.0
    return float("nan")


# +confidence up, -confidence down, 0 flat, NaN uncertain: the sensitivity.
def confidence_stance(answer: Mapping[str, object] | None) -> float:
    """Return the confidence-weighted stance for one answer."""
    if answer is None:
        return float("nan")
    direction = answer.get("direction")
    confidence = float(answer.get("confidence", 0.0))
    if direction == "up":
        return confidence
    if direction == "down":
        return -confidence
    if direction == "flat":
        return 0.0
    return float("nan")


# The daily cross-sectional rank IC of a stance matrix against the
# precomputed forward residual matrix.
def daily_ic(
    matrix: np.ndarray,
    forward: np.ndarray,
    benchmark: int,
    min_names: int = MIN_STANCE_NAMES,
) -> np.ndarray:
    """Return the (T,) daily rank IC, NaN where undefined."""
    out = np.full(len(matrix), np.nan, dtype=float)
    for session in range(len(matrix)):
        mask = np.isfinite(matrix[session]) & np.isfinite(forward[session])
        mask[benchmark] = False
        if int(mask.sum()) < min_names:
            continue
        out[session] = harness.rank_correlation(
            matrix[session][mask], forward[session][mask]
        )
    return out


# Newey-West t of the mean of a 1-D series, with `lag` overlap periods.
def newey_west_t(values: np.ndarray, lag: int) -> float | None:
    """Return the HAC t-statistic of the mean, or None when undefined."""
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 2 or float(np.ptp(values)) == 0:
        return None
    centred = values - values.mean()
    variance = float(centred @ centred) / len(values)
    for step in range(1, min(lag, len(values) - 1) + 1):
        covariance = float(centred[step:] @ centred[:-step]) / len(values)
        variance += 2.0 * (1.0 - step / (lag + 1.0)) * covariance
    if variance <= 0:
        return None
    return float(values.mean() / math.sqrt(variance / len(values)))


# ISO weeks present in the dates, used as the block bootstrap's independent
# units.
def week_ids(dates: Sequence[date]) -> list[tuple[int, int]]:
    """Return the ISO (year, week) for each date."""
    return [day.isocalendar()[:2] for day in dates]


# The mean daily IC resampled by week with replacement.
def block_bootstrap(
    values: np.ndarray,
    weeks: Sequence[tuple[int, int]],
    draws: int = 2000,
    seed: int = 20261101,
) -> dict[str, float | int | None]:
    """Return the mean and 95% interval of the weekly block bootstrap."""
    values = np.asarray(values, dtype=float)
    keep = np.isfinite(values)
    values = values[keep]
    groups = [
        week for week, kept in zip(weeks, keep, strict=True) if kept
    ]
    if len(values) < 2 or len(set(groups)) < 2:
        return {"draws": 0, "mean": None, "lower": None, "upper": None}
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for value, week in zip(values, groups, strict=True):
        buckets[week].append(float(value))
    keys = sorted(buckets)
    rng = np.random.default_rng(seed)
    means: list[float] = []
    for _ in range(draws):
        picked: list[float] = []
        for _ in range(len(keys)):
            picked.extend(buckets[keys[int(rng.integers(len(keys)))]])
        means.append(float(np.mean(picked)))
    return {
        "draws": draws,
        "mean": float(np.mean(means)),
        "lower": float(np.percentile(means, 2.5)),
        "upper": float(np.percentile(means, 97.5)),
    }


# The 95th percentile of the mean daily IC after shuffling the stance across
# names within each session, preserving the missing mask.
def stance_placebo(
    matrix: np.ndarray,
    forward: np.ndarray,
    benchmark: int,
    sessions: np.ndarray,
    draws: int = 200,
    seed: int = 20261101,
    min_names: int = MIN_STANCE_NAMES,
) -> dict[str, float | int | None]:
    """Return the placebo mean and 95th percentile of the daily IC."""
    rng = np.random.default_rng(seed)
    finite = np.isfinite(matrix)
    means: list[float] = []
    for _ in range(draws):
        shuffled = matrix.copy()
        for session in range(len(matrix)):
            columns = np.flatnonzero(finite[session])
            if len(columns) > 1:
                shuffled[session, columns] = matrix[session, rng.permutation(columns)]
        ics = daily_ic(shuffled, forward, benchmark, min_names=min_names)
        selected = ics[sessions & np.isfinite(ics)]
        if len(selected):
            means.append(float(selected.mean()))
    if not means:
        return {"draws": 0, "mean": None, "p95": None}
    return {
        "draws": len(means),
        "mean": float(np.mean(means)),
        "p95": float(np.percentile(means, 95)),
    }


# The exact one-sided binomial tail P(X >= correct) under p0.
def binomial_tail(correct: int, total: int, p0: float = BENCHMARK_ACCURACY) -> float:
    """Return the exact upper-tail probability."""
    if total < 0 or correct < 0 or correct > total:
        raise ValueError("correct must lie in [0, total]")
    if total == 0:
        return 1.0
    terms = [
        math.comb(total, k) * (p0**k) * ((1.0 - p0) ** (total - k))
        for k in range(correct, total + 1)
    ]
    return float(math.fsum(terms))


# The accuracy, coverage, baseline and exact binomial p of one sample.
def accuracy_stats(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Return the registered accuracy statistics for answered rows."""
    sample = [row for row in rows if row.get("answer") is not None]
    answered = [
        row
        for row in sample
        if row["answer"]["direction"] != "uncertain"  # type: ignore[index]
    ]
    labels = [row["label"]["label"] for row in answered]  # type: ignore[index]
    directions = [row["answer"]["direction"] for row in answered]  # type: ignore[index]
    total = len(answered)
    correct = sum(
        label == direction
        for label, direction in zip(labels, directions, strict=True)
    )
    counts = {name: labels.count(name) for name in ("up", "down", "flat")}
    majority = max(counts.values()) if counts else 0
    return {
        "labelled": len(rows),
        "answered_with_model": len(sample),
        "answered": total,
        "coverage": (total / len(rows)) if rows else None,
        "correct": correct,
        "accuracy": (correct / total) if total else None,
        "binomial_p": binomial_tail(correct, total) if total else None,
        "majority_accuracy": (majority / total) if total else None,
        "uncertain": len(sample) - total,
        "labels": counts,
        "directions": {
            name: directions.count(name) for name in DIRECTIONS
        },
    }


# The 95th percentile of accuracy after shuffling the answer directions
# across names, preserving the answer distribution.
def accuracy_placebo(
    rows: Sequence[Mapping[str, object]],
    draws: int = 200,
    seed: int = 20261101,
) -> dict[str, float | int | None]:
    """Return the placebo accuracy mean and 95th percentile."""
    answered = [
        row
        for row in rows
        if row.get("answer") is not None
        and row["answer"]["direction"] != "uncertain"  # type: ignore[index]
    ]
    if not answered:
        return {"draws": 0, "mean": None, "p95": None}
    labels = [row["label"]["label"] for row in answered]  # type: ignore[index]
    directions = [row["answer"]["direction"] for row in answered]  # type: ignore[index]
    rng = np.random.default_rng(seed)
    accuracies: list[float] = []
    for _ in range(draws):
        permuted = [directions[index] for index in rng.permutation(len(directions))]
        correct = sum(
            label == direction
            for label, direction in zip(labels, permuted, strict=True)
        )
        accuracies.append(correct / len(directions))
    return {
        "draws": draws,
        "mean": float(np.mean(accuracies)),
        "p95": float(np.percentile(accuracies, 95)),
    }


# Change future versions, the anchor version and gross profit to prove the
# packet ignores the future, reads the past and keeps missing as NA.
def perturbation_check(
    versions: Sequence[fa.Version], decision: date
) -> dict[str, object]:
    """Return the registered null-test result for one name."""
    baseline = build_packet(versions, decision)
    if baseline is None:
        return {
            "name": None,
            "future_identical": False,
            "newest_changes": False,
            "missing_is_na": False,
            "reason": "no baseline packet",
        }
    future = [
        replace(version, value=version.value + 1.0)
        if version.available > decision
        else version
        for version in versions
    ]
    shifted = build_packet(future, decision)
    same = (
        shifted is not None
        and json.dumps(shifted.view(), sort_keys=True)
        == json.dumps(baseline.view(), sort_keys=True)
    )
    baseline_view = json.dumps(baseline.view(), sort_keys=True)
    # The anchor's versions, newest first. A reported quarter can beat a
    # derived YTD value on the same end, so try each candidate until one
    # actually moves the packet; that one is the newest contributing past
    # version the registered test asks for.
    candidates = [
        version
        for version in versions
        if version.name == "net_income"
        and version.tag == baseline.net_income_tag
        and version.end == baseline.anchor
        and version.available <= decision
    ]
    candidates.sort(
        key=lambda version: (version.available, version.filed, version.accession),
        reverse=True,
    )
    moved = False
    for candidate in candidates:
        # A material change: adding one unit to a billion-dollar fact would
        # round away in the packet's two-decimal ratios and prove nothing.
        altered = [
            replace(version, value=version.value * 2.0 + 1.0)
            if version is candidate
            else version
            for version in versions
        ]
        changed = build_packet(altered, decision)
        if changed is not None and json.dumps(
            changed.view(), sort_keys=True
        ) != baseline_view:
            moved = True
            break
    no_gross = [
        version for version in versions if version.name != "gross_profit"
    ]
    missing = build_packet(no_gross, decision)
    missing_na = missing is not None and all(
        row.gross_margin_pct is None for row in missing.rows
    )
    return {
        "name": baseline.net_income_tag,
        "anchor": baseline.anchor.isoformat(),
        "future_identical": bool(same),
        "newest_changes": bool(moved),
        "missing_is_na": bool(missing_na),
    }
