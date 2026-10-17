"""Frozen private ReplayBroker checkpoints, never production-account restoration.

Ordered pairs preserve FIFO maps; only explicit primitive/tuple/datetime types
are decoded. Caps PAUSE without truncation and are not full-horizon feasibility
proof. Current-state consistency does not replace an independent economic audit.
"""

import hashlib
import json
import math
from copy import deepcopy
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path
from types import MappingProxyType

import numpy as np

from backend.market import replay_broker as native
from backend.market.historical_packet_registry import digest, symbol
from backend.market.historical_timing_packet import _decode, _digest

N2 = "ad44d536a70d5c037cb931836a3c9f48b014d84a"
IMAGE = "sha256:e0a54c1f3b293c241ea0eae767d8ba017d0e1a05679965935b336910faa63237"
BROKER = "c3d427e180e6b7527d3b666a450c6076b24e1cd75bfce1786852dced9eb2d616"
CALENDAR = "f5ceca3cd12484f66a13f75026c4466970c8810496bf7b7871f5973d749f05f4"
CONFIGS = {
    "holding_config_sha256": (
        "338e2a490d13cc889667d577ec93ba68f775863a8c1db385fed3dd77fee26dcc"
    ),
    "holding_release_sha256": (
        "bb6c24aabb33daff30bd7af5b6c505208cc996c38929a84b54573662bab1bd4c"
    ),
    "timing_config_sha256": (
        "d03339a3ad4b590ef8ed4205375d39d634df12a6fb49e290ab5b0f3642ea679a"
    ),
}
CAPS = MappingProxyType(
    {
        "bytes": 8 * 1024**2,
        "names": 256,
        "orders": 8192,
        "attempts": 16384,
        "fills": 8192,
        "actions": 8192,
        "dividends": 8192,
        "claims_per_kind": 2048,
        "records": 32768,
        "string_chars": 512,
        "depth": 16,
    }
)
FIELDS = {
    "_cash",
    "cost_bps",
    "_held",
    "_average",
    "_orders",
    "_attempts",
    "_fills",
    "_actions",
    "_dividends",
    "_marks",
    "_mark_times",
    "_security_distributions",
    "_security_exchanges",
    "_share_consolidations",
    "_cash_mergers",
    "_now",
    "_observed_at",
    "_market_open",
    "_batch_open",
    "_last_equity",
}
CLAIMS = (
    "_security_distributions",
    "_security_exchanges",
    "_share_consolidations",
    "_cash_mergers",
)
ORDER = {
    "id",
    "client_order_id",
    "symbol",
    "side",
    "qty",
    "type",
    "time_in_force",
    "status",
    "filled_qty",
    "filled_avg_price",
    "created_at",
    "submitted_at",
    "execution_phase",
    "execute_on",
    "reserved_cash",
    "fee",
}
ATTEMPT = {
    "client_order_id",
    "symbol",
    "side",
    "qty",
    "at",
    "observed_price",
    "available_cash",
    "accepted",
    "reason",
}
FILL = {
    "client_order_id",
    "symbol",
    "side",
    "requested_qty",
    "filled_qty",
    "price",
    "fee",
    "at",
    "status",
    "reason",
}


# Preserve resource exhaustion as a same-identity pause, never missing account data.
class CheckpointPause(ValueError):  # noqa: N818 -- Explicit operational pause.
    """The complete original checkpoint exceeds a fixed declared resource bound."""


# Reject malformed schemas rather than ignoring unknown native fields.
def _fields(value, required, optional=frozenset()):
    if type(value) is not dict or not required <= set(value) <= required | optional:
        raise ValueError("Unknown/missing checkpoint fields")


# Preserve financial types while rejecting booleans and nonfinite values.
def _number(value, *, positive=False, nullable=False):
    if value is None and nullable:
        return
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or (value <= 0 if positive else value < 0)
    ):
        raise ValueError("Finite native numeric value required")


# Require exact whole quantities without equating floats or booleans with integers.
def _integer(value, *, zero=False):
    if type(value) is not int or value < (0 if zero else 1):
        raise ValueError("Exact native integer required")


# Retain bounded nonempty source strings without permitting arbitrary object payloads.
def _text(value):
    if type(value) is not str or not value:
        raise ValueError("Explicit native string required")
    if len(value) > CAPS["string_chars"]:
        raise CheckpointPause("Checkpoint string cap; PAUSED")


# Preserve native UTC clock strings without assigning timezone or losing precision.
def _time(value):
    _text(value)
    instant = native._instant(value)
    if instant.isoformat() != value:
        raise ValueError("Canonical native UTC clock string required")
    return instant


