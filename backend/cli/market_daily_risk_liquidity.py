"""Fit and score daily risk/volume models from existing SIP cubes, read-only inputs.

python -m backend.cli.market_daily_risk_liquidity --cubes-dir <sip_cubes> \
    --out-dir <new-research-directory> [--paper-state <state.json>]
No network requests, cache rebuilds, serving changes or trade execution.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import point_in_time
from backend.market import daily_risk_liquidity as study
from backend.market import liquidity_relevance, universe
from backend.market.calendar import reviewed_sessions
from backend.market.sip_cube import CUBE_VERSION, SessionCube
from backend.market.stage3_io import clean_json


# Fingerprint input bytes, including legacy caches without upgrading their provenance.
def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# Read cached cubes directly without refreshing or writing into the production store.
def load_cubes(directory: Path) -> tuple[dict[str, SessionCube], dict]:
    cubes, manifest = {}, {}
    fields = (
        "dates",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "prior_close",
        "auction_open",
        "auction_volume",
    )
    for path in sorted(directory.glob("*.npz")):
        before = sha256(path)
        with np.load(path, allow_pickle=False) as data:
            if int(data["key"][-1]) != CUBE_VERSION or str(data["ticker"]) != path.stem:
                raise ValueError(f"unsupported cube identity/version: {path.name}")
            arrays = {key: data[key].copy() for key in fields}
            excluded = dict(
                zip(
                    data["excluded_reasons"].astype(str).tolist(),
                    data["excluded_counts"].astype(int).tolist(),
                    strict=True,
                )
            )
        if sha256(path) != before:
            raise ValueError(f"cube changed during read: {path.name}")
        if len(arrays["dates"]):
            cubes[path.stem] = SessionCube(
                ticker=path.stem, excluded=excluded, **arrays
            )
        manifest[path.name] = {
            "sha256": before,
            "rows": len(arrays["dates"]),
            "excluded": excluded,
        }
    if not cubes:
        raise ValueError("no nonempty SIP cubes")
    return cubes, manifest


# Refuse accidental reuse of a results directory or writes into the input store.
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cubes-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument(
        "--membership", type=Path, default=universe.MEMBERSHIP_HISTORY_PATH
    )
    parser.add_argument("--paper-state", type=Path)
    parser.add_argument(
        "--cnn-forecast",
        type=Path,
        help="existing archive; comparison only, no provenance upgrade",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="short synthetic-like run; never registered results",
    )
    return parser


# Check locations before any expensive work or output creation.
def check_locations(args: argparse.Namespace) -> tuple[Path, Path]:
    out = args.out_dir.resolve()
    inputs = args.cubes_dir.resolve()
    if out.exists() or out == inputs or inputs in out.parents:
        raise ValueError("output must be a new directory outside the cube inputs")
    if not args.membership.is_file():
        raise ValueError("membership history is required")
    return out, inputs


# Compare archived CNN forecasts on common rows without upgrading old provenance.
def compare_cnn(path: Path, ds: study.Dataset, predictions: dict) -> dict:
    from backend.market.vol_forecast import load_forecasts

    archive = load_forecasts(path)
    lookup = {
        (str(d), str(t)): i
        for i, (d, t) in enumerate(zip(archive.dates, archive.tickers, strict=True))
    }
    cnn = np.array(
        [
            archive.forecast[lookup[(str(d), str(t))]]
            if (str(d), str(t)) in lookup
            else np.nan
            for d, t in zip(ds.dates, ds.tickers, strict=True)
        ]
    )
    rows = []
    for window, (start, end) in study.WINDOWS.items():
        good = (ds.dates >= np.datetime64(start)) & (ds.dates < np.datetime64(end))
        good &= np.isfinite(cnn) & np.isfinite(ds.y[:, 0]) & (ds.y[:, 0] > 0)
        good &= np.isfinite(predictions["raw_log"][:, 0]).all(axis=1)
        if not good.any():
            continue
        truth = np.log(ds.y[good, 0])
        errors = {
            name: float(np.mean((predictions["raw_log"][good, 0, j] - truth) ** 2))
            for j, name in enumerate(study.MODELS)
        }
        errors["archived_cnn"] = float(np.mean((cnn[good] - truth) ** 2))
        rows.append(
            {"window": window, "common_rows": int(good.sum()), "log_mse": errors}
        )
    return {
        "sha256": sha256(path),
        "row_selection": archive.row_selection,
        "archive_requalified": False,
        "target": study.TARGETS[0],
        "rows": rows,
        "note": "CNN was not retrained on revised rows; diagnostic comparison only.",
    }


# Execute the frozen study and retain predictions, hashes, partitions and strict JSON.
def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    out, inputs = check_locations(args)
    began = time.perf_counter()

    # Print bounded progress while long fits run on the research CPU.
    def log(message: str) -> None:
        print(f"[{time.perf_counter() - began:.1f}s] {message}", flush=True)

    cubes, manifest = load_cubes(inputs)
    years, calendar = reviewed_sessions()
    cube_years = {
        int(str(day)[:4])
        for cube in cubes.values()
        for day in (cube.dates[0], cube.dates[-1])
    }
    if not cube_years <= years:
        raise ValueError("cube dates extend outside the reviewed calendar")
    membership_hash = sha256(args.membership)

    # Apply dated membership; context ETFs never become training targets.
    def membership(dates: np.ndarray, tickers: tuple[str, ...]) -> np.ndarray:
        return point_in_time.eligibility(dates, tickers, args.membership)

    ds = study.build_dataset(cubes, membership, calendar)
    if sha256(args.membership) != membership_hash:
        raise ValueError("membership changed during dataset build")
    config = study.Config()
    if args.smoke:
        config = study.Config(
            min_train=80, validation=20, refit=100000, trees=5, patience=2
        )
    log(
        f"dataset: {len(ds.dates)} rows, {len(ds.sessions)} sessions, "
        f"{len(set(ds.tickers))} names"
    )
    predictions = study.forecast(ds, config, log)
    scores = study.score(ds, predictions)
    source = Path(__file__).resolve().parents[2]
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain", "--", "backend"],
        cwd=source,
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()
    payload = {
        "study": "daily-risk-liquidity/1",
        "source_revision": head,
        "source_dirty": bool(dirty),
        "registered_config": not args.smoke,
        "config": asdict(config),
        "coverage": ds.coverage,
        "feature_names": ds.feature_names,
        "inputs": manifest,
        "membership_sha256": membership_hash,
        "scores": scores,
        "fits": predictions["fits"],
        "verdict": study.verdict(scores),
        "limitations": [
            "Reused historical sample; not an untouched test set.",
            "Dated membership does not restore missing delisted-stock prices.",
            "Input hashes establish reproducibility, not historical data availability.",
            "RTH full-session cubes exclude early closes and the closing auction.",
            "Gap proxy is not continuous overnight/pre/postmarket realized variance.",
            "No strategy change or portfolio-return claim.",
        ],
        "source_hashes": {
            name: sha256(source / name)
            for name in (
                "backend/market/daily_risk_liquidity.py",
                "backend/market/liquidity_relevance.py",
                "backend/cli/market_daily_risk_liquidity.py",
            )
        },
    }
    if args.cnn_forecast:
        payload["cnn_comparison"] = compare_cnn(args.cnn_forecast, ds, predictions)
    if args.paper_state:
        # Read one immutable in-memory snapshot; never preserve account identifiers.
        raw = args.paper_state.read_bytes()
        payload["paper_state_sha256"] = hashlib.sha256(raw).hexdigest()
        payload["execution_relevance"] = liquidity_relevance.evaluate(
            json.loads(raw), ds, predictions
        )
    out.mkdir(parents=True, exist_ok=False)
    artifact = out / "predictions.npz"
    np.savez_compressed(
        artifact,
        dates=ds.dates,
        tickers=ds.tickers,
        y=ds.y,
        baseline=ds.baseline,
        seasonal_volume=ds.seasonal_volume,
        session_index=ds.session_index,
        label_end=ds.label_end,
        feature_names=np.asarray(ds.feature_names),
        x=ds.x,
        point=predictions["point"],
        raw_log=predictions["raw_log"],
        interval=predictions["interval"],
        baseline_interval=predictions["baseline_interval"],
        regime=predictions["regime"],
    )
    payload["predictions_sha256"] = sha256(artifact)
    payload["seconds"] = time.perf_counter() - began
    (out / "results.json").write_text(
        json.dumps(clean_json(payload), indent=2, allow_nan=False), encoding="utf-8"
    )
    for row in scores:
        if row["regime"] == -1 and row["model"] == "lightgbm":
            log(
                f"{row['window']} {row['target']}: "
                f"skill vs best simple {row['skill_vs_best_simple']:+.2%}, "
                f"interval coverage {row['interval_coverage']:.1%}"
            )
    log(json.dumps(payload["verdict"]))
    log(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
