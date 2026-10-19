"""Read one authenticated numeric plan without running or inventing a decision."""

import json
import math
from copy import deepcopy
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from zipfile import BadZipFile

import numpy as np

from backend.agents.trading.desk.intraday_orders import INTRADAY_TIMING
from backend.market import (
    calendar,
    grade_led_policy,
    grade_parity,
    joint_funded_policy,
    learned_live_holding,
    learned_live_timing,
)
from backend.market.live_probability_timing import POLICY as TIMING_POLICY

VERSION = "live-model-decisions/1"
_TERMINAL = {
    "filled",
    "cancelled",
    "canceled",
    "rejected",
    "held",
    "missed",
    "expired",
    "dead",
    "skipped",
}
_WORKING = {"planned", "queued", "sent", "waiting", "due", "partial"}


# Hash a JSON decision without permitting nonfinite values or changing its source.
def _digest(value):
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


# Require finite numerical quantities rather than accepting booleans or numeric strings.
def _number(value, *, whole=False):
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
        or (whole and value != math.floor(value))
    ):
        raise ValueError("Finite nonnegative numeric account values required")
    return int(value) if whole else float(value)


# Validate the original order identity without accepting a different stock or session.
def _order_identity(identity, symbol, side, session):
    if (
        not isinstance(session, str)
        or date.fromisoformat(session).isoformat() != session
        or not isinstance(symbol, str)
        or not symbol
        or len(symbol) > 16
        or any(letter not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ.-" for letter in symbol)
        or side not in ("buy", "sell")
        or not isinstance(identity, str)
    ):
        raise ValueError("Original order identity required")
    prefix = f"anios-{session}-{side}-{symbol.lower()}-"
    sequence = identity.removeprefix(prefix)
    if (
        not identity.startswith(prefix)
        or not sequence.isascii()
        or not sequence.isdecimal()
        or str(int(sequence)) != sequence
    ):
        raise ValueError("Canonical original client order identity required")


# Check actual fill chronology while preserving the original timestamp strings.
def _journal_clock(entry, execution, now):
    filled_at = execution.get("filled_at")
    if filled_at is None:
        return
    clock = datetime.fromisoformat(filled_at)
    if (
        clock.utcoffset() is None
        or clock > now
        or clock.astimezone(calendar.NEW_YORK).date().isoformat() < entry["session"]
    ):
        raise ValueError("Actual fill clock must precede observation")
    for name in ("decision_at", "created_at", "submitted_at"):
        if execution.get(name) is not None:
            earlier = datetime.fromisoformat(execution[name])
            if earlier.utcoffset() is None or earlier > clock:
                raise ValueError("Original execution clock follows its fill")
    if execution.get("reconciled_at") is not None:
        reconciled = datetime.fromisoformat(execution["reconciled_at"])
        if reconciled.utcoffset() is None or not clock <= reconciled <= now:
            raise ValueError("Original reconciliation clock must follow its fill")


# Require a positive price for a positive fill before checking dated execution facts.
def _journal_fill(entry, execution, now):
    if entry["filled_qty"] > 0 and execution.get("filled_at") is not None:
        if _number(entry.get("filled_price")) <= 0:
            raise ValueError("Positive actual fill price required")
        _journal_clock(entry, execution, now)


# Reject impossible quantities and statuses before exposing a terminal receipt.
def _journal_quantities(entry):
    qty = _number(entry.get("qty"), whole=True)
    filled = _number(entry.get("filled_qty"))
    if (
        qty <= 0
        or filled > qty
        or entry.get("status") not in _TERMINAL | {"partial"}
        or (entry["status"] == "filled" and filled != qty)
    ):
        raise ValueError("Journal fill differs from its original whole-share order")


# Reject ambiguous journal identities before considering any individual fill evidence.
def _journal_rows(journal, now):
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware journal observation clock required")
    if not isinstance(journal, list):
        raise ValueError("Original journal list required")
    identities = set()
    for entry in journal:
        if not isinstance(entry, dict):
            raise ValueError("Original journal object required")
        identity = entry.get("client_order_id")
        if not isinstance(identity, str) or not identity:
            continue
        if identity in identities:
            raise ValueError("Duplicate journal client order identity")
        identities.add(identity)
    return journal


# Validate one terminal record without repairing historical identities or clocks.
def _terminal_entry(entry, now):
    if entry.get("terminal") is not True:
        return None
    execution = entry.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError("Original journal execution clocks required")
    _order_identity(
        entry.get("client_order_id"),
        entry.get("symbol"),
        entry.get("side"),
        entry.get("session"),
    )
    _journal_quantities(entry)
    _journal_fill(entry, execution, now)
    return entry


# Validate a working partial's actual fill separately from terminal decision conclusions.
def _recorded_fill_entry(entry, now):
    if entry.get("terminal") is True:
        return _terminal_entry(entry, now)
    if entry.get("terminal") is not False or entry.get("status") != "partial":
        return None
    execution = entry.get("execution") or {}
    if not isinstance(execution, dict):
        raise ValueError("Original journal execution clocks required")
    _order_identity(
        entry.get("client_order_id"), entry.get("symbol"),
        entry.get("side"), entry.get("session"),
    )
    _journal_quantities(entry)
    _journal_fill(entry, execution, now)
    return entry


# Expose dated actual fills, including working partials, without concluding their orders.
def recorded_fills(journal, now):
    result = []
    for supplied in _journal_rows(journal, now):
        try:
            entry = _recorded_fill_entry(supplied, now)
        except (ValueError, TypeError, KeyError, OverflowError):
            # Invalid historical rows cannot hide later verified fills.
            continue
        if entry is None:
            continue
        filled_at = (entry.get("execution") or {}).get("filled_at")
        if entry["filled_qty"] > 0 and filled_at is not None:
            execution = deepcopy(entry.get("execution") or {})
            result.append(
                {
                    "client_order_id": entry["client_order_id"],
                    "symbol": entry["symbol"],
                    "side": entry["side"],
                    "qty": entry["filled_qty"],
                    "price": entry["filled_price"],
                    "filled_at": filled_at,
                    "session": entry["session"],
                    "created_at": execution.get("created_at"),
                    "reconciled_at": execution.get("reconciled_at"),
                    "original_qty": entry["qty"],
                    "source": "recorded_paper_journal",
                    "execution": execution,
                }
            )
    return result[-1000:]


# Preserve the tracked universe while withholding every unverified instruction.
def _unavailable(record, now, reason, *, stale=False):
    record = record if isinstance(record, dict) else {}
    grades = record.get("grades")
    names = (
        sorted(name for name in grades if isinstance(name, str))
        if isinstance(grades, dict)
        else []
    )
    session = record.get("session") if isinstance(record.get("session"), str) else None
    return {
        "version": VERSION,
        "status": "stale" if stale else "unavailable",
        "reason": reason,
        "policy": grade_led_policy.POLICY,
        "session": session,
        "observed_at": record.get("written"),
        "valid_until": None,
        "as_of": now.isoformat(),
        "rows": {
            name: {
                "grade": None,
                "action": None,
                "qty": None,
                "when": None,
                "status": "unavailable",
                "reason": reason,
                "decided": record.get("session"),
                "signal_session": record.get("session"),
                "execute_on": None,
            }
            for name in names
        },
    }


# Limit a dated nightly plan to the end of its following reviewed exchange session.
def _valid_until(session):
    if (
        not isinstance(session, str)
        or date.fromisoformat(session).isoformat() != session
    ):
        raise ValueError("Exact original decision date required")
    day = np.datetime64(session, "D")
    years, sessions = calendar.reviewed_sessions()
    if day.astype(object).year not in years or not np.is_busday(
        day, busdaycal=sessions
    ):
        raise ValueError("Reviewed model decision session required")
    following = np.busday_offset(day, 1, busdaycal=sessions).astype(object)
    if following.year not in years:
        raise ValueError("Reviewed following execution session required")
    return datetime.combine(
        following, calendar.session_close(following), calendar.NEW_YORK
    )


# Read a regular artifact bound to its installed receipt without restoring a predictor.
def _artifact(path, digest):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Original regular model artifact required")
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != digest:
        raise ValueError("Original numeric artifact hash differs")
    return raw


# Verify saved close and publication bytes without prediction or loading a head.
def _saved_close(folder, model_folder, admission, config, written):
    close = json.loads(
        _artifact(folder / "close.json", admission["close_receipt_sha256"])
    )
    identity = close["identity"]
    original_digest = sha256(
        json.dumps(identity, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    published = datetime.fromisoformat(identity["published_at"])
    observed = datetime.fromisoformat(identity["observed_at"])
    model_published = datetime.fromisoformat(identity["model_published_at"])
    if (
        any(
            clock.utcoffset() is None
            for clock in (published, observed, model_published)
        )
        or not model_published <= observed <= published <= written
        or close["identity_sha256"] != original_digest
        or identity["policy"] != "forward-holding-close/1-shadow"
        or close["adoption_eligible"] is not False
        or identity["model_publication_sha256"] != config["model_receipt_sha256"]
        or identity["provenance"] != admission["provenance"]
    ):
        raise ValueError("Original close publication and provenance required")
    publication = json.loads(
        _artifact(model_folder / "publication.json", config["model_receipt_sha256"])
    )
    if publication["identity"]["published_at"] != identity["model_published_at"]:
        raise ValueError("Original model publication clock differs")
    model_file = publication["model_file"]
    if model_file is not None:
        if model_file["name"] != "model.npz":
            raise ValueError("Canonical numeric model artifact required")
        _artifact(model_folder / "model.npz", model_file["sha256"])
    _artifact(folder / "close.npz", close["arrays_sha256"])
    with np.load(folder / "close.npz", allow_pickle=False) as archive:
        fields = {
            "dates",
            "symbols",
            "features",
            "prices",
            "forecasts",
            "support",
            "history_prices",
            "history_grades",
        }
        if set(archive.files) != fields or set(identity["array_sha256"]) != fields:
            raise ValueError("Exact original close array schema required")
        dates, symbols, grades = (
            archive["dates"],
            tuple(archive["symbols"].tolist()),
            archive["history_grades"],
        )
        if (
            dates.ndim != 1
            or not len(dates)
            or dates.dtype != np.dtype("datetime64[D]")
            or np.isnat(dates).any()
            or np.any(dates[1:] <= dates[:-1])
            or len(set(symbols)) != len(symbols)
            or list(symbols) != identity["symbols"]
            or grades.shape != (len(dates), len(symbols))
            or not np.isin(grades, (-1, 0, 1, 2, 3)).all()
        ):
            raise ValueError("Original close grade grid required")
        for name in fields:
            value = np.ascontiguousarray(archive[name])
            hashed = sha256(
                str(value.dtype).encode()
                + json.dumps(value.shape).encode()
                + value.tobytes()
            ).hexdigest()
            if identity["array_sha256"][name] != hashed:
                raise ValueError("Original close array identity differs")
    return SimpleNamespace(dates=dates, symbols=symbols, history_grades=grades)


# Authenticate saved bytes, installed approval and the original close before projection.
def _authenticate(root, record, now):
    root = Path(root)
    session = record["session"]
    path = root / "desk" / ("asof=" + session) / "desk.json"
    raw = path.read_bytes()
    if json.loads(raw) != record:
        raise ValueError("Original saved model record required")
    captured = json.loads(
        (root / "learned_inputs" / ("asof=" + session + ".json")).read_bytes()
    )
    written = datetime.fromisoformat(record["written"])
    captured_at = datetime.fromisoformat(captured["captured_at"])
    if (
        written.tzinfo is None
        or captured_at.tzinfo is None
        or not written <= captured_at <= now
        or captured.get("record_sha256") != sha256(raw).hexdigest()
        or captured.get("session") != session
        or captured.get("record_written_at") != written.isoformat()
    ):
        raise ValueError("Original immutable model input capture required")
    config_raw, config = learned_live_holding.read_configuration(root, now)
    paper = record["paper"]
    admission = paper["learned_holding"]
    if (
        config["policy"] != grade_led_policy.POLICY
        or admission["config_sha256"] != sha256(config_raw).hexdigest()
        or sha256((root / learned_live_timing.CONFIG).read_bytes()).hexdigest()
        != config["timing_config_sha256"]
    ):
        raise ValueError("Exact installed model and timing admission required")
    identifier = Path(admission["close_directory"]).name
    if len(identifier) != 32 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("Original private close identifier required")
    base = (root / "desk/learned-holding/observations").resolve()
    folder = (base / identifier).resolve()
    if folder.parent != base:
        raise ValueError("Original close must remain within its observation directory")
    # The saved close was admitted by the nightly; reads never repeat its prediction.
    observed = _saved_close(
        folder,
        learned_live_holding._folder(root, config["model_directory"]),
        admission,
        config,
        written,
    )
    if str(observed.dates[-1]) != session:
        raise ValueError("Original numeric close session required")
    indices = [i for i, name in enumerate(observed.symbols) if name != "QQQ"]
    report = SimpleNamespace(
        panel=SimpleNamespace(
            tickers=tuple(observed.symbols[i] for i in indices),
            benchmark="SPY",
            dates=observed.dates,
        ),
        graded=SimpleNamespace(grades=observed.history_grades[:, indices]),
    )
    return sha256(raw).hexdigest(), config, report


# Keep immutable whole-share holdings independent of subsequent broker price marks.
def _holdings(positions):
    result = {}
    for row in positions:
        name = row["symbol"]
        if not isinstance(name, str) or not name or name in result:
            raise ValueError("Unique original account positions required")
        result[name] = _number(row["qty"], whole=True)
    return {name: qty for name, qty in result.items() if qty}


# Reject repeated IDs or repeated stock legs rather than adding their quantities.
def _basket(paper, names, receipt):
    basket, identities = {}, set()
    timing = receipt["execution_timing"]["orders"]
    for source, supplied in [("orders", row) for row in paper["orders"]] + [
        ("planned", row) for row in paper["planned"]
    ]:
        order = deepcopy(supplied)
        name, side = order["symbol"], order["side"]
        identity = order.get("client_order_id")
        if identity is None and source == "planned":
            prefix = f"anios-{paper['session']}-{side}-{name}-".lower()
            candidates = [
                value
                for value in timing
                if isinstance(value, str)
                and value.startswith(prefix)
                and value[len(prefix) :].isdecimal()
                and str(int(value[len(prefix) :])) == value[len(prefix) :]
                and timing[value] == INTRADAY_TIMING
            ]
            if (
                len(candidates) != 1
                or order.get("execute_on")
                != _valid_until(paper["session"]).date().isoformat()
            ):
                raise ValueError(
                    "Unambiguous original planned identity and session required"
                )
            identity = candidates[0]
            order["client_order_id"] = identity
        qty = _number(order["qty"], whole=True)
        _order_identity(identity, name, side, paper["session"])
        if (
            name not in names
            or name in basket
            or not isinstance(identity, str)
            or not identity
            or identity in identities
            or side not in ("buy", "sell")
            or qty <= 0
            or timing.get(identity) not in ("next_open", INTRADAY_TIMING)
        ):
            raise ValueError("Unique original whole-share order basket required")
        if name in receipt["company_exits"] and (
            side != "sell" or timing[identity] != "next_open"
        ):
            raise ValueError("Original company exit routing required")
        basket[name] = order
        identities.add(identity)
    if identities != set(timing):
        raise ValueError("Complete original timing and order identity required")
    return basket


# Bind each saved grade, proposal, direction and quantity to the same original basket.
def _actions(record, config, receipt, held, basket, names):
    actions = {row["ticker"]: row for row in record["actions"]}
    if len(actions) != len(record["actions"]) or set(actions) != names:
        raise ValueError("One original model action for every tracked stock required")
    for name, row in actions.items():
        qty = _number(row["order_quantity"], whole=True)
        signal = receipt["grade_signals"][name]
        grade = record["grades"][name]["grade"]
        if (
            grade not in ("A+", "A", "B", "C", None)
            or grade != signal["grade"]
            or row.get("grade") != grade
            or row.get("policy") != config["policy"]
            or row.get("decision_source") != config["policy"]
            or row.get("grade_signal") != signal["action"]
            or row.get("signal_session") != record["session"]
            or row.get("model_target_weight") != receipt["sizing_model_targets"][name]
        ):
            raise ValueError(
                "Original grade, model action and proposal must share one receipt"
            )
        order = basket.get(name)
        if not qty:
            if order is not None or row.get("action") != "hold":
                raise ValueError("Zero quantity cannot claim an original funded order")
            continue
        if order is None or order["qty"] != qty:
            raise ValueError(
                "Model action quantity differs from original funded basket"
            )
        side = order["side"]
        expected = (
            ("add" if held.get(name, 0) else "buy")
            if side == "buy"
            else "sell"
            if qty == held.get(name, 0)
            else "trim"
        )
        if row.get("action") != expected or (
            side == "sell" and qty > held.get(name, 0)
        ):
            raise ValueError(
                "Saved direction differs from original whole-share holdings"
            )
    return actions


# Check the saved numeric policy and funded order basket without calculating new sizes.
def _validate(record, config, report):
    paper = record["paper"]
    allocation = paper["joint_funded"]
    receipt = allocation["receipt"]
    names = set(record["grades"])
    if (
        config["policy"] != grade_led_policy.POLICY
        or any(
            value.get("policy") != config["policy"]
            for value in (
                record["targets"],
                paper,
                paper["selected_targets"],
                allocation,
                receipt,
            )
        )
        or receipt.get("session") != record["session"]
        or allocation.get("as_of") != record["session"]
        or paper.get("session") != record["session"]
        or paper["selected_targets"] != record["targets"]
        or receipt.get("status") != "available"
    ):
        raise ValueError("Matching available grade-led numeric receipt required")
    if (
        receipt.get("source_sha256")
        != sha256(Path(joint_funded_policy.__file__).read_bytes()).hexdigest()
        or receipt.get("cost_bps") != config["cost_bps"]
        or receipt.get("timing_policy") != TIMING_POLICY
        or receipt.get("timing_source_sha256")
        != sha256(
            Path(__file__).with_name("live_probability_timing.py").read_bytes()
        ).hexdigest()
        or receipt["execution_timing"]["ordinary"] != TIMING_POLICY
        or receipt["execution_timing"]["company_exit"] != "next_open"
    ):
        raise ValueError("Original numeric policy source and cost required")
    grade_parity._grade_led_targets(record, report)
    held = _holdings(paper["positions"])
    current = receipt["current_weights"]
    if set(receipt["grade_signals"]) != names or receipt[
        "grade_signals"
    ] != grade_led_policy.signals(report, held):
        raise ValueError("Original numeric policy grade signals required")
    basket = _basket(paper, names, receipt)
    actions = _actions(record, config, receipt, held, basket, names)
    _number(receipt["observed_equity"])
    _number(receipt["observed_cash"])
    if (
        receipt["observed_equity"] <= 0
        or receipt["observed_cash"] > receipt["observed_equity"]
        or any(_number(value) > 1 for value in current.values())
        or any(value > 0 and name not in held for name, value in current.items())
    ):
        raise ValueError("Original account basis required")
    return receipt, held, actions


# Keep exact ticker-keyed blocker strings rather than matching another stock's name.
def _reason(receipt, name, row):
    execution = receipt.get("execution") or {}
    reasons = [
        value
        for value in [*execution.get("blocked", []), *execution.get("missing", [])]
        if isinstance(value, str) and value.partition(":")[0] == name
    ]
    excluded = (
        (receipt.get("entry_qualification") or {}).get("excluded_entries") or {}
    ).get(name) or {}
    return (
        "; ".join(reasons)
        or excluded.get("reason")
        or row.get("signal_reason")
        or receipt.get("reason")
        or "Awaiting model plan"
    )


# Bound actual execution quantities by the original funded leg and known submission.
def _execution_quantities(execution, original_qty):
    values = {
        name: None if execution.get(name) is None else _number(execution[name])
        for name in ("submitted_qty", "filled_qty", "remaining_qty")
    }
    submitted, filled, remaining = (
        values["submitted_qty"],
        values["filled_qty"],
        values["remaining_qty"],
    )
    basis = original_qty if submitted is None else submitted
    if (
        basis > original_qty
        or (filled is not None and filled > basis)
        or (remaining is not None and remaining > basis - (filled or 0))
    ):
        raise ValueError(
            "Execution quantities exceed original funded or submitted order"
        )
    if execution.get("qty") is not None:
        shown = _number(execution["qty"])
        expected = {
            "planned": original_qty,
            "submitted": submitted,
            "filled": filled,
        }.get(execution.get("quantity_basis"))
        if expected is None or shown != expected or shown > original_qty:
            raise ValueError(
                "Displayed execution quantity differs from its actual basis"
            )


# Match execution status to the immutable original leg without importing current sizes.
def _executions(plan, record, config, receipt):
    if plan.get("policy") != config["policy"] or plan.get("reason"):
        raise ValueError("Matching paper plan policy required")
    names = set(record["grades"])
    basket = _basket(record["paper"], names, receipt)
    by_id = {row["client_order_id"]: row for row in basket.values()}
    result, seen = {}, set()
    for execution in plan["orders"]:
        identity = execution["client_order_id"]
        if identity in seen:
            raise ValueError("Duplicate execution receipt identity")
        seen.add(identity)
        if execution.get("decided") != record["session"]:
            if identity in by_id:
                raise ValueError("Original execution decision session differs")
            continue
        original = by_id[identity]
        timing = receipt["execution_timing"]["orders"][identity]
        if (
            execution["symbol"] != original["symbol"]
            or execution["side"] != original["side"]
            or _number(execution["planned_qty"], whole=True) != original["qty"]
            or execution.get("timing") != timing
            or execution.get("execute_on")
            != _valid_until(record["session"]).date().isoformat()
            or (
                timing == INTRADAY_TIMING
                and execution.get("timing_policy") != receipt["timing_policy"]
            )
        ):
            raise ValueError("Execution differs from the authenticated funded decision")
        terminal = execution.get("terminal")
        if terminal is not None and type(terminal) is not bool:
            raise ValueError("Explicit execution terminal status required")
        _execution_quantities(execution, original["qty"])
        result[original["symbol"]] = deepcopy(execution)
    return result


# Display an original numeric action while suppressing every concluded or unknown order.
def _row(name, saved, receipt, held, execution, session, concluded=False):
    qty = int(saved["order_quantity"])
    target, current = (
        receipt["targets"][name],
        receipt["current_weights"].get(name, 0.0),
    )
    action, state, reason = None, "no_position", _reason(receipt, name, saved)
    when, execute_on = None, None
    if qty:
        if concluded:
            state, reason = (
                "complete",
                "Recorded order concluded; awaiting the next model plan",
            )
        elif execution is None:
            state, reason = (
                "unavailable",
                "Order status unavailable for the recorded model quantity",
            )
        elif execution.get("terminal") is True or execution.get("state") in _TERMINAL:
            state, reason = (
                "complete",
                "Recorded order concluded; awaiting the next model plan",
            )
        elif (
            execution.get("state") not in _WORKING
            or not isinstance(execution.get("when"), str)
            or not execution["when"]
        ):
            state, reason = "unavailable", "Recorded execution state is unavailable"
        else:
            action = "buy" if saved["action"] in ("buy", "add") else saved["action"]
            state, when, execute_on = (
                "planned",
                execution["when"],
                execution["execute_on"],
            )
            reason = execution.get("status") or reason
    elif target > current + 1e-10 or receipt["grade_signals"][name]["action"] == "buy":
        action, state = "buy", "blocked"
    elif held.get(name, 0) and target < current - 1e-10:
        action, state = "trim", "blocked"
    elif held.get(name, 0) and receipt["grade_signals"][name]["action"] == "hold":
        action, state = "hold", "no_new_order"
    elif (
        held.get(name, 0) and receipt["grade_signals"][name]["action"] == "unavailable"
    ):
        state, reason = "unavailable", receipt["grade_signals"][name]["reason"]
    return {
        "grade": receipt["grade_signals"][name]["grade"],
        "action": action,
        "qty": qty if action is not None else None,
        "when": when,
        "status": state,
        "reason": reason,
        "decided": session,
        "signal_session": session,
        "execute_on": execute_on,
        "raw_model_target_weight": receipt["sizing_model_targets"][name],
        "target_weight": target,
        "current_qty": held.get(name, 0),
        "executions": [execution] if execution is not None else [],
        "quantity_basis": "original_funded_plan_not_new_instruction",
    }


# Project an admitted saved decision and its distinct execution state together.
def _project(record, plan, config, report, now, record_sha256, journal):
    receipt, held, actions = _validate(record, config, report)
    executions = _executions(plan, record, config, receipt)
    basket = _basket(record["paper"], set(record["grades"]), receipt)
    originals = {row["client_order_id"]: row for row in basket.values()}
    concluded = set()
    for supplied in _journal_rows(journal, now):
        original = originals.get(supplied.get("client_order_id"))
        if original is None:
            continue
        entry = _terminal_entry(supplied, now)
        if entry is None:
            continue
        if entry["session"] != record["session"] or any(
            entry[name] != original[name] for name in ("symbol", "side", "qty")
        ):
            raise ValueError("Journal conclusion differs from original funded order")
        concluded.add(original["symbol"])
    rows = {
        name: _row(
            name,
            saved,
            receipt,
            held,
            executions.get(name),
            record["session"],
            name in concluded,
        )
        for name, saved in actions.items()
    }
    return {
        "version": VERSION,
        "status": "available",
        "reason": "Recorded numeric model plan",
        "policy": config["policy"],
        "session": record["session"],
        "observed_at": record["written"],
        "valid_until": _valid_until(record["session"]).isoformat(),
        "as_of": now.isoformat(),
        "record_sha256": record_sha256,
        "receipt_sha256": _digest(receipt),
        "account_basis": "original_recorded_quantities_cash_equity_and_sizing_weights",
        "rows": rows,
    }


# Withhold absent, stale or incompatible decisions without inference or planning.
def read(root, record, plan, now, *, journal=None):
    record = record or {}
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware model projection clock required")
    try:
        if not record:
            return _unavailable(record, now, "Awaiting model plan")
        if now >= _valid_until(record["session"]):
            return _unavailable(
                record,
                now,
                "Saved model plan has expired; awaiting the next model plan",
                stale=True,
            )
        if datetime.fromisoformat(record["written"]) > now:
            raise ValueError("Model record cannot be from the future")
        digest, config, report = _authenticate(root, record, now)
        return _project(
            record,
            plan,
            config,
            report,
            now,
            digest,
            [] if journal is None else journal,
        )
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        OverflowError,
        IndexError,
        EOFError,
        BadZipFile,
    ):
        return _unavailable(record, now, "Model plan could not be verified")
