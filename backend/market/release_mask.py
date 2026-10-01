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
  emails                                    [EMAIL]
  the dateline city and the wire tag        [CITY], removed
  a name after "said" or before a title     [NAME]
  any token rare across the corpus          [NAME]
  URLs, phone numbers, exhibit file names   removed
  the "About the company" boilerplate and
  the contact trailer                       removed, bounded by the
                                            next heading or a cap

The corpus rule is what makes this hold without a dictionary: a token
with a capital letter, or letters and digits together (A100, 1z), that
occurs in fewer than MIN_ISSUERS distinct issuers' releases is a name of
something - a person, a product, a city, a customer - and goes. A token
in fifteen or more issuers (GAAP, Revenue, Nasdaq, Calif, AI, GPU) is
the language of releases and stays. `rare_tokens` builds the set from
the whole corpus; `mask` takes it.

HTML entities in the stored text (`&#58;`, `&#160;`, `&#8226;`) are
decoded first, so "Nasdaq&#58; SMCI" is a ticker in an exchange label
and the reader gets clean text.

What stays: every number. Revenue, margins, growth rates, guidance ranges
are the content the reader is meant to score, and a masked release with
its numbers gone would measure a different question.

Names are matched at word boundaries, case-insensitively, with a trailing
possessive absorbed, so "NVIDIA's" becomes "[COMPANY]" and a name that is
a substring of another word is left alone. Every placeholder is free of
digits and month names, which is what makes a second pass a no-op.
"""

import html
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

COMPANY = "[COMPANY]"
TICKER = "[TICKER]"
PERSON = "[PERSON]"
PRODUCT = "[PRODUCT]"
DATE = "[DATE]"
PERIOD = "[PERIOD]"
QUARTER = "[QUARTER]"
YEAR = "[YEAR]"
NAME = "[NAME]"
CITY = "[CITY]"
EMAIL = "[EMAIL]"
PLACEHOLDERS: tuple[str, ...] = (
    COMPANY,
    TICKER,
    PERSON,
    PRODUCT,
    DATE,
    PERIOD,
    QUARTER,
    YEAR,
    NAME,
    CITY,
    EMAIL,
)
# A token in fewer distinct issuers than this is a name of something.
MIN_ISSUERS = 15

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
            rf"|\bF?Q[1-4]\s*(?:FY|fiscal\s*)?\s*(?:{_YEAR}|{_SHORT_YEAR})\b{_POSSESSIVE}"
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
            rf"\b(?:{_ORDINAL})[- ]quarter\b{_POSSESSIVE}|\bF?Q[1-4]\b|\b[1-4]Q\b",
            re.IGNORECASE,
        ),
        QUARTER,
    ),
    # A bare year.
    ("year", re.compile(rf"{_YEAR}{_POSSESSIVE}"), YEAR),
)

# A way to reach someone - a URL, a phone number - or an exhibit file
# name (which carries the filing date) is removed wherever it stands. The
# stored text is one line (`edgar.html_to_text` collapses whitespace), so
# nothing here works by line.
_CONTACT_TOKEN = re.compile(
    r"https?://\S+|www\.\S+|\b[\w-]+\.(?:com|net|org|io)\b(?:/\S*)?"
    r"|\(\d{3}\)\s?\d{3}-\d{4}\b|\b\d{3}-\d{3}-\d{4}\b|\b\d{3}\.\d{3}\.\d{4}\b"
    r"|\S+\.(?:htm|html|pdf|txt|xml)\b",
    re.IGNORECASE,
)
# Anything holding an @ is an address, even a truncated one ("jdoe@").
_EMAIL_TOKEN = re.compile(r"[^\s@()<>,;]*@[^\s()<>,;]*")
# The dateline: a city in capitals, optionally a state, before the (already
# masked) date, a dash, or a wire-service tag.
_WIRE_TAGS = (
    "BUSINESS WIRE|GLOBE NEWSWIRE|GLOBENEWSWIRE|PRNewswire|PR Newswire|"
    "Business Wire|Globe Newswire|ACCESSWIRE|Marketwired|MARKETWIRED"
)
_WIRE_TAG = re.compile(rf"\(\s*(?:{_WIRE_TAGS})\s*\)")
_DATELINE = re.compile(
    r"(?<![\w\]])([A-Z][A-Z.']+(?:[ \t][A-Z][A-Z.']+){0,3})"
    r"(?:,\s*(?:[A-Z][a-z]+\.?(?:\s[A-Z][a-z]+)?|[A-Z]{2})\.?)?"
    rf"[\s,.\u2013\u2014-]*(?=\[DATE\]|--|\u2013|\u2014|\(\s*(?:{_WIRE_TAGS}))"
)
# A person: two or three capitalised tokens right after "said", or right
# before a comma and a title.
_CAPITALISED = r"[A-Z][\w.'-]*"
_SAID_NAME = re.compile(rf"\b(said)\s+((?:{_CAPITALISED}\s+){{1,2}}{_CAPITALISED})")
_TITLED_NAME = re.compile(
    rf"(?<![\w\]])((?:{_CAPITALISED}\s+){{1,2}}{_CAPITALISED})(,\s+)"
    r"(?=(?i:(?:the\s+|our\s+|its\s+)?(?:co-)?(?:founder|president|chief|CEO|CFO|"
    r"COO|CTO|chairman|chairwoman|executive|officer|director|vice|senior|"
    r"managing|general|head)\b))"
)
# The rest of a legal name after a masked short form: "[COMPANY] Computer,
# Inc." when the store knows the issuer as "Super Micro".
_COMPANY_TAIL = re.compile(
    rf"{re.escape(COMPANY)}(?:\s+[A-Z][\w&-]*){{0,3}},?\s+"
    r"(?i:Inc|Incorporated|Corp|Corporation|Company|Co|Ltd|Limited|plc|Holdings|"
    r"N\.V|S\.A|AG|Group)\b\.?"
)
# A token the corpus rule considers: letters, digits and hyphens, at least
# two characters, with a capital letter or letters and digits together.
_TOKEN = re.compile(r"(?<![\w-])[A-Za-z0-9][A-Za-z0-9-]*(?![\w-])")
_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_DIGIT = re.compile(r"\d")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_NAME_RUN = re.compile(
    rf"{re.escape(NAME)}(?:['\u2019]s)?(?:[\s,&]+{re.escape(NAME)}(?:['\u2019]s)?)+"
)
# Where the "About the company" boilerplate opens, once the name is masked.
_ABOUT_OPENER = re.compile(rf"\bAbout\s+(?:the\s+)?{re.escape(COMPANY)}")
# Where the contact trailer opens: a capitalised Contact label, or the
# investor-relations sign-off.
_TRAILER_OPENER = re.compile(
    r"\b(?:Investor|Media|Press|Company|IR)\s+(?:Relations\s+)?Contacts?\b"
    r"|\bContacts?:"
    r"|\bInvestor\s+Relations\b"
    r"|\bFor\s+(?:further|more|additional)\s+information,?\s+(?:please\s+)?"
    r"contact\b",
)
# Where a removed span ends: the next section heading, or the cap.
_NEXT_HEADING = re.compile(
    r"Forward[- ]Looking|Cautionary|Safe Harbor|Non-GAAP|Use of Non|"
    r"Condensed Consolidated|CONDENSED CONSOLIDATED|Consolidated Statements?|"
    r"CONSOLIDATED STATEMENTS?|Reconciliation|Supplemental|Source:|###|"
    r"Conference Call|Webcast|Investor Relations|Investor Contact|"
    r"Media Contact|Contacts?:"
)
# The most a removed span may run without a heading: an About paragraph
# is a few hundred characters, a contact block fewer.
ABOUT_MAX_CHARS = 1_500
TRAILER_MAX_CHARS = 400
# A trailer opener earlier than this share of the text is content ("contact
# center revenue"), not a sign-off.
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


# Remove a span from each opener to the next heading or the cap, whichever
# comes first, repeating until no opener is left so a second pass finds
# nothing. Returns the text and how many spans went.
def _remove_spans(
    text: str, opener: re.Pattern[str], cap: int, start_from: float = 0.0
) -> tuple[str, int]:
    removed = 0
    while True:
        floor = int(len(text) * start_from)
        found = opener.search(text, floor)
        if found is None:
            return text, removed
        head = found.start()
        limit = min(len(text), found.end() + cap)
        heading = _NEXT_HEADING.search(text, found.end(), limit)
        stop = heading.start() if heading else limit
        text = (text[:head] + " " + text[stop:]).strip()
        text = re.sub(r"[ \t]{2,}", " ", text)
        removed += 1


# Remove every URL, phone number and exhibit file name.
def _drop_contact_tokens(text: str) -> tuple[str, int]:
    out, hits = _CONTACT_TOKEN.subn("", text)
    return re.sub(r"[ \t]{2,}", " ", out), hits


# Decode HTML entities and unify the spaces they hide (`&#160;` is a
# no-break space, which is not a word boundary to a reader either).
def unescape(text: str) -> str:
    """Return the text with entities decoded and unicode spaces as spaces."""
    out = html.unescape(text.replace("\r\n", "\n"))
    return re.sub(r"[\u00a0\u2007\u202f\u2009\u200a\u2002\u2003]", " ", out)


# Whether a token is one the corpus rule considers: two characters or
# more, with a capital letter or with digits and letters together.
def _considered(token: str) -> bool:
    if len(token) < 2:
        return False
    if _HAS_UPPER.search(token):
        return True
    return bool(_HAS_DIGIT.search(token) and _HAS_LETTER.search(token))


# In how many distinct issuers each considered token occurs.
def token_issuer_counts(texts_by_issuer: Mapping[str, Sequence[str]]) -> dict[str, int]:
    """Return {token: number of issuers whose releases contain it}."""
    counts: dict[str, int] = {}
    for texts in texts_by_issuer.values():
        seen: set[str] = set()
        for text in texts:
            seen.update(t for t in _TOKEN.findall(unescape(text)) if _considered(t))
        for token in seen:
            counts[token] = counts.get(token, 0) + 1
    return counts


# The tokens that name something: those in fewer than `min_issuers`
# distinct issuers. The placeholders themselves are never in the set, so a
# masked text is never re-masked.
def rare_tokens(
    texts_by_issuer: Mapping[str, Sequence[str]], min_issuers: int = MIN_ISSUERS
) -> set[str]:
    """Return the case-sensitive tokens occurring in fewer than `min_issuers`."""
    protected = {p.strip("[]") for p in PLACEHOLDERS}
    return {
        token
        for token, n in token_issuer_counts(texts_by_issuer).items()
        if n < min_issuers and token not in protected
    }


# Replace every rare token, whole-word and case-sensitive, and collapse a
# run of placeholders into one.
def _mask_rare(text: str, rare: set[str]) -> tuple[str, int]:
    hits = 0

    def swap(match: re.Match[str]) -> str:
        nonlocal hits
        token = match.group(0)
        if token in rare:
            hits += 1
            return NAME
        return token

    out = _TOKEN.sub(swap, text)
    out = re.sub(rf"{re.escape(NAME)}['\u2019]s\b", NAME, out)
    out = _NAME_RUN.sub(NAME, out)
    return out, hits


# The dateline city and the wire-service tag.
def _mask_dateline(text: str) -> tuple[str, int, int]:
    out, cities = _DATELINE.subn(f"{CITY} ", text, count=1)
    out, wires = _WIRE_TAG.subn("", out)
    return re.sub(r"[ \t]{2,}", " ", out), cities, wires


# People named after "said" or before a title.
def _mask_people(text: str) -> tuple[str, int]:
    out, said = _SAID_NAME.subn(rf"\g<1> {NAME}", text)
    out, titled = _TITLED_NAME.subn(rf"{NAME}\g<2>", out)
    return out, said + titled


# Mask a release: entities decoded, ways to reach someone first, then the
# issuer's names, then the boilerplate that opens with the masked name,
# then the other identities, the dateline, the calendar, the people, and
# last the corpus rule over whatever is left.
def mask(text: str, issuer: MaskIssuer, rare: set[str] | None = None) -> MaskedText:
    """Return the masked text and a count of replacements per kind."""
    counts: dict[str, int] = {}
    out = unescape(text)
    out, counts["contact"] = _drop_contact_tokens(out)
    out, counts["email"] = _EMAIL_TOKEN.subn(EMAIL, out)
    names = [v for name in issuer.names for v in name_variants(name)]
    out, counts["company"] = _apply(out, _phrase_pattern(names), COMPANY)
    out, tails = _COMPANY_TAIL.subn(COMPANY, out)
    counts["company"] += tails
    out, counts["about_section"] = _remove_spans(out, _ABOUT_OPENER, ABOUT_MAX_CHARS)
    out, counts["trailer"] = _remove_spans(
        out, _TRAILER_OPENER, TRAILER_MAX_CHARS, TRAILER_FROM
    )
    out, counts["ticker"] = _apply(out, _ticker_pattern(issuer.tickers), TICKER)
    out, counts["other_ticker"] = _apply(
        out, _labelled_ticker_pattern(issuer.other_tickers), rf"\g<1>{TICKER}"
    )
    out, counts["person"] = _apply(out, _phrase_pattern(issuer.people), PERSON)
    out, counts["product"] = _apply(out, _phrase_pattern(issuer.products), PRODUCT)
    for kind, pattern, replacement in _TIME_RULES:
        out, hits = pattern.subn(replacement, out)
        counts[kind] = counts.get(kind, 0) + hits
    out, counts["dateline"], counts["wire"] = _mask_dateline(out)
    out, counts["people"] = _mask_people(out)
    out, counts["rare"] = _mask_rare(out, rare or set())
    return MaskedText(text=out, counts=counts)


# How many word tokens a text has, the denominator of the rare share.
def token_count(text: str) -> int:
    """Return the number of word tokens in `text`."""
    return len(_TOKEN.findall(text))


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
