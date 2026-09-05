"""The run worker's way to the chat loop: the API, with the person's token.

The worker is another process and does not build the assistant; it asks the
API to decide and apply one step at a time, exactly as the scheduled-task
runner fires a task through `/api/v1/chat`. The token is short-lived and
holds only the `chat` scope, minted for the run's own principal, so the
continuation acts as that person and as nothing more.
"""

from __future__ import annotations

from typing import Any

import httpx

from backend.config.settings import settings
from backend.core.auth import SCOPE_CHAT, issue_user_token

# One step's wall time at the boundary: a search is seconds, a slow tool
# tens; anything past this is the step's own timeout to have taken.
STEP_TIMEOUT_SECONDS = 180.0
TOKEN_TTL_SECONDS = 300


class HttpStepClient:
    """Decide and apply chat steps through the API."""

    def __init__(self, base_url: str | None = None, timeout: float = STEP_TIMEOUT_SECONDS) -> None:
        self.base_url = (base_url or settings.IMESSAGE_CHAT_BASE_URL).rstrip("/")
        self.timeout = timeout

    def _headers(self, user_id: str) -> dict[str, str]:
        token = issue_user_token(user_id, ttl_seconds=TOKEN_TTL_SECONDS, scopes=[SCOPE_CHAT])
        return {"Authorization": f"Bearer {token}"}

    async def _post(self, user_id: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/v1/chat/{user_id}/steps/{path}",
                json=body,
                headers=self._headers(user_id),
            )
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def decide(self, user_id: str, query: str, lines: list[str], remaining_seconds: float) -> dict[str, Any]:
        return await self._post(
            user_id, "decide",
            {"query": query, "lines": list(lines), "remaining_seconds": float(remaining_seconds)},
        )

    async def apply(self, user_id: str, query: str, conversation_id: str | None, call: dict[str, Any]) -> dict[str, Any]:
        return await self._post(
            user_id, "apply",
            {"query": query, "conversation_id": conversation_id, "call": call},
        )
