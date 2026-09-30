"""Mask who and when out of an earnings release, keeping what was said.

The tone-validity study (`docs/research/tone-validity-plan-2026-09-30.md`)
re-reads every release with the same model and prompt that produced the
stored scores, but with the issuer's identity and the fiscal period
removed, so the reader cannot lean on what it later learned about the
company. This is that removal: a deterministic pass, no model in it, so
the same text always masks the same way and a leak test can be run on
its output before any score is read.

What goes, and to what:

  the issuer's names and its tickers        [COMPANY], [TICKER]
  another book ticker in an exchange label  [TICKER]
  people and product names, when given      [PERSON], [PRODUCT]
  calendar dates and month names            [DATE]
  a quarter with its year, a fiscal year    [PERIOD]
  a bare quarter label                      [QUARTER]
  a bare four-digit year                    [YEAR]
  lines carrying an email, URL or phone     removed
  the "About the company" boilerplate and
  the contact trailer                       removed

What stays: every number. Revenue, margins, growth rates, guidance ranges
are the content the reader is meant to score, and a masked release with
its numbers gone would measure a different question.

Names are matched at word boundaries, case-insensitively, with a trailing
possessive absorbed, so "NVIDIA's" becomes "[COMPANY]" and a name that is
a substring of another word is left alone. Every placeholder is free of
digits and month names, which is what makes a second pass a no-op.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

COMPANY = "[COMPANY]"
TICKER = "[TICKER]"
PERSON = "[PERSON]"
PRODUCT = "[PRODUCT]"
DATE = "[DATE]"
PERIOD = "[PERIOD]"
QUARTER = "[QUARTER]"
YEAR = "[YEAR]"

# The question the leak test puts to the reader over a masked release.
LEAK_QUESTION = (
    "Which company issued this release, and which fiscal quarter/year does "
    "it report? Answer as JSON {company, quarter, year}."
)

# Corporate suffixes stripped, one at a time from the end, to make the
# shorter variants of a legal name ("Micron Technology, Inc." -> "Micron
# Technology" -> "Micron").
SUFFIXES: tuple[str, ...] = (
    "incorporated",
    "inc",
    "corporation",
    "corp",
    "company",
    "co",
    "holdings",
    "holding",
    "limited",
    "ltd",
    "plc",
    "n.v.",
    "nv",
    "s.a.",
    "sa",
    "ag",
    "group",
    "technologies",
    "technology",
    "systems",
    "networks",
    "semiconductor",
    "international",
    "the",
)
# A first word that is an ordinary English word is not a name on its own:
# "Advanced" (Micro Devices), "Super" (Micro Computer), "First" (Solar).
GENERIC_WORDS: frozenset[str] = frozenset(
    {
        "advanced",
        "american",
        "applied",
        "digital",
        "first",
        "general",
        "global",
        "international",
        "micro",
        "national",
        "super",
        "united",
        "universal",
        "western",
        "the",
        "on",
    }
)
# The shortest first word taken as a name variant on its own.
MIN_VARIANT_CHARS = 4

_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec"
)
_ORDINAL = "first|second|third|fourth|1st|2nd|3rd|4th"
_POSSESSIVE = r"(?:['’]s)?"
# A four-digit year 1900-2099 that is not part of a larger number or a
# decimal: "$2,024 million" and "2024.5" are amounts, "2024" is a year.
_YEAR = r"(?<![\d$.,])(?:19|20)\d\d(?!\d|[.,]\d)"
_SHORT_YEAR = r"['’]?\d\d"

# Ordered (kind, pattern, replacement); each pattern is applied to the
# whole text in this order. Dates go before quarters and years so "the
# quarter ended July 30, 2024" masks as one date rather than pieces.
_TIME_RULES: tuple[tuple[str, re.Pattern[str], str], ...] = (
    # July 30, 2024 / Jul. 30 2024 / 30 July 2024 / July 2024 / 2024-07-30 / 7/30/24
    (
        "date",
        re.compile(
            rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+{_YEAR}{_POSSESSIVE}"
            rf"|\b\d{{1,2}}\s+(?:{_MONTHS})\.?,?\s+{_YEAR}{_POSSESSIVE}"
            rf"|\b(?:{_MONTHS})\.?,?\s+{_YEAR}{_POSSESSIVE}"
            rf"|\b(?:{_MONTHS})\.?\s+\d{{1,2}}(?:st|nd|rd|th)?\b"
            rf"|{_YEAR}-\d\d-\d\d\b"
            r"|\b\d{1,2}/\d{1,2}/(?:\d\d|\d{4})\b"
        ),
        DATE,
    ),
    # A month name on its own ("in July", "Sept.").
    ("month", re.compile(rf"\b(?:{_MONTHS})\b\.?"), DATE),
    # A quarter with a year: Q2 2025, Q2 FY2025, Q2'25, 2Q25, Q2FY25, second
    # quarter of fiscal 2025, fourth quarter 2024.
    (
        "period",
        re.compile(
            rf"\b(?:{_ORDINAL})[- ]quarter(?:\s+(?:of|for)\s+(?:the\s+)?)?"
            rf"(?:\s*(?:fiscal|FY)\s*(?:year\s*)?)?\s*{_YEAR}{_POSSESSIVE}"
            rf"|\bQ[1-4]\s*(?:FY|fiscal\s*)?\s*(?:{_YEAR}|{_SHORT_YEAR})\b{_POSSESSIVE}"
            rf"|\b[1-4]Q\s*(?:FY)?\s*(?:{_YEAR}|\d\d)\b{_POSSESSIVE}",
            re.IGNORECASE,
        ),
        PERIOD,
    ),
    # A fiscal year: fiscal 2024, fiscal year 2024, FY2024, FY24, FY'25,
    # full year 2024, calendar 2024.
    (
        "period",
        re.compile(
            rf"\b(?:fiscal|calendar|full)[- ]?(?:year\s*)?(?:{_YEAR}|{_SHORT_YEAR})"
            rf"\b{_POSSESSIVE}"
            rf"|\bFY\s?(?:{_YEAR}|{_SHORT_YEAR})\b{_POSSESSIVE}"
            rf"|\b(?:first|second|1st|2nd)[- ]half(?:\s+of)?\s+(?:fiscal\s+)?{_YEAR}"
            rf"{_POSSESSIVE}"
            rf"|\bH[12]\s?(?:{_YEAR}|{_SHORT_YEAR})\b{_POSSESSIVE}",
            re.IGNORECASE,
        ),
        PERIOD,
    ),
    # A bare quarter label: second quarter, fourth-quarter, Q3, 3Q.
    (
        "quarter",
        re.compile(
            rf"\b(?:{_ORDINAL})[- ]quarter\b{_POSSESSIVE}|\bQ[1-4]\b|\b[1-4]Q\b",
            re.IGNORECASE,
        ),
        QUARTER,
    ),
    # A bare year.
    ("year", re.compile(rf"{_YEAR}{_POSSESSIVE}"), YEAR),
)

# A line carrying a way to reach someone is dropped whole.
_CONTACT_LINE = re.compile(
    r"[\w.+-]+@[\w-]+\.[\w.-]+"
    r"|https?://|www\.|\b[\w-]+\.(?:com|net|org|io)\b(?:/|\b)"
    r"|\(\d{3}\)\s?\d{3}-\d{4}\b|\b\d{3}-\d{3}-\d{4}\b|\b\d{3}\.\d{3}\.\d{4}\b",
    re.IGNORECASE,
)
# A line that opens the contact trailer; everything from it on is dropped.
_TRAILER_LINE = re.compile(
    r"^\s*(?:media\s+|investor\s+|press\s+|company\s+)?"
    r"(?:contacts?|investor\s+relations|media\s+relations|"
    r"for\s+(?:further|more|additional)\s+information)\b",
    re.IGNORECASE,
)
# A line that opens the "About the company" boilerplate.
_ABOUT_LINE = re.compile(r"^\s*About\s+(?:the\s+)?[A-Z\[]")
# How far into the text a trailer or boilerplate opener may sit: a
# "Contact" in the first half is part of the release, not its tail.
TRAILER_FROM = 0.5


@dataclass(frozen=True)
class MaskIssuer:
    """Who filed the release and what else must not be recognisable."""

    names: tuple[str, ...]
    tickers: tuple[str, ...]
    people: tuple[str, ...] = ()
    products: tuple[str, ...] = ()
    # Other book tickers, masked only inside an exchange label or
    # parentheses, where a ticker is a ticker and not an English word.
    other_tickers: tuple[str, ...] = ()


@dataclass(frozen=True)
class MaskedText:
    """A masked release and how many of each thing were replaced."""

    text: str
    counts: dict[str, int] = field(default_factory=dict)


# The variants of a legal name worth matching: the name as given, then the
# name with each corporate suffix stripped in turn, then its first word
# alone when that word is distinctive enough to be the company.
def name_variants(name: str) -> tuple[str, ...]:
    """Return the name and its shorter forms, longest first, deduplicated."""
    cleaned = re.sub(r"\s+", " ", name.replace(",", " ")).strip().strip(".")
    if not cleaned:
        return ()
    variants = [cleaned]
    current = cleaned
    stripped = True
    while stripped:
        stripped = False
        for suffix in SUFFIXES:
            pattern = rf"\s+{re.escape(suffix)}\.?$"
            shorter = re.sub(pattern, "", current, flags=re.IGNORECASE)
            if shorter != current and shorter.strip():
                current = shorter.strip()
                variants.append(current)
                stripped = True
                break
    first = current.split(" ")[0]
    if (
        len(first) >= MIN_VARIANT_CHARS
        and first.lower() not in GENERIC_WORDS
        and first != current
    ):
        variants.append(first)
    unique = list(dict.fromkeys(v for v in variants if v))
    return tuple(sorted(unique, key=lambda v: (-len(v), v)))


# A word-bounded, case-insensitive pattern over the given phrases, longest
# first, that also swallows a trailing possessive.
def _phrase_pattern(phrases: Iterable[str]) -> re.Pattern[str] | None:
    ordered = sorted({p.strip() for p in phrases if p and p.strip()}, key=len)
    if not ordered:
        return None
    alternatives = "|".join(
        re.escape(p).replace(r"\ ", r"\s+") for p in reversed(ordered)
    )
    return re.compile(rf"(?<!\w)(?:{alternatives}){_POSSESSIVE}(?!\w)", re.IGNORECASE)


# A case-sensitive, word-bounded pattern over tickers.
def _ticker_pattern(tickers: Iterable[str]) -> re.Pattern[str] | None:
    ordered = sorted({t.strip().upper() for t in tickers if t and t.strip()}, key=len)
    if not ordered:
        return None
    alternatives = "|".join(re.escape(t) for t in reversed(ordered))
    return re.compile(rf"(?<![\w$])(?:{alternatives})(?!\w)")


# Other tickers count only in an exchange label or parentheses: "(NYSE:
# AMD)", "NASDAQ: MU", "(MU)". Elsewhere "ON" and "NOW" are words.
def _labelled_ticker_pattern(tickers: Iterable[str]) -> re.Pattern[str] | None:
    ordered = sorted({t.strip().upper() for t in tickers if t and t.strip()}, key=len)
    if not ordered:
        return None
    alternatives = "|".join(re.escape(t) for t in reversed(ordered))
    return re.compile(
        rf"((?:NASDAQ|NYSE|Nasdaq|AMEX|TSX|LSE)\s*:\s*|\()(?:{alternatives})(?=[\s),.;])"
    )


# Substitute a pattern and count how many times it fired.
def _apply(
    text: str, pattern: re.Pattern[str] | None, replacement: str
) -> tuple[str, int]:
    if pattern is None:
        return text, 0
    return pattern.subn(replacement, text)


# Drop the boilerplate tail: from the last "About <company>" opener or the
# first contact-trailer opener in the second half of the text, whichever
# comes first, to the end.
def _cut_tail(text: str) -> tuple[str, int, int]:
    lines = text.split("\n")
    floor = int(len(lines) * TRAILER_FROM)
    about = next(
        (
            i
            for i in range(len(lines) - 1, floor - 1, -1)
            if _ABOUT_LINE.match(lines[i])
        ),
        None,
    )
    trailer = next(
        (i for i in range(floor, len(lines)) if _TRAILER_LINE.match(lines[i])), None
    )
    candidates = [i for i in (about, trailer) if i is not None]
    if not candidates:
        return text, 0, 0
    cut = min(candidates)
    return (
        "\n".join(lines[:cut]).rstrip(),
        int(about is not None and cut == about),
        int(trailer is not None),
    )


# Drop every line that carries an email, URL or phone number.
def _drop_contact_lines(text: str) -> tuple[str, int]:
    kept = [line for line in text.split("\n") if not _CONTACT_LINE.search(line)]
    return "\n".join(kept), text.count("\n") + 1 - len(kept)


# Mask a release: identity first, so a name inside a date-like phrase is
# still a name; then the calendar; then the boilerplate.
def mask(text: str, issuer: MaskIssuer) -> MaskedText:
    """Return the masked text and a count of replacements per kind."""
    counts: dict[str, int] = {}
    out = text.replace("\r\n", "\n")
    out, counts["about_section"], counts["trailer"] = _cut_tail(out)
    out, counts["contact_line"] = _drop_contact_lines(out)
    names = [v for name in issuer.names for v in name_variants(name)]
    out, counts["company"] = _apply(out, _phrase_pattern(names), COMPANY)
    out, counts["ticker"] = _apply(out, _ticker_pattern(issuer.tickers), TICKER)
    out, counts["other_ticker"] = _apply(
        out, _labelled_ticker_pattern(issuer.other_tickers), rf"\g<1>{TICKER}"
    )
    out, counts["person"] = _apply(out, _phrase_pattern(issuer.people), PERSON)
    out, counts["product"] = _apply(out, _phrase_pattern(issuer.products), PRODUCT)
    for kind, pattern, replacement in _TIME_RULES:
        out, hits = pattern.subn(replacement, out)
        counts[kind] = counts.get(kind, 0) + hits
    return MaskedText(text=out, counts=counts)


# What still identifies the release after masking: a four-digit year, a
# month name, or any of the given names. Zero of each is the target.
def residuals(text: str, names: Sequence[str] = ()) -> dict[str, int]:
    """Return counts of {year, month, name} tokens left in a masked text."""
    name_pattern = _phrase_pattern(v for n in names for v in name_variants(n))
    return {
        "year": len(re.findall(_YEAR, text)),
        "month": len(re.findall(rf"\b(?:{_MONTHS})\b", text)),
        "name": len(name_pattern.findall(text)) if name_pattern else 0,
    }


# The leak-test prompt: the masked release, then the question.
def leak_prompt(masked_text: str) -> str:
    """Return the prompt asking the reader to identify a masked release."""
    return f"{masked_text.strip()}\n\n{LEAK_QUESTION}"
