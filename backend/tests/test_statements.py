"""The standardised, anonymised statement blocks (A2).

What has to hold: a block carries no ticker, no issuer name, no four-digit
run (so no year), no month name and no currency name, over every block
of a synthetic filer whose numbers are chosen to look like years; an
observation is dated by the availability of the filing that completed its
latest quarter, with the after-the-close rule; a restatement filed later
cannot change an earlier block and makes no observation of its own; a
name needs eight consecutive quarters before its first observation and a
gap in the quarters withholds one; derived lines are arithmetic on two
filed lines and read n/a when either is missing; operating income is
always n/a; EPS takes reported quarter spans only; the realised
directions and the persistence baseline read from the next observation;
stances carry forward from the first session on or after availability.
"""

import re
from datetime import date, timedelta

import numpy as np

from backend.market import fundamentals_asof as fa
from backend.market import statements as st
from backend.market.universe import build_universe

MONTHS = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


# The quarter end `i` quarters after the quarter starting at `start`.
def quarter_end(start: date, i: int) -> date:
    months = (start.month - 1) + 3 * (i + 1)
    return date(start.year + months // 12, months % 12 + 1, 1) - timedelta(days=1)


# The quarter start `i` quarters after `start`.
def quarter_start(start: date, i: int) -> date:
    months = (start.month - 1) + 3 * i
    return date(start.year + months // 12, months % 12 + 1, 1)


# Quarterly duration rows for one tag, each filed `lag` days after its end.
def flow_rows(
    values, start=date(2015, 1, 1), lag=40, accepted_hour="21:05", prefix="q"
):
    rows = []
    for i, val in enumerate(values):
        end = quarter_end(start, i)
        filed = end + timedelta(days=lag)
        rows.append(
            {
                "start": quarter_start(start, i).isoformat(),
                "end": end.isoformat(),
                "val": val,
                "filed": filed.isoformat(),
                "accn": f"{prefix}{i}",
                "form": "10-Q",
                "accepted": f"{filed.isoformat()}T{accepted_hour}:00Z",
            }
        )
    return rows


# Instant rows for one tag at each quarter end.
def instant_rows(values, start=date(2015, 1, 1), lag=40):
    rows = []
    for i, val in enumerate(values):
        end = quarter_end(start, i)
        filed = end + timedelta(days=lag)
        rows.append(
            {
                "end": end.isoformat(),
                "val": val,
                "filed": filed.isoformat(),
                "accn": f"i{i}",
                "form": "10-Q",
                "accepted": f"{filed.isoformat()}T21:05:00Z",
            }
        )
    return rows


# A company-facts payload from {tag: rows}.
def payload(**tags):
    return {
        "facts": {
            "us-gaap": {tag: {"units": {"USD": rows}} for tag, rows in tags.items()}
        }
    }


# A full filer over `n` quarters whose figures are chosen to resemble years
# (revenue 2,015 million and up, assets 1,999 million), to make the
# anonymity test bite.
def filer(n=12, **overrides):
    revenue = [2_015e6 + 1e6 * i for i in range(n)]
    tags = {
        "Revenues": flow_rows(revenue),
        "GrossProfit": flow_rows([r * 0.6 for r in revenue]),
        "NetIncomeLoss": flow_rows([r * 0.2 for r in revenue]),
        "EarningsPerShareDiluted": flow_rows([0.5 + 0.05 * i for i in range(n)]),
        "NetCashProvidedByUsedInOperatingActivities": flow_rows(
            [r * 0.25 for r in revenue]
        ),
        "PaymentsToAcquirePropertyPlantAndEquipment": flow_rows(
            [r * 0.1 for r in revenue]
        ),
        "Assets": instant_rows([1_999e6 + 1e6 * i for i in range(n)]),
        "StockholdersEquity": instant_rows([1_000e6] * n),
        "CashAndCashEquivalentsAtCarryingValue": instant_rows([2_024e6] * n),
        "LongTermDebtNoncurrent": instant_rows([2_000e6] * n),
    }
    tags.update(overrides)
    return fa.parse_versions(payload(**tags))


def test_no_name_ticker_year_month_or_currency_appears_in_any_block():
    universe = build_universe()
    tickers = {m.ticker for m in universe if len(m.ticker) >= 2}
    names = {m.name.lower() for m in universe if m.name}
    rows = st.observations(filer())
    assert rows
    for row in rows:
        text = row.block
        lowered = text.lower()
        assert not re.search(r"\d{4}", text), text
        assert not any(month in lowered for month in MONTHS), text
        assert not re.search(r"\b(usd|eur|twd|nt\$|\$|€)", lowered), text
        words = set(re.findall(r"[A-Za-z][A-Za-z.&-]*", text))
        assert not (words & tickers), words & tickers
        assert not any(name in lowered for name in names)
        assert "2015" not in text
        assert "2024" not in text


def test_an_observation_is_dated_by_the_availability_of_its_latest_quarter():
    rows = st.observations(filer())
    first = rows[0]
    # Eight quarters from 2015-Q1 end at 2016-12-31; filed 40 days later at
    # 21:05 UTC, after the New York close, so available the next day.
    assert first.quarter_end == date(2016, 12, 31)
    assert first.available == date(2017, 2, 10)
    assert first.quarter_ends[0] == date(2015, 3, 31)
    assert len(first.quarter_ends) == 8
    assert first.anchor == "net_income"
    # One observation per later quarter, each dated by its own filing.
    assert [r.quarter_end for r in rows] == [
        quarter_end(date(2015, 1, 1), i) for i in range(7, 12)
    ]
    assert all(b.available > a.available for a, b in zip(rows, rows[1:], strict=False))


def test_a_filing_accepted_before_the_close_is_available_that_day():
    versions = filer(NetIncomeLoss=flow_rows([1e6] * 12, accepted_hour="13:00"))
    rows = st.observations(versions)
    assert rows[0].available == date(2017, 2, 9)


def test_a_restatement_cannot_change_an_earlier_block_and_makes_no_observation():
    base = filer()
    before = st.observations(base)
    restated = base + fa.parse_versions(
        payload(
            NetIncomeLoss=[
                {
                    "start": "2016-07-01",
                    "end": "2016-09-30",
                    "val": 999e6,
                    "filed": "2017-06-01",
                    "accn": "r1",
                    "form": "10-K/A",
                    "accepted": "2017-06-01T20:00:00Z",
                }
            ]
        )
    )
    after = st.observations(restated)
    assert len(after) == len(before)
    # Blocks made before the restatement's availability are identical.
    for a, b in zip(before, after, strict=True):
        if a.available < date(2017, 6, 2):
            assert a.block == b.block
    # Those after it carry the restated quarter where it is in the window.
    later = [b for b in after if b.available >= date(2017, 6, 2)]
    assert later
    assert "999.0" in later[0].block


def test_eight_consecutive_quarters_are_required():
    assert st.observations(filer(n=7)) == []
    # A gap in the anchor withholds the observation whose window spans it.
    values = [1e6] * 12
    rows = flow_rows(values)
    del rows[9]  # 2017-Q2 missing from net income
    gapped = st.observations(filer(NetIncomeLoss=rows))
    ends = [r.quarter_end for r in gapped]
    # The windows ending at Q8 and Q9 lie before the gap and are observed;
    # every later window within twelve quarters spans the gap, so nothing
    # after it is observed until eight consecutive quarters exist again.
    assert quarter_end(date(2015, 1, 1), 7) in ends
    assert quarter_end(date(2015, 1, 1), 8) in ends
    assert all(e <= quarter_end(date(2015, 1, 1), 8) for e in ends)


def test_derived_lines_need_both_inputs_and_operating_income_is_absent():
    rows = st.observations(filer())
    values = rows[0].values
    assert (
        values["cost_of_revenue"][0] == values["revenue"][0] - values["gross_profit"][0]
    )
    assert values["liabilities"][0] == values["assets"][0] - values["equity"][0]
    assert all(v is None for v in values["operating_income"])
    assert "Operating income" in rows[0].block
    without_gross = st.observations(filer(GrossProfit=[]))
    assert all(v is None for v in without_gross[0].values["cost_of_revenue"])
    assert all(v is None for v in without_gross[0].values["gross_profit"])
    assert without_gross[0].lines_present == rows[0].lines_present - 2


def test_eps_uses_reported_quarters_only_and_is_not_scaled():
    # A year-to-date EPS span must not be differenced into a quarter.
    eps = flow_rows([1.0] * 12)
    eps.append(
        {
            "start": "2015-01-01",
            "end": "2015-06-30",
            "val": 5.0,
            "filed": "2015-08-10",
            "accn": "ytd",
            "form": "10-Q",
            "accepted": "2015-08-10T21:05:00Z",
        }
    )
    rows = st.observations(filer(EarningsPerShareDiluted=eps))
    assert rows[0].values["eps"] == (1.0,) * 8
    assert "1.00" in rows[0].block


def test_revenue_anchors_a_filer_without_net_income():
    rows = st.observations(filer(NetIncomeLoss=[]))
    assert rows
    assert rows[0].anchor == "revenue"
    assert all(v is None for v in rows[0].values["net_income"])


def test_format_cell_renders_millions_with_separators_and_na():
    assert st.format_cell(1_234_567_890.0) == "1,234.6"
    assert st.format_cell(-5e6) == "-5.0"
    assert st.format_cell(None) == "n/a"
    assert st.format_cell(float("nan")) == "n/a"
    assert st.format_cell(12.345, per_share=True) == "12.35"


def test_realised_directions_and_persistence_read_from_the_next_observation():
    revenue = [1e6] * 12
    net = [10, 20, 30, 40, 50, 60, 70, 80, 45, 100, 110, 120]  # Q9 (45) < Q5 (50)
    rows = st.observations(
        filer(
            Revenues=flow_rows(revenue),
            NetIncomeLoss=flow_rows([v * 1e6 for v in net]),
        )
    )
    realised = st.realised_directions(rows)
    # The first observation (Q8 = 80) is followed by Q9 = 45: down YoY
    # against Q5 = 50, down sequentially against Q8 = 80.
    assert realised[0] == (-1, -1)
    # The second (Q9 = 45) is followed by Q10 = 100: up on both counts.
    assert realised[1] == (1, 1)
    assert realised[-1] == (None, None)
    # Persistence: the first observation's own Q8 - Q4 is 80 - 40 > 0.
    assert st.persistence_direction(rows[0]) == 1


def test_a_missing_next_quarter_gives_no_realised_direction():
    rows = st.observations(filer())
    broken = [rows[0], rows[2]]  # one quarter skipped between them
    assert st.realised_directions(broken)[0] == (None, None)


def test_stances_carry_forward_from_the_session_on_or_after_availability():
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(10)],
        dtype="datetime64[D]",
    )
    out = st.aligned_stances(
        dates,
        ("A", "B"),
        {"A": [(date(2024, 1, 3), 0.2), (date(2024, 1, 7), -0.1)]},
    )
    assert np.isnan(out[:2, 0]).all()
    assert (out[2:6, 0] == 0.2).all()
    assert (out[6:, 0] == -0.1).all()
    assert np.isnan(out[:, 1]).all()


def test_the_block_sha_identifies_the_text():
    rows = st.observations(filer())
    assert rows[0].sha256 == st.block_sha(rows[0].block)
    assert rows[0].sha256 != rows[1].sha256
