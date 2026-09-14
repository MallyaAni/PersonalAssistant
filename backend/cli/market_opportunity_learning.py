"""One bounded supervised comparison; frozen research artifacts, never live trades."""

import argparse
import hashlib
import json
import subprocess
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import sklearn
import torch
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits

from backend.agents.trading.desk.desk import book_panel
from backend.cli.market_growth_pilot import (
    fixed_chooser,
    portable_state,
    predict,
    resolve_device,
    return_network,
)
from backend.market import growth_pilot as gp
from backend.market import opportunity_learning as ol
from backend.market.store import MarketStore


# Fix a small model budget rather than searching the already examined test period.
def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--facts-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--asof", required=True)
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    return p


# Evaluate all predictions under identical twenty-session decisions and two cost levels.
def score(data, rows, predictions, cost=0.001):
    return gp.evaluate(data, rows, ol.chooser(data, predictions), cost, stride=20)


# Train one small network and choose among three epochs by validation net wealth.
def neural(data, x, y, train_mask, validation, device):
    torch.manual_seed(0)
    model = return_network(x.shape[-1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    tx = torch.tensor(x[train_mask], device=device)
    ty = torch.tensor(y[train_mask], dtype=torch.float32, device=device)
    best, state, chosen = -float("inf"), None, None
    observations = []
    for epoch in range(1, 16):
        for batch in torch.randperm(len(tx), device=device).split(2048):
            loss = torch.nn.functional.mse_loss(model(tx[batch]).squeeze(-1), ty[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        if epoch % 5 == 0:
            predicted = predict(model, x)
            net = score(data, validation, predicted)["metrics"]["log_growth"]
            observations.append({"epoch": epoch, "validation_log_growth": net})
            if net > best:
                best, state, chosen = net, portable_state(model), epoch
    model.load_state_dict(state)
    return model, {"selected_epoch": chosen, "checkpoints": observations}


# Train and replay a fixed ladder outside live accounts.
def main():
    args = parser().parse_args()
    device = resolve_device(args.device)
    torch.set_num_threads(2)
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    panel, _ = book_panel(MarketStore(args.data_dir), date.fromisoformat(args.asof))
    data, raw, names = ol.features(
        panel, MarketStore(args.facts_dir), date.fromisoformat(args.asof)
    )
    y = ol.labels(data.prices)
    train = gp.split_rows(data, "2018-01-01", "2024-01-01", horizon=21)[::5]
    validation = gp.split_rows(data, "2024-01-01", "2025-01-01", horizon=1)
    test = gp.split_rows(data, "2025-01-01", "2027-01-01", horizon=1)
    mask = np.zeros(data.eligible.shape, dtype=bool)
    mask[train] = data.eligible[train] & np.isfinite(y[train])
    if not mask.any() or not len(validation) or not len(test):
        raise ValueError(
            "Usable chronological training and evaluation partitions required"
        )
    x, fitted = ol.normalize(raw, raw[mask])
    np.savez_compressed(
        output / "inputs.npz",
        features=x,
        raw=raw,
        labels=y,
        dates=data.dates,
        prices=data.prices,
        eligible=data.eligible,
        market=data.market,
        medians=fitted[0],
        scale=fitted[1],
    )
    source = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    manifest = {
        "source": source,
        "arguments": vars(args),
        "feature_names": names,
        "feature_sha256": hashlib.sha256(x.tobytes()).hexdigest(),
        "price_sha256": hashlib.sha256(data.prices.tobytes()).hexdigest(),
        "tickers": list(data.tickers),
        "numpy": np.__version__,
        "sklearn": sklearn.__version__,
        "torch": torch.__version__,
        "train_examples": int(mask.sum()),
        "train_last_label": str(data.dates[train[-1] + 21]),
        "test_first": str(data.dates[test[0]]),
        "test_last": str(data.dates[test[-1] + 1]),
        "financial_coverage": float(
            np.isfinite(raw[test, :, 8])[data.eligible[test]].mean()
        ),
        "limitations": [
            "Current thematic membership; no delisting universe",
            "2025+ already examined; not an untouched holdout",
            "Filings delayed a day; share-count/split units need further audit",
            "No analyst consensus, release-text model or full adopted desk replay",
            "Fractional adjusted next-close execution; no spread history or settlement",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    models = {
        "ridge": Ridge(alpha=10),
        "trees": HistGradientBoostingRegressor(
            max_iter=100,
            max_leaf_nodes=15,
            l2_regularization=10,
            min_samples_leaf=100,
            learning_rate=0.05,
            early_stopping=False,
            random_state=0,
        ),
    }
    predictions, replay = {}, {}
    for name, model in models.items():
        model.fit(x[mask], y[mask])
        predictions[name] = model.predict(x.reshape(-1, x.shape[-1])).reshape(y.shape)
        joblib.dump(model, output / f"{name}.joblib")
        # Reload only artifacts written by this process, never external pickles.
        restored = joblib.load(output / f"{name}.joblib")
        replay[name] = restored.predict(x.reshape(-1, x.shape[-1])).reshape(y.shape)
    model, neural_info = neural(data, x, y, mask, validation, device)
    predictions["neural"] = predict(model, x)
    torch.save(portable_state(model), output / "neural.pt")
    restored = return_network(x.shape[-1]).to(device)
    restored.load_state_dict(
        torch.load(output / "neural.pt", weights_only=True, map_location=device)
    )
    replay["neural"] = predict(restored, x)
    # Fixed valuation rule comparator, not a calibrated forecast.
    predictions["valuation_rule"] = x[:, :, 8] + x[:, :, 9] + x[:, :, 12]
    validation_scores = {
        name: score(data, validation, pred)["metrics"]["log_growth"]
        for name, pred in predictions.items()
    }
    for name, action in (("momentum20", 1), ("momentum120", 3)):
        validation_scores[name] = gp.evaluate(
            data, validation, fixed_chooser(data, action), stride=20
        )["metrics"]["log_growth"]
    winner = max(validation_scores, key=validation_scores.get)
    results = {}
    for cost in (0.001, 0.003):
        for name, pred in predictions.items():
            result = score(data, test, pred, cost)
            results[f"{name}@{round(cost * 10000)}bps"] = result
            if name in replay:
                replayed = score(data, test, replay[name], cost)
                np.testing.assert_allclose(
                    replayed["nav"], result["nav"], rtol=0, atol=1e-10
                )
                assert replayed["decisions"] == result["decisions"]
        for name, chooser in (
            ("SPY", fixed_chooser(data, benchmark=True)),
            ("momentum20", fixed_chooser(data, 1)),
            ("momentum120", fixed_chooser(data, 3)),
            ("equal", fixed_chooser(data, 5)),
            ("USD", fixed_chooser(data, 0)),
        ):
            results[f"{name}@{round(cost * 10000)}bps"] = gp.evaluate(
                data, test, chooser, cost, stride=20
            )
    report = {
        "validation_log_growth": validation_scores,
        "validation_winner": winner,
        "neural_selection": neural_info,
        "verified_replay_curves": 6,
        "status": "research_only_not_promoted",
        "results": results,
    }
    (output / "results.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(
        json.dumps(
            {
                "validation_winner": winner,
                "financial_coverage": manifest["financial_coverage"],
                "metrics": {k: v["metrics"] for k, v in results.items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    with threadpool_limits(limits=2):
        main()
