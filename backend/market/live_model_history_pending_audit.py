"""Conserve original legacy pending metadata; never certify its timing judgement."""

import gzip
import io
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import paper
from backend.cli.verify_actual_policy_timing import same
from backend.market import calendar, entry_timing
from backend.market import live_model_history_nightly_model as numerical
from backend.market.live_model_history_receipts import instant, require, whole
from backend.market.live_probability_timing import POLICY

ORIGINAL_SOURCES = {
    "backend/market/live_probability_timing.py": (
        "3fc9da7ae628e3fdd98388bbaa0e08bbaf5b8c36da78fb7c0e0efdcab63c1721"
    ),
    "backend/cli/market_strategy_continue.py": (
        "14357ed7b87618ee514dd3cd4e4a71e2c27290875c3df257e692773e524cfaaf"
    ),
    "backend/agents/trading/desk/intraday_orders.py": (
        "ca8c236746441e204f36a263e972104d48d442538ea189fd4cad9d4ccf9f0f1c"
    ),
    "backend/market/live_policy_replay.py": (
        "b6ef95f0c5eaa53bd732f0ee5baa55f21ef875d07c69e5abbbb236aafd0586e9"
    ),
    "backend/market/entry_timing.py": (
        "f23d286c0d613d99620ce4a4ea8aa889be88ca224c5fbfc945b4360eae944a88"
    ),
}
MAX_COMPRESSED_BYTES = 64 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024 * 1024


# Preserve unique JSON fields instead of silently replacing conflicting evidence.
def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "Duplicate original pending evidence field")
        result[key] = value
    return result


# Reject nonfinite JSON constants instead of admitting fabricated numeric evidence.
def reject_constant(value):
    raise ValueError("Nonfinite original pending JSON constant: " + value)


# Reject overflowed JSON exponents before any timing receipt comparison.
def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "Nonfinite original pending JSON number")
    return parsed


