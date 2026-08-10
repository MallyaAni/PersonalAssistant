"""Refuse a find that says, in its own words, that it is somewhere else.

Search is told the place — the query is `{subject} {place} {month year}` — and it
still returns the wrong one, because town names repeat. Two reached real
digests: a concerts index at `concertfix.com/concerts/arlington-tx` sent to
someone in Arlington, *Virginia*, and a chamber-of-commerce page for Alexandria
Bay, *New York*, sent to someone in Alexandria, *Virginia*. Both name their
region plainly; nothing was reading it.

The rule is deliberately narrow, because the cost of the two mistakes is not
symmetric. Admitting a find from the wrong state wastes a slot in a digest.
Rejecting a local one removes something the user wanted and leaves no trace it
existed — so this only refuses when the find is **explicit** about a region and
**none** of the regions it names is the user's.

That means silence is always safe: a find that never says where it is passes,
and is judged by everything else in the loop. It also means this cannot help
with a town whose page names no region at all, which is a real limit rather than
an oversight.

Nothing here infers. It reads what a page says about itself, the way the date
parser reads a date and refuses to guess one.
"""

import re

# The states, and the abbreviations a URL slug uses. Both spellings are needed:
# a page says "Arlington, Texas" in its title and `arlington-tx` in its path,
# and the second is the one that gave the wrong Arlington away.
_US_STATES: dict[str, str] = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
    "district of columbia": "dc",
}

_ABBREVIATIONS = {abbreviation: name for name, abbreviation in _US_STATES.items()}

# "Arlington, TX" and "Alexandria Bay, New York" — a region stated after a
# comma, which is how a page names the place it is actually about.
_AFTER_COMMA = re.compile(
    r",\s*(" + "|".join(sorted(_US_STATES, key=len, reverse=True)) + r"|[a-z]{2})\b",
    re.IGNORECASE,
)

# `/arlington-tx`, `/concerts/arlington-tx/`, `/va-alexandria`. A slug is the
# most reliable of the three signals because nobody writes one by accident.
_SLUG_NAMES = "|".join(
    name.replace(" ", "-") for name in sorted(_US_STATES, key=len, reverse=True)
)
_SLUG_REGION = re.compile(
    rf"[/-]([a-z]{{2}})(?=[/-]|$)|[/-]({_SLUG_NAMES})(?=[/-]|$)",
    re.IGNORECASE,
)


# Reduce any spelling of a region to one name, or nothing when it is not one.
def normalize_region(value: str) -> str | None:
    text = " ".join((value or "").split()).casefold().strip(" .,")
    if text in _US_STATES:
        return text
    if text in _ABBREVIATIONS:
        return _ABBREVIATIONS[text]
    return None


# Every region the text and URL explicitly claim, as full state names.
def stated_regions(title: str, summary: str | None, url: str | None) -> set[str]:
    found: set[str] = set()
    for blob in (title or "", summary or ""):
        for match in _AFTER_COMMA.finditer(blob):
            region = normalize_region(match.group(1))
            if region:
                found.add(region)
    for match in _SLUG_REGION.finditer(url or ""):
        raw = match.group(1) or match.group(2) or ""
        region = normalize_region(raw.replace("-", " "))
        if region:
            found.add(region)
    return found


# Whether a find contradicts where the user actually is.
#
# True only when the find names at least one region and none of them is the
# user's. With no locality region configured there is nothing to contradict, so
# nothing is refused — the same fail-open posture the rest of the loop takes.
def contradicts_locality(
    title: str,
    summary: str | None,
    url: str | None,
    locality_region: str | None,
) -> bool:
    home = normalize_region(locality_region or "")
    if home is None:
        return False
    claimed = stated_regions(title, summary, url)
    if not claimed:
        return False
    return home not in claimed
