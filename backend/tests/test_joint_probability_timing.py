"""Private funded journeys joining risk sizing to causal intraday decisions."""

from datetime import datetime, timedelta

import numpy as np
import pytest

from backend.agents.trading.desk import intraday_orders, paper
from backend.cli import market_daily
from backend.market import calendar, entry_timing
from backend.market import direct_feature_arithmetic as feature
from backend.market import probabilistic_execution as timing_model
from backend.market import probabilistic_execution_saved as saved
from backend.market.joint_funded_policy import (
    TIMED_POLICY,
    JointFundedPolicy,
    ProbabilityTimedFundedPolicy,
)
from backend.market.live_policy_replay import run_account
from backend.market.live_probability_timing import build_reader
from backend.market.replay_broker import ReplayBroker
from backend.tests.test_joint_funded_policy import reader as reader
from backend.tests.test_joint_funded_policy import report
from backend.tests.test_live_policy_replay import fixture


# An explicit timing model cannot be silently discarded by next-open sizing orders.
def test_next_open_policy_refuses_unused_intraday_model(reader, tmp_path):
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))

    # Missing synthetic forecasts are intentional and must remain unavailable.
    def unavailable(day, clock, stock):
        return None

    with pytest.raises(ValueError, match="next-open.*intraday"):
        run_account(
            panel,
            raw,
            cubes,
            tmp_path / "account",
            len(reader.dates) - 2,
            len(reader.dates) - 1,
            10,
            holding_policy=JointFundedPolicy(reader, 10),
            reader_builder=build_reader,
            provider=unavailable,
        )
    assert not (tmp_path / "account").exists()


# Restore actual empirical timing artifacts on the original synthetic session grid.
@pytest.fixture(scope="module")
def timing(reader):
    args = {
        "dates": reader.dates,
        "symbols": ("AAA", "SPY", "QQQ"),
        "means": np.full((len(reader.dates), 23, 3), -0.02),
        "valid": np.ones((len(reader.dates), 23, 3), dtype=bool),
        "outcome_end_dates": reader.dates,
        "data_as_of": datetime.combine(
            reader.dates[-1].astype(object),
            calendar.session_close(reader.dates[-1].astype(object)),
            calendar.NEW_YORK,
        ),
        "horizon": timing_model.HORIZON,
    }
    args["means"][:, 0] = 0.02
    args["labels"] = args["means"].copy()
    args["second_moments"] = args["means"] ** 2 + 0.01
    result = timing_model.calibrate(**args)
    return saved.load_saved(
        **args,
        manifest=result.manifest,
        saved_probability=result.probability_positive,
        saved_quantiles=result.quantiles,
    )


# Isolate routing with an explicit scenario oracle, not a claimed trained alpha edge.
def policy(reader, monkeypatch, *, positive=True, cost=10):
    result = ProbabilityTimedFundedPolicy(reader, cost)

    # Feed a known gain or loss to the real optimizer so its desired side is testable.
    def scenarios(day, names):
        return feature.HoldingScenarios(
            np.full((252, len(names)), 0.1 if positive else -0.1),
            np.full(252, 1 / 252),
            names,
            {"status": "available", "synthetic": True},
        )

    monkeypatch.setattr(result.reader, "distribution", scenarios)
    return result


# Keep calendar and blocked-buy dependencies explicit on the real nightly journey.
def features(kind, ignored):
    return (
        {"calendar_known": True, "factor": 1.0}
        if kind == "event"
        else (set(), {})
        if kind == "blocked"
        else {}
    )


# Write actual funded pending intents without submitting ordinary orders overnight.
def planned(root, reader, monkeypatch, *, positive=True, held=None, grades=(3, 0)):
    chosen = policy(reader, monkeypatch, positive=positive)
    current = report(reader, day=len(reader.dates) - 2, grades=grades)
    session = str(current.panel.dates[-1])
    now = datetime.combine(
        current.panel.dates[-1].astype(object),
        calendar.session_close(current.panel.dates[-1].astype(object)),
        calendar.NEW_YORK,
    ) + timedelta(minutes=1)
    broker = ReplayBroker(
        100000.0, 10, initial_holdings=held or {}, initial_average_prices={"AAA": 90}
    )
    broker.observe(now, {"AAA": 100.0, "BBB": 100.0}, False)
    entry = market_daily.paper_trade(
        current,
        root,
        session,
        True,
        client_factory=lambda: broker,
        decision_at=now,
        feature_reader=features,
        holding_policy=chosen,
    )
    return chosen, current, broker, entry, now