# Check externally pinned frozen source/config without reading live selectors.
def _identity(identity, expected_sha256):
    _fields(
        identity,
        {
            "source_revision",
            "backend_image",
            "broker_sha256",
            "calendar_sha256",
            "source_sha256",
            *CONFIGS,
        },
    )
    if _digest(identity) != digest(expected_sha256):
        raise ValueError("Externally pinned checkpoint identity differs")
    expected = {
        "source_revision": N2,
        "backend_image": IMAGE,
        "broker_sha256": BROKER,
        "calendar_sha256": CALENDAR,
        **CONFIGS,
    }
    if any(identity[k] != v for k, v in expected.items()):
        raise ValueError("Frozen N2 source/config identity differs")
    sources = identity["source_sha256"]
    if type(sources) is not dict or len(sources) != 31:
        raise ValueError("Exact externally pinned31-source chain required")
    root = Path(native.__file__).resolve().parents[2]
    for name, expected_hash in {
        **sources,
        "backend/market/replay_broker.py": BROKER,
        "backend/market/calendar.py": CALENDAR,
    }.items():
        if (
            type(name) is not str
            or not (
                (name.startswith("backend/") and name.endswith(".py"))
                or (name.startswith("docs/research/") and name.endswith(".md"))
            )
            or ".." in Path(name).parts
        ):
            raise ValueError("Bounded native source path required")
        path = root / name
        if path.stat().st_size > 256 * 1024 or hashlib.sha256(
            path.read_bytes()
        ).hexdigest() != digest(expected_hash):
            raise ValueError("Actual frozen source bytes differ")


# Preserve ordered mappings and tuple action keys using only known JSON-safe types.
def _pack(value, depth=0, used=None):  # noqa: C901 -- Bounded explicit type encoding.
    used = [0] if used is None else used
    if depth > CAPS["depth"]:
        raise CheckpointPause("Checkpoint depth cap; PAUSED")
    kind = type(value)
    if kind is str and len(value) > CAPS["string_chars"]:
        raise CheckpointPause("Checkpoint string cap before expansion; PAUSED")
    if kind in (str, int, float, bool, type(None)):
        cost = len(json.dumps(value, allow_nan=False).encode())
    else:
        cost = (
            64
            if kind is datetime
            else 16 + (4 * len(value) if kind in (dict, list, tuple) else 0)
        )
    used[0] += cost
    if used[0] > CAPS["bytes"]:
        raise CheckpointPause("Checkpoint packing byte cap; PAUSED")
    if kind is datetime:
        if value.tzinfo is not UTC:
            raise ValueError("Native UTC datetime required")
        return {"datetime": value.isoformat()}
    if kind is dict:
        return {
            "map": [
                [_pack(k, depth + 1, used), _pack(v, depth + 1, used)]
                for k, v in value.items()
            ]
        }
    if kind in (list, tuple):
        return {kind.__name__: [_pack(v, depth + 1, used) for v in value]}
    if kind is str:
        if len(value) > CAPS["string_chars"]:
            raise CheckpointPause("Checkpoint string cap; PAUSED")
    elif kind not in (int, float, bool, type(None)):
        raise ValueError("Unknown checkpoint value type")
    if kind is float and not math.isfinite(value):
        raise ValueError("Nonfinite checkpoint value")
    return value


# Decode only explicit containers and datetimes, never a named Python class or pickle.
def _unpack(value, depth=0):  # noqa: C901 -- Explicit restricted type variants.
    if depth > CAPS["depth"]:
        raise CheckpointPause("Checkpoint depth cap; PAUSED")
    if type(value) is not dict:
        if type(value) not in (str, int, float, bool, type(None)):
            raise ValueError("Unknown checkpoint scalar type")
        _pack(value, depth)
        return value
    if len(value) != 1:
        raise ValueError("Exact checkpoint type tag required")
    tag, body = next(iter(value.items()))
    if tag == "datetime":
        return _time(body)
    if type(body) is not list or tag not in {"map", "list", "tuple"}:
        raise ValueError("Unknown checkpoint type tag")
    if len(body) > CAPS["attempts"]:
        raise CheckpointPause("Checkpoint container cap before construction; PAUSED")
    if tag != "map":
        values = [_unpack(v, depth + 1) for v in body]
        return tuple(values) if tag == "tuple" else values
    output = {}
    for pair in body:
        if type(pair) is not list or len(pair) != 2:
            raise ValueError("Explicit ordered checkpoint pair required")
        key, item = [_unpack(v, depth + 1) for v in pair]
        if type(key) not in (str, tuple) or key in output:
            raise ValueError("Duplicate/invalid ordered checkpoint key")
        output[key] = item
    return output


