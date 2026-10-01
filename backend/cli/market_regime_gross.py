"""The regime-gross verdict (B2): each pair's payload against two controls.

    python -m backend.cli.market_regime_gross \\
        --control docs/research/scorecards/vol-target/control.json \\
        --vol-target-verdict \\
            docs/research/scorecards/vol-target/vol_target_verdict.json \\
        --candidates docs/research/scorecards/regime-gross/rg_rg30_g50.json \\
                     docs/research/scorecards/regime-gross/rg_rg50_g50.json \\
                     docs/research/scorecards/regime-gross/rg_rg50_g00.json \\
                     docs/research/scorecards/regime-gross/rg_rg50_g50_vt25.json \\
        --output docs/research/scorecards/regime-gross/regime_gross_verdict.json

Reads point-in-time scorecard payloads written by `market_pit_scorecard`:
the gross-1 control, the best registered B1 target (chosen from B1's
verdict file by `regime_gross.best_registered`, its payload read from that
file's `sources`, or named outright with `--vol-target PATH`), and one
payload per `--gross-regime` pair. Each pair is paired with both controls
session by session at the median offset through B1's verdict
(`vol_target.verdict`) and labelled as the plan fixes it
(`regime_gross.verdict`): REPLACES only when it clears both; RECORD (does
not beat the vol target) when it clears the control alone; RECORD
otherwise; the combination with B1's target is REPORTED. The deflated
Sharpe's trial variance is the across-pair variance of the registered
pairs' paired Sharpes against the control. Writes the verdict file;
`docs/research/scorecards/regime-gross/regime_gross_check.py` recomputes
its numbers from the payload curves.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.market import regime_gross, vol_target


# Read a payload; NaN comes back as NaN (the scorecard writes it so).
def _load(path: Path) -> dict:
    """Return the JSON payload at `path`."""
    return json.loads(path.read_text(encoding="utf-8"))


# The best registered B1 target's payload path from B1's verdict file.
def vol_target_from_verdict(path: Path) -> tuple[str, Path]:
    """Return (tag, payload path) of the best registered target."""
    record = _load(path)
    tag = regime_gross.best_registered(record)
    source = record.get("sources", {}).get("targets", {}).get(tag)
    if source is None:
        raise KeyError(f"B1's verdict names no source payload for {tag!r}")
    candidate = Path(source)
    if not candidate.is_absolute() and not candidate.exists():
        # A source written relative to the repository root, read from elsewhere.
        candidate = path.parent / candidate.name
    return tag, candidate


# Pair every candidate with both controls and assemble the verdict record.
def build(control: dict, vol_target_payload: dict, candidates: dict[str, dict]) -> dict:
    """Return the verdict record for every candidate."""
    variance = regime_gross.trial_variance(candidates, control)
    out = {
        "plan": regime_gross.PLAN,
        "study": regime_gross.STUDY,
        "trials": regime_gross.TRIALS,
        "trial_variance": variance,
        "cost_bps": vol_target.COST_BPS,
        "control": {
            "arm": control.get("arm"),
            "asof": control.get("asof"),
            "offsets": control.get("offsets"),
            "membership": control.get("membership"),
        },
        "vol_target": {
            "arm": vol_target_payload.get("arm"),
            "asof": vol_target_payload.get("asof"),
            "tag": vol_target_payload.get("vol_target", {}).get("tag"),
            "spec": vol_target_payload.get("vol_target", {}),
        },
        "candidates": {},
    }
    for tag, payload in candidates.items():
        out["candidates"][tag] = regime_gross.verdict(
            payload, control, vol_target_payload, variance
        )
    return out


# The verdict as text: the header, then every candidate's lines.
def render(record: dict) -> str:
    """Return the verdict lines."""
    lines = [
        f"regime gross (B2) against {record['control']['arm']} and "
        f"{record['vol_target']['tag']} as of {record['control']['asof']}, "
        f"{record['control']['offsets']} offsets, {record['cost_bps']:g} bp; "
        f"trials {record['trials']['cumulative']} cumulative, trial variance "
        f"{record['trial_variance']:.4f}"
    ]
    for reading in record["candidates"].values():
        lines.extend(reading["lines"])
    return "\n".join(lines)


# Read the payloads, pair, write, print.
def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--control", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--vol-target-verdict",
        type=Path,
        help="B1's verdict file; the best registered target is read from it",
    )
    group.add_argument("--vol-target", type=Path, help="B1's best target's payload")
    parser.add_argument("--candidates", type=Path, nargs="+", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/research/scorecards/regime-gross/regime_gross_verdict.json"),
    )
    args = parser.parse_args(argv)
    control = _load(args.control)
    if args.vol_target is not None:
        vt_path = args.vol_target
    else:
        _, vt_path = vol_target_from_verdict(args.vol_target_verdict)
    vt_payload = _load(vt_path)
    if not vt_payload.get("vol_target", {}).get("registered"):
        parser.error(f"{vt_path} is not a registered B1 target's payload")
    if vt_payload.get("asof") != control.get("asof"):
        parser.error("the control and the vol target are not as of the same session")
    candidates = {}
    for path in args.candidates:
        payload = _load(path)
        tag = payload.get(regime_gross.KEY, {}).get("tag") or path.stem
        if tag in candidates:
            parser.error(f"two payloads carry the tag {tag!r}")
        if payload.get("asof") != control.get("asof"):
            parser.error(f"{path} is not as of the control's session")
        candidates[tag] = payload
    record = build(control, vt_payload, candidates)
    record["sources"] = {
        "control": str(args.control),
        "vol_target": str(vt_path),
        "vol_target_verdict": (
            None if args.vol_target_verdict is None else str(args.vol_target_verdict)
        ),
        "candidates": {
            tag: str(p) for tag, p in zip(candidates, args.candidates, strict=True)
        },
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
