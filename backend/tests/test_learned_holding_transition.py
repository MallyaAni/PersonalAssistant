"""Retained holdings must not finance trades or prevent calibrated decisions."""

import json
from copy import deepcopy
from hashlib import sha256

import pytest

from backend.agents.trading.desk import paper
from backend.market import holdings, learned_live_timing
from backend.market import learned_holding_transition as transition
from backend.market import learned_live_holding as runtime
from backend.market.joint_funded_policy import RetainedMarketConditionedFundedPolicy
from backend.tests.test_forward_execution import fitted as fitted
from backend.tests.test_forward_execution import residual_archive as residual_archive
from backend.tests.test_learned_live_holding import example as example
from backend.tests.test_learned_live_holding import install
from backend.tests.test_learned_personal_guidance import personal as personal


# Historical and installed paths must use one holding decision, not parallel copies.
@pytest.mark.parametrize("unsupported", [False, True])
def test_shared_retained_plan_matches_installed_account_decision(
    example, tmp_path, monkeypatch, unsupported
):
    installed, shown, _ = install_transition(tmp_path, example, monkeypatch)
    if unsupported:
        unavailable_holding(installed, monkeypatch)
    historical = RetainedMarketConditionedFundedPolicy(installed.reader, 10)
    prices = {name: float(shown.panel.close[-1, shown.panel.index(name)])
              for name in ("AAA", "BBB")}
    held, cash = {"AAA": 20, "BBB": 30}, 1000
    equity = cash + sum(held[name] * prices[name] for name in held)
    args = (str(shown.panel.dates[-1]), paper.PaperState(), equity, held,
            prices, shown, cash, set())
    actual = historical.plan(*args)
    expected = installed.plan(*args)
    assert actual == expected
    assert historical.decide.__func__ is installed.decide.__func__
    assert not isinstance(historical, runtime.InstalledHoldingPolicy)


# The economic runner and independent verifier must agree on all declared accounts.
def test_retained_policy_has_identical_fixed_funded_and_verifier_grids():
    import numpy as np

    from backend.cli import verify_joint_funded as verifier
    from backend.market.joint_funded_accounts import candidate_grid

    dates = np.arange("2018-01-01", "2026-10-01", dtype="datetime64[D]")
    actual = candidate_grid(dates, policy=transition.POLICY)
    assert actual == verifier.candidate_grid(dates, policy=transition.POLICY)
    assert [(row["cost_bps"], row["start"]) for row in actual] == [
        (0, 0), (10, 0), (25, 0),
    ]
    assert all(row["first_session"] == "2018-02-01" for row in actual)


# Preserve actual shares and derive calibrated capital without anticipated sales.
def test_capital_units_preserve_retained_position_and_reserve_unobserved_wealth():
    capital = transition.partition(
        1000, 100, {"AAA": 2, "BBB": 5}, {"AAA": 100, "BBB": 100}, {"BBB"}
    )
    assert capital.modeled_equity == 300
    assert capital.modeled_holdings == {"AAA": 2}
    assert capital.lift({"AAA": 0.2}) == {"AAA": 0.06, "BBB": 0.5}
    assert capital.retained_weights["BBB"] * 1000 / 100 == 5
    receipt = capital.receipt({"BBB": {"status": "unavailable"}})
    assert receipt["reserved_capital"] == 700
    assert receipt["observed_cash"] == 100
    assert receipt["sale_proceeds_are_funding"] is False


# Retained holdings cannot make full wealth smaller than calibrated wealth.
@pytest.mark.parametrize("unknown_gross", [0, 0.5, 1, 5])
def test_zero_future_value_is_a_lower_bound_not_an_assumed_forecast(unknown_gross):
    capital = transition.partition(
        1000, 200, {"AAA": 1, "BBB": 7}, {"AAA": 100, "BBB": 100}, {"BBB"}
    )
    targets = capital.lift({"AAA": 0.2})
    known_future = 300 * (1 + 0.2 * -0.5)
    full_future = known_future + 700 * unknown_gross
    assert full_future >= known_future
    assert targets["AAA"] * 1000 == 0.2 * capital.modeled_equity


