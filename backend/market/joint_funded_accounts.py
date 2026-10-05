"""Fixed candidate accounts using the actual shared planner and cash ledger.

The caller authenticates archived source/input bytes before invoking this runner.
It does not restore models, fetch data, simulate controls or select start dates.
Original control artifacts can be paired once independently verified.
"""

from datetime import datetime
from pathlib import Path

import numpy as np

from backend.cli.market_actual_policy_timing import (
    WINDOWS,
    account_grid,
    account_score,
    archive_account,
)
from backend.cli.market_learned_entry import write_json
from backend.market import calendar
from backend.market.joint_funded_policy import (
    CALIBRATED_POLICY,
    MARKET_TIMED_POLICY,
    MATURITY_POLICY,
    POLICY,
    CalibratedMaturityFundedPolicy,
    JointFundedPolicy,
    MarketConditionedTimedFundedPolicy,
    MaturityFundedPolicy,
)
from backend.market.live_policy_features import FeatureCache
from backend.market.live_policy_replay import plain, run_account


# Admit registered variants with separate IDs and the unchanged start/cost grid.
def _variant(policy):
    options = {
        POLICY: (JointFundedPolicy, "joint"),
        MATURITY_POLICY: (MaturityFundedPolicy, "maturity"),
        CALIBRATED_POLICY: (CalibratedMaturityFundedPolicy, "calibrated"),
        MARKET_TIMED_POLICY: (MarketConditionedTimedFundedPolicy, "market"),
    }
    if not isinstance(policy, str) or policy not in options:
        raise ValueError("Registered funded candidate required")
    return options[policy]


# Retain existing grids and limit calibration screens to their first fixed start.
def candidate_grid(dates, *, policy=POLICY):
    _, prefix = _variant(policy)
    return [
        {**row, "arm": policy, "id": f"{prefix}-{row['cost_bps']}-{row['start']}"}
        for row in account_grid(dates)
        if row["arm"] == "rule"
        and (
            policy not in (CALIBRATED_POLICY, MARKET_TIMED_POLICY) or row["start"] == 0
        )
    ]


# Carry each predeclared private account and retain all requests, fills and missing NAV.
def evaluate(panel, raw, cubes, reader, output, source_identity, *, policy=POLICY):
    policy_type, _ = _variant(policy)
    if not np.array_equal(panel.dates, reader.dates) or tuple(panel.tickers) != tuple(
        reader.symbols
    ):
        raise ValueError("Original risk and physical-account grids must match")
    if (
        not isinstance(source_identity, dict)
        or not source_identity.get("manifest_sha256")
        or not source_identity.get("source_revision")
    ):
        raise ValueError("Authenticated source identity required")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    accounts = output / "accounts"
    accounts.mkdir()
    grid = candidate_grid(panel.dates, policy=policy)
    write_json(
        output / "inputs.json",
        {
            "policy": policy,
            "source": source_identity,
            "accounts": grid,
            "raw_provenance": plain(raw.provenance),
            "adoption_eligible": False,
        },
    )
    cache = FeatureCache(source_identity["manifest_sha256"])
    rows = []
    for spec in grid:
        completed = 0

        # Publish completed-session receipts without supplying future planning inputs.
        def progress(row, account_id=spec["id"], final=str(panel.dates[spec["last"]])):
            nonlocal completed
            completed += 1
            if completed == 1 or completed % 20 == 0 or row["session"] == final:
                write_json(
                    output / "active-account.json",
                    {
                        "account": account_id,
                        "completed_accounts": len(rows),
                        "completed_sessions": completed,
                        "session": row["session"],
                        "written_at": datetime.now(calendar.NEW_YORK).isoformat(),
                    },
                )

        result = run_account(
            panel,
            raw,
            cubes,
            output / "state" / spec["id"],
            spec["first"],
            spec["last"],
            spec["cost_bps"],
            holding_policy=policy_type(reader, spec["cost_bps"]),
            feature_reader=cache,
            on_session=progress,
        )
        result["comparison_account"] = spec
        artifact = accounts / (spec["id"] + ".json.gz")
        digest = archive_account(artifact, result)
        rows.append(
            {
                **spec,
                "file": str(artifact.relative_to(output)),
                "sha256": digest,
                "scores": {
                    name: account_score(result, lower, upper)
                    for name, lower, upper in WINDOWS
                },
            }
        )
        write_json(
            output / "progress.json",
            {
                "status": "running",
                "completed": len(rows),
                "declared": len(grid),
                "accounts": rows,
                "source": source_identity,
                "adoption_eligible": False,
            },
        )
    report = {
        "status": "complete_candidate_unverified_controls",
        "policy": policy,
        "source": source_identity,
        "accounts": rows,
        "declared": len(grid),
        "adoption_eligible": False,
    }
    write_json(output / "report.json", report)
    return report
