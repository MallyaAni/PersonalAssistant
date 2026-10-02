"""Pin frozen candle-path timing and separate it from funded quote fill evidence."""

from copy import deepcopy

import numpy as np
import pytest

from backend.market import specialist_timing as timing


# Build a reviewed 252-bar raw prefix and explicit dated no-split research evidence.
def payload(session="2026-09-03"):
    grid = timing.expected_prefix(session)
    return {
        "symbol": "NVDA",
        "session": session,
        "observed_at": (grid[-1] + timing.BAR).isoformat(),
        "source_sha256": "a" * 64,
        "price_basis": "raw",
        "availability_mode": "bar_close_assumed",
        "split_audit": {
            "basis": "dated-actions",
            "source_sha256": "b" * 64,
            "availability_mode": "assumed_research",
            "available_at": grid[0].isoformat(),
            "coverage_start": str(grid[0].date()),
            "coverage_end": session,
            "events": [],
        },
        "bars": [
            {
                "start": start.isoformat(),
                "available_at": (start + timing.BAR).isoformat(),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 1000,
            }
            for start in grid
        ],
    }


# Bind an unchanged original allocation intent created before the session opens.
def intent(side="buy", qty=10):
    return {
        "symbol": "NVDA",
        "session": "2026-09-03",
        "side": side,
        "qty": qty,
        "client_order_id": "original-1",
        "created_at": "2026-09-02T16:00:00-04:00",
    }


# Supply eight valid distinct synthetic paths without asserting model profitability.
def samples(prepared):
    out = np.tile(
        [100, 102, 98, 100, 1000], (8, len(prepared["future_starts"]), 1)
    ).astype(float)
    for i in range(8):
        out[i, :, 1] += i * 0.1
        out[i, :, 2] -= i * 0.1
    return out


# Build separate future execution candles whose opens never become forecast inputs.
def future(prepared, opening=97):
    return [
        {
            "start": start,
            "available_at": (timing.aware(start) + timing.BAR).isoformat(),
            "open": opening,
            "high": max(103, opening),
            "low": min(96, opening),
            "close": 100,
            "volume": 1000,
        }
        for start in prepared["future_starts"]
    ]


# Exercise the public proxy with an explicit account and outcome publication cutoff.
def execute(order, bars, **kwargs):
    return timing.proxy_fill(
        order,
        bars,
        data_as_of=order["expires_at"],
        available_cash=kwargs.get("cash", 10000),
        held_qty=kwargs.get("held", 20),
        cost_bps=10,
        completed_ids=kwargs.get("done", set()),
    )


# Appending arbitrary future candles must not alter causal context or its hash.
def test_future_prefix_invariance():
    row = payload()
    first = timing.prepare(row)
    row["bars"] += [{"start": first["future_starts"][-1], "open": "bad"}]
    assert timing.prepare(row) == first
    assert len(first["bars"]) == 252
    assert len(first["future_starts"]) == 25


# A late, missing or duplicate prefix bar cannot establish a causal permission.
@pytest.mark.parametrize("defect", ["late", "missing", "duplicate", "invalid", "clock"])
def test_prefix_defects(defect):
    row = payload()
    if defect == "late":
        row["bars"][-1]["available_at"] = "2026-09-03T09:45:01-04:00"
    elif defect == "missing":
        row["bars"].pop(0)
    elif defect == "duplicate":
        row["bars"].append(row["bars"][0])
    elif defect == "invalid":
        row["bars"][0]["high"] = 1
    else:
        row["observed_at"] = "2026-09-03T10:00:00-04:00"
    with pytest.raises(ValueError, match="prefix|permission|ohlc"):
        timing.prepare(row)


# Raw splits and unknown corporate-action coverage cannot masquerade as candle paths.
@pytest.mark.parametrize(
    "defect", ["split", "basis", "coverage", "publication", "no_audit"]
)
def test_units_and_split_evidence(defect):
    row = payload()
    if defect == "split":
        row["split_audit"]["events"] = [
            {"effective_session": "2026-09-03", "ratio": 10}
        ]
    elif defect == "basis":
        row["price_basis"] = "adjusted"
    elif defect == "coverage":
        row["split_audit"]["coverage_start"] = "2026-09-03"
    elif defect == "publication":
        row["split_audit"]["available_at"] = "2026-09-03T16:00:00-04:00"
    else:
        row.pop("split_audit")
    with pytest.raises(ValueError, match="split|basis"):
        timing.prepare(row)


# Published early closes change both completed context grids and permission expiry.
def test_early_close_and_closed_session():
    prepared = timing.prepare(payload("2026-11-27"))
    assert len(prepared["future_starts"]) == 13
    assert prepared["expires_at"] == "2026-11-27T13:00:00-05:00"
    with pytest.raises(ValueError, match="closed_session"):
        timing.slots("2026-11-26")


# Fixed sample minima/maxima establish separate inward-rounded buy and sell bounds.
def test_empirical_bounds():
    prepared = timing.prepare(payload())
    paths = samples(prepared)
    buy = timing.permission(prepared, intent(), paths)
    sell = timing.permission(prepared, intent("sell"), paths)
    assert buy["limit_price"] == 97.47
    assert sell["limit_price"] == 102.53
    assert buy["context_sha256"] == sell["context_sha256"]
    assert buy["path_sha256"] == sell["path_sha256"]
    assert buy["fill_proof"] is False


