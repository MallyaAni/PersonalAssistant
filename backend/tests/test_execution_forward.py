"""Funded forward acceptance; synthetic outcomes do not establish alpha."""

from datetime import date, timedelta
from importlib.util import find_spec
from types import SimpleNamespace

import pytest

from backend.cli.market_execution_forward import initialize
from backend.market import entry_timing
from backend.market import execution_forward as forward
from backend.tests.test_intraday_orders import TODAY, ny


# Supply an explicit pending ordinary order without touching the real paper account.
def order(symbol="AAA", side="buy", qty=10, cid="a"):
    return {
        "symbol": symbol,
        "side": side,
        "qty": qty,
        "client_order_id": cid,
        "execute_on": TODAY.isoformat(),
        "execution_timing": entry_timing.RULE,
    }


# Supply causal regular-session quotes, bars and crossing latches for both arms.
def obs(
    now=None, *, ask=99, bid=98.9, size=100, sell=False, symbols=("AAA", "SPY", "QQQ")
):
    now = now or ny(10, 16)
    quotes, raw, latched = {}, {}, {}
    for s in symbols:
        quotes[s] = {
            "open": 100,
            "last": 98,
            "bar": ny(10).isoformat(),
            "as_of": now.isoformat(),
        }
        raw[s] = {"bp": bid, "ap": ask, "bs": size, "as": size, "t": now.isoformat()}
        latched[s] = {
            "open": 100,
            "buy_trigger": {
                "bar": ny(10).isoformat(),
                "price": 98,
                "seen_at": ny(10, 15).isoformat(),
            },
        }
        if sell:
            latched[s]["sell_trigger"] = {
                "bar": ny(10).isoformat(),
                "price": 102,
                "seen_at": ny(10, 15).isoformat(),
            }
    return forward.observation(
        {"as_of": now.isoformat(), "quotes": quotes},
        {"session": TODAY.isoformat(), "symbols": latched},
        {
            "feed": "sip",
            "market_open": True,
            "quotes": raw,
            "fetched_at": now.isoformat(),
        },
        now,
    )


# Create an isolated immutable cohort with an explicit funded starting account.
def cohort(tmp_path, *, cash=1000, holdings=None, rows=None, first=None):
    frozen = forward.manifest(
        rows or [order()],
        forward.account(cash, holdings or {}),
        first or obs(),
        "test-revision",
    )
    forward.exclusive(tmp_path / "manifest.json", frozen)
    return frozen


# Read exact cash debits, holdings and fees from both real decision arms.
def test_funded_cash_bounds_and_fees(tmp_path):
    cohort(tmp_path)
    result = forward.compare(tmp_path)
    assert result["adoption_eligible"] is False
    assert {r["cost_bps"] for r in result["results"]} == {10, 25}
    for r in result["results"]:
        assert r["book"]["holdings"] == {"AAA": 10}
        expected_fee = 990 * r["cost_bps"] / 10000
        assert r["book"]["cash"] == pytest.approx(10 - expected_fee)
        assert r["book"]["fees"] == pytest.approx(expected_fee)
        assert r["opportunities"]["a"]["filled_qty"] == 10
        assert r["total_gain"] == pytest.approx(-1 - expected_fee)
        assert r["benchmarks"]["SPY"]["ending_reference_value"] is not None
        assert "cagr" not in r
        assert "sharpe" not in r


# Retain a recovered dip while forbidding the bounded arm from chasing it.
def test_recovery_is_not_current_entry_permission(tmp_path):
    cohort(tmp_path, cash=1200, first=obs(ask=110, bid=109.9))
    results = forward.compare(tmp_path)["results"]
    legacy, bounded = results[:2]
    assert legacy["book"]["holdings"]["AAA"] == 10
    assert bounded["book"]["holdings"] == {}
    assert bounded["opportunities"]["a"]["status"] == "never_attempted"
    assert (
        "Current price is outside the execution bound"
        in bounded["opportunities"]["a"]["blocked"]
    )


