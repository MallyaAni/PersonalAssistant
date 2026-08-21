"""Read the accumulated context measurements and say what the floors should be.

    python -m backend.cli.report_context_usage
    docker compose exec backend python -m backend.cli.report_context_usage

The context budget ships observe-only because floors chosen before the
measurement they are meant to come from would be the number-first,
justification-afterwards mistake this whole area exists to stop. This is the
other half of that bargain: once real turns have accumulated in the telemetry
file, it prints the per-section distribution and a suggested floor per
section, and until enough have accumulated it says so instead of suggesting.

Suggestions are advisory and deliberately conservative: the floor offered is
the 90th percentile of items a section actually kept on the turns where it
appeared at all. A floor guarantees survival under pressure, so sizing it to
the common case rather than the maximum keeps a heavy outlier from reserving
space every ordinary turn pays for.
"""

import argparse
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from backend.config.settings import settings

# Below this many turns a percentile is an anecdote. The threshold is loose on
# purpose: the point is to refuse to suggest floors from three probes.
_MIN_TURNS_FOR_SUGGESTIONS = 25


def _percentile(values: list[int], pct: float) -> int:
    ordered = sorted(values)
    if not ordered:
        return 0
    index = min(len(ordered) - 1, round(pct * (len(ordered) - 1)))
    return ordered[int(index)]


def load_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn line from a crash mid-write costs that line, not the
                # report.
                continue
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=settings.CONTEXT_REPORT_PATH)
    args = parser.parse_args(argv)

    path = Path(args.path)
    if not path.exists():
        print(f"No measurements at {path} - has any authenticated turn run?")
        return 1
    rows = load_rows(path)
    if not rows:
        print(f"{path} exists but holds no readable rows")
        return 1

    used = [row["used_tokens"] for row in rows]
    dropped = sum(row.get("dropped_total", 0) for row in rows)
    print(f"turns measured : {len(rows)}")
    print(f"window         : {rows[-1]['budget_tokens']} spendable tokens")
    print(
        "used tokens    : "
        f"p50={_percentile(used, 0.5):,} p90={_percentile(used, 0.9):,} "
        f"max={max(used):,}"
    )
    print(f"dropped total  : {dropped}")

    kept: dict[str, list[int]] = defaultdict(list)
    tokens: dict[str, list[int]] = defaultdict(list)
    present: dict[str, int] = defaultdict(int)
    for row in rows:
        for name, section in (row.get("sections") or {}).items():
            if section.get("kept", 0) > 0:
                present[name] += 1
                kept[name].append(section["kept"])
                tokens[name].append(section.get("tokens", 0))

    print(
        f"\n{'section':<10} {'present':>8} {'kept p50/p90/max':>18} {'tokens p90':>11}"
    )
    for name in sorted(present, key=lambda n: -present[n]):
        counts = kept[name]
        spread = f"{_percentile(counts, 0.5)}/{_percentile(counts, 0.9)}/{max(counts)}"
        print(
            f"{name:<10} {present[name]:>7,}x {spread:>18} "
            f"{_percentile(tokens[name], 0.9):>10,}"
        )

    if len(rows) < _MIN_TURNS_FOR_SUGGESTIONS:
        print(
            f"\n{len(rows)} turns is not a distribution "
            f"({_MIN_TURNS_FOR_SUGGESTIONS} needed); no floors suggested yet."
        )
        return 0

    print("\nsuggested floor_items (p90 of kept, where the section appeared):")
    for name in sorted(present, key=lambda n: -present[n]):
        if name in ("system", "query"):
            continue  # never trimmable; a floor is meaningless
        print(f"  {name:<10} {_percentile(kept[name], 0.9)}")
    print(
        "\nApply by editing _turn_sections in backend/agents/graph.py, then "
        "enable CONTEXT_BUDGET_ENFORCE only once trimming is implemented."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
