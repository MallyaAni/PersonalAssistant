"""Train and replay conditional entry timing on local data and an optional GPU."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import fields
from pathlib import Path

import joblib
import numpy as np
import torch
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from threadpoolctl import threadpool_limits
from torch import nn

from backend.agents.trading.desk.desk import book_panel
from backend.market import entry_pilot as ep
from backend.market import intraday
from backend.market.store import MarketStore


# Expose a bounded training run or an exact replay of its own saved artifacts.
def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/market")
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    p.add_argument("--horizon", type=int, default=5)
    p.add_argument("--verify", action="store_true")
    return p


# Fingerprint the exact arrays, including their shapes and dtypes.
def digest(data):
    h = hashlib.sha256()
    for f in fields(data):
        a = np.asarray(getattr(data, f.name))
        h.update(f"{f.name}|{a.shape}|{a.dtype}".encode())
        h.update(a.tobytes())
    return h.hexdigest()


# Standardize from training observations only, leaving padded sequence slots zero.
def transform(data, train, fitted=None):
    valid = data.sequence[:, :, -1] > 0
    if fitted is None:
        values = data.sequence[train][valid[train]]
        fitted = {
            "xm": data.x[train].mean(axis=0),
            "xs": np.maximum(data.x[train].std(axis=0), 1e-5),
            "sm": values.mean(axis=0),
            "ss": np.maximum(values.std(axis=0), 1e-5),
            "ym": data.y[train].mean(axis=0),
            "ys": np.maximum(data.y[train].std(axis=0), 1e-5),
        }
    x = np.clip((data.x - fitted["xm"]) / fitted["xs"], -10, 10).astype("float32")
    seq = np.clip((data.sequence - fitted["sm"]) / fitted["ss"], -10, 10).astype(
        "float32"
    )
    seq[~valid] = 0
    y = ((data.y - fitted["ym"]) / fitted["ys"]).astype("float32")
    return x, seq, y, fitted


class TimingNetwork(nn.Module):
    """A small intraday sequence encoder conditioned on daily and setup context."""

    # Keep model capacity bounded and share the timing and holding-return trunk.
    def __init__(self, width):
        super().__init__()
        self.gru = nn.GRU(7, 32, batch_first=True)
        self.head = nn.Sequential(
            nn.Linear(width + 32, 64), nn.SiLU(), nn.Linear(64, 2)
        )

    # Read only the last observed bar; padded future slots never become context.
    def forward(self, x, seq, slot):
        encoded, _ = self.gru(seq)
        last = encoded[torch.arange(len(slot), device=slot.device), slot]
        return self.head(torch.cat((x, last), dim=-1))


# Infer in bounded batches and restore outputs to log-return percentage units.
def predict(model, x, seq, slots, fitted, device):
    out = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(x), 4096):
            sl = slice(start, start + 4096)
            prediction = model(
                torch.tensor(x[sl], device=device),
                torch.tensor(seq[sl], device=device),
                torch.tensor(slots[sl], device=device),
            )
            out.append(prediction.cpu().numpy())
    return np.concatenate(out) * fitted["ys"] + fitted["ym"]


# Train two prespecified seeds and select their ensemble checkpoint on validation NAV.
def train_networks(data, x, seq, y, fitted, train, validation, device, output):
    models, optimizers = [], []
    for seed in (0, 1):
        torch.manual_seed(seed)
        model = TimingNetwork(x.shape[1]).to(device)
        models.append(model)
        optimizers.append(torch.optim.AdamW(model.parameters(), lr=0.001))
    tx = torch.tensor(x[train], device=device)
    ts = torch.tensor(seq[train], device=device)
    ty = torch.tensor(y[train], device=device)
    tk = torch.tensor(data.slot[train], device=device)
    best, best_prediction, log = -np.inf, None, []
    for epoch in range(1, 13):
        for seed, (model, optimizer) in enumerate(zip(models, optimizers, strict=True)):
            torch.manual_seed(1000 * seed + epoch)
            model.train()
            for batch in torch.randperm(len(tx), device=device).split(2048):
                loss = nn.functional.huber_loss(
                    model(tx[batch], ts[batch], tk[batch]), ty[batch]
                )
                optimizer.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                optimizer.step()
        if epoch % 4 == 0:
            preds = np.mean(
                [predict(m, x, seq, data.slot, fitted, device) for m in models], axis=0
            )
            result = ep.evaluate(data, validation, ep.actions(preds), 10)
            score = result["net_return"]
            log.append({"epoch": epoch, "validation_net_return": score})
            print(f"GRU epoch {epoch}: validation net {score:+.3%}", flush=True)
            if score > best:
                best, best_prediction = score, preds
                for seed, model in enumerate(models):
                    torch.save(
                        {k: v.detach().cpu() for k, v in model.state_dict().items()},
                        output / f"gru-{seed}.pt",
                    )
                (output / "neural-selection.json").write_text(
                    json.dumps(
                        {
                            "epoch": epoch,
                            "validation_net_return": score,
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
    return best_prediction, log


# Price all methods over identical candidates with and without abstention.
def evaluate_all(data, predictions):
    results = {}
    for period, start, stop in (
        ("2025", "2025-01-01", "2026-01-01"),
        ("2026", "2026-01-01", "2027-01-01"),
        ("pooled", "2025-01-01", "2027-01-01"),
    ):
        mask = ep.split(data, start, stop, labelled=False)
        if not (mask & data.candidate).any():
            continue
        for cost in (10, 30):
            base = ep.evaluate(data, mask, np.zeros(len(data.x), dtype=int), cost)
            prefix = f"{period}@{cost}bps/"
            results[prefix + "enter"] = base
            results[prefix + "wait"] = ep.evaluate(
                data, mask, np.ones(len(data.x), dtype=int), cost
            )
            results[prefix + "cash"] = ep.evaluate(
                data, mask, np.full(len(data.x), 2, dtype=int), cost
            )
            for name, pred in predictions.items():
                for skip in (False, True):
                    action = ep.actions(pred, cost, skip)
                    result = ep.evaluate(data, mask, action, cost)
                    result["paired_vs_enter"] = ep.paired_interval(result, base)
                    mode = "skip" if skip else "timing"
                    results[prefix + name + "/" + mode] = result
    return results


# Reload only files created by this experiment and regenerate their forecasts.
def reload_predictions(data, output, device):
    fitted = dict(np.load(output / "normalization.npz", allow_pickle=False))
    x, seq, _, _ = transform(data, np.zeros(len(data.x), dtype=bool), fitted)
    pred = {}
    for name in ("ridge", "trees_basic", "trees_full"):
        model = joblib.load(output / f"{name}.joblib")
        inputs = x[:, : ep.BASIC] if name == "trees_basic" else x
        normalized = (
            np.column_stack([m.predict(inputs) for m in model])
            if isinstance(model, list)
            else model.predict(inputs)
        )
        pred[name] = normalized * fitted["ys"] + fitted["ym"]
    seeds = []
    for seed in (0, 1):
        model = TimingNetwork(x.shape[1]).to(device)
        model.load_state_dict(
            torch.load(
                output / f"gru-{seed}.pt", weights_only=True, map_location=device
            )
        )
        seeds.append(predict(model, x, seq, data.slot, fitted, device))
    pred["gru"] = np.mean(seeds, axis=0)
    return pred


# Check frozen inputs, reloaded model decisions and every saved account path.
def verify(output, device):
    saved = np.load(output / "dataset.npz", allow_pickle=False)
    data = ep.Dataset(**{k: saved[k] for k in saved.files})
    data.horizon = int(data.horizon)
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    if digest(data) != manifest["dataset_sha256"]:
        raise ValueError("Frozen dataset fingerprint mismatch")
    predictions = reload_predictions(data, output, device)
    reference = np.load(output / "predictions.npz", allow_pickle=False)
    for name, pred in predictions.items():
        np.testing.assert_allclose(pred, reference[name], rtol=1e-5, atol=1e-5)
    results = evaluate_all(data, predictions)
    original = json.loads((output / "results.json").read_text(encoding="utf-8"))
    for name, result in results.items():
        np.testing.assert_allclose(
            result["nav"], original[name]["nav"], rtol=0, atol=1e-10
        )
        if result["decisions"] != original[name]["decisions"]:
            raise ValueError(f"Replay decisions changed: {name}")
    print(
        f"VERIFIED: {len(results)} account paths and four reloaded models", flush=True
    )


# Execute the frozen protocol once without any production writes or external requests.
def main():
    args = parser().parse_args()
    if args.device == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("Requested CUDA device unavailable")
    torch.set_num_threads(4)
    if args.verify:
        with threadpool_limits(limits=4):
            verify(args.output, args.device)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    panel, _ = book_panel(MarketStore(args.data_dir))
    root = intraday.partition(Path(args.data_dir) / "bars_15m")
    data = ep.build(panel, root, args.horizon)
    train = ep.split(data, "2020-01-01", "2024-01-01")
    validation = ep.split(data, "2024-01-01", "2025-01-01", labelled=False)
    if train.sum() < 1000 or not (validation & data.candidate).any():
        raise ValueError("Insufficient chronological data")
    np.savez_compressed(
        args.output / "dataset.npz",
        **{f.name: getattr(data, f.name) for f in fields(data)},
    )
    # Prove the controls can execute before spending time fitting models.
    for start, stop in (("2024-01-01", "2025-01-01"), ("2025-01-01", "2027-01-01")):
        for a in (0, 1):
            ep.evaluate(
                data,
                ep.split(data, start, stop, labelled=False),
                np.full(len(data.x), a, dtype=int),
            )
    code_paths = [Path(__file__), Path(ep.__file__)]
    manifest = {
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "source_sha256": {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths
        },
        "dataset_sha256": digest(data),
        "features": ep.NAMES,
        "device": args.device,
        "gpu": torch.cuda.get_device_name(0) if args.device == "cuda" else None,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "data_end": str(panel.dates[-1]),
        "intraday_partition": str(root),
        "rows": len(data.x),
        "training_rows": int(train.sum()),
        "validation_rows": int(validation.sum()),
        "horizon": data.horizon,
        "limitations": [
            "Survivor universe",
            "Retrospective test years",
            "IEX bar-open fills, no impact or spread history",
            "Price-only fixed selection, not the production desk",
            "Zero cash interest; daily close drawdown only",
        ],
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(json.dumps(manifest), flush=True)
    x, seq, y, fitted = transform(data, train)
    np.savez(args.output / "normalization.npz", **fitted)
    predictions = {}
    with threadpool_limits(limits=4):
        ridge = Ridge(alpha=100).fit(x[train], y[train])
        joblib.dump(ridge, args.output / "ridge.joblib")
        predictions["ridge"] = ridge.predict(x) * fitted["ys"] + fitted["ym"]
        for name, width in (("trees_basic", ep.BASIC), ("trees_full", x.shape[1])):
            models = []
            for target in range(2):
                model = HistGradientBoostingRegressor(
                    max_iter=100,
                    max_leaf_nodes=15,
                    min_samples_leaf=100,
                    l2_regularization=10,
                    learning_rate=0.05,
                    early_stopping=False,
                    random_state=0,
                ).fit(x[train, :width], y[train, target])
                models.append(model)
            joblib.dump(models, args.output / f"{name}.joblib")
            predictions[name] = (
                np.column_stack([m.predict(x[:, :width]) for m in models])
                * fitted["ys"]
                + fitted["ym"]
            )
            print(f"Fitted {name}", flush=True)
    predictions["gru"], selection = train_networks(
        data, x, seq, y, fitted, train, validation, args.device, args.output
    )
    np.savez_compressed(args.output / "predictions.npz", **predictions)
    (args.output / "validation.json").write_text(
        json.dumps(selection, indent=2), encoding="utf-8"
    )
    results = evaluate_all(data, predictions)
    (args.output / "results.json").write_text(json.dumps(results), encoding="utf-8")
    summary = {
        k: {
            n: v
            for n, v in r.items()
            if n not in ("nav", "daily", "decisions", "dates")
        }
        for k, r in results.items()
    }
    (args.output / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    with threadpool_limits(limits=4):
        verify(args.output, args.device)
    for name, row in summary.items():
        if name.startswith("pooled@10bps"):
            print(f"{name}: net {row['net_return']:+.2%}, DD {row['max_drawdown']:.2%}")


if __name__ == "__main__":
    main()
