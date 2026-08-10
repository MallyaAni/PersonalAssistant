"""Make a find readable enough to decide on.

A recipient cannot judge "Nature and History Events – Official Website of
Arlington County Virginia Government" — that is a page title, not an event. They
need to know what the thing is before deciding whether to add it. So two steps,
in order of how much they can be trusted:

1. **deterministic cleanup**, which never fails and never invents: strip the site
   name a CMS appended to every page title, collapse whitespace, bound length;
2. **a written one-line description**, which is the one place a model belongs in
   this subsystem. Deciding *what qualifies* stays deterministic — a sweep runs
   unattended and must not vary by sampling — but turning a scraped paragraph
   into a sentence a person can read is exactly what a model is for.

The safety story for step 2 is deliberate and limited. Page text is untrusted and
the result is delivered to third parties, so:

- the model answers into a **constrained schema** with a bounded field, so it
  cannot emit structure, markup, or a wall of text;
- **no URL survives from model output.** Links in a message come from the typed
  record, never from anything the model wrote, so a page cannot get a link of its
  choosing in front of a recipient;
- failure is **silent and safe**: if anything goes wrong the deterministic
  summary is used, which is worse to read and impossible to subvert.

A grammar constrains shape, not meaning. A hostile page can still influence the
wording of its own description — the same way it can influence its own title. It
cannot inject a link, exceed the bound, or reach anything else.
"""

import re

# One line. Long enough to say what a thing is, short enough to read in a message
# among five others.
MAX_DESCRIPTION_CHARS = 160

# A name, said the way a person would say it. Short enough that the whole line
# is the name rather than the name plus a page's search-engine tail.
MAX_NAME_CHARS = 70
MAX_SOURCE_CHARS = 1_200

# Separators a CMS puts between a page's real title and the site name. Real
# titles contain these too, so only a trailing segment is removed.
_TITLE_SEPARATORS = ("|", " – ", " — ", " - ", " · ", " :: ")

# Boilerplate that marks a trailing segment as a site name rather than content.
_SITE_MARKERS = re.compile(
    r"(official\s+website|home\s*page|\.com|\.org|\.gov|\.net|county government"
    r"|convention\s+&?\s*visitors|department\s+of)",
    re.IGNORECASE,
)

_MARKDOWN_NOISE = re.compile(r"[#*_`>\[\]]+")
_URL_IN_TEXT = re.compile(r"https?://\S+", re.IGNORECASE)

# Everything in a page that is not prose. Script and style carry text nodes that
# are code, and dropping the tags around them without dropping their contents
# turns a stylesheet into the description.
_SCRIPT_OR_STYLE = re.compile(
    r"<(script|style|noscript|template)\b[^>]*>.*?</\1>", re.S | re.I
)
_HTML_TAG = re.compile(r"<[^>]+>")
_HTML_ENTITY = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}


# The readable prose of a page, for a find whose source gave us none.
#
# A link page publishes a title and a destination and nothing else, so finds
# from one arrive with no summary at all — which is why a digest built from one
# was a list of bare titles, and why nothing could tell that a thing advertised
# "through August 3" was over. The destination page says both.
#
# Crude on purpose. This feeds a model that is going to rewrite it anyway, so
# the bar is "enough prose to judge", not faithful extraction.
def text_from_html(document: str, limit: int = MAX_SOURCE_CHARS) -> str | None:
    if not document:
        return None
    stripped = _SCRIPT_OR_STYLE.sub(" ", document)
    text = _HTML_TAG.sub(" ", stripped)
    for entity, character in _HTML_ENTITY.items():
        text = text.replace(entity, character)
    collapsed = " ".join(text.split())
    return collapsed[:limit] or None


# Drop a trailing site name. "Nature and History Events – Official Website of
# Arlington County Virginia Government" is two things joined by a CMS, and only
# the first is the event.
def clean_title(raw: str, limit: int = 120) -> str:
    title = " ".join(_MARKDOWN_NOISE.sub(" ", raw).split())
    for separator in _TITLE_SEPARATORS:
        if separator not in title:
            continue
        head, _, tail = title.rpartition(separator)
        # Only strip when the tail looks like a site name and the head still
        # says something. A title that is genuinely hyphenated survives.
        if head.strip() and _SITE_MARKERS.search(tail):
            title = head.strip()
    return title[:limit].strip(" -–—|·") or raw[:limit]


# What a scraped page yields without any model: the first readable sentence.
# Crude, but it never fails and never invents, so it is the floor everything
# else falls back to.
def summarize_deterministically(
    source: str | None, limit: int = MAX_DESCRIPTION_CHARS
) -> str | None:
    if not source:
        return None
    text = _URL_IN_TEXT.sub(" ", _MARKDOWN_NOISE.sub(" ", source))
    text = " ".join(text.split())
    if not text:
        return None
    sentence = re.split(r"(?<=[.!?])\s+", text)[0]
    if len(sentence) > limit:
        sentence = sentence[: limit - 1].rsplit(" ", 1)[0] + "…"
    return sentence or None
