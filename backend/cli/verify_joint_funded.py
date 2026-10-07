"""Independently verify saved funded accounts; never choose or simulate a trade.

Partial progress is an authenticated prefix, not a completed study. Physical
account arithmetic and receipt consistency do not prove predictive accuracy,
broker fills, historical publication completeness or adoption eligibility.
"""

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.cli import verify_actual_policy_timing as ledger
from backend.market import calendar

POLICY = "joint-stock-risk-funded/1-research"
MATURITY_POLICY = "joint-stock-risk-funded/2-maturity-shadow"
CALIBRATED_POLICY = "joint-stock-risk-funded/3-log-calibration-research"
HORIZON = "next_open_to_following_open_arithmetic_return"
PROTOCOL = "docs/research/joint-funded-account-plan-2026-10-04.md"
MARKET_CONTEXT = [
    "spy_return_20",
    "spy_drawdown_252",
    "spy_volatility_20",
    "breadth_20",
]
MARKET_PROTOCOL = "docs/research/market-conditioned-holding-plan-2026-10-05.md"
MARKET_TIMED_POLICY = (
    "joint-stock-risk-funded/5-market-conditioned-probability-timing-research"
)
CANDIDATES = {
    POLICY: PROTOCOL,
    MATURITY_POLICY: "docs/research/risk-qualified-funded-plan-2026-10-04.md",
    CALIBRATED_POLICY: (
        "docs/research/conditional-holding-calibration-plan-2026-10-05.md"
    ),
    MARKET_TIMED_POLICY: MARKET_PROTOCOL,
}
RECEIPT_PROTOCOLS = dict(CANDIDATES)


# Authenticate array dtype, shape and bytes without importing the forecast producer.
def _market_hash(array):
    value = np.ascontiguousarray(array)
    digest = hashlib.sha256()
    digest.update(str(value.dtype).encode())
    digest.update(json.dumps(value.shape).encode())
    digest.update(value.tobytes())
    return digest.hexdigest()


# Read JSON numbers without silently coercing booleans or missing values.
def _market_numbers(value, shape):
    raw = np.asarray(value, dtype=object)
    ledger.require(
        raw.shape == shape and all(type(x) in (int, float) for x in raw.flat),
        "Typed market calibration numbers required",
    )
    result = raw.astype(float)
    ledger.require(
        np.isfinite(result).all(), "Finite market calibration numbers required"
    )
    return result


# Compare independent arithmetic with a bound derived only from machine precision.
def _market_same(actual, expected, name, *, operations=1):
    actual, expected = np.asarray(actual), np.asarray(expected)
    scale = max(1.0, float(np.max(np.abs(expected))))
    tolerance = 64 * np.finfo(float).eps * max(operations, 1, *expected.shape) * scale
    ledger.require(
        actual.shape == expected.shape
        and np.all(np.abs(actual - expected) <= tolerance),
        "Market calibration arithmetic differs: " + name,
    )


