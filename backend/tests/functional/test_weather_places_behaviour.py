"""The weather tool answers for the places people actually write, from the
official US source, without asking for a ZIP code.

2026-08-27: "what's the weather in DC this weekend?" was answered with a
request for a ZIP code - the geocoder had nothing for "Washington, DC" -
and then with "violent showers" for a 29% day and "overcast" for a
mostly-sunny Saturday. Needs the internet; runs on spark1 like the rest.
"""

from __future__ import annotations

import json

import pytest

from backend.mcp.servers.internet import get_weather

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize("written", ["Washington, DC", "DC", "Washington DC", "20024"])
async def test_dc_however_written_gets_a_forecast(written: str) -> None:
    payload = json.loads(await get_weather(written, days=4))
    assert "error" not in payload, payload
    assert "Washington" in payload["place"], payload["place"]
    assert len(payload["daily"]) == 4 and all(row.get("weekday") for row in payload["daily"]), payload["daily"]
    assert payload["covers"], payload


async def test_a_us_place_comes_from_the_national_weather_service() -> None:
    payload = json.loads(await get_weather("Arlington, Virginia", days=2))
    assert "weather.gov" in payload["source"], payload["source"]
    first = payload["daily"][0]
    assert first["high"] is not None and first["conditions"], first


async def test_a_state_abbreviation_picks_the_right_city() -> None:
    payload = json.loads(await get_weather("Arlington, TX", days=1))
    assert "Texas" in payload["place"], payload["place"]


async def test_elsewhere_still_answers_from_open_meteo() -> None:
    payload = json.loads(await get_weather("Canggu, Bali", days=1, units="metric"))
    assert "error" not in payload and payload["source"] == "open-meteo.com", payload
