"""Read the reviewed price-only experiment without touching trading policies."""

import json
from pathlib import Path

FILE = Path(__file__).parent / "data" / "neural_price_study_20260924.json"


# Serve the frozen research result separately from account plans and nightly neural.
def summary():
    payload = json.loads(FILE.read_text(encoding="utf-8"))
    if payload["policy"] != "neural-price-only-live-ranking/1":
        raise ValueError("Unexpected research policy")
    if payload["adoption_eligible"] is not False:
        raise ValueError("Research artifact cannot authorize a live strategy")
    return {
        "policy": payload["policy"],
        "title": "Price-only neural ranking test",
        "status": "research_only_not_adopted",
        "decision": (
            "This candidate had lower return, deeper drawdown and higher turnover "
            "relative to account value than the incumbent at both tested costs."
        ),
        "limitations": [
            "Current survivor universe and reconstructed grades; these are not "
            "achievable-return estimates or personal account returns.",
            "The 2025–2026 evaluation period was previously examined, not an "
            "untouched holdout. Earlier periods were used for training and "
            "configuration.",
            "Eight price/volume features; all financial inputs are missing. Only "
            "scheduled ranking changes; existing entry, exit and risk rules remain.",
            "Live-rule buy/sell timing is retained. Index and equal-weight controls "
            "use next-open execution. Midpoint fills are not demonstrated.",
        ],
        "tables": payload["tables"],
        "provenance": payload["provenance"],
    }
