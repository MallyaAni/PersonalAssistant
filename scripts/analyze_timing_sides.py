"""Read frozen zero-cost timing traces without fitting or replaying a policy."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics


# Distinguish starting, increasing, reducing and closing a position by its intent.
def action(row):
    if row["side"] == "buy":
        return "entry" if row["initial_shares"] == 0 else "add"
    if row["side"] == "sell":
        return "exit" if row["desired_shares"] == 0 else "trim"
    raise ValueError("Unknown side")


# Require unique original intents and actual zero-cost accounting evidence.
def indexed(rows):
    result = {}
    for row in rows:
        key = row["intent_id"]
        if key in result:
            raise ValueError("Duplicate intent")
        if row["fee"] != 0:
            raise ValueError("Nonzero fee in zero-cost trace")
        action(row)
        result[key] = row
    return result


# Keep empty comparisons unavailable rather than manufacturing a zero effect.
def distribution(values):
    if not values:
        return {"count": 0, "mean": None, "median": None, "positive": 0}
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Nonfinite comparison")
    return {
        "count": len(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "positive": sum(value > 0 for value in values),
    }


# Compare only same-action common fills and disclose everything excluded from prices.
def summarize(phases, start, end, kind):
    counts = Counter()
    outcomes = {name: Counter() for name in ("candidate", "control")}
    prices, clocks, quantities = [], [], []
    for phase in phases:
        arms = {
            name: indexed(phase[name]["intent_trace"])
            for name in ("candidate", "control")
        }
        for key in sorted(arms["candidate"].keys() | arms["control"].keys()):
            pair = {name: rows.get(key) for name, rows in arms.items()}
            present = [row for row in pair.values() if row is not None]
            if not start <= present[0]["date"] <= end:
                continue
            if not any(action(row) == kind for row in present):
                continue
            counts["union_intents"] += 1
            for name, row in pair.items():
                if row is not None and action(row) == kind:
                    outcomes[name][row["outcome"]] += 1
            a, b = pair["candidate"], pair["control"]
            if a is None or b is None:
                counts["unmatched"] += 1
                continue
            if action(a) != kind or action(b) != kind:
                counts["different_action"] += 1
                continue
            counts["same_action"] += 1
            if a["attempt_clock"] is not None and b["attempt_clock"] is not None:
                clocks.append(15 * (a["attempt_clock"] - b["attempt_clock"]))
            if not a["filled_delta"] or not b["filled_delta"]:
                counts["one_or_both_unfilled"] += 1
                continue
            pa, pb = a["realized_price"], b["realized_price"]
            if not all(isinstance(p, (int, float)) and math.isfinite(p) and p > 0
                       for p in (pa, pb)):
                raise ValueError("Filled intent lacks a finite positive price")
            direction = 1 if a["side"] == "buy" else -1
            prices.append(direction * (pb - pa) / pb * 10000)
            quantities.append(abs(a["filled_delta"]) / abs(b["filled_delta"]))
    return {
        "counts": dict(counts),
        "outcomes": {name: dict(rows) for name, rows in outcomes.items()},
        "common_fill_price_advantage_bp": distribution(prices),
        "common_attempt_delay_minutes": distribution(clocks),
        "common_fill_quantity_ratio": distribution(quantities),
    }


# Authenticate saved evidence and retain every zero-cost phase and registered era.
def analyze(path, expected_sha256):
    raw = Path(path).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_sha256:
        raise ValueError("Original report hash mismatch")
    report = json.loads(raw)
    if report["status"] != "complete_reused_conditional_research":
        raise ValueError("Completed original report required")
    phases = [row for row in report["phases"] if row["cost_bps"] == 0]
    if sorted(row["phase"] for row in phases) != list(range(20)):
        raise ValueError("All twenty original zero-cost phases required")
    windows = (
        ("all", "2018-02-01", "2026-09-30"),
        ("early", "2018-02-01", "2020-12-31"),
        ("later", "2021-01-01", "2026-09-30"),
        ("reused_recent", "2026-08-17", "2026-09-30"),
    )
    return {
        "source_sha256": digest,
        "cost_bps": 0,
        "adoption_eligible": False,
        "interpretation": [
            "Positive price advantage means lower buy or higher sell price.",
            "Equal-intent paired price diagnostic, not compounded portfolio gain.",
            "Phase observations overlap; counts are not independent sample sizes.",
            "Different fills affect later quantities; no causal side attribution.",
            "Current-vintage universe and reused windows, not a fresh holdout.",
        ],
        "windows": {
            label: {kind: summarize(phases, start, end, kind)
                    for kind in ("entry", "add", "trim", "exit")}
            for label, start, end in windows
        },
    }


# Print a saved-evidence diagnostic without creating or changing trading artifacts.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(analyze(args.report, args.sha256), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
