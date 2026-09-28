"""The personal board over HTTP carries the timed `/4` decision and its evidence.

`/desk/mine` loads today's entry-timing latch from the data root and passes
it to the board, so the page gets, per row, the timed `action`, the kept
intent, the timing state and level, the executor's band gate and both
grades; and a board-level `timing` block. A `/3` record's payload has none
of it. Needs fastapi and httpx (the backend container); skipped elsewhere.
"""

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from httpx import ASGITransport, AsyncClient  # noqa: E402

from backend.api.v1 import market  # noqa: E402
from backend.main import app  # noqa: E402
from backend.market import entry_timing  # noqa: E402
from backend.core.auth import issue_user_token  # noqa: E402
from backend.tests.test_personal_guidance_api import (  # noqa: E402
    personal_context as personal_context,
)

POLICY = "graded-equal-weight/4"


# Post the page's own request for the personal board and return its JSON.
# A POST is a write to the route's scope rules (the page's token carries
# memory:write), so the request is made with the page's scopes, not the
# read-only token the shared fixture issues for GETs.
async def _mine(auth):
    """Return the /desk/mine POST response body."""
    token = issue_user_token("desk_user", scopes=["memory:read", "memory:write"])
    headers = {**auth, "Authorization": f"Bearer {token}"}
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=headers
    ) as client:
        response = await client.post(
            "/api/v1/market/desk_user/desk/mine",
            json={"equity": 100000, "available_cash": 100000},
        )
    assert response.status_code == 200, response.text
    return response.json()


# A `/4` record with S10's level triggered and S9 still waiting: the payload
# says so row by row, and the board says it is timed and that today's latch
# was on file.
@pytest.mark.asyncio
async def test_the_desk_mine_payload_carries_the_timing(personal_context):
    record, _, now, root, auth = personal_context
    record["targets"] = {
        "policy": POLICY,
        "weights": {n: (0.0 if n == "S0" else 1 / 11) for n in record["grades"]},
    }
    record["paper"]["until_rebalance"] = 10
    record["levels"] = {n: {"rejecting_band": False} for n in record["grades"]}
    snapshot = market._live_snapshot()
    for name, quote in snapshot["quotes"].items():
        move = -0.015 if name == "S10" else -0.005
        quote["open"] = quote["last"] / (1.0 + move)
    entry_timing.update(root, snapshot, now)
    body = await _mine(auth)
    decisions = body["decisions"]
    assert decisions["timing"]["rule"] == "dip_or_close"
    assert decisions["timing"]["level"] == entry_timing.LEVEL
    assert decisions["timing"]["latched"] is True
    triggered, waiting = decisions["rows"]["S10"], decisions["rows"]["S9"]
    assert triggered["action"] == "Buy"
    assert triggered["timing"]["state"] == "triggered"
    assert triggered["move_weight"] > 0
    assert waiting["action"] == "Hold"
    assert waiting["strategy_action"] == "Buy"
    assert waiting["move_weight"] == 0
    assert waiting["timing"]["state"] == "waiting"
    assert waiting["reason"].startswith("Buy 9.1% planned: on a 15-minute close")
    for row in (triggered, waiting):
        assert row["structure_gate"] == "clear"
        assert row["grade"] == "A+"
        assert "grade_intraday" in row


# The `/3` board over HTTP is not timed and carries none of the new fields.
@pytest.mark.asyncio
async def test_a_v3_payload_carries_no_timing(personal_context):
    _, _, _, _, auth = personal_context
    body = await _mine(auth)
    assert "timing" not in body["decisions"]
    for row in body["decisions"]["rows"].values():
        assert "timing" not in row
        assert "structure_gate" not in row
