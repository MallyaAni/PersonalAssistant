"""Check saved actual-policy study evidence without running a policy or predictor.

This verifier folds recorded transactions into accounting identities. It never
selects a trade, fits/restores a predictor, or regenerates an account. Original
corporate-action history/publication/payment completeness remains unverified.
"""

import argparse
import gzip
import hashlib
import json
import math
import platform
import sys
from datetime import UTC, date, datetime, timedelta
from fractions import Fraction
from pathlib import Path

import numpy as np

from backend.market import calendar

POLICY = "actual-policy-timing/1-research"
PROTOCOL = "docs/research/actual-policy-timing-plan-2026-10-04.md"
PROTOCOL_SHA = "8bb0b528f56dd4f43e72823e4efa8eee71631e90b6d84831c881247a70cbabcc"
SNAPSHOT_SHA = "8670c86dd268fdf25ec16b44be86dcd40b840f703b7721ef319bc40e0e22ea58"
PROVENANCE_SHA = "529f59d10ca0b612b050a0eddd21b2fd7eee316346004130d035cdac4dbd9844"
ACTIONS_SHA = "0e05a397f3719c61688e2eb79355eb5111961c05f31916db8a16ab6ff01dbcca"
# Byte authentication cannot certify the known incorrect WDC share entitlement.
REJECTED_ACTIONS_SHA = (
    "0e05a397f3719c61688e2eb79355eb5111961c05f31916db8a16ab6ff01dbcca"
)
ACTION_REVIEW_SHA = "81106947ba049d0315d610719988a80da8e0efce9d87c52f789f2041901e95e8"
PASSIVE_ARRAYS_SHA = "c07e4615e425e8778282f26c75f18437ca38fa88993a4bab9bfe4b4499e99411"
PASSIVE_RECEIPT_SHA = "2bc957fcf9948981c4139c1868ad1336b0425d0bf5106460974ffb240a2869a9"
ECONOMIC_INPUT_PROOF_SHA = (
    "2a8ef22bf20de7891b27ae80ab05570a0be20ca170d6176ab596d0ec20aec102"
)
INPUT_RECEIPT_SHA = "9a367843ab2f529ba5123997967e435ae41481be5692314501e71f3aaad7be29"
FORECAST_INPUT_HASHES = (
    "c759ecb607e755631dacc0d28a147511a1eaa7e54e3cbcb23bdff4aafe8b76bf",
    "b797bc49c33c23b70c75b5217aa052ad99f2bdae86df722e6badd12ece40917a",
    "7ea72fd7f8b67c0d5f95397d8472a83b587aa3f7c5882be6ca86f94a510931c9",
    "7c5024fadcf4ae313004a7cb8bb002c1bea5ae4b2d2fbc7de60ebd3bbe708df2",
    "67084f65042a1defe87cfc5372ef5dd1de9e18e86a50b8c9d94b9d223681bf34",
    "c319fa57d520ae28189ba2158d2dc0b6f326f7dad1c671b6c3069ad9c34c2556",
)
ARMS = ("rule", "boosting", "ridge")
BENCHMARKS = ("SPY", "QQQ")
COSTS = (0, 10, 25)
WINDOWS = (
    ("full", "2018-02-01", "2026-10-01"),
    ("2018-20", "2018-02-01", "2021-01-01"),
    ("2021-26", "2021-01-01", "2026-10-01"),
    ("reused_recent", "2026-08-17", "2026-10-01"),
)


# Stop on inconsistent evidence rather than skip a failing account.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Hash original bytes without accepting a symlink or missing artifact.
def digest(path):
    path = Path(path)
    require(
        path.is_file() and not path.is_symlink(), f"Regular evidence required: {path}"
    )
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


# Reject nonstandard JSON numbers instead of turning invalid evidence into null.
def invalid_constant(value):
    raise ValueError(f"Nonfinite JSON number: {value}")


# Reject duplicate JSON keys that could make two readers authenticate different values.
def unique_object(pairs):
    result = {}
    for name, value in pairs:
        require(name not in result, f"Duplicate JSON key: {name}")
        result[name] = value
    return result


# Decode ordinary or compressed saved JSON with strict numeric and object semantics.
def decode(payload):
    return json.loads(
        payload, parse_constant=invalid_constant, object_pairs_hook=unique_object
    )


# Read and authenticate a saved JSON file before inspecting its contents.
def read_json(path, expected=None):
    before = digest(path)
    require(expected is None or before == expected, f"Evidence hash differs: {path}")
    result = decode(Path(path).read_bytes())
    require(digest(path) == before, f"Evidence changed while reading: {path}")
    return result


# Compare nested saved values while retaining exact null, boolean and schema boundaries.
def same(actual, expected, context="evidence"):
    if isinstance(expected, dict):
        require(
            isinstance(actual, dict) and set(actual) == set(expected),
            f"{context}: keys differ",
        )
        for key, value in expected.items():
            same(actual[key], value, f"{context}.{key}")
    elif isinstance(expected, (list, tuple)):
        require(
            isinstance(actual, (list, tuple)) and len(actual) == len(expected),
            f"{context}: length differs",
        )
        for index, value in enumerate(expected):
            same(actual[index], value, f"{context}[{index}]")
    elif isinstance(expected, bool) or expected is None or isinstance(expected, str):
        require(
            type(actual) is type(expected) and actual == expected,
            f"{context}: value differs",
        )
    elif isinstance(expected, (int, float, np.number)):
        require(
            not isinstance(actual, bool)
            and isinstance(actual, (int, float, np.number)),
            f"{context}: numeric value required",
        )
        require(
            math.isfinite(float(actual))
            and math.isclose(
                float(actual), float(expected), rel_tol=2e-10, abs_tol=1e-7
            ),
            f"{context}: arithmetic differs ({actual} != {expected})",
        )
    else:
        require(actual == expected, f"{context}: value differs")


# Require timezone-aware receipt instants and normalize their comparison clock.
def aware(value):
    result = datetime.fromisoformat(value)
    require(result.utcoffset() is not None, "Aware receipt clock required")
    return result.astimezone(UTC)


# Obtain a receipt's historical exchange date without using publication timestamps.
def receipt_day(row):
    return aware(row["at"]).astimezone(calendar.NEW_YORK).date().isoformat()


# Check whole submitted shares separately from fractional split entitlements.
def whole(value, *, zero=False):
    require(
        type(value) is int and value >= (0 if zero else 1),
        "Whole-share quantity required",
    )
    return value


# Independently enumerate every declared arm, cost and start from reviewed dates.
def fixed_grid(dates):
    require(
        dates.dtype == np.dtype("datetime64[D]")
        and not np.isnat(dates).any()
        and np.all(dates[1:] > dates[:-1]),
        "Ordered original dates required",
    )
    first = np.flatnonzero(dates == np.datetime64("2018-02-01"))
    last = np.flatnonzero(dates == np.datetime64("2026-09-30"))
    require(
        len(first) == len(last) == 1 and first[0] > 0 and first[0] + 19 < last[0],
        "Fixed complete study dates required",
    )
    return [
        {
            "arm": arm,
            "cost_bps": cost,
            "start": start,
            "first": int(first[0]) + start,
            "last": int(last[0]),
            "first_session": str(dates[int(first[0]) + start]),
            "id": f"{arm}-{cost}-{start}",
        }
        for cost in COSTS
        for start in range(20)
        for arm in (*ARMS, *BENCHMARKS)
    ]


