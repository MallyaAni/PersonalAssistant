"""The readiness endpoint: the worker's question reaches the judgement, and
only for the user whose token asks."""

import pytest
from httpx import ASGITransport, AsyncClient

from backend.core.auth import issue_user_token
from backend.main import app
from backend.services.conversation_service import ConversationService
from backend.services.readiness import Readiness


@pytest.mark.asyncio
async def test_the_endpoint_returns_the_judgement(monkeypatch):
    asked: list[tuple] = []

    async def judge(self, previous_reply, fragments, *, in_group=False, addressed_by=""):
        asked.append((previous_reply, fragments, in_group, addressed_by))
        return Readiness(False, True, "unfinished")

    monkeypatch.setattr(ConversationService, "judge_readiness", judge)
    token = issue_user_token("readiness_user", ttl_seconds=60, scopes=["chat"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/readiness",
            json={"user_id": "readiness_user", "fragments": ["ok so"], "previous_reply": "Thai?", "in_group": True, "addressed_by": "reply"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "complete": False,
        "needs_reply": True,
        "accepts_offer": False,
        "reason": "unfinished",
    }
    assert asked == [("Thai?", ["ok so"], True, "reply")]


@pytest.mark.asyncio
async def test_another_users_token_is_refused(monkeypatch):
    # With auth off every caller is the trusted local user; the refusal is
    # only meaningful when identities are enforced.
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    token = issue_user_token("someone_else", ttl_seconds=60, scopes=["chat"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/readiness",
            json={"user_id": "readiness_user", "fragments": ["hi"]},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_empty_fragments_are_rejected_by_the_schema():
    token = issue_user_token("readiness_user", ttl_seconds=60, scopes=["chat"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/readiness",
            json={"user_id": "readiness_user", "fragments": []},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_the_observe_endpoint_stores_without_answering(monkeypatch):
    seen: list[tuple] = []

    async def observe(self, user_id, query, conversation_id, metadata):
        seen.append((user_id, query, conversation_id, metadata.get("channel")))
        return "conv-9"

    monkeypatch.setattr(ConversationService, "observe", observe)
    token = issue_user_token("readiness_user", ttl_seconds=60, scopes=["chat"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/chat/observe",
            json={"user_id": "readiness_user", "query": "lunch friday?", "metadata": {"channel": "imessage_group", "group": {"speaker_user_id": "u"}}},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"conversation_id": "conv-9"}
    assert seen == [("readiness_user", "lunch friday?", None, "imessage_group")]
