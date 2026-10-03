"""Fixed joint-selection accounts using saved forecasts and verified prior controls.

No training, historical refetch, prior-account replay or live order submission.
This measures reconstructed daily selection, not the current intraday executor.
"""

import hashlib
import json
from collections import Counter
from itertools import product
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import event_risk, paper, policy_v5, simulate
from backend.market import retention_inputs
from backend.market import retention_study as prior
from backend.market.learned_cash_selection import CashSelectionAdapter
from backend.market.learned_entry_models import _array_hash, _write_json
from backend.market.retention_replay import RetentionAdapter

PRIOR_REVISION = "95ee87086ac336ea81e80f6b29a693a62d686602"
PRIOR_RESULT = "d9781a5910cb5d5893ce88e42a8e29ce4507cfc57049e012745b61e0b24017b7"
PRIOR_PROOF = "d855eea0eb910748f01142a3b44f027079f1665afd9570d95c0d0f1a879a238f"
PRIOR_PUBLIC = "55f15b8d713b675c23dbe711532833abc829fc5559cdf88f68f56cb16e7e1a90"
PRIOR_ARTIFACTS = {
    "forecasts.npz": "4de8c9521bb1f7eaf3047c6c45534ef172dbf02b83d087e914cb2d124e8f712d",
    "curves.npz": "22d267b23af1ab8d66879130a6a6954952a4ce7e845059b967c19cf7d2ecffbb",
    "fit.json": "726c272444e60c748eb2254e5daa33f7a2b6cbc3cc5d694041c8144c515ae42b",
    "inputs.json": "5d556a2fc4d2e4e52121e0039e11f2cfc07eb5d5f53acbb3a6240f5fcf2d171a",
}
JOINT_REVISION = "e8505b221bdd4cd21f2c0a3b13e52d720ab93bea"
JOINT_RESULT = "8bb4cb5d9ca2ac797395be88f69d693d9f9ee4df592ce419dd4d738b246eebb7"
JOINT_PROOF = "cc31794054ab02b90c9df75865643a092352cb00a482f92e3f1b3ff6978803f3"
JOINT_PUBLIC = "1c83155fdf5c90a7b2922899757dfbefd25247caf49c7f6fd6e526004fad818a"
JOINT_CURVES = "f4af0f4d6d32ffe5325101c0723170caf5a3aa778bd8d7db3e57c21f9ed3060a"
ATTRIBUTION_ARMS = ("quantity_control", "buy_only", "exit_only")
ATTRIBUTION_CONTRASTS = (
    ("buy_only", "quantity_control"),
    ("exit_only", "quantity_control"),
    ("joint", "quantity_control"),
    ("joint", "buy_only"),
    ("joint", "exit_only"),
    ("quantity_control", "learned"),
)


# Reuse the exact verified joint scores and curves without replaying those accounts.
def authenticate_joint(directory, proof_path, public_path, dates):
    directory = Path(directory)
    for path, expected in (
        (directory / "result.json", JOINT_RESULT),
        (directory / "curves.npz", JOINT_CURVES),
        (Path(proof_path), JOINT_PROOF),
        (Path(public_path), JOINT_PUBLIC),
    ):
        if digest(path) != expected:
            raise ValueError("Exact verified joint control bytes required")
    proof = json.loads(Path(proof_path).read_text())
    public = json.loads(Path(public_path).read_text())
    if (
        proof.get("ok") is not True
        or proof.get("source_revision") != JOINT_REVISION
        or proof.get("result_sha256") != JOINT_RESULT
        or public.get("source_revision") != JOINT_REVISION
        or public.get("result_sha256") != JOINT_RESULT
        or public.get("independent_proof_sha256") != JOINT_PROOF
    ):
        raise ValueError("Joint proof/control identity mismatch")
    expected = {f"joint-{c}-{o}" for c in prior.COSTS for o in prior.OFFSETS}
    rows = public["accounts"]
    if len(rows) != len(expected) or {r["account"] for r in rows} != expected:
        raise ValueError("Complete unique joint control grid required")
    if any(
        r["arm"] != "joint" or r["account"] != f"joint-{r['cost_bps']}-{r['offset']}"
        for r in rows
    ):
        raise ValueError("Joint control row identity mismatch")
    with np.load(directory / "curves.npz", allow_pickle=False) as saved:
        if set(saved.files) != expected | {"dates"} or not np.array_equal(
            saved["dates"], dates
        ):
            raise ValueError("Joint control curve clock/grid mismatch")
        curves = {key: saved[key].copy() for key in expected}
    for row in rows:
        nav = curves[row["account"]]
        if (
            nav.shape != dates.shape
            or not np.isfinite(nav).all()
            or np.any(nav <= 0)
            or _array_hash(nav) != row["nav_sha256"]
        ):
            raise ValueError("Joint control NAV differs from verified score")
    return rows, curves


