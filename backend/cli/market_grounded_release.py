"""Bounded research-only extraction check; never writes market or broker state."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from backend.agents.trading.grounded_release import extract, text_hash
from backend.agents.trading.grounded_release_cases import CASES
from backend.core.interfaces import TextWriter
from backend.core.llm import OpenAICompatibleInferenceProvider


# Run the fixed cases sequentially and retain failures instead of hiding missing output.
def evaluate(writer: TextWriter, model: str) -> dict:
    rows = []
    for case in CASES:
        row = {
            "id": case["id"],
            "source_sha256": text_hash(case["text"]),
            "expected": case["expected"],
        }
        try:
            result = extract(
                writer,
                case["text"],
                published_at=datetime(2026, 9, 29, 20, tzinfo=UTC),
                model=model,
            )
            observed = {key: fact["value"] for key, fact in result["features"].items()}
            row.update(
                result=result, observed=observed, passed=observed == case["expected"]
            )
        except Exception as exc:
            # Avoid echoing provider bodies or credentials into a stored report.
            row.update(passed=False, error=type(exc).__name__)
        rows.append(row)
        print(f"{case['id']}: {'PASS' if row['passed'] else 'FAIL'}", flush=True)
    return {
        "scope": "synthetic extraction feasibility, not trading performance",
        "model": model,
        "cases": rows,
        "passed": sum(r["passed"] for r in rows),
        "total": len(rows),
    }


# Preserve one report without overwriting any prior run.
def write_report(path: Path, report: dict) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")


# Evaluate the existing runtime only; the caller must explicitly name it and an output.
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--llm-url", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; use a new report path")
    writer = OpenAICompatibleInferenceProvider(
        args.llm_url, args.model, timeout_seconds=120, reasoning_effort=""
    )
    report = evaluate(writer, args.model)
    write_report(args.output, report)
    print(f"{report['passed']}/{report['total']} extraction cases passed")
    raise SystemExit(0 if report["passed"] == report["total"] else 1)


if __name__ == "__main__":
    main()
