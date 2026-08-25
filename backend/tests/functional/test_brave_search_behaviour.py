"""Does the first rung answer a real question? One Brave request, counted."""

from __future__ import annotations

import json
import os

import pytest

from backend.mcp.servers import internet

pytestmark = pytest.mark.asyncio


async def test_brave_answers_a_live_whats_on_question() -> None:
    if not os.getenv("BRAVE_SEARCH_API_KEY"):
        pytest.skip("no Brave key in this environment")
    payload = json.loads(await internet.search_web("events in Canggu Bali this weekend", max_results=3))
    assert payload.get("error") is None, payload
    assert payload["provider"] == "brave", payload["provider"]
    assert payload["results"], payload
    assert all(item["url"].startswith("http") and item["title"] for item in payload["results"])
