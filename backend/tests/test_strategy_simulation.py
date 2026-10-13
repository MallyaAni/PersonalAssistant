"""Counterfactual charts must retain funded decisions and original timing."""

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.market.strategy_simulation import (
    DIRECTORY,
    POLICY,
    SCHEMA,
    continue_account,
    project,
    read,
)


# Reject economic or artifact changes even when source approval is renewed.
@pytest.mark.parametrize(
    "changed", [None, "cost_bps", "policy", "model", "risk", "timing"]
)
def test_approval_only_configuration_preserves_original_economic_binding(
    tmp_path, changed
):
    from backend.cli.market_strategy_simulation import prior_configuration

    original = {
        "release_receipt_sha256": "old",
        "cost_bps": 10,
        "policy": POLICY,
        "model": "frozen-model",
        "risk": "frozen-bank",
        "timing": "frozen-timing",
    }
    path = tmp_path / "original-config.json"
    raw = json.dumps(original).encode()
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    updated = {**original, "release_receipt_sha256": "reviewed-correction"}
    if changed is not None:
        updated[changed] = "changed"
        with pytest.raises(ValueError, match="Only source-release approval"):
            prior_configuration(updated, digest, path)
    else:
        prior_configuration(updated, digest, path)
        with pytest.raises(ValueError, match="Original continuation configuration"):
            prior_configuration(updated, digest, None)
        with pytest.raises(ValueError, match="evidence hash differs"):
            prior_configuration(updated, "0" * 64, path)
    assert path.read_bytes() == raw


# Build a carried account with predecessor trades and a partially executed trim.
def account():
    order = {
        "client_order_id": "trim-1",
        "session": "2026-09-23",
        "execute_on": "2026-09-24",
        "symbol": "STOCK",
        "side": "sell",
        "qty": 4,
        "reason": "joint net-growth allocation",
        "execution_timing": "dip_or_close",
    }
    result = {
        "policy": POLICY,
        "cost_bps": 10,
        "holding_start": "2026-09-23",
        "last": "2026-09-24",
        "initial_cash": 100000,
        "nightlies": [
            {
                "session": "2026-09-23",
                "at": "2026-09-23T16:01:00-04:00",
                "entry": {
                    "policy": POLICY,
                    "equity": 1000,
                    "selected_targets": {"weights": {"STOCK": 0.2, "EMPTY": 0}},
                    "actions": [
                        {"ticker": "STOCK", "action": "trim", "last_close": 100}
                    ],
                },
            }
        ],
        "intents": [
            order,
            {**order, "client_order_id": "old", "session": "2026-09-22"},
        ],
        "fills": [
            {
                "client_order_id": "old",
                "at": "2026-09-23T13:30:00Z",
                "symbol": "STOCK",
                "filled_qty": 10,
                "price": 99,
                "fee": 0.99,
                "status": "filled",
            },
            {
                "client_order_id": "trim-1",
                "at": "2026-09-24T13:45:00Z",
                "symbol": "STOCK",
                "side": "sell",
                "filled_qty": 2,
                "price": 101,
                "fee": 0.202,
                "status": "partial",
            },
        ],
        "sessions": [
            {
                "session": "2026-09-23",
                "nav": 1000,
                "cash": 0,
                "holdings": {"STOCK": 10},
            },
            {
                "session": "2026-09-24",
                "nav": 1010,
                "cash": 202,
                "holdings": {"STOCK": 8},
            },
        ],
    }
    result["nightlies"].append(
        {
            **deepcopy(result["nightlies"][0]),
            "session": "2026-09-24",
            "at": "2026-09-24T16:01:00-04:00",
        }
    )
    return result


