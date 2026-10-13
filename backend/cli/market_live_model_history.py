"""Run a separate historical account with exact installed current models.

Every completed session is saved exclusively. Production data is read-only,
and current model availability is explicitly retrospective, not backdated.
"""

import argparse
import gzip
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_actual_policy_timing as economic
from backend.cli.market_strategy_continue import (
    _session_bars,
    close_report,
    inputs,
    timing_reader,
)
from backend.market import (
    calendar,
    entry_timing,
    forward_arithmetic,
    forward_probability_timing,
    holding_risk_bank,
    learned_retention_models,
    live_policy_replay,
)
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.joint_funded_policy import GradeLedFundedPolicy
from backend.market.live_execution_inputs import (
    DAILY_BASIS,
    PassiveMarks,
    RawExecutionInputs,
)
from backend.market.live_model_history import (
    FrozenCurrentGradePolicy,
    FrozenCurrentMarketReader,
    FrozenCurrentRiskReader,
)
from backend.market.market_conditioned_holding import (
    ForwardMarketConditionedHoldingReader,
)
from backend.market.replay_broker import ReplayBroker


# Save immutable stage or session bytes, refusing accidental replay into an old result.
def save(path, value, *, compressed=False):
    raw = json.dumps(
        live_policy_replay.plain(value), allow_nan=False, sort_keys=True
    ).encode()
    if compressed:
        raw = gzip.compress(raw, mtime=0)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
    path.chmod(0o600)
    return sha256(raw).hexdigest()


