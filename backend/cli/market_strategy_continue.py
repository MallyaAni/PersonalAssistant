"""Continue only missing counterfactual sessions from a verified carried seed.

Original October artifact publication dates are retained. They are assumed
available earlier only inside this explicitly synthetic, isolated account.
"""

import argparse
import json
from dataclasses import asdict, replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from backend.agents.trading.desk import intraday_orders, paper
from backend.market import (
    calendar,
    entry_timing,
    forward_arithmetic,
    forward_entry_features,
    forward_execution,
    forward_probability_timing,
    holding_risk_bank,
    intraday_sip,
    live_policy_replay,
    live_policy_report,
    live_probability_timing,
)
from backend.market.counterfactual_holding import (
    CounterfactualMarketReader,
    CounterfactualPolicy,
    CounterfactualRiskReader,
)
from backend.market.daily_arithmetic_bridge import _hash
from backend.market.live_execution_inputs import DAILY_BASIS, RawExecutionInputs
from backend.market.panel import build_panel
from backend.market.replay_broker import ReplayBroker
from backend.market.store import MarketStore


# Hash each immutable publication before parsing its bytes.
def read_json(path, digest=None):
    raw = Path(path).read_bytes()
    if digest is not None and sha256(raw).hexdigest() != digest:
        raise ValueError("Counterfactual input bytes differ")
    return json.loads(raw)


# Read dated grades and mechanical share conversions without model prose.
def inputs(market, original, through):
    store = MarketStore(market)
    panel = build_panel(
        store,
        original.symbols,
        "SPY",
        {},
        asof=through,
        start=original.dates[0].astype(object),
    )
    if panel.tickers != tuple(original.symbols):
        raise ValueError("Complete installed model cohort required")
    grades = np.full(panel.close.shape, -1, dtype=np.int16)
    sources, actions = {}, {}
    factors = np.ones(panel.close.shape)
    labels = {"A+": 3, "A": 2, "B": 1, "C": 0}
    for stock, symbol in enumerate(panel.tickers):
        history = store.read(symbol, through)
        if history.complete_through < through:
            raise ValueError("Completed daily observations required for " + symbol)
        path = (
            market
            / "bars"
            / ("asof=" + store.latest_asof(symbol, through).isoformat())
            / (symbol + ".parquet")
        )
        sources[str(path)] = sha256(path.read_bytes()).hexdigest()
        if symbol not in ("SPY", "QQQ"):
            path = market / "history" / (symbol + ".json")
            raw = path.read_bytes()
            sources[str(path)] = sha256(raw).hexdigest()
            history_rows = json.loads(raw)
            if history_rows["asof"] < through.isoformat():
                raise ValueError("Completed grade history required for " + symbol)
            for row in history_rows["rows"]:
                index = np.searchsorted(panel.dates, np.datetime64(row["date"]))
                if index < len(panel.dates) and panel.dates[index] == np.datetime64(
                    row["date"]
                ):
                    grades[index, stock] = labels.get(row.get("grade"), -1)
        actions[symbol] = []
        for action in history.actions:
            if action.kind == "split":
                factors[panel.dates < np.datetime64(action.action_date), stock] *= (
                    action.value
                )
            actions[symbol].append(
                {
                    "date": action.action_date.isoformat(),
                    "kind": action.kind,
                    "value": action.value,
                }
            )
    eligible = grades >= 0
    shape = (len(panel.dates), 25, len(panel.tickers))
    observed, following = np.full(shape, np.nan), np.full(shape, np.nan)
    opened = np.full(panel.close.shape, np.nan)
    present = np.zeros(panel.close.shape, dtype=bool)
    complete = np.ones(len(panel.dates), dtype=bool)
    cubes = {}
    return (
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
        cubes,
    )


# Score a past bar prefix under the explicit model-availability assumption.
def timing_reader(
    panel,
    raw,
    records,
    models,
    residuals,
    config,
    actual_now,
    day,
    clock,
    now,
    live,
    pending,
    broker,
    trace,
):
    prior = SimpleNamespace(
        dates=panel.dates[:day], tickers=panel.tickers, adj_close=panel.adj_close[:day]
    )
    prefixes = {}
    for name, regular in records.items():
        if len(regular) <= clock:
            continue
        bars = regular[: clock + 1]
        stock = panel.index(name)
        prefixes[name] = {
            "starts": [bar.start.isoformat() for bar in bars],
            "published_at": now.isoformat(),
            "prior_close": raw.daily_close[day - 1, stock],
            **{
                field: np.asarray([getattr(bar, field) for bar in bars])
                for field in ("open", "high", "low", "close", "volume")
            },
        }
    frame = forward_entry_features.observe(
        prior,
        raw.grades[:day],
        raw.eligible[:day],
        prefixes,
        observed_at=now,
        daily_as_of=live_policy_replay.instant(
            panel.dates[day - 1],
            calendar.session_close(panel.dates[day - 1].astype(object)),
        )
        + timedelta(minutes=1),
    )
    distributions = forward_execution.current_distributions(
        models,
        config["model_receipt_sha256"],
        residuals,
        symbols=panel.tickers,
        values=frame["features"],
        valid=frame["valid"],
        observed_at=actual_now,
        timing_supported=frame["timing_supported"],
    )

    # Resolve frozen forecasts without sending outcome prices to the models.
    def provider(_day, _clock, stock):
        return distributions[panel.tickers[stock]]

    return live_probability_timing.build_reader(
        provider,
        panel.tickers,
        day,
        clock,
        panel.dates[day].astype(object),
        now,
        live,
        pending,
        broker,
        config["cost_bps"],
        trace,
    )


