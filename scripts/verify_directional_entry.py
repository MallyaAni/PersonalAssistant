"""Audit direction-isolated decisions with the original independent ledger."""

import hashlib
import json
import statistics
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np

from verify_timing_side_ablation import PRIMARY_SHA, VERIFIER_SHA


# Reconstruct scalar directional decisions while preserving original gate counters.
def audit_pending(v, mode, entries, pending, observed, wanted, shares, predictions,
                  opening, clock, budget, cost, method, attempts, totals):
    for j in pending:
        known = np.isfinite(observed[j]) and observed[j] > 0
        open_known = np.isfinite(opening[j]) and opening[j] > 0
        buy = entries[j]["side"] == "buy"
        base = known and (clock == 24 or (open_known and (
            observed[j] <= opening[j] * .99 if buy else observed[j] >= opening[j] * 1.01)))
        act = base
        if known and buy and clock < 24 and np.isfinite(predictions[j, 0]):
            learned = predictions[j, 0] <= 0
            act = (base or learned) if mode == "advance" else (base and learned)
        v.require((j in attempts) == act, "Direction-isolated action mismatch")
        if known and clock < 24:
            totals["opening_unavailable"] += int(not open_known)
            totals["waiting_decisions"] += int(open_known and not base)


# Authenticate all inputs and compare both saved interventions across all periods.
def main():
    raw = Path("/audit/verify_sequential_execution_evidence_v3.py").read_bytes()
    if hashlib.sha256(raw).hexdigest() != VERIFIER_SHA:
        raise ValueError("Independent verifier hash changed")
    source = raw.decode()
    for key in ("cash_limited_decisions", "forecast_unavailable"):
        field = f'            "{key}",\n'
        if source.count(field) != 1:
            raise ValueError("Unexpected original diagnostic declaration")
        source = source.replace(field, "")
    v = ModuleType("original_ledger")
    exec(compile(source, "original_ledger", "exec"), v.__dict__)
    primary = Path("/primary/evaluation.json")
    v.require(v.file_hash(primary) == PRIMARY_SHA, "Primary hash")
    report = v.read_json(primary)
    identity = report["identity"]["source"]

    # Verify frozen source bytes independently of the checkout's Git metadata.
    def original_bytes(root, revision, name):
        raw = (Path("/app") / name).read_bytes()
        v.require(hashlib.sha256(raw).hexdigest() == identity["files"][name], "Source hash")
        return raw

    v.git_bytes = original_bytes
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"), cubes=Path("/cubes"),
                           prepared=Path("/prepared"), source_root=Path("/app"))
    panel, data, opens, support = v.verify_inputs(args, identity)
    path = Path("/primary/models/predictions.npz")
    v.require(v.file_hash(path) == report["identity"]["forecast_sha256"], "Forecast hash")
    with np.load(path, allow_pickle=False) as saved:
        forecasts = saved["predictions"]
        v.require(np.array_equal(saved["dates"], data["dates"]), "Forecast calendar")
    producer = v.read_json(Path("/output/identity.json"))
    v.require(v.file_hash(Path("/experiment/directional_entry.py")) == producer["source_sha256"],
              "Producer changed")
    dates = panel["dates"].astype("datetime64[D]")
    first = int(np.flatnonzero(dates == np.datetime64("2018-02-01"))[0])
    comparison = dates[first - 1:]
    controls = {row["phase"]: np.asarray(row["control"]["curves"]["nav"])
                for row in report["phases"] if row["cost_bps"] == 0}
    result = {"adoption_eligible": False, "accounts": [], "summary": {}}
    for mode in ("advance", "defer"):
        # Bind this intervention to the unchanged ledger and funding reconstruction.
        def pending(*args):
            return audit_pending(v, mode, *args)

        v.audit_pending = pending
        gains = {key: [] for key in ("all", "early", "later", "reused_recent")}
        for phase in range(20):
            path = Path("/output") / f"{mode}-{phase}.json"
            evidence = v.read_json(path)
            curves = v.curves_from(evidence, len(comparison))
            v.verify_ledger(evidence, curves, panel, data, forecasts, opens,
                            support, first, phase, 0, "control")
            nav, control = curves["nav"], controls[phase]
            for key, start, end in (
                ("all", "2018-02-01", "2026-09-30"), ("early", "2018-02-01", "2020-12-31"),
                ("later", "2021-01-01", "2026-09-30"), ("reused_recent", "2026-08-17", "2026-09-30")
            ):
                indices = np.flatnonzero((comparison >= np.datetime64(start)) & (comparison <= np.datetime64(end)))
                lo, hi = indices[0] - 1, indices[-1]
                gains[key].append(float(nav[hi] / nav[lo] - control[hi] / control[lo]))
            result["accounts"].append({"mode": mode, "phase": phase, "sha256": v.file_hash(path),
                                       "intents": len(evidence["intent_trace"])})
        result["summary"][mode] = {key: {"median_paired_gain_pp": 100 * statistics.median(values),
                                        "winning_phases": sum(x > 0 for x in values), "phases": 20}
                                   for key, values in gains.items()}
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