# Missing marks, fractional shares and inconsistent NAV cannot create capital.
@pytest.mark.parametrize(
    ("equity", "cash", "held", "prices"),
    [
        (1000, 100, {"BBB": 0.5}, {"BBB": 100}),
        (1000, 100, {"BBB": 1}, {}),
        (100, 100, {"BBB": 1}, {"BBB": 100}),
        (1000, None, {"BBB": 1}, {"BBB": 100}),
    ],
)
def test_invalid_account_cannot_be_partitioned(equity, cash, held, prices):
    with pytest.raises(
        ValueError, match="whole_share|held_mark|inconsistent_account|account_cash"
    ):
        transition.partition(equity, cash, held, prices, {"BBB"})


# Lifting targets cannot create a modeled addition to an unsupported holding.
def test_retained_target_cannot_be_used_as_a_purchase():
    capital = transition.partition(1000, 900, {"BBB": 1}, {"BBB": 100}, {"BBB"})
    with pytest.raises(ValueError, match="modeled purchase"):
        capital.lift({"BBB": 0.1})


# Use personal cash and positions instead of reproducing paper's unsupported holding.
def test_personal_rebase_preserves_own_retained_and_uncovered_holdings():
    boundary = {"retained_weights": {"BBB": 0.4}, "modeled_fraction": 0.6}
    weights = {"AAA": 0.12, "BBB": 0.4}
    result = transition.personal_weights(
        boundary,
        weights,
        {"AAA": 1, "BBB": 3, "OTHER": 2},
        {"AAA": 100, "BBB": 100, "OTHER": 50},
        1000,
        200,
    )
    assert result == {"AAA": 0.06, "BBB": 0.3, "OTHER": 0.1}
    unheld = transition.personal_weights(boundary, weights, {}, {}, 1000, 1000)
    assert unheld["BBB"] == 0
    assert unheld["AAA"] == pytest.approx(0.2)


# Unconfirmed cash cannot turn provisional model weights into personal trades.
def test_personal_unknown_cash_preserves_current_weights():
    result = transition.personal_weights(
        {"retained_weights": {"BBB": 0.4}, "modeled_fraction": 0.6},
        {"AAA": 0.12, "BBB": 0.4},
        {"AAA": 2},
        {"AAA": 100},
        1000,
        None,
    )
    assert result == {"AAA": 0.2, "BBB": 0}


# Install the named transition with the same original synthetic numeric publications.
def install_transition(root, fixture, monkeypatch, *, company_exit=None):
    shown, now = install(root, fixture, monkeypatch)
    from backend.tests.test_forward_holding import report

    # The parent fixture gives BBB a company exit; this case needs a retained long.
    grades = shown.graded.grades.copy()
    grades[-1, shown.panel.index("BBB")] = 3
    if company_exit is not None:
        grades[-1, shown.panel.index(company_exit)] = 0
    shown = report(shown.panel, grades)
    shown.sides = {"AAA": "long", "BBB": "long"}
    shown.scores = grades.astype(float)
    config_path = root / runtime.CONFIG
    config = json.loads(config_path.read_bytes())
    release_path = config_path.with_name("release.json")
    release = json.loads(release_path.read_bytes())
    config["policy"] = transition.POLICY
    release["policy"] = transition.POLICY
    raw = json.dumps(release).encode()
    release_path.write_bytes(raw)
    config["release_receipt_sha256"] = sha256(raw).hexdigest()
    config_path.write_text(json.dumps(config))
    # The execution fixture checks its original config; only the named selector differs.
    monkeypatch.setattr(
        runtime,
        "_timing",
        lambda *args: (root / runtime.learned_live_timing.CONFIG).read_bytes(),
    )
    return runtime.prepare(root, shown, clock=lambda: now), shown, now


# Keep numeric scenarios unchanged while exposing an explicit missing-history boundary.
def unavailable_holding(policy, monkeypatch, name="BBB"):
    original = policy.reader.distribution

    # Emulate absence of mature errors without inventing forecasts or return scenarios.
    def distribution(day, names):
        sample = original(day, names)
        if name not in names:
            return sample
        receipt = {
            **sample.receipt,
            "status": "unavailable",
            "reason": "insufficient_joint_history",
            "joint_dates": 123,
        }
        return type(sample)(None, None, tuple(names), receipt)

    monkeypatch.setattr(policy.reader, "distribution", distribution)


