"""Research evidence reaches the desk without replacing any account or policy."""

import json
from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient

from backend.agents.trading.desk import paper
from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.main import app
from backend.market import board_paper, neural_study, opportunity_shadow
from backend.tests.test_market_desk_api import _write


# Prove authenticated delivery preserves both persisted paper accounts.
@pytest.mark.asyncio
async def test_research_results_are_visible_without_adopting_them(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "study_user")
    _write(tmp_path, "2026-09-18", {"AAPL": "A+"}, [("AAPL", 0.1)], [])
    before = board_paper.initialize(tmp_path, 100000)
    nightly = opportunity_shadow.initialize(
        tmp_path / "desk/ml-forward", ("AAPL", "SPY"), "frozen", datetime.now(UTC)
    )
    artifact = json.loads(neural_study.FILE.read_text())
    headers = {"Authorization": f"Bearer {issue_user_token('study_user')}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        response = await client.get("/api/v1/market/study_user/desk")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["current_policy"] == paper.POLICY_VERSION
        assert payload["neural_study"]["tables"] == artifact["tables"]
        assert payload["neural_study"]["status"] == "research_only_not_adopted"
        assert payload["neural_study"]["provenance"]["training_source_revision"]
        assert payload["ml_forward"]["accounts"]["neural@10bps"]["equity"] == 100000
        denied = await client.get("/api/v1/market/someone_else/desk")
        assert denied.status_code in (403, 404)
    assert board_paper.latest(tmp_path) == before
    assert opportunity_shadow.latest(tmp_path / "desk/ml-forward") == nightly
