"""One canonical form for a delivery address.

A person typing their own phone number writes it a different way every time:
`202-555-0143`, `(202) 555-0143`, `+1 202 555 0143`. Stored verbatim these are
three different subscriptions with three different identity digests, so the
same person could hold "one subscription per account" three times over — and
none of them need match the number an operator typed into the sending bridge's
allowlist, which is how a digest gets refused at the last hop for a recipient
who did everything right.

The rule is deliberately small and shared with the bridge rather than clever:
strip everything that is not a digit, and drop a North American country code
when doing so leaves a ten-digit number. `+12025550143` and `2025550143` are
the same phone, and that is the only equivalence worth asserting without a
phone-number library and a country to interpret against.

Anything that is not phone-shaped is left alone apart from case and spacing, so
an Apple ID email normalizes the way an email should and nothing else is
guessed at.
"""

import re

_NON_DIGITS = re.compile(r"[^0-9]")

# The North American country code, dropped only when what remains is a full
# ten-digit number. Removing a leading 1 from anything else would corrupt an
# international number that legitimately starts with one.
_NANP_CODE = "1"
_NANP_DIGITS = 10


# Reduce an address to the form used for storage, identity, and comparison.
def normalize_address(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return ""
    if "@" in cleaned:
        # An Apple ID is an email; case never distinguishes two of them.
        return cleaned.casefold()
    digits = _NON_DIGITS.sub("", cleaned)
    if not digits:
        # Not phone-shaped and not an email: keep what the user wrote rather
        # than inventing a form for something unrecognized.
        return cleaned
    if len(digits) == _NANP_DIGITS + 1 and digits.startswith(_NANP_CODE):
        return digits[1:]
    return digits


# Whether two addresses are the same destination once written the same way.
def same_address(left: str, right: str) -> bool:
    return normalize_address(left) == normalize_address(right)