# Observe only this completed raw bar and execute the persisted private intents.
def observe(root, reader, timing, broker, *, clock=0, price=98.0, supplied=True):
    session = reader.dates[-1].astype(object)
    now = datetime.combine(
        session, calendar.REGULAR_OPEN, calendar.NEW_YORK
    ) + timedelta(minutes=15 * (clock + 1))
    quotes = {
        "quotes": {
            "AAA": {
                "open": 100.0,
                "last": price,
                "bar": (now - timedelta(minutes=15)).isoformat(),
                "as_of": now.isoformat(),
            }
        }
    }
    broker.observe(now, {"AAA": price}, True)
    entry_timing.update(root, quotes, now)
    state = paper.load_state(root)
    trace = []
    chosen = (
        build_reader(
            timing.provider,
            timing.symbols,
            len(reader.dates) - 1,
            clock,
            session,
            now,
            quotes,
            state.pending,
            broker,
            10,
            trace,
        )
        if supplied
        else None
    )
    lines = intraday_orders.send_due(
        root, quotes, now, lambda: broker, timing_reader=chosen
    )
    return now, trace, paper.load_state(root), lines


# A favorable wait forecast overrides a latched dip, then executes on a flat bar.
def test_real_buy_waits_after_two_percent_dip_then_executes_without_dip(
    reader, timing, tmp_path, monkeypatch, capsys
):
    chosen, _, broker, entry, _ = planned(tmp_path, reader, monkeypatch)
    output = capsys.readouterr().out
    assert "probabilistic timing" in output
    assert "1% under" not in output
    original = paper.load_state(tmp_path).pending
    assert original[0]["qty"] == 250
    assert original[0]["timing_policy"] == chosen.timing_policy
    assert entry["execution_rule"] == chosen.timing_policy
    assert not entry["orders"]
    assert not broker.attempt_history
    _, trace, waiting, lines = observe(tmp_path, reader, timing, broker)
    assert trace[0]["state"] == "wait"
    assert not lines
    assert "sent" not in waiting.pending[0]
    latch = entry_timing.load(tmp_path, reader.dates[-1].astype(object))
    assert latch["symbols"]["AAA"]["buy_trigger"]["price"] == 98
    now, trace, sent, _ = observe(tmp_path, reader, timing, broker, clock=1, price=100)
    assert trace[0]["state"] == "execute"
    assert sent.pending[0]["sent"]["qty"] == original[0]["qty"]
    assert broker.ledger()["holdings"] == {}
    broker.flush(now, {"AAA": 101.0})
    reconciled, settled = market_daily._reconcile(broker, sent, tmp_path, True)
    assert settled
    assert not reconciled.pending
    assert broker.ledger()["holdings"] == {"AAA": 250}
    assert broker.ledger()["cash"] == pytest.approx(100000 - 250 * 101 * 1.001)
    assert paper.load_state(tmp_path).journal == reconciled.journal
    assert paper.load_state(tmp_path).policy_version == TIMED_POLICY


# A discretionary held exit can submit without a pop while its grade remains A+.
def test_real_profit_taking_uses_learned_timing_and_covered_original_quantity(
    reader, timing, tmp_path, monkeypatch
):
    chosen, _, broker, entry, _ = planned(
        tmp_path, reader, monkeypatch, positive=False, held={"AAA": 10}
    )
    before = paper.load_state(tmp_path).pending
    assert before[0]["side"] == "sell"
    assert before[0]["qty"] == 10
    assert before[0]["timing_policy"] == chosen.timing_policy
    assert entry["joint_funded"]["receipt"]["grades"]["AAA"] == 3
    now, trace, sent, _ = observe(tmp_path, reader, timing, broker)
    assert trace[0]["state"] == "execute"
    assert trace[0]["desired_qty"] == trace[0]["observed_qty"] == 10
    assert broker.ledger()["holdings"] == {"AAA": 10}
    broker.flush(now, {"AAA": 97.0})
    _, settled = market_daily._reconcile(broker, sent, tmp_path, True)
    assert settled
    assert broker.ledger()["holdings"] == {}
    assert broker.ledger()["cash"] == pytest.approx(100000 + 10 * 97 * 0.999)