# Verify saved historical calibration algebra without fitting, predicting or trading.
class MarketCalibrationVerifier:
    # Detach the externally authenticated bank and check its original calendar contract.
    def __init__(self, bank, source):
        keys = ("dates", "endpoints", "forecasts", "labels", "features", "support")
        self.bank = {key: np.asarray(bank[key]).copy() for key in keys}
        self.symbols = tuple(bank["symbols"])
        self.source = dict(source)
        dates = self.bank["dates"]
        ledger.require(dates.ndim == 1, "Original daily market dates required")
        size = (len(dates), len(self.symbols))
        ledger.require(
            dates.dtype == np.dtype("datetime64[D]")
            and dates.ndim == 1
            and len(dates) > 2
            and not np.isnat(dates).any()
            and np.all(dates[1:] > dates[:-1])
            and len(set(self.symbols)) == len(self.symbols)
            and "SPY" in self.symbols
            and self.bank["features"].shape == (*size, 13)
            and self.bank["features"].dtype.kind in "fiu"
            and self.bank["support"].shape == size
            and self.bank["support"].dtype == np.dtype("bool")
            and all(
                self.bank[key].shape == size and self.bank[key].dtype.kind in "fiu"
                for key in ("forecasts", "labels")
            ),
            "Original aligned market calibration bank required",
        )
        years, sessions = calendar.reviewed_sessions()
        whole = np.arange(dates[0], dates[-1] + np.timedelta64(1, "D"))
        ledger.require(
            all(day.astype(object).year in years for day in whole)
            and np.array_equal(dates, whole[np.is_busday(whole, busdaycal=sessions)]),
            "Complete reviewed market calibration calendar required",
        )
        endpoints = np.full(len(dates), np.datetime64("NaT", "D"))
        endpoints[:-2] = dates[2:]
        ledger.require(
            self.bank["endpoints"].dtype == endpoints.dtype
            and np.array_equal(self.bank["endpoints"].view("i8"), endpoints.view("i8")),
            "Original D+2 market calibration endpoints required",
        )
        self.market = self.bank["features"][:, self.symbols.index("SPY")][
            :, [1, 5, 4, 12]
        ]
        self.features_sha256 = _market_hash(self.bank["features"])
        self.context_sha256 = _market_hash(self.market)
        for array in self.bank.values():
            array.flags.writeable = False

    # Check source and bank identity even when the recorded opportunity was unavailable.
    def identity(self, sample):
        identity = sample["calibration_identity"]
        ledger.same(sample["policy"], "market-conditioned-joint-holding/1-research")
        ledger.same(identity["policy"], sample["policy"])
        ledger.same(
            identity["source_sha256"],
            self.source["backend/market/market_conditioned_holding.py"],
        )
        ledger.same(
            identity["numerical_source_sha256"],
            self.source["backend/market/market_conditioned_calibration.py"],
        )
        ledger.same(identity["protocol_sha256"], self.source[MARKET_PROTOCOL])
        ledger.same(identity["features_sha256"], self.features_sha256)
        ledger.same(identity["context_sha256"], self.context_sha256)
        ledger.same(identity["context"], MARKET_CONTEXT)
        ledger.require(
            identity["adoption_eligible"] is False
            and identity["confidence_guarantee"] is False,
            "Market calibration limitations missing",
        )
        ledger.same(
            identity["calibration_residuals"], "in_sample_on_genuine_OOS_base_forecasts"
        )

    # Check current context and every recorded stock fit against original admitted rows.
    def check(self, sample):
        self.identity(sample)
        ledger.require(
            sample["status"] == "available",
            "Available historical market receipt required",
        )
        dates = self.bank["dates"]
        hits = np.flatnonzero(dates == np.datetime64(sample["decision_date"], "D"))
        ledger.require(len(hits) == 1, "Historical market observation required")
        day = int(hits[0])
        scenario_receipt(sample, sample["decision_date"], dates)
        current = self.market[day].astype(float)
        ledger.require(
            np.isfinite(current).all()
            and -1 <= current[1] <= 0
            and current[2] >= 0
            and 0 <= current[3] <= 1,
            "Possible current market context required",
        )
        _market_numbers(sample["current_context"], (4,))
        ledger.same(sample["current_context"], current.tolist())
        ledger.same(sample["current_context_sha256"], _market_hash(current))
        ledger.require(
            isinstance(sample["symbols"], list)
            and len(sample["symbols"]) > 0
            and len(set(sample["symbols"])) == len(sample["symbols"]),
            "Unique nonempty market stock list required",
        )
        ledger.same([fit["symbol"] for fit in sample["calibration"]], sample["symbols"])
        ledger.same(len(sample["predictions"]), len(sample["calibration"]))
        first = int(
            np.flatnonzero(
                dates.astype("datetime64[M]") == dates[day].astype("datetime64[M]")
            )[0]
        )
        candidates = np.arange(max(0, first - 756), first)
        mature = candidates[
            ~np.isnat(self.bank["endpoints"][candidates])
            & (
                self.bank["endpoints"][candidates]
                < np.datetime64(sample["label_end_before"], "D")
            )
        ]
        joint = np.ones(len(mature), dtype=bool)
        for fit, prediction in zip(
            sample["calibration"], sample["predictions"], strict=True
        ):
            ledger.require(
                fit["symbol"] in self.symbols and fit["symbol"] not in ("SPY", "QQQ"),
                "Original market stock required",
            )
            stock = self.symbols.index(fit["symbol"])
            mask = (
                self.bank["support"][mature, stock]
                & np.isfinite(self.bank["forecasts"][mature, stock])
                & np.isfinite(self.bank["labels"][mature, stock])
            )
            joint &= mask
            rows = mature[mask]
            ledger.require(
                isinstance(fit["selected_indices"], list)
                and all(type(value) is int for value in fit["selected_indices"]),
                "Typed original market singleton dates required",
            )
            ledger.same(
                fit["selected_indices"],
                rows.tolist(),
                "Original market singleton dates",
            )
            ledger.require(252 <= len(rows) <= 756, "Mature market support required")
            ledger.same(fit["fit_date"], sample["fit_date"])
            ledger.same(fit["label_end_before"], sample["label_end_before"])
            ledger.same(
                fit["maximum_endpoint"], str(self.bank["endpoints"][rows].max())
            )
            self._fit(fit, prediction, rows, day, stock, current)
        ledger.same(
            sample["decision_indices"],
            mature[joint].tolist(),
            "Original simultaneous market dates",
        )

    # Prove the saved least-squares solution and leverage from moment equations only.
    def _fit(self, fit, prediction, rows, day, stock, current):
        ledger.same(fit["policy"], "market-conditioned-holding/1-research")
        ledger.same(
            fit["source_sha256"],
            self.source["backend/market/market_conditioned_calibration.py"],
        )
        ledger.same(fit["protocol_sha256"], self.source[MARKET_PROTOCOL])
        ledger.same(fit["context"], MARKET_CONTEXT)
        ledger.require(
            fit["adoption_eligible"] is False and fit["confidence_guarantee"] is False,
            "Saved fit limitations missing",
        )
        raw, observed = (
            self.bank["forecasts"][rows, stock],
            self.bank["labels"][rows, stock],
        )
        market = self.market[rows].astype(float)
        volatility = self.bank["features"][rows, stock, 4]
        ledger.require(
            np.isfinite(volatility).all()
            and np.all(volatility > 0)
            and np.isfinite(self.bank["features"][day, stock, 4])
            and self.bank["features"][day, stock, 4] > 0,
            "Positive original stock volatility required",
        )
        ledger.require(
            np.all(raw > -1)
            and np.all(observed >= -1)
            and np.isfinite(market).all()
            and np.all((market[:, 1] >= -1) & (market[:, 1] <= 0))
            and np.all(market[:, 2] >= 0)
            and np.all((market[:, 3] >= 0) & (market[:, 3] <= 1)),
            "Possible original market observations required",
        )
        expected = dict(
            zip(
                ("dates", "endpoints", "forecasts", "outcomes", "context"),
                map(
                    _market_hash,
                    (
                        self.bank["dates"][rows],
                        self.bank["endpoints"][rows],
                        raw,
                        observed,
                        market,
                    ),
                ),
                strict=True,
            )
        )
        ledger.same(fit["row_hashes"], expected)
        default = observed == -1
        n, rank = int((~default).sum()), fit["rank"]
        ledger.require(
            type(fit["observations"]) is int
            and fit["observations"] == n
            and type(fit["defaults"]) is int
            and fit["defaults"] == int(default.sum())
            and type(rank) is int
            and 1 <= rank <= 6
            and n > rank,
            "Saved market support and rank differ",
        )
        predictors = np.c_[np.log1p(raw[~default]), market[~default]]
        y = np.log1p(observed[~default])
        center = _market_numbers(fit["center"], (5,))
        scale = _market_numbers(fit["scale"], (5,))
        _market_same(center, predictors.mean(axis=0), "training centers")
        expected_scale = np.max(np.abs(predictors - center), axis=0)
        constant = np.all(predictors == predictors[0], axis=0)
        expected_scale[constant] = 0
        _market_same(scale, expected_scale, "training scales")
        ledger.require(
            np.array_equal(scale == 0, constant), "Saved constant predictor differs"
        )
        design = np.zeros((n, 6))
        design[:, 0] = 1
        active = scale > 0
        design[:, 1 + np.flatnonzero(active)] = (
            predictors[:, active] - center[active]
        ) / scale[active]
        coefficients = _market_numbers(fit["coefficients"], (6,))
        directions = _market_numbers(fit["directions"], (rank, 6))
        singular = _market_numbers(fit["singular_values"], (rank,))
        values = np.linalg.svd(design, compute_uv=False)
        retained = values > np.finfo(float).eps * max(design.shape) * values[0]
        ledger.same(rank, int(retained.sum()), "Saved numerical rank")
        _market_same(singular, values[retained], "singular values")
        _market_same(directions @ directions.T, np.eye(rank), "orthonormal directions")
        _market_same(
            (directions.T * singular**2) @ directions,
            design.T @ design,
            "design Gram matrix",
        )
        _market_same(
            design.T @ (y - design @ coefficients),
            np.zeros(6),
            "least-squares stationarity",
            operations=n,
        )
        _market_same(
            directions.T @ directions @ coefficients,
            coefficients,
            "identified coefficients",
        )
        query_raw = np.r_[np.log1p(self.bank["forecasts"][day, stock]), current]
        constant_tolerance = (
            64 * np.finfo(float).eps * np.maximum(1, np.abs(center[~active]))
        )
        ledger.require(
            np.isfinite(query_raw).all()
            and np.all(
                np.abs(query_raw[~active] - center[~active]) <= constant_tolerance
            ),
            "Current identified market query required",
        )
        query = np.zeros(6)
        query[0] = 1
        query[1 + np.flatnonzero(active)] = (
            query_raw[active] - center[active]
        ) / scale[active]
        _market_same(directions.T @ directions @ query, query, "identified query span")
        ledger.require(
            set(prediction) == {"conditional_log_mean", "residual_multiplier"},
            "Saved market prediction fields differ",
        )
        actual = _market_numbers(
            [prediction["conditional_log_mean"], prediction["residual_multiplier"]],
            (2,),
        )
        expected = np.array(
            [
                query @ coefficients,
                np.sqrt(
                    n
                    / (n - rank)
                    * (1 + np.sum(((directions @ query) / singular) ** 2))
                ),
            ]
        )
        _market_same(actual, expected, "recorded conditional mean and leverage")