# Pause before constructing copies of native collections that exceed fixed bounds.
def _counts(state):
    _fields(state, FIELDS)
    limits = {
        "_held": CAPS["names"],
        "_average": CAPS["names"],
        "_marks": CAPS["names"],
        "_mark_times": CAPS["names"],
        "_orders": CAPS["orders"],
        "_attempts": CAPS["attempts"],
        "_fills": CAPS["fills"],
        "_actions": CAPS["actions"],
        "_dividends": CAPS["dividends"],
        **{name: CAPS["claims_per_kind"] for name in CLAIMS},
    }
    for name, limit in limits.items():
        expected = (
            dict
            if name
            in {"_held", "_average", "_marks", "_mark_times", "_orders", "_actions"}
            else list
        )
        if type(state[name]) is not expected:
            raise ValueError("Exact native collection type required")
        if len(state[name]) > limit:
            raise CheckpointPause("Checkpoint record cap; PAUSED")
    if (
        sum(
            len(state[k])
            for k in limits
            if k not in {"_held", "_average", "_marks", "_mark_times"}
        )
        > CAPS["records"]
    ):
        raise CheckpointPause("Checkpoint aggregate cap; PAUSED")


# Validate held/basis/mark maps and clocks without inventing fresh NAV.
def _account(state):  # noqa: C901 -- Native clock/mark schema kept together.
    for key in ("_cash", "_last_equity"):
        _number(state[key])
    if type(state["cost_bps"]) is not float or state["cost_bps"] != 10.0:
        raise ValueError("Frozen10bp native broker required")
    if set(state["_held"]) != set(state["_average"]) or set(state["_marks"]) != set(
        state["_mark_times"]
    ):
        raise ValueError("Native basis/mark-time keys differ")
    now, observed = state["_now"], state["_observed_at"]
    if any(type(state[k]) is not bool for k in ("_market_open", "_batch_open")):
        raise ValueError("Exact native clock flags required")
    if now is None or observed is None:
        if (
            now is not None
            or observed is not None
            or state["_market_open"]
            or state["_batch_open"]
            or state["_marks"]
        ):
            raise ValueError("Conflicting unobserved native clock state")
    elif (
        type(now) is not datetime
        or type(observed) is not datetime
        or now.tzinfo is not UTC
        or observed.tzinfo is not UTC
        or observed > now
        or (state["_batch_open"] and observed != now)
        or (state["_market_open"] and not native._session(observed)[1])
    ):
        raise ValueError("Inconsistent native observation state")
    for name, qty in state["_held"].items():
        symbol(name)
        _number(qty)
        _number(state["_average"][name], nullable=True)
    for name, price in state["_marks"].items():
        symbol(name)
        _number(price, positive=True, nullable=True)
        at = state["_mark_times"][name]
        if (
            type(at) is not datetime
            or at.tzinfo is not UTC
            or observed is None
            or at > observed
        ):
            raise ValueError("Invalid native mark clock")


# Recompute native phase scheduling from its original precise submission clock.
def _due(submitted, phase):
    local = submitted.astimezone(native.calendar.NEW_YORK)
    years, days = native.calendar.reviewed_sessions()
    if local.year not in years:
        raise ValueError("Reviewed order calendar unavailable")
    if phase == "market":
        if not native._session(submitted)[1]:
            raise ValueError("Market submission outside native session")
        return local.date().isoformat()
    day = np.datetime64(local.date(), "D")
    opening = (
        native.calendar.REGULAR_OPEN
        if phase == "open"
        else native.calendar.session_close(local.date())
    )
    selected = (
        day
        if np.is_busday(day, busdaycal=days) and local.time() < opening
        else np.busday_offset(day, 1, roll="backward", busdaycal=days)
    )
    if selected.astype(object).year not in years:
        raise ValueError("Reviewed queued session unavailable")
    return str(selected)


# Require canonical positive or zero whole-share strings in native order receipts.
def _quantity(value, *, zero=False):
    _text(value)
    if (
        not value.isascii()
        or not value.isdecimal()
        or str(int(value)) != value
        or int(value) < (0 if zero else 1)
    ):
        raise ValueError("Canonical native quantity string required")
    return int(value)


