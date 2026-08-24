"""A phone number at sign-up is what makes an approved person reachable.

The iMessage path has two gates and they are easy to confuse. AniOS keeps a
subscriber table that maps a sender to an account - without a row there, an
inbound text belongs to nobody and is ignored. The Mac keeps its own recipient
allowlist, and it is the last hop before a message reaches a real person; it
refuses regardless of what AniOS was persuaded to ask for.

Approving a sign-up has to satisfy both, or the failure is the one already on
record: a subscriber approved, her digest built on time, and the bridge
refusing it at the last hop with nothing in the run to say why.

These are structural because the interesting parts are a format rule and a
wiring claim, neither of which needs a model. The format rule gets real
numbers from four countries, because "works internationally" is the actual
requirement and a US-only regex would pass a test written with US numbers.
"""

import inspect

import pytest

from backend.core.phone import InvalidPhoneNumber, matching_key, to_e164
from backend.discovery.addressing import normalize_address


# Real numbers, written the way people in each place write them.
@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("+1 (202) 555-0100", "+12025550100"),
        ("+1.202.555.0100", "+12025550100"),
        ("0012025550100", "+12025550100"),
        ("+44 20 7946 0958", "+442079460958"),
        ("+91 98765 43210", "+919876543210"),
        ("+81 3-1234-5678", "+81312345678"),
        ("+61 2 9374 4000", "+61293744000"),
    ],
)
def test_international_numbers_reach_one_canonical_form(typed: str, expected: str):
    assert to_e164(typed) == expected


# A bare national number is the case that must be refused, and the reason is
# not pedantry: the same ten digits are a different person in another country.
def test_a_number_without_a_country_code_is_refused():
    with pytest.raises(InvalidPhoneNumber, match="country code"):
        to_e164("2025550100")


@pytest.mark.parametrize("bad", ["", "   ", "+123", "+0123456789", "+1abc", "hello"])
def test_unusable_numbers_are_refused_with_a_reason(bad: str):
    with pytest.raises(InvalidPhoneNumber) as raised:
        to_e164(bad)
    # Every message has to be something a person can act on, not "invalid".
    assert len(str(raised.value)) > 20


# Unicode digits must be refused, not accepted-then-collapsed. Arabic-Indic
# numerals satisfy a Unicode-aware \d and str.isdigit(), then vanish under the
# ASCII-only normalizer downstream, where two different such numbers both
# reduce to their country code alone and collide.
@pytest.mark.parametrize(
    "sneaky",
    ["+1٢٠٢٥٥٥٠١٠٠", "+１２３４５６７８"],
)
def test_unicode_digits_are_refused(sneaky: str):
    with pytest.raises(InvalidPhoneNumber):
        to_e164(sneaky)


# The allowlist match must be computed the way the iMessage worker computes it.
# If these two ever disagree, someone who signed up correctly silently cannot
# text and nothing anywhere reports it.
def test_the_matching_key_agrees_with_the_imessage_worker():
    for typed in ("+1 (202) 555-0100", "+44 20 7946 0958", "0012025550100"):
        assert matching_key(typed) == normalize_address(to_e164(typed))


# Two spellings of one number are one person to the allowlist.
def test_two_spellings_of_one_number_match():
    assert matching_key("+1 (202) 555-0100") == matching_key("+1 202 555 0100")
    assert matching_key("0012025550100") == matching_key("+1-202-555-0100")


# Different numbers must not collide, including across countries.
def test_different_numbers_do_not_collide():
    keys = {
        matching_key(n)
        for n in ("+12025550100", "+12025550101", "+442079460958", "+919876543210")
    }
    assert len(keys) == 4


# The sign-up body must require it, or the allowlist has a hole the size of
# everyone who left the field blank.
def test_the_signup_body_requires_a_phone_number():
    from backend.api.v1.auth import AccessRequestBody

    fields = AccessRequestBody.model_fields
    assert "phone" in fields, "sign-up does not collect a number"
    assert fields["phone"].is_required(), "the number is optional; it must not be"


# Both gates, asserted on the source of the approval path. A wiring claim is
# what this feature is; the alternative is a live test that needs a Mac.
def test_approval_enrols_the_number_and_grants_it_on_the_bridge():
    from backend.api.v1.admin import approve_access_request

    source = inspect.getsource(approve_access_request)
    assert "SubscriberRepository" in source and ".enroll(" in source, (
        "approval does not enrol the number, so an inbound text maps to nobody"
    )
    assert "grant_recipient_on_bridge" in source, (
        "approval does not grant the number on the Mac, so the bridge refuses "
        "at the last hop with nothing in the run to say why"
    )
    # Enrolling must come first: granting on the Mac for an account that has no
    # subscriber row would let a text through to nobody.
    assert source.index(".enroll(") < source.index("grant_recipient_on_bridge")
