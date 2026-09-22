"""Validate and present the agreed funded-allocation view payload.

The shared contract's schema - `portfolio-allocation-view/1` - is the one
shape both sides of the boundary use. The paper account serializes its display
metadata into `snapshot["allocation_plan"]` in exactly this versioned
structure, and the API returns the same structure as
`decision_view`'s `portfolio_allocation`. This module does not invent a second
raw-map protocol: it validates the agreed payload and passes a well-formed one
through, and turns a missing, malformed, stale, cross-account or inconsistent
one into an explicit `status="unavailable"` payload with null weights.

What is validated before a payload is called `available` or `blocked`:

* `as_of` must be a parseable date equal to the decision session being shown;
  anything earlier is stale and anything later is inconsistent.
* `status` must be one of `available`/`unavailable`/`blocked`, and it must
  agree with the evidence: `blocked` needs a non-empty `blocked` list,
  `available` must not carry one.
* `current`, `target` and `projected` are bucket maps
  `{stocks, indexes, cash}` whose values are finite nonnegative fractions and
  which each total one - a per-symbol map in a bucket, a missing stage, an
  over-total or a NaN is rejected, never clamped, never defaulted to cash.
* `rows` is optional per-symbol detail; when present every row needs a valid
  `kind` (stock/index/cash), a valid `action` (BUY/HOLD/SELL), a `reason` and
  finite-or-null weights that agree with the stage buckets.
* `capabilities` carries eligibility only from explicit evidence: an entry
  needs a valid kind and a boolean `eligible`. Nothing is fabricated - a
  money-market or duration asset the plan does not evidence simply has no
  capability entry, and SWVXX can never read as an eligible stock here.
* `adopted` defaults False and the preview never replaces the incumbent
  decision rows' BUY/HOLD/SELL.

The whole payload stays `status="available"`, `blocked` only when the plan
says so with reasons, and `unavailable` whenever any evidence is missing,
stale or inconsistent.
"""

from __future__ import annotations

import math
from datetime import date

# The version both the stored metadata and the served payload report.
VERSION = "portfolio-allocation-view/1"

# The only instrument kinds and actions the payload can name.
KINDS = ("stock", "index", "cash")
ACTIONS = ("BUY", "HOLD", "SELL")
STATUSES = ("available", "unavailable", "blocked")

# A composition is still one when its buckets total this close to 1.
_TOL = 1e-6