# Distinguish immediate full exits from ordinary trims without shorting the account.
def test_full_exit_does_not_wait_for_pop(tmp_path):
    first = obs(ask=99, bid=98.9)
    frozen = cohort(
        tmp_path,
        cash=0,
        holdings={"AAA": 4},
        rows=[order(side="sell", qty=5)],
        first=first,
    )
    assert frozen["opportunities"][0]["intent"] == "exit"
    legacy, bounded = forward.compare(tmp_path)["results"][:2]
    assert legacy["book"]["holdings"]["AAA"] == 4
    assert bounded["book"]["holdings"]["AAA"] == 0
    assert bounded["opportunities"]["a"]["filled_qty"] == 4
    assert bounded["opportunities"]["a"]["unfilled_qty"] == 1
    assert bounded["book"]["cash"] == pytest.approx(4 * 98.9 * 0.999)


# Preserve the trim wait even when an ordinary exit could be sent immediately.
def test_trim_still_waits_and_missing_anchor_is_retained(tmp_path):
    frozen = cohort(
        tmp_path, cash=0, holdings={"AAA": 5}, rows=[order(side="sell", qty=2)]
    )
    assert frozen["opportunities"][0]["intent"] == "trim"
    assert all(
        r["book"]["holdings"]["AAA"] == 5 for r in forward.compare(tmp_path)["results"]
    )


# Conserve displayed liquidity across two orders and never replenish a repeated event.
def test_shared_liquidity_and_partial_attempts_are_terminal(tmp_path):
    cohort(
        tmp_path,
        cash=3000,
        rows=[order(qty=4), order(qty=4, cid="b")],
        first=obs(size=5),
    )
    forward.append(tmp_path, obs(ny(10, 17), size=5))
    result = forward.compare(tmp_path)
    for r in result["results"]:
        assert r["book"]["holdings"]["AAA"] == 5
        assert r["opportunities"]["a"]["status"] == "filled"
        assert r["opportunities"]["b"]["status"] == "partial"
        assert r["opportunities"]["b"]["filled_qty"] == 1


# Sale proceeds from the same observation do not fabricate buying power.
def test_same_observation_sales_cannot_fund_buys(tmp_path):
    cohort(
        tmp_path,
        cash=0,
        holdings={"AAA": 2},
        rows=[order(side="sell", qty=2), order("BBB", qty=1, cid="b")],
        first=obs(sell=True, symbols=("AAA", "BBB", "SPY", "QQQ")),
    )
    for r in forward.compare(tmp_path)["results"]:
        assert r["opportunities"]["b"]["filled_qty"] == 0
        assert r["book"]["cash"] > 0
        assert r["book"]["holdings"].get("BBB", 0) == 0


# Missing starting holdings marks and benchmark quotes remain explicitly unavailable.
def test_missing_marks_and_benchmarks_do_not_become_zero_returns(tmp_path):
    cohort(tmp_path, holdings={"MISSING": 3}, first=obs(symbols=("AAA",)))
    result = forward.compare(tmp_path)
    assert result["missing_starting_marks"] == ["MISSING"]
    for r in result["results"]:
        assert r["total_return"] is None
        assert r["max_drawdown_loss"] is None
        assert r["benchmarks"]["QQQ"]["excess_gain"] is None


# Capture chain alteration, skipped observations and attempts to replace frozen bytes.
def test_chain_is_exclusive_ordered_and_tamper_evident(tmp_path):
    cohort(tmp_path)
    with pytest.raises(FileExistsError):
        forward.exclusive(tmp_path / "manifest.json", {})
    with pytest.raises(ValueError, match="advance"):
        forward.append(tmp_path, obs())
    row = forward.append(tmp_path, obs(ny(10, 17)))
    row["previous"] = "bad"
    (tmp_path / "00000001.json").write_bytes(forward.encoded(row))
    with pytest.raises(ValueError, match="altered"):
        forward.compare(tmp_path)


# A future quote or receipt cannot authorize either arm or a valuation mark.
@pytest.mark.parametrize("key", ["timestamp", "received_at"])
def test_future_quote_is_not_executable(tmp_path, key):
    first = obs()
    first["snapshot"]["quotes"]["AAA"]["execution_quote"][key] = ny(11).isoformat()
    cohort(tmp_path, first=first)
    assert all(
        r["book"]["holdings"] == {} for r in forward.compare(tmp_path)["results"]
    )


