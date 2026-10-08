"""Authenticated remaining-session forecasts and a fixed funded component screen.

Training verification and account execution are separate phases. The latter can
run on the unmodified frozen comparison engine with this explicit source overlay.
Nothing here selects a production policy, calibrates confidence or places orders.
"""

import json
from pathlib import Path

import numpy as np

from backend.cli.market_learned_entry import sha256, write_json
from backend.market.learned_entry_models import _array_hash

SCHEMA = "verified-continuation-bank/1"
POLICY = "nonlinear-self-continuation/1-research"
PROTOCOL = "docs/research/nonlinear-continuation-funded-screen-plan-2026-10-07.md"
PROTOCOL_SHA = "3524f6642a92d9aaad5921f40731db7f53334b17bd78c4a3a24c362f74c4ae56"
FIELDS = {"dates", "symbols", "valid", "current_close", "predictions"}


# Refuse an altered artifact before decoding it or starting any funded account.
def checked_json(path, digest):
    if not isinstance(digest, str) or len(digest) != 64 or sha256(path) != digest:
        raise ValueError("Externally pinned evidence hash differs")
    return json.loads(Path(path).read_text())


# Reconcile all completed numeric monthly forecasts without fitting or trading.
def export_verified(prepared, fitted, manifest_sha256, output):
    from backend.market import nonlinear_continuation_artifact as artifact
    from backend.market import nonlinear_continuation_study as study

    fitted, output = Path(fitted), Path(output)
    manifest = checked_json(fitted / "manifest.json", manifest_sha256)
    dataset, original = study.load_original(prepared)
    expected = study.identity(dataset, original)
    if manifest["identity"] != expected or manifest["adoption_eligible"] is not False:
        raise ValueError("Original fitted continuation identity required")
    dates = dataset["dates"]
    months = list(map(str, np.unique(dates.astype("datetime64[M]"))))
    if [row["month"] for row in manifest["months"]] != months:
        raise ValueError("Every original monthly checkpoint required")
    path = fitted / "predictions.npz"
    if sha256(path) != manifest["forecast_sha256"]:
        raise ValueError("Complete continuation forecast bytes differ")
    with np.load(path, allow_pickle=False) as saved:
        if set(saved.files) != {"dates", "predictions"} or not np.array_equal(
            saved["dates"], dates
        ):
            raise ValueError("Original forecast calendar required")
        forecasts = saved["predictions"].copy()
    if _array_hash(forecasts) != manifest["prediction_array_sha256"]:
        raise ValueError("Complete continuation array identity differs")
    receipts = []
    for row in manifest["months"]:
        folder = fitted / row["month"]
        checkpoint = json.loads((folder / "checkpoint.json").read_text())
        if checkpoint != {key: row[key] for key in (
            "month", "fit_index", "identity_sha256", "manifest_sha256"
        )}:
            raise ValueError("Completed monthly checkpoint differs")
        _, monthly = artifact.load(
            folder, dataset, manifest_sha256=row["manifest_sha256"]
        )
        if monthly["fit"]["status"] != row["status"]:
            raise ValueError("Completed monthly status differs")
        with np.load(folder / "predictions.npz", allow_pickle=False) as saved:
            if not np.array_equal(
                forecasts[np.asarray(monthly["days"])], saved["predictions"],
                equal_nan=True,
            ):
                raise ValueError("Global forecasts differ from actual numeric heads")
        receipts.append({**row, "numeric_parity_verified": True})
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    arrays = {"dates": dates, "symbols": np.asarray(dataset["tickers"]),
              "valid": dataset["valid"], "current_close": dataset["current_close"],
              "predictions": forecasts}
    with (output / "bank.npz").open("xb") as handle:
        np.savez(handle, **arrays)
    receipt = {
        "schema": SCHEMA, "policy": POLICY,
        "status": "VERIFIED_ALL_MONTHLY_NUMERIC_FORECASTS",
        "fitted_manifest_sha256": manifest_sha256, "original_inputs": original,
        "identity_sha256": manifest["identity_sha256"], "months": receipts,
        "bank_sha256": sha256(output / "bank.npz"),
        "arrays": {key: _array_hash(value) for key, value in arrays.items()},
        "price_basis": "dimensionless_stop_minus_selected_suffix_over_current",
        "historical_publication": False, "adoption_eligible": False,
        "models_fitted": 0, "accounts_replayed": 0,
    }
    write_json(output / "receipt.json", receipt)
    return receipt