# A plan's date, which must parse so freshness can be judged at all.
def _plan_date(value):
    """Return the date a plan's `as_of` or the session names, else None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


# A finite fraction, the only number shape the payload is allowed to carry.
def _fraction(value, label):
    """Return float(value) when it is a finite nonnegative number, else raise."""
    if isinstance(value, bool):
        raise ValueError(f"{label} is a boolean, not a weight")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{label} is not a number") from None
    if not math.isfinite(number) or number < 0.0:
        raise ValueError(f"{label} is not a finite nonnegative number")
    return float(number)


# A string list (missing/blocked), so malformed lists are an explicit reason.
def _string_list(raw, label):
    """Return the validated list of strings, or raise on a non-string entry."""
    if raw is None:
        return []
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise ValueError(f"{label} must be a list of strings")
    return list(raw)


# One aggregate stage: {stocks, indexes, cash}, each finite or null.
def _bucket(raw, label):
    """Return the validated stage bucket for `current`/`target`/`projected`."""
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be a bucket map")
    out = {}
    for key in ("stocks", "indexes", "cash"):
        if key not in raw:
            raise ValueError(f"{label} is missing its {key} value")
        value = raw[key]
        if value is None:
            out[key] = None
            continue
        out[key] = _fraction(value, f"{label}.{key}")
    return out


# A complete stage: every value finite and the whole composition summing to one.
def _complete_bucket(raw, label):
    """Return the validated stage bucket, requiring completeness and total one."""
    bucket = _bucket(raw, label)
    if any(bucket[key] is None for key in ("stocks", "indexes", "cash")):
        raise ValueError(f"{label} is incomplete; a null weight is not a value")
    total = bucket["stocks"] + bucket["indexes"] + bucket["cash"]
    if abs(total - 1.0) > _TOL:
        raise ValueError(f"{label} does not total one ({total:.6f})")
    return bucket


# One row entry: kind, action, reason and finite-or-null weights.
def _row_entry(symbol, entry):
    """Return the validated row map for one symbol, or raise on a bad value."""
    if not isinstance(symbol, str) or not symbol:
        raise ValueError("rows has a non-symbol key")
    if not isinstance(entry, dict):
        raise ValueError(f"row {symbol} must be a map")
    kind = entry.get("kind")
    if kind not in KINDS:
        raise ValueError(f"row {symbol} has an unknown kind")
    action = entry.get("action")
    if action not in ACTIONS:
        raise ValueError(f"row {symbol} has an unknown action")
    reason = entry.get("reason")
    if not isinstance(reason, str):
        raise ValueError(f"row {symbol} lacks a reason")
    weights = {}
    for key in ("current_weight", "target_weight", "projected_weight"):
        value = entry.get(key)
        if value is None:
            weights[key] = None
            continue
        weights[key] = _fraction(value, f"row {symbol} {key}")
    return {"kind": kind, **weights, "action": action, "reason": reason}


# The optional per-symbol detail, validated against the stage buckets.
def _rows(raw, buckets):
    """Return the validated rows map, or raise on inconsistency."""
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("rows must be a map")
    out = {symbol: _row_entry(symbol, entry) for symbol, entry in raw.items()}
    if out:
        _rows_agree_with_buckets(out, buckets)
    return out


# Row detail must not contradict the aggregate buckets it claims to detail.
def _rows_agree_with_buckets(rows, buckets):
    """Raise unless each stage's per-kind row sums equal its bucket."""
    bucket_key = {"stock": "stocks", "index": "indexes", "cash": "cash"}
    for stage, weight_key in (
        ("current", "current_weight"),
        ("target", "target_weight"),
        ("projected", "projected_weight"),
    ):
        for kind in KINDS:
            bucket_value = buckets[stage][bucket_key[kind]]
            if bucket_value is None:
                raise ValueError(f"{stage} bucket is incomplete beside rows")
            total = sum(
                row[weight_key]
                for row in rows.values()
                if row["kind"] == kind and row[weight_key] is not None
            )
            incomplete = any(
                row[weight_key] is None for row in rows.values() if row["kind"] == kind
            )
            if incomplete:
                raise ValueError(f"row {weight_key} is null beside a complete bucket")
            if abs(total - bucket_value) > _TOL:
                raise ValueError(
                    f"{stage} {kind} rows sum to {total:.6f}, bucket says "
                    f"{bucket_value:.6f}"
                )


