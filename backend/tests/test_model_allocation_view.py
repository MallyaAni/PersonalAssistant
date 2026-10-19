"""Published strategy percentages never depend on current paper or personal accounts."""

from copy import deepcopy
from datetime import datetime

import pytest

from backend.market import model_allocation_view as view
from backend.tests.test_live_model_decision import NOW, admitted


# Return authenticated targets, including zero, without loading an account.
def test_original_percentages_are_account_independent(monkeypatch):
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    record, _, _, _ = admitted(monkeypatch)
    before = deepcopy(record)

    # Any current-account access violates the shared allocation reader's contract.
    def forbidden(*args, **kwargs):
        pytest.fail("Published model percentages must not load a current account")

    monkeypatch.setattr(paper, "load_state", forbidden)
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    result = view.read("unused", record, NOW)
    assert result["status"] == "available"
    assert result["basis"] == (
        "original_published_strategy_allocation_not_trade_quantity"
    )
    assert result["record_sha256"] == "a" * 64
    assert result["rows"] == {
        name: {"target_weight": float(value)}
        for name, value in record["targets"]["weights"].items()
    }
    assert result["rows"]["DDD"]["target_weight"] == 0
    assert result["rows"]["BBB"]["target_weight"] == .25
    assert record == before


# Never expose expired percentages as a current allocation.
def test_expired_plan_has_no_current_sizes(monkeypatch):
    record, _, _, _ = admitted(monkeypatch)

    # Expiry needs no expensive source/model artifact read.
    def forbidden(*args):
        pytest.fail("Expired allocations need no source materialization")

    monkeypatch.setattr(view.live_model_decision, "_authenticate", forbidden)
    result = view.read(
        "unused", record, datetime.fromisoformat("2026-10-19T18:00:00-04:00")
    )
    assert result["status"] == "stale"
    assert result["rows"] == {}
    assert "expired" in result["reason"]


# Preserve original-receipt validation for every displayed numeric target.
@pytest.mark.parametrize(
    ("field", "value"),
    [("weight", True), ("weight", float("nan")), ("weight", -0.1),
     ("weight", 1.1), ("policy", "other"), ("source", "0" * 64)],
)
def test_corrupt_saved_allocation_is_unavailable(monkeypatch, field, value):
    record, _, _, _ = admitted(monkeypatch)
    if field == "weight":
        record["targets"]["weights"]["BBB"] = value
    elif field == "policy":
        record["targets"]["policy"] = value
    else:
        record["paper"]["joint_funded"]["receipt"]["source_sha256"] = value
    result = view.read("unused", record, NOW)
    assert result["status"] == "unavailable"
    assert result["rows"] == {}


# The real authenticated HTTP route rejects foreign readers and never consults a broker.
@pytest.mark.asyncio
async def test_allocation_http_owner_and_account_independence(monkeypatch, tmp_path):
    from httpx import ASGITransport, AsyncClient

    from backend.api.v1 import market_allocation
    from backend.config.settings import settings
    from backend.core.auth import issue_user_token
    from backend.main import app
    from backend.market import alpaca_trading

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    record, _, _, _ = admitted(monkeypatch)
    monkeypatch.setattr(
        market_allocation.deskrecord, "latest_pair", lambda root: (record, None)
    )
    result = view.read(tmp_path, record, NOW)
    calls = []

    # Record the owner-only projection with its exact original record.
    def project(root, saved, now):
        assert root == tmp_path
        assert saved is record
        assert now.utcoffset() is not None
        calls.append("project")
        return result

    # A GET of shared strategy percentages cannot make a broker call.
    def forbidden():
        pytest.fail("Allocation HTTP route accessed a broker")

    monkeypatch.setattr(view, "read", project)
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    url = "/api/v1/market/desk_user/desk/model-allocation"
    owner = issue_user_token("desk_user", scopes=["memory:read"])
    other = issue_user_token("outsider", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        accepted = await client.get(
            url, headers={"Authorization": f"Bearer {owner}"}
        )
        foreign = await client.get(
            url, headers={"Authorization": f"Bearer {other}"}
        )
        anonymous = await client.get(url)
    assert accepted.status_code == 200
    assert accepted.json() == result
    assert accepted.headers["cache-control"] == "private, no-store"
    assert foreign.status_code == 403
    assert anonymous.status_code == 401
    assert calls == ["project"]
