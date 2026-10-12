"""Counterfactual views must authenticate ownership and never mutate accounts."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1.api import router
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.tests.test_strategy_simulation import publication


# Exercise the real router, authentication and integrity reader over HTTP.
def test_strategy_http_content_ownership_integrity_and_no_writes(tmp_path, monkeypatch):
    path, _, _ = publication(tmp_path)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "strategy_owner")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    before = {
        str(file): file.read_bytes() for file in tmp_path.rglob("*") if file.is_file()
    }
    target = "/api/v1/market/strategy_owner/desk/strategy-simulation/STOCK"
    owner = {"Authorization": "Bearer " + issue_user_token("strategy_owner")}
    foreign = {"Authorization": "Bearer " + issue_user_token("another_owner")}
    with TestClient(app) as client:
        assert client.get(target).status_code == 401
        assert client.get(target, headers=foreign).status_code == 403
        response = client.get(target, headers=owner)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        value = response.json()
        assert value["counterfactual"] is True
        assert value["real_orders"] is False
        assert value["ticker"] == "STOCK"
        assert value["trades"][0]["qty"] == 2
        assert value["decisions"][0]["qty"] == 4
        assert value["decisions"][0]["state"] == "partial"
        overview = client.get(target.rsplit("/", 1)[0], headers=owner)
        assert overview.status_code == 200, overview.text
        assert overview.json()["stock_overview"]["STOCK"]["holding"] == 8
        assert client.post(target, headers=owner).status_code == 405
        assert {
            str(file): file.read_bytes()
            for file in tmp_path.rglob("*")
            if file.is_file()
        } == before
        path.write_text("{}")
        corrupt = client.get(target, headers=owner)
        assert corrupt.status_code == 503
        assert corrupt.json()["detail"] == "Latest-strategy simulation unavailable."