# Expose immutable clock-specific means only after exact calendar and units checks.
class ForecastBank:
    # Authenticate the numeric-only transport before accepting execution coordinates.
    def __init__(self, directory, receipt_sha256):
        directory = Path(directory)
        receipt = checked_json(directory / "receipt.json", receipt_sha256)
        if receipt.get("schema") != SCHEMA or receipt.get("policy") != POLICY or (
            receipt.get("status") != "VERIFIED_ALL_MONTHLY_NUMERIC_FORECASTS"
            or receipt.get("adoption_eligible") is not False
            or receipt.get("historical_publication") is not False
            or receipt.get("models_fitted") != 0
            or receipt.get("accounts_replayed") != 0
            or sha256(directory / "bank.npz") != receipt.get("bank_sha256")
        ):
            raise ValueError("Verified research continuation bank required")
        with np.load(directory / "bank.npz", allow_pickle=False) as saved:
            if set(saved.files) != FIELDS:
                raise ValueError("Exact continuation bank fields required")
            arrays = {key: saved[key].copy() for key in saved.files}
        hashes = {key: _array_hash(value) for key, value in arrays.items()}
        if hashes != receipt["arrays"]:
            raise ValueError("Verified continuation bank array identity differs")
        self.dates = arrays["dates"]
        self.symbols = tuple(arrays["symbols"].tolist())
        self.valid, self.current, self.means = (
            arrays[key] for key in ("valid", "current_close", "predictions")
        )
        shape = (len(self.dates), 25, len(self.symbols))
        if self.dates.dtype != np.dtype("datetime64[D]") or (
            np.isnat(self.dates).any() or not np.all(self.dates[1:] > self.dates[:-1])
            or not self.symbols or len(set(self.symbols)) != len(self.symbols)
            or any(not isinstance(name, str) or not name for name in self.symbols)
            or self.valid.dtype != np.dtype("bool") or self.valid.shape != shape
            or self.current.shape != shape or self.current.dtype.kind != "f"
            or self.means.shape != shape + (2,) or self.means.dtype.kind not in "fiu"
            or np.isinf(self.means).any() or np.isinf(self.current).any()
            or np.isfinite(self.means[~self.valid]).any()
            or np.isfinite(self.means[:, 24]).any()
        ):
            raise ValueError(
                "Ordered aligned finite-or-missing continuation bank required"
            )
        for value in arrays.values():
            value.flags.writeable = False
        self.verification, self.aligned = receipt, False

    # Bind adjusted observations to identical raw cube bars without fitting ratios.
    def align(self, panel, inputs, cubes):
        from backend.market.fill_timing import session_scale

        if not np.array_equal(self.dates, panel.dates) or not np.array_equal(
            self.dates, inputs.dates
        ) or self.symbols != tuple(panel.tickers) or (
            self.symbols != tuple(inputs.tickers)
        ):
            raise ValueError("Continuation execution calendar or symbols differ")
        checked = 0
        for stock, name in enumerate(self.symbols):
            supported = self.valid[:, :, stock]
            cube = cubes.get(name)
            if cube is None:
                if supported.any():
                    raise ValueError("Available forecast has no original raw cube")
                continue
            positions, inside, scales = session_scale(
                cube, panel.dates, panel.adj_close[:, stock]
            )
            rows = positions[inside]
            expected = np.full(supported.shape, np.nan)
            expected[rows] = cube.close[inside, :25] * scales[inside, None]
            actual = inputs.observation_close[:, :25, stock]
            raw = np.full(supported.shape, np.nan)
            raw[rows] = cube.close[inside, :25]
            # This tolerance covers only the stored float32 representation.
            tolerance = 4 * np.finfo(self.current.dtype).eps
            if not np.isfinite(expected[supported]).all() or not np.allclose(
                self.current[:, :, stock][supported], expected[supported],
                rtol=tolerance, atol=0,
            ) or not np.array_equal(actual[supported], raw[supported], equal_nan=True):
                raise ValueError(
                    "Continuation training and raw execution price bases differ"
                )
            checked += int(supported.sum())
        if self.valid[~inputs.full_session].any():
            raise ValueError("Unavailable early-close forecasts cannot be invented")
        self.aligned = True
        return {"available_price_observations_checked": checked,
                "conversion": "original_session_scale_not_fitted_price_ratios"}

    # Return an observed coordinate from a bank containing no future fill outcomes.
    def provider(self, day, clock, stock):
        if not self.aligned or any(type(value) not in (int, np.int64, np.int32)
                                   for value in (day, clock, stock)) or not (
            0 <= day < len(self.dates) and 0 <= clock < 25
            and 0 <= stock < len(self.symbols)
        ):
            raise ValueError("Aligned continuation forecast coordinate required")
        return self.means[day, clock, stock].copy()