# The capability list; eligibility comes only from the plan's own entries.
def _capabilities(raw):
    """Return the validated capability list, or [] when the plan gave none."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("capabilities must be a list")
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ValueError("a capability must be a map")
        symbol = entry.get("symbol")
        kind = entry.get("kind")
        eligible = entry.get("eligible")
        reason = entry.get("reason")
        if (
            not isinstance(symbol, str)
            or not symbol
            or kind not in KINDS
            or not isinstance(eligible, bool)
            or not isinstance(reason, str)
        ):
            raise ValueError(
                "a capability needs a symbol, a valid kind, "
                "an eligibility boolean and a reason"
            )
        out.append(
            {"symbol": symbol, "kind": kind, "eligible": eligible, "reason": reason}
        )
    return out


# The explicit unavailable payload, with whatever provenance the plan did give.
def _unavailable(reason, plan=None):
    """Return a status=unavailable payload; no weights are invented."""
    as_of = plan.get("as_of") if isinstance(plan, dict) else None
    policy = plan.get("policy") if isinstance(plan, dict) else None
    missing = blocked = []
    if isinstance(plan, dict):
        try:
            missing = _string_list(plan.get("missing"), "missing")
            blocked = _string_list(plan.get("blocked"), "blocked")
        except ValueError:
            missing = blocked = []
    return {
        "version": VERSION,
        "as_of": as_of if isinstance(as_of, str) else None,
        "policy": policy if isinstance(policy, str) else None,
        "status": "unavailable",
        "adopted": False,
        "reason": reason,
        "missing": missing,
        "blocked": blocked,
        "current": {"stocks": None, "indexes": None, "cash": None},
        "target": {"stocks": None, "indexes": None, "cash": None},
        "projected": {"stocks": None, "indexes": None, "cash": None},
        "rows": {},
        "capabilities": [],
    }


# The provenance and evidence gates that decide between pass-through and rejection.
def _validate_plan(plan, *, session, expected_account):
    """Return (fields, None) or (None, unavailable payload) for `plan`."""
    if plan is None:
        return None, _unavailable("no allocation metadata recorded")
    if not isinstance(plan, dict):
        return None, _unavailable("allocation metadata malformed")
    if (
        expected_account is not None
        and plan.get("account") is not None
        and str(plan.get("account")) != str(expected_account)
    ):
        return None, _unavailable(
            "allocation metadata belongs to another account", plan
        )
    as_of = _plan_date(plan.get("as_of"))
    if as_of is None:
        return None, _unavailable("allocation metadata is undated", plan)
    if session is not None:
        mismatch = _stale_mismatch(as_of, session)
        if mismatch is not None:
            return None, _unavailable(mismatch, plan)
    status = plan.get("status")
    if status not in STATUSES:
        return None, _unavailable("allocation metadata has no usable status", plan)
    if status == "unavailable":
        return None, _unavailable(
            plan.get("reason") or "allocation evidence was incomplete", plan
        )
    try:
        fields = _read_fields(plan, status)
    except ValueError as exc:
        return None, _unavailable(str(exc), plan)
    return fields, None


# Why a plan's date does not match the decision session, as a reason string.
def _stale_mismatch(as_of, session):
    """Return the staleness reason when `as_of` differs from `session`."""
    session_date = _plan_date(session)
    if session_date is None or as_of == session_date:
        return None
    if as_of < session_date:
        return (
            "allocation metadata is stale for the current decision session "
            f"(plan {as_of}, expected {session_date})"
        )
    return (
        "allocation metadata is inconsistent with the current decision session "
        f"(plan {as_of}, expected {session_date})"
    )


# Pull every field a pass-through payload needs, fully validated.
def _read_fields(plan, status):
    """Return the validated fields for an available or blocked plan."""
    buckets = {
        stage: _complete_bucket(plan.get(stage), stage)
        for stage in ("current", "target", "projected")
    }
    rows = _rows(plan.get("rows"), buckets)
    capabilities = _capabilities(plan.get("capabilities"))
    missing = _string_list(plan.get("missing"), "missing")
    blocked = _string_list(plan.get("blocked"), "blocked")
    if status == "blocked" and not blocked:
        raise ValueError("blocked status without any blocked reason")
    if status == "available" and blocked:
        raise ValueError("available status with blocked symbols is inconsistent")
    policy = plan.get("policy")
    if policy is not None and not isinstance(policy, str):
        raise ValueError("policy must be a string")
    reason = plan.get("reason")
    if reason is not None and not isinstance(reason, str):
        raise ValueError("reason must be a string")
    adopted = plan.get("adopted", False)
    if not isinstance(adopted, bool):
        raise ValueError("adopted must be a boolean")
    return {
        "as_of": _plan_date(plan.get("as_of")),
        "status": status,
        "adopted": adopted,
        "policy": policy,
        "reason": reason,
        "missing": missing,
        "blocked": blocked,
        "current": buckets["current"],
        "target": buckets["target"],
        "projected": buckets["projected"],
        "rows": rows,
        "capabilities": capabilities,
    }


# The serializer: one plan becomes the validated portfolio_allocation payload.
def serialize(plan, *, session=None, expected_account=None):
    """Return the portfolio_allocation payload for `snapshot['allocation_plan']`.

    `session` is the decision session being shown (the record's session): a
    plan whose `as_of` differs from it is stale or inconsistent and becomes
    explicitly unavailable. `expected_account` is the account identity the plan
    must belong to when it names one. The result never raises and always
    carries every payload field.
    """
    fields, failure = _validate_plan(
        plan, session=session, expected_account=expected_account
    )
    if failure is not None:
        return failure
    return {
        "version": VERSION,
        "as_of": str(fields["as_of"]),
        "policy": fields["policy"],
        "status": fields["status"],
        "adopted": fields["adopted"],
        "reason": (
            fields["reason"] or "funded allocation preview from recorded metadata"
        ),
        "missing": fields["missing"],
        "blocked": fields["blocked"],
        "current": fields["current"],
        "target": fields["target"],
        "projected": fields["projected"],
        "rows": fields["rows"],
        "capabilities": fields["capabilities"],
    }