# The new policy produces exactly the original targets when every holding is calibrated.
def test_fully_calibrated_transition_keeps_original_numeric_targets(
    example, tmp_path, monkeypatch
):
    chosen, shown, now = install_transition(tmp_path, example, monkeypatch)
    original = runtime.InstalledHoldingPolicy(
        chosen.reader,
        chosen.cost_bps,
        tmp_path,
        chosen.config_bytes,
        chosen.admission,
        now,
    )
    prices = {
        name: float(shown.panel.close[-1, shown.panel.index(name)])
        for name in ("AAA", "BBB")
    }
    held = {"AAA": 2}
    equity = 1000 + 2 * prices["AAA"]
    actual, _ = chosen.decide(
        str(shown.panel.dates[-1]), shown, equity, held, prices, 1000, set()
    )
    expected, _ = original.decide(
        str(shown.panel.dates[-1]), shown, equity, held, prices, 1000, set()
    )
    assert actual == expected
    assert chosen.version == transition.POLICY


# Actual funded planning retains unknown shares while allowing a calibrated adjustment.
@pytest.mark.parametrize("cost", [10, 25])
def test_unavailable_holding_does_not_freeze_calibrated_orders(
    example, tmp_path, monkeypatch, cost
):
    chosen, shown, _ = install_transition(tmp_path, example, monkeypatch)
    chosen.cost_bps = cost
    unavailable_holding(chosen, monkeypatch)
    prices = {
        name: float(shown.panel.close[-1, shown.panel.index(name)])
        for name in ("AAA", "BBB")
    }
    held = {"AAA": 20, "BBB": 30}
    cash = 1000
    equity = cash + sum(held[name] * prices[name] for name in held)
    orders, state, _ = chosen.plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        equity,
        held,
        prices,
        shown,
        cash,
        set(),
    )
    receipt = state.allocation_state["receipt"]
    assert receipt["status"] == "available"
    assert receipt["transition"]["modeled_equity"] == cash + held["AAA"] * prices["AAA"]
    assert (
        receipt["transition"]["retained_weights"]["BBB"]
        == held["BBB"] * prices["BBB"] / equity
    )
    assert any(order.symbol == "AAA" for order in orders)
    assert all(order.symbol != "BBB" for order in orders)
    assert receipt["execution"]["projected_liquid_cash"] >= 0
    assert (
        sum(
            order.qty * prices[order.symbol] * (1 + cost / 10000)
            for order in orders
            if order.side == "buy"
        )
        <= cash + 1e-8
    )
    recorded = {
        "session": str(shown.panel.dates[-1]),
        "targets": {"policy": transition.POLICY},
        "paper": {"joint_funded": state.allocation_state},
    }
    assert (
        transition.recorded(recorded)["retained_weights"]
        == receipt["transition"]["retained_weights"]
    )


# A malformed receipt cannot present reserved paper capital as available personal cash.
def test_inconsistent_transition_receipt_is_rejected():
    capital = transition.partition(1000, 500, {"BBB": 5}, {"BBB": 100}, {"BBB"})
    boundary = capital.receipt(
        {
            "BBB": {
                "status": "unavailable",
                "symbols": ["BBB"],
                "decision_date": "2026-10-06",
            }
        }
    )
    record = {
        "session": "2026-10-06",
        "targets": {"policy": transition.POLICY},
        "paper": {"joint_funded": {"receipt": {"transition": boundary}}},
    }
    assert transition.recorded(record)["modeled_equity"] == 500
    changed = deepcopy(record)
    changed["paper"]["joint_funded"]["receipt"]["transition"]["modeled_fraction"] = 1
    with pytest.raises(ValueError, match="accounting"):
        transition.recorded(changed)


# Retaining a different stock must not delay or erase an authenticated company exit.
def test_company_exit_survives_missing_risk_on_another_holding(
    example, tmp_path, monkeypatch
):
    chosen, shown, _ = install_transition(
        tmp_path, example, monkeypatch, company_exit="AAA"
    )
    unavailable_holding(chosen, monkeypatch)
    prices = {
        name: float(shown.panel.close[-1, shown.panel.index(name)])
        for name in ("AAA", "BBB")
    }
    held = {"AAA": 20, "BBB": 30}
    equity = 1000 + sum(held[name] * prices[name] for name in held)
    orders, state, _ = chosen.plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        equity,
        held,
        prices,
        shown,
        1000,
        set(),
    )
    assert [(o.symbol, o.side, o.qty, o.execution_timing) for o in orders] == [
        ("AAA", "sell", 20, "next_open")
    ]
    assert state.allocation_state["receipt"]["company_exits"] == ["AAA"]
    assert set(state.allocation_state["receipt"]["transition"]["retained_weights"]) == {
        "BBB"
    }


