"""Train and replay the ten-session entry context ablation; research only."""

import argparse
import hashlib
import json
import subprocess
from dataclasses import fields
from pathlib import Path

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

from backend.market import entry_context as ec
from backend.market import entry_pilot as ep
from backend.market import fundamental_features as ff
from backend.market import fundamentals_asof as fa
from backend.market import intraday
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.universe import (
    MARKET_BENCHMARK,
    book_sides,
    build_universe,
    theme_map,
)

# The protocol's frozen constants: ten sessions, three costs, the training
# window, and the retrospective report windows.
HORIZON = 10
COSTS = (5, 10, 20)
TRAIN_START, TRAIN_STOP = "2020-01-01", "2024-01-01"
PERIOD_2024 = ("2024-01-01", "2025-01-01")

# The information test's explicit limits, recorded in every manifest.
LIMITATIONS = (
    "survivor universe",
    "retrospective/reused periods, not untouched validation or test",
    "IEX bar-open fills with no impact or spread history",
    "price-only fixed selection, not the production desk",
    "zero cash interest",
    "daily-close drawdown only",
    "research information test only; no live promotion",
)

# Every source file that shapes this experiment, hashed into the manifest.
SOURCE_FILES = (
    Path(__file__),
    Path(__file__).parent.parent / "market" / "entry_context.py",
    Path(__file__).parent.parent / "market" / "entry_pilot.py",
    Path(__file__).parent.parent / "market" / "fundamental_features.py",
    Path(__file__).parent.parent / "market" / "fundamentals_asof.py",
)


# The protocol's fixed command-line surface.
def parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data-dir", default="data/market")
    p.add_argument("--output", type=Path, required=True)
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


# One tree model per target, with the protocol's exact parameters.
def make_regressor():
    """Return a HistGradientBoostingRegressor with the protocol's fixed parameters."""
    return HistGradientBoostingRegressor(
        max_iter=100,
        max_leaf_nodes=15,
        min_samples_leaf=100,
        l2_regularization=10,
        learning_rate=0.05,
        early_stopping=False,
        random_state=0,
    )


# Fit the two per-target models for one feature set on the training rows.
def fit_models(x, y, train):
    """Return [model0, model1] trained on the training rows of the two targets."""
    return [make_regressor().fit(x[train], y[train, t]) for t in range(y.shape[1])]


# Predict both targets for every observation.
def predict(models, x):
    """Return (R, 2) predictions from the two per-target models."""
    return np.column_stack([m.predict(x) for m in models])


# Build the desk book panel without importing the whole desk.
def book_panel(store):
    """Return the (panel, sides) of the desk book, mirroring desk.book_panel."""
    uni = build_universe()
    sides = book_sides(uni)
    themes = {t: g for t, g in theme_map(uni).items() if t in sides}
    panel = build_panel(store, tuple(sorted(sides)), MARKET_BENCHMARK, themes)
    return panel, sides


# Build the book panel and the entry dataset from the stored 15m partition.
def build_data(store, data_dir):
    """Return (panel, data, partition) for the desk book on the newest bars.

    The entry pilot expects the intraday partition path, not the store root;
    a wrong root has no per-ticker parquet and the build must fail.
    """
    panel, _ = book_panel(store)
    root = intraday.partition(Path(data_dir) / "bars_15m")
    data = ep.build(panel, root, HORIZON)
    return panel, data, root


# Standardize the pilot's price features from training observations only.
def preprocess_price(x, train, fitted=None):
    """Return (R, 28) normalized price features and the frozen normalization.

    Training-only mean and std, std floored, clipped to [-10, 10] exactly as
    the pilot's trees receive the price block, so the two arms share it.
    """
    if fitted is None:
        fitted = {
            "mean": x[train].mean(axis=0),
            "std": np.maximum(x[train].std(axis=0), 1e-5),
        }
    norm = np.clip((x - fitted["mean"]) / fitted["std"], -10, 10).astype("float32")
    return norm, fitted


