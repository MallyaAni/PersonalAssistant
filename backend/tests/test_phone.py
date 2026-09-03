

# Two sign-ups typed "+" and their ten-digit US number, as the field's
# example invited, and were stored as Slovenia and the Seychelles
# (2026-09-02). Ten digits in NANP shape are +1 and those digits, with or
# without the plus; a number that already carries a country code is kept.
def test_a_ten_digit_us_number_is_plus_one_with_or_without_the_plus():
    from backend.core.phone import to_e164

    assert to_e164("+3864054564") == "+13864054564"
    assert to_e164("2486305184") == "+12486305184"
    assert to_e164("(386) 405-4564") == "+13864054564"
    assert to_e164("+1 205 704 9267") == "+12057049267"
    assert to_e164("+44 20 7946 0958") == "+442079460958"
    # Eleven digits starting with 1 are already a NANP number with its code.
    assert to_e164("12057049267") == "+12057049267"
