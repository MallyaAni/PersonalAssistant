"""Funded forward acceptance; synthetic outcomes do not establish alpha."""

import json
from datetime import date, timedelta
from decimal import Decimal
from importlib.util import find_spec
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from backend.cli.market_execution_forward import initialize, valuate
from backend.market import entry_timing
from backend.market import execution_forward as forward
from backend.market import execution_marks as labels
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
    later = obs(ny(15, 51))
    later["latch"]["symbols"]["AAA"].pop("buy_trigger")
    later["snapshot"]["quotes"]["AAA"]["last"] = 100
    forward.append(tmp_path, later)
    incumbent = forward.compare(tmp_path)["results"][0]
    assert "Closing auction unsupported" in incumbent["opportunities"]["a"]["blocked"]
    assert incumbent["opportunities"]["a"]["filled_qty"] == 0
    assert incumbent["opportunities"]["a"]["status"] == "unsupported_auction"
    assert incumbent["execution_complete"] is False
    assert incumbent["total_gain"] is None
    assert incumbent["total_return"] is None


# A known prior recorder remains readable, while arbitrary changed code is refused.
@pytest.mark.parametrize("approved", [True, False])
def test_recording_code_compatibility_is_exact(tmp_path, approved):
    frozen = cohort(tmp_path)
    frozen["implementation"]["execution_forward.py"] = (
        forward.V1_RECORDER_SHA256 if approved else "unrecognized-source"
    )
    (tmp_path / "manifest.json").write_bytes(forward.encoded(frozen))
    if approved:
        assert (
            forward.load(tmp_path)[0]["implementation"]["execution_forward.py"]
            == forward.V1_RECORDER_SHA256
        )
    else:
        with pytest.raises(ValueError, match="identity"):
            forward.load(tmp_path)


# Unknown auction fills cannot become a paired profit from cancellation arithmetic.
def test_auction_uncertainty_withholds_consolidated_pnl(tmp_path):
    at = ny(15, 35)
    first = obs(at)
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    frozen = cohort(tmp_path, first=first)
    proxy = forward.compare(tmp_path)
    rows = {s: [label_row(at)] for s in ("AAA", "SPY", "QQQ")}
    start = label_packet(tmp_path / "start", at, rows)
    end = label_packet(tmp_path / "end", at, rows)
    result = labels.supplement(frozen, proxy, start, end)
    for final in result["results"]:
        assert final["gain_vs_incumbent"] is None
        if final["mode"] == "incumbent":
            assert final["unsupported_auction_orders"] == ["a"]
            assert final["ending_value"] is None
            assert final["ending_cash"] is None
            assert final["fees"] is None


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


# Check shares and USD-normalized balances against the independent native engine.
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
    # The diagnostic retains fractional cost allowances; native USD Money rounds cents.
    normalized_cash = float(
        Decimal(str(result["book"]["cash"])).quantize(Decimal(".01"))
    )
    normalized_fee = float(
        Decimal(str(result["book"]["fees"])).quantize(Decimal(".01"))
    )
    assert normalized_cash == pytest.approx(reference["ending_cash"])
    assert normalized_fee == pytest.approx(reference["commissions"])
    assert result["book"]["holdings"]["AAA"] == reference["ending_holdings"]["AAA"]
    native_mark = (
        normalized_cash
        + result["book"]["holdings"]["AAA"] * candle["execution_quote"]["bid"]
    )
    assert native_mark == pytest.approx(reference["ending_bid_marked_equity"])


# Provide raw consolidated endpoint events without accessing credentials or providers.
def label_row(at, *, bid=100, ask=100.1):
    return {"t": at.isoformat(), "bp": bid, "ap": ask, "bs": 100, "as": 100}


# Exercise actual paginated capture and preserve the original provider bytes.
def label_packet(tmp_path, at, quotes, *, token=None):
    return labels.fetch_window(
        set(quotes),
        at,
        tmp_path,
        request=lambda url, headers: (
            200,
            forward.encoded({"quotes": quotes, "next_page_token": token}),
        ),
        headers={"test": "read-only"},
        clock=lambda: at + timedelta(minutes=17),
    )


