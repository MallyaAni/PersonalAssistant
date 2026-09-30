"""The masking pass the tone-validity study reads releases through.

What has to hold: after masking a realistic release no issuer name,
ticker, month name or four-digit year survives; every dollar figure and
percentage does; a name is matched whole-word and with its possessive;
the boilerplate tail and every line with a way to reach someone are
gone; and masking a masked text changes nothing.
"""

import re

from backend.market import release_mask
from backend.market.release_mask import MaskIssuer, mask

RELEASE = """NVIDIA Announces Financial Results for Second Quarter Fiscal 2025
SANTA CLARA, Calif., Aug. 28, 2024 (GLOBE NEWSWIRE) -- NVIDIA (NASDAQ: NVDA) today
reported revenue for the second quarter ended July 28, 2024, of $30.0 billion,
up 15% from the previous quarter and up 122% from a year ago.
GAAP earnings per diluted share for the quarter were $0.67, up 12% from the
previous quarter and up 168% from a year ago. NVIDIA's GAAP gross margin was
75.1%, compared with 70.1% in Q2 2024 and 78.4% in Q1 FY25.
"Hopper demand remains strong, and the anticipation for Blackwell is
incredible," said Jensen Huang, founder and CEO of NVIDIA. Micron (NASDAQ: MU)
and AMD (AMD) were named as peers. Data Center revenue was $26.3 billion.
Outlook: for the third quarter of fiscal 2025, revenue is expected to be $32.5
billion, plus or minus 2%. In 2023 the company earned $2,024 million, and in
fourth-quarter 2022 it reported a 7/30/2022 record. FY2024 and fiscal 2023's
GAAP and non-GAAP gross margins are expected to be 74.4% and 75.0%.
NVIDIA will host a conference call on Sept. 10 at 2 p.m. Pacific time.
About NVIDIA
NVIDIA (NASDAQ: NVDA) is the world leader in accelerated computing. Since 1993.
For further information, contact:
Simona Jankowski, Investor Relations, sjankowski@nvidia.com, (408) 486-2000
www.nvidia.com/news
"""

ISSUER = MaskIssuer(
    names=("NVIDIA Corporation",),
    tickers=("NVDA",),
    people=("Jensen Huang",),
    products=("Blackwell", "Hopper"),
    other_tickers=("MU", "AMD", "ON"),
)


# Nothing identifying survives a realistic release: no issuer name, no
# ticker, no month, no year, no person, no product, no way to reach anyone.
def test_realistic_release_is_anonymised():
    out = mask(RELEASE, ISSUER)
    text = out.text
    assert not re.search(r"nvidia|nvda", text, re.IGNORECASE)
    assert not re.search(r"\b(?:19|20)\d\d\b", text)
    assert not re.search(
        r"\b(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|"
        r"Nov|Dec)\b",
        text,
    )
    assert "Huang" not in text
    assert "Blackwell" not in text
    assert "Hopper" not in text
    assert "@" not in text
    assert "www." not in text
    assert "486-2000" not in text
    assert "world leader" not in text  # the About section went with the tail
    assert release_mask.residuals(text, ISSUER.names) == {
        "year": 0,
        "month": 0,
        "name": 0,
    }


# The numbers stay: they are the content the reader scores.
def test_numbers_are_kept():
    text = mask(RELEASE, ISSUER).text
    for figure in (
        "$30.0 billion",
        "up 15%",
        "up 122%",
        "$0.67",
        "75.1%",
        "70.1%",
        "$26.3 billion",
        "$32.5",
        "plus or minus 2%",
        "$2,024 million",
        "74.4% and 75.0%",
    ):
        assert figure in text, figure


# Each replacement lands as the placeholder the plan names, and the counts
# say how many of each were made.
def test_placeholders_and_counts():
    out = mask(RELEASE, ISSUER)
    text = out.text
    assert text.startswith("[COMPANY] Announces Financial Results for [PERIOD]")
    assert "[COMPANY] (NASDAQ: [TICKER])" in text
    assert "[PERSON], founder and CEO of [COMPANY]" in text
    assert "Micron (NASDAQ: [TICKER])" in text
    assert "and AMD ([TICKER])" in text
    assert "[QUARTER] ended [DATE]" in text
    assert "in [PERIOD] and 78.4% in [PERIOD]" in text  # Q2 2024, Q1 FY25
    assert "for the [PERIOD], revenue" in text  # third quarter of fiscal 2025
    assert "In [YEAR] the company earned" in text
    assert "[PERIOD] it reported a [DATE] record" in text  # fourth-quarter 2022
    assert "record. [PERIOD] and [PERIOD]" in text  # FY2024, fiscal 2023's
    assert "call on [DATE] at 2 p.m." in text
    assert out.counts["company"] >= 5
    assert out.counts["ticker"] == 1
    assert out.counts["other_ticker"] == 2
    assert out.counts["person"] == 1
    assert out.counts["product"] == 2
    assert out.counts["about_section"] == 1
    assert out.counts["trailer"] == 1


# Case and possessives: "nvidia", "NVIDIA's" and "Nvidia Corp." all go; a
# name inside another word stays, because it is a different word.
def test_case_possessive_and_word_boundaries():
    issuer = MaskIssuer(names=("Micron Technology, Inc.",), tickers=("MU",))
    text = mask(
        "MICRON's revenue. micron technology grew. Micron's margin. "
        "An omicron variant and a MUSE product; MU (MU) rose.",
        issuer,
    ).text
    assert "MICRON" not in text
    assert "micron technology" not in text
    assert "[COMPANY] revenue. [COMPANY] grew. [COMPANY] margin." in text
    assert "omicron" in text
    assert "MUSE" in text
    assert "[TICKER] ([TICKER]) rose" in text


# Masking twice is the same as masking once.
def test_masking_is_idempotent():
    once = mask(RELEASE, ISSUER)
    twice = mask(once.text, ISSUER)
    assert twice.text == once.text
    assert all(v == 0 for k, v in twice.counts.items())


# Name variants: the legal name, its shorter forms and a distinctive first
# word; a generic first word is not a name on its own.
def test_name_variants():
    assert release_mask.name_variants("NVIDIA Corporation") == (
        "NVIDIA Corporation",
        "NVIDIA",
    )
    assert "Micron" in release_mask.name_variants("Micron Technology, Inc.")
    assert "Advanced" not in release_mask.name_variants("Advanced Micro Devices")
    assert release_mask.name_variants("") == ()


# Amounts and decimals that look like years are not years.
def test_amounts_are_not_years():
    text = mask("Revenue of $2,024 million and 2024.5 units in 12024 and 2024.", ISSUER)
    assert (
        text.text == "Revenue of $2,024 million and 2024.5 units in 12024 and [YEAR]."
    )


# The leak prompt is the masked text followed by the fixed question.
def test_leak_prompt():
    prompt = release_mask.leak_prompt("  masked body  ")
    assert prompt.startswith("masked body\n\n")
    assert prompt.endswith("Answer as JSON {company, quarter, year}.")
    assert "Which company issued this release" in prompt


# A "Contact" in the first half is content; only the tail is cut.
def test_trailer_is_cut_only_in_the_tail():
    body = "\n".join(["Contact lens revenue rose 5%."] + ["Margin held."] * 6)
    assert mask(body, ISSUER).text.startswith("Contact lens revenue rose 5%.")
    tail = body + "\nInvestor Contact:\nJane Doe\n"
    out = mask(tail, ISSUER)
    assert "Jane Doe" not in out.text
    assert out.counts["trailer"] == 1
