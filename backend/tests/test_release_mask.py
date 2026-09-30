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


# The stored text is one line (`edgar.html_to_text` collapses whitespace):
# the About paragraph and the contact block go, bounded by the next
# heading, and the statements and tables after them survive with their
# numbers.
def test_one_line_release_keeps_the_tables():
    one_line = " ".join(RELEASE.split()) + (
        " Forward-Looking Statements Certain statements in this press release "
        "including statements about NVIDIA's growth are forward-looking. "
        "NVIDIA CORPORATION CONDENSED CONSOLIDATED STATEMENTS OF INCOME "
        "Three Months Ended July 28, 2024 Revenue $ 30,040 $ 13,507 "
        "Net income $ 16,599"
    )
    out = mask(one_line, ISSUER)
    assert "\n" not in out.text
    assert "world leader" not in out.text
    assert "Jankowski" not in out.text
    assert "Forward-Looking Statements Certain statements" in out.text
    assert "[COMPANY] growth are forward-looking" in out.text
    assert "[COMPANY] CONDENSED CONSOLIDATED STATEMENTS OF INCOME" in out.text
    assert "Three Months Ended [DATE] Revenue $ 30,040 $ 13,507" in out.text
    assert "Net income $ 16,599" in out.text
    assert out.counts["about_section"] == 1
    assert out.counts["trailer"] == 1
    assert out.counts["contact"] == 3
    assert release_mask.residuals(out.text, ISSUER.names)["name"] == 0
    assert mask(out.text, ISSUER).text == out.text


# The corpus rule: a token in two of twenty issuers is a name and goes; one
# in sixteen is the language of releases and stays; it is case-sensitive;
# letters-and-digits tokens count; consecutive names collapse into one.
def test_corpus_rule():
    common = "Revenue grew and GAAP margin held; the Blackwell platform shipped. "
    corpus = {f"I{i}": [common] for i in range(16)}
    corpus["I0"] = [common + "Jensen Huang and the A100 and 1z node. jensen too."]
    corpus["I1"] = [common + "Jensen Huang spoke."]
    for i in range(16, 20):
        corpus[f"I{i}"] = ["Revenue fell."]
    rare = release_mask.rare_tokens(corpus, min_issuers=15)
    assert {"Jensen", "Huang", "A100", "1z"} <= rare
    assert "jensen" not in rare  # lower case is not considered
    assert "Blackwell" not in rare  # 16 issuers
    assert "GAAP" not in rare
    assert "Revenue" not in rare
    counts = release_mask.token_issuer_counts(corpus)
    assert counts["Blackwell"] == 16
    assert counts["Jensen"] == 2
    out = release_mask.mask(
        "Jensen Huang, Jensen's A100 and 1z, said jensen. Blackwell grew 10%.",
        MaskIssuer(names=(), tickers=()),
        rare,
    )
    assert out.text == "[NAME] and [NAME], said jensen. Blackwell grew 10%."
    assert out.counts["rare"] == 5
    # A placeholder is never in the set, so a masked text is never re-masked.
    assert "COMPANY" not in release_mask.rare_tokens({"I0": ["[COMPANY] grew."]})


# The dateline city and the wire tag go, before a date or a dash, in each
# of the forms the corpus uses.
def test_dateline_and_wire_tags():
    issuer = MaskIssuer(names=(), tickers=())
    cases = {
        "SAN JOSE, Calif. -- May 4, 2021 (BUSINESS WIRE) -- Super grew.": (
            "[CITY] [DATE] -- Super grew."
        ),
        "SANTA CLARA, Calif.-Nov. 18, 2020- Revenue rose.": (
            "[CITY] [DATE]- Revenue rose."
        ),
        "BOISE, Idaho, Sept. 29, 2020 \u2013 Micron reported.": (
            "[CITY] [DATE] \u2013 Micron reported."
        ),
        "NEW YORK--(GLOBE NEWSWIRE)--The company said.": "[CITY] --The company said.",
        "Revenue rose 5% in the quarter.": "Revenue rose 5% in the quarter.",
    }
    for text, expected in cases.items():
        out = release_mask.mask(text, issuer)
        assert out.text == expected, text
    out = release_mask.mask(cases and next(iter(cases)), issuer)
    assert out.counts["dateline"] == 1
    assert out.counts["wire"] == 1


# People after "said" or before a title are masked without the corpus.
def test_people_after_said_or_before_a_title():
    issuer = MaskIssuer(names=("NVIDIA",), tickers=("NVDA",))
    out = release_mask.mask(
        '"Demand is strong," said Jensen Huang, founder and CEO of NVIDIA. '
        "Colette Kress, executive vice president and CFO, added. "
        "Sanjay Mehrotra, President and Chief Executive Officer of Micron. "
        "Results were said to be strong, the company said.",
        issuer,
    )
    assert "said [NAME], founder and CEO of [COMPANY]." in out.text
    assert "[NAME], executive vice president and CFO, added." in out.text
    assert "[NAME], President and Chief Executive Officer of Micron." in out.text
    assert "Results were said to be strong, the company said." in out.text
    assert out.counts["people"] == 3


# HTML entities are decoded so an exchange label is an exchange label, the
# company's legal tail goes with its short name, and a truncated address
# is still an address.
def test_entities_legal_tail_and_emails():
    issuer = MaskIssuer(names=("Supermicro", "Super Micro"), tickers=("SMCI",))
    out = release_mask.mask(
        "EX-99.1 2 exhibit991_20210331.htm Super Micro Computer, Inc. "
        "(Nasdaq&#58; SMCI) &#8226; Net sales of $896&#160;million. "
        "Contact farhanahmad&#64; or ir@supermicro.com now.",
        issuer,
    )
    assert "exhibit991" not in out.text
    assert "[COMPANY] (Nasdaq: [TICKER]) \u2022 Net sales of $896 million." in out.text
    assert "Contact [EMAIL] or [EMAIL] now." in out.text
    assert out.counts["email"] == 2
    assert out.counts["company"] == 2  # the short name, then its legal tail
    assert "Super" not in out.text
    assert "Computer" not in out.text