# With no calibrated capital, retain actual shares instead of manufacturing funded buys.
def test_zero_calibrated_capital_preserves_all_shares(example, tmp_path, monkeypatch):
    chosen, shown, _ = install_transition(tmp_path, example, monkeypatch)
    unavailable_holding(chosen, monkeypatch)
    prices = {"BBB": float(shown.panel.close[-1, shown.panel.index("BBB")])}
    orders, state, _ = chosen.plan(
        str(shown.panel.dates[-1]),
        paper.PaperState(),
        30 * prices["BBB"],
        {"BBB": 30},
        prices,
        shown,
        0,
        set(),
    )
    assert orders == []
    assert state.allocation_state["targets"] == {"BBB": 1}
    assert state.allocation_state["receipt"]["reason"] == "no_calibrated_capital"


# Individual support cannot substitute for simultaneous scenario support.
def test_transition_never_bypasses_insufficient_joint_support(
    example, tmp_path, monkeypatch
):
    chosen, shown, _ = install_transition(tmp_path, example, monkeypatch)
    original = chosen.reader.distribution

    # Refuse only the joint book while retaining genuine supported individual scenarios.
    def distribution(day, names):
        sample = original(day, names)
        if len(names) < 2:
            return sample
        return type(sample)(
            None,
            None,
            tuple(names),
            {
                **sample.receipt,
                "status": "unavailable",
                "reason": "insufficient_joint_history",
            },
        )

    monkeypatch.setattr(chosen.reader, "distribution", distribution)
    prices = {
        name: float(shown.panel.close[-1, shown.panel.index(name)])
        for name in ("AAA", "BBB")
    }
    equity = 1000 + sum(prices.values())
    targets, receipt = chosen.decide(
        str(shown.panel.dates[-1]),
        shown,
        equity,
        {"AAA": 1, "BBB": 1},
        prices,
        1000,
        set(),
    )
    assert receipt["status"] == "unavailable"
    assert receipt["reason"] == "joint_risk_unavailable"
    assert "transition" not in receipt
    assert targets == {name: price / equity for name, price in prices.items()}


# Bind the selector to private fixture approval without changing numeric heads.
def approve_personal_transition(root, record):
    config_path = root / runtime.CONFIG
    config = json.loads(config_path.read_bytes())
    release_path = config_path.with_name("release.json")
    release = json.loads(release_path.read_bytes())
    config["policy"] = release["policy"] = transition.POLICY
    raw = json.dumps(release).encode()
    release_path.write_bytes(raw)
    config["release_receipt_sha256"] = sha256(raw).hexdigest()
    raw_config = json.dumps(config).encode()
    config_path.write_bytes(raw_config)
    record["targets"] = {
        "policy": transition.POLICY,
        "weights": {"AAOI": 0.05, "QQQ": 0.3},
    }
    record["paper"].update(
        policy=transition.POLICY, selected_targets=deepcopy(record["targets"])
    )
    record["paper"]["learned_holding"]["config_sha256"] = sha256(raw_config).hexdigest()
    capital = transition.partition(10000, 7000, {"QQQ": 30}, {"QQQ": 100}, {"QQQ"})
    record["paper"]["joint_funded"] = {
        "receipt": {
            "status": "available",
            "transition": capital.receipt(
                {
                    "QQQ": {
                        "status": "unavailable",
                        "symbols": ["QQQ"],
                        "decision_date": record["session"],
                    }
                }
            ),
        }
    }


