"""Historical share amounts are owner-only, authenticated and read-only over HTTP."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.v1.api import router
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.tests.test_live_model_history_reader import publication


# Exercise ownership, quantities, integrity errors and no writes through HTTP.
def test_current_model_history_http_amounts_ownership_and_no_writes(
    tmp_path, monkeypatch
):
    expected, path = publication(tmp_path)
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "history_owner")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    target = "/api/v1/market/history_owner/desk/live-model-history/AAA"
    owner = {"Authorization": "Bearer " + issue_user_token("history_owner")}
    foreign = {"Authorization": "Bearer " + issue_user_token("another_owner")}
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    with TestClient(app) as client:
        assert client.get(target).status_code == 401
        assert client.get(target, headers=foreign).status_code == 403
        response = client.get(target, headers=owner)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.json() == {"user_id": "history_owner", **expected}
        assert response.json()["decisions"][0]["qty"] == 5
        assert client.post(target, headers=owner).status_code == 405
        assert {
            str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()
        } == before
        path.write_text("{}")
        broken = client.get(target, headers=owner)
        assert broken.status_code == 503
        assert broken.json()["detail"] == "Live-model historical sizing unavailable."
