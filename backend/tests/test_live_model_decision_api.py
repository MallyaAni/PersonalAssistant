"""The owner receives one private saved numeric plan beside broker executions."""

from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app


# Keep broker reads observable without permitting any order-writing methods.
class ReadOnlyBroker:
    # Return account values that cannot replace the saved model decision basis.
    def account(self):
        return SimpleNamespace(equity=1200.0, last_equity=1100.0, cash=100.0)

    # Return the current broker book independently of the saved decision book.
    def positions(self):
        return []

    # Return actual open orders without constructing new model instructions.
    def open_orders(self):
        return []

    # Supply actual activity separately from the admitted decision projection.
    def fill_activity(self, session):
        return {"session": str(session), "complete": True, "fills": []}


# Exercise the actual owner route and prove its projection uses the same saved plan.
@pytest.mark.asyncio
@pytest.mark.parametrize("unreadable_record", [False, True])
async def test_private_numeric_projection_and_owner_isolation(
    tmp_path, monkeypatch, unreadable_record
):
    from backend.agents.trading.desk import paper
    from backend.market import live_model_decision

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    broker = ReadOnlyBroker()
    reads = []

    # Fail if an unauthorized request reaches the private broker boundary.
    def client():
        reads.append("broker")
        return broker

    record = {"session": "2026-10-13", "grades": {"ALAB": {"grade": "A"}}}
    plan = {"policy": "grade-led-learned-sizing/1", "orders": []}
    projected = {
        "version": live_model_decision.VERSION,
        "status": "stale",
        "rows": {"ALAB": {"action": None, "qty": None, "when": None}},
    }

    # Assert identity of the saved record and plan rather than re-deriving quantities.
    def project(root, saved, execution, now, *, journal):
        assert root == tmp_path
        assert saved == (
            {"reason": "Saved model record could not be read"}
            if unreadable_record
            else record
        )
        assert execution is plan
        assert now.tzinfo is not None
        assert journal == []
        return projected

    # A damaged saved file must withhold decisions without hiding the actual account.
    def latest(root):
        if unreadable_record:
            raise ValueError("damaged saved record")
        return record, None

    monkeypatch.setattr(market.alpaca_trading, "client_from_env", client)
    monkeypatch.setattr(
        paper,
        "load_state",
        lambda root: SimpleNamespace(start_equity=1000.0, journal=[]),
    )
    monkeypatch.setattr(market, "_paper_plan", lambda *args, **kwargs: plan)
    monkeypatch.setattr(market.deskrecord, "latest_pair", latest)
    monkeypatch.setattr(live_model_decision, "read", project)
    monkeypatch.setattr(live_model_decision, "recorded_fills", lambda journal, now: [])
    owner = issue_user_token("desk_user", scopes=["memory:read"])
    foreign = issue_user_token("outsider", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as http:
        accepted = await http.get(
            "/api/v1/market/desk_user/desk/paper",
            headers={"Authorization": f"Bearer {owner}"},
        )
        rejected = await http.get(
            "/api/v1/market/desk_user/desk/paper",
            headers={"Authorization": f"Bearer {foreign}"},
        )
        anonymous = await http.get("/api/v1/market/desk_user/desk/paper")
    assert accepted.status_code == 200, accepted.text
    assert accepted.headers["cache-control"] == "private, no-store"
    assert accepted.json()["model_decisions"] == projected
    assert accepted.json()["plan"] == plan
    assert accepted.json()["recorded_fills"] == []
    assert accepted.json()["equity"] == 1200.0
    assert rejected.status_code == 403
    assert anonymous.status_code == 401
    assert reads == ["broker"]
