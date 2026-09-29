"""Read stage 3's decision-test payloads and print the registered verdicts.

    python -m backend.cli.market_stage3_verdict --dir ~/scratch/stage3_decisions \\
        --out docs/research/scorecards/stage3_verdicts.json

The directory holds the payloads the two decision tests write, by name:

* T-I (`market_fill_timing --stage3-forecast ...`): `ti_10.json`,
  `ti_16.json`, `ti_25.json` (cost runs), `ti_nextbar.json` (the
  `--next-bar` run), `ti_seed0.json`..`ti_seed4.json` (single-seed runs);
* T-S1 (`market_stage3_overlay`): `s1_<family>.json` (the ensemble at 10, 16
  and 25 bp) and `s1_<family>_seed0.json`..`_seed4.json`.

Missing files are reported, never guessed; a candidate whose runs are
incomplete is judged on what the verdict functions receive and fails the
criteria they cannot read (`stage3_verdict` fails closed). Every
candidate's excess moments feed the deflated Sharpe's trial variance.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from backend.market import stage3_io as io
from backend.market import stage3_verdict as sv

S1_FAMILIES = (io.LGBM, io.CNN_I5, io.CNN_I20, io.SEQ)


# The command-line parser.
def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    return parser


# A JSON payload, or None when the file is absent.
def _read(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text()) if path.exists() else None


# Gather the payloads, judge every candidate, print and optionally write.
def run(args: argparse.Namespace, out: TextIO = sys.stdout) -> int:
    """Print the verdicts; return 0 (the verdict is in the text, not the code)."""
    folder = args.dir
    missing: list[str] = []

    def need(name: str) -> dict[str, Any] | None:
        payload = _read(folder / name)
        if payload is None:
            missing.append(name)
        return payload

    ti_runs = [p for p in (need(f"ti_{c}.json") for c in (10, 16, 25)) if p is not None]
    ti_next = [p for p in (need("ti_nextbar.json"),) if p is not None]
    ti_seeds = [p for p in (need(f"ti_seed{s}.json") for s in io.SEEDS) if p is not None]
    s1_runs: dict[str, dict[str, Any]] = {}
    s1_seeds: dict[str, list[dict[str, Any]]] = {}
    for family in S1_FAMILIES:
        payload = need(f"s1_{family}.json")
        if payload is not None:
            s1_runs[family] = payload
            s1_seeds[family] = [p for p in (need(f"s1_{family}_seed{s}.json") for s in io.SEEDS) if p is not None]
    excess = sv.outer_excess(ti_runs=ti_runs, s1_runs=list(s1_runs.values()))
    record: dict[str, Any] = {"plan": io.PLAN, "missing": missing, "ti": None, "s1": {}}
    if ti_runs:
        verdict = sv.ti_verdict(ti_runs, next_bar=ti_next, seeds=ti_seeds, others=excess)
        record["ti"] = verdict
        print(verdict.get("text", json.dumps(verdict, default=str)[:2000]), file=out)
    for family, payload in s1_runs.items():
        verdict = sv.s1_verdict(payload, seeds=s1_seeds.get(family, []), others=excess)
        record["s1"][family] = verdict
        print(verdict.get("text", json.dumps(verdict, default=str)[:2000]), file=out)
    if missing:
        print(f"missing payloads: {', '.join(missing)}", file=out)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(io.clean_json(record), indent=2, sort_keys=True))
        print(f"wrote {args.out}", file=out)
    return 0


# Entry point.
def main(argv: list[str] | None = None) -> int:
    """Parse and run."""
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
