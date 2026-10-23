"""The chart replay's grade changes come from the same run as its trades."""

from backend.cli import market_policy_replay_research as research
from backend.tests.test_market_pit_scorecard import _report, history  # noqa: F401


# Each stock's grades start on the first session, then list only changes of
# letter, each effective at the next session's New York open; and they agree
# with the letters on the rows the trades are read from.
def test_replay_records_every_grade_change_once(history):  # noqa: F811
    report = _report()
    manifest, stocks = research.replay(report, history, "leader_ewma_minB_floor50")
    assert manifest["arm"] == "leader_ewma_minB_floor50"
    assert stocks
    for stock in stocks.values():
        grades = stock["grades"]
        assert grades[0]["date"] == manifest["start"]
        letters = [g["grade"] for g in grades]
        assert all(a != b for a, b in zip(letters, letters[1:]))
        for g in grades:
            assert g["said"] is False
            if "at" in g:
                assert g["at"].endswith(("T09:30:00-04:00", "T09:30:00-05:00"))
                assert g["at"][:10] > g["date"]
        by_date = {g["date"]: g["grade"] for g in grades}
        current = None
        for row in sorted(stock["rows"], key=lambda r: r["date"]):
            for day in sorted(by_date):
                if day <= row["date"]:
                    current = by_date[day]
            assert row["grade"] == current
