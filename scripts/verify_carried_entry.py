"""Independently reconstruct carried timing decisions and funded saved ledgers."""

import hashlib
import json
import statistics
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from verify_timing_side_ablation import PRIMARY_SHA, verifier


# Reconstruct plans, every first eligible action, funding and daily wealth from traces.
def audit(v, evidence, panel, data, opens, support, first, phase, carry, forecasts=None):
    tickers = panel["symbols"].tolist()
    dates, close = panel["dates"].astype("datetime64[D]"), panel["adj_close"]
    index = {name: i for i, name in enumerate(tickers)}
    curves = v.curves_from(evidence, len(dates) - first + 1)
    by_date = v.traces_by_date(evidence["intent_trace"], index, phase)
    shares, flows = np.zeros(len(tickers)), np.zeros(len(tickers))
    cash, budget = 1.0, 0.0
    entries, attempted, totals = {}, set(), Counter()
    for day in range(first, len(dates)):
        plan = (day - first) % 20 == phase
        new = by_date.pop(str(dates[day]), [])
        v.require(plan or not new, "Off-cycle plan")
        if plan:
            if entries:
                v.audit_outcomes(entries, wanted, shares, initial, totals)
            prior = close[day - 1]
            nav = cash + float(np.sum(shares * np.nan_to_num(prior)))
            selected = (panel["eligible"][day - 1].astype(bool)
                        & (panel["grades"][day - 1] >= 2) & np.isfinite(prior))
            selected[index["SPY"]] = False
            target = selected * (min(.25, 1 / selected.sum()) if selected.any() else 0)
            wanted = shares.copy()
            known = np.isfinite(prior) & (prior > 0)
            wanted[known] = target[known] * nav / prior[known]
            entries = {index[r["symbol"]]: r for r in new}
            v.require(set(entries) == set(np.flatnonzero(abs(wanted - shares) > 1e-10)),
                      "Missing or extra plan intent")
            budget, initial, attempted = cash, shares.copy(), set()
            for j, row in entries.items():
                for key, expected in {
                    "prior_nav": nav, "prior_price": float(prior[j]),
                    "initial_shares": float(shares[j]), "desired_shares": float(wanted[j]),
                    "morning_cash": cash, "target_weight": float(target[j]),
                    "side": "buy" if wanted[j] > shares[j] else "sell",
                }.items():
                    v.equal(row[key], expected, key)
                v.require(row["attempt_clock"] is None or
                          (type(row["attempt_clock"]) is int and 0 <= row["attempt_clock"] <= 24),
                          "Invalid attempt clock")
        turnover = 0.0
        for clock in range(25) if support[day] and (plan or carry) and entries else ():
            observed = data["current_close"][day, clock]
            actual = {j: r for j, r in entries.items()
                      if r.get("attempt_date") == str(dates[day]) and r["attempt_clock"] == clock}
            blocked = np.any((shares > 0) & (~np.isfinite(observed) | (observed <= 0)))
            expected = set()
            if not blocked:
                for j, row in entries.items():
                    if j in attempted or abs(wanted[j] - shares[j]) <= 1e-10:
                        continue
                    buy = row["side"] == "buy"
                    if not plan and not buy:
                        continue
                    if not np.isfinite(observed[j]) or observed[j] <= 0:
                        continue
                    crossed = np.isfinite(opens[day, j]) and opens[day, j] > 0 and (
                        observed[j] <= opens[day, j] * .99 if buy
                        else observed[j] >= opens[day, j] * 1.01)
                    if buy and forecasts is not None:
                        crossed = np.isfinite(forecasts[day, clock, j]) and forecasts[day, clock, j] <= 0
                    if crossed or (clock == 24 and (not carry or not buy)):
                        expected.add(j)
            v.require(set(actual) == expected, "First causal attempt differs")
            if blocked:
                continue
            nav = cash + float(np.sum(shares * np.nan_to_num(observed)))
            v.audit_funding(actual, wanted, shares, budget, 0)
            for j, row in actual.items():
                v.equal(row["observed_price"], float(observed[j]), "Observed price")
                price = float(data["next_open"][day, clock, j])
                valid = np.isfinite(price) and price > 0
                v.equal(row["realized_price"], float(price) if valid else None, "Future fill")
                v.require(row["terminal_action"] == (clock == 24), "Clock identity")
                delta = row["filled_delta"]
                dollars = delta * price if valid else 0.0
                v.require(valid or delta == 0, "Unavailable fill")
                v.equal(row["fee"], 0, "Zero-cost requirement")
                shares[j] += delta
                cash -= dollars
                flows[j] -= dollars
                budget -= max(0, dollars)
                attempted.add(j)
                turnover += abs(dollars) / nav
            v.require(cash >= -1e-9 and budget >= -1e-9 and np.all(shares >= -1e-9),
                      "Unfunded trade")
        slot = day - first + 1
        v.equal(curves["cash"][slot], cash, "Daily cash")
        v.equal(curves["nav"][slot], cash + float(np.sum(shares * np.nan_to_num(close[day]))),
                "Daily wealth")
        v.equal(curves["turnover"][slot], turnover, "Daily turnover")
        v.equal(curves["fees"][slot], 0, "Daily fee")
        if entries and not carry:
            v.audit_outcomes(entries, wanted, shares, initial, totals)
            entries = {}
    if entries:
        v.audit_outcomes(entries, wanted, shares, initial, totals)
    v.require(not by_date, "Unvisited plan")
    for key in ("completed_intents", "expired_partial", "expired_unfilled"):
        v.equal(evidence["counts"][key], totals[key], key)
    for j, ticker in enumerate(tickers):
        v.equal(evidence["stocks"][ticker]["net_gain_initial_nav_units"],
                flows[j] + shares[j] * np.nan_to_num(close[-1, j]), "Stock wealth")
    return curves["nav"]


