"""Train explicitly selected CPU/CUDA neural and sequential RL challengers.

This is a price/calendar pilot, not a replay of the full adopted desk. It uses
today's book membership, adjusted total-return prices, fractional research
units and next-close execution. It cannot establish investable superiority.
No API calls, broker changes or production configuration changes occur.
CPU remains the default; CUDA is opt-in and must be available.
"""

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path

import numpy as np
import torch
from torch import nn

from backend.agents.trading.desk.desk import book_panel
from backend.market import growth_pilot as gp
from backend.market.store import MarketStore


# Keep every training choice in a reproducible, explicit research invocation.
def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--asof", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--epochs", type=int, default=15)
    p.add_argument("--episodes", type=int, default=120)
    p.add_argument("--verify", action="store_true")
    p.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    return p


# Refuse an unavailable accelerator rather than silently changing the experiment.
def resolve_device(name):
    if name not in ("cpu", "cuda"):
        raise ValueError("Device must be cpu or cuda")
    if name == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA requested but unavailable")
    return torch.device(name)


# Preserve portable weights independently of the device used for optimization.
def portable_state(model):
    return {
        name: value.detach().cpu().clone() for name, value in model.state_dict().items()
    }


# Run inference on the network's explicit device and return NumPy accounting inputs.
def predict(model, values):
    device = next(model.parameters()).device
    with torch.no_grad():
        return (
            model(torch.as_tensor(values, dtype=torch.float32, device=device))
            .squeeze(-1)
            .cpu()
            .numpy()
        )


# Fit feature normalization exclusively on the requested training observations.
def normalization(values):
    return values.mean(axis=0), np.maximum(values.std(axis=0), 1e-5)


# Use the identical network shape for training and frozen-artifact replay.
def return_network(width):
    return nn.Sequential(
        nn.Linear(width, 32), nn.Tanh(), nn.Linear(32, 16), nn.Tanh(), nn.Linear(16, 1)
    )


# Fit a small stock-return network; select its epoch using 2024 labels only.
def neural(data, train, validation, seed, epochs, output, device="cpu"):
    device = resolve_device(str(device))
    torch.manual_seed(seed)
    labels = np.full(data.prices.shape, np.nan)
    with np.errstate(all="ignore"):
        labels[:-5] = 100 * np.log(data.prices[5:] / data.prices[1:-4])
    train_ok = data.eligible[train] & np.isfinite(labels[train])
    val_ok = data.eligible[validation] & np.isfinite(labels[validation])
    raw = data.features[train][train_ok]
    mean, scale = normalization(raw)
    x = torch.tensor(
        np.clip((raw - mean) / scale, -5, 5), dtype=torch.float32, device=device
    )
    y = torch.tensor(labels[train][train_ok], dtype=torch.float32, device=device)
    vx = torch.tensor(
        np.clip((data.features[validation][val_ok] - mean) / scale, -5, 5),
        dtype=torch.float32,
        device=device,
    )
    vy = torch.tensor(labels[validation][val_ok], dtype=torch.float32, device=device)
    model = return_network(x.shape[1]).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.001, weight_decay=0.001)
    best, best_state, best_epoch = float("inf"), None, None
    for epoch in range(epochs):
        for batch in torch.randperm(len(x), device=device).split(2048):
            loss = nn.functional.mse_loss(model(x[batch]).squeeze(-1), y[batch])
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
        with torch.no_grad():
            score = float(nn.functional.mse_loss(model(vx).squeeze(-1), vy))
        if score < best:
            best, best_state, best_epoch = (
                score,
                portable_state(model),
                epoch + 1,
            )
    model.load_state_dict(best_state)
    model.eval()
    transformed = np.nan_to_num(np.clip((data.features - mean) / scale, -5, 5))
    predicted = predict(model, transformed)
    torch.save(
        {"state": best_state, "mean": mean.tolist(), "scale": scale.tolist()},
        output / f"neural-{seed}.pt",
    )
    return predicted, {
        "validation_mse_percent_squared": best,
        "selected_epoch": best_epoch,
        "train_examples": int(len(x)),
        "validation_examples": int(len(vx)),
    }


class Allocator(nn.Module):
    # Learn action probabilities and a state-value baseline for sequential returns.
    def __init__(self, width):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(width, 32), nn.Tanh())
        self.actor = nn.Linear(32, len(gp.ACTION_NAMES))
        self.critic = nn.Linear(32, 1)

    # Share the market/account representation between policy and value estimates.
    def forward(self, state):
        hidden = self.body(state)
        return self.actor(hidden), self.critic(hidden).squeeze(-1)


