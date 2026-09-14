"""Predeclared intraday allocation candidates, never broker instructions.

Technical-only and technical-plus-macro arms reuse the same risk manager.
The macro arm tests the existing defensive budget when inflation pressure
builds and both daily and weekly benchmark trends are negative. This is a
candidate policy, not a claim that the condition predicts profitable exits.
"""

from dataclasses import dataclass
from datetime import datetime

import numpy as np

from backend.agents.trading.desk import economist, grading, risk
from backend.agents.trading.desk.regime import TIGHTENING_EXPOSURE
from backend.market import desk_freshness, holdings
from backend.market.panel import Panel

VERSION = "intraday-macro-candidate/1"


@dataclass(frozen=True)
class Budget:
    """An exposure ceiling and the existing rate-driven volatility tilt."""

    exposure: float
    tightening: bool


# Keep unknown macro inputs distinct from a known absence of the defensive trigger.
def macro_budget(
    record: dict, snapshot: dict, economic: dict, now: datetime
) -> tuple[Budget, dict]:
    assessment = economic.get("assessment") or {}
    observed = desk_freshness.timestamp(economic.get("observed_at"))
    if (
        observed is None
        or not 0 <= (now - observed).total_seconds() < 36 * 3600
        or assessment.get("status") != "model_assessment"
        or assessment.get("prompt_version") != economist.VERSION
        or assessment.get("pressure") not in ("easing", "building", "mixed")
    ):
        raise ValueError("Fresh, known economic assessment required")
    benchmark = snapshot.get("technical_detail", {}).get("SPY") or {}
    daily = (benchmark.get("short") or {}).get("daily_trend")
    weekly = (benchmark.get("medium") or {}).get("weekly_trend")
    if daily not in (-1, 0, 1) or weekly not in (-1, 0, 1):
        raise ValueError("Benchmark daily and weekly trends required")
    source = record.get("regime") or {}
    exposure = float(source.get("exposure", float("nan")))
    if not np.isfinite(exposure) or not 0 <= exposure <= 1:
        raise ValueError("Valid evening exposure budget required")
    defensive = assessment["pressure"] == "building" and daily < 0 and weekly < 0
    capped = min(exposure, TIGHTENING_EXPOSURE) if defensive else exposure
    return Budget(capped, bool(source.get("tightening", False))), {
        "pressure": assessment["pressure"],
        "observed_at": economic["observed_at"],
        "content_sha256": economic.get("content_sha256"),
        "evidence_ids": assessment.get("evidence_ids") or [],
        "daily_trend": daily,
        "weekly_trend": weekly,
        "defensive": defensive,
        "base_exposure": exposure,
        "exposure": capped,
    }


# Re-size current grades through the existing concentration and volatility caps.
def calculate(
    record: dict, snapshot: dict, economic: dict, panel: Panel, now: datetime
) -> dict:
    technical, value = desk_freshness.grade_inputs(snapshot, record, now)
    names = set(record.get("grades") or {})
    described = desk_freshness.describe(snapshot, now)
    required = names | {panel.benchmark}
    missing = required - {
        name
        for name, status in described["quote_status"].items()
        if not status["stale"]
    }
    if missing or names - set(technical):
        raise ValueError("Complete fresh price and technical coverage required")
    prices = [float(snapshot["quotes"][name].get("last", 0)) for name in required]
    if not all(np.isfinite(price) and price > 0 for price in prices):
        raise ValueError("Finite positive prices required")
    bars = {snapshot["quotes"][name]["bar"] for name in required}
    if len(bars) != 1:
        raise ValueError("Synchronized completed bars required")
    if (
        str(panel.dates[-1])
        != now.astimezone(desk_freshness.NEW_YORK).date().isoformat()
    ):
        raise ValueError("Current-session risk panel required")
    budget, macro = macro_budget(record, snapshot, economic, now)
    live = holdings.live_grades(record, technical, value)
    scores = np.full(len(panel.tickers), np.nan)
    grades = np.zeros(len(panel.tickers), dtype=int)
    for name in names:
        reading = live.get(name)
        if reading is None or not np.isfinite(reading["score_live"]):
            raise ValueError("A current grade and score are required for every name")
        column = panel.index(name)
        scores[column] = reading["score_live"]
        grades[column] = grading.ORDINAL[reading["grade_live"]]
    base_budget = Budget(macro["base_exposure"], budget.tightening)
    _, technical_targets = risk.desk_targets(scores, grades, panel, base_budget)
    _, macro_targets = risk.desk_targets(scores, grades, panel, budget)
    deadlines = desk_freshness.grade_expiries(snapshot, required)
    return {
        "version": VERSION,
        "mode": "research_only",
        "session": record["session"],
        "as_of": now.isoformat(),
        "bar": next(iter(bars)),
        "valid_until": min(deadlines.values()),
        "macro": macro,
        "valuation": "evening expectations model retained"
        if "expectations-gap"
        in ((record.get("provenance") or {}).get("rule") or {}).get("inputs", [])
        else "compatible intraday value",
        "grades": live,
        "targets": {
            name: float(macro_targets[panel.index(name)]) for name in sorted(names)
        },
        "technical_targets": {
            name: float(technical_targets[panel.index(name)]) for name in sorted(names)
        },
        "baseline_targets": {
            row["ticker"]: row["weight"] for row in record.get("book") or []
        },
        "prices": {
            name: float(snapshot["quotes"][name]["last"]) for name in sorted(required)
        },
        "event_paused": bool(
            (record.get("event_risk") or {}).get("execution_pending")
            or (record.get("event_risk") or {}).get("factor") == 0.5
            or (record.get("event_risk") or {}).get("calendar_known") is False
        ),
    }