# Authenticate frozen capture bytes before any retrospective model or account use.
def authenticate(market):
    proof = json.loads((market / "capture.json").read_bytes())
    for name, digest in proof["files"].items():
        if sha256((market / name).read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen current-model input differs: " + name)
    overlay = json.loads((market / "grade-overlay-proof.json").read_bytes())
    for name, digest in overlay["histories"].items():
        if (
            sha256((market / "history" / (name + ".json")).read_bytes()).hexdigest()
            != digest
        ):
            raise ValueError("Authenticated historical grade overlay differs")
    return proof, overlay


# Reuse authenticated reviewed economics, preserving missing inherited-asset marks.
def reviewed_economics(panel, raw, sources):
    receipt = Path("/economic-receipt.json")
    if sha256(receipt.read_bytes()).hexdigest() != (
        "afa4edc554a6a2548e2558077833eb53239494dd685f990f685ac63de8b15a30"
    ):
        raise ValueError("Original reviewed economic input receipt required")
    command = json.loads(receipt.read_bytes())["commands"]["study"]
    fields = (
        "snapshot",
        "provenance",
        "cubes",
        "actions",
        "input_receipt",
        "action_review",
        "passive_arrays",
        "passive_receipt",
        "economic_input_proof",
    )
    values = {}
    for name in fields:
        option = "--" + name.replace("_", "-")
        if command.count(option) != 1:
            raise ValueError("Unique reviewed economic input option required")
        values[name] = Path(command[command.index(option) + 1])
    proof = economic.forecasts.evidence(
        values["economic_input_proof"],
        economic.ECONOMIC_INPUT_PROOF_SHA,
        json_file=True,
    )
    if proof["status"] != "VERIFIED_INDEPENDENT_REVIEWED_ORIGINAL_INPUTS":
        raise ValueError("Independent original economic proof required")
    old_panel, old, _, files = economic.load_execution_inputs(
        SimpleNamespace(**values), reviewed=True
    )
    if panel.tickers != old_panel.tickers:
        raise ValueError("Reviewed economic cohort differs")
    indices = np.searchsorted(panel.dates, old.dates)
    if not np.array_equal(panel.dates[indices], old.dates):
        raise ValueError("Reviewed daily calendar differs")
    if not np.allclose(
        raw.split_factors[indices], old.split_factors, rtol=0, atol=1e-12
    ):
        wrong = np.argwhere(
            np.abs(raw.split_factors[indices] - old.split_factors) > 1e-12
        )
        details = [
            {
                "session": str(old.dates[day]),
                "symbol": panel.tickers[stock],
                "current": float(raw.split_factors[indices[day], stock]),
                "reviewed": float(old.split_factors[day, stock]),
            }
            for day, stock in wrong[:20]
        ]
        raise ValueError(
            "Current archive factors differ from reviewed original units: "
            + json.dumps(details)
        )
    cutoff = str(old.dates[-1])
    actions = {
        name: [dict(row) for row in old.actions[name]]
        + [row for row in raw.actions[name] if row["date"] > cutoff]
        for name in panel.tickers
    }
    passive = old.passive
    shape = (len(panel.dates), len(passive.tickers))
    opening, closing = np.full(shape, np.nan), np.full(shape, np.nan)
    observed = np.full((len(panel.dates), 26, len(passive.tickers)), np.nan)
    opening[indices], closing[indices], observed[indices] = (
        passive.session_open,
        passive.daily_close,
        passive.observation_close,
    )
    aligned = PassiveMarks(
        panel.dates,
        passive.tickers,
        opening,
        observed,
        closing,
        {**dict(passive.provenance), "later_marks": "missing_not_invented"},
    )
    sources.update(
        {name: digest for name, digest in files.items() if digest is not None}
    )
    sources[str(receipt)] = sha256(receipt.read_bytes()).hexdigest()
    sources[str(values["economic_input_proof"])] = economic.ECONOMIC_INPUT_PROOF_SHA
    return replace(
        raw,
        actions=actions,
        passive=aligned,
        inherited_actions=old.inherited_actions,
        provenance={
            **raw.provenance,
            "reviewed_economic_proof_sha256": economic.ECONOMIC_INPUT_PROOF_SHA,
        },
    )


# Compare authentic installed inference, live planning and selected historical prefixes.
def verify_installed_parity(market, panel, raw, reader, holding, output):
    folder = Path("/observation")
    metadata_bytes = (folder / "close.json").read_bytes()
    metadata = json.loads(metadata_bytes)
    original_clock = datetime.fromisoformat(metadata["identity"]["published_at"])
    original = forward_arithmetic.load_close(
        folder,
        market / "desk/learned-holding" / holding["model_directory"],
        receipt_sha256=sha256(metadata_bytes).hexdigest(),
        observed_at=original_clock,
    )
    reader.select(len(panel.dates) - 1)
    for name in (
        "dates",
        "features",
        "prices",
        "forecasts",
        "support",
        "history_prices",
    ):
        left, right = getattr(reader.current, name), getattr(original, name)
        if not np.array_equal(left, right, equal_nan=True):
            wrong = np.argwhere(
                ~np.isclose(left, right, rtol=0, atol=0, equal_nan=True)
            )
            print(
                json.dumps(
                    {
                        "parity_array": name,
                        "different_cells": len(wrong),
                        "examples": [
                            {
                                "index": index.tolist(),
                                "private": live_policy_replay.plain(left[tuple(index)]),
                                "original": live_policy_replay.plain(
                                    right[tuple(index)]
                                ),
                            }
                            for index in wrong[:20]
                        ],
                    }
                ),
                flush=True,
            )
        np.testing.assert_array_equal(
            getattr(reader.current, name), getattr(original, name)
        )
    # Saved chart grades remain authoritative for past direction; the raw live archive
    # recalculates those older rows. Verify current grades and preserve both identities.
    np.testing.assert_array_equal(
        reader.current.history_grades[-1], original.history_grades[-1]
    )
    grade_difference = reader.current.history_grades != original.history_grades
    known = (reader.current.history_grades >= 0) & (original.history_grades >= 0)
    bank, _ = holding_risk_bank.load_bank(
        market / "desk/learned-holding" / holding["risk_directory"],
        receipt_sha256=holding["risk_receipt_sha256"],
        observed_at=datetime.now(UTC),
    )
    live = GradeLedFundedPolicy(
        ForwardMarketConditionedHoldingReader(
            forward_arithmetic.ForwardVolatilityHoldingReader(bank, original)
        ),
        holding["cost_bps"],
    )
    private = FrozenCurrentGradePolicy(reader, holding["cost_bps"])
    day = len(panel.dates) - 1
    scenarios = []
    for name in panel.tickers:
        left, right = (
            live.reader.distribution(day, (name,)),
            reader.distribution(day, (name,)),
        )
        np.testing.assert_array_equal(left.scenarios, right.scenarios)
        np.testing.assert_array_equal(left.probabilities, right.probabilities)
        scenarios.append(
            {
                "symbol": name,
                "scenarios_sha256": _hash(right.scenarios),
                "probabilities_sha256": _hash(right.probabilities),
                "status": right.receipt["status"],
            }
        )
    report = close_report(panel, raw, raw.grades, raw.eligible, day)
    values = (
        str(panel.dates[-1]),
        paper.PaperState(),
        100000,
        {},
        live_policy_replay.marks(panel.tickers, raw.daily_close[-1]),
        report,
        100000,
        set(),
    )
    live_grades = original.history_grades.astype(np.int16)
    live_eligible = live_grades >= 0
    live_raw = replace(
        raw,
        grades=live_grades,
        eligible=live_eligible,
        provenance={
            **raw.provenance,
            "grade_sha256": _hash(live_grades),
            "eligible_sha256": _hash(live_eligible),
        },
    )
    live_report = close_report(panel, live_raw, live_raw.grades, live_raw.eligible, day)
    live_values = (*values[:5], live_report, *values[6:])
    left_orders, left_state, _ = live.plan(*live_values)
    right_orders, right_state, _ = private.plan(*values)
    assert (
        left_state.allocation_state["targets"]
        == right_state.allocation_state["targets"]
    )
    assert [(o.symbol, o.side, o.qty, o.execution_timing) for o in left_orders] == [
        (o.symbol, o.side, o.qty, o.execution_timing) for o in right_orders
    ]
    prefixes = []
    for boundary in ("2019-02-28", "2021-01-04", "2026-09-15"):
        index = int(np.searchsorted(panel.dates, np.datetime64(boundary)))
        assert str(panel.dates[index]) == boundary
        selected = replace(
            panel,
            **{
                name: getattr(panel, name)[: index + 1]
                for name in (
                    "dates",
                    "open",
                    "high",
                    "low",
                    "close",
                    "adj_close",
                    "volume",
                )
            },
        )
        values = learned_retention_models.completed_features(
            selected,
            raw.grades[: index + 1],
            raw.eligible[: index + 1],
            selected.dates,
            {"data_as_of": datetime.now(UTC).isoformat()},
        )
        reader.select(index)
        np.testing.assert_array_equal(reader.current.features, values["X"][-1])
        np.testing.assert_array_equal(reader.current.support, values["risk_valid"][-1])
        prefixes.append(
            {"session": boundary, "features_sha256": _hash(reader.current.features)}
        )
    save(
        output / "installed-parity.json",
        {
            "status": "VERIFIED_INSTALLED_CURRENT_MODEL_NUMERICAL_PARITY",
            "original_close_identity_sha256": metadata["identity_sha256"],
            "original_close_published_at": original_clock.isoformat(),
            "scenarios": scenarios,
            "causal_prefixes": prefixes,
            "historical_grade_basis": (
                "authenticated_saved_and_recalculated_chart_history"
            ),
            "historical_grades_sha256": _hash(raw.grades),
            "original_live_raw_grades_sha256": _hash(original.history_grades),
            "known_historical_grade_differences": int((grade_difference & known).sum()),
            "unavailable_historical_grade_differences": int(
                (grade_difference & ~known).sum()
            ),
            "targets": right_state.allocation_state["targets"],
            "orders": [
                {"symbol": o.symbol, "side": o.side, "qty": o.qty} for o in right_orders
            ],
            "actual_verified_at": datetime.now(UTC).isoformat(),
            "real_orders": False,
        },
    )


# Load unchanged live artifacts and one complete retrospective daily input grid.
def prepare(market, through):
    proof, overlay = authenticate(market)
    actual_now = datetime.now(UTC)
    holding_path = market / "desk/learned-holding/config.json"
    timing_path = market / "desk/learned-timing/config.json"
    holding = json.loads(holding_path.read_bytes())
    timing = json.loads(timing_path.read_bytes())
    if (
        holding["policy"] != "grade-led-learned-sizing/1"
        or holding["cost_bps"] != timing["cost_bps"]
        or holding["cost_bps"] != 10
    ):
        raise ValueError("Exact installed grade-led policy and10bp costs required")
    original, _ = holding_risk_bank.load_bank(
        holding_path.parent / holding["risk_directory"],
        receipt_sha256=holding["risk_receipt_sha256"],
        observed_at=actual_now,
    )
    head, model = forward_arithmetic.load_publication(
        holding_path.parent / holding["model_directory"],
        receipt_sha256=holding["model_receipt_sha256"],
        observed_at=actual_now,
    )
    residuals = forward_probability_timing.load_residual_month(
        timing_path.parent / timing["residual_directory"],
        receipt_sha256=timing["residual_receipt_sha256"],
        observed_at=actual_now,
    )
    values = inputs(market, original, through)
    (
        panel,
        grades,
        eligible,
        factors,
        actions,
        observed,
        following,
        opened,
        present,
        complete,
        sources,
        _,
    ) = values
    close_folder = Path("/observation")
    close_bytes = (close_folder / "close.json").read_bytes()
    close_metadata = json.loads(close_bytes)
    close_array_bytes = (close_folder / "close.npz").read_bytes()
    if sha256(close_array_bytes).hexdigest() != close_metadata["arrays_sha256"]:
        raise ValueError("Original observed grade arrays differ")
    with np.load(close_folder / "close.npz", allow_pickle=False) as archive:
        if (
            not np.array_equal(archive["dates"], panel.dates)
            or tuple(archive["symbols"]) != panel.tickers
        ):
            raise ValueError("Original observed benchmark grade calendar required")
        if (
            _hash(archive["history_grades"])
            != close_metadata["identity"]["array_sha256"]["history_grades"]
        ):
            raise ValueError("Original observed grade hash differs")
        for name in ("SPY", "QQQ"):
            column = panel.tickers.index(name)
            grades[:, column] = archive["history_grades"][:, column]
    eligible = grades >= 0
    sources[str(close_folder / "close.json")] = sha256(close_bytes).hexdigest()
    sources[str(close_folder / "close.npz")] = sha256(close_array_bytes).hexdigest()
    provenance = {
        "daily_price_basis": DAILY_BASIS,
        "supplied": {
            "capture_sha256": sha256((market / "capture.json").read_bytes()).hexdigest()
        },
        "grade_sha256": _hash(grades),
        "eligible_sha256": _hash(eligible),
        "daily_source_arrays": {
            name: _hash(getattr(panel, name))
            for name in ("dates", "open", "high", "low", "close", "adj_close")
        },
    }
    raw = RawExecutionInputs(
        panel.dates,
        panel.tickers,
        grades,
        eligible,
        panel.open * factors,
        panel.high * factors,
        panel.low * factors,
        panel.close * factors,
        observed,
        following,
        opened,
        present,
        complete,
        np.full(panel.close.shape, "unobserved", dtype="U24"),
        factors,
        actions,
        provenance,
    )
    raw = reviewed_economics(panel, raw, sources)
    reader = FrozenCurrentMarketReader(
        FrozenCurrentRiskReader(
            original, panel, grades, eligible, head, model, actual_now
        )
    )
    identity = {
        "policy": holding["policy"],
        "cost_bps": holding["cost_bps"],
        "basis": "fixed_current_models_applied_retrospectively",
        "actual_started_at": actual_now.isoformat(),
        "holding_config_sha256": proof["holding_config_sha256"],
        "timing_config_sha256": proof["timing_config_sha256"],
        "model_receipt_sha256": holding["model_receipt_sha256"],
        "risk_receipt_sha256": holding["risk_receipt_sha256"],
        "timing_model_receipt_sha256": timing["model_receipt_sha256"],
        "timing_residual_receipt_sha256": timing["residual_receipt_sha256"],
        "original_holding_publication": model["identity"]["published_at"],
        "original_holding_fit_date": model["training"]["fit_date"],
        "historical_grade_basis": "authenticated_saved_and_recalculated_chart_history",
        "source_sha256": proof["source_sha256"],
        "capture_sha256": sha256((market / "capture.json").read_bytes()).hexdigest(),
        "grade_overlay": overlay,
        "current_model_inference": reader._parent.identity,
        "real_orders": False,
        "base_models_fitted": 0,
    }
    return panel, raw, reader, holding, timing, residuals, actual_now, sources, identity


# Stream the shared live nightly/sender account with authentic raw observations.
def run(market, output, *, first="2019-03-01", through="2026-10-12", stop=None):
    market, output = Path(market).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(market):
        raise ValueError("New exclusive account output outside source data required")
    panel, raw, reader, holding, timing, residuals, actual_now, sources, identity = (
        prepare(market, date.fromisoformat(through))
    )
    hits = np.flatnonzero(panel.dates == np.datetime64(first))
    if len(hits) != 1 or hits[0] < 1:
        raise ValueError("Historical start needs one original prior close")
    start = int(hits[0])
    end = (
        len(panel.dates) - 1
        if stop is None
        else int(np.searchsorted(panel.dates, np.datetime64(stop)))
    )
    if (
        end < start
        or end >= len(panel.dates)
        or (stop is not None and str(panel.dates[end]) != stop)
    ):
        raise ValueError("Exact in-range bounded session required")
    output.mkdir(mode=0o700, parents=True)
    save(
        output / "admission.json",
        {
            **identity,
            "first": first,
            "through": str(panel.dates[end]),
            "initial_cash": 100000,
            "initial_holdings": {},
        },
    )
    verify_installed_parity(market, panel, raw, reader, holding, output)
    state_root = output / "state"
    broker = ReplayBroker(100000, holding["cost_bps"])
    policy = FrozenCurrentGradePolicy(reader, holding["cost_bps"])
    intents, archives, logs = {}, [], []
    reader.select(start - 1)
    live_policy_replay.nightly(
        panel,
        raw,
        state_root,
        broker,
        start - 1,
        close_report,
        intents,
        logs,
        holding_policy=policy,
    )
    save(
        output / "initial.json.gz",
        {
            "nightly": logs[-1],
            "broker": broker.ledger(),
            "paper_state": asdict(paper.load_state(state_root)),
            "intents": list(intents.values()),
        },
        compressed=True,
    )
    logs.clear()
    for day in range(start, end + 1):
        session = panel.dates[day].astype(object)
        records, auctions = _session_bars(market, panel, day, raw, sources)
        opening = live_policy_replay.instant(panel.dates[day], calendar.REGULAR_OPEN)
        closing = live_policy_replay.instant(
            panel.dates[day], calendar.session_close(session)
        )
        attempt_start, fill_start, old_intents = (
            len(broker.attempt_history),
            len(broker.fill_history),
            set(intents),
        )
        broker.observe(
            opening,
            live_policy_replay.account_marks(raw, day, opening, raw.session_open[day]),
            True,
        )
        live_policy_replay.corporate_actions(broker, raw, day, opening)
        broker.flush(
            opening,
            live_policy_replay.marks(panel.tickers, raw.session_open[day]),
            phase="open",
        )
        forecasts, observed = [], []
        for clock in range(int((closing - opening).total_seconds() // 900) - 1):
            now = opening + timedelta(minutes=15 * (clock + 1))
            live = live_policy_replay.snapshot(raw, day, clock, now)
            broker.observe(
                now,
                live_policy_replay.account_marks(
                    raw, day, now, raw.observation_close[day, clock]
                ),
                True,
            )
            entry_timing.update(state_root, live, now)
            due = intraday_orders.due(paper.load_state(state_root), session)
            timing_rule = (
                timing_reader(
                    panel,
                    raw,
                    records,
                    market / "desk/learned-timing" / timing["model_directory"],
                    residuals,
                    timing,
                    actual_now,
                    day,
                    clock,
                    now,
                    live,
                    due,
                    broker,
                    forecasts,
                )
                if due and now < entry_timing.session_clock(session)["final"]
                else None
            )
            if due:
                lines = intraday_orders.send_due(
                    state_root, live, now, lambda: broker, timing_reader=timing_rule
                )
                observed.append(
                    {
                        "at": now.isoformat(),
                        "due": live_policy_replay.plain(due),
                        "sender_logs": lines,
                    }
                )
            broker.flush(
                now, live_policy_replay.marks(panel.tickers, raw.next_open[day, clock])
            )
        broker.flush(closing, auctions, phase="close")
        reader.select(day)
        live_policy_replay.nightly(
            panel,
            raw,
            state_root,
            broker,
            day,
            close_report,
            intents,
            logs,
            holding_policy=policy,
        )
        value = {
            "session": session.isoformat(),
            "nightly": logs[-1],
            "valuation": live_policy_replay.valuation(broker, raw, day),
            "new_intents": [
                row for key, row in intents.items() if key not in old_intents
            ],
            "attempts": broker.attempt_history[attempt_start:],
            "fills": broker.fill_history[fill_start:],
            "forecast_decisions": forecasts,
            "observations": observed,
            "broker": broker.ledger(),
            "paper_state": asdict(paper.load_state(state_root)),
        }
        path = output / "sessions" / (session.isoformat() + ".json.gz")
        archives.append(
            {
                "session": session.isoformat(),
                "sha256": save(path, value, compressed=True),
            }
        )
        logs.clear()
        progress = {
            "session": session.isoformat(),
            "through": str(panel.dates[end]),
            "sessions_completed": len(archives),
            "fills": len(broker.fill_history),
            "intents": len(intents),
            "actual_updated_at": datetime.now(UTC).isoformat(),
        }
        temporary = output / "progress.tmp"
        temporary.write_text(json.dumps(progress))
        temporary.replace(output / "progress.json")
    if any(
        sha256(Path(path).read_bytes()).hexdigest() != digest
        for path, digest in sources.items()
    ):
        raise ValueError("Original physical source changed during historical account")
    authenticate(market)
    save(
        output / "completion.json",
        {
            **identity,
            "first": first,
            "through": str(panel.dates[end]),
            "sessions": archives,
            "broker": broker.ledger(),
            "paper_state": asdict(paper.load_state(state_root)),
            "input_sha256": sources,
            "fills": len(broker.fill_history),
            "intents": len(intents),
            "status": "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT",
        },
    )
    return progress


# Require explicit private source/output locations and fixed historical boundaries.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--first", default="2019-03-01")
    parser.add_argument("--through", default="2026-10-12")
    parser.add_argument("--stop")
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.market,
                args.output,
                first=args.first,
                through=args.through,
                stop=args.stop,
            )
        )
    )


if __name__ == "__main__":
    main()
