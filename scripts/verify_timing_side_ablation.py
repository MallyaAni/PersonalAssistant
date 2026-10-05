"""Audit saved side interventions using independent original ledger arithmetic."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
from types import ModuleType, SimpleNamespace

import numpy as np

VERIFIER_SHA = "73946b7624930d32a16e82bb6d2c882bb80ad47405289575dcf8b1099c8c5e2a"
PRIMARY_SHA = "2a8276f0c5e677292a600c260e87016d39029ee33359cdfae9c228c70fe22f11"


# Load pinned independent accounting, adapting only the absent diagnostic counter.
def verifier():
    raw = Path("/audit/verify_sequential_execution_evidence_v3.py").read_bytes()
    if hashlib.sha256(raw).hexdigest() != VERIFIER_SHA:
        raise ValueError("Independent verifier changed")
    source = raw.decode()
    field = '            "cash_limited_decisions",\n'
    if source.count(field) != 1:
        raise ValueError("Expected one diagnostic field declaration")
    # The new producer did not emit this counter; all funding assertions stay intact.
    source = source.replace(field, "")
    module = ModuleType("independent_ledger")
    exec(compile(source, "independent_ledger", "exec"), module.__dict__)
    return module


# Audit both sides with original scalar policy rules, independent of the producer.
def side_pending(v, original, learned_side, entries, pending, observed, wanted,
                 shares, predictions, opening, clock, budget, cost, method,
                 attempts, totals):
    for side in ("buy", "sell"):
        subset = {stock for stock in pending if entries[stock]["side"] == side}
        subcounts = Counter()
        original(entries, subset, observed, wanted, shares, predictions, opening,
                 clock, budget, cost, "candidate" if side == learned_side else "control",
                 {stock for stock in attempts if stock in subset}, subcounts)
        totals.update(subcounts)


# Verify original data and every recorded fill, then summarize paired account gains.
def main():
    v = verifier()
    raw = Path("/primary/evaluation.json").read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRIMARY_SHA:
        raise ValueError("Original economic report changed")
    primary = json.loads(raw)
    source = primary["identity"]["source"]

    # Read only original hash-checked source bytes instead of relying on Git metadata.
    def original_bytes(root, revision, name):
        data = (Path("/app") / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != source["files"][name]:
            raise ValueError("Original source file changed")
        return data

    v.git_bytes = original_bytes
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"), cubes=Path("/cubes"),
                           prepared=Path("/prepared"), source_root=Path("/app"))
    panel, dataset, opened, supported = v.verify_inputs(args, source)
    prediction_path = Path("/primary/models/predictions.npz")
    if v.file_hash(prediction_path) != primary["identity"]["forecast_sha256"]:
        raise ValueError("Original forecast archive changed")
    predictions = v.read_npz(prediction_path)["predictions"]
    dates = panel["dates"].astype("datetime64[D]")
    first = int(np.flatnonzero(dates == np.datetime64("2018-02-01"))[0])
    comparison_dates = dates[first - 1:]
    controls = {r["phase"]: r["control"]["curves"]["nav"]
                for r in primary["phases"] if r["cost_bps"] == 0}
    original_pending = v.audit_pending
    result = {"primary_sha256": PRIMARY_SHA, "verifier_sha256": VERIFIER_SHA,
              "cost_bps": 0, "adoption_eligible": False, "accounts": [], "summary": {}}
    for side in ("buy", "sell"):
        # Bind the intervention side while preserving the original accounting checker.
        def audit(*args):
            return side_pending(v, original_pending, side, *args)

        v.audit_pending = audit
        gains = {key: [] for key in ("all", "early", "later", "reused_recent")}
        for phase in range(20):
            path = Path("/output") / f"{side}-{phase}.json"
            evidence = v.read_json(path)
            if (evidence["side"], evidence["phase"], evidence["cost_bps"],
                evidence["primary_sha256"]) != (side, phase, 0, PRIMARY_SHA):
                raise ValueError("Saved account identity changed")
            curves = v.curves_from(evidence, len(comparison_dates))
            v.verify_ledger(evidence, curves, panel, dataset, predictions, opened,
                            supported, first, phase, 0, side)
            nav = curves["nav"]
            control = np.asarray(controls[phase])
            for label, start, end in (
                ("all", "2018-02-01", "2026-09-30"),
                ("early", "2018-02-01", "2020-12-31"),
                ("later", "2021-01-01", "2026-09-30"),
                ("reused_recent", "2026-08-17", "2026-09-30"),
            ):
                indices = np.flatnonzero((comparison_dates >= np.datetime64(start)) &
                                         (comparison_dates <= np.datetime64(end)))
                lo, hi = int(indices[0]) - 1, int(indices[-1])
                gains[label].append(float(nav[hi] / nav[lo] - control[hi] / control[lo]))
            result["accounts"].append({"side": side, "phase": phase,
                                       "sha256": v.file_hash(path),
                                       "intents": len(evidence["intent_trace"])})
        result["summary"][side] = {
            label: {"median_paired_gain_pp": statistics.median(values) * 100,
                    "min_pp": min(values) * 100, "max_pp": max(values) * 100,
                    "winning_phases": sum(value > 0 for value in values), "phases": 20}
            for label, values in gains.items()
        }
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
