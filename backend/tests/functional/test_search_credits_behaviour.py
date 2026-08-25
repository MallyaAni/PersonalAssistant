"""Does the meter read a real number from the provider?

The tool exists so "are we about to run out of search credits?" has an
answer with a number in it. Asked of the real usage endpoint: a GET that
spends nothing.
"""

from __future__ import annotations

import json
import os

import pytest

from backend.mcp.servers import internet

pytestmark = pytest.mark.asyncio


async def test_the_meter_reads_the_providers_own_numbers() -> None:
    if not os.getenv("SEARCH_API_KEY"):
        pytest.skip("no search key in this environment")
    payload = json.loads(await internet.search_credits())
    assert payload.get("error") is None, payload
    assert isinstance(payload["spent"], int) and payload["spent"] >= 0
    assert isinstance(payload["limit"], int) and payload["limit"] > 0
    assert payload["remaining"] == max(0, payload["limit"] - payload["spent"])