# Read complete raw sessions without substituting daily prices for missing bars.
def _session_bars(market, panel, day, raw, sources):
    session = panel.dates[day].astype(object)
    records, auctions = {}, {}
    for stock, name in enumerate(panel.tickers):
        found = intraday_sip.read_session_full(MarketStore(market), name, session)
        if found is None:
            raw.full_session[day] = False
            continue
        regular, auction, meta = found
        path = (
            market
            / "bars_15m_sip"
            / ("asof=" + session.isoformat())
            / (name + ".parquet")
        )
        sources[str(path)] = sha256(path.read_bytes()).hexdigest()
        if meta.get("complete") != "true":
            raw.full_session[day] = False
            continue
        records[name] = regular
        raw.cube_present[day, stock] = True
        raw.session_open[day, stock] = regular[0].open
        for slot in range(min(25, len(regular) - 1)):
            raw.observation_close[day, slot, stock] = regular[slot].close
            raw.next_open[day, slot, stock] = regular[slot + 1].open
        auctions[name] = auction.open if auction is not None else None
    return records, auctions


# Bind this close's report to its prefix while retaining the full input receipt.
def close_report(panel, raw, grades, eligible, report_day):
    report = live_policy_report.build(panel, raw, grades, eligible, report_day)
    metadata = dict(report.provenance)
    metadata["full_source_arrays"] = metadata["raw_source_arrays"]
    metadata["raw_source_arrays"] = {
        field: _hash(getattr(panel, field)[: report_day + 1])
        for field in ("dates", "open", "high", "low", "close", "adj_close")
    }
    return replace(report, provenance=metadata)


