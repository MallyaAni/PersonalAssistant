"""The replay's in-sample boundary is stamped where the history is served."""

from backend.market import strategy_replay_sample as sample


# Rows at or before the frozen fit date are in-sample, later rows are not,
# and an undated row is left alone rather than guessed.
def test_rows_are_stamped_against_the_fit_date():
    boundary = sample.MODEL_FIT_THROUGH
    assert sample.sample({"at": f"{boundary}T15:45:00-04:00"}) == sample.IN_SAMPLE
    assert sample.sample({"date": "2026-09-01"}) == sample.OUT_OF_SAMPLE
    assert sample.sample({"date": "2018-02-01"}) == sample.IN_SAMPLE
    assert sample.sample({}) is None
    assert sample.sample({"date": "not a date"}) is None


# A served stock view gains a stamp on every dated row, the fit date on its
# provenance and the split of its decisions; the summary sums its stocks.
def test_a_served_view_carries_stamps_counts_and_the_fit_date():
    stock = {
        "ticker": "AAA",
        "provenance": {"basis": "x"},
        "decisions": [{"date": "2018-02-01"}, {"date": "2026-10-01"}, {"id": 1}],
        "trades": [{"at": "2026-09-30T09:30:00-04:00"}],
        "targets": [],
    }
    served = sample.stamp(stock)
    assert [row.get("sample") for row in served["decisions"]] == [
        sample.IN_SAMPLE,
        sample.OUT_OF_SAMPLE,
        None,
    ]
    assert served["trades"][0]["sample"] == sample.OUT_OF_SAMPLE
    assert served["provenance"]["model_fit_through"] == sample.MODEL_FIT_THROUGH
    assert (served["in_sample_decisions"], served["out_of_sample_decisions"]) == (1, 1)
    summary = sample.stamp(
        {
            "stocks": {
                "AAA": {"decisions": [{"date": "2018-02-01"}]},
                "BBB": {"decisions": [{"date": "2026-10-01"}] * 2},
            }
        }
    )
    assert (summary["in_sample_decisions"], summary["out_of_sample_decisions"]) == (
        1,
        2,
    )
    assert summary["model_fit_through"] == sample.MODEL_FIT_THROUGH
