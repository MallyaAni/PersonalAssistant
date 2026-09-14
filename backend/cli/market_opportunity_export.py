"""Export the validation-selected neural model to a pickle-free NumPy bundle."""

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from threadpoolctl import threadpool_limits

from backend.cli.market_growth_pilot import predict as torch_predict
from backend.cli.market_growth_pilot import return_network
from backend.market import growth_pilot as gp
from backend.market.opportunity_shadow import predict


# Check inference and every historical basket before exporting frozen parameters.
def export(run, output):
    report = json.loads((run / "results.json").read_text())
    manifest = json.loads((run / "manifest.json").read_text())
    if report["validation_winner"] != "neural":
        raise ValueError("This export requires the validation-selected neural model")
    state = torch.load(run / "neural.pt", weights_only=True, map_location="cpu")
    with np.load(run / "inputs.npz", allow_pickle=False) as inputs:
        x, eligible = inputs["features"], inputs["eligible"]
        weights = {key: value.numpy() for key, value in state.items()}
        weights.update(
            medians=inputs["medians"],
            scale=inputs["scale"],
            tickers=np.array(manifest["tickers"]),
            feature_names=np.array(manifest["feature_names"]),
            training_source=np.array(manifest["source"]),
        )
    model = return_network(x.shape[-1])
    model.load_state_dict(state)
    expected, actual = torch_predict(model, x), predict(x, weights)
    np.testing.assert_allclose(actual, expected, rtol=1e-5, atol=1e-5)
    for t in range(len(x)):
        np.testing.assert_array_equal(
            gp.basket(expected[t], eligible[t] & (expected[t] > 0)),
            gp.basket(actual[t], eligible[t] & (actual[t] > 0)),
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        np.savez_compressed(stream, **weights)
    print(
        json.dumps(
            {
                "verified_baskets": len(x),
                "max_prediction_difference": float(np.max(np.abs(actual - expected))),
                "bundle": str(output),
            }
        )
    )


# Export only an explicitly named research run, without any retraining.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    torch.set_num_threads(2)
    with threadpool_limits(limits=2):
        export(args.run_dir, args.output)


if __name__ == "__main__":
    main()