# Preserve each preregistered paired difference and the carried-book interaction.
def attribution_results(accounts, joint, controls):
    rows = accounts + joint + controls
    lookup = {(r["arm"], r["cost_bps"], r["offset"]): r for r in rows}
    if len(lookup) != len(rows):
        raise ValueError("Duplicate attribution/control account identity")
    paired, interactions = [], []
    for cost, offset, window in product(prior.COSTS, prior.OFFSETS, prior.WINDOWS):
        values = {
            arm: lookup[arm, cost, offset]["score"][window]["metrics"]
            for arm in (*ATTRIBUTION_ARMS, "joint", "learned")
        }
        for left, right in ATTRIBUTION_CONTRASTS:
            paired.append(
                {
                    "cost_bps": cost,
                    "offset": offset,
                    "window": window,
                    "left": left,
                    "right": right,
                    "paired_total_gain": None
                    if values[left] is None or values[right] is None
                    else values[left]["total"] - values[right]["total"],
                }
            )
        required = [values[a] for a in (*ATTRIBUTION_ARMS, "joint")]
        interactions.append(
            {
                "cost_bps": cost,
                "offset": offset,
                "window": window,
                "interaction_total_gain": None
                if any(v is None for v in required)
                else values["joint"]["total"]
                - values["buy_only"]["total"]
                - values["exit_only"]["total"]
                + values["quantity_control"]["total"],
            }
        )
    return paired, interactions


# Authenticate large original artifacts incrementally without loading their payloads.
def digest(path):
    hashed = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            hashed.update(chunk)
    return hashed.hexdigest()


# Retain exact prior evidence; no prior model or account is recomputed here.
def authenticate_prior(directory, proof_path, public_path):
    directory = Path(directory)
    if digest(directory / "result.json") != PRIOR_RESULT:
        raise ValueError("Original verified prior result bytes required")
    if digest(proof_path) != PRIOR_PROOF or digest(public_path) != PRIOR_PUBLIC:
        raise ValueError("Verified proof and complete public control bytes required")
    for name, expected in PRIOR_ARTIFACTS.items():
        if digest(directory / name) != expected:
            raise ValueError(f"Verified prior artifact bytes required: {name}")
    proof = json.loads(Path(proof_path).read_text())
    public = json.loads(Path(public_path).read_text())
    if (
        proof.get("ok") is not True
        or proof.get("source_revision") != PRIOR_REVISION
        or proof.get("result_sha256") != PRIOR_RESULT
        or public.get("source_revision") != PRIOR_REVISION
        or public.get("result_sha256") != PRIOR_RESULT
        or public.get("independent_proof_sha256") != PRIOR_PROOF
    ):
        raise ValueError("Prior proof/control identity mismatch")
    expected = {
        f"{arm}-{cost}-{offset}"
        for arm in prior.ARMS
        for cost in prior.COSTS
        for offset in prior.OFFSETS
    }
    rows = {row["account"]: row for row in public["accounts"]}
    if len(rows) != len(public["accounts"]) or set(rows) != expected:
        raise ValueError("Complete unique original control grid required")
    return public, json.loads((directory / "inputs.json").read_text())


# Refuse shifted clocks, changed symbols or hidden source substitutions before replay.
def saved_arrays(directory, panel, public, inputs, original):
    if original["original_inputs"] != inputs:
        raise ValueError("Original input provenance differs from verified controls")
    directory = Path(directory)
    with np.load(directory / "forecasts.npz", allow_pickle=False) as source:
        dates, relative, spy = source["dates"], source["relative"], source["spy"]
    if not np.array_equal(dates, panel.dates):
        raise ValueError("Saved forecast calendar differs from source panel")
    if relative.shape != panel.close.shape or spy.shape != (len(panel.dates),):
        raise ValueError("Saved forecast grid differs from source panel")
    if np.isinf(relative).any() or np.isinf(spy).any():
        raise ValueError("Saved forecasts contain infinite values")
    first = int(np.searchsorted(panel.dates, prior.START))
    expected = {row["account"] for row in public["accounts"]} | {
        f"{symbol}-{cost}" for symbol in ("SPY", "QQQ") for cost in prior.COSTS
    }
    with np.load(directory / "curves.npz", allow_pickle=False) as saved:
        if set(saved.files) != expected | {"dates"} or not np.array_equal(
            saved["dates"], panel.dates[first:]
        ):
            raise ValueError("Saved control curve grid/calendar mismatch")
        curves = {key: saved[key].copy() for key in expected}
    for row in public["accounts"]:
        if _array_hash(curves[row["account"]]) != row["nav_sha256"]:
            raise ValueError(
                "Saved control NAV differs from independently verified score"
            )
    if any(
        curve.shape != (len(panel.dates) - first,)
        or not np.isfinite(curve).all()
        or np.any(curve <= 0)
        for curve in curves.values()
    ):
        raise ValueError("Complete positive prior control NAV required")
    return relative, spy, curves