# Bind successful attempts and order states without replaying any submission.
def _orders(state):  # noqa: C901 -- Bind original native attempt variants.
    accepted = {}
    for attempt in state["_attempts"]:
        _fields(attempt, ATTEMPT)
        _text(attempt["client_order_id"])
        symbol(attempt["symbol"])
        _integer(attempt["qty"])
        at = _time(attempt["at"])
        if (
            state["_now"] is None
            or at > state["_now"]
            or attempt["side"] not in {"buy", "sell"}
            or type(attempt["accepted"]) is not bool
        ):
            raise ValueError("Inconsistent original attempt")
        if attempt["accepted"]:
            if attempt["reason"] is not None or attempt["client_order_id"] in accepted:
                raise ValueError("Duplicate/inconsistent accepted CID")
            accepted[attempt["client_order_id"]] = attempt
        elif attempt["reason"] not in {
            "insufficient_reserved_cash",
            "uncovered_sell",
            "terminated_security",
        }:
            raise ValueError("Unknown native refusal reason")
        terminated = attempt["reason"] == "terminated_security"
        _number(attempt["observed_price"], positive=True, nullable=terminated)
        _number(attempt["available_cash"], nullable=terminated)
        if terminated:
            if (
                attempt["observed_price"] is not None
                or attempt["available_cash"] is not None
                or not any(
                    r["symbol"] == attempt["symbol"] and _time(r["applied_at"]) <= at
                    for r in state["_cash_mergers"]
                )
            ):
                raise ValueError("Terminated-security attempt lacks original merger")
        else:
            needed = (
                attempt["qty"]
                * attempt["observed_price"]
                * (1 + state["cost_bps"] / 1e4)
                if attempt["side"] == "buy"
                else 0
            )
            if (
                not math.isfinite(needed)
                or (attempt["accepted"] and needed > attempt["available_cash"])
                or (
                    attempt["reason"] == "insufficient_reserved_cash"
                    and not needed > attempt["available_cash"]
                )
                or (attempt["reason"] == "uncovered_sell" and attempt["side"] != "sell")
            ):
                raise ValueError("Native attempt funding/refusal differs")
    if set(accepted) != set(state["_orders"]):
        raise ValueError("Order and accepted-attempt CIDs differ")
    for index, (cid, row) in enumerate(state["_orders"].items()):
        _order(state, cid, row, index, accepted[cid])


# Validate one exact native order variant and its original attempt identity.
def _order(state, cid, row, index, attempt):
    status = row.get("status")
    extras = {
        "filled": {"filled_at"},
        "expired": {"expired_at"}
        | ({"filled_at"} if row.get("filled_qty") != "0" else set()),
        "canceled": {"canceled_at"},
        "accepted": set(),
    }
    if status not in extras:
        raise ValueError("Unknown native order status")
    _fields(row, ORDER | extras[status])
    qty, filled = _quantity(row["qty"]), _quantity(row["filled_qty"], zero=True)
    submitted = _time(row["submitted_at"])
    if (
        cid != row["client_order_id"]
        or row["id"] != f"private-replay-{index}"
        or row["created_at"] != row["submitted_at"]
        or row["type"] != "market"
        or row["side"] not in {"buy", "sell"}
        or row["execution_phase"] not in {"market", "open", "close"}
        or row["time_in_force"]
        != ("cls" if row["execution_phase"] == "close" else "day")
        or row["execute_on"] != _due(submitted, row["execution_phase"])
        or filled > qty
        or any(
            attempt[k] != value
            for k, value in (
                ("symbol", row["symbol"]),
                ("side", row["side"]),
                ("qty", qty),
                ("at", row["submitted_at"]),
            )
        )
    ):
        raise ValueError("Native order/phase/attempt identity differs")
    _number(row["reserved_cash"])
    _number(row["fee"])
    for field in extras[status]:
        if not submitted <= _time(row[field]) <= state["_now"]:
            raise ValueError("Terminal order clock differs")
    if status in {"accepted", "canceled"}:
        reserve = (
            qty * attempt["observed_price"] * (1 + state["cost_bps"] / 1e4)
            if status == "accepted" and row["side"] == "buy"
            else 0.0
        )
        if (
            filled
            or row["filled_avg_price"] is not None
            or row["fee"] != 0.0
            or row["reserved_cash"] != reserve
        ):
            raise ValueError("Native unfilled order/reservation differs")
    elif row["reserved_cash"] != 0 or (status == "filled") != (filled == qty):
        raise ValueError("Native terminal quantity/reservation differs")
    if status == "expired" and filled and row["filled_at"] != row["expired_at"]:
        raise ValueError("Partial terminal clocks differ")