# Derive existing grids and the calibration screen without removing missing accounts.
def candidate_grid(dates, *, policy=POLICY):
    ledger.require(policy in CANDIDATES, "Registered candidate policy required")
    prefix = {
        POLICY: "joint",
        MATURITY_POLICY: "maturity",
        CALIBRATED_POLICY: "calibrated",
        MARKET_TIMED_POLICY: "market",
    }[policy]
    return [
        {**row, "arm": policy, "id": f"{prefix}-{row['cost_bps']}-{row['start']}"}
        for row in ledger.fixed_grid(dates)
        if row["arm"] == "rule"
        and (
            policy not in (CALIBRATED_POLICY, MARKET_TIMED_POLICY) or row["start"] == 0
        )
    ]


# Authenticate source bytes and actual image evidence without changing receipts.
def source_proof(spec):
    manifest = ledger.read_json(spec["manifest"], spec["manifest_sha256"])
    ledger.require(
        manifest["git_commit"] == spec["revision"]
        and len(spec["revision"]) == 40
        and len(manifest["files"]) >= 2300,
        "Whole exact producer tree required",
    )
    root = Path(spec["source"])
    for name, expected in manifest["files"].items():
        relative = Path(name)
        ledger.require(
            not relative.is_absolute() and ".." not in relative.parts,
            "Unsafe source manifest path",
        )
        ledger.same(ledger.digest(root / relative), expected, "producer member")
    runtime = ledger.read_json(spec["inspection"], spec["inspection_sha256"])
    ledger.require(
        len(runtime) == 1
        and runtime[0]["Id"] == spec["container_id"]
        and runtime[0]["Image"] == spec["image_id"]
        and runtime[0]["State"]["OOMKilled"] is False,
        "Actual producer container/image evidence differs",
    )
    ledger.require(
        runtime[0]["HostConfig"]["ReadonlyRootfs"] is True
        and runtime[0]["HostConfig"]["NetworkMode"] == "none"
        and any(
            m["Destination"] == "/app"
            and m["Source"] == spec["host_source"]
            and m["RW"] is False
            for m in runtime[0]["Mounts"]
        ),
        "Producer source mount or isolation differs",
    )
    return manifest


