"""Collect the tapbacks left on digest bubbles.

Apple gives no callback when someone reacts to a message, so this is a poll: ask
the Mac about the bubbles still awaiting an opinion, and write back whatever it
reports. It runs on the discovery worker's own cadence rather than on a schedule
of its own, because a reaction is worth reading soon and never urgently.

The question asked is deliberately closed. The bridge is handed the identifiers
of messages it sent and answers only about those, so this cannot become a way to
read what anyone said — the difference between "did they react to the pottery
class" and "what is on this Mac" is the whole privacy story of the feature.

A reaction changes nothing today. It is recorded, and nothing in ranking reads
it: the first weeks of a feedback signal are worth having before anything acts
on them, and a loop trained on a handful of tapbacks would learn noise.
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime

from backend.core.logging_config import get_logger
from backend.discovery.feedback import DISLIKED, LIKED, SentFindRepository

logger = get_logger(__name__)

# Reading reactions asks the bridge about specific messages, so the batch is
# bounded by what fits one tool call rather than by cost.
MAX_GUIDS_PER_POLL = 200

type ToolInvoker = Callable[[str, dict[str, object]], Awaitable[object]]


class ReactionCollector:
    """Ask the bridge what came back, and record it."""

    def __init__(
        self,
        sent_finds: SentFindRepository,
        invoke_tool: ToolInvoker,
        tool_name: str = "read_reactions",
    ) -> None:
        self.sent_finds = sent_finds
        self.invoke_tool = invoke_tool
        self.tool_name = tool_name

    # One pass. Returns how many reactions were newly recorded, so a caller can
    # log something meaningful without reading the table again.
    async def collect(self) -> int:
        guids = await self.sent_finds.awaiting_reaction(limit=MAX_GUIDS_PER_POLL)
        if not guids:
            return 0
        try:
            answer = await self.invoke_tool(
                self.tool_name, {"message_guids": list(guids)}
            )
        except Exception:
            # An unreachable Mac, a bridge without the tool, a refused call. All
            # of them mean "no feedback this time", and none of them are worth
            # failing a worker tick for.
            return 0
        recorded = 0
        for entry in _reactions(answer):
            guid = entry.get("message_guid")
            reaction = entry.get("reaction")
            if not isinstance(guid, str) or reaction not in (LIKED, DISLIKED):
                continue
            if await self.sent_finds.record_reaction(guid, reaction, _at(entry)):
                recorded += 1
        if recorded:
            logger.info("discovery_reactions_recorded", extra={"count": recorded})
        return recorded


# The reaction list out of whatever the tool boundary handed back.
#
# The bridge answers with JSON text, the invocation service wraps it, and a test
# may pass the structure directly. Anything unreadable is no reactions, which is
# the same outcome as a Mac that has nothing to report.
def _reactions(answer: object) -> list[dict[str, object]]:
    payload: object = answer
    if not isinstance(payload, (dict, list)):
        text = payload if isinstance(payload, str) else getattr(payload, "content", "")
        if not isinstance(text, str) or not text.strip():
            return []
        try:
            payload = json.loads(text)
        except ValueError:
            return []
    if isinstance(payload, dict):
        payload = payload.get("reactions", [])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


# When the reaction happened, if the bridge said and said it readably.
def _at(entry: dict[str, object]) -> datetime | None:
    raw = entry.get("at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
