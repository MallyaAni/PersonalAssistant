"""One way to write a phone number, so two spellings of it are one person.

A phone number is how the iMessage bridge decides who is talking: a sender's
normalized address is looked up against the subscriber allowlist, and an
address that matches nothing is answered by nobody. So the number collected at
sign-up is not a contact detail, it is a credential, and it has to survive
being typed by a human in whatever form their country writes numbers in.

**E.164 is required, and that is the point.** A bare `2025550100` is a valid
local number in several countries at once, and nothing in the string says
which. Requiring the `+` and the country code makes the number self-describing,
which is the only way one allowlist can serve people in different places. The
cost is that someone typing their own number the way they say it out loud gets
rejected once and has to add `+1`; the alternative is guessing a country from
an IP address and occasionally guessing wrong about who is allowed to talk to
the assistant.

Storage follows the pattern the rest of this codebase uses for anything that
identifies a person: the value is encrypted at rest, and a separate digest
carries uniqueness and lookup. The digest is computed from
`discovery.addressing.normalize_address`, deliberately - matching has to agree
with the iMessage worker's own comparison, and the way to guarantee that is to
call the same function rather than to write a second one that looks equivalent.
"""

import re

# E.164: a plus, a country code that cannot start with zero, then up to
# fourteen more digits. Fifteen digits total is the standard's ceiling.
#
# `re.ASCII` is load-bearing, not cosmetic. Without it `\d` matches Unicode
# digits, so a number typed in Arabic-Indic numerals ("+1٢٠٢...") passes here
# and then collapses to a useless key downstream, where `normalize_address`
# and the bridge both strip on ASCII `[^0-9]` only. Two different such numbers
# both reduce to their country code alone and collide. Match only ASCII 0-9.
_E164 = re.compile(r"^\+[1-9][0-9]{7,14}$", re.ASCII)

# The ASCII digits, named once so the country-code check below cannot drift
# back to `str.isdigit()`, which is Unicode-aware and accepts the same numerals
# the regex above exists to reject.
_ASCII_DIGITS = frozenset("0123456789")

# What people actually type: spaces, hyphens, dots, and brackets around an area
# code, plus the Unicode dashes a number pasted from a web page carries. All of
# it is decoration around the digits.
_DECORATION = re.compile(r"[\s\-().‐-―]")

# A leading 00 is how much of the world dials internationally; it means the
# same thing as a plus and arrives often enough to be worth accepting.
_INTERNATIONAL_PREFIX = "00"


class InvalidPhoneNumber(ValueError):
    """The number cannot be stored, with a reason a person can act on."""


# Strip the decoration and return E.164, or raise with something worth showing.
#
# Deliberately strict about the country code and forgiving about everything
# else: "+1 (202) 555-0100", "+1.202.555.0100" and "0012025550100" are the same
# number and all three are accepted, while "2025550100" is refused because it
# does not say which country it belongs to.
def to_e164(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise InvalidPhoneNumber("A phone number is required.")

    cleaned = _DECORATION.sub("", raw)
    if cleaned.startswith(_INTERNATIONAL_PREFIX):
        cleaned = "+" + cleaned[len(_INTERNATIONAL_PREFIX) :]

    if not cleaned.startswith("+"):
        raise InvalidPhoneNumber(
            "Include the country code, starting with + - for example "
            "+1 202 555 0100 or +44 20 7946 0958. Without it the same digits "
            "are a different person in a different country."
        )
    if not cleaned[1:] or set(cleaned[1:]) - _ASCII_DIGITS:
        raise InvalidPhoneNumber(
            "A phone number can only contain digits after the country code."
        )
    if not _E164.match(cleaned):
        raise InvalidPhoneNumber(
            "That does not look like a complete international number. It "
            "should be a + and 8 to 15 digits in total."
        )
    return cleaned


# The value the allowlist is matched on, computed the same way the iMessage
# worker computes it for an incoming sender.
#
# Imported here rather than reimplemented: if these two ever disagree, a person
# who signed up correctly is silently unable to text, and nothing anywhere
# reports it.
def matching_key(value: str) -> str:
    from backend.discovery.addressing import normalize_address

    return normalize_address(to_e164(value))
