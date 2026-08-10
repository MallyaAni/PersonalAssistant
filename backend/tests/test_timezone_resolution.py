"""A place must not be stored in a zone the model invented.

The resolver's only real job is disbelief: the model is asked one geography
question, and anything it answers that is not in the IANA database is discarded.
These check that discarding, because the failure it prevents is silent — a
plausible-looking zone shifts every scheduled digest by hours and nothing in the
product looks broken.
"""

import json
from typing import Any

import pytest

from backend.agents.scout.timezones import TimezoneResolver


class _Answers:
    """A writer that returns one fixed answer."""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    def chat(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        self.calls += 1
        return {"content": json.dumps({"timezone": self.answer})}


class _Raises:
    """A writer that is down."""

    def chat(self, *args: Any, **kwargs: Any) -> dict[str, str]:
        raise RuntimeError("inference unavailable")


@pytest.mark.asyncio
async def test_a_real_zone_is_kept() -> None:
    resolved = await TimezoneResolver(_Answers("Asia/Makassar")).resolve("Canggu, Bali")
    assert resolved == "Asia/Makassar"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invented",
    [
        # Every one of these is the shape a model reaches for when it does not
        # know: a real place in a plausible format that the database has never
        # contained.
        "Asia/Canggu",
        "Indonesia/Bali",
        "GMT+8",
        "Asia/Makassar (WITA)",
        "asia/makassar",
        "",
    ],
)
async def test_an_identifier_outside_the_database_is_refused(invented: str) -> None:
    assert await TimezoneResolver(_Answers(invented)).resolve("Canggu, Bali") is None


@pytest.mark.asyncio
async def test_an_unusable_model_resolves_to_nothing_rather_than_a_guess() -> None:
    assert await TimezoneResolver(_Raises()).resolve("Canggu, Bali") is None
    assert await TimezoneResolver(None).resolve("Canggu, Bali") is None


@pytest.mark.asyncio
async def test_an_empty_place_never_reaches_the_model() -> None:
    writer = _Answers("Asia/Makassar")
    assert await TimezoneResolver(writer).resolve("   ") is None
    assert writer.calls == 0