# Select exactly the preregistered three start-zero accounts, never an outcome winner.
def account_grid(engine, dates):
    rows = [dict(row, arm="continuation", id=f"continuation-{row['cost_bps']}-0")
            for row in engine.account_grid(dates)
            if row["arm"] == "rule" and row["start"] == 0]
    if len(rows) != 3 or [row["cost_bps"] for row in rows] != [0, 10, 25]:
        raise ValueError("Fixed three-cost start-zero continuation screen required")
    return rows


# Run new funded accounts on an authenticated frozen engine and save closed receipts.
def execute(config):
    from types import SimpleNamespace

    from backend.cli import market_actual_policy_timing as engine
    from backend.market import live_continuation_timing as reader

    root = Path(__file__).resolve().parents[2]
    if sha256(root / PROTOCOL) != PROTOCOL_SHA:
        raise ValueError("Frozen continuation screen protocol differs")
    args = SimpleNamespace(**{
        key: Path(value) if key != "source_revision" else value
        for key, value in config["engine_arguments"].items()
    })
    source = engine.source_identity(args)
    if source != config["engine_identity"]:
        raise ValueError("Frozen control execution source differs")
    proof = checked_json(args.economic_input_proof, engine.ECONOMIC_INPUT_PROOF_SHA)
    if proof["status"] != "VERIFIED_INDEPENDENT_REVIEWED_ORIGINAL_INPUTS" or (
        proof["original_files"] != 103 or proof["selection_symbols"] != 96
        or proof["sessions"] != 2953 or proof["adoption_eligible"] is not False
        or proof["models_fitted"] != 0 or proof["accounts_created"] != 0
        or engine.runtime_identity()["image_id"] != config["image"]
    ):
        raise ValueError("Independent original economic input proof required")
    bank = ForecastBank(config["bank"], config["bank_receipt_sha256"])
    panel, raw, cubes, files = engine.load_execution_inputs(args, reviewed=True)
    alignment = bank.align(panel, raw, cubes)
    overlay = {name: sha256(root / name) for name in config["overlay"]}
    if overlay != config["overlay"]:
        raise ValueError("Continuation evaluation overlay differs")
    output = Path(config["output"])
    if output.resolve().is_relative_to(Path(config["bank"]).resolve()):
        raise ValueError("New accounts must be separate from immutable forecasts")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    for folder in ("accounts", "receipts"):
        (output / folder).mkdir(mode=0o700)
    grid = account_grid(engine, panel.dates)
    identity = {
        "policy": POLICY, "accounts": grid, "source": source,
        "overlay": overlay, "runtime": engine.runtime_identity(),
        "bank_receipt_sha256": config["bank_receipt_sha256"],
        "original_files": files, "raw_input_provenance": engine.plain(raw.provenance),
        "alignment": alignment, "protocol_sha256": PROTOCOL_SHA,
        "adoption_eligible": False, "historical_live_reconstruction": False,
    }
    write_json(output / "identity.json", identity)
    cache, rows = engine.FeatureCache(source["manifest_sha256"]), []
    for spec in grid:
        result = engine.run_account(
            panel, raw, cubes, output / "state" / spec["id"],
            spec["first"], spec["last"], spec["cost_bps"],
            feature_reader=cache, reader_builder=reader.build_reader,
            provider=bank.provider,
        )
        result["comparison_account"] = spec
        path = output / "accounts" / (spec["id"] + ".json.gz")
        digest = engine.archive_account(path, result)
        row = {**spec, "file": str(path.relative_to(output)), "sha256": digest,
               "scores": {name: engine.account_score(result, lower, upper)
                          for name, lower, upper in engine.WINDOWS}}
        write_json(output / "receipts" / (spec["id"] + ".json"), row)
        rows.append(row)
        write_json(output / "progress.json", {"completed": len(rows), "accounts": rows,
                                             "declared": 3, "adoption_eligible": False})
        print(json.dumps({"completed": len(rows), "account": spec["id"]}), flush=True)
    engine.check_original_files(files)
    write_json(output / "complete.json", {
        "accounts": rows, "adoption_eligible": False,
        "identity_sha256": sha256(output / "identity.json"),
    })
    return rows


