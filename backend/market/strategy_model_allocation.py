"""Read-only strategy targets on one unit of capital, without a funded account.

These are model portfolio percentages, not quantities to trade in an account.
Original approved model/risk/close evidence is required; no new forecast, broker
request, paper transition, record rewrite or historical replay occurs here.
"""

import json
from datetime import datetime
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.market import (
    adaptive_growth_policy as growth,
    forward_arithmetic as forward,
    grade_led_leader_policy as leader,
    grade_led_policy,
    holding_risk_bank,
    joint_funded_policy as funded,
    learned_live_holding,
    live_model_decision,
)

VERSION = "strategy-model-allocation/1"
BASIS = "account_independent_unit_capital_targets"


# Allocate the installed sizing over a unit budget rather than an account's money.
def targets_from_model(
    report, reader, cost_bps, blocked, policy=grade_led_policy.POLICY
):
    if policy not in learned_live_holding.GRADE_LED_POLICIES:
        raise ValueError("Installed grade-led model required")
    policy = (
        leader.GradeLedLeaderFundedPolicy if policy == leader.POLICY
        else funded.GradeLedFundedPolicy
    )(reader, cost_bps)
    signals = grade_led_policy.signals(report, {}, policy.entry_grade)
    grades = {
        name: int(report.graded.grades[-1, column])
        for column, name in enumerate(report.panel.tickers) if name in signals
    }
    day = int(np.flatnonzero(reader.dates == report.panel.dates[-1])[0])
    names, qualification = policy._required_stocks(grades, {}, day, blocked)
    targets = dict.fromkeys(signals, 0.0)
    if qualification.get("refusal_reason"):
        raise ValueError(qualification["refusal_reason"])
    proof = {"status": "no_eligible_entries", "targets": []}
    scenario = None
    if names and policy.version == leader.POLICY:
        # The same arithmetic the funded plan uses, on unit capital with no holdings.
        sizes, proof = leader.size_report(report, names, blocked, {})
        targets.update(sizes)
    elif names:
        sample = policy.reader.distribution(day, names)
        scenario = sample.receipt
        if scenario["status"] != "available":
            raise ValueError("Original current joint-risk evidence unavailable")
        weights, proof = growth.allocate_distribution(
            sample.scenarios, sample.probabilities,
            np.array([grades[name] for name in names]),
            np.ones(len(names), dtype=bool), np.zeros(len(names)),
            1.0, cost_bps, np.array([], dtype=np.int64), horizon=funded.HORIZON,
        )
        if proof["status"] != "optimized":
            raise ValueError("Certified current strategy allocation unavailable")
        targets.update(zip(names, weights.tolist(), strict=True))
    if (
        any(not np.isfinite(v) or not 0 <= v <= growth.CAP for v in targets.values())
        or sum(targets.values()) > 1 + 1e-10
        or any(targets[name] > 0 for name in blocked)
    ):
        raise ValueError("Finite grade-qualified unit-capital percentages required")
    return targets, signals, {
        "basis": BASIS, "cost_bps": cost_bps,
        "entry_qualification": qualification, "scenario": scenario,
        **({"leader_sizing": proof} if policy.version == leader.POLICY
           else {"optimizer": proof}),
    }


# Authenticate original current market/model evidence without reading account cash or allocation status.
def read(root, record, now):
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("Aware strategy observation required")
    root = Path(root)
    until = live_model_decision._valid_until(record["session"])
    if now >= until:
        raise ValueError("Current strategy inputs expired")
    digest, config, report = live_model_decision._authenticate(root, record, now)
    if config["policy"] not in learned_live_holding.GRADE_LED_POLICIES:
        raise ValueError("Installed grade-led model required")
    admission = record["paper"]["learned_holding"]
    original, _ = holding_risk_bank.load_bank(
        learned_live_holding._folder(root, config["risk_directory"]),
        receipt_sha256=config["risk_receipt_sha256"], observed_at=now,
    )
    observation = forward.load_close(
        root / "desk/learned-holding/observations" / Path(admission["close_directory"]).name,
        learned_live_holding._folder(root, config["model_directory"]),
        receipt_sha256=admission["close_receipt_sha256"], observed_at=now,
    )
    reader = forward.ForwardVolatilityHoldingReader(original, observation)
    original_market = record["paper"]["joint_funded"]["receipt"]
    blocked = original_market["buy_blocked"]
    names = set(record["grades"])
    grades = {
        name: int(report.graded.grades[-1, column])
        for column, name in enumerate(report.panel.tickers) if name in names
    }
    if (
        original_market["grades"] != grades or not isinstance(blocked, list)
        or len(set(blocked)) != len(blocked) or not set(blocked) <= names
    ):
        raise ValueError("Original independent market entry evidence required")
    targets, signals, receipt = targets_from_model(
        report, reader, config["cost_bps"], set(blocked), config["policy"]
    )
    receipt.update(
        version=VERSION, record_sha256=digest,
        close_receipt_sha256=admission["close_receipt_sha256"],
        risk_receipt_sha256=config["risk_receipt_sha256"],
        model_receipt_sha256=config["model_receipt_sha256"],
        calculation_source_sha256=sha256(Path(__file__).read_bytes()).hexdigest(),
        targets=targets, grade_signals=signals,
    )
    encoded = json.dumps(receipt, sort_keys=True, allow_nan=False).encode()
    return {
        "version": VERSION, "status": "available", "reason": None,
        "policy": config["policy"], "session": record["session"],
        "observed_at": record["written"], "as_of": now.isoformat(),
        "valid_until": until.isoformat(), "record_sha256": digest,
        "receipt_sha256": sha256(encoded).hexdigest(), "basis": BASIS,
        "grade_signals": signals,
        "rows": {name: {"target_weight": value} for name, value in targets.items()},
        "calculation_receipt": receipt,
    }
