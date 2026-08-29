"""Addresses a reply may say, and the fence that holds it to them.

On 2026-08-29 a recommendation went to a phone carrying
`https://maps.app.goo.gl/xyz`, `/abc`, `/def`, `/ghi`, `/jkl` and
`https://youtu.be/xyz` - shortened links with placeholder ids, invented
whole. The chat path hands the reply model four fields per search result
(title, url, content, provider) and asks it, in prose, to *construct* a
Google Maps link from a venue it also inferred. Nothing checked the result.

Scout's own digest path never had this failure, and the reason is
structural rather than instructional: its model is given no URL field, its
output is stripped of URL-shaped text, and links are attached afterwards
from typed records. This module carries that rule to the chat path.

The rule: a URL survives only when the application can vouch for it -
either it appeared in this turn's evidence, or code can see it is a search
template whose query is made of words the evidence actually contains. A
maps search for a venue named in a result is a fact about the search box;
a shortened link is a claim about a destination, and a model has no way to
know one. Everything else is removed, and the words around it are kept.

Deliberately not here: bare handles like "@oldmansbali". A handle is not a
URL and no pattern can tell an invented one from a real one - that is a
schema problem (do not ask a model for handles), fixed where the listing is
built, not here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable
from urllib.parse import parse_qs, unquote_plus, urlsplit

# One pattern for "something in this text is an address", shared with the
# Scout digest writer so the two cannot drift apart.
URL_IN_TEXT = re.compile(r"https?://\S+|\bwww\.\S+", re.IGNORECASE)

# Punctuation a sentence puts after a URL that is not part of it. Stripped
# before comparison and put back after, so "(see https://x.test/a)." matches
# the evidence's "https://x.test/a".
_TRAILING = ".,;:!?)]}>\"'"

# A markdown link, so a dropped address leaves its label rather than an
# empty pair of brackets: "[Google Maps](https://…)" becomes "Google Maps".
_MARKDOWN_LINK = re.compile(r"\[([^\]]{1,120})\]\((\S{1,2048}?)\)")

# A line that says nothing once its address is gone is dropped whole rather
# than left dangling: "Map link:", and equally "Map link: Google Maps" or
# "Instagram: @thelawncanggu", where all that survived is the label the
# address was hiding behind. Only applied to lines an address was removed
# from, so an ordinary short line is never touched.
_LABEL_REMNANT = re.compile(
    r"^\s*(?:[-*•]\s*)?\*{0,2}[\w '/&]{1,28}\*{0,2}\s*:\s*\*{0,2}[\w '@&/.-]{0,40}\*{0,2}\s*$"
)

# What could still turn into an address, so a line carrying one is held to
# the end. Everything else can be let through as it is written.
_RISKY = re.compile(r"https?:|www\.|\[", re.IGNORECASE)

# How much risk-free prose is held before it is let through mid-line. Long
# enough that a listing's lines are always ruled on whole, short enough that
# a paragraph still arrives as it is written.
_EAGER_CHARS = 200


# The three URLs code can build from a value and vouch for: a maps search, a
# YouTube search, and a Google Calendar prefill. Each carries its subject in
# one query parameter, so the subject can be checked against the evidence.
_TEMPLATES: dict[tuple[str, str], str] = {
    ("maps.google.com", "/"): "q",
    ("www.google.com", "/maps"): "q",
    ("www.youtube.com", "/results"): "search_query",
    ("calendar.google.com", "/calendar/render"): "text",
}


# One URL reduced to what makes two of them the same address: scheme and
# host lowercased, "www." dropped, a trailing slash and sentence punctuation
# removed. The query is kept - a real result and a shortened invention of it
# differ nowhere else.
def canonical(url: str) -> str:
    cleaned = (url or "").strip().rstrip(_TRAILING)
    if not cleaned:
        return ""
    if cleaned.lower().startswith("www."):
        cleaned = "https://" + cleaned
    parts = urlsplit(cleaned)
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    query = f"?{parts.query}" if parts.query else ""
    return f"{host}{path}{query}"


# Whether a URL is one of the shapes code can build at all.
def _is_template(url: str) -> bool:
    parts = urlsplit((url or "").strip().rstrip(_TRAILING))
    return (parts.netloc.lower(), parts.path.rstrip("/") or "/") in _TEMPLATES


# Whether a template URL is grounded in what this turn actually saw: every
# word of its query value must appear in the evidence text. "Old Man's Beach
# Bar Canggu" read from a result passes; "Made Up Bar" does not, so a model
# cannot launder an invention through a search box.
def template_is_grounded(url: str, evidence: str) -> bool:
    parts = urlsplit((url or "").strip().rstrip(_TRAILING))
    host = parts.netloc.lower()
    key = (host, parts.path.rstrip("/") or "/")
    name = _TEMPLATES.get(key)
    if name is None:
        return False
    values = parse_qs(parts.query).get(name) or []
    if not values:
        return False
    # Punctuation is dropped from both sides before comparing: a search box
    # spells "Old Man's Beach Bar" as "Old+Mans+Beach+Bar", and a fence that
    # rejected that would strip the very links this system builds correctly.
    subject = _bare_words(unquote_plus(values[0]))
    haystack = _bare_words(evidence)
    words = [word for word in subject.split() if len(word) > 2]
    if not words:
        return False
    return all(word in haystack for word in words)


# Text reduced to lowercase words with punctuation removed, so "Man's" and
# "Mans" are the same word on both sides of the comparison.
def _bare_words(text: str) -> str:
    return re.sub(r"[^\w\s]+", "", (text or "").casefold())


# Every address the application put in front of the model this turn. Nothing
# the model wrote is in here; that is the whole point.
def allowed_urls(sources: Iterable[dict | str]) -> frozenset[str]:
    found: set[str] = set()
    for item in sources or ():
        raw = item if isinstance(item, str) else str((item or {}).get("url") or "")
        key = canonical(raw)
        if key:
            found.add(key)
    return frozenset(found)


@dataclass
class LinkFence:
    """The reply boundary: model prose in, publishable prose out.

    Held to whole lines rather than tokens, because whether a line survives
    cannot be decided until the address on it has finished arriving - and a
    line is the unit a reader sees anyway.
    """

    allowed: frozenset[str] = frozenset()
    evidence: str = ""
    # Hosts only, for the log. The dropped URL itself is never logged: it is
    # untrusted text and the reason it is going is that nobody vouched for it.
    dropped: list[str] = field(default_factory=list)
    _pending: str = ""

    # Whether the sender's own evidence is enough to let a search template
    # through without checking its subject. The wall in front of the Mac has
    # the addresses but not the text they came from, and a search template
    # cannot send anyone to an invented destination - it opens a search box.
    # The reply boundary, which has the text, checks the subject properly.
    templates_ok: bool = False

    # Whether this exact address may be said.
    def permits(self, url: str) -> bool:
        if canonical(url) in self.allowed:
            return True
        if self.templates_ok and _is_template(url):
            return True
        return template_is_grounded(url, self.evidence)

    # One finished line, with every address it may not say removed.
    def line(self, text: str) -> str:
        # Counted from the top: a markdown link is the commonest way an
        # invented address arrives, and counting after it made the
        # label-remnant rule blind to exactly that case.
        before = len(self.dropped)

        def _markdown(match: re.Match[str]) -> str:
            label, url = match.group(1), match.group(2)
            if self.permits(url):
                return match.group(0)
            self._note(url)
            return label

        cleaned = _MARKDOWN_LINK.sub(_markdown, text)

        def _bare(match: re.Match[str]) -> str:
            url = match.group(0)
            trailing = ""
            while url and url[-1] in _TRAILING:
                trailing = url[-1] + trailing
                url = url[:-1]
            if self.permits(url):
                return match.group(0)
            self._note(url)
            return trailing

        cleaned = URL_IN_TEXT.sub(_bare, cleaned)
        removed = len(self.dropped) - before

        # An address in parentheses leaves "()" behind; a phone should not be
        # shown punctuation standing on its own. Leading whitespace is held
        # aside first: a listing's indentation is how a reader tells the
        # lines apart, and collapsing it fuses the listing into a paragraph.
        indent = cleaned[: len(cleaned) - len(cleaned.lstrip(" \t"))]
        body = cleaned[len(indent) :]
        body = re.sub(r"\(\s*\)", "", body)
        body = re.sub(r"\[\s*\]", "", body)
        body = re.sub(r"[ \t]{2,}", " ", body)
        body = re.sub(r"[ \t]+([.,;:!?])", r"\1", body)
        cleaned = (indent + body).rstrip()
        if not cleaned.strip():
            return ""
        # Nothing was removed here, so whatever this line is, it is the
        # model's own sentence and not our business.
        if not removed:
            return cleaned
        return "" if _LABEL_REMNANT.match(cleaned) else cleaned

    def _note(self, url: str) -> None:
        host = urlsplit(url if "//" in url else f"https://{url}").netloc.lower()
        if host:
            self.dropped.append(host)

    # Model chunks in, publishable chunks out.
    #
    # A line is the unit: an address arrives across several chunks, and
    # whether the line survives cannot be decided until it has finished (a
    # line left as "Map link:" is worse than one dropped). A long paragraph
    # with no address in sight is let through in pieces anyway, so ordinary
    # prose still arrives as it is written rather than in one lump.
    def feed(self, chunk: str) -> str:
        self._pending += chunk
        out: list[str] = []
        while True:
            if "\n" in self._pending:
                line, self._pending = self._pending.split("\n", 1)
                fenced = self.line(line)
                # A line that was only an address disappears with its
                # newline; one that had text keeps its shape.
                if fenced or not line.strip():
                    out.append(fenced + "\n")
                continue
            if len(self._pending) > _EAGER_CHARS and not _RISKY.search(self._pending):
                # Nothing here can become an address, so it needs no ruling.
                # A short tail stays behind in case the next chunk starts one.
                out.append(self._pending[:-8])
                self._pending = self._pending[-8:]
            break
        return "".join(out)

    # Whatever is left when the model stops.
    def flush(self) -> str:
        rest, self._pending = self._pending, ""
        return self.line(rest) if rest else ""


# The same rule over a whole string, for callers that are not streaming -
# the iMessage worker's second wall, and the tests.
def fence_text(
    text: str,
    allowed: frozenset[str],
    evidence: str = "",
    templates_ok: bool = False,
) -> tuple[str, list[str]]:
    fence = LinkFence(allowed=allowed, evidence=evidence, templates_ok=templates_ok)
    fenced = fence.feed(text) + fence.flush()
    return fenced, fence.dropped