# Verify side decisions against saved means without fitting or resimulating trades.
def check_trace(account, bank):
    counts = dict.fromkeys(("execute", "wait", "unavailable", "no_trade"), 0)
    intents = {row["client_order_id"]: row for row in account["intents"]}
    for row in account["forecast_decisions"]:
        day, clock = row["day"], row["clock"]
        if type(day) is not int or type(clock) is not int or not (
            0 <= day < len(bank.dates) and 0 <= clock < 24
        ):
            raise ValueError("Original continuation decision coordinate differs")
        original = intents.get(row["intent_id"])
        if original is None or row["policy"] != "live-self-continuation/1-research" or (
            row["is_calibrated_confidence"] is not False
            or row["funding_is_ex_ante"] is not True
            or row["state"] not in counts
            or row["symbol"] != original["symbol"]
            or row["side"] != original["side"]
            or row["desired_qty"] != original["qty"]
            or row["session"] != str(bank.dates[day])
        ):
            raise ValueError("Original continuation decision identity differs")
        state, mean = row["state"], row["continuation_mean"]
        if state in ("execute", "wait"):
            stock = bank.symbols.index(row["symbol"])
            side = 0 if row["side"] == "buy" else 1
            saved = bank.means[day, clock, stock, side]
            waiting = saved > 0 if side == 0 else saved < 0
            if not np.isfinite(saved) or mean != saved or row["reason"] or (
                state != ("wait" if waiting else "execute")
                or row["trade_fraction"] <= 0
            ):
                raise ValueError("Saved continuation side decision differs")
        elif mean is not None:
            raise ValueError("Unavailable continuation cannot claim a mean")
        counts[state] += 1
    return counts


# Reuse unchanged control proofs and reconcile only newly closed matched references.
def _controls(config, original, previous, data):
    from backend.cli import verify_joint_funded as funded

    prior = {row["id"]: row for row in previous["control_accounts"]}
    controls, newly_checked = [], []
    control_study = Path(config["control_study"])
    acknowledgments = [json.loads(path.read_text()) for path in sorted(
        (control_study / "receipts").glob("completed-*.json")
    )]
    for cost in (0, 10, 25):
        for arm in ("rule", "SPY", "QQQ"):
            identifier = f"{arm}-{cost}-0"
            if identifier in prior:
                row = prior[identifier]
                if sha256(control_study / "accounts" / (identifier + ".json.gz")) != (
                    row["sha256"]
                ):
                    raise ValueError("Previously verified matched control changed")
                controls.append(row)
            else:
                path = control_study / "receipts" / (identifier + ".json")
                row = json.loads(path.read_text())
                matches = [ack for ack in acknowledgments
                           if ack["account"] == identifier]
                if len(matches) != 1 or matches[0]["sha256"] != row["sha256"]:
                    raise ValueError("Matched control lacks its closed acknowledgment")
                spec = next(item for item in original["accounts"]
                            if item["id"] == identifier)
                if any(row[key] != value for key, value in spec.items()):
                    raise ValueError("Fixed matched control specification differs")
                fresh = funded.verify_rows(control_study, [row], data)
                controls.extend(fresh)
                newly_checked.append(identifier)
    return controls, newly_checked