# No malformed path is repaired, removed or resampled to create a favorable bound.
def test_malformed_sample_refused():
    prepared = timing.prepare(payload())
    paths = samples(prepared)
    paths[0, 0, 1] = 1
    with pytest.raises(ValueError, match="inconsistent_ohlc"):
        timing.permission(prepared, intent(), paths)
    with pytest.raises(ValueError, match="eight_complete"):
        timing.permission(prepared, intent(), paths[:7])


# Holds, rewritten identities and current-session intents are outside the kernel.
@pytest.mark.parametrize("defect", ["hold", "zero", "identity", "created"])
def test_original_intent_guards(defect):
    prepared = timing.prepare(payload())
    order = intent()
    if defect == "hold":
        order["side"] = "hold"
    elif defect == "zero":
        order["qty"] = 0
    elif defect == "identity":
        order["symbol"] = "AAOI"
    else:
        order["created_at"] = "2026-09-03T09:30:00-04:00"
    with pytest.raises(ValueError, match="intent|identity|allocation"):
        timing.permission(prepared, order, samples(prepared))


# Strict event ordering excludes the boundary open and includes actual funded buy gaps.
def test_buy_proxy_gap_and_funding():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    result = execute(order, future(prepared), cash=500)
    assert result["proxy_at"] == "2026-09-03T10:00:00-04:00"
    assert result["proxy_price"] == 97
    assert result["status"] == "partial"
    assert result["filled_qty"] == 5
    assert 500 + result["cash_delta"] >= 0
    assert result["shares_delta"] == 5


# Sell permissions cannot oversell, borrow holdings, or fill again after completion.
def test_sell_proxy_and_repeat():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent("sell"), samples(prepared))
    bars = future(prepared, opening=104)
    result = execute(order, bars, held=3)
    assert result["status"] == "partial"
    assert result["filled_qty"] == 3
    assert result["shares_delta"] == -3
    assert result["cash_delta"] > 0
    assert execute(order, bars, held=0)["status"] == "unfunded"
    assert (
        execute(order, bars, done={order["client_order_id"]})["status"]
        == "repeat_suppressed"
    )


# Intrabar touches and an unfavorable terminal close do not create fallback fills.
def test_touches_expire_without_close_fallback():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    result = execute(order, future(prepared, opening=100))
    assert result["status"] == "expired"
    assert result["filled_qty"] == 0
    assert result["touches_not_fills"] == 24


# Missing consecutive bars remain missing even if a later candle is favorable.
def test_missing_and_immature_outcomes():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    bars = future(prepared)
    assert execute(order, bars[1:])["reason"] == "missing_consecutive_execution_bar"
    result = timing.proxy_fill(
        order,
        bars,
        data_as_of=prepared["observed_at"],
        available_cash=1000,
        held_qty=10,
        cost_bps=10,
        completed_ids=set(),
    )
    assert result["status"] == "immature"
    assert result["filled_qty"] == 0


# Invalid future candle publication and duplicates cannot become precise fill evidence.
def test_execution_publication_and_duplicates():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    bars = future(prepared)
    late = deepcopy(bars)
    late[1]["available_at"] = "2026-09-04T10:00:00-04:00"
    assert execute(order, late)["reason"] == "execution_bar_not_available"
    with pytest.raises(ValueError, match="duplicate_execution_bar"):
        execute(order, [*bars, bars[0]])


# A changed quantity, limit or context cannot reuse an earlier inference permission.
def test_immutable_context_and_permission():
    prepared = timing.prepare(payload())
    changed = deepcopy(prepared)
    changed["bars"][0]["close"] = 99.5
    with pytest.raises(ValueError, match="context_hash_mismatch"):
        timing.permission(changed, intent(), samples(prepared))
    changed = deepcopy(prepared)
    changed["future_starts"].pop()
    with pytest.raises(ValueError, match="calendar_horizon_mismatch"):
        timing.permission(changed, intent(), samples(prepared))
    order = timing.permission(prepared, intent(), samples(prepared))
    order["qty"] += 1
    with pytest.raises(ValueError, match="permission_hash_mismatch"):
        execute(order, future(prepared))


# Unobserved future duplicates and bad candles cannot rewrite an already resolved proxy.
def test_execution_prefix_invariance():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    bars = future(prepared)
    resolved = execute(order, bars)
    changed = deepcopy(bars)
    changed[-1]["open"] = -1
    changed.append(changed[-1])
    assert execute(order, changed) == resolved


# A normalized portfolio may consume a price probe without invented raw share funding.
def test_price_probe_has_no_account_claims():
    prepared = timing.prepare(payload())
    order = timing.permission(prepared, intent(), samples(prepared))
    result = timing.price_opportunity(
        order, future(prepared), data_as_of=prepared["expires_at"]
    )
    assert result["status"] == "opportunity"
    assert result["proxy_price"] == 97
    assert result["proxy_at"] == "2026-09-03T10:00:00-04:00"
    assert not {
        "filled_qty",
        "requested_qty",
        "cash_delta",
        "shares_delta",
        "fees",
    } & set(result)
    funded = execute(order, future(prepared), cash=500)
    assert funded["filled_qty"] == 5


# Recomputing a content hash cannot authorize an uncompleted bar as model context.
def test_rehashed_future_context_refused():
    prepared = timing.prepare(payload())
    prepared["bars"][-1]["start"] = prepared["future_starts"][0]
    evidence = {
        key: value
        for key, value in prepared.items()
        if key not in ("context_sha256", "future_starts", "expires_at")
    }
    prepared["context_sha256"] = timing.digest(evidence)
    with pytest.raises(ValueError, match="prefix|context"):
        timing.permission(prepared, intent(), samples(prepared))