# Read the raw response back after capture and verify consolidated endpoint selection.
def test_delayed_label_capture_preserves_bytes_and_request(tmp_path):
    at = ny(10, 16)
    row = label_row(at)
    packet = label_packet(tmp_path / "labels", at, {"AAA": [row]})
    qualified, missing = labels.marks(packet, {"AAA"})
    assert qualified["AAA"]["bid"] == 100
    assert missing == {}
    assert (
        packet["pages"][0]["body"]
        == forward.encoded({"quotes": {"AAA": [row]}, "next_page_token": None}).decode()
    )
    assert (tmp_path / "labels/complete.json").read_bytes() == forward.encoded(packet)
    assert packet["request"]["feed"] == "sip"
    assert packet["request"]["asof"] == "-"
    with pytest.raises(FileExistsError):
        label_packet(tmp_path / "labels", at, {"AAA": [row]})


# Reject premature label access before any request or output directory is created.
def test_sip_delay_is_structural(tmp_path):
    called = []
    at = ny(10, 16)
    with pytest.raises(ValueError, match="16 minutes"):
        labels.fetch_window(
            {"AAA"},
            at,
            tmp_path / "premature",
            request=lambda *args: called.append(args),
            clock=lambda: at + timedelta(minutes=15),
        )
    assert called == []
    assert not (tmp_path / "premature").exists()


# A completed endpoint resumes from its original bytes without another provider call.
def test_completed_endpoint_is_reused_without_refetch(tmp_path):
    at = ny(10, 16)
    packet = label_packet(tmp_path / "labels", at, {"AAA": [label_row(at)]})
    calls = []
    reused = labels.endpoint(
        {"AAA"}, at, tmp_path / "labels", request=lambda *args: calls.append(args)
    )
    assert reused == packet
    assert calls == []
    with pytest.raises(ValueError, match="another observation"):
        labels.endpoint({"AAA"}, at + timedelta(seconds=1), tmp_path / "labels")


# An incomplete refused capture cannot be silently replaced during a later valuation.
def test_refused_endpoint_preserves_failure_and_does_not_retry(tmp_path):
    at = ny(10, 16)
    folder = tmp_path / "labels"
    with pytest.raises(ValueError, match="HTTP 403"):
        labels.endpoint(
            {"AAA"},
            at,
            folder,
            request=lambda *args: (403, b'{"message":"not permitted"}'),
            headers={"test": "only"},
            clock=lambda: at + timedelta(minutes=17),
        )
    assert (folder / "0000.json").exists()
    with pytest.raises(FileNotFoundError):
        labels.endpoint({"AAA"}, at, folder)


# The latest invalid or wide event cannot be replaced with an older convenient mark.
@pytest.mark.parametrize("change", [{"bp": 0}, {"bp": 90}, {"bs": 0}, {"bp": 101}])
def test_invalid_latest_label_does_not_fall_back(tmp_path, change):
    at = ny(10, 16)
    latest = {**label_row(at), **change}
    packet = label_packet(
        tmp_path / "labels", at, {"AAA": [label_row(at - timedelta(seconds=1)), latest]}
    )
    qualified, missing = labels.marks(packet, {"AAA"})
    assert qualified == {}
    assert "AAA" in missing


# Preserve nanosecond ordering and reject an event just after the endpoint.
def test_quote_nanoseconds_cannot_round_into_the_past(tmp_path):
    at = ny(10, 16).replace(microsecond=123456)
    row = label_row(at)
    row["t"] = row["t"].replace(".123456", ".123456001")
    packet = label_packet(tmp_path / "labels", at, {"AAA": [row]})
    assert labels.nanos(row["t"]) == labels.nanos(at.isoformat()) + 1
    with pytest.raises(ValueError, match="outside"):
        labels.marks(packet, {"AAA"})


