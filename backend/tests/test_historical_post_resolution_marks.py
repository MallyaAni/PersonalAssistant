"""Synthetic native-state mark selection; no actual account, model or provider call."""

from copy import deepcopy
from decimal import Decimal
from math import ulp

import pytest

from backend.market import historical_packet_parser as parser
from backend.market import historical_post_resolution_marks as marks
from backend.market import historical_timing_packet as timing
from backend.market import replay_broker as native
from backend.market.alpaca_trading import AlpacaTradingError
from backend.tests.test_historical_packet_demand import (
    VERIFIED,
    declaration,
    demand,
    page,
    sha,
    source_registry,
)

WINDOW = timing.schedule("2019-03-01T14:45:00Z")


# Construct native synthetic state with distinct observation/resolution clocks.
def broker(held=None, prior="assumed_submission_at", resolved=True, cash=1000):
    client = native.ReplayBroker(
        cash,
        10,
        initial_holdings=held or {},
        initial_average_prices={name: 10 for name in held or {}},
    )
    client.observe(WINDOW[prior], {"AAPL": 100, "MSFT": 20}, True)
    if resolved:
        client.flush(WINDOW["quote_end"], {}, phase="market")
    return client


# Preserve raw quote clocks independently of fill prices or broker observation clocks.
def quote(at="2019-03-01T14:45:32.9Z", bid=199.99, ask=200, size=1):
    return {"t": at, "bp": bid, "ap": ask, "bs": size, "as": size}


# Seal only labelled synthetic source pages under a fixed declared request manifest.
def packet(events, names=("AAPL", "MSFT")):
    reg = source_registry(names)
    manifest = declaration(reg, held=sorted(names), legs=[])
    queries = demand.read(manifest, reg)["queries"]
    groups = {
        q["sha256"]: [
            page(
                q,
                {
                    name: events.get(name, [])
                    for name in q["parameters"]["symbols"].split(",")
                },
            )
        ]
        for q in queries
    }
    raw = demand.encoded(
        {
            "schema": "historical-demand-capture/1",
            "demand_sha256": manifest.sha256,
            "complete": True,
            "failure": None,
            "groups": groups,
        }
    )
    return reg, manifest, parser.packets(raw, sha(raw), manifest, reg, VERIFIED)


# Exercise selection with a pre-call binding and assert complete immutability.
def select(client, events=None, names=("AAPL", "MSFT"), expected=None):
    reg, manifest, source = packet(events or {}, names)
    before = deepcopy(client.__dict__)
    result = marks.select(
        client,
        expected_state_sha256=expected or marks.state_binding(client),
        packet=source,
        manifest=manifest,
        entity_registry=reg,
    )
    assert client.__dict__ == before
    return result


# Freshness uses prior observed31.2, even though the native current clock is already33.
def test_resolution_clock_is_not_previous_observation_cutoff():
    client = broker({"AAPL": 2, "MSFT": 1})
    result = select(client, {"AAPL": [quote()], "MSFT": [quote(bid=19.99, ask=20)]})
    assert result["candidate_marks"]["AAPL"] == 199.995
    # Independent decimal midpoint permits one IEEE ULP from native half-summing.
    expected_msft = float((Decimal("19.99") + Decimal("20")) / 2)
    assert result["candidate_marks"]["MSFT"] == pytest.approx(
        expected_msft, rel=0, abs=ulp(expected_msft)
    )
    assert result["required_holdings"] == {"AAPL": 2.0, "MSFT": 1.0}
    assert (
        result["clocks"]["previous_observed_at"] == "2019-03-01T14:45:31.200000+00:00"
    )
    assert (
        result["clocks"]["previous_observation_upper_at"]
        == "2019-03-01T14:45:31.201000000Z"
    )
    assert result["clocks"]["native_current_clock"] == "2019-03-01T14:45:33+00:00"
    assert (
        result["clocks"]["assumed_mark_observation_at"]
        == "2019-03-01T14:45:33.101000000Z"
    )
    assert result["details"]["AAPL"]["raw_event_at"] == "2019-03-01T14:45:32.9Z"
    assert (
        result["details"]["AAPL"]["assumed_receive_upper_at"]
        == "2019-03-01T14:45:33.001000000Z"
    )
    assert result["nav"] is None
    with pytest.raises(AlpacaTradingError, match="Fresh observed account clock"):
        client.account()


# WAIT can retain the31.1 decision observation without inventing a sender submission.
def test_wait_uses_actual_decision_observation_without_any_native_attempt():
    client = broker({"AAPL": 1}, prior="assumed_decision_at", resolved=False)
    result = select(client, {"AAPL": [quote(at="2019-03-01T14:45:31.15Z")]})
    assert result["candidate_marks"] == {"AAPL": 199.995}
    assert (
        result["clocks"]["previous_observation_upper_at"]
        == "2019-03-01T14:45:31.101000000Z"
    )
    assert client.attempt_history == ()
    assert client.fill_history == ()
    assert result["nav"] is None


# Missing preheld marks withhold the entire candidate observation.
def test_missing_preheld_mark_withholds_all_candidates():
    client = broker({"AAPL": 2, "MSFT": 1})
    result = select(client, {"AAPL": [quote()]})
    assert result["missing"] == ["MSFT"]
    assert result["candidate_marks"] is None
    assert result["details"]["AAPL"]["status"] == "CANDIDATE"
    assert result["nav"] is None


# Derive required coverage from native holdings, not a caller name list.
def test_actual_held_name_missing_from_manifest_refuses():
    client = broker({"AAPL": 2, "MSFT": 1})
    with pytest.raises(ValueError, match="Actual resulting holdings exceed"):
        select(client, {"AAPL": [quote()]}, names=("AAPL",))