# Compare each new account only with the same cost, reset phase and window.
def paired_results(accounts, controls):
    lookup = {(r["arm"], r["cost_bps"], r["offset"]): r for r in controls}
    result = []
    for row in accounts:
        for control in prior.ARMS:
            old = lookup[control, row["cost_bps"], row["offset"]]
            for window in prior.WINDOWS:
                own = row["score"][window]["metrics"]
                other = old["score"][window]["metrics"]
                result.append(
                    {
                        "cost_bps": row["cost_bps"],
                        "offset": row["offset"],
                        "control": control,
                        "window": window,
                        "paired_total_gain": None
                        if own is None or other is None
                        else own["total"] - other["total"],
                    }
                )
    return result


# Reject ambiguous experiment/control combinations before reading account evidence.
def experiment_arms(attribution, joint_directory, joint_proof, joint_public):
    if type(attribution) is not bool:
        raise ValueError("Boolean attribution mode required")
    supplied = (joint_directory, joint_proof, joint_public)
    if (attribution and any(p is None for p in supplied)) or (
        not attribution and any(p is not None for p in supplied)
    ):
        raise ValueError("Attribution alone requires all verified joint control paths")
    return ATTRIBUTION_ARMS if attribution else ("joint",)


# Run only the registered new joint or attribution accounts from saved forecasts.
def run(
    snapshot,
    provenance_path,
    daily_dir,
    old_directory,
    proof_path,
    public_path,
    output,
    source_revision,
    source_manifest,
    *,
    attribution=False,
    joint_directory=None,
    joint_proof=None,
    joint_public=None,
):
    arms = experiment_arms(attribution, joint_directory, joint_proof, joint_public)
    identity = prior.authenticate_source(source_revision, source_manifest)
    root = Path(__file__).resolve().parents[2]
    files = prior.source_hashes()
    for name in (
        "backend/market/cash_selection_study.py",
        "backend/market/learned_cash_selection.py",
        "backend/cli/market_cash_selection_study.py",
        "docs/research/joint-cash-selection-plan-2026-10-03.md",
    ):
        files[name] = digest(root / name)
    if attribution:
        name = "docs/research/cash-selection-attribution-plan-2026-10-03.md"
        files[name] = digest(root / name)
    manifest = json.loads(Path(source_manifest).read_text())
    if any(manifest["files"].get(name) != value for name, value in files.items()):
        raise ValueError("Joint source/registered contract differs from manifest")
    public, original = authenticate_prior(old_directory, proof_path, public_path)
    if digest(snapshot) != prior.SNAPSHOT_SHA256:
        raise ValueError("Fixed original snapshot required")
    panel, grades, eligible, inputs = retention_inputs.load(
        snapshot, provenance_path, daily_dir
    )
    if panel.dates[-1] != prior.END or prior.START not in panel.dates:
        raise ValueError("Original complete fixed evaluation window required")
    relative, spy, curves = saved_arrays(old_directory, panel, public, inputs, original)
    first = int(np.searchsorted(panel.dates, prior.START))
    joint_rows = []
    if attribution:
        joint_rows, _ = authenticate_joint(
            joint_directory, joint_proof, joint_public, panel.dates[first:]
        )
    output = Path(output)
    output.mkdir(exist_ok=False)
    (output / "journals").mkdir()
    provenance = {
        "source_revision": source_revision,
        "source_identity": identity,
        "source_sha256": files,
        "original_inputs": inputs,
        "saved_forecast_source": PRIOR_REVISION,
        "saved_artifacts": PRIOR_ARTIFACTS,
        "prior_result_sha256": PRIOR_RESULT,
        "prior_proof_sha256": PRIOR_PROOF,
        "prior_public_sha256": PRIOR_PUBLIC,
        "adoption": False,
        "selection": "reconstructed_current_vintage_not_historical_publications",
        "execution": "legacy_daily_not_current_intraday_or_broker_parity",
        **(
            {
                "attribution_modes": ATTRIBUTION_ARMS,
                "joint_result_sha256": JOINT_RESULT,
                "joint_proof_sha256": JOINT_PROOF,
                "joint_public_sha256": JOINT_PUBLIC,
                "joint_curves_sha256": JOINT_CURVES,
            }
            if attribution
            else {}
        ),
    }
    _write_json(output / "inputs.json", provenance)
    _write_json(
        output / "status.json",
        {
            "stage": "verified_inputs",
            "completed": 0,
            "source_revision": source_revision,
        },
    )
    report = SimpleNamespace(panel=panel, graded=prior._Grades(grades))
    options = dict(
        simulate.LIVE_POLICY,
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_exposure=event_risk.live_path(panel),
        event_lifecycle=True,
        midcycle_redeploy=True,
        redeploy_buffer=float(paper.REDEPLOY_BUFFER),
        allocator=policy_v5.allocator(eligible),
        since=str(prior.START),
    )
    accounts, new_curves = [], {}
    count = len(arms) * len(prior.COSTS) * len(prior.OFFSETS)
    for arm, cost, offset in product(arms, prior.COSTS, prior.OFFSETS):
        benchmarks = {name: curves[f"{name}-{cost}"] for name in ("SPY", "QQQ")}
        key = f"{arm}-{cost}-{offset}"
        retention = RetentionAdapter(panel.tickers, eligible, relative, spy, cost)
        selection = CashSelectionAdapter(
            panel.tickers, eligible, relative, spy, cost, dates=panel.dates, mode=arm
        )
        journal = prior._journal(panel, cost, key, provenance)
        result = simulate.run(
            report,
            **options,
            cost_bps=cost,
            rebalance_offset=offset,
            retention_adapter=retention,
            cash_selection_adapter=selection,
            journal=journal,
        )
        archive = prior._archive(journal, output / "journals" / key)
        traded, fees = prior._flows(journal, first)
        decisions = {"selection": selection.events, "retention": retention.events}
        _write_json(output / f"{key}-decisions.json", decisions)
        new_curves[key] = result.equity
        accounts.append(
            {
                "account": key,
                "arm": arm,
                "cost_bps": cost,
                "offset": offset,
                "score": prior.score(
                    result.dates, result.equity, traded, fees, benchmarks
                ),
                "journal": archive,
                "nav_sha256": _array_hash(result.equity),
                "decisions_sha256": digest(output / f"{key}-decisions.json"),
                "decision_counts": {
                    leg: dict(
                        Counter(e.get("reason", e.get("boundary")) for e in events)
                    )
                    for leg, events in decisions.items()
                },
            }
        )
        _write_json(
            output / "status.json",
            {
                "stage": "accounts",
                "completed": len(accounts),
                "last": key,
                "source_revision": source_revision,
            },
        )
        print(f"reconciled {key}: {len(accounts)}/{count}", flush=True)
    np.savez_compressed(output / "curves.npz", dates=panel.dates[first:], **new_curves)
    result = {
        "schema": "cash-selection-attribution-funded/1"
        if attribution
        else "joint-cash-selection-funded/1",
        "source_revision": source_revision,
        "source_sha256": files,
        "saved_forecast_source": PRIOR_REVISION,
        "adoption": False,
        "accounts": accounts,
        "paired_results": []
        if attribution
        else paired_results(accounts, public["accounts"]),
        "reused_controls": {
            "public_sha256": PRIOR_PUBLIC,
            "result_sha256": PRIOR_RESULT,
        },
        "artifacts": {
            name: digest(output / name) for name in ("inputs.json", "curves.npz")
        },
    }
    if attribution:
        paired, interactions = attribution_results(
            accounts, joint_rows, public["accounts"]
        )
        result.update(
            paired_results=paired,
            interactions=interactions,
            reused_joint={"public_sha256": JOINT_PUBLIC, "result_sha256": JOINT_RESULT},
        )
    _write_json(output / "result.json", result)
    _write_json(
        output / "status.json",
        {
            "stage": "complete",
            "accounts": len(accounts),
            "result_sha256": digest(output / "result.json"),
            "source_revision": source_revision,
        },
    )
    return result