# Missing or disconnected pagination and changed response bytes cannot silently pass.
@pytest.mark.parametrize(
    "defect", ["body", "missing_page", "disconnected", "early_receipt"]
)
def test_label_provenance_is_enforced(tmp_path, defect):
    at = ny(10, 16)
    packet = label_packet(tmp_path / "labels", at, {"AAA": [label_row(at)]})
    page = packet["pages"][0]
    if defect == "body":
        page["body"] += " "
    elif defect == "missing_page":
        page["body"] = forward.encoded(
            {"quotes": {}, "next_page_token": "missing"}
        ).decode()
        import hashlib

        page["body_sha256"] = hashlib.sha256(page["body"].encode()).hexdigest()
    elif defect == "disconnected":
        packet["pages"].append(dict(page))
    else:
        page["received_at"] = at.isoformat()
    with pytest.raises(ValueError, match="provenance|Incomplete|Disconnected"):
        labels.marks(packet, {"AAA"})


# Follow actual continuation tokens across all symbols and reject repeated tokens.
def test_label_pagination_covers_later_symbols(tmp_path):
    at = ny(10, 16)
    seen = []

    # Return a second symbol only when the caller follows the provider's token.
    def request(url, headers):
        token = parse_qs(urlsplit(url).query).get("page_token", [None])[0]
        seen.append(token)
        body = {
            "quotes": {"AAA" if token is None else "BBB": [label_row(at)]},
            "next_page_token": "second" if token is None else None,
        }
        return 200, forward.encoded(body)

    packet = labels.fetch_window(
        {"AAA", "BBB"},
        at,
        tmp_path / "labels",
        request=request,
        headers={"test": "only"},
        clock=lambda: at + timedelta(minutes=17),
    )
    assert seen == [None, "second"]
    assert set(labels.marks(packet, {"AAA", "BBB"})[0]) == {"AAA", "BBB"}
    with pytest.raises(ValueError, match="repeated"):
        label_packet(tmp_path / "repeated", at, {"AAA": []}, token="loop")


# Tied latest timestamps cannot select a favorable record or create a label.
def test_conflicting_consolidated_events_are_refused(tmp_path):
    at = ny(10, 16)
    packet = label_packet(
        tmp_path / "labels", at, {"AAA": [label_row(at), label_row(at, bid=99)]}
    )
    qualified, missing = labels.marks(packet, {"AAA"})
    assert qualified == {}
    assert "ambiguous" in missing["AAA"]


# Earlier timestamp ties cannot invalidate a later unambiguous endpoint event.
def test_earlier_tied_quotes_do_not_override_latest_endpoint(tmp_path):
    at = ny(10, 16)
    earlier = at - timedelta(seconds=1)
    packet = label_packet(
        tmp_path / "labels",
        at,
        {"AAA": [label_row(earlier), label_row(earlier, bid=99), label_row(at)]},
    )
    qualified, missing = labels.marks(packet, {"AAA"})
    assert qualified["AAA"]["bid"] == 100
    assert missing == {}


# Equal unpriced holdings cancel in paired gain while neither total NAV is fabricated.
def test_common_missing_holdings_do_not_hide_identifiable_paired_gain(tmp_path):
    frozen = cohort(
        tmp_path, cash=1200, holdings={"UNPRICED": 3}, first=obs(ask=110, bid=109.9)
    )
    proxy = forward.compare(tmp_path)
    at = ny(10, 16)
    rows = {s: [label_row(at, bid=115, ask=115.1)] for s in ("AAA", "SPY", "QQQ")}
    rows["UNPRICED"] = []
    first = label_packet(tmp_path / "first", at, rows)
    last = label_packet(tmp_path / "last", at, rows)
    result = labels.supplement(frozen, proxy, first, last)
    assert result["starting_value"] is None
    for value in result["results"]:
        assert value["ending_value"] is None
        assert value["total_return"] is None
        assert value["benchmarks"]["SPY"]["excess_gain"] is None
        assert value["missing_pair_marks"] == []
        if value["mode"] == "bounded":
            expected = 1100 * (1 + value["cost_bps"] / 10000) - 1150
            assert value["gain_vs_incumbent"] == pytest.approx(expected)