# Authenticate original bytes and source without certifying economic correctness.
@dataclass(frozen=True, slots=True)
class OriginalProxyEvidence:
    _archive: bytes
    sha256: str

    # Keep immutable input bytes separately from all saved state comparison targets.
    def __init__(self, archive, expected_sha256, producer_sources):
        require(type(archive) is bytes, "Immutable original gzip evidence required")
        require(
            len(archive) <= MAX_COMPRESSED_BYTES,
            "UNRECONSTRUCTIBLE_ARCHIVE_SIZE: original gzip exceeds bound",
        )
        require(
            sha256(archive).hexdigest() == expected_sha256,
            "Original session archive bytes differ",
        )
        require(
            producer_sources == ORIGINAL_SOURCES,
            "Exact original proxy sources required",
        )
        root = Path(__file__).resolve().parents[2]
        require(
            all(
                sha256((root / name).read_bytes()).hexdigest() == digest
                for name, digest in ORIGINAL_SOURCES.items()
            ),
            "Actual original proxy source bytes differ",
        )
        object.__setattr__(self, "_archive", archive)
        object.__setattr__(self, "sha256", expected_sha256)

    # Select original decision/attempt receipts without reading saved current controls.
    def records(self, session):
        require(
            sha256(self._archive).hexdigest() == self.sha256,
            "Original pending archive changed",
        )
        with gzip.GzipFile(fileobj=io.BytesIO(self._archive)) as stream:
            expanded = stream.read(MAX_JSON_BYTES + 1)
        require(
            len(expanded) <= MAX_JSON_BYTES,
            "UNRECONSTRUCTIBLE_ARCHIVE_SIZE: original JSON expansion exceeds bound",
        )
        value = json.loads(
            expanded,
            object_pairs_hook=unique,
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
        require(
            value["session"] == session, "Original pending evidence session differs"
        )
        result = {
            key: value[key]
            for key in ("forecast_decisions", "observations", "attempts")
        }
        require(
            all(type(rows) is list for rows in result.values()),
            "Original pending receipt lists required",
        )
        return result


# Build only the source-authenticated raw completed quote at its real archived clock.
def raw_quote(raw, day, slot, now, stock):
    opened, close = (
        raw.session_open[day, stock],
        raw.observation_close[day, slot, stock],
    )
    if not (np.isfinite(opened) and opened > 0 and np.isfinite(close) and close > 0):
        return None
    return {
        "ticker": str(raw.tickers[stock]),
        "open": float(opened),
        "last": float(close),
        "bar": (now - entry_timing.BAR).isoformat(),
        "as_of": now.isoformat(),
        "source": "original_raw_SIP_completed_bar_proxy",
    }


# Bind an original legacy verdict to its previously recomputed funded intent and quote.
def proxy_timed(row, trace, quote, now, day, slot):
    price = trace["observed_price"]
    require(
        price is None
        or (type(price) in (int, float) and math.isfinite(price) and price > 0),
        "Explicit positive finite original legacy price required",
    )
    require(
        trace["policy"] == POLICY
        and trace["intent_id"] == row["client_order_id"]
        and trace["symbol"] == row["symbol"]
        and trace["side"] == row["side"]
        and whole(trace["desired_qty"]) == row["qty"]
        and type(trace["day"]) is int
        and trace["day"] == day
        and type(trace["clock"]) is int
        and trace["clock"] == slot
        and instant(trace["at"]) == now
        and trace["state"] in ("execute", "wait", "unavailable", "no_trade")
        and not (
            {"forward_receipt", "forward_receipt_sha256", "inference"} & set(trace)
        ),
        "Original legacy timing identity differs; no forward substitution permitted",
    )
    require(
        trace["observed_price"] == (quote["last"] if quote else None),
        "Original legacy observed price differs from authenticated raw prefix",
    )
    require(
        whole(trace["observed_qty"], zero=True) <= row["qty"],
        "Original legacy observed quantity differs",
    )
    require(
        trace["state"] != "execute" or quote is not None,
        "Original execute quote unavailable",
    )
    return {
        **trace,
        "open": quote["open"] if quote else None,
        "trigger_bar": (now - entry_timing.BAR).isoformat(),
        "trigger_price": trace["observed_price"],
    }


# Reconstruct literal sender metadata without calling a sender or probability provider.
def apply_attempt(row, attempt, accepted, timed, now):
    cid = row["client_order_id"]
    require(
        attempt["client_order_id"] == cid
        and attempt["symbol"] == row["symbol"]
        and attempt["side"] == row["side"]
        and whole(attempt["qty"]) <= row["qty"]
        and instant(attempt["at"]) == now
        and type(attempt["accepted"]) is bool,
        "Conserved intraday attempt identity differs",
    )
    require(
        not ({"forward_receipt", "forward_receipt_sha256"} & set(timed)),
        "UNRECONSTRUCTIBLE_FORWARD_REFERENCE: legacy sender metadata only",
    )
    row["sending"] = now.isoformat(timespec="seconds")
    if not attempt["accepted"]:
        require(
            cid not in accepted or instant(accepted[cid]["at"]) > now,
            "Refused legacy attempt conflicts with accepted request",
        )
        require(
            attempt["reason"]
            in ("insufficient_reserved_cash", "uncovered_sell", "terminated_security"),
            "UNRECONSTRUCTIBLE_REFUSAL: exact original venue error required",
        )
        row["send_error"] = attempt["reason"]
        return
    require(accepted.get(cid) == attempt, "Original accepted intraday receipt differs")
    require(attempt["reason"] is None, "Accepted original request has refusal reason")
    row["sent"] = {
        "at": now.isoformat(timespec="seconds"),
        "how": "market",
        "state": timed["state"],
        "open": timed.get("open"),
        "level": timed.get("level"),
        "trigger_bar": timed.get("trigger_bar"),
        "trigger_price": timed.get("trigger_price"),
        "qty": attempt["qty"],
    }
    row.pop("send_error", None)
    row["execution"] = {
        **row["execution"],
        "created_at": attempt["at"],
        "submitted_at": attempt["at"],
        "time_in_force": "day",
    }


# Index only old regular-session receipts, leaving new nightly requests separate.
def receipt_indexes(records, pending, clock, conserved_attempts):
    attempts = {}
    original_intraday = []
    for attempt in records["attempts"]:
        at = instant(attempt["at"]).astimezone(calendar.NEW_YORK)
        if at >= clock["close"]:
            require(
                at == clock["close"] + timedelta(minutes=1),
                "Original nightly attempt clock differs",
            )
            continue
        require(
            clock["open"] < at <= clock["final"],
            "Original intraday attempt outside session",
        )
        cid = attempt["client_order_id"]
        require(
            cid in pending,
            "Intraday attempt lacks previously recomputed pending intent",
        )
        key = cid, at
        require(key not in attempts, "Duplicate original intraday attempt")
        attempts[key] = attempt
        original_intraday.append(attempt)
    expected = numerical.serialized(conserved_attempts)
    numerical.exact_integers(
        original_intraday, expected, "Original attempted quantities"
    )
    same(original_intraday, expected, "Independently conserved original attempt list")
    traces = {}
    for trace in records["forecast_decisions"]:
        key = trace["intent_id"], instant(trace["at"]).astimezone(calendar.NEW_YORK)
        require(key not in traces, "Duplicate original proxy timing identity")
        traces[key] = trace
    observations = {}
    for observation in records["observations"]:
        at = instant(observation["at"]).astimezone(calendar.NEW_YORK)
        require(at not in observations, "Duplicate original due observation")
        observations[at] = observation
    return attempts, traces, observations


# Fold every available original completed quote into its own private latch prefix.
def advance_quotes(raw, day, slot, now, latches):
    quotes = {}
    for stock, symbol in enumerate(raw.tickers):
        quote = raw_quote(raw, day, slot, now, stock)
        if quote:
            quotes[str(symbol)] = quote
            latches[str(symbol)] = entry_timing._merge(
                latches.get(str(symbol)),
                quote["open"],
                quote["last"],
                now - entry_timing.BAR,
                quote["as_of"],
            )
    return quotes


# Fold original metadata; terminal facts never reconcile controls here.
def fold_pending(
    previous, evidence, accepted, outcomes, raw, day, session, *, conserved_attempts
):
    require(
        type(evidence) is OriginalProxyEvidence,
        "Authenticated original legacy evidence required",
    )
    require(
        type(day) is int and 0 <= day < len(raw.dates),
        "Exact integer original raw day required",
    )
    require(str(raw.dates[day]) == session, "Exact authenticated raw session required")
    state = paper.PaperState(**deepcopy(vars(previous)))
    records = evidence.records(session)
    today = raw.dates[day].astype(object)
    clock = entry_timing.session_clock(today)
    count = int((clock["close"] - clock["open"]) / entry_timing.BAR) - 1
    require(
        isinstance(raw.session_open, np.ndarray)
        and raw.session_open.dtype.kind in "fiu"
        and raw.session_open.shape == (len(raw.dates), len(raw.tickers))
        and isinstance(raw.observation_close, np.ndarray)
        and raw.observation_close.dtype.kind in "fiu"
        and raw.observation_close.ndim == 3
        and raw.observation_close.shape[0] == len(raw.dates)
        and raw.observation_close.shape[1] >= count
        and raw.observation_close.shape[2] == len(raw.tickers),
        "UNRECONSTRUCTIBLE_RAW_PREFIX: "
        "complete authenticated original quote arrays required",
    )
    pending = {row["client_order_id"]: row for row in state.pending}
    require(
        len(pending) == len(state.pending),
        "Duplicate previously recomputed pending identity",
    )
    attempts, traces, observations = receipt_indexes(
        records, pending, clock, conserved_attempts
    )
    consumed_attempts, consumed_traces, consumed_observations = set(), set(), set()
    latches, transitions = {}, []
    for slot in range(count):
        now = clock["open"] + (slot + 1) * entry_timing.BAR
        quotes = advance_quotes(raw, day, slot, now, latches)
        due = [
            row
            for row in state.pending
            if row.get("execution_timing") == "dip_or_close"
            and not row.get("event_id")
            and row.get("execute_on") == session
            and not row.get("sent")
        ]
        if not due:
            continue
        require(now in observations, "Original due observation missing")
        expected_due = numerical.serialized(due)
        numerical.exact_integers(observations[now]["due"], expected_due, "Original due")
        same(
            observations[now]["due"],
            expected_due,
            "Independently derived original due rows",
        )
        consumed_observations.add(now)
        for row in due:
            require(
                row.get("timing_policy") == POLICY and "execution_policy" not in row,
                "UNRECONSTRUCTIBLE_TIMING_POLICY: original legacy contract only",
            )
            cid, quote = row["client_order_id"], quotes.get(row["symbol"])
            key = cid, now
            if now < clock["final"]:
                require(key in traces, "Original proxy timing receipt missing")
                timed = proxy_timed(row, traces[key], quote, now, day, slot)
                consumed_traces.add(key)
                ready = timed["state"] == "execute"
            else:
                timed = entry_timing.timing(
                    latches.get(row["symbol"]), quote, row["side"], now, today
                )
                ready = timed["state"] in (entry_timing.TRIGGERED, entry_timing.CLOSE)
                timed.update(
                    policy=POLICY,
                    level=None,
                    level_fraction=None,
                    reason="Session completion",
                )
            require(
                ready == (key in attempts),
                "UNRECONSTRUCTIBLE_SENDER_RESULT: "
                "ready/no-quantity/adoption or missing attempt evidence",
            )
            if not ready:
                continue
            apply_attempt(row, attempts[key], accepted, timed, now)
            consumed_attempts.add(key)
            transitions.append(
                {
                    "client_order_id": cid,
                    "at": now.isoformat(),
                    "accepted": attempts[key]["accepted"],
                }
            )
    require(consumed_attempts == set(attempts), "Unmatched original intraday attempts")
    require(consumed_traces == set(traces), "Unmatched original legacy timing receipts")
    require(
        consumed_observations == set(observations),
        "Unmatched original due observations",
    )
    for cid, outcome in outcomes.items():
        if cid in pending:
            require(
                cid in accepted
                and outcome["client_order_id"] == cid
                and outcome["requested_qty"] == accepted[cid]["qty"],
                "Conserved terminal outcome identity differs",
            )
    return state, {
        "scope": "pending_metadata_receipt_conservation_only",
        "archive_sha256": evidence.sha256,
        "transitions": transitions,
        "trace_rows": len(consumed_traces),
        "observations": len(consumed_observations),
        "new_nightly_attempts_not_validated_here": len(records["attempts"])
        - len(consumed_attempts),
        "journal_control_history_reconciliation": False,
        "current_live_timing_parity": "FAILED_SEPARATE_ORIGINAL_PATH_CONTRACT",
        "model_provider_sender_broker_calls": 0,
    }


# Compare a failed first account read without reconciling the closing state.
def compare_unavailable(value, previous, derived, observed, held, session, at):
    before = numerical.serialized(vars(previous))
    after = numerical.serialized(vars(derived))
    before_controls = {key: row for key, row in before.items() if key != "pending"}
    after_controls = {key: row for key, row in after.items() if key != "pending"}
    numerical.exact_integers(
        after_controls, before_controls, "Unavailable retained controls"
    )
    same(
        after_controls,
        before_controls,
        "Unavailable account retained pre-reconciliation controls",
    )
    closing = entry_timing.session_clock(
        instant(at).astimezone(calendar.NEW_YORK).date()
    )["close"] + timedelta(minutes=1)
    require(
        closing.date().isoformat() == session and at == closing.isoformat(),
        "Original unavailable nightly close required",
    )
    messages = {
        "unknown_distribution_cash_in_lieu": (
            "Unknown distribution cash-in-lieu prevents full NAV"
        ),
        "unknown_consolidation_cash_in_lieu": (
            "Unknown consolidation cash-in-lieu prevents full NAV"
        ),
        "unknown_exchange_cash_in_lieu": (
            "Unknown exchange cash-in-lieu prevents full NAV"
        ),
    }
    problem = observed["problem"]
    if problem == "missing_held_close":
        missing = set(observed["missing_symbols"])
        selected = next((name for name in held if name in missing), None)
        require(selected is not None, "Independent missing held symbol required")
        reason = "Fresh raw held mark unavailable for " + selected
    else:
        require(problem in messages, "Independent original account problem required")
        reason = messages[problem]
    expected = {
        "session": session,
        "at": at,
        "text": "",
        "status": "nightly_broker_unavailable",
        "reason": reason,
    }
    same(value["nightly"], expected, "Complete original unavailable nightly result")
    same(value["new_intents"], [], "Unavailable account created no new intent")
    numerical.exact_integers(value["paper_state"], after, "Unavailable full state")
    same(value["paper_state"], after, "Complete original unavailable state")
    require(value["session"] == session, "Unavailable archive session differs")
    return {
        "path": "nightly_broker_unavailable",
        "model_required": False,
        "model_invoked": False,
        "reason": problem,
    }