# Join the point-in-time fundamental context to every decision.
def build_context(data, features, train):
    """Return (block, values, flags, ages, medians) for every decision.

    The block is the (R, 21) concatenation of imputed values, missing flags,
    and fiscal ages; the components are returned so verification can rebuild
    the block from them.
    """
    values, ends = ec.context_block(features, data.day, data.name)
    medians = ec.training_medians(values, train)
    flags = ec.missing_flags(values)
    ages = ec.fiscal_ages(data.dates, data.day, values, ends)
    block = np.column_stack((ec.impute(values, medians), flags, ages)).astype("float32")
    return block, values, flags, ages, medians


# Report windows ending at the data's last session.
def report_periods(data):
    """Return the protocol's retrospective windows ending at the last session."""
    end = str(np.datetime64(data.dates[-1]) + np.timedelta64(1, "D"))
    return {
        "2024": PERIOD_2024,
        "2025_to_data_end": ("2025-01-01", end),
        "pooled": (PERIOD_2024[0], end),
    }


# Run every baseline and model through every cost and report period.
def evaluate_all(data, predictions, periods, costs=COSTS):
    """Return one account result per period, cost, baseline and model mode.

    Every model runs in timing-only (enter/wait) and skip modes. Each model
    result carries paired daily-return intervals against both baselines
    (always-enter and always-wait), and each context-arm result also carries
    the paired interval against its price-only arm on the same window, cost
    and mode.
    """
    results = {}
    for period, (start, stop) in periods.items():
        mask = ep.split(data, start, stop, labelled=False)
        if not (mask & data.candidate).any():
            continue
        for cost in costs:
            prefix = f"{period}@{cost}bps/"
            enter = ep.evaluate(data, mask, np.zeros(len(data.x), dtype=int), cost)
            results[prefix + "enter"] = enter
            wait = ep.evaluate(data, mask, np.ones(len(data.x), dtype=int), cost)
            results[prefix + "wait"] = wait
            for name, pred in predictions.items():
                for skip in (False, True):
                    action = ep.actions(pred, cost, skip)
                    result = ep.evaluate(data, mask, action, cost)
                    result["paired_vs_enter"] = ep.paired_interval(result, enter)
                    result["paired_vs_wait"] = ep.paired_interval(result, wait)
                    mode = "skip" if skip else "timing"
                    results[prefix + name + "/" + mode] = result
            for mode in ("timing", "skip"):
                price_key = prefix + "price/" + mode
                context_key = prefix + "context/" + mode
                if price_key in results and context_key in results:
                    results[context_key]["paired_vs_price"] = ep.paired_interval(
                        results[context_key], results[price_key]
                    )
    return results


# Prove the account machinery on the report windows before fitting anything.
def preflight(data, periods, costs=COSTS):
    """Run the always-enter and always-wait baselines on every report window."""
    for _, (start, stop) in periods.items():
        mask = ep.split(data, start, stop, labelled=False)
        if not (mask & data.candidate).any():
            continue
        for cost in costs:
            ep.evaluate(data, mask, np.zeros(len(data.x), dtype=int), cost)
            ep.evaluate(data, mask, np.ones(len(data.x), dtype=int), cost)


# SHA-256 of every source file that shapes this experiment.
def source_hashes():
    """Return {filename: sha256} for the experiment's source files."""
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}


# The current git revision, best effort.
def revision():
    """Return the git HEAD short hash, or 'unknown' outside a repository."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except (subprocess.SubprocessError, FileNotFoundError):
        return "unknown"


# Reduce every result to its scalar metrics plus the paired interval.
def summary(results):
    """Return the scalar metrics and paired intervals of every account result."""
    return {
        name: {
            "net_return": res["net_return"],
            "sharpe_zero_cash_yield": res["sharpe_zero_cash_yield"],
            "max_drawdown": res["max_drawdown"],
            "average_exposure": res["average_exposure"],
            "turnover_total": res["turnover_total"],
            "action_counts": res["action_counts"],
            "paired_vs_enter": res.get("paired_vs_enter"),
            "paired_vs_wait": res.get("paired_vs_wait"),
            "paired_vs_price": res.get("paired_vs_price"),
        }
        for name, res in results.items()
    }


# The fixed machine-readable description of one run.
def build_manifest(data, train, periods, medians, intraday_partition=None):
    """Return the manifest pinning this run's revision, data, and settings."""
    counts = {"training": int(train.sum())}
    for period, (start, stop) in periods.items():
        counts[period] = int(
            (ep.split(data, start, stop, labelled=False) & data.candidate).sum()
        )
    return {
        "revision": revision(),
        "horizon": HORIZON,
        "intraday_partition": intraday_partition,
        "report_periods": {period: list(span) for period, span in periods.items()},
        "features": {
            "price": list(ep.NAMES),
            "context": list(ec.ECONOMIC),
            "context_columns": int(block_width()),
        },
        "source_sha256": source_hashes(),
        "dataset_sha256": digest(data),
        "split_counts": counts,
        "library_versions": {
            "numpy": np.__version__,
            "sklearn": sklearn.__version__,
            "joblib": joblib.__version__,
        },
        "limitations": list(LIMITATIONS),
        "median_vector": medians.tolist(),
    }


