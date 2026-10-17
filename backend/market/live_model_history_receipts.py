"""Independently conserve saved historical requests, outcomes and durable identities."""

import math
from copy import deepcopy
from datetime import datetime

from backend.market import calendar


# Reject malformed evidence without converting booleans into quantities or money.
def require(condition, message):
    if not condition:
        raise ValueError(message)


# Compare saved financial arithmetic without permitting nonfinite evidence.
def same_number(actual, expected, message):
    require(
        not isinstance(actual, bool)
        and isinstance(actual, (int, float))
        and math.isfinite(actual)
        and math.isclose(actual, expected, rel_tol=2e-10, abs_tol=1e-7),
        message,
    )


# Require positive or explicitly zero whole-share receipt quantities.
def whole(value, *, zero=False):
    require(
        type(value) is int and value >= (0 if zero else 1),
        "Whole receipt shares required",
    )
    return value


# Parse an aware saved clock while retaining its original text in all evidence.
def instant(value):
    require(isinstance(value, str), "Saved receipt clock required")
    parsed = datetime.fromisoformat(value)
    require(parsed.utcoffset() is not None, "Aware saved receipt clock required")
    return parsed


# Audit saved receipts without submitting, selecting, fitting or changing an order.
class ReceiptLedger:
    # Start the independent cash/reservation ledger and durable transition history.
    def __init__(self, cash=100000, cost_bps=10):
        self.cash, self.cost_bps = cash, cost_bps
        self.accepted, self.outcomes, self.outstanding = {}, {}, {}
        self.attempt_keys, self.cancellations = set(), {}
        self.filled, self.journal = {}, {}
        self.last_attempt, self.last_fill, self.last_state = None, None, None

    # Match a receipt to its original funded identity without replacing its quantity.
    def identity(self, row, intents):
        identifier = row["client_order_id"]
        original = intents.get(identifier)
        require(
            original is not None
            and row["symbol"] == original["symbol"]
            and row["side"] == original["side"]
            and row["side"] in ("buy", "sell"),
            "Receipt differs from original funded intent",
        )
        whole(original["qty"])
        return identifier, original

    # Authenticate requested shares, ordering, acceptance and original execution window.
    def attempts(self, rows, intents, observed):
        for row in rows:
            identifier, original = self.identity(row, intents)
            qty, at = whole(row["qty"]), instant(row["at"])
            decision = instant(original["execution"]["decision_at"])
            require(
                qty <= original["qty"] and decision <= at <= observed,
                "Attempt quantity or clock differs from original funded intent",
            )
            require(
                self.last_attempt is None or at >= self.last_attempt,
                "Attempt clocks moved backwards",
            )
            require(
                self.last_state is None or at > self.last_state,
                "Attempt was added after its original saved observation",
            )
            key = identifier, at
            require(
                key not in self.attempt_keys, "Duplicate attempted identity and clock"
            )
            require(
                identifier not in self.accepted, "Attempt follows accepted identity"
            )
            self.attempt_keys.add(key)
            self.last_attempt = at
            if original.get("execution_timing") == "intraday":
                local = at.astimezone(calendar.NEW_YORK)
                require(
                    local.date().isoformat() == original["execute_on"]
                    and calendar.REGULAR_OPEN
                    < local.time()
                    < calendar.session_close(local.date())
                    and not local.second
                    and not local.microsecond
                    and local.minute % 15 == 0,
                    "Attempt is outside the original completed-bar execution window",
                )
            require(
                type(row["accepted"]) is bool, "Explicit attempt acceptance required"
            )
            terminated = row["reason"] == "terminated_security"
            if terminated:
                require(
                    not row["accepted"]
                    and row["observed_price"] is None
                    and row["available_cash"] is None,
                    "Terminated-security refusal evidence differs",
                )
            else:
                same_number(
                    row["observed_price"],
                    row["observed_price"],
                    "Finite observed attempt price required",
                )
                same_number(
                    row["available_cash"],
                    row["available_cash"],
                    "Finite attempt cash required",
                )
                require(
                    row["observed_price"] > 0 and row["available_cash"] >= 0,
                    "Positive price and nonnegative attempt cash required",
                )
                require(
                    row["reason"] is None
                    if row["accepted"]
                    else row["reason"]
                    in ("insufficient_reserved_cash", "uncovered_sell"),
                    "Attempt status or refusal reason differs",
                )
                require(
                    row["reason"] != "uncovered_sell" or row["side"] == "sell",
                    "Uncovered-sale refusal names a buy",
                )
                require(
                    row["reason"] != "insufficient_reserved_cash"
                    or row["side"] == "buy",
                    "Cash refusal names a sale",
                )
            if row["accepted"]:
                self.accepted[identifier] = deepcopy(row)

    # Bind every terminal outcome to its accepted submitted shares and exact clock.
    def fills(self, rows, intents, observed):
        for row in rows:
            identifier, original = self.identity(row, intents)
            accepted = self.accepted.get(identifier)
            require(accepted is not None, "Fill has no accepted original attempt")
            at = instant(row["at"])
            require(
                instant(accepted["at"]) <= at <= observed
                and (self.last_fill is None or at >= self.last_fill),
                "Fill clocks differ from accepted attempt",
            )
            require(
                self.last_state is None or at > self.last_state,
                "Fill was added after its original saved observation",
            )
            require(
                identifier not in self.outcomes, "Duplicate terminal execution identity"
            )
            qty, requested = (
                whole(row["filled_qty"], zero=True),
                whole(row["requested_qty"]),
            )
            require(
                requested == accepted["qty"] and qty <= requested <= original["qty"],
                "Fill exceeds original submitted or funded shares",
            )
            require(
                row["status"] == ("filled" if qty == requested else "expired"),
                "Execution terminal status differs",
            )
            if qty:
                same_number(
                    row["price"], row["price"], "Finite execution price required"
                )
                require(row["price"] > 0, "Positive execution price required")
                require(
                    row["reason"]
                    == ("filled" if qty == requested else "partial_cash_or_coverage"),
                    "Execution reason differs",
                )
            else:
                require(
                    row["price"] is None
                    and row["reason"]
                    in ("missing_execution_price", "partial_cash_or_coverage"),
                    "Zero execution price or reason differs",
                )
            same_number(
                row["fee"],
                qty * (row["price"] or 0) * self.cost_bps / 10000,
                "Execution fee differs",
            )
            self.filled[identifier] = self.filled.get(identifier, 0) + qty
            require(
                self.filled[identifier] <= accepted["qty"],
                "Cumulative execution exceeds submitted shares",
            )
            self.outcomes[identifier] = deepcopy(row)
            self.last_fill = at

    # Preserve original decisions and every durable intent through valid transitions.
    def durable(self, state, intents, observed):
        collections = {}
        for kind in ("pending", "journal"):
            rows = state[kind]
            require(isinstance(rows, list), "Durable receipt list required")
            indexed = {}
            for row in rows:
                identifier, original = self.identity(row, intents)
                require(
                    identifier not in indexed, "Duplicate durable " + kind + " identity"
                )
                indexed[identifier] = row
                require(
                    row["qty"] == original["qty"]
                    and type(row["qty"]) is int
                    and row["session"] == original["session"],
                    "Durable receipt changed original funded intent",
                )
                for name in ("kind", "event_id"):
                    require(
                        row.get(name) == original.get(name),
                        "Durable original order leg identity differs",
                    )
                execution = row.get("execution", {})
                for name, value in original["execution"].items():
                    require(
                        execution.get(name) == value,
                        "Durable original decision evidence differs",
                    )
                accepted = self.accepted.get(identifier)
                if accepted is not None:
                    clocks = [
                        execution[name]
                        for name in ("created_at", "submitted_at")
                        if name in execution
                    ]
                    require(
                        clocks
                        and all(
                            instant(clock) == instant(accepted["at"])
                            for clock in clocks
                        ),
                        "Accepted attempt lacks matching original broker clock",
                    )
                    sent = row.get("sent")
                    if sent is not None:
                        require(
                            instant(sent["at"]) == instant(accepted["at"])
                            and (
                                "qty" not in sent
                                or (
                                    type(sent["qty"]) is int
                                    and sent["qty"] == accepted["qty"]
                                )
                            ),
                            "Original sent request differs from accepted attempt",
                        )
                for name in (
                    "created_at",
                    "submitted_at",
                    "filled_at",
                    "expired_at",
                    "canceled_at",
                ):
                    if name in execution:
                        decision = instant(original["execution"]["decision_at"])
                        clock = instant(execution[name])
                        require(
                            (
                                clock >= decision
                                if name in ("created_at", "submitted_at")
                                else clock > decision
                            )
                            and clock <= observed,
                            "Durable broker clock is outside original observation",
                        )
                if "canceled_at" in execution:
                    require(
                        accepted is not None, "Cancellation has no accepted request"
                    )
                    require(
                        identifier not in self.outcomes,
                        "Terminal execution cannot also be canceled",
                    )
                    previous = self.cancellations.get(identifier)
                    require(
                        previous is None or previous == execution["canceled_at"],
                        "Original cancellation clock changed",
                    )
                    self.cancellations[identifier] = execution["canceled_at"]
                if kind == "pending":
                    for name, original_value in original.items():
                        if name == "execution":
                            continue
                        require(
                            row.get(name) == original_value,
                            "Durable pending execution basis changed",
                        )
            collections[kind] = indexed
        require(
            set(collections["pending"]) | set(collections["journal"]) == set(intents),
            "Original durable intent is missing from pending and journal",
        )
        for identifier, previous in self.journal.items():
            current = collections["journal"].get(identifier)
            require(
                current is not None, "Original durable journal identity disappeared"
            )
            if previous["terminal"]:
                require(current == previous, "Terminal durable journal receipt changed")
            else:
                require(
                    current["filled_qty"] >= previous["filled_qty"],
                    "Durable journal filled quantity regressed",
                )
        for identifier, row in collections["journal"].items():
            qty = whole(row["filled_qty"], zero=True)
            expected = self.filled.get(identifier, 0)
            require(
                qty == expected,
                "Durable journal differs from conserved executed shares",
            )
            outcome = self.outcomes.get(identifier)
            same_number(
                row["filled_price"],
                (outcome["price"] or 0) if outcome else 0,
                "Durable journal execution price differs",
            )
            status, terminal = row["status"], row["terminal"]
            require(type(terminal) is bool, "Explicit durable terminal state required")
            if status == "filled":
                require(
                    qty == intents[identifier]["qty"] and terminal,
                    "Durable filled status differs",
                )
            elif status == "partial":
                require(
                    0 < qty < intents[identifier]["qty"]
                    and terminal
                    == (outcome is not None or identifier in self.cancellations),
                    "Durable partial status differs",
                )
            elif status in ("missing", "dead", "open"):
                require(
                    qty == 0 and terminal == (status != "open"),
                    "Durable zero-outcome status differs",
                )
                if status == "missing":
                    require(
                        identifier not in self.accepted,
                        "Accepted request cannot become missing",
                    )
                elif status == "dead":
                    require(
                        outcome is not None or identifier in self.cancellations,
                        "Dead request has no original terminal outcome",
                    )
                else:
                    require(
                        identifier in self.accepted
                        and outcome is None
                        and identifier not in self.cancellations,
                        "Open request has terminal outcome",
                    )
            elif status == "skipped":
                require(
                    row["side"] == "sell" and terminal,
                    "Skipped durable request differs",
                )
            else:
                raise ValueError("Unknown durable journal status")
            require(
                (identifier in collections["pending"]) == (not terminal),
                "Durable pending/journal terminal transition differs",
            )
        self.journal = deepcopy(collections["journal"])

    # Reconcile cash reservations and prevent same-batch sale funding.
    def funding(self, attempts, fills):
        clocks = sorted(
            {instant(row["at"]) for row in attempts + fills}
            | {
                instant(at)
                for identifier, at in self.cancellations.items()
                if identifier in self.outstanding
            }
        )
        for at in clocks:
            for identifier, canceled in self.cancellations.items():
                if instant(canceled) <= at:
                    self.outstanding.pop(identifier, None)
            for row in attempts:
                if instant(row["at"]) != at or row["reason"] == "terminated_security":
                    continue
                available = max(0, self.cash - sum(self.outstanding.values()))
                same_number(
                    row["available_cash"],
                    available,
                    "Independent submission buying-power reservation differs",
                )
                need = (
                    row["qty"] * row["observed_price"] * (1 + self.cost_bps / 10000)
                    if row["side"] == "buy"
                    else 0
                )
                require(
                    not row["accepted"] or need <= available + 1e-7,
                    "Accepted request spends unfunded cash",
                )
                if row["reason"] == "insufficient_reserved_cash":
                    require(
                        need > available, "Insufficient-cash refusal is inconsistent"
                    )
                if row["accepted"]:
                    self.outstanding[row["client_order_id"]] = need
            batch = [row for row in fills if instant(row["at"]) == at]
            identifiers = {row["client_order_id"] for row in batch}
            budget = max(
                0,
                self.cash
                - sum(
                    value
                    for identifier, value in self.outstanding.items()
                    if identifier not in identifiers
                ),
            )
            spent = sum(
                row["filled_qty"] * (row["price"] or 0) + row["fee"]
                for row in batch
                if row["side"] == "buy"
            )
            require(
                spent <= budget + 1e-7, "Same-batch sale proceeds funded a purchase"
            )
            self.cash += (
                sum(
                    row["filled_qty"] * (row["price"] or 0) - row["fee"]
                    for row in batch
                    if row["side"] == "sell"
                )
                - spent
            )
            for identifier in identifiers:
                self.outstanding.pop(identifier, None)

    # Check one immutable session while retaining only independent audit-side state.
    def check(self, value, intents):
        observed = instant(value["broker"]["observed_at"])
        require(
            self.last_state is None or observed > self.last_state,
            "Saved account observation clock did not advance",
        )
        for row in value["attempts"]:
            if row["reason"] == "terminated_security":
                require(
                    any(
                        record["symbol"] == row["symbol"]
                        and instant(record["completed_before"]) <= instant(row["at"])
                        for record in value["broker"].get("cash_mergers", [])
                    ),
                    "Terminated-security refusal lacks original economic entitlement",
                )
        self.attempts(value["attempts"], intents, observed)
        self.fills(value["fills"], intents, observed)
        self.durable(value["paper_state"], intents, observed)
        self.funding(value["attempts"], value["fills"])
        same_number(
            value["broker"]["cash"],
            self.cash,
            "Independent reserved-cash ledger differs",
        )
        self.last_state = observed
