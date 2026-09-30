"""Judge the universe-expansion arms against the control by the registered criteria.

    python -m backend.cli.universe_verdict --dir docs/research/scorecards/universe-expansion

Reads `control.json` and every `universe_<arm>.json` in the directory (the
`market_pit_scorecard --graded-cap 0.25` payloads of step 3), applies the
six criteria of `docs/research/universe-expansion-plan-2026-09-30.md`
(`backend/market/universe_verdict.py`), prints the verdict lines and the
sha256 of every payload, and writes `verdict.json` beside them. Pure
arithmetic on the files: the independent recomputation of the write-up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from backend.market import universe_verdict as uv

ARMS = ("sector", "flat", "tone")


# sha256 of a file's bytes, so a quoted number can be tied to its payload.
def digest(path: Path) -> str:
    """Return the hex sha256 of `path`."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Read, judge, print and write.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--dir", type=Path, default=Path("docs/research/scorecards/universe-expansion")
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args(argv)
    control_path = args.dir / "control.json"
    if not control_path.exists():
        print(f"no control payload at {control_path}")
        return 1
    control = json.loads(control_path.read_text(encoding="utf-8"))
    arms = {}
    digests = {"control": digest(control_path)}
    for arm in ARMS:
        path = args.dir / f"universe_{arm}.json"
        if path.exists():
            arms[arm] = json.loads(path.read_text(encoding="utf-8"))
            digests[arm] = digest(path)
    if not arms:
        print(f"no universe payloads in {args.dir}")
        return 1
    judged = uv.judge(control, arms)
    judged["payload_sha256"] = digests
    print(uv.render(judged))
    print("\npayload sha256:")
    for name, value in digests.items():
        print(f"  {name:8} {value}")
    target = args.output or args.dir / "verdict.json"
    target.write_text(json.dumps(judged, indent=2, allow_nan=True), encoding="utf-8")
    print(f"\nwrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