# The width of the assembled context block: values, flags and ages.
def block_width():
    """Return the number of context columns (3x the economic features)."""
    return 3 * len(ec.ECONOMIC)


# SHA-256 of every saved artifact file, pinned in the manifest.
def artifact_hashes(output):
    """Return {filename: sha256} for every persisted artifact."""
    names = (
        "dataset.npz",
        "context.npz",
        "price_preprocess.npz",
        "predictions.npz",
        "price_models.joblib",
        "context_models.joblib",
    )
    return {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest() for name in names
    }


# Load one saved npz into a dict of arrays.
def _load_npz(path):
    """Return {name: array} for one saved npz artifact."""
    with np.load(path) as z:
        return {k: z[k] for k in z.files}


# Write every artifact plus the manifest that describes and pins them.
def save_artifacts(
    output,
    data,
    train,
    context_parts,
    price_fit,
    price_models,
    context_models,
    predictions,
    results,
    periods,
    intraday_partition=None,
):
    """Persist the dataset, context, models, predictions, results and manifest.

    Every persisted artifact is hashed into the manifest, and the dataset is
    fingerprinted in memory, so verification can detect tampering before it
    loads a single model.
    """
    values, flags, ages, block, medians = context_parts
    dataset = {f.name: np.asarray(getattr(data, f.name)) for f in fields(data)}
    np.savez_compressed(output / "dataset.npz", **dataset)
    np.savez_compressed(
        output / "context.npz",
        values=values,
        flags=flags,
        ages=ages,
        block=block,
        medians=medians,
    )
    np.savez_compressed(output / "price_preprocess.npz", **price_fit)
    joblib.dump(price_models, output / "price_models.joblib")
    joblib.dump(context_models, output / "context_models.joblib")
    np.savez_compressed(output / "predictions.npz", **predictions)
    results_dir = output / "results"
    results_dir.mkdir()
    for name, res in results.items():
        safe = name.replace("/", "_")
        np.savez_compressed(
            results_dir / f"{safe}.npz",
            nav=np.asarray(res["nav"]),
            daily=np.asarray(res["daily"]),
            decisions=np.asarray(res["decisions"]),
            dates=np.asarray(res["dates"]),
        )
    manifest = build_manifest(data, train, periods, medians, intraday_partition)
    manifest["artifact_sha256"] = artifact_hashes(output)
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (output / "summary.json").write_text(json.dumps(summary(results), indent=2))


# Run the whole ablation into a new output directory.
def run(
    data,
    features,
    output,
    train_period=(TRAIN_START, TRAIN_STOP),
    periods=None,
    intraday_partition=None,
):
    """Preprocess, preflight, fit, evaluate and save every artifact for the run.

    The training mask and report periods come from the pilot's split; the
    context block is joined before imputation, and both arms share the same
    normalized price block. The intraday partition the data was built from is
    recorded in the manifest.
    """
    output.mkdir(exist_ok=False)
    if periods is None:
        periods = report_periods(data)
    train = ep.split(data, *train_period)
    if not train.any():
        raise ValueError("no training rows in the training window")
    preflight(data, periods)
    block, values, flags, ages, medians = build_context(data, features, train)
    x_norm, price_fit = preprocess_price(data.x, train)
    x_price = x_norm
    x_context = np.column_stack((x_norm, block)).astype("float32")
    y = data.y
    price_models = fit_models(x_price, y, train)
    context_models = fit_models(x_context, y, train)
    predictions = {
        "price": predict(price_models, x_price),
        "context": predict(context_models, x_context),
    }
    results = evaluate_all(data, predictions, periods)
    save_artifacts(
        output,
        data,
        train,
        (values, flags, ages, block, medians),
        price_fit,
        price_models,
        context_models,
        predictions,
        results,
        periods,
        intraday_partition,
    )
    print(f"wrote {output}")
    return output


