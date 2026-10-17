"""Independently conserve a new current-model account; never choose or replay orders."""

import argparse
import gzip
import json
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import paper
from backend.cli import verify_actual_policy_timing as ledger
from backend.cli.market_live_model_history import prepare, save, verify_installed_parity
from backend.market import calendar, intraday_sip
from backend.market.live_model_history_projection import (
    overlay_digest,
    project,
    session,
)
from backend.market.live_model_history_receipts import ReceiptLedger
from backend.market.store import MarketStore


# Recompute frozen numerical and causal parity without overwriting the producer receipt.
def independent_parity(market, panel, raw, reader, holding, original, folder):
    folder.mkdir(mode=0o700, parents=True, exist_ok=False)
    verify_installed_parity(market, panel, raw, reader, holding, folder)
    path = folder / "installed-parity.json"
    fresh = json.loads(path.read_bytes())
    ledger.same(
        {key: value for key, value in fresh.items() if key != "actual_verified_at"},
        {key: value for key, value in original.items() if key != "actual_verified_at"},
        "Independent numerical and causal parity",
    )
    return sha256(path.read_bytes()).hexdigest()


# Bind original chart-grade inputs and stocks to the authenticated model cohort.
def complete_cohort(completion, overlay, panel):
    ledger.same(
        completion["grade_overlay"], overlay, "Authenticated historical grade overlay"
    )
    names = sorted(overlay["histories"])
    ledger.require(
        len(names) == 94 and set(names) == set(panel.tickers) - {"SPY", "QQQ"},
        "Exact authenticated94-stock historical cohort required",
    )
    return names


# Conserve original identities and cumulative quantities across attempts and fills.
def order_receipts(value, intents, totals, audit=None):
    audit = audit or ReceiptLedger()
    audit.check(value, intents)
    totals.clear()
    totals.update(audit.filled)
    return audit


# Match each nonzero execution to an original raw SIP opening, without daily proxies.
def physical_fill(market, fill, cost_bps):
    qty = fill["filled_qty"]
    ledger.require(
        type(qty) is int and qty >= 0, "Nonnegative whole filled shares required"
    )
    at = ledger.aware(fill["at"]).astimezone(calendar.NEW_YORK)
    found = intraday_sip.read_session_full(
        MarketStore(market), fill["symbol"], at.date()
    )
    complete = found is not None and found[2].get("complete") == "true"
    regular, auction = found[:2] if complete else ([], None)
    bar = (
        auction
        if at.time() == calendar.session_close(at.date())
        else next((row for row in regular if row.start == at), None)
    )
    priced = bar is not None and np.isfinite(bar.open) and bar.open > 0
    if not qty:
        ledger.require(fill["price"] is None, "Zero execution has an invented price")
        ledger.same(fill["fee"], 0, "zero-execution fee")
        ledger.require(
            fill["reason"]
            == ("partial_cash_or_coverage" if priced else "missing_execution_price"),
            "Zero execution missing-price reason differs from original raw bars",
        )
        return False
    ledger.require(priced, "Original raw bar at exact simulated execution required")
    ledger.same(fill["price"], float(bar.open), "raw SIP simulated execution price")
    ledger.same(
        fill["fee"], qty * fill["price"] * cost_bps / 10000, "per-side fill fee"
    )
    return True


# Match a submitted request's observed price to its completed raw SIP prefix.
def physical_attempt(market, attempt, panel, raw):
    if attempt["reason"] == "terminated_security":
        return False
    at = ledger.aware(attempt["at"]).astimezone(calendar.NEW_YORK)
    if at.time() > calendar.session_close(at.date()):
        day = int(np.searchsorted(panel.dates, np.datetime64(at.date())))
        ledger.require(
            day < len(panel.dates) and panel.dates[day] == np.datetime64(at.date()),
            "Observed attempt session is absent from original daily grid",
        )
        price = raw.daily_close[day, panel.tickers.index(attempt["symbol"])]
    else:
        found = intraday_sip.read_session_full(
            MarketStore(market), attempt["symbol"], at.date()
        )
        ledger.require(
            found is not None and found[2].get("complete") == "true",
            "Original complete raw attempt bars required",
        )
        regular = found[0]
        if at.time() == calendar.REGULAR_OPEN:
            price = regular[0].open if regular and regular[0].start == at else None
        else:
            bar = next(
                (row for row in regular if row.start + timedelta(minutes=15) == at),
                None,
            )
            price = bar.close if bar else None
        ledger.require(price is not None, "Attempt has no original completed raw bar")
    ledger.same(
        attempt["observed_price"], float(price), "observed raw SIP submission price"
    )
    return True