# A missing mark for a differing position still prevents a paired gain claim.
def test_differing_unpriced_position_keeps_pair_gain_missing():
    delta, missing = labels.difference(
        {"cash": 100, "holdings": {"AAA": 2}}, {"cash": 90, "holdings": {"AAA": 1}}, {}
    )
    assert delta is None
    assert missing == ["AAA"]


# The receipt workflow exposes reads only and persists exact matched broker outcomes.
def test_paper_receipts_are_get_only_and_match_frozen_ids(tmp_path):
    frozen = cohort(tmp_path)
    calls = []

    # Return a paper fill while asserting that no body or write method can be sent.
    def transport(method, url, headers, body):
        calls.append(method)
        assert method == "GET"
        assert body is None
        assert parse_qs(urlsplit(url).query)["client_order_id"] == ["a"]
        return 200, forward.encoded(
            {
                "client_order_id": "a",
                "symbol": "AAA",
                "side": "buy",
                "status": "filled",
                "filled_qty": "10",
                "filled_avg_price": "99",
            }
        )

    client = SimpleNamespace(
        base_url=labels.alpaca_trading.PAPER_URL,
        transport=transport,
        headers={"test": "read-only"},
    )
    output = tmp_path / "receipts.json"
    result = labels.capture_receipts(
        frozen, output, client=client, clock=lambda: ny(16, 1)
    )
    assert calls == ["GET"]
    assert result["complete"] is True
    assert result["manifest_sha256"] == forward.digest(frozen)
    assert output.read_bytes() == forward.encoded(result)
    assert "headers" not in result["receipts"][0]
    with pytest.raises(FileExistsError):
        labels.capture_receipts(frozen, output, client=client)


# A refused or mismatched receipt cannot be counted as a fill for another order.
@pytest.mark.parametrize("status", [401, 404, 200])
def test_receipt_failure_and_missing_outcomes_are_explicit(tmp_path, status):
    frozen = cohort(tmp_path)
    client = SimpleNamespace(
        base_url=labels.alpaca_trading.PAPER_URL,
        headers={},
        transport=lambda *args: (status, b'{"client_order_id":"wrong"}'),
    )
    output = tmp_path / "receipts.json"
    if status == 404:
        result = labels.capture_receipts(
            frozen, output, client=client, clock=lambda: ny(16, 1)
        )
        assert result["receipts"][0]["http_status"] == 404
    else:
        with pytest.raises(ValueError, match="HTTP 401|match"):
            labels.capture_receipts(
                frozen, output, client=client, clock=lambda: ny(16, 1)
            )
        if status == 401:
            assert not json.loads(output.read_text())["complete"]


# Supply matched terminal broker evidence without executing or mutating any account.
def broker_labels(frozen, *, statuses=None, price=110):
    import hashlib

    rows = []
    for op in frozen["opportunities"]:
        order = op["order"]
        status = (statuses or {}).get(order["client_order_id"], "filled")
        row = {
            "client_order_id": order["client_order_id"],
            "symbol": order["symbol"],
            "side": order["side"],
            "qty": str(order["qty"]),
            "type": "market",
            "time_in_force": "cls",
            "submitted_at": ny(15, 36).isoformat(),
            "status": status,
            "filled_qty": str(order["qty"] if status == "filled" else 0),
            "filled_avg_price": str(price) if status == "filled" else None,
            "filled_at": ny(15, 59).isoformat() if status == "filled" else None,
        }
        body = forward.encoded(row)
        rows.append(
            {
                "client_order_id": order["client_order_id"],
                "http_status": 200,
                "received_at": ny(16, 1).isoformat(),
                "body": body.decode(),
                "body_sha256": hashlib.sha256(body).hexdigest(),
            }
        )
    return {
        "manifest_sha256": forward.digest(frozen),
        "complete": True,
        "receipts": rows,
    }