# Reconcile fill receipts, notional fees and the complete terminal order set.
def _fills(state):
    seen = set()
    for row in state["_fills"]:
        _fields(row, FILL)
        cid = row["client_order_id"]
        if cid in seen or cid not in state["_orders"]:
            raise ValueError("Duplicate/unknown fill CID")
        seen.add(cid)
        order = state["_orders"][cid]
        _integer(row["requested_qty"])
        _integer(row["filled_qty"], zero=True)
        _number(row["price"], positive=True, nullable=row["filled_qty"] == 0)
        _number(row["fee"])
        if row["filled_qty"] == 0 and row["price"] is not None:
            raise ValueError("Native zero fill must retain absent price")
        expected_reason = (
            "missing_execution_price"
            if not row["filled_qty"] and row["price"] is None
            else "partial_cash_or_coverage"
            if row["filled_qty"] < row["requested_qty"]
            else "filled"
        )
        # Native zero-fill receipts omit even a known execution reference.
        reasons = (
            {"missing_execution_price", "partial_cash_or_coverage"}
            if row["filled_qty"] == 0
            else {expected_reason}
        )
        if (
            row["requested_qty"] != int(order["qty"])
            or row["filled_qty"] != int(order["filled_qty"])
            or any(row[k] != order[k] for k in ("symbol", "side", "status", "fee"))
            or order["filled_avg_price"]
            != (str(row["price"]) if row["filled_qty"] else None)
            or row["at"] != order.get("filled_at", order.get("expired_at"))
            or row["reason"] not in reasons
            or row["fee"]
            != row["filled_qty"] * (row["price"] or 0) * state["cost_bps"] / 1e4
        ):
            raise ValueError("Native fill/order arithmetic or identity differs")
        at = _time(row["at"])
        local = at.astimezone(native.calendar.NEW_YORK)
        phase = order["execution_phase"]
        expected = (
            native.calendar.REGULAR_OPEN
            if phase == "open"
            else native.calendar.session_close(local.date())
        )
        if (
            not native._session(at)[0]
            or str(local.date()) != order["execute_on"]
            or (
                phase == "market"
                and not native.calendar.REGULAR_OPEN
                <= local.time()
                <= native.calendar.session_close(local.date())
            )
            or (phase != "market" and local.time() != expected)
        ):
            raise ValueError("Native fill phase/session clock differs")
    terminal = {
        cid
        for cid, row in state["_orders"].items()
        if row["status"] in {"filled", "expired"}
    }
    if seen != terminal:
        raise ValueError("Terminal native order/fill receipts differ")


# Require original tuple action identities and their exact recorded source values.
def _actions(state):
    for key, value in state["_actions"].items():
        if type(key) is not tuple or len(key) != 3:
            raise ValueError("Original tuple action key required")
        name, kind, at = key
        symbol(name)
        if kind not in {
            "split",
            "dividend",
            "share_consolidation",
            "security_exchange",
            "cash_merger",
        } and not (
            type(kind) is str
            and kind.startswith("stock_distribution/")
            and len(kind.split("/")) == 2
        ):
            raise ValueError("Unknown native action kind")
        if state["_now"] is None or _time(at) > state["_now"]:
            raise ValueError("Future/unobserved native action")
        _number(value, positive=True)


# Bind a claim to its existing native action tuple and application/payment clocks.
def _claim_key(row, state, name, kind, effective):
    key = row["action_key"]
    if (
        type(key) is not tuple
        or key != (name, kind, row[effective])
        or key not in state["_actions"]
    ):
        raise ValueError("Native claim/action identity differs")
    if _time(row[effective]) > state["_now"]:
        raise ValueError("Future native claim")
    return key


# Validate fractional payments without manufacturing missing evidence.
def _payment(row, effective, now):
    paid = row["cash_in_lieu"] is not None
    optional = {"paid_at", "observed_payment_at"}
    if paid != (optional <= set(row)) or (not paid and optional & set(row)):
        raise ValueError("Fractional payment evidence differs")
    if paid:
        _number(row["cash_in_lieu"])
        if (
            not effective
            <= _time(row["paid_at"])
            <= _time(row["observed_payment_at"])
            <= now
        ):
            raise ValueError("Native fractional payment clocks differ")