# Reconstruct shares, cash, basis and entitlements from dated source events.
def verify(market, account_root, output):
    market, root, output = Path(market), Path(account_root), Path(output)
    if output.exists():
        raise ValueError("Exclusive independent verification output required")
    raw_completion = (root / "completion.json").read_bytes()
    completion = json.loads(raw_completion)
    captured = json.loads((market / "capture.json").read_bytes())
    panel, raw, reader, holding, _, _, _, _, identity = prepare(
        market, date.fromisoformat(captured["through"])
    )
    overlay = json.loads((market / "grade-overlay-proof.json").read_bytes())
    tickers = complete_cohort(completion, overlay, panel)
    ledger.require(
        completion["status"] == "COMPLETED_UNVERIFIED_CURRENT_MODEL_ACCOUNT"
        and completion["policy"] == holding["policy"]
        and completion["cost_bps"] == 10
        and completion["real_orders"] is False
        and completion["base_models_fitted"] == 0,
        "Exact isolated grade-led current-model account required",
    )
    for key in (
        "holding_config_sha256",
        "timing_config_sha256",
        "model_receipt_sha256",
        "risk_receipt_sha256",
        "timing_model_receipt_sha256",
        "timing_residual_receipt_sha256",
        "capture_sha256",
        "source_sha256",
    ):
        ledger.same(completion[key], identity[key], "Frozen account " + key)
    for path, expected in completion["input_sha256"].items():
        ledger.require(
            sha256(Path(path).read_bytes()).hexdigest() == expected,
            "Physical account input bytes differ",
        )
    parity = json.loads((root / "installed-parity.json").read_bytes())
    ledger.require(
        parity["status"] == "VERIFIED_INSTALLED_CURRENT_MODEL_NUMERICAL_PARITY"
        and len(parity["scenarios"]) == 96
        and len(parity["causal_prefixes"]) == 3,
        "Installed-model numerical and causal-prefix evidence required",
    )
    parity_sha = independent_parity(
        market,
        panel,
        raw,
        reader,
        holding,
        parity,
        output.parent / (output.stem + "-independent-parity"),
    )
    initial = json.loads(gzip.decompress((root / "initial.json.gz").read_bytes()))
    ledger.same(initial["broker"]["cash"], 100000, "New independent capital")
    ledger.same(initial["broker"]["holdings"], {}, "New independent empty book")
    expected_dates = panel.dates[
        (panel.dates >= np.datetime64(completion["first"]))
        & (panel.dates <= np.datetime64(completion["through"]))
    ]
    ledger.same(
        [row["session"] for row in completion["sessions"]],
        list(map(str, expected_dates)),
        "Complete account session sequence",
    )
    events = ledger.source_events(
        {
            "actions": {str(name): rows for name, rows in raw.actions.items()},
            "inherited_actions": {
                str(name): rows for name, rows in (raw.inherited_actions or {}).items()
            },
        }
    )
    cash, held, basis, dividends, seen = 100000, {}, {}, [], set()
    records = {
        name: []
        for name in (
            "security_distributions",
            "share_consolidations",
            "security_exchanges",
            "cash_mergers",
        )
    }
    initial_at = ledger.aware(initial["broker"]["observed_at"])
    ledger.fold_actions(
        events, initial_at, held, basis, dividends, records, seen, completion["broker"]
    )
    ledger.same(
        initial["broker"]["dividends"], dividends, "Initial zero-share entitlements"
    )
    intents = {row["client_order_id"]: row for row in initial["intents"]}
    ledger.require(len(intents) == len(initial["intents"]), "Duplicate initial intent")
    receipt_audit = order_receipts(
        {**initial, "attempts": [], "fills": []}, intents, {}
    )
    fill_count, all_fills, attempts, priced_attempts = 0, 0, 0, 0
    missing_marks, unknown_claims = 0, 0
    price_data = {
        "names": panel.tickers,
        "close": raw.daily_close,
        "passive": {
            "names": raw.passive.tickers,
            "close": raw.passive.daily_close,
        }
        if raw.passive
        else None,
    }
    totals = {}
    for record in completion["sessions"]:
        value = session(root, record)
        day = date.fromisoformat(value["session"])
        opening = datetime.combine(day, calendar.REGULAR_OPEN, calendar.NEW_YORK)
        closing = datetime.combine(
            day, calendar.session_close(day), calendar.NEW_YORK
        ) + timedelta(minutes=1)
        ledger.fold_actions(
            events, opening, held, basis, dividends, records, seen, completion["broker"]
        )
        for fill in value["fills"]:
            intent = intents.get(fill["client_order_id"])
            ledger.require(
                intent is not None
                and fill["symbol"] == intent["symbol"]
                and fill["side"] == intent["side"]
                and fill["filled_qty"] <= intent["qty"],
                "Simulated fill differs from original durable intent",
            )
            fill_count += physical_fill(market, fill, completion["cost_bps"])
        priced_attempts += sum(
            physical_attempt(market, row, panel, raw) for row in value["attempts"]
        )
        all_fills += len(value["fills"])
        attempts += len(value["attempts"])
        cash = ledger.fold_fills(value["fills"], cash, held, basis)
        ledger.fold_actions(
            events, closing, held, basis, dividends, records, seen, completion["broker"]
        )
        actual = value["broker"]
        for name, expected in (
            ("cash", cash),
            ("holdings", held),
            ("average_prices", basis),
        ):
            ledger.same(actual[name], expected, value["session"] + " " + name)
        ledger.same(actual["dividends"], dividends, value["session"] + " dividends")
        for name, expected in records.items():
            ledger.same(actual.get(name, []), expected, "Economic entitlement " + name)
        missing, unknown = ledger.check_valuation(
            {"session": value["session"], **value["valuation"]},
            price_data,
            int(np.searchsorted(panel.dates, np.datetime64(day))),
            ledger.aware(actual["observed_at"]),
            cash,
            held,
            dividends,
            records,
        )
        missing_marks += missing
        unknown_claims += unknown
        for intent in value["new_intents"]:
            ledger.require(
                intent["client_order_id"] not in intents, "Duplicate new account intent"
            )
            intents[intent["client_order_id"]] = intent
        order_receipts(value, intents, totals, receipt_audit)
        if value["nightly"]["status"] == "planned":
            ledger.same(
                value["nightly"]["persisted_policy"],
                holding["policy"],
                "Persisted live grade-led policy",
            )
        ledger.same(
            ledger.aware(actual["observed_at"]),
            closing.astimezone(UTC),
            "Historical completed close clock",
        )
    ledger.same(completion["broker"], value["broker"], "Ending account ledger")
    ledger.same(
        completion["paper_state"], value["paper_state"], "Ending durable account state"
    )
    state_path = paper.state_path(root / "state")
    ledger.same(
        json.loads(state_path.read_bytes()),
        value["paper_state"],
        "Physical final paper state",
    )
    ledger.same(completion["intents"], len(intents), "Original intent count")
    ledger.same(completion["fills"], all_fills, "Original complete fill receipt count")
    result = {
        "status": "VERIFIED_CURRENT_MODEL_HISTORICAL_ACCOUNT",
        "account_sha256": sha256(raw_completion).hexdigest(),
        "verified_tickers": tickers,
        "grade_overlay_content_sha256": overlay_digest(overlay),
        "sessions": len(completion["sessions"]),
        "filled_receipts": fill_count,
        "intents": len(intents),
        "execution_attempts": attempts,
        "raw_observed_price_attempts": priced_attempts,
        "all_execution_receipts": all_fills,
        "zero_execution_receipts": all_fills - fill_count,
        "durable_pending_and_journal": True,
        "independent_attempt_outcome_and_durable_transitions": True,
        "independent_cash_reservations_and_batch_funding": True,
        "learned_timing_inference_verified": False,
        "learned_timing_acceptance": (
            "UNVERIFIED; holding parity and conserved receipts do not prove "
            "per-session installed15m timing inference"
        ),
        "every_saved_nightly_model_proposal_verified": False,
        "missing_held_mark_sessions": missing_marks,
        "unpriced_entitlement_sessions": unknown_claims,
        "independent_raw_valuation_and_missing_states": True,
        "independently_recomputed_parity_sha256": parity_sha,
        "final_paper_state_sha256": sha256(state_path.read_bytes()).hexdigest(),
        "raw_prices_and_fees": True,
        "independent_cash_shares_basis_entitlements": True,
        "current_model_parity_sha256": sha256(
            (root / "installed-parity.json").read_bytes()
        ).hexdigest(),
        "actual_verified_at": datetime.now(UTC).isoformat(),
        "real_orders": False,
        "historically_available_models": False,
        "investment_quality_verified": False,
    }
    stocks = project(root, result)
    result["projected_stocks"] = len(stocks)
    result["projected_decisions"] = sum(
        len(stock["decisions"]) for stock in stocks.values()
    )
    save(output, result)
    return result


# Verify an explicit completed private account without changing its receipts or source.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--market", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(verify(args.market, args.account, args.output)))


if __name__ == "__main__":
    main()