# Continue an isolated synthetic account through the shared planning and sender.
def run(market, seed_path, seed_sha, output, through):
    market, output = Path(market).resolve(), Path(output).resolve()
    if output.is_relative_to(market) or output.exists():
        raise ValueError("Exclusive output outside the read-only market root required")
    seed = read_json(seed_path, seed_sha)
    if seed["last"] >= through.isoformat() or seed["paper_state"]["pending"]:
        raise ValueError(
            "Unreplayed subsequent sessions and an empty settled pending book required"
        )
    actual_now = datetime.now(UTC)
    holding_path = market / "desk/learned-holding/config.json"
    timing_path = market / "desk/learned-timing/config.json"
    holding_bytes, timing_bytes = holding_path.read_bytes(), timing_path.read_bytes()
    holding, timing = json.loads(holding_bytes), json.loads(timing_bytes)
    if (
        seed["policy"] != holding["policy"]
        or seed["cost_bps"] != holding["cost_bps"]
        or timing["cost_bps"] != seed["cost_bps"]
    ):
        raise ValueError("Unchanged installed strategy and costs required")
    original, risk_receipt = holding_risk_bank.load_bank(
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
        cubes,
    ) = values
    provenance = {
        "daily_price_basis": DAILY_BASIS,
        "supplied": {"seed": seed_sha},
        "grade_sha256": _hash(grades),
        "eligible_sha256": _hash(eligible),
        "daily_source_arrays": {
            field: _hash(getattr(panel, field))
            for field in ("dates", "open", "high", "low", "close", "adj_close")
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
    output.mkdir(mode=0o700, parents=True)
    state_root = output / "state"
    paper.save_state(state_root, paper.PaperState(**seed["paper_state"]))
    broker = ReplayBroker(
        seed["broker"]["cash"],
        seed["cost_bps"],
        initial_holdings=seed["broker"]["holdings"],
        initial_average_prices=seed["broker"]["average_prices"],
    )
    for name in (
        "dividends",
        "security_distributions",
        "security_exchanges",
        "share_consolidations",
        "cash_mergers",
    ):
        if name in seed["broker"]:
            setattr(broker, "_" + name, seed["broker"][name])
    logs, sessions, intents, forecasts, observations = (
        [seed["nightly"]],
        [seed["session"]],
        {},
        [],
        [],
    )
    first = int(np.searchsorted(panel.dates, np.datetime64(seed["last"]), side="right"))
    for day in range(first, len(panel.dates)):
        session = panel.dates[day].astype(object)
        records, auctions = _session_bars(market, panel, day, raw, sources)
        opening = live_policy_replay.instant(panel.dates[day], calendar.REGULAR_OPEN)
        closing = live_policy_replay.instant(
            panel.dates[day], calendar.session_close(session)
        )
        broker.observe(
            opening, live_policy_replay.marks(panel.tickers, opened[day]), True
        )
        live_policy_replay.corporate_actions(broker, raw, day, opening)
        broker.flush(
            opening, live_policy_replay.marks(panel.tickers, opened[day]), phase="open"
        )
        for clock in range(int((closing - opening).total_seconds() // 900) - 1):
            now = opening + timedelta(minutes=15 * (clock + 1))
            live = live_policy_replay.snapshot(raw, day, clock, now)
            broker.observe(
                now, live_policy_replay.marks(panel.tickers, observed[day, clock]), True
            )
            entry_timing.update(state_root, live, now)
            due = intraday_orders.due(paper.load_state(state_root), session)
            reader = (
                timing_reader(
                    panel,
                    raw,
                    records,
                    timing_path.parent / timing["model_directory"],
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
                    state_root, live, now, lambda: broker, timing_reader=reader
                )
                observations.append(
                    {
                        "at": now.isoformat(),
                        "session": session.isoformat(),
                        "sender_logs": lines,
                    }
                )
            broker.flush(
                now, live_policy_replay.marks(panel.tickers, following[day, clock])
            )
        broker.flush(closing, auctions, phase="close")
        close_panel = replace(
            panel,
            **{
                field: getattr(panel, field)[: day + 1]
                for field in (
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
        parent = CounterfactualRiskReader(
            original,
            close_panel,
            grades[: day + 1],
            eligible[: day + 1],
            head,
            model,
            actual_now,
        )
        policy = CounterfactualPolicy(
            CounterfactualMarketReader(parent), holding["cost_bps"]
        )
        status = live_policy_replay.nightly(
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
        sessions.append(
            {
                "session": session.isoformat(),
                "initial": False,
                **live_policy_replay.valuation(broker, raw, day),
                "nightly": status,
            }
        )
        (output / "progress.json").write_text(
            json.dumps(
                {
                    "session": session.isoformat(),
                    "through": through.isoformat(),
                    "actual_observed_at": actual_now.isoformat(),
                }
            )
        )
        del parent, policy
    if (
        holding_path.read_bytes() != holding_bytes
        or timing_path.read_bytes() != timing_bytes
        or any(
            sha256(Path(path).read_bytes()).hexdigest() != digest
            for path, digest in sources.items()
        )
    ):
        raise ValueError("Counterfactual source changed during continuation")
    result = {
        "policy": holding["policy"],
        "cost_bps": holding["cost_bps"],
        "holding_start": seed["holding_start"],
        "first": seed["last"],
        "last": through.isoformat(),
        "initial_cash": seed["initial_cash"],
        "sessions": sessions,
        "nightlies": logs,
        "intents": list(intents.values()),
        "fills": broker.fill_history,
        "attempts": broker.attempt_history,
        "broker": broker.ledger(),
        "paper_state": asdict(paper.load_state(state_root)),
        "forecast_decisions": forecasts,
        "observations": observations,
        "counterfactual": True,
        "base_models_fitted": 0,
        "original_account_replayed": False,
        "assumption": (
            "original installed October artifacts assumed available "
            "at earlier October closes"
        ),
        "seed_sha256": seed_sha,
        "parent_account_sha256": seed["account_sha256"],
        "sources": sources,
        "actual_observed_at": actual_now.isoformat(),
        "original_model_publication": model["identity"]["published_at"],
    }
    from backend.cli.market_actual_policy_timing import archive_account

    digest = archive_account(
        output / "continuation.json.gz", live_policy_replay.plain(result)
    )
    (output / "complete.json").write_text(
        json.dumps(
            {
                "sha256": digest,
                "through": through.isoformat(),
                "real_orders": False,
                "base_models_fitted": 0,
                "market_calibration": "original monthly computation",
                "parent_account_replayed": False,
            },
            indent=2,
        )
    )


# Require explicit seed identity, read-only source root and bounded historical endpoint.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("market", "seed", "seed-sha256", "output", "through"):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    run(
        args.market,
        args.seed,
        args.seed_sha256,
        args.output,
        date.fromisoformat(args.through),
    )


if __name__ == "__main__":
    main()