# Never relabel the predecessor prefix or a partial simulated execution as a full sale.
def test_projection_preserves_funded_quantities_times_and_empty_names():
    source = account()
    original = deepcopy(source)
    result = project(source, {"cost_bps": 10})
    stock = result["tickers"]["STOCK"]
    assert stock["decisions"][0]["action"] == "TRIM"
    assert stock["decisions"][0]["qty"] == 4
    assert stock["decisions"][0]["weight"] == 0.4
    assert len(stock["trades"]) == 1
    assert stock["trades"][0]["qty"] == 2
    assert stock["trades"][0]["weight"] == 0.202
    assert stock["trades"][0]["at"] == "2026-09-24T13:45:00+00:00"
    assert result["tickers"]["EMPTY"]["trades"] == []
    assert result["counterfactual"] is True
    assert result["real_orders"] is False
    assert result["starting_holdings"] == {"STOCK": 10}
    assert source == original


# A size or execution clock inconsistent with its decision must fail publication.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("filled_qty", 5),
        ("price", -1),
        ("at", "2026-09-23T13:45:00Z"),
        ("at", "2026-09-24T13:45:00"),
        ("symbol", "EMPTY"),
        ("side", "buy"),
    ],
)
def test_invalid_simulated_execution_is_not_displayed(field, value):
    source = account()
    source["fills"][-1][field] = value
    with pytest.raises(ValueError, match="(?i)simulation|amount|instant"):
        project(source, {"cost_bps": 10})


# Another allocator or a winning cost must not appear as the installed strategy.
@pytest.mark.parametrize(("field", "value"), [("policy", "old"), ("cost_bps", 0)])
def test_projection_refuses_policy_or_cost_substitution(field, value):
    source = account()
    source[field] = value
    with pytest.raises(ValueError, match="strategy and simulation costs"):
        project(source, {"cost_bps": 10})


# Keep expired planned quantities without drawing them as simulated trades.
def test_missing_price_expiry_keeps_the_decision_unexecuted():
    source = account()
    source["fills"][-1].update(status="expired", filled_qty=0, price=None, fee=0)
    value = project(source, {"cost_bps": 10})["tickers"]["STOCK"]
    assert value["trades"] == []
    assert value["decisions"][0]["qty"] == 4
    assert value["decisions"][0]["executed_qty"] == 0
    assert value["decisions"][0]["state"] == "not_executed"


# Build a published file without involving the real market root or paper history.
def publication(root):
    config = {"policy": POLICY, "cost_bps": 10}
    config_bytes = json.dumps(config).encode()
    config_sha = hashlib.sha256(config_bytes).hexdigest()
    config_path = root / "desk/learned-holding/config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_bytes(config_bytes)
    from backend.market import strategy_simulation

    value = project(
        account(),
        {
            "cost_bps": 10,
            "config_sha256": config_sha,
            "projection_source_sha256": hashlib.sha256(
                Path(strategy_simulation.__file__).read_bytes()
            ).hexdigest(),
        },
    )
    stock = {
        "splits": [],
        **value["tickers"]["STOCK"],
        **{
            key: value[key]
            for key in (
                "schema",
                "policy",
                "start",
                "through",
                "provenance",
                "counterfactual",
                "real_orders",
            )
        },
    }
    directory = root / DIRECTORY
    version = "a" * 64
    (directory / version).mkdir(parents=True)
    payload = json.dumps(stock).encode()
    path = directory / version / "STOCK.json"
    path.write_bytes(payload)
    manifest = {
        "schema": SCHEMA,
        "version": version,
        "config_sha256": config_sha,
        "cost_bps": 10,
        "files": {"STOCK": hashlib.sha256(payload).hexdigest()},
    }
    summary = json.dumps(
        {key: data for key, data in value.items() if key != "tickers"}
    ).encode()
    (directory / version / "summary.json").write_bytes(summary)
    manifest["files"]["summary"] = hashlib.sha256(summary).hexdigest()
    (directory / "manifest.json").write_text(json.dumps(manifest))
    return path, stock, manifest