# Read one atomic progress snapshot without hiding omitted or reordered accounts.
def read_index(study, grid, identity, *, candidate, policy=POLICY):
    study = Path(study)
    path = study / (
        "report.json" if (study / "report.json").exists() else "progress.json"
    )
    if not path.exists():
        ledger.require(
            not any((study / "accounts").glob("*.json.gz")),
            "Saved accounts lack a progress index",
        )
        return [], {"status": "pending_first_account", "sha256": None}
    digest = ledger.digest(path)
    index = ledger.read_json(path, digest)
    rows = index["accounts"]
    complete = path.name == "report.json"
    ledger.require(
        identity["adoption_eligible"] is False, "Research limitation missing"
    )
    if candidate or complete:
        ledger.require(index["adoption_eligible"] is False, "Index limitation missing")
    if complete:
        expected = (
            "complete_candidate_unverified_controls"
            if candidate
            else "complete_pending_independent_verification"
        )
        ledger.require(
            index["status"] == expected and len(rows) == len(grid),
            "Incomplete final report",
        )
        ledger.same(index["policy"], policy if candidate else ledger.POLICY)
    else:
        ledger.require(index["status"] == "running", "Unexpected partial status")
        ledger.same(index["completed"], len(rows), "completed count")
    if candidate or not complete:
        ledger.same(index["declared"], len(grid), "declared count")
    if candidate:
        ledger.same(index["source"], identity["source"], "candidate source")
    if complete and not candidate:
        ledger.same(index["identity_sha256"], ledger.digest(study / "identity.json"))
    ledger.require(len(rows) <= len(grid), "Extra accounts")
    for row, spec in zip(rows, grid, strict=False):
        ledger.same({key: row[key] for key in spec}, spec, "exact declared prefix")
    return rows, {"status": index["status"], "sha256": digest, "file": path.name}


# Check original scenario maturity without generating predictions or outcomes.
def scenario_receipt(sample, day, dates):
    if sample is None:
        return
    ledger.same(sample["decision_date"], day)
    chosen = sample.get("decision_indices", [])
    ledger.require(
        len(chosen) == len(set(chosen))
        and all(type(i) is int and i >= 0 and i + 2 < len(dates) for i in chosen),
        "Invalid historical scenario indices",
    )
    cutoff = np.datetime64(sample["label_end_before"])
    ledger.require(
        cutoff <= np.datetime64(day) and all(dates[i + 2] < cutoff for i in chosen),
        "Unpublished scenario outcomes",
    )
    month = np.datetime64(day, "M")
    opening = dates[np.flatnonzero(dates.astype("datetime64[M]") == month)[0]]
    ledger.same(sample["fit_date"], str(opening), "Monthly scenario publication")
    ledger.same(
        sample["label_end_before"],
        str(min(opening, np.datetime64("2026-08-17"))),
        "Frozen monthly cutoff",
    )
    ledger.same(sample["joint_dates"], len(chosen), "Scenario row count")
    if sample["status"] == "available":
        ledger.require(len(chosen) >= 252, "Insufficient available joint history")


# Check saved calibration provenance and maturity without fitting or predicting.
def calibration_receipt(sample, source):
    identity = sample["calibration_identity"]
    ledger.same(sample["policy"], "joint-holding-log-calibration/1-research")
    ledger.same(identity["policy"], sample["policy"])
    ledger.same(
        identity["source_sha256"],
        source["backend/market/conditional_holding_calibration.py"],
    )
    ledger.same(identity["protocol_sha256"], source[CANDIDATES[CALIBRATED_POLICY]])
    ledger.require(
        identity["confidence_guarantee"] is False
        and identity["adoption_eligible"] is False
        and identity["calibration_residuals"]
        == "in_sample_on_genuine_OOS_base_forecasts",
        "Calibration limitations differ",
    )
    if sample["status"] != "available":
        return
    fits, predictions = sample["calibration"], sample["predictions"]
    ledger.same([fit["symbol"] for fit in fits], sample["symbols"])
    ledger.same(len(predictions), len(fits), "Calibration prediction count")
    for proof, prediction in zip(fits, predictions, strict=True):
        ledger.same(proof["fit_date"], sample["fit_date"])
        ledger.same(proof["label_end_before"], sample["label_end_before"])
        fit = proof["fit"]
        ledger.require(
            type(proof["calibration_dates"]) is int
            and 252 <= proof["calibration_dates"] <= 756
            and np.datetime64(proof["maximum_endpoint"])
            < np.datetime64(proof["label_end_before"])
            and all(
                type(fit[key]) is int
                for key in ("observations", "defaults", "parameters")
            )
            and fit["observations"] >= 3
            and fit["defaults"] >= 0
            and fit["observations"] + fit["defaults"] == proof["calibration_dates"]
            and fit["parameters"] in (1, 2)
            and fit["observations"] > fit["parameters"],
            "Invalid calibration support or publication",
        )
        values = [
            fit[key]
            for key in ("center", "scale", "slope", "mean", "sum_squared_predictor")
        ]
        ledger.require(
            all(type(value) in (int, float) and np.isfinite(value) for value in values)
            and (
                fit["parameters"] == 1
                and fit["scale"] == fit["slope"] == fit["sum_squared_predictor"] == 0
                or fit["parameters"] == 2
                and fit["scale"] > 0
                and fit["sum_squared_predictor"] > 0
            ),
            "Invalid calibration coefficients",
        )
        for key in (
            "decision_indices_sha256",
            "forecasts_sha256",
            "labels_sha256",
            "endpoints_sha256",
        ):
            value = proof[key]
            ledger.require(
                isinstance(value, str)
                and len(value) == 64
                and all(c in "0123456789abcdef" for c in value),
                "Invalid calibration provenance digest",
            )
        ledger.require(
            all(
                type(value) in (int, float) and np.isfinite(value)
                for value in prediction.values()
            )
            and set(prediction) == {"conditional_log_mean", "residual_multiplier"}
            and prediction["residual_multiplier"] >= 1,
            "Invalid calibration prediction or uncertainty",
        )