# Validate dividend entitlements while retaining unknown or future payment dates.
def _dividends(state):
    seen = set()
    for row in state["_dividends"]:
        _fields(
            row, {"action_key", "symbol", "amount", "effective_at", "pay_at", "paid"}
        )
        key = _claim_key(row, state, row["symbol"], "dividend", "effective_at")
        if key in seen or type(row["paid"]) is not bool:
            raise ValueError("Duplicate/invalid native dividend")
        seen.add(key)
        _number(row["amount"])
        if row["pay_at"] is not None and _time(row["pay_at"]) < _time(
            row["effective_at"]
        ):
            raise ValueError("Dividend payment precedes entitlement")
        if row["paid"] and (
            row["pay_at"] is None or _time(row["pay_at"]) > state["_now"]
        ):
            raise ValueError("Paid dividend lacks dated evidence")


# Validate reverse-split and stock-distribution claim variants exactly.
def _fractional(row, state, distribution):  # noqa: C901 -- Two native claim schemas.
    common = {
        "action_key",
        "numerator",
        "denominator",
        "fractional_qty",
        "fractional_basis",
        "cash_in_lieu",
        "applied_at",
    }
    extra = (
        {
            "parent",
            "child",
            "parent_qty",
            "whole_qty",
            "parent_basis_fraction",
            "effective_at",
        }
        if distribution
        else {
            "symbol",
            "quantity_before",
            "whole_qty",
            "fractional_policy",
            "effective_at",
            "entitlement_scope",
        }
    )
    unknown = distribution and row.get("parent_basis_fraction") is None
    policy = {"basis_policy", "basis_before"} if unknown else set()
    _fields(row, common | extra | policy, {"paid_at", "observed_payment_at"})
    name = row["parent"] if distribution else row["symbol"]
    kind = (
        "stock_distribution/" + row["child"] if distribution else "share_consolidation"
    )
    key = _claim_key(row, state, name, kind, "effective_at")
    _integer(row["numerator"])
    _integer(row["denominator"])
    _integer(row["whole_qty"], zero=True)
    _number(row["fractional_qty"])
    _number(row["fractional_basis"], nullable=True)
    if row["fractional_qty"] == 0 and row["fractional_basis"] != 0:
        raise ValueError("Native zero fraction has zero acquisition cost")
    if (
        row["fractional_qty"] >= 1
        or state["_actions"][key] != row["numerator"] / row["denominator"]
    ):
        raise ValueError("Native fractional ratio differs")
    ratio = Fraction(row["numerator"], row["denominator"])
    before = row["parent_qty"] if distribution else row["quantity_before"]
    _number(before)
    entitlement = Fraction(str(before)) * ratio
    if (
        (ratio.numerator, ratio.denominator) != (row["numerator"], row["denominator"])
        or (not distribution and before != int(before))
        or row["whole_qty"] != int(entitlement)
        or row["fractional_qty"] != float(entitlement - int(entitlement))
    ):
        raise ValueError("Native fractional entitlement differs")
    if not _time(row["effective_at"]) <= _time(row["applied_at"]) <= state["_now"]:
        raise ValueError("Native claim application clock differs")
    if distribution:
        symbol(row["child"])
        if row["child"] == row["parent"]:
            raise ValueError("Distinct native distribution securities required")
        _number(row["parent_qty"])
        if unknown:
            _fields(row["basis_before"], {"parent_total", "child_total"})
            if row["basis_policy"] != "unallocated_at_effective_clock":
                raise ValueError("Unknown distribution basis policy")
            for value in row["basis_before"].values():
                _number(value, nullable=True)
        else:
            _number(row["parent_basis_fraction"], positive=True)
            if row["parent_basis_fraction"] >= 1:
                raise ValueError("Distribution basis fraction differs")
    else:
        _number(row["quantity_before"])
        if (
            row["numerator"] >= row["denominator"]
            or row["fractional_policy"] != "cash_in_lieu_unknown"
            or row["entitlement_scope"]
            != "private_holder_aggregate_not_broker_street_name_allocation"
        ):
            raise ValueError("Native consolidation policy differs")
    _payment(row, _time(row["effective_at"]), state["_now"])
    return key


