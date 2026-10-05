"""Replay saved numerical forecasts before independently checking carried ledgers."""

import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np

from next_session_entry import CLOCKS
from rule_relative_entry import CONFIG, FREEZE, numeric_predict, technical_prefix
from verify_carried_entry import main as audit_ledgers


# Require exact numeric readback and strictly matured next-session publications.
def main():
    with np.load("/prepared/prepared.npz", allow_pickle=False) as source:
        x = np.concatenate((source["X"], technical_prefix(source["current_close"])), axis=-1)
        dates, valid = source["dates"], source["valid"]
    with np.load("/output/models/predictions.npz", allow_pickle=False) as source:
        forecasts = source["predictions"]
        if not np.array_equal(dates, source["dates"]):
            raise ValueError("Forecast dates changed")
    fit = json.loads(Path("/output/models/fit.json").read_text())
    if fit["config"] != CONFIG or fit["clocks"] != list(CLOCKS):
        raise ValueError("Registered model parameters changed")
    months = dates.astype("datetime64[M]")
    expected = np.unique(months[dates >= np.datetime64("2018-02-01")]).astype(str).tolist()
    if [r["month"] for r in fit["receipts"]] != expected:
        raise ValueError("Missing or duplicate model publication")
    count = 0
    for row in fit["receipts"]:
        test = np.flatnonzero(months == np.datetime64(row["month"]))
        if np.datetime64(row["last_label_session"]) >= min(dates[test[0]], FREEZE):
            raise ValueError("Training label not matured before publication")
        path = Path("/output/models") / f"model-{row['month']}.npz"
        from hashlib import sha256
        if sha256(path.read_bytes()).hexdigest() != row["model_sha256"]:
            raise ValueError("Numeric model hash changed")
        day, clock, stock = np.nonzero(valid[test])
        with np.load(path, allow_pickle=False) as model:
            values = numeric_predict([model[f"tree{i}"] for i in range(CONFIG["max_iter"])],
                                     float(model["baseline"]), x[test[day], clock, stock])
        if not np.array_equal(values.astype(np.float32), forecasts[test[day], clock, stock]):
            raise ValueError("Saved predictions differ from numeric trees")
        count += len(values)
    stream = io.StringIO()
    with redirect_stdout(stream):
        audit_ledgers(forecasts, Path("/control"))
    proof = json.loads(stream.getvalue())
    proof["numeric_model_replay"] = {"months": len(expected), "predictions_checked": count}
    print(json.dumps(proof, indent=2))


if __name__ == "__main__":
    main()
