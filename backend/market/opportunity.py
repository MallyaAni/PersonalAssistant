"""Explain the existing analyst evidence on a bounded scale, not a return forecast."""

import math

from backend.agents.trading.desk import grading
from backend.agents.trading.desk.opinions import SHARPNESS, conviction_from_ranks
from backend.market import desk_freshness


# Normalize the configured analyst convictions while preserving missing input evidence.
def explain(grade, live, quote, deadline, now, session):
    ranks = (live or {}).get("ranks_live") or grade.get("ranks") or {}
    parts = []
    missing = []
    for analyst, weight in grading.ANALYST_WEIGHTS.items():
        rank = ranks.get(analyst)
        if rank is None or not math.isfinite(rank) or not 0 <= rank <= 1:
            missing.append(analyst)
            continue
        score = 5 * (1 + float(conviction_from_ranks(rank, SHARPNESS)))
        current = bool(live) and (
            analyst == "technical"
            and live.get("technical_now") is not None
            or analyst == "value"
            and live.get("value_now") is not None
        )
        parts.append(
            {
                "analyst": analyst,
                "score": score,
                "weight": weight,
                "basis": "intraday" if current else session,
                "evidence": (grade.get("reads") or {}).get(analyst) or [],
            }
        )
    until = desk_freshness.timestamp(deadline)
    price = quote.get("last")
    fresh = bool(
        live and until and now < until and price and math.isfinite(price) and price > 0
    )
    score = (
        sum(p["score"] * p["weight"] for p in parts)
        / sum(grading.ANALYST_WEIGHTS.values())
        if not missing and fresh
        else None
    )
    return {
        "version": "analyst-opportunity/1",
        "score": score,
        "status": "indicative" if score is not None else "unavailable",
        "price": price if fresh else None,
        "bar": quote.get("bar"),
        "valid_until": deadline,
        "parts": parts,
        "missing": missing,
        "valuation_current": bool(live and live.get("value_now") is not None),
        "method": "Configured analyst convictions normalized to 0–10. "
        "This is an evidence index, not a predicted return or probability of profit.",
    }