# Replay a saved run from its own artifacts and prove it reproduces exactly.
def verify(output):
    """Reload the run's artifacts and assert hashes, predictions, decisions, NAV.

    The pinned artifact hashes and the dataset fingerprint are checked before
    any model is loaded, so a tampered input is rejected without being used.
    Nothing is ever recomputed into the manifest or overwritten here.
    """
    manifest = json.loads((output / "manifest.json").read_text())
    if "artifact_sha256" not in manifest:
        raise AssertionError("manifest has no pinned artifact hashes")
    for name, recorded in manifest["artifact_sha256"].items():
        actual = hashlib.sha256((output / name).read_bytes()).hexdigest()
        if actual != recorded:
            raise AssertionError(f"artifact {name} does not match its pinned hash")
    saved_data = _load_npz(output / "dataset.npz")
    # The dataclass types horizon as int; an int64 reload would float64-poison
    # the ledger's cash arithmetic and break bit-exact NAV replay.
    saved_data["horizon"] = int(saved_data["horizon"])
    data = ep.Dataset(**saved_data)
    if digest(data) != manifest.get("dataset_sha256"):
        raise AssertionError("dataset does not match its pinned hash")
    ctx = _load_npz(output / "context.npz")
    pre = _load_npz(output / "price_preprocess.npz")
    saved_predictions = _load_npz(output / "predictions.npz")
    price_models = joblib.load(output / "price_models.joblib")
    context_models = joblib.load(output / "context_models.joblib")
    reassembled = np.column_stack(
        (ec.impute(ctx["values"], ctx["medians"]), ctx["flags"], ctx["ages"])
    ).astype("float32")
    if not np.array_equal(reassembled, ctx["block"]):
        raise AssertionError("context block does not reassemble from its own parts")
    x_norm, _ = preprocess_price(data.x, np.zeros(len(data.x), dtype=bool), pre)
    predictions = {
        "price": predict(price_models, x_norm),
        "context": predict(
            context_models, np.column_stack((x_norm, ctx["block"])).astype("float32")
        ),
    }
    for name, pred in predictions.items():
        np.testing.assert_allclose(pred, saved_predictions[name], rtol=1e-5, atol=1e-5)
    periods = {p: tuple(span) for p, span in manifest["report_periods"].items()}
    results = evaluate_all(data, predictions, periods)
    for name, res in results.items():
        safe = name.replace("/", "_")
        saved = _load_npz(output / "results" / f"{safe}.npz")
        np.testing.assert_allclose(
            np.asarray(res["nav"]), saved["nav"], rtol=0, atol=1e-10
        )
        np.testing.assert_allclose(
            np.asarray(res["daily"]), saved["daily"], rtol=0, atol=1e-10
        )
        if not np.array_equal(np.asarray(res["decisions"]), saved["decisions"]):
            raise AssertionError(f"decisions differ for {name}")
    print(f"verified {output}: hashes, predictions, decisions and NAV reproduced")


# Entry point: run the ablation, or replay and verify a saved run.
def main(argv=None):
    args = parser().parse_args(argv)
    with threadpool_limits(limits=4):
        if args.verify:
            verify(args.output)
            return
        store = MarketStore(Path(args.data_dir))
        panel, data, root = build_data(store, args.data_dir)
        versions = fa.load_versions(store, panel)
        features = ff.features(panel, versions)
        run(data, features, args.output, intraday_partition=str(root))
        verify(args.output)


if __name__ == "__main__":
    main()