# The real personal/timing path never copies paper's retained holding into a purchase.
@pytest.mark.parametrize("owns_retained", [True, False])
def test_personal_transition_uses_own_positions_and_real_timing(
    personal, owns_retained
):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    held = [holdings.Holding("QQQ", 30, 100, "2026-10-01")] if owns_retained else []
    before = deepcopy(record)
    result = run(held=held, cash=7000)
    assert result["policy"] == transition.POLICY
    assert result["rows"]["AAOI"]["action"] == "Buy", result
    assert (
        result["rows"]["AAOI"]["learned_timing"]["policy"] == learned_live_timing.POLICY
    )
    row = result["rows"]["QQQ"]
    assert row["action"] == "Hold"
    assert row["target_weight"] == (0.297 if owns_retained else 0)
    assert row["blocker"] == "Risk history unavailable"
    assert result["rows"]["AAOI"]["move_weight"] * 10000 * 1.001 <= 7000
    assert record == before
    assert len(seen) == 3
    assert not (root / "paper" / "state.json").exists()
    from backend.market import personal_history

    receipt = personal_history.project(result, record, {"quotes": {}}, {})
    assert receipt["policy_version"] == transition.POLICY
    assert receipt["decision_policy"] == transition.POLICY


# Unconfirmed personal cash preserves quantities and never borrows paper's budget.
def test_personal_transition_unknown_cash_does_not_trigger_trades(personal):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], cash=None)
    assert result["rows"]["AAOI"]["action"] == "Hold"
    assert result["rows"]["AAOI"]["target_weight"] == 0.099
    assert result["rows"]["QQQ"]["target_weight"] == 0
    assert seen == []


# Missing cash must not prevent an authenticated company exit from the owned account.
def test_personal_transition_unknown_cash_preserves_company_exit(personal):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    record["grades"]["AAOI"]["grade"] = "C"
    record["targets"]["weights"]["AAOI"] = 0
    record["paper"]["selected_targets"] = deepcopy(record["targets"])
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], cash=None)
    row = result["rows"]["AAOI"]
    assert row["action"] == "Sell", row
    assert row["target_weight"] == 0
    assert row["planned_qty"] == 10
    assert row["reason"] == "Company exit"
    assert seen == []


# The real nightly recorder carries the named targets instead of the legacy policy.
def test_nightly_record_accepts_exact_transition_weights(
    example, tmp_path, monkeypatch
):
    from backend.cli import market_daily

    chosen, shown, _ = install_transition(tmp_path, example, monkeypatch)
    weights = {
        name: 0.0 for name in shown.panel.tickers if name != shown.panel.benchmark
    }
    weights.update(AAA=0.05, BBB=0.7)
    selected = {"policy": chosen.version, "weights": weights}
    result = market_daily._record_targets(
        shown, {"policy": chosen.version, "selected_targets": selected}
    )
    assert result == selected


# The real nightly broker boundary accepts only the explicitly installed paper policy.
@pytest.mark.parametrize("endpoint", ["paper", "live", "replay"])
def test_transition_admission_uses_original_paper_endpoint_guard(
    example, tmp_path, monkeypatch, endpoint
):
    from backend.cli import market_daily
    from backend.market import alpaca_trading
    from backend.market.replay_broker import ReplayBroker

    chosen, _, now = install_transition(tmp_path, example, monkeypatch)
    calls = []

    # Supply the actual typed client clock while prohibiting every account mutation.
    def transport(method, url, headers, body):
        assert method == "GET"
        assert body is None
        assert url == alpaca_trading.PAPER_URL + "/clock"
        calls.append(url)
        return 200, json.dumps({"timestamp": now.isoformat()}).encode()

    client = (
        ReplayBroker(100000, 10)
        if endpoint == "replay"
        else alpaca_trading.AlpacaTradingClient(
            "fixture",
            "fixture",
            transport=transport,
            base_url=alpaca_trading.PAPER_URL
            if endpoint == "paper"
            else "https://api.alpaca.markets/v2",
        )
    )
    if endpoint == "paper":
        market_daily._holding_broker(chosen, client, now)
        assert calls == [alpaca_trading.PAPER_URL + "/clock"]
    else:
        with pytest.raises(ValueError, match="paper endpoint"):
            market_daily._holding_broker(chosen, client, now)
        assert calls == []


# Personal risk exclusions preserve shares even when paper has no position.
def test_personal_owned_unqualified_stock_does_not_inherit_paper_zero_target(personal):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    record["targets"]["weights"]["AAOI"] = 0
    record["paper"]["selected_targets"] = deepcopy(record["targets"])
    record["paper"]["joint_funded"]["receipt"].update(
        status="available",
        entry_qualification={
            "excluded_entries": {
                "AAOI": {
                    "reason": "entry_risk_unavailable",
                    "risk": {
                        "status": "unavailable",
                        "symbols": ["AAOI"],
                        "decision_date": record["session"],
                        "joint_dates": 123,
                    },
                }
            }
        },
    )
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], price=150)
    row = result["rows"]["AAOI"]
    assert row["action"] == "Hold", row
    assert row["target_weight"] == 0.15
    assert row["blocker"] == "Risk history unavailable"
    assert seen == []