# Check qualification partitions and past support without predicting or selecting again.
def qualification_receipt(receipt, day, dates, *, policy=MATURITY_POLICY):
    if policy == POLICY:
        return
    q = receipt["entry_qualification"]
    ledger.same(q["policy"], policy)
    if q.get("status") == "not_evaluated":
        ledger.require(
            receipt["status"] == "unavailable"
            and receipt["reason"]
            in {
                "account_cash_or_equity_unavailable",
                "whole_share_holdings_unavailable",
                "held_mark_unavailable",
                "inconsistent_account_equity",
                "protected_held_risk_unavailable",
            },
            "Fabricated qualification skip",
        )
        ledger.same(q["reason"], receipt["reason"], "Skipped eligibility reason")
        return
    grades, held, blocked = (
        receipt["grades"],
        receipt["current_weights"],
        receipt["buy_blocked"],
    )
    candidates = sorted(
        s
        for s, grade in grades.items()
        if grade >= 2 or (grade == 1 and held.get(s, 0) > 0)
    )
    mandatory = [s for s in candidates if held.get(s, 0) > 0]
    considered = [s for s in candidates if s not in mandatory]
    ledger.same(q["mandatory_held"], mandatory, "Mandatory held risk")
    ledger.same(q["considered_entrants"], considered, "Original considered entries")
    admitted, excluded = q["admitted_entrants"], q["excluded_entries"]
    ledger.require(
        admitted == sorted(set(admitted))
        and set(admitted).isdisjoint(excluded)
        and set(admitted).isdisjoint(blocked)
        and sorted([*admitted, *excluded]) == considered,
        "Qualification partition changed or held stock excluded",
    )
    ledger.require(
        q["selection_uses_future_outcomes"] is False
        and q["joint_risk_still_required"] is True,
        "Qualification limitation missing",
    )
    for name, exclusion in excluded.items():
        if exclusion["reason"] == "buy_permission_blocked":
            ledger.require(
                name in blocked and "risk" not in exclusion,
                "Fabricated buy permission exclusion",
            )
        else:
            ledger.same(exclusion["reason"], "entry_risk_unavailable")
            ledger.require(
                name not in blocked, "Permission exclusion relabelled as risk"
            )
            risk = exclusion["risk"]
            ledger.same(risk["status"], "unavailable", "Excluded available stock")
            ledger.same(risk["decision_date"], day)
            ledger.same(risk["symbols"], [name])
            ledger.require(
                risk["reason"]
                in {
                    "uncovered_required_stock",
                    "insufficient_joint_history",
                    "missing_current_forecast",
                    "unsupported_volatility_arithmetic",
                    "unsupported_current_or_bank_volatility",
                    "unsupported_scenario_arithmetic",
                    *(
                        ("unsupported_log_calibration",)
                        if policy == CALIBRATED_POLICY
                        else ("unsupported_market_calibration",)
                        if policy == MARKET_TIMED_POLICY
                        else ()
                    ),
                },
                "Unknown risk exclusion",
            )
            if risk["reason"] != "uncovered_required_stock":
                scenario_receipt(risk, day, dates)
            if risk["reason"] == "insufficient_joint_history":
                ledger.require(
                    risk["joint_dates"] < 252, "Fabricated short-history exclusion"
                )
    sample = receipt.get("scenario")
    if sample is not None:
        ledger.same(
            sample["symbols"],
            sorted([*mandatory, *admitted]),
            "Joint request omitted a required stock",
        )
    if receipt["status"] == "available" and (mandatory or admitted):
        ledger.require(
            sample is not None
            and sample["status"] == "available"
            and receipt.get("optimizer", {}).get("certificate", {}).get("certified")
            is True,
            "Qualified exposure lacks joint risk or optimizer certificate",
        )
    for name in excluded:
        ledger.require(
            receipt["targets"].get(name, 0) == 0,
            "Excluded unheld stock received exposure",
        )


# Recover current weights from original marks, including valuation-only assets.
def held_weights(row, index, data):
    prices = dict(zip(data["names"], data["close"][index], strict=True))
    if data.get("passive") is not None:
        prices.update(
            zip(data["passive"]["names"], data["passive"]["close"][index], strict=True)
        )
    return {
        name: qty * prices[name] / row["nav"]
        for name, qty in row["holdings"].items()
        if qty > 0
    }