# Recorded closing fills resolve uncertainty without changing the original comparison.
def test_observed_auction_stress_resolves_only_matched_outcomes(tmp_path):
    first = obs(ny(15, 35), ask=110, bid=109.9)
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    frozen = cohort(tmp_path, cash=1200, first=first)
    proxy = forward.compare(tmp_path)
    original = forward.encoded(proxy)
    result = labels.observed_auctions(frozen, proxy, broker_labels(frozen))
    assert forward.encoded(proxy) == original
    assert result["ended_at"] == ny(16).isoformat()
    for arm in result["results"]:
        assert arm["execution_complete"] is True
        if arm["mode"] == "incumbent":
            assert arm["book"]["holdings"] == {"AAA": 10}
            assert arm["book"]["cash"] == pytest.approx(
                100 - 1100 * arm["cost_bps"] / 10000
            )
            assert arm["opportunities"]["a"]["observed_filled_qty"] == 10
            assert arm["opportunities"]["a"]["status"] == "observed_auction_filled"


# Expired broker orders stay missed and cannot acquire a later market fill.
def test_observed_auction_expired_order_stays_zero_fill(tmp_path):
    first = obs(ny(15, 35))
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    frozen = cohort(tmp_path, first=first)
    result = labels.observed_auctions(
        frozen,
        forward.compare(tmp_path),
        broker_labels(frozen, statuses={"a": "expired"}),
    )
    for arm in result["results"]:
        if arm["mode"] == "incumbent":
            assert arm["execution_complete"] is True
            assert arm["book"]["cash"] == 1000
            assert arm["opportunities"]["a"]["filled_qty"] == 0
            assert arm["opportunities"]["a"]["status"] == "observed_auction_expired"


# Auction sale proceeds cannot fund a simultaneous stress-modelled purchase.
def test_observed_auction_cash_and_covered_share_constraints(tmp_path):
    first = obs(ny(15, 35), symbols=("AAA", "BBB", "SPY", "QQQ"))
    for symbol in ("AAA", "BBB"):
        first["latch"]["symbols"][symbol].pop("buy_trigger")
        first["snapshot"]["quotes"][symbol]["last"] = 100
    frozen = cohort(
        tmp_path,
        cash=0,
        holdings={"AAA": 2},
        first=first,
        rows=[order(side="sell", qty=2), order("BBB", qty=1, cid="b")],
    )
    result = labels.observed_auctions(
        frozen, forward.compare(tmp_path), broker_labels(frozen, price=100)
    )
    for arm in result["results"]:
        if arm["mode"] == "incumbent":
            assert arm["book"]["holdings"].get("BBB", 0) == 0
            assert arm["opportunities"]["b"]["observed_filled_qty"] == 1
            assert arm["opportunities"]["b"]["filled_qty"] == 0
            assert arm["book"]["cash"] == pytest.approx(
                200 * (1 - arm["cost_bps"] / 10000)
            )


# Changed receipt bytes, mismatched identity and future fills cannot create outcomes.
@pytest.mark.parametrize("defect", ["bytes", "future", "identity"])
def test_observed_auction_source_is_enforced(tmp_path, defect):
    import hashlib

    first = obs(ny(15, 35))
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    frozen = cohort(tmp_path, first=first)
    receipts = broker_labels(frozen)
    entry = receipts["receipts"][0]
    if defect == "bytes":
        entry["body"] += " "
    else:
        row = json.loads(entry["body"])
        row["filled_at" if defect == "future" else "symbol"] = (
            ny(16, 1).isoformat() if defect == "future" else "OTHER"
        )
        entry["body"] = forward.encoded(row).decode()
        entry["body_sha256"] = hashlib.sha256(entry["body"].encode()).hexdigest()
    with pytest.raises(ValueError, match="changed|cohort|time"):
        labels.observed_auctions(frozen, forward.compare(tmp_path), receipts)