# Repeated reads preserve the exact projection and every stored byte.
def test_published_view_is_read_only_and_case_normalized(tmp_path):
    publication(tmp_path)
    before = {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    }
    assert read(tmp_path, "stock")["trades"][0]["qty"] == 2
    assert read(tmp_path, "STOCK") == read(tmp_path, "stock")
    assert {
        str(path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()
    } == before


# Never display stale configuration, corrupted bytes or another stock's payload.
@pytest.mark.parametrize("failure", ["config", "bytes", "real", "ticker", "path"])
def test_read_refuses_invalid_or_misattributed_projection(tmp_path, failure):
    path, stock, manifest = publication(tmp_path)
    if failure == "config":
        (tmp_path / "desk/learned-holding/config.json").write_text("{}")
    elif failure == "bytes":
        path.write_text("{}")
    elif failure in ("real", "ticker"):
        stock["real_orders" if failure == "real" else "ticker"] = (
            True if failure == "real" else "OTHER"
        )
        payload = json.dumps(stock).encode()
        path.write_bytes(payload)
        manifest["files"]["STOCK"] = hashlib.sha256(payload).hexdigest()
        (tmp_path / DIRECTORY / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Simulation"):
        read(tmp_path, "../STOCK" if failure == "path" else "STOCK")


# A continuation may add only later sessions and cannot replace its carried seed.
def test_continuation_requires_the_exact_parent_and_preserves_old_records():
    parent = account()
    original = deepcopy(parent)
    child = {
        "policy": POLICY,
        "cost_bps": 10,
        "counterfactual": True,
        "base_models_fitted": 0,
        "original_account_replayed": False,
        "parent_account_sha256": "parent",
        "first": parent["last"],
        "last": "2026-09-25",
        "intents": [],
        "fills": [],
        "sessions": [
            parent["sessions"][-1],
            {**parent["sessions"][-1], "session": "2026-09-25"},
        ],
        "nightlies": [
            parent["nightlies"][-1],
            {**parent["nightlies"][-1], "session": "2026-09-25"},
        ],
    }
    result = continue_account(parent, child, "parent")
    assert parent == original
    assert result["sessions"][:-1] == parent["sessions"]
    assert result["nightlies"][:-1] == parent["nightlies"]
    child["sessions"][0] = {**child["sessions"][0], "cash": 999}
    with pytest.raises(ValueError, match="carried-account"):
        continue_account(parent, child, "parent")


# Split metadata must be authenticated and cannot change original trade quantities.
def test_split_projection_requires_full_cohort_and_preserves_trades(tmp_path):
    from backend.cli.market_strategy_simulation import attach_splits

    value = project(account(), {"cost_bps": 10})
    before = deepcopy(value["tickers"]["STOCK"]["trades"])
    path = tmp_path / "splits.json"
    raw = json.dumps(
        {"STOCK": [{"date": "2026-09-24", "ratio": 4}], "EMPTY": []}
    ).encode()
    path.write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    attach_splits(value, path, sha)
    assert value["tickers"]["STOCK"]["trades"] == before
    assert value["tickers"]["STOCK"]["splits"] == [{"date": "2026-09-24", "ratio": 4}]
    path.write_text("{}")
    with pytest.raises(ValueError, match="evidence hash"):
        attach_splits(value, path, sha)


# Missing stocks, duplicate split events and impossible ratios refuse publication.
@pytest.mark.parametrize(
    "events",
    [
        {"STOCK": []},
        {"STOCK": [{"date": "2026-09-24", "ratio": -4}], "EMPTY": []},
        {"STOCK": [{"date": "2026-09-24", "ratio": 4}] * 2, "EMPTY": []},
    ],
)
def test_invalid_split_metadata_is_not_published(tmp_path, events):
    from backend.cli.market_strategy_simulation import attach_splits

    path = tmp_path / "splits.json"
    raw = json.dumps(events).encode()
    path.write_bytes(raw)
    with pytest.raises(ValueError, match="cohort|Split event|simulation amount"):
        attach_splits(
            project(account(), {"cost_bps": 10}), path, hashlib.sha256(raw).hexdigest()
        )