# Check optional calibration provenance with the original bank for market conditioning.
def candidate_calibration(receipt, source, policy, *, market_calibration=None):
    if policy in (CALIBRATED_POLICY, MARKET_TIMED_POLICY):
        samples = [receipt.get("scenario")]
        samples.extend(
            entry.get("risk")
            for entry in receipt.get("entry_qualification", {})
            .get("excluded_entries", {})
            .values()
        )
        for sample in samples:
            if sample is not None:
                if policy == CALIBRATED_POLICY:
                    calibration_receipt(sample, source)
                else:
                    ledger.require(
                        type(market_calibration) is MarketCalibrationVerifier,
                        "Original authenticated market calibration bank required",
                    )
                    for name in (
                        "backend/market/market_conditioned_holding.py",
                        "backend/market/market_conditioned_calibration.py",
                        MARKET_PROTOCOL,
                    ):
                        ledger.same(market_calibration.source[name], source[name])
                    market_calibration.identity(sample)
                    if sample["status"] == "available":
                        market_calibration.check(sample)


# Check market-policy routing while leaving registered next-open receipts unchanged.
def candidate_order_routing(account, entry, receipt, source, day, policy):
    if policy != MARKET_TIMED_POLICY:
        return
    timing = "live-probability-timing/1-research"
    ledger.same(receipt["timing_policy"], timing)
    ledger.same(
        receipt["timing_source_sha256"],
        source["backend/market/live_probability_timing.py"],
    )
    ledger.same(receipt["timing_horizon"], "one_decision_log_price_advantage")
    orders = [row for row in account["intents"] if row["session"] == day]
    expected = {}
    ordinary = False
    for row in orders:
        delayed = (
            row["symbol"] not in receipt["company_exits"]
            and not row.get("event_id")
            and not row.get("priority")
        )
        expected[row["client_order_id"]] = "dip_or_close" if delayed else "next_open"
        ledger.same(row["execution_timing"], expected[row["client_order_id"]])
        if delayed:
            ledger.same(row.get("timing_policy"), timing)
            ordinary = True
        else:
            ledger.require("timing_policy" not in row, "Mandatory exit delayed")
    ledger.same(entry["execution_rule"], timing if ordinary else "next_open")
    if expected:
        routing = receipt["execution_timing"]
        ledger.same(routing["ordinary"], timing)
        ledger.same(routing["company_exit"], "next_open")
        ledger.same(routing["orders"], expected, "Original order routing")
    else:
        ledger.require(
            "execution_timing" not in receipt,
            "Routing fabricated without original orders",
        )


# Check ordinary receipts against original permissions and observed funded accounts.
def candidate_receipts(
    account, data, source, *, policy=POLICY, market_calibration=None
):
    ledger.require(policy in RECEIPT_PROTOCOLS, "Registered receipt policy required")
    sessions = {row["session"]: row for row in account["sessions"]}
    checked = events = 0
    for night in account["nightlies"]:
        day = night["session"]
        clock = datetime.combine(
            datetime.fromisoformat(day).date(),
            calendar.session_close(datetime.fromisoformat(day).date()),
            calendar.NEW_YORK,
        ) + timedelta(minutes=1)
        ledger.require(
            ledger.aware(night["at"]) == clock, "Nightly decision clock differs"
        )
        if night["status"] != "planned":
            ledger.require(
                night["status"] == "nightly_broker_unavailable",
                "Unknown nightly status",
            )
            continue
        entry = night["entry"]
        ledger.same(entry["policy"], policy, "nightly policy")
        ledger.same(entry["session"], day)
        state = entry["joint_funded"]
        if state.get("status") == "event_priority":
            ledger.same(state["policy"], policy)
            events += 1
            continue
        receipt = state["receipt"]
        ledger.same(state["policy"], policy)
        ledger.same(state["as_of"], day)
        ledger.same(state["targets"], receipt["targets"], "persisted targets")
        ledger.same(receipt["policy"], policy)
        ledger.same(
            receipt["source_sha256"], source["backend/market/joint_funded_policy.py"]
        )
        ledger.same(receipt["protocol_sha256"], source[RECEIPT_PROTOCOLS[policy]])
        candidate_calibration(
            receipt, source, policy, market_calibration=market_calibration
        )
        candidate_order_routing(account, entry, receipt, source, day, policy)
        ledger.same(receipt["horizon"], HORIZON)
        ledger.same(receipt["session"], day)
        ledger.same(receipt["cost_bps"], account["cost_bps"])
        ledger.require(
            receipt["adoption_eligible"] is False, "Candidate adoption flag differs"
        )
        row = sessions[day]
        ledger.same(receipt["observed_cash"], row["cash"], "observed funding")
        ledger.same(receipt["observed_equity"], row["nav"], "observed wealth")
        index = int(np.flatnonzero(data["dates"] == np.datetime64(day))[0])
        grades = {
            name: int(data["grades"][index, column])
            for column, name in enumerate(data["names"])
            if name not in ("SPY", "QQQ")
            and data["eligible"][index, column]
            and data["grades"][index, column] >= 0
            and np.isfinite(data["close"][index, column])
        }
        ledger.same(receipt["grades"], grades, "original grade permissions")
        weights = receipt["current_weights"]
        exits = sorted(name for name in weights if grades.get(name) == 0)
        protected = sorted(name for name in weights if name not in grades)
        ledger.same(receipt["company_exits"], exits)
        ledger.same(receipt["protected_holdings"], protected)
        if row["nav"] is not None and row["nav"] > 0:
            expected = held_weights(row, index, data)
            if receipt["reason"] != "held_mark_unavailable":
                ledger.same(weights, expected, "observed held weights")
                ledger.same(
                    receipt["reserved_wealth"],
                    row["nav"] - row["price_nav"],
                    "unspendable wealth",
                )
        targets = receipt["targets"]
        ledger.require(
            all(np.isfinite(value) and value >= 0 for value in targets.values()),
            "Invalid target weights",
        )
        for name, target in targets.items():
            old = weights.get(name, 0)
            ledger.require(
                target <= old + 1e-10
                or (grades.get(name, -1) >= 2 and name not in receipt["buy_blocked"]),
                "Ordinary add violates permission",
            )
            if name in protected:
                ledger.same(target, old, "Protected holding changed")
        scenario_receipt(receipt.get("scenario"), day, data["dates"])
        qualification_receipt(receipt, day, data["dates"], policy=policy)
        if receipt["status"] == "available" and receipt.get("optimizer") is not None:
            optimizer = receipt["optimizer"]
            ledger.require(
                optimizer["status"] == "optimized"
                and optimizer["certificate"]["certified"] is True,
                "Missing optimizer certificate",
            )
        if receipt.get("execution") is not None:
            ledger.require(
                receipt["execution"]["projection_is_fill"] is False,
                "Projection relabelled as fill",
            )
        checked += 1
    return {"ordinary_receipts": checked, "event_priority_receipts": events}


