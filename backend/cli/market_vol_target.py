"""The volatility-targeting verdict (B1): each target's payload against the control's.

    python -m backend.cli.market_vol_target \\
        --control docs/research/scorecards/vol-target/control.json \\
        --targets docs/research/scorecards/vol-target/vt_vt20.json \\
                  docs/research/scorecards/vol-target/vt_vt25.json \\
                  docs/research/scorecards/vol-target/vt_vt30.json \\
        --output docs/research/scorecards/vol-target/vol_target_verdict.json

Reads point-in-time scorecard payloads written by `market_pit_scorecard`
(the control at gross 1 and one per `--gross-target`), pairs each target's
rule line with the control's session by session at the median offset and
prints the registered verdict lines (`vol_target.verdict`): per window the
median worst drawdown and CAGR against the control, the Sharpe, the paired
daily difference's Newey-West t at lag 20, the offsets above the control,
the deflated Sharpe at the cumulative 474 (reported), and REPLACES or
RECORD exactly as the plan fixes them. The deflated Sharpe's trial variance
is the across-target variance of the registered targets' paired Sharpes.
Writes the verdict file; `docs/research/scorecards/vol-target/
vol_target_check.py` recomputes its numbers from the payload curves.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.market import vol_target


# Read a payload; NaN comes back as NaN (the scorecard writes it so).
def _load(path: Path) -> dict:
    """Return the JSON payload at `path`."""
    return json.loads(path.read_text(encoding="utf-8"))


# Pair every target with the control and assemble the verdict record.
def build(control: dict, targets: dict[str, dict]) -> dict:
    """Return {"control", "trials", "trial_variance", "targets": {tag: verdict}}."""
    variance = vol_target.trial_variance(targets, control)
    out = {
        "plan": vol_target.PLAN,
        "study": vol_target.STUDY,
        "trials": vol_target.TRIALS,
        "trial_variance": variance,
        "cost_bps": vol_target.COST_BPS,
        "control": {
            "arm": control.get("arm"),
            "asof": control.get("asof"),
            "offsets": control.get("offsets"),
            "membership": control.get("membership"),
        },
        "targets": {},
    }
    for tag, payload in targets.items():
        out["targets"][tag] = vol_target.verdict(payload, control, variance)
    return out


# The verdict as text: the header, then every target's registered lines.
def render(record: dict) -> str:
    """Return the verdict lines."""
    lines = [
        f"volatility target (B1) against {record['control']['arm']} as of "
        f"{record['control']['asof']}, {record['control']['offsets']} offsets, "
        f"{record['cost_bps']:g} bp; trials {record['trials']['cumulative']} "
        f"cumulative, trial variance {record['trial_variance']:.4f}"
    ]
    for reading in record["targets"].values():
        lines.extend(reading["lines"])
    return "\n".join(lines)


# Read the payloads, pair, write, print.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--control", type=Path, required=True)
    parser.add_argument("--targets", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/scorecards/vol-target/vol_target_verdict.json"),
    )
    args = parser.parse_args(argv)
    control = _load(args.control)
    targets = {}
    for path in args.targets:
        payload = _load(path)
        tag = payload.get("vol_target", {}).get("tag") or path.stem
        if tag in targets:
            parser.error(f"two payloads carry the tag {tag!r}")
        targets[tag] = payload
    record = build(control, targets)
    record["sources"] = {
        "control": str(args.control),
        "targets": {tag: str(p) for tag, p in zip(targets, args.targets, strict=True)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(record, indent=2, allow_nan=True), encoding="utf-8"
    )
    print(render(record))
    print(f"\nwrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