# Run closing valuation while ensuring delayed labels never create entries.
def test_receipt_valuation_workflow_preserves_candidate_causality(tmp_path):
    source = tmp_path / "cohort"
    source.mkdir()
    first = obs(ny(15, 35), ask=110, bid=109.9)
    first["latch"]["symbols"]["AAA"].pop("buy_trigger")
    first["snapshot"]["quotes"]["AAA"]["last"] = 100
    frozen = cohort(source, cash=1200, first=first)
    receipts = tmp_path / "receipts.json"
    receipts.write_bytes(forward.encoded(broker_labels(frozen)))
    original = receipts.read_bytes()

    # Return later consolidated prices only through the outcome-label transport.
    def request(url, headers):
        query = parse_qs(urlsplit(url).query)
        at = forward.bounded.instant(query["end"][0])
        bid = 100 if at == ny(15, 35) else 120
        return 200, forward.encoded(
            {
                "quotes": {
                    s: [label_row(at, bid=bid, ask=bid + 0.1)]
                    for s in query["symbols"][0].split(",")
                },
                "next_page_token": None,
            }
        )

    result = valuate(
        source,
        tmp_path / "result.json",
        receipts_path=receipts,
        request=request,
        headers={"test": "only"},
        clock=lambda: ny(16, 30),
    )
    assert receipts.read_bytes() == original
    assert result["consolidated"]["valuation_ended_at"] == ny(16).isoformat()
    assert result["consolidated"]["paper_receipt_sha256"] == forward.digest(
        broker_labels(frozen)
    )
    for raw, final in zip(
        result["observed_auction_supplement"]["results"],
        result["consolidated"]["results"],
        strict=True,
    ):
        if final["mode"] == "bounded":
            assert raw["book"]["holdings"] == {}
            assert final["total_gain"] == 0
            assert final["gain_vs_incumbent"] < 0
        else:
            assert final["total_gain"] == pytest.approx(
                100 - 1100 * final["cost_bps"] / 10000
            )
    assert result["consolidated"]["adoption_eligible"] is False


# Exercise the CLI's full frozen comparison and label valuation without changing inputs.
def test_consolidated_workflow_retains_fills_and_missing_marks(tmp_path):
    source = tmp_path / "cohort"
    source.mkdir()
    frozen = cohort(source, cash=1000)
    forward.append(source, obs(ny(10, 17), ask=105, bid=104.9))
    originals = {p.name: p.read_bytes() for p in source.glob("*.json")}
    received = ny(10, 40)

    # Return endpoint labels for each requested symbol, withholding QQQ explicitly.
    def request(url, headers):
        query = parse_qs(urlsplit(url).query)
        at = forward.bounded.instant(query["end"][0])
        bid = 100 if at == ny(10, 16) else 110
        quotes = {
            s: [label_row(at, bid=bid, ask=bid + 0.1)]
            for s in query["symbols"][0].split(",")
            if s != "QQQ"
        }
        return 200, forward.encoded({"quotes": quotes, "next_page_token": None})

    output = tmp_path / "result.json"
    result = valuate(
        source,
        output,
        request=request,
        headers={"test": "only"},
        clock=lambda: received,
    )
    assert output.read_bytes() == forward.encoded(result)
    assert originals == {p.name: p.read_bytes() for p in source.glob("*.json")}
    assert result["proxy"]["manifest_sha256"] == forward.digest(frozen)
    for proxy, final in zip(
        result["proxy"]["results"], result["consolidated"]["results"], strict=True
    ):
        assert proxy["book"]["holdings"] == {"AAA": 10}
        assert final["ending_value"] == pytest.approx(proxy["book"]["cash"] + 1100)
        assert final["total_gain"] == pytest.approx(final["ending_value"] - 1000)
        assert final["fees"] == proxy["book"]["fees"]
        assert final["ending_exposure"] == pytest.approx(1100 / final["ending_value"])
        assert final["gain_vs_incumbent"] == 0
        assert final["max_drawdown_loss"] is None
        assert final["benchmarks"]["QQQ"]["excess_gain"] is None
        assert final["benchmarks"]["SPY"]["excess_gain"] is not None
    assert result["consolidated"]["adoption_eligible"] is False
    with pytest.raises(FileExistsError):
        valuate(
            source,
            output,
            request=request,
            headers={"test": "only"},
            clock=lambda: received,
        )
