"""Run the predeclared retrospective study once, without network or account writes."""

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import numpy as np
import sklearn
from threadpoolctl import threadpool_limits

from backend.market import learned_research as study
from backend.market.panel import panel_from_histories
from backend.market.store import MarketStore


# Parse only data locations; the experiment's dates and policies stay fixed.
def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--data-dir", required=True)
    result.add_argument("--output", required=True)
    return result


# Load the declared current cohort and exactly one already-stored price vintage.
def load_snapshot(root):
    root = Path(root)
    asof = date(2026, 9, 23)
    record_path = root / "desk" / f"asof={asof}" / "desk.json"
    record = json.loads(record_path.read_text())
    names = tuple(sorted(set(record["grades"]) | {"SPY", "QQQ"}))
    store = MarketStore(root)
    histories, hashes = (
        {},
        {str(record_path): hashlib.sha256(record_path.read_bytes()).hexdigest()},
    )
    for name in names:
        if store.latest_asof(name, asof) != asof:
            raise ValueError(f"{name} has no exact declared source vintage")
        history = store.read(name, asof)
        days = tuple(bar.session_date for bar in history.bars)
        if len(set(days)) != len(days) or list(days) != sorted(days):
            raise ValueError(f"ambiguous source calendar for {name}")
        if history.complete_through < asof or any(day > asof for day in days):
            raise ValueError(f"incomplete or future source for {name}")
        histories[name] = history
        path = root / "bars" / f"asof={asof}" / f"{name}.parquet"
        hashes[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    spy_dates = tuple(bar.session_date for bar in histories["SPY"].bars)
    panel = panel_from_histories(histories, "SPY", {}, start=spy_dates[0])
    if tuple(value.astype(date) for value in panel.dates) != spy_dates:
        raise ValueError("source calendar differs from SPY sessions")
    return panel, hashes


# Save one deterministic report and its frozen inputs before inspecting results.
def main():
    args = parser().parse_args()
    if subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], text=True
    ).strip():
        raise ValueError("commit the reviewed source before the outcome run")
    panel, hashes = load_snapshot(args.data_dir)
    data = study.prepare(panel)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    np.savez_compressed(
        output / "inputs.npz",
        dates=panel.dates,
        tickers=np.asarray(panel.tickers),
        open=panel.open,
        high=panel.high,
        low=panel.low,
        close=panel.close,
        adjusted_close=panel.adj_close,
        features=data.inputs.features,
        eligible=data.eligible,
        market=data.market,
    )
    protocol = Path("docs/research/learned-price-protocol-2026-09-24.md")
    manifest = {
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "protocol_sha256": hashlib.sha256(protocol.read_bytes()).hexdigest(),
        "input_hashes": hashes,
        "snapshot": "2026-09-23",
        "holdout": str(study.HOLDOUT),
        "numpy": np.__version__,
        "sklearn": sklearn.__version__,
        "tickers": list(panel.tickers),
        "evidence_basis": "retrospective-price",
        "adoption_eligible": False,
        "limitations": [
            "Current cohort; historical membership and delisted outcomes absent",
            "Retrospective adjusted data; live grades and tone not reconstructed",
            "Holdout dates appeared in prior research; not pristine unseen data",
            "Close-sized next-open proxy; no midpoint fills or personal account",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {
                "event": "inputs_frozen",
                "rows": len(panel.dates),
                "names": len(panel.tickers),
            }
        ),
        flush=True,
    )
    with threadpool_limits(limits=4):
        rank, brake, first = study.fit(data)
    np.savez_compressed(
        output / "forecasts.npz",
        rank=rank.values,
        brake=brake.values,
        rank_fit=rank.fit_session,
        brake_fit=brake.fit_session,
    )
    (output / "fits.json").write_text(
        json.dumps({"rank": rank.model_hash, "brake": brake.model_hash}, indent=2)
    )
    report = {
        "manifest": manifest,
        "actual_first": str(panel.dates[first]),
        "actual_last": str(panel.dates[-1]),
        "policies": {},
        "full_live_incumbent": {
            "available": False,
            "reason": "historical grades, tone and entry states unavailable",
        },
    }
    for cost in (10, 25):
        paths = {}
        for policy in study.POLICIES:
            key = f"{policy}@{cost}bp"
            try:
                path = study.replay(data, rank, brake, first, policy, cost)
                paths[policy] = path
                report["policies"][key] = {
                    "full": study.metrics(path),
                    "2016-2020": study.metrics(path, "2016-01-04", "2021-01-01"),
                    "2021-2026": study.metrics(path, "2021-01-01"),
                    "holdout": study.metrics(path, str(study.HOLDOUT)),
                    "decision_count": len(path["decisions"]),
                }
                np.savez_compressed(
                    output / f"{key}.npz",
                    dates=path["dates"],
                    nav=path["nav"],
                    turnover=path["turnover"],
                    cash=path["cash"],
                )
            except ValueError as error:
                report["policies"][key] = {"available": False, "reason": str(error)}
        for policy, path in paths.items():
            report["policies"][f"{policy}@{cost}bp"]["rolling"] = {
                name: study.rolling_wins(path, paths[name])
                if name in paths
                else {
                    "windows": 0,
                    "win_fraction": None,
                    "reason": "control unavailable",
                }
                for name in ("SPY", "QQQ")
            }
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(
        json.dumps(
            {
                "event": "complete",
                "first": report["actual_first"],
                "output": str(output),
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