# An unavailable optimizer cannot turn paper weights into personal trades.
def test_personal_unavailable_joint_allocation_preserves_own_book(personal):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    record["paper"]["joint_funded"]["receipt"]["status"] = "unavailable"
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], price=150)
    row = result["rows"]["AAOI"]
    assert row["action"] == "Hold", row
    assert row["target_weight"] == 0.15
    assert row["blocker"] == "Learned allocation unavailable"
    assert seen == []


# An allocation refusal or event-priority record never suppresses a company C exit.
@pytest.mark.parametrize("status", ["unavailable", "event_priority"])
def test_personal_company_exit_survives_unavailable_allocation(personal, status):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    record["grades"]["AAOI"]["grade"] = "C"
    record["targets"]["weights"]["AAOI"] = 0
    if status == "event_priority":
        record["targets"]["weights"]["QQQ"] = 0
        record["paper"]["joint_funded"] = {
            "policy": transition.POLICY,
            "status": status,
        }
    else:
        record["paper"]["joint_funded"]["receipt"]["status"] = status
    record["paper"]["selected_targets"] = deepcopy(record["targets"])
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], price=150)
    row = result["rows"]["AAOI"]
    assert row["action"] == "Sell", row
    assert row["planned_qty"] == 10
    assert row["reason"] == "Company exit"
    assert seen == []


# Wrong-name, stale or malformed risk evidence cannot authorize a personal trade.
@pytest.mark.parametrize("fault", ["symbol", "date", "shape"])
def test_personal_risk_exclusion_requires_dated_original_shape(personal, fault):
    run, record, seen, root = personal
    approve_personal_transition(root, record)
    risk = {
        "status": "unavailable",
        "symbols": ["AAOI"],
        "decision_date": record["session"],
    }
    if fault == "symbol":
        risk["symbols"] = ["OTHER"]
    elif fault == "date":
        risk["decision_date"] = "2026-10-01"
    qualification = {
        "excluded_entries": {"AAOI": {"reason": "entry_risk_unavailable", "risk": risk}}
    }
    if fault == "shape":
        qualification["excluded_entries"] = []
    record["paper"]["joint_funded"]["receipt"]["entry_qualification"] = qualification
    result = run(held=[holdings.Holding("AAOI", 10, 40, "2026-10-01")], price=150)
    assert result["rows"]["AAOI"]["action"] == "Hold"
    assert result["rows"]["AAOI"]["blocker"] == (
        "Recorded stock risk exclusions required"
        if fault == "shape"
        else "Dated unavailable individual stock risk required"
    )
    assert result["rows"]["AAOI"]["move_weight"] == 0
    assert result["rows"]["AAOI"]["executable"] is False
    assert seen == []


# Personal capital reserves uncovered holdings even when paper needs no transition.
@pytest.mark.parametrize("paper_retained", [False, True])
def test_personal_transition_reserves_uncovered_capital_in_both_paper_states(
    personal, paper_retained
):
    from backend.tests.test_forward_market_evidence import NOW

    run, record, _, root = personal
    approve_personal_transition(root, record)
    if not paper_retained:
        record["paper"]["joint_funded"]["receipt"].pop("transition")
        record["targets"]["weights"]["QQQ"] = 0
        record["paper"]["selected_targets"] = deepcopy(record["targets"])
    result = run(
        held=[holdings.Holding("OTHER", 20, 40, "2026-10-01")],
        cash=7000,
        extra_quotes={
            "OTHER": {
                "bp": 98.995,
                "ap": 99.005,
                "bs": 100,
                "as": 100,
                "t": NOW.isoformat(),
            }
        },
    )
    assert result["rows"]["AAOI"]["target_weight"] == pytest.approx(
        0.05 if paper_retained else 0.035
    )
    assert result["rows"]["AAOI"]["action"] == "Buy", result
    assert result["rows"]["OTHER"]["action"] == "Hold"
    assert result["rows"]["OTHER"]["target_weight"] == 0.198
    assert result["rows"]["OTHER"]["move_weight"] == 0