# Validate both security-exchange cash-default and floor-forfeiture variants.
def _exchange(row, state):
    common = {
        "action_key",
        "symbol",
        "old_security_id",
        "new_security_id",
        "numerator",
        "denominator",
        "quantity_before",
        "quantity_after",
        "fractional_policy",
        "cash_credit",
        "entitlement_scope",
        "basis_policy",
    }
    cash = row.get("fractional_policy") == "cash_in_lieu_unknown"
    extra = (
        {
            "fractional_qty",
            "fractional_basis",
            "cash_in_lieu",
            "completed_before",
            "legal_clock_precision",
            "applied_at",
            "election_policy",
        }
        if cash
        else {"forfeited_fraction", "forfeited_basis", "effective_at"}
    )
    _fields(row, common | extra, {"paid_at", "observed_payment_at"} if cash else set())
    clock = "completed_before" if cash else "effective_at"
    key = _claim_key(row, state, row["symbol"], "security_exchange", clock)
    for k in ("old_security_id", "new_security_id"):
        _text(row[k])
    for k in ("numerator", "denominator"):
        _integer(row[k])
    _integer(row["quantity_after"], zero=True)
    _number(row["quantity_before"])
    fraction = row["fractional_qty"] if cash else row["forfeited_fraction"]
    _number(fraction)
    fraction_basis = row["fractional_basis"] if cash else row["forfeited_basis"]
    _number(fraction_basis, nullable=True)
    _number(row["cash_credit"])
    if fraction == 0 and fraction_basis != 0:
        raise ValueError("Native zero fraction has zero acquisition cost")
    if (
        fraction >= 1
        or row["old_security_id"] == row["new_security_id"]
        or row["cash_credit"] != 0
        or row["entitlement_scope"]
        != "private_holder_aggregate_not_broker_street_name_allocation"
        or state["_actions"][key] != row["numerator"] / row["denominator"]
    ):
        raise ValueError("Native exchange identity/ratio differs")
    ratio = Fraction(row["numerator"], row["denominator"])
    before = row["quantity_before"]
    entitlement = Fraction(str(before)) * ratio
    if (
        before != int(before)
        or (ratio.numerator, ratio.denominator)
        != (row["numerator"], row["denominator"])
        or row["quantity_after"] != int(entitlement)
        or fraction != float(entitlement - int(entitlement))
    ):
        raise ValueError("Native exchange entitlement differs")
    if cash:
        if (
            row["basis_policy"]
            != "ratio_basis_with_separate_fractional_cost_not_tax_basis"
            or row["election_policy"] != "declared_no_election_default_shares"
            or row["legal_clock_precision"] != "completed_before_open_not_exact"
        ):
            raise ValueError("Native exchange cash-default policy differs")
        if not _time(row[clock]) <= _time(row["applied_at"]) <= state["_now"]:
            raise ValueError("Native exchange application clock differs")
        native._exchange_boundary(_time(row[clock]), True)
        _payment(row, _time(row[clock]), state["_now"])
    elif (
        row["fractional_policy"] != "floor_no_compensation"
        or row["basis_policy"]
        != "ratio_basis_with_separate_forfeited_cost_not_tax_basis"
    ):
        raise ValueError("Native exchange forfeiture policy differs")
    return key


# Validate unpaid or explicitly settled terminal cash-merger claims.
def _merger(row, state):
    _fields(
        row,
        {
            "action_key",
            "symbol",
            "old_security_id",
            "election_policy",
            "quantity_before",
            "per_share",
            "amount",
            "prior_total_cost",
            "completed_before",
            "legal_clock_precision",
            "applied_at",
            "paid",
            "entitlement_scope",
        },
        {"paid_at", "observed_payment_at"},
    )
    key = _claim_key(row, state, row["symbol"], "cash_merger", "completed_before")
    native._exchange_boundary(_time(row["completed_before"]), True)
    _text(row["old_security_id"])
    _number(row["quantity_before"])
    if row["quantity_before"] != int(row["quantity_before"]):
        raise ValueError("Native merger requires whole pre-event holdings")
    _number(row["per_share"], positive=True)
    _number(row["amount"])
    _number(row["prior_total_cost"], nullable=True)
    if (
        type(row["paid"]) is not bool
        or row["amount"] != row["quantity_before"] * row["per_share"]
        or state["_actions"][key] != row["per_share"]
        or row["election_policy"] != "declared_no_election_default_cash"
        or row["legal_clock_precision"] != "completed_before_open_not_exact"
        or row["entitlement_scope"] != "declared_private_no_election_not_broker_receipt"
        or not _time(row["completed_before"])
        <= _time(row["applied_at"])
        <= state["_now"]
    ):
        raise ValueError("Native merger identity/amount differs")
    payment = {"paid_at", "observed_payment_at"}
    if row["paid"] != (payment <= set(row)) or (not row["paid"] and payment & set(row)):
        raise ValueError("Native merger payment evidence differs")
    if (
        row["paid"]
        and not _time(row["completed_before"])
        <= _time(row["paid_at"])
        <= _time(row["observed_payment_at"])
        <= state["_now"]
    ):
        raise ValueError("Native merger payment clocks differ")
    return key