# Refuse invalid latest evidence without falling back to older quotes.
@pytest.mark.parametrize("kind", ["invalid", "conflict", "zero_size", "wide_spread"])
def test_latest_invalid_or_conflicting_has_no_older_fallback(kind):
    client = broker({"AAPL": 2})
    latest = quote(at="2019-03-01T14:45:33Z")
    rows = [quote(), latest]
    if kind == "invalid":
        latest["bp"] = 0
    elif kind == "conflict":
        rows.append(dict(latest, ap=200.01))
    elif kind == "zero_size":
        latest["as"] = 0
    else:
        latest["ap"] = 220
    result = select(client, {"AAPL": rows})
    assert result["candidate_marks"] is None
    assert result["missing"] == ["AAPL"]
    assert "no older fallback" in result["details"]["AAPL"]["reason"]


# A quote exactly at the conservative freshness boundary is not strictly fresh.
@pytest.mark.parametrize(
    ("at", "available"),
    [("2019-03-01T14:45:31.202Z", False), ("2019-03-01T14:45:31.202000001Z", True)],
)
def test_prior_observation_upper_and_event_lower_are_strict(at, available):
    result = select(broker({"AAPL": 1}), {"AAPL": [quote(at=at)]})
    assert (result["candidate_marks"] is not None) is available


# The existing inclusive window endpoint is received by the distinct33.101 mark clock.
def test_window_endpoint_preserves_raw_event_and_assumed_receive():
    result = select(broker({"AAPL": 1}), {"AAPL": [quote(at="2019-03-01T14:45:33Z")]})
    row = result["details"]["AAPL"]
    assert row["raw_event_at"] == "2019-03-01T14:45:33Z"
    assert row["event_upper_at"] == "2019-03-01T14:45:33.001000000Z"
    assert (
        row["assumed_receive_upper_at"]
        == result["clocks"]["assumed_mark_observation_at"]
    )


# Native partial fills retain original basis and require a separate midpoint candidate.
def test_partial_native_fill_does_not_substitute_fill_price():
    client = broker({}, resolved=False)
    client.submit_market("AAPL", 9, "buy", "synthetic-gap")
    fills = client.flush(WINDOW["quote_end"], {"AAPL": 200}, phase="market")
    assert fills[0]["filled_qty"] == 4
    assert client.ledger()["cash"] == pytest.approx(float(Decimal("199.2")))
    result = select(client, {"AAPL": [quote()]})
    assert result["required_holdings"] == {"AAPL": 4}
    assert result["candidate_marks"] == {"AAPL": 199.995}
    assert result["candidate_marks"]["AAPL"] != fills[0]["price"]
    assert result["nav"] is None


# Preserve a fractional sell residue and require its fresh mark.
def test_fractional_residue_is_required_and_never_rounded():
    client = broker({"AAPL": 10}, resolved=False)
    client.apply_split("AAPL", 0.25, "2019-03-01T14:30:00Z")
    client.submit_market("AAPL", 2, "sell", "synthetic-covered-whole")
    client.flush(WINDOW["quote_end"], {"AAPL": 200}, phase="market")
    assert client.ledger()["holdings"] == {"AAPL": 0.5}
    result = select(client, {})
    assert result["required_holdings"] == {"AAPL": 0.5}
    assert result["missing"] == ["AAPL"]
    assert result["candidate_marks"] is None


# Full exits need no held marks and never manufacture cash equity from the empty set.
def test_full_exit_requires_no_marks_but_nav_remains_unevaluated():
    client = broker({"AAPL": 2}, resolved=False)
    client.submit_market("AAPL", 2, "sell", "synthetic-full-exit")
    client.flush(WINDOW["quote_end"], {"AAPL": 200}, phase="market")
    result = select(client)
    assert result["required_holdings"] == {}
    assert result["candidate_marks"] == {}
    assert result["nav"] is None


# No-fill held orders still need fresh marks after the prior observation.
def test_no_fill_with_preheld_shares_still_requires_fresh_evidence():
    client = broker({"AAPL": 2}, resolved=False)
    client.submit_market("AAPL", 1, "sell", "synthetic-missing-reference")
    fills = client.flush(WINDOW["quote_end"], {}, phase="market")
    assert fills[0]["filled_qty"] == 0
    result = select(client, {"AAPL": [quote(at="2019-03-01T14:45:30.9Z")]})
    assert result["candidate_marks"] is None
    assert result["required_holdings"] == {"AAPL": 2.0}


# Pin current state independently and refuse any intervening cash/clock/holding changes.
@pytest.mark.parametrize("field", ["cash", "observation", "held"])
def test_changed_state_binding_refuses(field):
    client = broker({"AAPL": 1})
    expected = marks.state_binding(client)
    if field == "cash":
        client._cash += 1
    elif field == "observation":
        client._observed_at = native._instant(WINDOW["assumed_decision_at"])
    else:
        client._held["AAPL"] += 0.5
    with pytest.raises(ValueError, match="state binding differs"):
        select(client, {"AAPL": [quote()]}, expected=expected)


# A proposed mark observation cannot move backward from an already later broker clock.
def test_monotone_mark_observation_refuses_future_native_state():
    client = broker({"AAPL": 1})
    client._now = native._instant("2019-03-01T14:45:33.102Z")
    with pytest.raises(ValueError, match="strictly advance native clock"):
        select(client, {"AAPL": [quote()]})


# Accept only the exact native class without broadening admission to custom brokers.
def test_subclass_state_binding_is_refused():
    class Derived(native.ReplayBroker):
        pass

    with pytest.raises(ValueError, match="Exact ReplayBroker"):
        marks.state_binding(Derived(1000, 10))