# A missing timing reader cannot fall back to a recorded dip before the final deadline.
def test_persisted_contract_waits_without_reader_then_uses_common_final(
    reader, timing, tmp_path, monkeypatch
):
    _, _, broker, _, _ = planned(tmp_path, reader, monkeypatch)
    _, trace, waiting, lines = observe(tmp_path, reader, timing, broker, supplied=False)
    assert not trace
    assert not lines
    assert "sent" not in waiting.pending[0]
    session = reader.dates[-1].astype(object)
    final = entry_timing.session_clock(session)["final"]
    broker.observe(final, {"AAA": 100.0}, True)
    intraday_orders.send_due(tmp_path, None, final, lambda: broker)
    assert paper.load_state(tmp_path).pending[0]["sent"]["qty"] == 250
    attempted = datetime.fromisoformat(broker.attempt_history[0]["at"])
    assert attempted == final


# Unknown timing contracts cannot downgrade even at the compulsory final clock.
@pytest.mark.parametrize("contract", [None, "wrong-policy", True, {}])
def test_malformed_timing_contract_never_uses_legacy_rule(
    reader, timing, tmp_path, monkeypatch, contract
):
    _, _, broker, _, _ = planned(tmp_path, reader, monkeypatch)
    state = paper.load_state(tmp_path)
    state.pending[0]["timing_policy"] = contract
    paper.save_state(tmp_path, state)
    _, _, waiting, lines = observe(tmp_path, reader, timing, broker, supplied=False)
    assert not lines
    assert "sent" not in waiting.pending[0]
    final = entry_timing.session_clock(reader.dates[-1].astype(object))["final"]
    broker.observe(final, {"AAA": 100.0}, True)
    assert not intraday_orders.send_due(tmp_path, None, final, lambda: broker)
    assert not broker.attempt_history


# Mandatory company exits remain next-open requests rather than discretionary timing.
def test_company_exit_does_not_acquire_intraday_delay(reader, tmp_path, monkeypatch):
    _, _, broker, entry, _ = planned(
        tmp_path, reader, monkeypatch, held={"AAA": 10}, grades=(0, 0)
    )
    state = paper.load_state(tmp_path)
    assert state.pending[0]["execution_timing"] == "next_open"
    assert "timing_policy" not in state.pending[0]
    assert len(entry["orders"]) == 1
    assert entry["execution_rule"] == "next_open"
    opening = datetime.combine(
        reader.dates[-1].astype(object), calendar.REGULAR_OPEN, calendar.NEW_YORK
    )
    broker.observe(opening, {"AAA": 100.0}, True)
    broker.flush(opening, {"AAA": 100.0}, phase="open")
    assert broker.ledger()["holdings"] == {}


# The full replay retains actual forecast decisions and their submitted intent IDs.
def test_chronological_account_connects_quantity_and_timing(
    reader, timing, tmp_path, monkeypatch
):
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    result = run_account(
        panel,
        raw,
        cubes,
        tmp_path / "account",
        len(reader.dates) - 1,
        len(reader.dates) - 1,
        10,
        holding_policy=policy(reader, monkeypatch),
        feature_reader=features,
        reader_builder=build_reader,
        provider=timing.provider,
    )
    assert result["policy"] == TIMED_POLICY
    assert [r["state"] for r in result["forecast_decisions"]] == ["wait", "execute"]
    assert result["attempts"][0]["observed_price"] == 100
    assert result["fills"][0]["requested_qty"] == 250
    assert result["fills"][0]["price"] == 100
    assert (
        result["forecast_decisions"][1]["intent_id"]
        == result["intents"][0]["client_order_id"]
    )
    assert result["adoption_eligible"] is False


# Early closes keep missing bars explicit without inventing a request or proxy fill.
def test_combined_account_uses_actual_early_close_without_invented_fill(
    reader, timing, tmp_path, monkeypatch
):
    early = next(
        day
        for day, value in enumerate(reader.dates)
        if day > 850
        and calendar.session_close(value.astype(object)) != calendar.REGULAR_CLOSE
    )
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    result = run_account(
        panel,
        raw,
        cubes,
        tmp_path / "early",
        early,
        early,
        10,
        holding_policy=policy(reader, monkeypatch),
        feature_reader=features,
        reader_builder=build_reader,
        provider=timing.provider,
    )
    assert not raw.full_session[early]
    assert not result["attempts"]
    assert not result["fills"]
    assert len(result["observations"]) == 13
    observed = datetime.fromisoformat(result["observations"][-1]["at"])
    assert (
        observed
        == entry_timing.session_clock(reader.dates[early].astype(object))["final"]
    )
    assert result["broker"]["cash"] == 100000.0
    assert result["broker"]["holdings"] == {}
    assert all(row["state"] == "unavailable" for row in result["forecast_decisions"])