# Repeating a source event with changed prices must fail rather than add liquidity.
def test_conflicting_quote_event_is_refused(tmp_path):
    cohort(tmp_path)
    later = obs(ny(10, 16) + timedelta(seconds=10))
    later["snapshot"]["quotes"]["AAA"]["execution_quote"].update(
        timestamp=ny(10, 16).isoformat(), ask=99.01
    )
    forward.append(tmp_path, later)
    with pytest.raises(ValueError, match="Conflicting"):
        forward.compare(tmp_path)


# Unknown cash, fractional shares and invalid plan identities cannot be fabricated.
@pytest.mark.parametrize("value", [-1, float("inf"), True])
def test_invalid_starting_cash_is_refused(value):
    with pytest.raises(ValueError, match="account|cash"):
        forward.account(value, {})


# Capture the real initialization workflow through a client exposing reads only.
def test_initializer_reads_and_preserves_source_files(tmp_path):
    root, out = tmp_path / "source", tmp_path / "research"
    (root / "paper").mkdir(parents=True)
    (root / "desk").mkdir()
    state_path = root / "paper/state.json"
    live_path = root / "desk/live.json"
    state_path.write_bytes(forward.encoded({"pending": [order()]}))
    live_path.write_bytes(forward.encoded(obs()["snapshot"]))
    originals = (state_path.read_bytes(), live_path.read_bytes())
    client = SimpleNamespace(
        account=lambda: SimpleNamespace(cash=1000), positions=lambda: []
    )
    frozen = initialize(
        root,
        out,
        "test",
        client=client,
        reader=lambda _: obs()["packet"],
        clock=lambda: ny(10, 16),
    )
    assert len(frozen["opportunities"]) == 1
    assert originals == (state_path.read_bytes(), live_path.read_bytes())
    assert forward.load(out)[0]["starting"]["cash"] == 1000
    with pytest.raises(ValueError, match="outside"):
        initialize(root, root / "research", "test", client=client)


# An account that changes during initialization cannot masquerade as a common start.
def test_initializer_refuses_inconsistent_account(tmp_path):
    root = tmp_path / "source"
    (root / "paper").mkdir(parents=True)
    (root / "desk").mkdir()
    (root / "paper/state.json").write_bytes(forward.encoded({"pending": [order()]}))
    (root / "desk/live.json").write_bytes(forward.encoded(obs()["snapshot"]))
    calls = iter([1000, 900])
    client = SimpleNamespace(
        account=lambda: SimpleNamespace(cash=next(calls)), positions=lambda: []
    )
    with pytest.raises(ValueError, match="changed"):
        initialize(
            root,
            tmp_path / "research",
            "test",
            client=client,
            reader=lambda _: obs()["packet"],
            clock=lambda: ny(10, 16),
        )
    assert not (tmp_path / "research").exists()


# Old recorded crossings expire for the candidate even when a fresh quote is available.
def test_trigger_age_cannot_be_renewed_by_a_new_quote(tmp_path):
    first = obs()
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    cohort(tmp_path, first=first)
    forward.append(tmp_path, obs(ny(10, 40)))
    legacy, candidate = forward.compare(tmp_path)["results"][:2]
    assert legacy["book"]["holdings"]["AAA"] == 10
    assert candidate["book"]["holdings"] == {}
    assert (
        "Earlier trigger is no longer actionable"
        in candidate["opportunities"]["a"]["blocked"]
    )


# Missing initial bounds stay in both denominators instead of selecting easy trades.
def test_missing_bound_remains_an_unavailable_opportunity(tmp_path):
    first = obs()
    first["latch"]["symbols"]["AAA"] = {}
    first["snapshot"]["quotes"]["AAA"] = {}
    frozen = cohort(tmp_path, first=first)
    assert len(frozen["opportunities"]) == 1
    assert frozen["opportunities"][0]["unavailable"]
    for r in forward.compare(tmp_path)["results"]:
        assert len(r["opportunities"]) == 1
        assert r["opportunities"]["a"]["filled_qty"] == 0


