"""Native-engine acceptance; synthetic evidence does not establish profitability."""

from copy import deepcopy
from datetime import timedelta
from importlib.util import find_spec

import pytest

from backend.market import open_source_execution as execution
from backend.tests.test_bounded_execution import candidate, snapshot
from backend.tests.test_intraday_orders import ny

NATIVE = pytest.mark.skipif(
    find_spec("nautilus_trader") is None,
    reason="Pinned optional native engine required",
)


# Retain the same causal synthetic opportunity input for both policy arms.
def packet(*, cash=1000, cost=0, observations=None, orders=None):
    evidence = {
        "observed_at": ny(10, 16).isoformat(),
        "candle": snapshot()["quotes"]["AAA"],
        "execution_quote": snapshot()["quotes"]["AAA"]["execution_quote"],
    }
    return {
        "schema": execution.SCHEMA,
        "price_basis": "raw",
        "quantity_unit": "shares",
        "session": candidate()["execute_on"],
        "starting_cash": cash,
        "cost_bps": cost,
        "legacy_quote_age_seconds": 10,
        "opportunities": orders
        or [
            {
                "order": candidate(),
                "observations": observations
                if observations is not None
                else [evidence],
            }
        ],
    }


# Require aware ordered evidence and unchanged identity before fitting either arm.
def test_prepare_rejects_future_and_duplicate_evidence():
    data = packet()
    obs = data["opportunities"][0]["observations"][0]
    obs["latch"] = {
        "buy_trigger": {"bar": ny(10).isoformat(), "seen_at": ny(11).isoformat()}
    }
    with pytest.raises(ValueError, match="future"):
        execution.prepare(data)
    data = packet()
    data["opportunities"].append(deepcopy(data["opportunities"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        execution.prepare(data)


# Refuse nonfinite accounts and unsupported bootstrap holdings.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("starting_cash", float("inf")),
        ("cost_bps", -1),
        ("initial_holdings", {"AAA": 3}),
    ],
)
def test_prepare_refuses_invalid_account(key, value):
    data = packet()
    data[key] = value
    with pytest.raises(ValueError, match="portfolio|Initial holdings"):
        execution.prepare(data)


# Retain empty opportunities without silently removing them from the denominator.
@NATIVE
def test_native_empty_opportunity_has_no_fabricated_outcome():
    result = execution.run(packet(observations=[]), mode="bounded")
    assert result["opportunities"][0]["status"] == "never_attempted"
    assert result["ending_cash"] == 1000
    assert result["ending_holdings"] == {"AAA": 0}


# Refuse ambiguous quote lot sizes and multi-session raw split accounting.
@pytest.mark.parametrize(
    ("key", "value"), [("quantity_unit", "lots"), ("session", "2026-09-29")]
)
def test_prepare_refuses_unsupported_units_or_session(key, value):
    data = packet()
    data[key] = value
    with pytest.raises(ValueError, match="units|Single declared session"):
        execution.prepare(data)


# Keep unsupported precision and fractional size evidence explicitly unavailable.
@NATIVE
@pytest.mark.parametrize(("key", "value"), [("ask_size", 0.5), ("ask", 99.00001)])
def test_native_does_not_round_unsupported_quote_evidence(key, value):
    data = packet()
    data["opportunities"][0]["observations"][0]["execution_quote"][key] = value
    result = execution.run(data, mode="bounded")
    row = result["opportunities"][0]
    assert row["filled_qty"] == 0
    assert row["observations"][0]["missing_evidence"] is not None


# Run actual native fills, cash debits and fee attribution rather than a mock.
@NATIVE
@pytest.mark.parametrize(("cost", "fee"), [(10, 0.99), (25, 2.48)])
def test_native_cash_fill_and_costs(cost, fee):
    data = packet(cost=cost)
    result = execution.run(data, mode="bounded")
    row = result["opportunities"][0]
    assert row["filled_qty"] == 10
    assert row["average_fill_price"] == 99
    assert result["commissions"] == pytest.approx(fee)
    assert result["ending_cash"] == pytest.approx(10 - fee)
    assert result["ending_holdings"] == {"AAA": 10}
    assert result["broker_fill_proof"] is False
    assert result["engine_version"] == execution.ENGINE_VERSION


# Let the native matching engine consume only observed displayed liquidity.
@NATIVE
def test_native_partial_ioc_is_terminal_and_never_retries():
    data = packet()
    observations = data["opportunities"][0]["observations"]
    observations[0]["execution_quote"]["ask_size"] = 2
    later = deepcopy(observations[0])
    later["observed_at"] = ny(10, 17).isoformat()
    later["execution_quote"] = snapshot(ny(10, 17))["quotes"]["AAA"]["execution_quote"]
    observations.append(later)
    result = execution.run(data, mode="bounded")
    row = result["opportunities"][0]
    assert row["status"] == "partial"
    assert row["attempted_qty"] == 10
    assert row["filled_qty"] == 2
    assert result["ending_cash"] == pytest.approx(802)


# Prevent two simultaneous IOC attempts from reusing the same displayed shares.
@NATIVE
def test_native_shared_liquidity_leaves_second_ioc_unfilled():
    data = packet(cash=10000)
    first = data["opportunities"][0]
    first["observations"][0]["execution_quote"]["ask_size"] = 2
    second = deepcopy(first)
    second["order"]["client_order_id"] = "second"
    second["order"]["execution_policy"]["client_order_id"] = "second"
    data["opportunities"].append(second)
    result = execution.run(data, mode="bounded")
    assert sum(row["filled_qty"] for row in result["opportunities"]) == 2
    assert {row["status"] for row in result["opportunities"]} == {"partial", "unfilled"}


# Preserve missed opportunities when quotes are absent or permission has expired.
@NATIVE
@pytest.mark.parametrize(("missing", "late"), [(True, False), (False, True)])
def test_native_missing_and_expired_opportunities_remain(missing, late):
    data = packet()
    obs = data["opportunities"][0]["observations"][0]
    if missing:
        obs["execution_quote"] = None
    if late:
        obs["observed_at"] = ny(15, 55).isoformat()
        obs["execution_quote"] = snapshot(ny(15, 55))["quotes"]["AAA"][
            "execution_quote"
        ]
    result = execution.run(data, mode="bounded")
    assert len(result["opportunities"]) == 1
    assert result["opportunities"][0]["status"] == "never_attempted"
    assert result["ending_cash"] == 1000


# Compare recovered-price entry permission without claiming simulated profit.
@NATIVE
def test_native_rebound_control_and_same_input_hash():
    data = packet()
    obs = data["opportunities"][0]["observations"][0]
    obs["execution_quote"].update(bid=109.9, ask=110)
    result = execution.compare(data)
    assert result["bounded"]["opportunities"][0]["filled_qty"] == 0
    assert result["incumbent"]["opportunities"][0]["filled_qty"] == 9
    assert result["bounded"]["input_sha256"] == result["incumbent"]["input_sha256"]


# Preserve sequential cash and holdings constraints across shared book orders.
@NATIVE
def test_native_cash_shared_and_sell_cannot_short():
    data = packet(cash=150)
    first = data["opportunities"][0]
    second = deepcopy(first)
    second["order"] = candidate()
    second["order"]["client_order_id"] = "second-buy"
    second["order"]["execution_policy"]["client_order_id"] = "second-buy"
    third = deepcopy(first)
    third["order"] = candidate(side="sell", intent="exit")
    third["order"]["client_order_id"] = "third-sell"
    third["order"]["execution_policy"]["client_order_id"] = "third-sell"
    third["observations"][0]["observed_at"] = ny(10, 17).isoformat()
    third["observations"][0]["execution_quote"] = snapshot(ny(10, 17))["quotes"]["AAA"][
        "execution_quote"
    ]
    data["opportunities"] += [second, third]
    result = execution.run(data, mode="bounded")
    assert (
        sum(
            row["filled_qty"] for row in result["opportunities"] if row["side"] == "buy"
        )
        == 1
    )
    assert (
        sum(
            row["filled_qty"]
            for row in result["opportunities"]
            if row["side"] == "sell"
        )
        == 1
    )
    assert result["ending_cash"] == pytest.approx(149.9)
    assert result["ending_holdings"]["AAA"] == 0


# Never replenish a reused quote event or accept conflicting values under its ID.
@NATIVE
def test_native_conflicting_quote_identity_rejected():
    data = packet()
    obs = deepcopy(data["opportunities"][0]["observations"][0])
    obs["observed_at"] = (ny(10, 16) + timedelta(seconds=1)).isoformat()
    obs["execution_quote"]["ask_size"] = 100
    data["opportunities"][0]["observations"].append(obs)
    with pytest.raises(ValueError, match="Conflicting quote"):
        execution.run(data, mode="bounded")


# Never allow a research CLI result to overwrite frozen inputs or prior outcomes.
@pytest.mark.parametrize("same_input", [False, True])
def test_cli_preserves_existing_artifacts(tmp_path, monkeypatch, same_input):
    from backend.cli.market_open_source_execution import main

    source = tmp_path / "input.json"
    source.write_text("frozen input")
    output = source if same_input else tmp_path / "result.json"
    if not same_input:
        output.write_text("frozen outcome")
    before = output.read_bytes()
    monkeypatch.setattr("sys.argv", ["replay", str(source), "--output", str(output)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert output.read_bytes() == before
