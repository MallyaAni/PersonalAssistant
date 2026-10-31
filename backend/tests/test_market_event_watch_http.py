"""The event-watch route is fixed before the desk's dated-session wildcard."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from backend.api.v1 import event_watch as route
from backend.api.v1 import market
from backend.config.settings import settings
from backend.core.auth import issue_user_token


# The scan file the nightly writes for one session.
def _scan(root: Path, asof: str) -> None:
    folder = root / "research" / "event-watch" / f"asof={asof}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "event_watch.json").write_text(
        json.dumps(
            {
                "version": "event-watch/1",
                "asof": asof,
                "rule": {"qoq_drop": -0.2, "price_window": 5},
                "calendar": {"next_election": "2026-11-03"},
                "shocks": [{"ticker": "GOOGL"}],
                "price_shocks": [{"ticker": "FFIV"}],
                "contagion": [],
                "names": [{"ticker": "GOOGL"}],
            }
        ),
        encoding="utf-8",
    )


# Owner content, foreign refusal and the fixed path against the wildcard.
class EventWatchHTTPTests(IsolatedAsyncioTestCase):
    async def test_owner_reads_the_scan_and_foreign_user_is_refused(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            _scan(root, "2026-10-30")
            app = FastAPI()
            # Same order as backend/api/v1/api.py: the fixed path first.
            app.include_router(route.router, prefix="/api/v1")
            app.include_router(market.router, prefix="/api/v1")
            with (
                patch.object(settings, "AUTH_REQUIRED", True),
                patch.object(settings, "MARKET_DESK_USER", "desk_user"),
                patch.object(settings, "MARKET_DATA_ROOT", str(root)),
                patch.object(
                    market.deskrecord,
                    "latest_pair",
                    return_value=({"session": "2026-10-30"}, None),
                ),
            ):
                owner = issue_user_token("desk_user", scopes=["memory:read"])
                other = issue_user_token("other_user", scopes=["memory:read"])
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    url = "/api/v1/market/desk_user/desk/event-watch"
                    response = await client.get(
                        url, headers={"Authorization": "Bearer " + owner}
                    )
                    assert response.status_code == 200
                    body = response.json()
                    assert body["user_id"] == "desk_user"
                    assert body["event_watch"]["asof"] == "2026-10-30"
                    assert not body["event_watch"]["stale"]
                    foreign = await client.get(
                        url, headers={"Authorization": "Bearer " + other}
                    )
                    assert foreign.status_code == 403
                    anonymous = await client.get(url)
                    assert anonymous.status_code == 401
