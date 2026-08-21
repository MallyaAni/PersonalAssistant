"""The message itself, written rather than assembled.

For most of this system's life the digest was built from typed records by
`discovery/digest.py`, and the reason was a good one: page text is untrusted,
and this string leaves the machine to third parties over a channel that cannot
be unsent. A fixed shape cannot be talked into saying something else.

What that bought in safety it paid for in reading. Every digest opened with the
same six words, every find was a bullet with a colon, and nothing in it sounded
like it had been written by anything that had looked at the finds. A weekly
message that reads like a form letter gets the same attention as a form letter.

So the prose is the model's now, and the boundary moved rather than went away:

- **no address is ever written by the model.** It is not asked for one, the
  schema has nowhere to put one, and the link under each find is attached from
  the typed record afterwards. A hostile page can influence how its own find is
  described — exactly as it always could — and cannot put an address in a
  message;
- **the clock is not the model's to compute.** Each find arrives with its `when`
  already rendered in the reader's timezone by `digest._format_when`, whose
  date-only handling was hard-won: an event listed for Oct 3 was once announced
  as "Fri Oct 2, 8:00pm" because a date with no time had been shifted into a
  zone. The model is told to reproduce that text exactly, and a functional test
  asserts it did. A 4B model recomputing a weekday is a wrong appointment, and a
  wrong appointment is worse than no message;
- **it cannot invent a find.** Lines are returned against the indices it was
  given, and an index that was not offered is dropped.

The tone is deliberate and measured rather than asked for once and hoped at. A
digest should sound like a friend who knows what you like and is pleased to have
found these — not like marketing, which is what "enthusiastic" degrades into
when a model is left to interpret it alone. `test_digest_writing.py` holds both
ends: warmth that survives, and hype that does not.
"""

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any

from backend.core.interfaces import TextWriter
from backend.core.prompts import render

# One opening line. Long enough to say something about this batch, short enough
# that the first find is visible without scrolling on a phone.
MAX_GREETING_CHARS = 110

# One line per find. This is the sentence that has to make someone decide, and
# it sits under a name and a date they can already see.
MAX_LINE_CHARS = 200

# How many lines the model may write. Matches the delivery cap rather than
# exceeding it: a line written for a find that will not be sent is a wasted
# generation, and one written for a find that does not exist is worse.
MAX_LINES = 5

_URL_IN_TEXT = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class Find:
    """One find as the writer sees it: typed facts, no page text."""

    index: int
    name: str
    # What the describing step made of it, which may be nothing.
    description: str | None
    # Already rendered in the reader's zone. Reproduced, never recomputed.
    when: str | None
    place: str | None


@dataclass(frozen=True, slots=True)
class WrittenLine:
    """One find's line, and the link that belongs under it."""

    index: int
    text: str


@dataclass(frozen=True, slots=True)
class WrittenDigest:
    """The model's prose for one message."""

    greeting: str
    lines: tuple[WrittenLine, ...]


def _schema(count: int) -> dict[str, Any]:
    return {
        "title": "Digest",
        "type": "object",
        "additionalProperties": False,
        "required": ["greeting", "lines"],
        "properties": {
            "greeting": {
                "type": "string",
                "minLength": 8,
                "maxLength": MAX_GREETING_CHARS,
            },
            "lines": {
                "type": "array",
                "maxItems": MAX_LINES,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["index", "text"],
                    "properties": {
                        # Bounded to what was offered, so a line cannot be
                        # returned for a find that does not exist.
                        "index": {"type": "integer", "minimum": 0, "maximum": count},
                        "text": {
                            "type": "string",
                            "minLength": 15,
                            "maxLength": MAX_LINE_CHARS,
                        },
                    },
                },
            },
        },
    }


_SYSTEM = render(
    "scout/digest_message",
    MAX_GREETING_CHARS=MAX_GREETING_CHARS,
    MAX_LINE_CHARS=MAX_LINE_CHARS,
)


# Strip anything address-shaped from a written line.
#
# The model is told not to write one and has no field for it, so this is the
# floor rather than the mechanism: a line that carries an address loses it, and
# the link under the find still comes from the typed record. Belt and braces is
# right here specifically — this string is delivered to third parties and cannot
# be recalled.
def _without_links(value: str) -> str:
    return " ".join(_URL_IN_TEXT.sub(" ", value).split())


class DigestWriter:
    """Write one digest's prose from typed finds."""

    # The writer is the same narrow inference contract every other Scout prompt
    # takes, so passing None renders the assembled message instead of failing.
    def __init__(self, writer: TextWriter | None, max_tokens: int = 700) -> None:
        self.writer = writer
        self.max_tokens = max_tokens

    # Ask for the whole message, or return None so the caller falls back to the
    # assembled shape. Every failure — an unreachable runtime, an unparseable
    # body, a schema violation — lands here, because a digest that does not
    # arrive is worse than one that reads like a form letter.
    async def write(self, finds: tuple[Find, ...]) -> WrittenDigest | None:
        if self.writer is None or not finds:
            return None
        try:
            result = await asyncio.to_thread(
                self.writer.chat,
                [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _render_finds(finds)},
                ],
                self.max_tokens,
                _schema(max(find.index for find in finds)),
                # Greedy. The same sweep must produce the same message twice:
                # a digest that rewords itself between a retry and a redelivery
                # reads as two different messages about the same finds.
                0.0,
            )
            payload = json.loads(result["content"])
            greeting = _without_links(str(payload["greeting"]))
            offered = {find.index for find in finds}
            lines = tuple(
                WrittenLine(index=int(item["index"]), text=_without_links(item["text"]))
                for item in payload["lines"]
                # A line for a find that was never offered has nothing to attach
                # a link to, and is the one shape that would let a page invent
                # an entry rather than colour one.
                if int(item["index"]) in offered
            )
        except Exception:
            return None
        if not greeting or not lines:
            return None
        return WrittenDigest(greeting=greeting, lines=lines)


# Lay the finds out for the prompt: numbered, typed, and nothing else. Page text
# never reaches here — only what describing already made of it.
def _render_finds(finds: tuple[Find, ...]) -> str:
    blocks = []
    for find in finds:
        lines = [f"[{find.index}] {find.name}"]
        if find.when:
            lines.append(f"    when: {find.when}")
        if find.place:
            lines.append(f"    where: {find.place}")
        if find.description:
            lines.append(f"    what it is: {find.description}")
        else:
            # Said rather than left out. A missing heading reads as an omission,
            # and a model fills an omission in.
            lines.append("    what it is: not described — say only that it is on")
        blocks.append("\n".join(lines))
    return "These are the finds for this message.\n\n" + "\n\n".join(blocks)