# Reconcile closed accounts and matched controls using the independent ledger reader.
def verify_accounts(config, output):
    from types import SimpleNamespace

    from backend.cli import verify_actual_policy_timing as ledger
    from backend.cli import verify_joint_funded as funded

    study = Path(config["study"])
    complete = checked_json(study / "complete.json", config["complete_sha256"])
    identity = checked_json(study / "identity.json", complete["identity_sha256"])
    original = checked_json(
        config["control_identity"], config["control_identity_sha256"]
    )
    previous = checked_json(config["previous_proof"], config["previous_proof_sha256"])
    bank = ForecastBank(config["bank"], identity["bank_receipt_sha256"])
    if identity["accounts"] != [
        {key: row[key] for key in (
            "arm", "cost_bps", "start", "first", "last", "first_session", "id"
        )} for row in complete["accounts"]
    ] or len(complete["accounts"]) != 3 or [
        row["id"] for row in complete["accounts"]
    ] != ["continuation-0-0", "continuation-10-0", "continuation-25-0"] or (
        identity["raw_input_provenance"] != original["raw_input_provenance"]
        or identity["source"] != original["source"]
        or identity["protocol_sha256"] != PROTOCOL_SHA
        or complete["adoption_eligible"] is not False
        or previous["adoption_eligible"] is not False
        or previous["status"] != "VERIFIED_CONTINUATION_SNAPSHOT_ARITHMETIC"
        or previous["lineage"]["identity_sha256"] != config["control_identity_sha256"]
    ):
        raise ValueError("Fixed complete funded screen and matched controls required")
    args = SimpleNamespace(**{key: Path(value)
                              for key, value in config["input_arguments"].items()})
    data = ledger.load_original_data(args, original, reviewed=True)
    if not np.array_equal(bank.dates, data["dates"]) or bank.symbols != data["names"]:
        raise ValueError("Verified forecast and independent raw ledger grids differ")
    checked = funded.verify_rows(study, complete["accounts"], data)
    for row in checked:
        account = ledger.read_account(study, next(
            record for record in complete["accounts"] if record["id"] == row["id"]
        ))
        row["continuation_decisions"] = check_trace(account, bank)
    controls, newly_checked = _controls(config, original, previous, data)
    comparisons = funded.paired_results(checked, controls, identity["accounts"])
    output = Path(output)
    if output.resolve().is_relative_to(study.resolve()):
        raise ValueError("Read-only proof must be outside produced accounts")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    result = {
        "status": "VERIFIED_THREE_ACCOUNT_CONTINUATION_COMPONENT_SCREEN",
        "accounts": checked, "controls": controls, "comparisons": comparisons,
        "newly_verified_controls": newly_checked,
        "complete_sha256": config["complete_sha256"], "sources": config,
        "adoption_eligible": False, "models_fitted": 0, "accounts_replayed": 0,
        "limitations": ["three_start_zero_component_accounts_not_adoption",
                        "current_vintage_selection_not_historical_live_reconstruction",
                        "conditional_raw_open_fills_not_broker_or_midpoint_receipts",
                        "holding_exits_and_confidence_sizing_unchanged",
                        "recent_period_reused_not_fresh_holdout"],
    }
    write_json(output / "results.json", result)
    return result
