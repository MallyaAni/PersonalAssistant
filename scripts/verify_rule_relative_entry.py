"""Check numeric model publications and the new saved entry account ledgers."""

import hashlib
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import numpy as np
import verify_timing_side_ablation as ledger

from rule_relative_entry import CONFIG, FREEZE, numeric_predict, technical_prefix


# Authenticate every original fit publication and replay its saved numeric predictions.
def verify_models():
    output = Path("/output")
    identity = json.loads((output / "identity.json").read_text())
    for name, expected in identity["source"].items():
        if (
            hashlib.sha256((Path("/experiment") / name).read_bytes()).hexdigest()
            != expected
        ):
            raise ValueError("Producer source bytes changed")
    prepared = Path("/prepared/prepared.npz")
    if hashlib.sha256(prepared.read_bytes()).hexdigest() != identity["prepared_sha256"]:
        raise ValueError("Prepared source bytes changed")
    with np.load(prepared, allow_pickle=False) as original:
        x, dates, valid = original["X"], original["dates"], original["valid"]
        if identity.get("technical"):
            x = np.concatenate(
                (x, technical_prefix(original["current_close"])), axis=-1
            )
    with np.load(output / "models/predictions.npz", allow_pickle=False) as saved:
        predictions = saved["predictions"]
        if not np.array_equal(saved["dates"], dates):
            raise ValueError("Saved prediction dates changed")
    fit = json.loads((output / "models/fit.json").read_text())
    if fit["config"] != CONFIG or fit["clocks"] != [0, 3, 9, 19]:
        raise ValueError("Registered settings changed")
    months = dates.astype("datetime64[M]")
    expected = (
        np.unique(months[dates >= np.datetime64("2018-02-01")]).astype(str).tolist()
    )
    if [row["month"] for row in fit["receipts"]] != expected:
        raise ValueError("Missing or repeated monthly publications")
    count = 0
    for receipt in fit["receipts"]:
        if receipt["status"] != "fitted":
            raise ValueError("Incomplete monthly fit")
        test = np.flatnonzero(months == np.datetime64(receipt["month"], "M"))
        if np.datetime64(receipt["last_training_session"]) >= min(
            dates[test[0]], FREEZE
        ):
            raise ValueError("Training endpoint crosses publication boundary")
        path = output / f"models/model-{receipt['month']}.npz"
        if hashlib.sha256(path.read_bytes()).hexdigest() != receipt["model_sha256"]:
            raise ValueError("Saved model bytes changed")
        selected = (
            valid[test, :24]
            & np.isfinite(x[test, :24, :, 4])
            & (x[test, :24, :, 4] > 0)
        )
        day, clock, stock = np.nonzero(selected)
        with np.load(path, allow_pickle=False) as model:
            trees = [model[f"tree{i}"] for i in range(CONFIG["max_iter"])]
            replayed = numeric_predict(
                trees, float(model["baseline"]), x[test[day], clock, stock]
            ).astype(np.float32)
        if not np.array_equal(replayed, predictions[test[day], clock, stock, 0]):
            raise ValueError("Saved forecasts differ from numeric trees")
        count += len(replayed)
    return {"months": len(fit["receipts"]), "predictions_checked": count}


# Require model replay before the independent recorded-fill and daily-wealth audit.
def main():
    models = verify_models()
    path = Path("/output/models/predictions.npz")
    expected = hashlib.sha256(path.read_bytes()).hexdigest()
    stream = io.StringIO()
    with redirect_stdout(stream):
        ledger.main(path, expected, sides=("buy",))
    proof = json.loads(stream.getvalue())
    proof["numeric_model_replay"] = models
    print(json.dumps(proof, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