# Authenticate the declared producer tree and its preserved research limitations.
def check_identity(identity, manifest_path, revision, image_id, source_root):
    manifest = read_json(manifest_path)
    require(
        len(revision) == 40 and all(c in "0123456789abcdef" for c in revision),
        "Exact source revision required",
    )
    require(
        manifest.get("git_commit") == revision
        and isinstance(manifest.get("files"), dict)
        and len(manifest["files"]) >= 2300,
        "Whole producer source manifest required",
    )
    for name, expected in manifest["files"].items():
        relative = Path(name)
        require(
            not relative.is_absolute() and ".." not in relative.parts,
            "Unsafe source manifest path",
        )
        require(
            digest(source_root / relative) == expected,
            f"Mounted producer source differs: {name}",
        )
    for name in (
        PROTOCOL,
        "backend/cli/market_actual_policy_timing.py",
        "backend/market/live_policy_replay.py",
        "backend/market/replay_broker.py",
        "backend/cli/market_daily.py",
        "backend/market/live_execution_inputs.py",
        "backend/market/live_policy_report.py",
        "backend/market/live_policy_features.py",
        "backend/market/live_probability_timing.py",
    ):
        require(name in manifest["files"], f"Producer source missing: {name}")
    require(manifest["files"][PROTOCOL] == PROTOCOL_SHA, "Frozen protocol differs")
    same(
        identity["source"],
        {
            "git_commit": revision,
            "files": len(manifest["files"]),
            "manifest_sha256": digest(manifest_path),
        },
        "producer source",
    )
    require(
        identity["policy"] == POLICY and identity["protocol_sha256"] == PROTOCOL_SHA,
        "Study policy/protocol differs",
    )
    require(
        identity["adoption_eligible"] is False and identity["models_fitted"] == 0,
        "Research-only/no-fit identity required",
    )
    require(
        identity["availability"]
        == "current_vintage_grades_universe_and_history_not_exact_live_reconstruction",
        "Current-vintage limitation missing",
    )
    require(
        identity["sizing"] == "unchanged_actual_graded_equal_weight_5"
        and identity["holding_exits"] == "unchanged_grade_reset_FOMC_paths",
        "Actual policy limitations differ",
    )
    require(
        identity["dividends"]
        == "unspendable_receivables_unknown_payment_dates_no_reinvestment"
        and identity["fills"]
        == "conditional_original_raw_SIP_proxy_not_proven_broker_or_midpoint_fills",
        "Accounting/fill limitations missing",
    )
    runtime = identity["runtime"]
    require(
        image_id != "unavailable" and runtime["image_id"] == image_id,
        "Pinned producer image differs",
    )
    require(
        all(
            isinstance(runtime.get(key), str) and runtime[key]
            for key in ("python", "platform", "container_hostname", "numpy")
        ),
        "Producer runtime record incomplete",
    )
    require(
        isinstance(runtime.get("thread_limits"), dict) and runtime["thread_limits"],
        "Producer thread limits missing",
    )
    require(
        set(identity["restored_models"]) == {"boosting", "ridge"},
        "Both frozen model receipts required",
    )
    for row in identity["restored_models"].values():
        require(
            row["status"] == "VERIFIED_SAVED_DISTRIBUTIONS"
            and row["no_refit_or_recalibration"] is True,
            "Saved model receipt differs",
        )


# Verify every declared original byte and preserve originally absent cube paths.
def check_originals(files):
    require(isinstance(files, dict) and files, "Original input manifest required")
    for filename, expected in files.items():
        path = Path(filename)
        if expected is None:
            require(
                not path.exists() and not path.is_symlink(),
                f"Originally absent input appeared: {path}",
            )
        else:
            require(digest(path) == expected, f"Original input changed: {path}")


# Convert only dated source split units and keep raw dividend values distinct.
def normalize_actions(names, dates, exported, dividend_basis):
    require(
        set(exported["actions"]) == set(names), "Every original action name required"
    )
    require(
        dividend_basis
        in ("raw_ex_date_share_dollars", "split_adjusted_archive_share_dollars"),
        "Declared dividend basis required",
    )
    factors = np.ones((len(dates), len(names)), dtype=float)
    normalized = {}
    for column, name in enumerate(names):
        basis = exported["basis_as_of"]
        basis = basis[name] if isinstance(basis, dict) else basis
        through = exported["complete_through"]
        through = through[name] if isinstance(through, dict) else through
        require(
            str(dates[-1]) <= basis <= through,
            "Action basis/completeness bounds differ",
        )
        rows, seen, previous = [], set(), None
        for original in exported["actions"][name]:
            day, kind, value = original["date"], original["kind"], original["value"]
            date.fromisoformat(day)
            require(
                kind in ("split", "dividend")
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0,
                "Dated positive action required",
            )
            require(
                (day, kind) not in seen
                and (previous is None or day >= previous)
                and day <= through,
                "Duplicate/unordered action history",
            )
            seen.add((day, kind))
            previous = day
            rows.append({"date": day, "kind": kind, "value": float(value)})
            if kind == "split" and day <= basis:
                factors[dates < np.datetime64(day), column] *= value
        rows.sort(key=lambda row: (row["date"], row["kind"] != "split"))
        for row in rows:
            if row["kind"] == "dividend":
                row["source_value"] = row["value"]
                if dividend_basis == "split_adjusted_archive_share_dollars":
                    row["value"] *= math.prod(
                        split["value"]
                        for split in rows
                        if split["kind"] == "split"
                        and row["date"] < split["date"] <= basis
                    )
        normalized[name] = rows
    require(
        np.isfinite(factors).all() and (factors > 0).all(),
        "Invalid dated share conversion",
    )
    return normalized, factors


# Validate a reviewed legal clock against its first actual regular application.
def reviewed_opening(event):
    effective = aware(event["effective_at"])
    local = effective.astimezone(calendar.NEW_YORK)
    years, sessions = calendar.reviewed_sessions()
    require(local.year in years, "Reviewed action calendar required")
    regular = bool(np.is_busday(np.datetime64(local.date()), busdaycal=sessions))
    require(
        not regular
        or not calendar.REGULAR_OPEN
        < local.time()
        < calendar.session_close(local.date()),
        "Intraday legal action requires unsupported ordering",
    )
    application = np.busday_offset(
        np.datetime64(local.date()),
        int(regular and local.time() > calendar.REGULAR_OPEN),
        roll="forward",
        busdaycal=sessions,
    )
    require(str(application) == event["date"], "Action requires first regular opening")
    return datetime.fromisoformat(event["effective_at"]).isoformat()