# Reconcile every claim and action once while preserving unknown receivables.
def _claims(state):
    seen = set()
    for name in CLAIMS:
        for row in state[name]:
            key = (
                _fractional(row, state, name == "_security_distributions")
                if name in {"_security_distributions", "_share_consolidations"}
                else _exchange(row, state)
                if name == "_security_exchanges"
                else _merger(row, state)
            )
            if key in seen:
                raise ValueError("Duplicate native corporate claim")
            seen.add(key)
    expected = {k for k in state["_actions"] if k[1] not in {"split", "dividend"}}
    if seen != expected or {r["action_key"] for r in state["_dividends"]} != {
        k for k in state["_actions"] if k[1] == "dividend"
    }:
        raise ValueError("Native action/claim sets differ")


# Validate full native shape and receipt consistency before constructing a broker.
def _validate(state):
    _counts(state)
    _account(state)
    _orders(state)
    _fills(state)
    _actions(state)
    _dividends(state)
    _claims(state)
    reserved = sum(
        r["reserved_cash"]
        for r in state["_orders"].values()
        if r["status"] == "accepted"
    )
    if not math.isfinite(reserved) or reserved > state["_cash"]:
        raise ValueError("Native cash reservations exceed cash")
    sales = {}
    for row in state["_orders"].values():
        if row["status"] == "accepted" and row["side"] == "sell":
            sales[row["symbol"]] = sales.get(row["symbol"], 0) + int(row["qty"])
    if any(q > state["_held"].get(n, 0) for n, q in sales.items()):
        raise ValueError("Native sell reservations exceed held shares")


# Encode a complete bounded private snapshot without sorting FIFO-sensitive mappings.
def encode(broker, *, identity, identity_sha256):
    _identity(identity, identity_sha256)
    if type(broker) is not native.ReplayBroker:
        raise ValueError("Exact private ReplayBroker required")
    _validate(broker.__dict__)
    packed = _pack(broker.__dict__)
    original = deepcopy(broker.__dict__)
    envelope = {
        "schema": "private-n2-broker-checkpoint/1",
        "private_synthetic_only": True,
        "identity": deepcopy(identity),
        "identity_sha256": identity_sha256,
        "caps": dict(CAPS),
        "codec_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "state": packed,
    }
    output = bytearray()
    for text in json.JSONEncoder(allow_nan=False, separators=(",", ":")).iterencode(
        envelope
    ):
        chunk = text.encode()
        if len(output) + len(chunk) > CAPS["bytes"]:
            raise CheckpointPause("Checkpoint byte cap; PAUSED")
        output.extend(chunk)
    if broker.__dict__ != original:
        raise ValueError("Native broker changed during checkpoint encoding")
    return bytes(output)


# Restore exactly the known native class only after byte, identity and state validation.
def restore(raw, *, expected_sha256, identity, identity_sha256):
    if type(raw) is not bytes:
        raise ValueError("Immutable original checkpoint bytes required")
    if len(raw) > CAPS["bytes"]:
        raise CheckpointPause("Checkpoint byte cap before decode; PAUSED")
    if hashlib.sha256(raw).hexdigest() != digest(expected_sha256):
        raise ValueError("External checkpoint SHA differs")
    _identity(identity, identity_sha256)
    data = _decode(raw)
    _fields(
        data,
        {
            "schema",
            "private_synthetic_only",
            "identity",
            "identity_sha256",
            "caps",
            "codec_sha256",
            "state",
        },
    )
    if (
        data["schema"] != "private-n2-broker-checkpoint/1"
        or data["private_synthetic_only"] is not True
        or data["identity"] != identity
        or data["identity_sha256"] != identity_sha256
        or _digest(data["caps"]) != _digest(dict(CAPS))
        or data["codec_sha256"]
        != hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    ):
        raise ValueError("Frozen checkpoint header differs")
    state = _unpack(data["state"])
    _validate(state)
    broker = native.ReplayBroker(0, 10)
    broker.__dict__ = state
    return broker


# Bound stream allocation before JSON expansion or native construction.
def read(stream, **pins):
    raw = bytearray()
    while True:
        requested = min(65536, CAPS["bytes"] - len(raw) + 1)
        chunk = stream.read(requested)
        if type(chunk) is not bytes or len(chunk) > requested:
            raise ValueError("Bounded byte stream required")
        if not chunk:
            break
        if len(raw) + len(chunk) > CAPS["bytes"]:
            raise CheckpointPause("Checkpoint stream cap before allocation; PAUSED")
        raw.extend(chunk)
    return restore(bytes(raw), **pins)