# Produce an evaluation chooser using only the current observation and holdings.
def rl_chooser(data, model, mean, scale):
    # Choose a deterministic action from the frozen learned policy.
    def choose(t, holdings, cash):
        state = gp.policy_state(data, t, holdings, cash, mean, scale)
        with torch.no_grad():
            logits, _ = model(
                torch.tensor(state, device=next(model.parameters()).device)
            )
        action = int(logits.argmax())
        return gp.actions(data, t)[action], gp.ACTION_NAMES[action]

    return choose


# Train genuine sampled-action policy gradients with undiscounted net log wealth.
def reinforcement(data, train, validation, seed, episodes, output, device="cpu"):
    device = resolve_device(str(device))
    torch.manual_seed(seed)
    rng = np.random.default_rng(seed)
    mean, scale = normalization(data.market[train])
    model = Allocator(data.market.shape[1] + 1 + len(gp.ACTION_NAMES)).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)
    best, best_state, best_episode = -float("inf"), None, None
    episode_steps = 26
    starts = train[train + 5 * episode_steps <= train[-1]]
    if not len(starts):
        raise ValueError("Insufficient sequential training history")
    for episode in range(episodes):
        first = int(rng.choice(starts))
        holdings, cash = np.zeros(data.prices.shape[1]), 1.0
        logps, values, rewards = [], [], []
        for t in range(first, first + 5 * episode_steps, 5):
            state = torch.tensor(
                gp.policy_state(data, t, holdings, cash, mean, scale), device=device
            )
            logits, value = model(state)
            distribution = torch.distributions.Categorical(logits=logits)
            action = distribution.sample()
            target = gp.actions(data, t)[int(action)]
            holdings, cash, _, reward, _ = gp.transition(
                data, t, t + 5, holdings, cash, target, 0.001
            )
            logps.append(distribution.log_prob(action))
            values.append(value)
            rewards.append(100 * reward)
        returns = torch.tensor(
            np.cumsum(rewards[::-1])[::-1].copy(), dtype=torch.float32, device=device
        )
        values = torch.stack(values)
        advantage = returns - values.detach()
        loss = -(torch.stack(logps) * advantage).mean() + 0.5 * nn.functional.mse_loss(
            values, returns
        )
        optimizer.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if (episode + 1) % 20 == 0 or episode + 1 == episodes:
            score = gp.evaluate(data, validation, rl_chooser(data, model, mean, scale))[
                "metrics"
            ]["log_growth"]
            print(
                f"RL seed={seed} episode={episode + 1} "
                f"validation_log_growth={score:.5f}",
                flush=True,
            )
            if score > best:
                best, best_state, best_episode = (
                    score,
                    portable_state(model),
                    episode + 1,
                )
    model.load_state_dict(best_state)
    model.eval()
    torch.save(
        {"state": best_state, "mean": mean.tolist(), "scale": scale.tolist()},
        output / f"rl-{seed}.pt",
    )
    return rl_chooser(data, model, mean, scale), {
        "validation_log_growth": best,
        "selected_episode": best_episode,
    }


# Keep baseline construction identical between every cost and regime comparison.
def fixed_chooser(data, action=None, predictions=None, benchmark=False):
    # Select a fixed basket or predicted positive-return names on the current date.
    def choose(t, holdings, cash):
        if benchmark:
            weights = np.zeros(data.prices.shape[1])
            weights[data.benchmark] = 1
            return weights, "SPY"
        if predictions is not None:
            mask = data.eligible[t] & (predictions[t] > 0)
            return gp.basket(predictions[t], mask), "neural_positive_top10"
        return gp.actions(data, t)[action], gp.ACTION_NAMES[action]

    return choose


# Prove saved models reproduce every recorded learned-policy account curve.
def verify_artifacts(data, test, output, device="cpu"):
    device = resolve_device(str(device))
    manifest = json.loads((output / "manifest.json").read_text())
    recorded = json.loads((output / "results.json").read_text())["results"]
    for name, values in (("price", data.prices), ("feature", data.features)):
        if hashlib.sha256(values.tobytes()).hexdigest() != manifest[f"{name}_sha256"]:
            raise ValueError("Input snapshot differs from the training record")
    checked = 0
    for seed in range(manifest["arguments"]["seeds"]):
        for kind in ("neural", "rl"):
            saved = torch.load(
                output / f"{kind}-{seed}.pt", weights_only=True, map_location="cpu"
            )
            mean, scale = np.asarray(saved["mean"]), np.asarray(saved["scale"])
            if kind == "neural":
                model = return_network(data.features.shape[-1]).to(device)
                model.load_state_dict(saved["state"])
                transformed = np.nan_to_num(
                    np.clip((data.features - mean) / scale, -5, 5)
                )
                chooser = fixed_chooser(data, predictions=predict(model, transformed))
            else:
                model = Allocator(data.market.shape[1] + 1 + len(gp.ACTION_NAMES)).to(
                    device
                )
                model.load_state_dict(saved["state"])
                chooser = rl_chooser(data, model, mean, scale)
            for cost in (0.001, 0.003):
                actual = gp.evaluate(data, test, chooser, cost)
                expected = recorded[f"{kind}-{seed}@{round(cost * 10000)}bps"]
                np.testing.assert_allclose(
                    actual["nav"], expected["nav"], rtol=0, atol=1e-10
                )
                if (
                    actual["dates"] != expected["dates"]
                    or actual["decisions"] != expected["decisions"]
                ):
                    raise ValueError("Saved model decision replay differs")
                checked += 1
    print(
        json.dumps(
            {
                "verified_frozen_model_curves": checked,
                "training_revision": manifest["arguments"]["revision"],
                "replay_device": str(device),
            }
        )
    )


