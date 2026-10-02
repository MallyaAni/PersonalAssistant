"""A5 tone expiry's verdict: the control and both arms' payloads, judged.

    python -m backend.cli.market_tone_expiry \\
        --control docs/research/scorecards/tone-expiry/control.json \\
        --hard docs/research/scorecards/tone-expiry/hard.json \\
        --decay docs/research/scorecards/tone-expiry/decay.json

`docs/research/tone-expiry-plan-2026-10-01.md` registers the study;
`backend/market/tone_expiry_study.py` judges it. The three payloads are
point-in-time scorecard runs (`market_pit_scorecard --graded-cap 0.25`,
20 offsets, 10 and 25 bp): the control with `--sentiment-ic`, each arm
with `--tone-expiry hard|decay`. Each arm is judged against the control on
the plan's non-inferiority criteria - the paired sentiment IC difference
at 20 and 60 sessions with t >= -1, the book's paired daily difference with
Newey-West t >= -1 and its median CAGR no more than 0.5 point lower, on
both 2016-2023 and 2024-2026 - and A5-hard is the one proposed when both
pass. Pairs that do not describe the same desk (another session or
membership file, an incumbent IC series or desk fingerprint unlike the
control's) are refused: nothing is written and the exit code is 2.

Writes `tone_expiry_verdict.json` beside the control payload (or `--out`)
with each payload's sha256 and the code revision, and prints the verdict.
Nothing here trades or changes the desk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TextIO

from backend.cli.market_stage4_decisions import _sha256, revision
from backend.market import tone_expiry_study as tes

FILE = "tone_expiry_verdict.json"


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--control", type=Path, required=True, help="the control payload"
    )
    parser.add_argument("--hard", type=Path, required=True, help="A5-hard's payload")
    parser.add_argument("--decay", type=Path, required=True, help="A5-decay's payload")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"the verdict (default: {FILE} beside --control)",
    )
    return parser


# Read the three payloads, judge, write and print; 2 when refused.
def main(argv: list[str] | None = None, out: TextIO = sys.stdout) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    paths = {"control": args.control, "A5-hard": args.hard, "A5-decay": args.decay}
    missing = [str(p) for p in paths.values() if not p.is_file()]
    if missing:
        print(f"refused: not found: {', '.join(missing)}", file=out)
        return 2
    loaded = {k: json.loads(p.read_text(encoding="utf-8")) for k, p in paths.items()}
    control = loaded.pop("control")
    try:
        reading = tes.verdict(control, loaded)
    except (ValueError, KeyError) as exc:
        print(f"refused: {exc}", file=out)
        return 2
    reading["files"] = {
        name: {"file": str(path), "sha256": _sha256(path)}
        for name, path in paths.items()
    }
    reading["revision"] = revision()
    target = args.out if args.out is not None else args.control.parent / FILE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(reading, indent=2, allow_nan=True), encoding="utf-8")
    for line in reading["lines"]:
        print(line, file=out)
    print(f"wrote {target}", file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
