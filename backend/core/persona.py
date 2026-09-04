"""Who this person is, in a sentence, instead of a bag of tags.

Twenty interests were on file for the operator, every one of them at strength
2: salsa, bachata, east coast swing, west coast swing, line dancing, swing
dancing, dancing, live music, karaoke, breweries, wineries, chess, board
games, hiking, farmers markets, thrifting, traveling, exploring new places,
exploring new things, unique local events.

That is not twenty interests. Seven of those entries say one thing - the
person is a social dancer - and nothing in the system could tell, because a
flat list has no way to say that six of its rows are the same fact. Three
consequences, all of them things that actually went wrong:

  * A search query built from the list got six near-arbitrary tags, five of
    them variations on dancing, crowding out breweries and live music.
  * The reply prompt banned interests outright - "a standing list of
    interests with strengths in every prompt is a thumb on the scale for all
    of them", after unrelated answers came back bent toward hiking. A list
    can only be included or excluded; there is no dose.
  * "Exploring new things" read as filler beside "salsa" only because both
    had been flattened into the same kind of thing.

A characterization is dose-able where a list is not, and it is what a friend
actually knows about you. Rebuilt whenever the interests change, and not
otherwise: the key is the interests themselves, so there is no staleness to
manage and no schedule to run - saving a new interest is what makes the next
read regenerate it.
"""
from __future__ import annotations

import logging
from collections import OrderedDict
from hashlib import sha256
from typing import Any

from backend.core.prompts import load

logger = logging.getLogger(__name__)

_MAX_TOKENS = 160
# Small: one entry per person, and a person has one interest set at a time.
_CACHE_MAX = 256
_CACHED: OrderedDict[str, str] = OrderedDict()


# What the characterization is *of*. Order-independent, because the order
# interests were saved in is not part of who someone is, and a reordering
# should not spend a model call.
def _key(interests: tuple[str, ...]) -> str:
    material = "\x1f".join(sorted(str(item).strip().casefold() for item in interests if str(item).strip()))
    return sha256(material.encode("utf-8", "replace")).hexdigest()


# Forget every characterization. For tests, and for a changed prompt, which
# changes what the same interests would produce without changing the key.
def forget_personas() -> None:
    _CACHED.clear()


# One sentence describing this person, or "" when there is nothing to say or
# the call fails. Never raises: a missing characterization must cost a turn
# nothing, the way a missing interest list already costs it nothing.
async def characterize(llm: Any, interests: tuple[str, ...]) -> str:
    kept = tuple(str(item).strip() for item in interests if str(item).strip())[:60]
    if not kept or llm is None:
        return ""
    key = _key(kept)
    found = _CACHED.get(key)
    if found is not None:
        _CACHED.move_to_end(key)
        return found

    import asyncio

    listed = "\n".join(f"- {item}" for item in kept)
    try:
        answer = await asyncio.to_thread(
            llm.chat,
            [
                {"role": "system", "content": load("memory/persona")},
                {"role": "user", "content": f"What they like:\n{listed}"},
            ],
            _MAX_TOKENS,
        )
    except Exception:
        logger.warning("Could not characterize the person; keeping the plain list", exc_info=True)
        return ""
    written = " ".join(str((answer or {}).get("content") or "").split())[:400]
    if not written:
        return ""
    _CACHED[key] = written
    _CACHED.move_to_end(key)
    while len(_CACHED) > _CACHE_MAX:
        _CACHED.popitem(last=False)
    return written