# Fold each completed saved account and independently recompute every declared score.
def verify_rows(
    study,
    rows,
    data,
    *,
    candidate=False,
    source=None,
    policy=POLICY,
    market_calibration=None,
):
    checked = []
    for row in rows:
        spec = {
            key: row[key]
            for key in (
                "arm",
                "cost_bps",
                "start",
                "first",
                "last",
                "first_session",
                "id",
            )
        }
        account = ledger.read_account(Path(study), row)
        counts = ledger.reconcile_account(
            account, spec, data, account_policy=policy if candidate else ledger.POLICY
        )
        receipt_counts = (
            candidate_receipts(
                account,
                data,
                source,
                policy=policy,
                market_calibration=market_calibration,
            )
            if candidate
            else {}
        )
        scores = {
            name: ledger.independent_score(account, lower, upper)
            for name, lower, upper in ledger.WINDOWS
        }
        ledger.same(row["scores"], scores, "independent account scores")
        checked.append(
            {
                **spec,
                "sha256": row["sha256"],
                "scores": scores,
                "counts": counts,
                **receipt_counts,
            }
        )
    return checked


# Retain all fixed comparisons with explicit missing accounts or wealth paths.
def paired_results(candidates, controls, grid, *, references=("rule", "SPY", "QQQ")):
    ledger.require(
        len(references) == len(set(references))
        and set(references) <= {"rule", "boosting", "ridge", "SPY", "QQQ"},
        "Registered unique comparison arms required",
    )
    candidate = {(row["cost_bps"], row["start"]): row for row in candidates}
    control = {(row["cost_bps"], row["start"], row["arm"]): row for row in controls}
    ledger.require(
        len(candidate) == len(candidates) and len(control) == len(controls),
        "Duplicate comparison accounts",
    )
    result = []
    for spec in grid:
        key = (spec["cost_bps"], spec["start"])
        for reference in references:
            for window, _, _ in ledger.WINDOWS:
                left, right = candidate.get(key), control.get((*key, reference))
                a, b = (
                    (left["scores"][window] if left else None),
                    (right["scores"][window] if right else None),
                )
                status = (
                    "pending_candidate"
                    if a is None
                    else "pending_control"
                    if b is None
                    else "paired_complete_wealth"
                    if a["status"] == b["status"] == "complete"
                    else "paired_incomplete_wealth"
                )
                gains = (
                    a is not None
                    and b is not None
                    and a.get("total_gain") is not None
                    and b.get("total_gain") is not None
                )
                if (
                    reference in ledger.BENCHMARKS
                    and b is not None
                    and b.get("benchmark_reference_available") is not True
                ):
                    status = "benchmark_entry_unavailable"
                    gains = False
                result.append(
                    {
                        "cost_bps": key[0],
                        "start": key[1],
                        "reference": reference,
                        "window": window,
                        "status": status,
                        "candidate": a,
                        "control": b,
                        "funded_gain_difference": a["total_gain"] - b["total_gain"]
                        if gains
                        else None,
                    }
                )
    return result


