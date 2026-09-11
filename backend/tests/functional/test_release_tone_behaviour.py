"""Does the release reader score what a company states, and only that?

The prompt claims four things, and each is a case here:

- **A stated outlook is read as guidance.** A release that gives a figure
  for the coming quarter above the one just reported, and says spending is
  rising and supply is tight, must come back with positive guidance,
  positive capex, and a supply score above the midpoint. A first-draft
  instruction returned zeros for exactly this text; the prompt exists so it
  does not.
- **A lowered outlook is negative.** A release that cuts its range and
  describes weakening orders must score guidance and demand below zero.
- **A reported quarter is the past.** A release with a large reported
  revenue figure and no forward-looking statement at all must score
  guidance exactly 0, whatever the size of the number.
- **The summary is one plain sentence.** Non-empty, within the bound.

Each release is written the way companies write them, so the prompt is
measured on the real shape rather than on tidy examples.
"""

import pytest

from backend.agents.trading.release_tone import ReleaseToneReader

pytestmark = pytest.mark.asyncio

_RAISED = (
    "Halcyon Compute Announces Second Quarter Results\n\n"
    "Revenue for the quarter was $2.41 billion, up 38% from a year ago and "
    "up 9% from the prior quarter. GAAP gross margin was 61.2%.\n\n"
    "Outlook. For the third quarter, the company expects revenue of $2.75 "
    "billion, plus or minus 2%, and gross margin of approximately 62%. "
    "Demand for accelerated infrastructure continues to exceed our ability "
    "to supply it, with lead times for high-bandwidth memory extending into "
    "next year. To meet this demand we are increasing capital expenditure "
    "for the year to approximately $1.9 billion from the $1.4 billion "
    "previously planned.\n\n"
    "The company will host a conference call at 2 p.m. Pacific time."
)

_CUT = (
    "Meridian Software Reports Fiscal Third Quarter Results\n\n"
    "Total revenue was $884 million, an increase of 4% year over year. "
    "Subscription revenue was $790 million.\n\n"
    "Business Outlook. Based on information available as of today, the "
    "company is lowering its full-year revenue guidance to a range of "
    "$3.45 billion to $3.50 billion, from the prior range of $3.62 billion "
    "to $3.68 billion. New bookings declined in the quarter as customers "
    "extended sales cycles and reduced seat counts, and we expect these "
    "conditions to persist through the remainder of the year. We are "
    "reducing planned headcount and capital spending accordingly."
)

_FACTS_ONLY = (
    "Corvid Memory Corporation Reports Fourth Quarter and Full Year Results\n\n"
    "Fourth quarter revenue was $8.71 billion. Full year revenue was $31.2 "
    "billion. Fourth quarter net income was $1.92 billion, or $1.71 per "
    "diluted share. Operating cash flow for the year was $9.8 billion. Cash "
    "and investments totalled $12.4 billion at year end. The board declared "
    "a quarterly dividend of $0.12 per share payable on the 28th.\n\n"
    "Quarterly financial tables follow.\n"
    "Revenue 8,710 7,950 6,120\nGross margin 41.0% 39.5% 36.2%\n"
    "Operating expenses 1,210 1,180 1,090\n"
)


@pytest.fixture(scope="module")
def reader(structured_llm):
    return ReleaseToneReader(structured_llm)


# A raised outlook with rising capex and tight supply reads that way.
async def test_a_raised_outlook_scores_positive(reader):
    tone = await reader.score(_RAISED)
    assert tone is not None
    assert tone.guidance > 0.3, tone
    assert tone.capex > 0.3, tone
    assert tone.supply_constrained > 0.5, tone
    assert tone.demand > 0.3, tone


# A lowered range with weakening orders reads negative on both counts.
async def test_a_lowered_outlook_scores_negative(reader):
    tone = await reader.score(_CUT)
    assert tone is not None
    assert tone.guidance < -0.3, tone
    assert tone.demand < 0, tone
    assert tone.capex < 0, tone


# Large reported numbers with no outlook are not an outlook.
async def test_reported_results_without_an_outlook_are_neutral(reader):
    tone = await reader.score(_FACTS_ONLY)
    assert tone is not None
    assert tone.guidance == 0, tone
    assert abs(tone.demand) <= 0.2, tone


# The summary is one bounded sentence, and the reading is deterministic.
async def test_summary_is_bounded_and_scores_repeat(reader):
    first = await reader.score(_RAISED)
    second = await reader.score(_RAISED)
    assert first is not None
    assert second is not None
    assert 5 <= len(first.summary) <= 240
    assert first.guidance == second.guidance
    assert first.capex == second.capex


# A release that dates its quarter and states its numbers hands them to the
# fundamental layer: the model reports the quarter it covers, revenue, EPS,
# net income and gross margin as stated, on the release's own figures.
async def test_the_reported_financials_are_extracted(reader):
    release = (
        "Vantage Optics Reports Results for the Quarter Ended June 30, 2026\n\n"
        "Revenue for the quarter ended June 30, 2026 was $4.42 billion, "
        "compared with $3.18 billion in the same quarter last year. Net "
        "income was $1.21 billion, or $3.42 per diluted share. GAAP gross "
        "margin was 64.8%.\n\n"
        "For the third quarter of fiscal 2026, the company expects revenue "
        "of $4.65 billion, plus or minus 2%.\n\n"
        "The company will host a conference call at 2 p.m. Pacific time."
    )
    tone = await reader.score(release)
    assert tone is not None
    assert tone.quarter_end == "2026-06-30"
    assert tone.revenue_usd_m == pytest.approx(4420.0, rel=0.02)
    assert tone.net_income_usd_m == pytest.approx(1210.0, rel=0.02)
    assert tone.eps_usd == pytest.approx(3.42, rel=0.02)
    assert tone.gross_margin_pct == pytest.approx(64.8, rel=0.02)


# A release that states no figures at all leaves the financials null rather
# than carrying numbers over from elsewhere.
async def test_financials_are_null_when_not_stated(reader):
    sparse = (
        "Delta Systems Announces Third Quarter Results\n\n"
        "The company reported record results for the quarter. Full details "
        "are available in the accompanying financial tables.\n\n"
        "Outlook. For the fourth quarter the company expects continued "
        "growth and plans to raise its dividend.\n"
    )
    tone = await reader.score(sparse)
    assert tone is not None
    assert tone.revenue_usd_m is None
    assert tone.eps_usd is None
    assert tone.net_income_usd_m is None
    assert tone.gross_margin_pct is None
