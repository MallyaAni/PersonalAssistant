"""The weather tool answers for the places people actually write, from the
official US source, without asking for a ZIP code.

2026-08-27: "what's the weather in DC this weekend?" was answered with a
request for a ZIP code - the geocoder had nothing for "Washington, DC" -
and then with "violent showers" for a 29% day and "overcast" for a
mostly-sunny Saturday. Needs the internet; runs on spark1 like the rest.
"""

from __future__ import annotations

import json

import re

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



_TEMPERATURE = re.compile(r"\b\d{2,3}\s*°?\s*[FfCc]?\b")


async def test_with_no_place_known_the_reply_asks_instead_of_reporting_somewhere(llm) -> None:
    """The live group turn of 2026-08-28: "hows the weather here today?" with no
    place on record was answered for Here, Somalia. The tool now refuses a
    non-place; the reply, handed that refusal, must ask where they are and
    report no weather at all."""
    from backend.agents.graph import _build_system_prompt, turn_context_messages

    context = {
        "channel": "imessage",
        "tool_results": [
            {
                "tool": "get_weather",
                "arguments": {"place": "here", "days": 1},
                "result": {"error": "no_place", "place": "here", "message": "No place was named and none is on record; ask where they are rather than guessing."},
            }
        ],
    }
    messages = [{"role": "system", "content": _build_system_prompt(context)}]
    messages.extend(turn_context_messages(context))
    messages.append({"role": "user", "content": "hows the weather here today?"})
    text = str(llm.chat(messages, 300, None, 0.0)["content"]).strip()
    lowered = text.casefold()
    assert "?" in text, text
    assert any(word in lowered for word in ("where", "which city", "what city", "location", "town")), text
    assert not _TEMPERATURE.search(text), text
    assert not any(word in lowered for word in ("sunny", "clear sky", "humidity", "rain", "cloudy")), text