# Verify frozen accounts with caller-authenticated original market bank when required.
def verify(config, output, *, market_calibration=None):
    output = Path(output)
    ledger.require(
        not output.exists()
        and not output.is_symlink()
        and all(
            not output.resolve().is_relative_to(Path(config[role]["study"]).resolve())
            for role in ("candidate", "control")
        ),
        "Fresh external independent proof required",
    )
    manifests = {role: source_proof(config[role]) for role in ("candidate", "control")}
    cstudy, study = Path(config["candidate"]["study"]), Path(config["control"]["study"])
    identity = ledger.read_json(study / "identity.json")
    admission = ledger.read_json(config["admission"], config["admission_sha256"])
    inputs = ledger.read_json(cstudy / "inputs.json")
    identity_hash = ledger.digest(study / "identity.json")
    input_hash = ledger.digest(cstudy / "inputs.json")
    policy = config.get("candidate_policy", POLICY)
    ledger.require(
        policy in CANDIDATES
        and inputs["policy"] == policy
        and inputs["adoption_eligible"] is False,
        "Candidate identity differs",
    )
    if policy != POLICY:
        ledger.same(admission["candidate_policy"], policy, "Variant admission")
    if policy == MARKET_TIMED_POLICY:
        ledger.require(
            type(market_calibration) is MarketCalibrationVerifier,
            "Original authenticated market calibration bank required",
        )
    ledger.require(
        identity["policy"] == ledger.POLICY
        and identity["protocol_sha256"] == ledger.PROTOCOL_SHA
        and identity["adoption_eligible"] is False
        and identity["models_fitted"] == 0,
        "Original research identity differs",
    )
    ledger.same(manifests["control"]["files"][ledger.PROTOCOL], ledger.PROTOCOL_SHA)
    ledger.same(inputs["source"], admission["source"])
    ledger.same(
        identity["source"],
        {
            "git_commit": config["control"]["revision"],
            "files": len(manifests["control"]["files"]),
            "manifest_sha256": config["control"]["manifest_sha256"],
        },
    )
    ledger.same(admission["source"]["source_revision"], config["candidate"]["revision"])
    ledger.same(
        admission["source"]["manifest_sha256"], config["candidate"]["manifest_sha256"]
    )
    ledger.same(
        admission["source"]["source_files"], len(manifests["candidate"]["files"])
    )
    ledger.same(
        admission["source"]["runner_sha256"],
        ledger.digest(config["candidate"]["runner"]),
    )
    ledger.require(
        admission["models_fitted"] == admission["models_restored"] == 0
        and admission["candidate_accounts"]
        == (3 if policy in (CALIBRATED_POLICY, MARKET_TIMED_POLICY) else 60)
        and admission["adoption_eligible"] is False,
        "Candidate input limitations differ",
    )
    ledger.check_originals(admission["original_risk_files"])
    ledger.same(ledger.digest(study / "identity.json"), identity_hash)
    ledger.same(ledger.digest(cstudy / "inputs.json"), input_hash)
    physical = admission["original_physical_files"]
    ledger.require(
        len(physical) == 103
        and all(
            identity["original_files"].get(name) == value
            for name, value in physical.items()
        ),
        "Candidate/control original inputs differ",
    )
    ledger.same(inputs["raw_provenance"], identity["raw_input_provenance"])
    args = SimpleNamespace(
        **{name: Path(value) for name, value in config["input_arguments"].items()}
    )
    data = ledger.load_original_data(args, identity, reviewed=True)
    with np.load(args.snapshot, allow_pickle=False) as archive:
        data["grades"], data["eligible"] = (
            archive["grades"].copy(),
            archive["eligible"].copy(),
        )
    if policy == MARKET_TIMED_POLICY:
        ledger.same(market_calibration.symbols, tuple(data["names"]))
        ledger.require(
            np.array_equal(market_calibration.bank["dates"], data["dates"]),
            "Original market bank and physical account dates differ",
        )
    grid, original = (
        candidate_grid(data["dates"], policy=policy),
        ledger.fixed_grid(data["dates"]),
    )
    ledger.same(inputs["accounts"], grid)
    ledger.same(identity["accounts"], original)
    candidates, cindex = read_index(cstudy, grid, inputs, candidate=True, policy=policy)
    controls, index = read_index(study, original, identity, candidate=False)
    left = verify_rows(
        cstudy,
        candidates,
        data,
        candidate=True,
        source=manifests["candidate"]["files"],
        policy=policy,
        market_calibration=market_calibration,
    )
    right = verify_rows(study, controls, data)
    for role in ("candidate", "control"):
        source_proof(config[role])
    ledger.check_originals(identity["original_files"])
    ledger.check_originals(admission["original_risk_files"])
    proof = {
        "candidate_policy": policy,
        "status": "VERIFIED_SAVED_PREFIX_ARITHMETIC",
        "adoption_eligible": False,
        "verifier_revision": config["verifier_revision"],
        "sources": config,
        "candidate_index": cindex,
        "control_index": index,
        "candidate_inputs_sha256": input_hash,
        "control_identity_sha256": identity_hash,
        "control_reported_runtime": identity["runtime"],
        "verified_candidate_accounts": len(left),
        "verified_control_accounts": len(right),
        "pending_candidate_accounts": len(grid) - len(left),
        "pending_control_accounts": len(original) - len(right),
        "candidate_accounts": left,
        "control_accounts": right,
        "paired": paired_results(
            left,
            right,
            grid,
            references=("rule", "boosting", "ridge", "SPY", "QQQ")
            if policy != POLICY
            else ("rule", "SPY", "QQQ"),
        ),
        "limitations": [
            "current_vintage_not_exact_live_reconstruction",
            "conditional_raw_open_not_broker_fills",
            "unspendable_dividend_claims",
            "receipt_consistency_not_forecast_accuracy",
            "partial_prefix_not_adoption_evidence",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(proof, indent=2, allow_nan=False) + "\n")
    return proof


# Execute saved-artifact checks using a hash-bound evidence configuration.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--evidence-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    verify(ledger.read_json(args.evidence, args.evidence_sha256), args.output)


if __name__ == "__main__":
    main()