# Require declaration availability before observing a private default election.
def reviewed_default(event, election):
    day = date.fromisoformat(event["date"])
    years, sessions = calendar.reviewed_sessions()
    require(
        day.year in years and np.is_busday(np.datetime64(day), busdaycal=sessions),
        "Reviewed default election session required",
    )
    boundary = datetime.combine(day, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    require(
        event["election_policy"] == election
        and event["legal_clock_precision"] == "completed_before_open_not_exact"
        and aware(event["completed_before"]) == boundary
        and aware(event["terms_available_at"]) < boundary
        and aware(event["completion_available_at"]) <= boundary,
        "Available-by private default election required",
    )
    require(
        all(
            isinstance(event.get(key), str) and event[key].startswith("https://")
            for key in ("terms_source", "completion_source")
        ),
        "Declared default election sources required",
    )


# Derive physical grants from declarations independently of archive price conversion.
def reviewed_grant(event):
    require(
        not any(
            key in event
            for key in ("paid", "payment_amount", "payment_date", "cash_credit")
        ),
        "Payment receipts cannot be inferred from declarations",
    )
    category, n, d = event["classification"], event["numerator"], event["denominator"]
    require(
        all(type(value) is int and value > 0 for value in (n, d)),
        "Positive integer economic ratio required",
    )
    require(
        isinstance(event.get("source"), str) and event["source"].startswith("https://"),
        "Primary declaration URL required",
    )
    day = event["date"]
    if category == "same_security_split" and n % d == 0:
        require(n / d == event["archive_factor"], "Same-security ratio differs")
        return {
            "date": day,
            "kind": "share_split",
            "value": n / d,
            "review_event": event.copy(),
        }
    base = {"date": day, "numerator": n, "denominator": d}
    if category in ("same_security_split", "security_distribution"):
        require(
            event.get("fractional_policy") == "cash_in_lieu_unknown",
            "Explicit unknown fractional payment required",
        )
        require(
            all(
                isinstance(event.get(key), str) and event[key].startswith("https://")
                for key in ("effective_source", "fractional_source")
            ),
            "Effective and fractional source required",
        )
        base.update(
            effective_at=reviewed_opening(event),
            effective_source=event["effective_source"],
            fractional_source=event["fractional_source"],
            fractional_policy="cash_in_lieu_unknown",
        )
        receipt = {
            key: event.get(key) for key in ("effective_source", "fractional_source")
        }
        receipt["declaration"] = event["source"]
        if category == "same_security_split":
            require(n < d and n / d == event["archive_factor"], "Reverse ratio differs")
            receipt["effective_source_sha256"] = event.get("effective_source_sha256")
            return {**base, "kind": "share_consolidation", "source_receipt": receipt}
        require(
            isinstance(event.get("child"), str)
            and event["child"]
            and event["child"] != event["symbol"]
            and event.get("basis_policy") == "unallocated_at_effective_clock"
            and event.get("parent_basis_fraction") is None
            and event.get("basis_available_at") is None
            and event.get("share_basis") == "post_split_action_date_shares",
            "Explicit child, unallocated basis and share units required",
        )
        return {
            **base,
            "kind": "stock_distribution",
            "child": event["child"],
            "basis_policy": "unallocated_at_effective_clock",
            "parent_basis_fraction": None,
            "share_basis": "post_split_action_date_shares",
            "source_receipt": receipt,
            "entitlement_scope": (
                "private_action_date_holdings_due_bill_assumption_not_broker_proof"
            ),
        }
    require(category == "security_exchange", "Unsupported economic classification")
    require(
        all(
            isinstance(event.get(key), str) and event[key]
            for key in ("old_security_id", "new_security_id")
        )
        and event["old_security_id"] != event["new_security_id"]
        and date.fromisoformat(event["terms_available_on"]) < date.fromisoformat(day),
        "Distinct exchange identities and prior terms required",
    )
    fields = (
        "old_security_id",
        "new_security_id",
        "fractional_policy",
        "terms_available_on",
    )
    base.update({key: event[key] for key in fields})
    fraction = event["fractional_policy"]
    if fraction == "cash_in_lieu_unknown":
        reviewed_default(event, "declared_no_election_default_shares")
        require(
            aware(event["terms_available_at"]).astimezone(calendar.NEW_YORK).date()
            >= date.fromisoformat(event["terms_available_on"]),
            "Premature exchange terms",
        )
        base.update(
            {
                key: event[key]
                for key in (
                    "completed_before",
                    "terms_available_at",
                    "completion_available_at",
                    "legal_clock_precision",
                    "election_policy",
                    "terms_source",
                    "completion_source",
                    "fractional_source",
                )
            }
        )
    else:
        require(
            fraction == "floor_no_compensation"
            and event.get("election_policy") is None,
            "Explicit exchange fraction policy required",
        )
    require(
        isinstance(event.get("fractional_source"), str)
        and event["fractional_source"].startswith("https://"),
        "Fractional declaration source required",
    )
    receipt = {
        key: event.get(key)
        for key in (
            "fractional_source",
            "completion_source",
            "terms_source",
            "terms_source_sha256",
        )
    }
    receipt.update(
        declaration=event["source"],
        election_scope="declared_private_policy_not_broker_election",
    )
    return {**base, "kind": "security_exchange", "source_receipt": receipt}


# Preserve original factors and dividends while independently deriving reviewed grants.
def normalize_reviewed_actions(
    names, dates, exported, review, dividend_basis, *, original_sha
):
    require(
        review.get("schema") == "actual-policy-action-semantics/1"
        and review.get("adoption_eligible") is False
        and review.get("original_actions_sha256") == original_sha,
        "Reviewed original byte identity required",
    )
    first, last = review["first_session"], review["last_session"]
    require(
        date.fromisoformat(first) <= date.fromisoformat(last),
        "Ordered review scope required",
    )
    original, factors = normalize_actions(names, dates, exported, dividend_basis)
    indexed = {}
    for event in review["events"]:
        key = event["symbol"], event["date"]
        require(
            key not in indexed and key[0] in names and first <= key[1] <= last,
            "Unique covered in-scope economic review required",
        )
        date.fromisoformat(key[1])
        indexed[key] = event
    result, covered = {}, set()
    for name, rows in original.items():
        output = []
        for row in rows:
            if row["kind"] != "split":
                output.append(row)
                continue
            output.append({**row, "kind": "archive_adjustment"})
            if not first <= row["date"] <= last:
                continue
            key = name, row["date"]
            require(key in indexed, "Missing original economic review")
            event = indexed[key]
            require(
                type(event.get("archive_factor")) in (int, float)
                and event["archive_factor"] == row["value"],
                "Reviewed archive factor differs",
            )
            output.append(reviewed_grant(event))
            covered.add(key)
        result[name] = output
    require(covered == set(indexed), "Review event absent from original bytes")
    children = {
        event["child"]
        for event in indexed.values()
        if event["classification"] == "security_distribution"
    }
    inherited = {}
    for event in review.get("inherited_events", []):
        name, day = event["symbol"], event["date"]
        require(
            name in children
            and name not in names
            and name not in inherited
            and first <= day <= last
            and event["kind"] == "cash_merger"
            and type(event["value"]) in (int, float)
            and math.isfinite(event["value"])
            and event["value"] > 0,
            "Covered inherited terminal declaration required",
        )
        reviewed_default(event, "declared_no_election_default_cash")
        row = {key: value for key, value in event.items() if key != "symbol"}
        require(
            set(row)
            == {
                "date",
                "kind",
                "value",
                "old_security_id",
                "election_policy",
                "completed_before",
                "legal_clock_precision",
                "terms_available_at",
                "completion_available_at",
                "terms_source",
                "completion_source",
                "source_receipt",
            }
            and isinstance(row["old_security_id"], str)
            and row["old_security_id"]
            and isinstance(row["source_receipt"], dict)
            and row["source_receipt"],
            "Explicit terminal default without guessed payment required",
        )
        inherited[name] = [{**row, "value": float(row["value"])}]
    return result, inherited, factors


# Authenticate original typed array bytes without importing a producer's hash helper.
def array_digest(array):
    value = np.ascontiguousarray(array)
    result = hashlib.sha256()
    result.update(str(value.dtype).encode())
    result.update(json.dumps(value.shape).encode())
    result.update(value.tobytes())
    return result.hexdigest()


# Read valuation-only inherited marks while retaining their original missing cells.
def load_original_passive(args, names, dates, provenance, files):
    for path, expected in (
        (args.passive_arrays, PASSIVE_ARRAYS_SHA),
        (args.passive_receipt, PASSIVE_RECEIPT_SHA),
    ):
        require(
            files.get(str(path)) == expected and digest(path) == expected,
            "Fixed passive original input required",
        )
    receipt = read_json(args.passive_receipt, PASSIVE_RECEIPT_SHA)
    require(
        receipt["arrays_sha256"] == PASSIVE_ARRAYS_SHA
        and receipt["selection_symbols"] == len(names)
        and receipt["selection_universe_extended"] is False
        and receipt["adoption_eligible"] is False,
        "Passive marks cannot extend selection or authorize adoption",
    )
    contract = receipt["passive_provenance"]
    same(provenance["passive_provenance"], contract, "Passive original contract")
    require(
        contract["price_basis"] == "raw_session_dollars"
        and contract["supplied"]["snapshot_sha256"] == SNAPSHOT_SHA,
        "Passive original monetary basis required",
    )
    with np.load(args.passive_arrays, allow_pickle=False) as archive:
        require(
            set(archive.files)
            == {"dates", "symbols", "session_open", "observation_close", "daily_close"}
            and np.array_equal(archive["dates"], dates),
            "Passive original calendar required",
        )
        passive_names = tuple(archive["symbols"].tolist())
        require(
            len(passive_names) == len(set(passive_names))
            and passive_names
            and not set(passive_names).intersection(names),
            "Passive-only security identities required",
        )
        for key, shape in (
            ("session_open", (len(dates), len(passive_names))),
            ("observation_close", (len(dates), 26, len(passive_names))),
            ("daily_close", (len(dates), len(passive_names))),
        ):
            values = archive[key]
            require(
                values.shape == shape
                and values.dtype.kind == "f"
                and not np.isinf(values).any()
                and (values[np.isfinite(values)] > 0).all(),
                "Passive original price grid required",
            )
            require(
                array_digest(values) == contract["arrays"][key],
                "Passive typed byte identity differs",
            )
            for column, name in enumerate(passive_names):
                outside = (dates < np.datetime64(contract["first_session"][name])) | (
                    dates > np.datetime64(contract["complete_through"][name])
                )
                require(
                    not np.isfinite(values[outside, ..., column]).any(),
                    "Passive prices beyond source coverage",
                )
        require(
            array_digest(archive["dates"]) == contract["arrays"]["dates"],
            "Passive typed dates differ",
        )
        close = archive["daily_close"].copy()
    require(
        digest(args.passive_arrays) == PASSIVE_ARRAYS_SHA,
        "Passive original changed while reading",
    )
    return {"names": passive_names, "close": close, "provenance": contract}


# Check saved forecast bytes without restoring or recalibrating either predictor.
def check_frozen_forecast_inputs(files):
    require(
        set(FORECAST_INPUT_HASHES) <= set(files.values()),
        "Frozen forecast evidence missing",
    )
    diagnostic_hash = FORECAST_INPUT_HASHES[-2]
    diagnostic_path = Path(
        next(name for name, value in files.items() if value == diagnostic_hash)
    )
    diagnostic = read_json(diagnostic_path, diagnostic_hash)
    for name in ("boosting", "ridge"):
        for suffix, key in (
            (".npz", "artifact_sha256"),
            ("-calibration.json", "calibration_sha256"),
        ):
            require(
                files.get(str(diagnostic_path.parent / (name + suffix)))
                == diagnostic["methods"][name][key],
                "Frozen CDF byte receipt differs",
            )


# Refuse legacy false grants and retain explicit reviewed source limitations.
def load_original_data(args, identity, *, reviewed=False, input_only=False):
    if not reviewed:
        require(
            ACTIONS_SHA != REJECTED_ACTIONS_SHA,
            "Known incorrect stock-distribution export; "
            "arithmetic is not economic proof",
        )
    require(
        not input_only or reviewed,
        "Input-only proof requires explicit reviewed sources",
    )
    files = identity["original_files"]
    require(
        len(files) == (103 if input_only else 114 if reviewed else 110),
        "Complete original input mapping required",
    )
    check_originals(files)
    if reviewed and not input_only:
        require(
            files.get(str(args.economic_input_proof)) == ECONOMIC_INPUT_PROOF_SHA,
            "Independent original source proof mapping required",
        )
        read_json(args.economic_input_proof, ECONOMIC_INPUT_PROOF_SHA)
    for path, expected in ((args.snapshot, SNAPSHOT_SHA), (args.actions, ACTIONS_SHA)):
        require(
            files.get(str(path)) == expected and digest(path) == expected,
            "Fixed original snapshot/actions required",
        )
    require(
        PROVENANCE_SHA in files.values() and INPUT_RECEIPT_SHA in files.values(),
        "Original provenance/account receipt missing",
    )
    input_receipt = read_json(
        next(name for name, value in files.items() if value == INPUT_RECEIPT_SHA),
        INPUT_RECEIPT_SHA,
    )
    if not input_only:
        check_frozen_forecast_inputs(files)
    exported = read_json(args.actions, ACTIONS_SHA)
    require(
        exported["snapshot_sha256"] == SNAPSHOT_SHA
        and exported["provenance_sha256"] == PROVENANCE_SHA,
        "Action source archive differs",
    )
    with np.load(args.snapshot, allow_pickle=False) as archive:
        dates = archive["dates"].astype("datetime64[D]")
        names = tuple(archive["symbols"].tolist())
        close = archive["close"].astype(float)
    require(
        len(names) == len(set(names)) == 96
        and len(dates) == 2953
        and {"SPY", "QQQ"} <= set(names),
        "Complete original daily grid required",
    )
    require(close.shape == (len(dates), len(names)), "Original close grid differs")
    provenance = identity["raw_input_provenance"]
    require(
        provenance["daily_price_basis"] == "split_adjusted_daily_store"
        and provenance["cube_price_basis"] == "raw_session_dollars",
        "Original monetary bases differ",
    )
    passive, inherited = None, {}
    if reviewed:
        require(
            files.get(str(args.action_review)) == ACTION_REVIEW_SHA,
            "Fixed original review mapping required",
        )
        review = read_json(args.action_review, ACTION_REVIEW_SHA)
        require(
            (review["first_session"], review["last_session"])
            == ("2018-02-01", "2026-09-30"),
            "Frozen economic scope differs",
        )
        supplied = provenance["supplied"]
        require(
            supplied["reviewed_actions_sha256"] == ACTION_REVIEW_SHA
            and supplied["passive_arrays_sha256"] == PASSIVE_ARRAYS_SHA
            and supplied["passive_receipt_sha256"] == PASSIVE_RECEIPT_SHA
            and supplied["execution_readiness"] == "pending_declaration_receipts"
            and supplied["declaration_evidence"]
            == "manual_primary_URL_review_not_authenticated_source_receipts",
            "Reviewed declaration limitations required",
        )
        actions, inherited, factors = normalize_reviewed_actions(
            names,
            dates,
            exported,
            review,
            provenance["dividend_source_basis"],
            original_sha=ACTIONS_SHA,
        )
        passive = load_original_passive(args, names, dates, provenance, files)
        require(
            set(inherited) <= set(passive["names"]),
            "Covered inherited terminal names required",
        )
        for name, rows in inherited.items():
            require(
                np.datetime64(rows[0]["date"]) in dates
                and provenance["passive_provenance"]["complete_through"][name]
                < rows[0]["date"],
                "Terminal inherited marks must stop before conversion",
            )
        same(
            provenance["inherited_actions"],
            inherited,
            "Original terminal source contract",
        )
    else:
        actions, factors = normalize_actions(
            names, dates, exported, provenance["dividend_source_basis"]
        )
    close = close * factors
    require(
        not np.isinf(close).any() and (close[np.isfinite(close)] > 0).all(),
        "Raw close conversion invalid",
    )
    cubes, receipts = {}, provenance["supplied"]["cubes"]
    same(receipts, input_receipt["identity"]["data"]["cubes"], "Original cube receipt")
    require(
        set(receipts) == set(names), "Complete original cube receipt names required"
    )
    for name in names:
        path = args.cubes / f"{name}.npz"
        receipt = receipts[name]
        expected = receipt.get("sha256") if receipt["status"] == "original" else None
        require(
            str(path) in files and files[str(path)] == expected,
            "Cube absent/hash receipt differs",
        )
        if expected is None:
            require(
                not path.exists() and not path.is_symlink(),
                "Originally absent cube appeared",
            )
            continue
        require(digest(path) == expected, "Original cube hash differs")
        with np.load(path, allow_pickle=False) as archive:
            require(str(archive["key"][-1]) == "2", "Original v2 cube required")
            cube = {
                key: archive[key].copy()
                for key in ("dates", "open", "close", "auction_open")
            }
            excluded = dict(
                zip(
                    archive["excluded_reasons"].tolist(),
                    archive["excluded_counts"].astype(int).tolist(),
                    strict=True,
                )
            )
        cube["dates"] = cube["dates"].astype("datetime64[D]")
        require(
            len(cube["dates"]) == receipt["sessions"]
            and excluded == receipt["excluded"]
            and np.all(cube["dates"][1:] > cube["dates"][:-1]),
            "Original cube date/exclusion receipt differs",
        )
        require(
            cube["open"].shape == cube["close"].shape == (len(cube["dates"]), 26)
            and cube["auction_open"].shape == (len(cube["dates"]),),
            "Original raw cube shape differs",
        )
        cubes[name] = cube
    check_originals(files)
    return {
        "dates": dates,
        "names": names,
        "close": close,
        "actions": actions,
        "cubes": cubes,
        **({"passive": passive, "inherited_actions": inherited} if reviewed else {}),
    }


# Retrieve an original raw session price and preserve unavailable full-session evidence.
def original_price(data, symbol, day, wall_time, *, observed=False):
    cube = data["cubes"].get(symbol)
    if cube is None:
        return None
    indices = np.flatnonzero(cube["dates"] == np.datetime64(day))
    if (
        len(indices) != 1
        or calendar.session_close(date.fromisoformat(day)) != calendar.REGULAR_CLOSE
    ):
        return None
    delta = wall_time.hour * 60 + wall_time.minute - 570
    if wall_time.second or wall_time.microsecond or delta < 0 or delta % 15:
        return None
    row = int(indices[0])
    if delta == 390:
        value = cube["auction_open"][row]
    else:
        slot = delta // 15 - (1 if observed else 0)
        if not 0 <= slot < 26:
            return None
        value = cube["close" if observed else "open"][row, slot]
    return float(value) if np.isfinite(value) and value > 0 else None


# Check saved submission quantities, dates and refusal receipts independently.
def validate_attempts(attempts, dates, data):
    accepted, previous = {}, None
    for row in attempts:
        now = aware(row["at"])
        require(previous is None or now >= previous, "Attempt clocks unordered")
        previous = now
        require(
            str(dates[0]) <= receipt_day(row) <= str(dates[-1])
            and row["symbol"] in data["names"]
            and row["side"] in ("buy", "sell"),
            "Attempt outside account/source bounds",
        )
        whole(row["qty"])
        local = now.astimezone(calendar.NEW_YORK)
        if local.time() > calendar.session_close(local.date()):
            index = int(np.searchsorted(data["dates"], np.datetime64(local.date())))
            price = data["close"][index, data["names"].index(row["symbol"])]
        elif local.time() == calendar.REGULAR_OPEN:
            price = original_price(data, row["symbol"], receipt_day(row), local.time())
        else:
            price = original_price(
                data, row["symbol"], receipt_day(row), local.time(), observed=True
            )
        require(
            price is not None and np.isfinite(price), "Original observed price missing"
        )
        same(row["observed_price"], price, "submission observed raw price")
        require(
            type(row["accepted"]) is bool
            and math.isfinite(row["available_cash"])
            and row["available_cash"] >= 0,
            "Attempt funding/acceptance evidence invalid",
        )
        require(
            row["reason"] is None
            if row["accepted"]
            else row["reason"] in ("insufficient_reserved_cash", "uncovered_sell"),
            "Attempt refusal reason differs",
        )
        if row["accepted"]:
            require(
                row["client_order_id"] not in accepted, "Duplicate accepted submission"
            )
            accepted[row["client_order_id"]] = row
    return accepted


# Bind each saved fill to its accepted whole-share request and original raw price.
def validate_fills(fills, accepted, spec, data, dates):
    by_day, identities, previous = {}, set(), None
    for row in fills:
        now, symbol, quantity = (
            aware(row["at"]),
            row["symbol"],
            whole(row["filled_qty"], zero=True),
        )
        requested = whole(row["requested_qty"])
        require(previous is None or now >= previous, "Fill clocks unordered")
        previous = now
        require(
            str(dates[1]) <= receipt_day(row) <= str(dates[-1]),
            "Fill outside account bounds",
        )
        cid = row["client_order_id"]
        require(
            cid in accepted and cid not in identities and quantity <= requested,
            "Fill missing unique accepted submission",
        )
        identities.add(cid)
        attempt = accepted[cid]
        require(
            now >= aware(attempt["at"])
            and row["symbol"] == attempt["symbol"]
            and row["side"] == attempt["side"]
            and requested == attempt["qty"],
            "Fill/attempt identity differs",
        )
        require(
            row["status"] == ("filled" if quantity == requested else "expired"),
            "Fill terminal status differs",
        )
        local = now.astimezone(calendar.NEW_YORK)
        source_price = original_price(data, symbol, receipt_day(row), local.time())
        if quantity:
            require(
                source_price is not None, "Fill has no original raw execution price"
            )
            same(row["price"], source_price, "raw fill price")
            require(
                row["reason"]
                == ("filled" if quantity == requested else "partial_cash_or_coverage"),
                "Fill reason differs",
            )
        else:
            require(row["price"] is None, "Unfilled request has invented price")
            require(
                row["reason"]
                == (
                    "missing_execution_price"
                    if source_price is None
                    else "partial_cash_or_coverage"
                ),
                "Missing/partial fill reason differs",
            )
        same(
            row["fee"],
            quantity * (row["price"] or 0) * spec["cost_bps"] / 1e4,
            "fill fee",
        )
        by_day.setdefault(receipt_day(row), []).append(row)
    return by_day


# Check the saved receipt against independently derived entitlement arithmetic.
def check_entitlement(ledger, field, record):
    matches = [
        row
        for row in ledger.get(field, [])
        if row.get("action_key") == record["action_key"]
    ]
    require(len(matches) == 1, f"Unique {field} entitlement receipt required")
    same(matches[0], record, field)
    return record


# Derive whole security conversions and their separate fractional acquisition cost.
def conversion_entitlement(held, basis, symbol, action):
    numerator, denominator = action["numerator"], action["denominator"]
    require(
        type(numerator) is type(denominator) is int
        and numerator > 0
        and denominator > 0,
        "Positive integer share ratio required",
    )
    quantity = held.get(symbol, 0)
    require(quantity == int(quantity), "Whole pre-action holdings required")
    ratio = Fraction(numerator, denominator)
    entitlement = int(quantity) * ratio
    whole_qty, fraction = int(entitlement), float(entitlement % 1)
    average = basis.get(symbol, 0)
    new_average = average / float(ratio) if average is not None else None
    fractional_cost = (
        fraction * new_average if new_average is not None else None if fraction else 0
    )
    return ratio, quantity, whole_qty, fraction, new_average, fractional_cost


# Reconstruct economic grants separately from archive price factors and cash payments.
def fold_grant(symbol, action, effective, now, held, basis):
    kind, clock = action["kind"], effective.isoformat()
    key = [
        symbol,
        f"stock_distribution/{action['child']}"
        if kind == "stock_distribution"
        else kind,
        clock,
    ]
    if kind == "stock_distribution":
        child = action["child"]
        require(child != symbol, "Distinct distribution security required")
        ratio, parent_qty, whole_qty, fraction, _, _ = conversion_entitlement(
            held, basis, symbol, action
        )
        allocation = action["parent_basis_fraction"]
        require(
            (
                allocation is None
                and action.get("basis_policy") == "unallocated_at_effective_clock"
            )
            or (type(allocation) in (int, float) and 0 < allocation < 1),
            "Explicit known or unallocated acquisition basis required",
        )
        parent_average = basis.get(symbol, 0)
        parent_total = (
            parent_qty * parent_average if parent_average is not None else None
        )
        child_before, child_average = held.get(child, 0), basis.get(child, 0)
        child_total = (
            child_before * child_average if child_average is not None else None
        )
        child_grant_average = (
            parent_average * (1 - allocation) / float(ratio)
            if parent_average is not None and allocation is not None
            else None
        )
        if parent_qty:
            basis[symbol] = (
                parent_average * allocation
                if parent_average is not None and allocation is not None
                else None
            )
        if whole_qty:
            quantity = child_before + whole_qty
            held[child] = quantity
            basis[child] = (
                (child_before * child_average + whole_qty * child_grant_average)
                / quantity
                if child_grant_average is not None
                and (not child_before or child_average is not None)
                else None
            )
        record = {
            "action_key": key,
            "parent": symbol,
            "child": child,
            "parent_qty": parent_qty,
            "numerator": ratio.numerator,
            "denominator": ratio.denominator,
            "whole_qty": whole_qty,
            "fractional_qty": fraction,
            "fractional_basis": (
                fraction * child_grant_average
                if child_grant_average is not None
                else None
                if fraction
                else 0
            ),
            "parent_basis_fraction": allocation,
            "cash_in_lieu": None,
            "effective_at": clock,
            "applied_at": now.isoformat(),
        }
        if allocation is None:
            record.update(
                basis_policy="unallocated_at_effective_clock",
                basis_before={"parent_total": parent_total, "child_total": child_total},
            )
        return "security_distributions", record
    if kind == "cash_merger":
        quantity, average = held.get(symbol, 0), basis.get(symbol, 0)
        require(quantity == int(quantity), "Whole pre-merger holdings required")
        require(
            action["election_policy"] == "declared_no_election_default_cash",
            "Explicit private cash default required",
        )
        record = {
            "action_key": key,
            "symbol": symbol,
            "old_security_id": action["old_security_id"],
            "election_policy": action["election_policy"],
            "quantity_before": quantity,
            "per_share": action["value"],
            "amount": quantity * action["value"],
            "prior_total_cost": quantity * average if average is not None else None,
            "completed_before": clock,
            "legal_clock_precision": "completed_before_open_not_exact",
            "applied_at": now.isoformat(),
            "paid": False,
            "entitlement_scope": "declared_private_no_election_not_broker_receipt",
        }
        held.pop(symbol, None)
        basis.pop(symbol, None)
        return "cash_mergers", record
    require(kind in ("share_consolidation", "security_exchange"), "Unsupported grant")
    ratio, before, quantity, fraction, average, fractional_cost = (
        conversion_entitlement(held, basis, symbol, action)
    )
    if quantity:
        held[symbol], basis[symbol] = quantity, average
    else:
        held.pop(symbol, None)
        basis.pop(symbol, None)
    record = {
        "action_key": key,
        "symbol": symbol,
        "numerator": ratio.numerator,
        "denominator": ratio.denominator,
        "quantity_before": before,
        "fractional_policy": action["fractional_policy"],
        "entitlement_scope": (
            "private_holder_aggregate_not_broker_street_name_allocation"
        ),
    }
    if kind == "share_consolidation":
        require(
            ratio < 1 and action["fractional_policy"] == "cash_in_lieu_unknown",
            "Explicit consolidation cash-fraction policy required",
        )
        record.update(
            whole_qty=quantity,
            fractional_qty=fraction,
            fractional_basis=fractional_cost,
            cash_in_lieu=None,
            effective_at=clock,
            applied_at=now.isoformat(),
        )
        return "share_consolidations", record
    record.update(
        old_security_id=action["old_security_id"],
        new_security_id=action["new_security_id"],
        quantity_after=quantity,
        cash_credit=0,
    )
    require(
        record["old_security_id"] != record["new_security_id"],
        "Distinct issuers required",
    )
    if action["fractional_policy"] == "floor_no_compensation":
        require(action.get("election_policy") is None, "Unsupported cash election")
        record.update(
            forfeited_fraction=fraction,
            forfeited_basis=fractional_cost,
            effective_at=clock,
            basis_policy="ratio_basis_with_separate_forfeited_cost_not_tax_basis",
        )
    else:
        require(
            action["fractional_policy"] == "cash_in_lieu_unknown"
            and action["election_policy"] == "declared_no_election_default_shares",
            "Explicit share default required",
        )
        record.update(
            fractional_qty=fraction,
            fractional_basis=fractional_cost,
            cash_in_lieu=None,
            completed_before=clock,
            legal_clock_precision="completed_before_open_not_exact",
            applied_at=now.isoformat(),
            election_policy=action["election_policy"],
            basis_policy="ratio_basis_with_separate_fractional_cost_not_tax_basis",
        )
    return "security_exchanges", record


# Index both declaration application dates and legal dates without outcome filtering.
def source_events(data):
    priority = {
        "split": 0,
        "share_split": 0,
        "security_exchange": 1,
        "share_consolidation": 2,
        "cash_merger": 3,
        "stock_distribution": 4,
        "dividend": 5,
        "archive_adjustment": 6,
    }
    events = {}
    for symbol, rows in (
        *data["actions"].items(),
        *(data.get("inherited_actions") or {}).items(),
    ):
        for action in rows:
            require(action["kind"] in priority, "Unsupported source economic action")
            supplied_clock = action.get("effective_at", action.get("completed_before"))
            if supplied_clock is None:
                effective = datetime.combine(
                    date.fromisoformat(action["date"]),
                    calendar.REGULAR_OPEN,
                    calendar.NEW_YORK,
                ).astimezone(UTC)
            else:
                effective = aware(supplied_clock)
            for day in {
                action["date"],
                effective.astimezone(calendar.NEW_YORK).date().isoformat(),
            }:
                events.setdefault(day, []).append(
                    (effective, priority[action["kind"]], symbol, action)
                )
    return {
        day: sorted(rows, key=lambda event: event[:2]) for day, rows in events.items()
    }


# Apply source events only at actual opening/nightly observations, once per identity.
def fold_actions(events, now, held, basis, dividends, records, seen, ledger):
    now = aware(now.isoformat())
    local = now.astimezone(calendar.NEW_YORK)
    for effective, _, symbol, action in events.get(local.date().isoformat(), ()):
        if effective > now:
            continue
        kind = action["kind"]
        if kind == "archive_adjustment":
            continue
        identity = (
            "split"
            if kind == "share_split"
            else f"stock_distribution/{action['child']}"
            if kind == "stock_distribution"
            else kind
        )
        key = (symbol, identity, effective.isoformat())
        if key in seen:
            continue
        seen.add(key)
        if kind in ("split", "share_split"):
            if symbol in held:
                held[symbol] *= action["value"]
                if basis[symbol] is not None:
                    basis[symbol] /= action["value"]
        elif kind == "dividend":
            dividends.append(
                {
                    "action_key": list(key),
                    "symbol": symbol,
                    "amount": held.get(symbol, 0) * action["value"],
                    "effective_at": effective.isoformat(),
                    "pay_at": None,
                    "paid": False,
                }
            )
        else:
            field, record = fold_grant(symbol, action, effective, now, held, basis)
            records[field].append(check_entitlement(ledger, field, record))


# Fold recorded trades into cash, held shares and acquisition bases.
def fold_fills(fills, cash, held, basis):
    for fill in fills:
        symbol, qty, price, fee = (
            fill["symbol"],
            fill["filled_qty"],
            fill["price"],
            fill["fee"],
        )
        if not qty:
            continue
        if fill["side"] == "buy":
            before = held.get(symbol, 0)
            prior_basis = basis.get(symbol, 0)
            basis[symbol] = (
                price
                if not before
                else (
                    (before * prior_basis + qty * price) / (before + qty)
                    if prior_basis is not None
                    else None
                )
            )
            held[symbol] = before + qty
            cash -= qty * price + fee
        else:
            require(held.get(symbol, 0) >= qty, "Saved sale is uncovered")
            held[symbol] -= qty
            cash += qty * price - fee
            if not held[symbol]:
                held.pop(symbol)
                basis.pop(symbol)
        require(cash >= -1e-7, "Saved fill spends unfunded cash")
    return cash


# Check the matched ETF's single raw opening purchase and unavailable-entry status.
def check_benchmark_entry(account, spec, data, dates):
    fills, attempts = account["fills"], account["attempts"]
    require(
        all(fill["symbol"] == spec["arm"] and fill["side"] == "buy" for fill in fills)
        and len(fills) <= 1,
        "Benchmark is not buy-and-hold",
    )
    price = original_price(data, spec["arm"], str(dates[1]), calendar.REGULAR_OPEN)
    entry = {
        "status": "opening_price_unavailable",
        "symbol": spec["arm"],
        "session": str(dates[1]),
        "qty": None,
    }
    if price is not None:
        qty = math.floor(100000 / (price * (1 + spec["cost_bps"] / 1e4)))
        entry.update(
            qty=qty,
            price=price,
            status="filled_opening_proxy" if qty else "insufficient_cash_for_one_share",
        )
        require(len(fills) == int(qty > 0), "Benchmark entry receipt missing")
        if qty:
            require(
                fills[0]["requested_qty"] == fills[0]["filled_qty"] == qty
                and receipt_day(fills[0]) == str(dates[1]),
                "Benchmark capital/entry differs",
            )
    else:
        require(
            not attempts and not fills,
            "Unavailable benchmark entry was substituted",
        )
    same(account["entry"], entry, "benchmark entry")


# Retain original intent identities and every saved nightly boundary.
def check_policy_receipts(account, data, dates):
    intents = account["intents"]
    require(
        len({row["client_order_id"] for row in intents}) == len(intents),
        "Duplicate original intents",
    )
    for row in intents:
        whole(row["qty"])
        require(
            row["symbol"] in data["names"]
            and row["side"] in ("buy", "sell")
            and str(dates[0]) <= row["session"] <= str(dates[-1]),
            "Intent source/date bounds differ",
        )
    known = {row["client_order_id"]: row for row in intents}
    for row in account["attempts"]:
        require(row["client_order_id"] in known, "Submission missing original intent")
        intended = known[row["client_order_id"]]
        require(
            row["symbol"] == intended["symbol"]
            and row["side"] == intended["side"]
            and row["qty"] <= intended["qty"],
            "Submission differs from original intent",
        )
    require(
        [row["session"] for row in account["nightlies"]] == list(map(str, dates)),
        "Nightly gaps hidden",
    )


# Validate priced holdings and explicit unpaid claims against a saved session.
def check_valuation(row, data, global_index, observed, cash, held, dividends, records):
    day = row["session"]
    closing = datetime.combine(
        date.fromisoformat(day),
        calendar.session_close(date.fromisoformat(day)),
        calendar.NEW_YORK,
    )
    missing_marks, unknown_claim_marks = 0, 0
    marks = dict(zip(data["names"], data["close"][global_index], strict=True))
    passive = data.get("passive")
    if passive is not None:
        marks.update(
            zip(passive["names"], passive["close"][global_index], strict=True)
            if observed > closing
            else dict.fromkeys(passive["names"], np.nan).items()
        )
    absent = [
        name
        for name, qty in held.items()
        if qty and not np.isfinite(marks.get(name, np.nan))
    ]
    unknown = {
        field: [
            item
            for item in records[field]
            if item.get("fractional_qty", 0) > 0 and item["cash_in_lieu"] is None
        ]
        for field in (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
        )
    }
    unpriced = [item for group in unknown.values() for item in group]
    if unpriced:
        unknown_claim_marks += 1
        expected_status = (
            "unknown_exchange_cash_in_lieu"
            if unknown["security_exchanges"]
            else "unknown_consolidation_cash_in_lieu"
            if unknown["share_consolidations"]
            else "unknown_distribution_cash_in_lieu"
        )
        require(
            row["nav"] is None
            and row["price_nav"] is None
            and row["status"] == expected_status,
            "Unpriced entitlement NAV was fabricated",
        )
        same(row["unpriced_entitlements"], unpriced, f"{day} unpriced claims")
    elif absent:
        missing_marks += 1
        require(
            row["nav"] is None
            and row["price_nav"] is None
            and row["status"] == "missing_held_close"
            and row["missing_symbols"] == absent,
            "Missing held NAV was hidden or filled",
        )
    else:
        price_nav = cash + sum(qty * marks[name] for name, qty in held.items())
        receivable = sum(item["amount"] for item in dividends)
        merger_receivable = sum(item["amount"] for item in records["cash_mergers"])
        same(row["price_nav"], price_nav, f"{day} price NAV")
        same(row["dividend_receivable"], receivable, f"{day} receivable")
        if records["cash_mergers"]:
            same(row["merger_receivable"], merger_receivable, f"{day} merger claim")
        same(
            row["nav"],
            price_nav + receivable + merger_receivable,
            f"{day} funded NAV",
        )
        require(row["status"] == "marked_raw_close", "Raw NAV status differs")
    return missing_marks, unknown_claim_marks


# Fold recorded transactions under the caller's explicit account-policy identity.
def reconcile_account(account, spec, data, *, account_policy=POLICY):
    require(
        account["adoption_eligible"] is False
        and account["economic_status"] == "conditional_current_vintage_private_proxy",
        "Account limitations missing",
    )
    same(account["comparison_account"], spec, "account grid")
    dates = data["dates"][spec["first"] - 1 : spec["last"] + 1]
    require(
        account["first"] == str(dates[1]) and account["last"] == str(dates[-1]),
        "Account date bounds differ",
    )
    same(account["initial_cash"], 100000.0, "funded capital")
    same(account["cost_bps"], spec["cost_bps"], "per-side cost")
    benchmark = spec["arm"] in BENCHMARKS
    require(
        account["policy"]
        == ("whole-share-buy-and-hold/1-research" if benchmark else account_policy),
        "Account policy differs",
    )
    if benchmark:
        require(account["symbol"] == spec["arm"], "Benchmark symbol differs")
    sessions = account["sessions"]
    require(
        [row["session"] for row in sessions] == list(map(str, dates))
        and [row["initial"] for row in sessions] == [True] + [False] * (len(dates) - 1),
        "Every account session/baseline required",
    )
    attempts, fills = account["attempts"], account["fills"]
    accepted = validate_attempts(attempts, dates, data)
    by_day = validate_fills(fills, accepted, spec, data, dates)
    cash, held, basis, dividends = 100000.0, {}, {}, []
    ledger = account["broker"]
    records = dict.fromkeys(
        (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        )
    )
    records = {field: [] for field in records}
    events, seen = source_events(data), set()
    missing_marks = 0
    unknown_claim_marks = 0
    for index, row in enumerate(sessions):
        day = row["session"]
        opening = datetime.combine(
            date.fromisoformat(day), calendar.REGULAR_OPEN, calendar.NEW_YORK
        )
        closing = datetime.combine(
            date.fromisoformat(day),
            calendar.session_close(date.fromisoformat(day)),
            calendar.NEW_YORK,
        )
        observed = closing if benchmark else closing + timedelta(minutes=1)
        if index:
            fold_actions(events, opening, held, basis, dividends, records, seen, ledger)
            cash = fold_fills(by_day.get(day, []), cash, held, basis)
        if not benchmark:
            fold_actions(
                events, observed, held, basis, dividends, records, seen, ledger
            )
        same(row["cash"], cash, f"{day} cash")
        same(row["holdings"], held, f"{day} shares")
        global_index = spec["first"] - 1 + index
        missing, unknown = check_valuation(
            row, data, global_index, observed, cash, held, dividends, records
        )
        missing_marks += missing
        unknown_claim_marks += unknown
    same(ledger["cash"], cash, "final cash")
    same(ledger["holdings"], held, "final holdings")
    same(ledger["average_prices"], basis, "final acquisition basis")
    same(ledger["dividends"], dividends, "final unpaid dividend entitlements")
    for field, expected in records.items():
        same(ledger.get(field, []), expected, f"final {field}")
    final_clock = datetime.combine(
        date.fromisoformat(str(dates[-1])),
        calendar.session_close(dates[-1].astype(object)),
        calendar.NEW_YORK,
    )
    expected_clock = (
        final_clock if benchmark else final_clock.replace(minute=final_clock.minute + 1)
    )
    require(
        aware(ledger["observed_at"]) == expected_clock.astimezone(UTC),
        "Final observed clock differs",
    )
    if benchmark:
        check_benchmark_entry(account, spec, data, dates)
    else:
        check_policy_receipts(account, data, dates)
    return {
        "sessions": len(sessions) - 1,
        "fills": len(fills),
        "attempts": len(attempts),
        "missing_held_marks": missing_marks,
        "dividend_entitlements": len(dividends),
        "unknown_claim_marks": unknown_claim_marks,
    }


# Count unmet original intents independently of repeated refusal attempts.
def remaining_intents(account, lower, upper):
    executed = {}
    for row in account["fills"]:
        if receipt_day(row) < upper:
            executed[row["client_order_id"]] = (
                executed.get(row["client_order_id"], 0) + row["filled_qty"]
            )
    remaining, unexecuted = {}, 0
    _, sessions = calendar.reviewed_sessions()
    for row in account.get("intents", []):
        execution_day = row.get("execute_on")
        if execution_day is None:
            execution_day = str(
                np.busday_offset(
                    np.datetime64(row["session"]),
                    1,
                    roll="backward",
                    busdaycal=sessions,
                )
            )
        if lower <= execution_day < upper:
            qty = max(0, row["qty"] - executed.get(row["client_order_id"], 0))
            unexecuted += qty > 0
            remaining[row["symbol"]] = remaining.get(row["symbol"], 0) + qty
    return remaining, unexecuted


# Recompute fixed-window arithmetic from saved wealth and receipt records only.
def independent_score(account, lower, upper):
    positions = [
        i
        for i, row in enumerate(account["sessions"])
        if not row["initial"] and lower <= row["session"] < upper
    ]
    if not positions:
        return {"status": "no_sessions", "sessions": 0, "total_gain": None}
    selected = account["sessions"][positions[0] - 1 : positions[-1] + 1]
    wealth = [row["nav"] for row in selected]
    known = all(value is not None and math.isfinite(value) for value in wealth)
    require(
        all(value is None or value >= 0 for value in wealth),
        "Negative unlevered wealth",
    )
    complete = known and min(wealth) > 0
    zero = known and min(wealth) == 0
    endpoints = wealth[0] is not None and wealth[-1] is not None and wealth[0] > 0
    gain = wealth[-1] / wealth[0] - 1 if endpoints else None
    price_start, price_end = selected[0]["price_nav"], selected[-1]["price_nav"]
    price_gain = (
        price_end / price_start - 1
        if price_start is not None
        and price_end is not None
        and price_start > 0
        and price_end >= 0
        else None
    )
    annual, sharpe, drawdown = None, None, None
    if complete:
        returns = np.array(
            [
                after / before - 1
                for before, after in zip(wealth[:-1], wealth[1:], strict=True)
            ]
        )
        # Mirror the declared reference convention by compounding each adjacent return.
        curve = np.concatenate(([1.0], np.cumprod(returns + 1)))
        annual = float(curve[-1] ** (252 / len(returns)) - 1)
        drawdown = float(max(1 - curve / np.maximum.accumulate(curve)))
        volatility = float(np.std(returns, ddof=0) * math.sqrt(252))
        sharpe = float(np.mean(returns) * 252 / volatility) if volatility > 0 else None
    elif zero and wealth[0] > 0:
        annual = -1.0 if wealth[-1] == 0 else None
        drawdown = float(max(1 - np.array(wealth) / np.maximum.accumulate(wealth)))
    fills = [row for row in account["fills"] if lower <= receipt_day(row) < upper]
    refused = [
        row
        for row in account["attempts"]
        if row["accepted"] is False and lower <= receipt_day(row) < upper
    ]
    remaining, unexecuted = remaining_intents(account, lower, upper)
    denominators = {
        after["session"]: before["nav"]
        for before, after in zip(selected[:-1], selected[1:], strict=True)
    }
    turnover = 0.0
    for row in fills:
        previous = denominators.get(receipt_day(row))
        if previous is None or previous <= 0:
            turnover = None
            break
        turnover += row["filled_qty"] * (row["price"] or 0) / previous
    exposures = [
        (row["price_nav"] - row["cash"]) / row["nav"]
        for row in selected[1:]
        if row["nav"] is not None and row["nav"] > 0 and row["price_nav"] is not None
    ]
    return {
        "status": "complete"
        if complete
        else "zero_wealth"
        if zero
        else "missing_wealth_observations",
        "sessions": len(positions),
        "missing_nav_marks": sum(value is None for value in wealth),
        "total_gain": gain,
        "price_component_gain": price_gain,
        "ending_dividend_receivable": selected[-1].get("dividend_receivable"),
        "cagr": annual,
        "drawdown_positive_loss": drawdown,
        "sharpe": sharpe,
        "fees": sum(row["fee"] for row in fills),
        "missed_fill_quantity": sum(
            row["requested_qty"] - row["filled_qty"] for row in fills
        ),
        "refused_attempt_quantity": sum(row["qty"] for row in refused),
        "refused_attempts": len(refused),
        "refused_unique_intents": len({row["client_order_id"] for row in refused}),
        "unexecuted_original_intents": unexecuted,
        "remaining_original_qty_by_symbol": remaining,
        "quantity_basis": (
            "order_share_units_not_capital;refusal_retries_counted_as_attempts"
        ),
        "realized_notional": sum(
            row["filled_qty"] * (row["price"] or 0) for row in fills
        ),
        "realized_turnover": turnover,
        "mean_end_session_exposure": float(np.mean(exposures)) if complete else None,
        "benchmark_reference_available": account["entry"]["status"]
        == "filled_opening_proxy"
        if "entry" in account
        else None,
    }


# Independently pair every original start with rule and both matched ETF controls.
def independent_summary(rows):
    indexed = {(row["arm"], row["cost_bps"], row["start"]): row for row in rows}
    result = []
    for method in ARMS[1:]:
        for cost in COSTS:
            for window, _, _ in WINDOWS:
                pairs = []
                for start in range(20):
                    own = indexed[(method, cost, start)]["scores"][window]
                    rule = indexed[("rule", cost, start)]["scores"][window]
                    delta = (
                        own["total_gain"] - rule["total_gain"]
                        if own["total_gain"] is not None
                        and rule["total_gain"] is not None
                        else None
                    )
                    excess = {}
                    for name in BENCHMARKS:
                        other = indexed[(name, cost, start)]["scores"][window]
                        excess[name] = (
                            own["total_gain"] - other["total_gain"]
                            if own["total_gain"] is not None
                            and other["total_gain"] is not None
                            and other.get("benchmark_reference_available") is True
                            else None
                        )
                    pairs.append(
                        {
                            "start": start,
                            "candidate_status": own["status"],
                            "rule_status": rule["status"],
                            "gain_difference": delta,
                            "benchmark_excess": excess,
                        }
                    )
                values = [
                    row["gain_difference"]
                    for row in pairs
                    if row["gain_difference"] is not None
                ]
                result.append(
                    {
                        "method": method,
                        "cost_bps": cost,
                        "window": window,
                        "starts": 20,
                        "endpoint_pairs": len(values),
                        "complete_risk_pairs": sum(
                            row["candidate_status"] == row["rule_status"] == "complete"
                            for row in pairs
                        ),
                        "median_gain_difference": float(np.median(values))
                        if values
                        else None,
                        "minimum": min(values) if values else None,
                        "maximum": max(values) if values else None,
                        "count_better": sum(value > 0 for value in values),
                        "pairs": pairs,
                    }
                )
    return result


# Read one immutable gzip account with its exact report-bound hash and path.
def read_account(study, row):
    relative = Path(row["file"])
    require(
        not relative.is_absolute()
        and ".." not in relative.parts
        and relative == Path("accounts") / (row["id"] + ".json.gz"),
        "Unsafe or mismatched account path",
    )
    path = study / relative
    require(digest(path) == row["sha256"], "Compressed account hash differs")
    account = decode(gzip.decompress(path.read_bytes()))
    require(digest(path) == row["sha256"], "Account changed while reading")
    return account


# Verify saved accounts and report arithmetic without invoking any producer path.
def verify_saved(study, report, identity, data, *, grid=None):
    grid = fixed_grid(data["dates"]) if grid is None else grid
    same(identity["accounts"], grid, "declared grid")
    require(
        report["status"] == "complete_pending_independent_verification"
        and report["policy"] == POLICY
        and report["adoption_eligible"] is False,
        "Completed research report required",
    )
    require(len(report["accounts"]) == len(grid), "Declared accounts missing")
    counters = {
        "sessions": 0,
        "fills": 0,
        "attempts": 0,
        "missing_held_marks": 0,
        "dividend_entitlements": 0,
        "unknown_claim_marks": 0,
    }
    checked = []
    for spec, row in zip(grid, report["accounts"], strict=True):
        same({key: row[key] for key in spec}, spec, "reported account grid")
        account = read_account(study, row)
        counts = reconcile_account(account, spec, data)
        scores = {
            name: independent_score(account, lower, upper)
            for name, lower, upper in WINDOWS
        }
        same(row["scores"], scores, f"{spec['id']} scores")
        same(row["fill_records"], len(account["fills"]), "fill count")
        same(row["intents"], len(account.get("intents", [])), "intent count")
        same(
            row["forecast_decisions"],
            len(account.get("forecast_decisions", [])),
            "forecast count",
        )
        for key, value in counts.items():
            counters[key] += value
        checked.append({**spec, "sha256": row["sha256"], "scores": scores})
    # A nonfixed grid is used only by explicit synthetic unit workflows.
    summary = independent_summary(checked) if len(grid) == 300 else None
    if summary is not None:
        same(report["summary"], summary, "paired summary")
    return {
        "accounts": len(grid),
        "policy_accounts": sum(row["arm"] in ARMS for row in grid),
        "benchmark_accounts": sum(row["arm"] in BENCHMARKS for row in grid),
        "counts": counters,
        "summary": summary,
    }


# Authenticate original bytes around saved-only checks and write a fresh proof.
def verify(args):
    study, output = Path(args.study), Path(args.output)
    require(
        not output.exists()
        and not output.is_symlink()
        and not output.resolve().is_relative_to(study.resolve()),
        "Fresh independent proof folder required",
    )
    require(
        len(args.verifier_revision) == 40
        and all(c in "0123456789abcdef" for c in args.verifier_revision),
        "Exact verifier source revision required",
    )
    identity_hash, report_hash = (
        digest(study / "identity.json"),
        digest(study / "report.json"),
    )
    identity, report = (
        read_json(study / "identity.json"),
        read_json(study / "report.json"),
    )
    require(report["identity_sha256"] == identity_hash, "Report identity hash differs")
    source_root = Path(args.producer_source)
    check_identity(
        identity,
        args.source_manifest,
        args.source_revision,
        args.producer_image,
        source_root,
    )
    check_originals(identity["original_files"])
    if getattr(args, "reviewed_economics", False):
        data = load_original_data(args, identity, reviewed=True)
    else:
        data = load_original_data(args, identity)
    result = verify_saved(study, report, identity, data)
    check_originals(identity["original_files"])
    check_identity(
        identity,
        args.source_manifest,
        args.source_revision,
        args.producer_image,
        source_root,
    )
    require(
        digest(study / "identity.json") == identity_hash
        and digest(study / "report.json") == report_hash,
        "Study changed during saved verification",
    )
    proof = {
        "status": "VERIFIED_SAVED_ACCOUNT_ARITHMETIC",
        "policy": POLICY,
        "producer_source": identity["source"],
        "producer_runtime": identity["runtime"],
        "identity_sha256": identity_hash,
        "report_sha256": report_hash,
        "verifier_source_revision": args.verifier_revision,
        "verifier_modules": {
            "backend/cli/verify_actual_policy_timing.py": digest(__file__),
            "backend/market/calendar.py": digest(Path(calendar.__file__)),
            **{
                str(path.relative_to(Path(__file__).resolve().parents[2])): digest(path)
                for path in (Path(__file__).resolve().parents[1] / "market/data").glob(
                    "nyse_*.json"
                )
            },
        },
        "verifier_runtime": {
            "python": sys.version,
            "numpy": np.__version__,
            "platform": platform.platform(),
            "image_id": args.verifier_image,
        },
        "verified": result,
        "models_called": 0,
        "accounts_resimulated": 0,
        "unverified": [
            "all_name_corporate_action_declaration_history_and_payment_completeness",
            "same_day_split_dividend_ordering_external_authentication",
            "historical_publication_and_exact_live_eligibility",
            "actual_broker_fills_latency_and_corporate_action_processing",
            "forecast_causality_and_model_quality_not_retested",
            "planner_sender_decision_parity_not_resimulated",
            "submission_reservation_and_same_batch_funding_policy_not_resimulated",
        ],
        "adoption_eligible": False,
        "written_at": datetime.now(UTC).isoformat(),
    }
    output.mkdir(parents=True, exist_ok=False)
    with (output / "proof.json").open("x") as handle:
        json.dump(proof, handle, sort_keys=True, allow_nan=False, indent=2)
        handle.write("\n")
    print(
        json.dumps(
            {
                "proof_sha256": digest(output / "proof.json"),
                "accounts": result["accounts"],
                "adoption_eligible": False,
            }
        ),
        flush=True,
    )
    return proof


# Accept explicit saved evidence paths and a pinned producer identity.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "study",
        "snapshot",
        "actions",
        "cubes",
        "source-manifest",
        "producer-source",
        "output",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in (
        "source-revision",
        "producer-image",
        "verifier-revision",
        "verifier-image",
    ):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--reviewed-economics", action="store_true")
    for name in (
        "action-review",
        "passive-arrays",
        "passive-receipt",
        "economic-input-proof",
    ):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    if args.reviewed_economics and any(
        getattr(args, name) is None
        for name in (
            "action_review",
            "passive_arrays",
            "passive_receipt",
            "economic_input_proof",
        )
    ):
        parser.error(
            "Reviewed economic verification requires "
            "all original review/passive/proof paths"
        )
    if not args.reviewed_economics and any(
        getattr(args, name) is not None
        for name in (
            "action_review",
            "passive_arrays",
            "passive_receipt",
            "economic_input_proof",
        )
    ):
        parser.error("Reviewed sources require explicit reviewed economic verification")
    verify(args)


if __name__ == "__main__":
    main()