# Unsupported auction evidence cannot manufacture a favorable closing fill.
def test_incumbent_moc_is_explicitly_unsupported(tmp_path):
    first = obs(ny(15, 35))
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    cohort(tmp_path, first=first)
    incumbent = forward.compare(tmp_path)["results"][0]
    assert "Closing auction unsupported" in incumbent["opportunities"]["a"]["blocked"]
    assert incumbent["opportunities"]["a"]["filled_qty"] == 0


# Calendar boundaries reject weekends and the already closed early-close session.
@pytest.mark.parametrize(
    "moment", [ny(10, day=date(2026, 10, 3)), ny(13, day=date(2026, 11, 27))]
)
def test_cohort_refuses_closed_session(moment):
    with pytest.raises(ValueError, match="regular session"):
        forward.manifest([order()], forward.account(1000, {}), obs(moment), "test")


# Future source snapshots remain recorded but cannot authorize either decision arm.
def test_future_snapshot_is_not_a_causal_signal(tmp_path):
    first = obs()
    first["snapshot"]["as_of"] = ny(11).isoformat()
    first["timing_available"] = False
    cohort(tmp_path, first=first)
    for r in forward.compare(tmp_path)["results"]:
        assert r["book"]["holdings"] == {}
        assert (
            "Source snapshot time unavailable or future-dated"
            in r["opportunities"]["a"]["blocked"]
        )


# Distinct older source events cannot replenish a book after a newer quote.
def test_out_of_order_quote_events_are_refused(tmp_path):
    first_time = ny(10, 16) + timedelta(seconds=10)
    cohort(tmp_path, first=obs(first_time))
    later = obs(first_time + timedelta(seconds=10))
    later["snapshot"]["quotes"]["AAA"]["execution_quote"]["timestamp"] = ny(
        10, 16
    ).isoformat()
    forward.append(tmp_path, later)
    with pytest.raises(ValueError, match="out of order"):
        forward.compare(tmp_path)


# Later prices can change marks but cannot rewrite an earlier attempted quantity or fee.
def test_future_prefix_keeps_execution_identity(tmp_path):
    cohort(tmp_path)
    before = forward.compare(tmp_path)["results"]
    forward.append(tmp_path, obs(ny(10, 17), ask=120, bid=119.9))
    after = forward.compare(tmp_path)["results"]
    for old, new in zip(before, after, strict=True):
        assert old["opportunities"] == new["opportunities"]
        assert old["book"] == new["book"]
        assert new["total_gain"] > old["total_gain"]


# Match cash and fee accounting against the independent pinned native engine.
@pytest.mark.skipif(
    find_spec("nautilus_trader") is None, reason="Pinned native engine required"
)
@pytest.mark.parametrize("cost", [10, 25])
@pytest.mark.parametrize("mode", ["incumbent", "bounded"])
def test_flat_funding_matches_native_engine(tmp_path, cost, mode):
    from backend.market import open_source_execution as native

    frozen = cohort(tmp_path, cash=950)
    first = frozen["first"]
    row = frozen["opportunities"][0]["order"]
    candle = first["snapshot"]["quotes"]["AAA"]
    payload = {
        "schema": native.SCHEMA,
        "session": TODAY.isoformat(),
        "price_basis": "raw",
        "quantity_unit": "shares",
        "starting_cash": 950,
        "cost_bps": cost,
        "legacy_quote_age_seconds": forward.AGE,
        "opportunities": [
            {
                "order": row,
                "observations": [
                    {
                        "observed_at": first["observed_at"],
                        "candle": candle,
                        "latch": first["latch"]["symbols"]["AAA"],
                        "execution_quote": candle["execution_quote"],
                    }
                ],
            }
        ],
    }
    reference = native.run(payload, mode=mode)
    result = forward.replay(frozen, [first], mode, cost)
    assert result["book"]["cash"] == pytest.approx(reference["ending_cash"])
    assert result["book"]["holdings"]["AAA"] == reference["ending_holdings"]["AAA"]
    assert result["marks"][-1]["equity"] == pytest.approx(
        reference["ending_bid_marked_equity"]
    )