# Planning and repeated sender calls cannot create another intent or submission.
def test_combined_private_plan_and_submission_are_repeat_safe(
    reader, timing, tmp_path, monkeypatch
):
    chosen, current, broker, _, decision_at = planned(tmp_path, reader, monkeypatch)
    before = paper.load_state(tmp_path)
    market_daily.paper_trade(
        current,
        tmp_path,
        str(current.panel.dates[-1]),
        True,
        client_factory=lambda: broker,
        decision_at=decision_at,
        feature_reader=features,
        holding_policy=chosen,
    )
    assert paper.load_state(tmp_path).pending == before.pending
    assert not broker.attempt_history
    now, _, sent, _ = observe(tmp_path, reader, timing, broker, clock=1, price=100.0)
    assert len(broker.attempt_history) == 1
    assert not intraday_orders.send_due(tmp_path, None, now, lambda: broker)
    assert paper.load_state(tmp_path).pending == sent.pending
    assert len(broker.attempt_history) == 1


# Event reductions bypass ordinary learned planning without acquiring timing contracts.
@pytest.mark.parametrize("known", [False, True])
def test_combined_policy_preserves_event_dispatch(reader, monkeypatch, known):
    from backend.agents.trading.desk import nightly_plan
    from backend.tests.test_nightly_plan import inputs

    chosen = ProbabilityTimedFundedPolicy(reader, 10)

    # Event safety must run without consulting the discretionary risk optimizer.
    def forbidden(*args, **kwargs):
        pytest.fail("Event safety dispatched to ordinary learned planning")

    monkeypatch.setattr(chosen, "plan", forbidden)
    args = inputs()
    args["event_policy"] = {
        "calendar_known": known,
        "factor": 0.5,
        "decision_date": "2026-09-16",
    }
    orders, state, _ = nightly_plan.plan(**args, holding_policy=chosen)
    assert state.policy_version == TIMED_POLICY
    assert all(
        order.execution_timing != intraday_orders.INTRADAY_TIMING for order in orders
    )


# Reject a substituted custom verdict masquerading as the learned timing policy.
def test_required_timing_rejects_substituted_verdict(reader, tmp_path, monkeypatch):
    _, _, broker, _, _ = planned(tmp_path, reader, monkeypatch)
    session = reader.dates[-1].astype(object)
    now = datetime.combine(session, calendar.REGULAR_OPEN, calendar.NEW_YORK)
    now += timedelta(minutes=15)
    broker.observe(now, {"AAA": 98.0}, True)

    # Return a legacy-shaped decision without the required probabilistic identity.
    def legacy(*args):
        return {"send": intraday_orders.MARKET, "timed": {"state": "execute"}}

    with pytest.raises(ValueError, match="explicit ordinary verdict"):
        intraday_orders.send_due(
            tmp_path, None, now, lambda: broker, timing_reader=legacy
        )
    assert not broker.attempt_history


# Missing, substituted or misaligned timing sources fail before any private state write.
@pytest.mark.parametrize(
    "defect", ["missing", "builder", "unverified", "dates", "symbols"]
)
def test_combined_account_requires_original_aligned_timing_artifact(
    reader, timing, tmp_path, monkeypatch, defect
):
    panel, raw, cubes = fixture(tuple(map(str, reader.dates)))
    builder, provider = build_reader, timing.provider
    if defect == "missing":
        builder, provider = None, None
    elif defect == "builder":
        builder = features
    elif defect == "unverified":
        monkeypatch.setitem(timing.verification, "status", "unverified")
    elif defect == "dates":
        monkeypatch.setattr(timing, "dates", timing.dates[:-1])
    else:
        monkeypatch.setattr(timing, "symbols", tuple(reversed(timing.symbols)))
    with pytest.raises(ValueError, match="aligned saved distributions"):
        run_account(
            panel,
            raw,
            cubes,
            tmp_path / "account",
            len(reader.dates) - 1,
            len(reader.dates) - 1,
            10,
            holding_policy=policy(reader, monkeypatch),
            reader_builder=builder,
            provider=provider,
        )
    assert not (tmp_path / "account").exists()