# Authenticate the original inputs before auditing all forty saved accounts.
def main(forecasts=None, controls=None):
    v = verifier()
    primary_path = Path("/primary/evaluation.json")
    v.require(v.file_hash(primary_path) == PRIMARY_SHA, "Original report hash")
    source = v.read_json(primary_path)["identity"]["source"]

    # Check pinned source content independently of checkout metadata.
    def original_bytes(root, revision, name):
        raw = (Path("/app") / name).read_bytes()
        v.require(hashlib.sha256(raw).hexdigest() == source["files"][name], "Source hash")
        return raw

    v.git_bytes = original_bytes
    args = SimpleNamespace(snapshot=Path("/inputs/portfolio.npz"),
                           provenance=Path("/inputs/portfolio.json"), cubes=Path("/cubes"),
                           prepared=Path("/prepared"), source_root=Path("/app"))
    panel, data, opens, support = v.verify_inputs(args, source)
    identity = v.read_json(Path("/output/identity.json"))
    for name, expected in identity["source"].items():
        v.require(v.file_hash(Path("/experiment") / name) == expected, "Producer hash")
    dates = panel["dates"].astype("datetime64[D]")
    first = int(np.flatnonzero(dates == np.datetime64("2018-02-01"))[0])
    comparison = dates[first - 1:]
    gains = {name: [] for name in ("all", "early", "later", "reused_recent")}
    accounts = []
    for phase in range(20):
        navs = {}
        for name in ("control", "carry"):
            root = controls if name == "control" and controls is not None else Path("/output")
            path = root / f"{name}-{phase}.json"
            evidence = v.read_json(path)
            navs[name] = audit(v, evidence, panel, data, opens, support, first, phase,
                               name == "carry", forecasts if name == "carry" else None)
            accounts.append({"name": name, "phase": phase, "sha256": v.file_hash(path),
                             "intents": len(evidence["intent_trace"])})
        for name, start, end in (
            ("all", "2018-02-01", "2026-09-30"), ("early", "2018-02-01", "2020-12-31"),
            ("later", "2021-01-01", "2026-09-30"), ("reused_recent", "2026-08-17", "2026-09-30")
        ):
            indices = np.flatnonzero((comparison >= np.datetime64(start)) & (comparison <= np.datetime64(end)))
            lo, hi = indices[0] - 1, indices[-1]
            gains[name].append(float(navs["carry"][hi] / navs["carry"][lo]
                                     - navs["control"][hi] / navs["control"][lo]))
    print(json.dumps({"accounts": accounts, "adoption_eligible": False,
                      "summary": {key: {"median_paired_gain_pp": statistics.median(values) * 100,
                                         "winning_phases": sum(x > 0 for x in values), "phases": 20}
                                  for key, values in gains.items()}}, indent=2))


if __name__ == "__main__":
    main()