# Write one immutable research directory containing models, curves and provenance.
def main():
    args = parser().parse_args()
    device = resolve_device(args.device)
    if min(args.seeds, args.epochs, args.episodes) < 1:
        raise ValueError("Positive training bounds required")
    output = Path(args.output)
    if not args.verify:
        output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    panel, _ = book_panel(MarketStore(args.data_dir), date.fromisoformat(args.asof))
    data = gp.dataset(panel)
    train = gp.split_rows(data, "2018-01-01", "2024-01-01")
    val_labels = gp.split_rows(data, "2024-01-01", "2025-01-01")
    validation = gp.split_rows(data, "2024-01-01", "2025-01-01", horizon=1)
    test = gp.split_rows(data, "2025-01-01", "2027-01-01", horizon=1)
    if not all(len(x) for x in (train, val_labels, validation, test)):
        raise ValueError("A chronological split has no usable observations")
    if args.verify:
        verify_artifacts(data, test, output, device)
        return
    manifest = {
        "arguments": vars(args),
        "device": str(device),
        "cuda": torch.version.cuda if device.type == "cuda" else None,
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else None,
        "torch": torch.__version__,
        "numpy": np.__version__,
        "tickers": list(data.tickers),
        "price_sha256": hashlib.sha256(data.prices.tobytes()).hexdigest(),
        "feature_sha256": hashlib.sha256(data.features.tobytes()).hexdigest(),
        "train_last_decision": str(data.dates[train[-1]]),
        "train_last_label": str(data.dates[train[-1] + 5]),
        "validation_last_label": str(data.dates[val_labels[-1] + 5]),
        "test_first": str(data.dates[test[0]]),
        "test_last": str(data.dates[test[-1] + 1]),
        "status": "retrospective_daily_pilot_not_adopted",
        "limitations": [
            "Current book membership: survivorship/selection bias",
            "Price/calendar inputs only; no current desk/DeepSeek valuation replay",
            "Reinvested adjusted-price units; fractional next-close approximation",
            "No spread history, impact, settlement or historical quote eligibility",
            "No adopted FOMC overlay: diagnostic, not a replacement policy",
            "Post-event periods are short and not proof of a causal regime change",
            "2025+ examined by older experiments; not an untouched holdout",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    results = {}
    contenders = {
        "USD": fixed_chooser(data, 0),
        "SPY": fixed_chooser(data, benchmark=True),
        "momentum20": fixed_chooser(data, 1),
        "momentum120": fixed_chooser(data, 3),
        "equal": fixed_chooser(data, 5),
    }
    training = {}
    print(
        json.dumps(
            {k: manifest[k] for k in ("train_last_label", "test_first", "test_last")}
        ),
        flush=True,
    )
    for seed in range(args.seeds):
        predictions, info = neural(
            data, train, val_labels, seed, args.epochs, output, device
        )
        training[f"neural-{seed}"] = info
        contenders[f"neural-{seed}"] = fixed_chooser(data, predictions=predictions)
        print(f"Neural seed={seed}: {info}", flush=True)
        chooser, info = reinforcement(
            data, train, validation, seed, args.episodes, output, device
        )
        training[f"rl-{seed}"] = info
        contenders[f"rl-{seed}"] = chooser
    for name, chooser in contenders.items():
        for cost in (0.001, 0.003):
            key = f"{name}@{round(cost * 10000)}bps"
            results[key] = gp.evaluate(data, test, chooser, cost)
            print(f"{key}: {results[key]['metrics']}", flush=True)
    (output / "results.json").write_text(
        json.dumps(
            {"training": training, "results": results}, indent=2, allow_nan=False
        )
    )
    print(f"Research artifacts: {output}", flush=True)


if __name__ == "__main__":
    main()
