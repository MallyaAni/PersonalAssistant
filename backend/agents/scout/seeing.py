"""Read the picture a listing published, for the few finds about to be sent.

Event feeds increasingly carry the event's own poster, and the poster often
states what the text does not: the date, the venue, the performers, the price.
The primary model sees images itself now, so a selected find's picture is
fetched within the sweep's request budget and shown to it once. What comes back
is a caption prepended to the page text the describer already reads, which
keeps one description call and one schema rather than adding a second writing
stage.

The picture is untrusted input like any feed. The fetch is byte-bounded and
goes through the same public-address guard as a feed, the content type is
decided from the bytes rather than from the host's claim, and the caption is
bounded and whitespace-collapsed before it reaches a prompt. Failure is always
"no caption": an unreachable picture, an unreadable format, or a vision runtime
that is down leaves the find exactly as it was.
"""

import logging
from typing import Any

from backend.core.interfaces import VisionProvider
from backend.core.prompts import load
from backend.discovery.events import FeedError, clean_text
from backend.discovery.fetching import MAX_MEDIA_BYTES, RequestBudget, fetch_bytes

logger = logging.getLogger(__name__)

# How much of the model's answer is kept. A poster caption is a sentence or
# two; anything longer is the model writing an essay into a description prompt.
MAX_CAPTION_CHARS = 400

# The instruction is shared with Docling's picture description: both ask for
# the same thing - what the picture shows and any text in it - and one prompt
# means one thing to measure.
PICTURE_PROMPT = load("document/picture")

# What the describer is told the caption is. Without the label the model reads
# the caption as the page's own prose and may repeat it as though the listing
# had said it.
_CAPTION_LABEL = "A picture published with this listing shows: "

# The file signatures a web image actually starts with. The host's declared
# type is a claim; this is what decides whether the bytes are worth spending a
# vision call on, and it is also what stops an HTML error page from being sent
# to the model as a picture.
_MAGIC = (
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


# The type these bytes really are, or None when they are not a picture this
# pipeline can read. WEBP carries its marker after a RIFF header.
def image_media_type(content: bytes, declared: str = "") -> str | None:
    for signature, media_type in _MAGIC:
        if content.startswith(signature):
            return media_type
    if content[:4] == b"RIFF" and content[8:12] == b"WEBP":
        return "image/webp"
    # A format with no signature here (AVIF, HEIC) is only accepted when the
    # host declared an image type; the vision provider decides whether it can
    # decode it and fails to no caption if not. Text is refused regardless of
    # what the host claimed: an error page served as image/png is still an
    # error page, and it must never become a vision call.
    if _looks_like_text(content):
        return None
    claimed = declared.split(";", 1)[0].strip().lower()
    return claimed if claimed.startswith("image/") else None


# Whether the first bytes read as a text document rather than a picture. The
# formats with signatures never reach this check; it exists for the ones that
# rely on the host's declared type.
def _looks_like_text(content: bytes) -> bool:
    head = content[:512].lstrip()
    return head.startswith((b"<", b"{", b"["))


class PictureCaptioner:
    """Describe a selected find's poster, or say nothing about it."""

    def __init__(self, vision: VisionProvider | None) -> None:
        self.vision = vision

    # Fetch and describe one picture. Every failure returns None, because a
    # caption is an extra and must never cost the find it belongs to.
    async def caption(
        self, url: str | None, budget: RequestBudget | None = None
    ) -> str | None:
        if self.vision is None or not url or budget is None or budget.remaining <= 0:
            return None
        try:
            content, declared = await fetch_bytes(
                url, budget=budget, max_bytes=MAX_MEDIA_BYTES
            )
        except FeedError:
            return None
        media_type = image_media_type(content, declared)
        if media_type is None:
            return None
        try:
            result = await self.vision.analyze(PICTURE_PROMPT, content, media_type)
        except Exception:
            # An unreachable or refusing vision runtime is a missing caption,
            # not a failed sweep.
            logger.debug("discovery_picture_unreadable url=%s", url, exc_info=True)
            return None
        described = clean_text(_answer_text(result), MAX_CAPTION_CHARS)
        if described is None:
            return None
        return _CAPTION_LABEL + described


# The text of a vision answer, whatever shape the provider returned. The
# provider's own type carries it as `content`; a test double may hand back a
# string, and neither should make the caller branch.
def _answer_text(result: Any) -> str | None:
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    return content if isinstance(content, str) else None
