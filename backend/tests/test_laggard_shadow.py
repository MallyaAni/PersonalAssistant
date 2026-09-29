"""The laggard shadow's ledger, scoring and registered verdict (numpy only).

What has to hold (docs/research/laggard-shadow-plan-2026-09-29.md):

- An entry's book is the date's rows graded A or A+ with a finite
  forecast, in row order; the laggard is the lowest forecast (ties: the
  first row), the top name the highest; `unclean` keeps only book names.
- The first entry for a date is final: `append` refuses a date already in
  the ledger or twice in one call, and writes one JSON line per entry.
- A score needs a finite r for every book name and two names or more. The
  spread is 1e4 × (r of the laggard − the book's mean r), the gain
  −spread / (n − 1) / 20, and the IC inside the book needs three names.
- The primary series is the scored clean dates with a book of three or
  more, in date order.
  - CONFIRMED at the first look (250, then 500 dates) whose t is at most
    −2.24, judged on that look's first dates only.
  - NOT CONFIRMED at 500 otherwise.
  - PENDING before that.
- Forward dates are the export's dates after the training export's last.
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from backend.market import candidate_stats
from backend.market import laggard_shadow as shadow
from backend.market import stage3_io as io


# A T-S1 export over the given days, one row per (day, ticker) with the
# grades and r given per day as lists in ticker order.
def _export(days, tickers, grades, r):
    dates, names, g, rr = [], [], [], []
    for d, day in enumerate(days):
        for t, ticker in enumerate(tickers):
            dates.append(np.datetime64(day, "D"))
            names.append(ticker)
            g.append(grades[d][t])
            rr.append(r[d][t])
    count = len(dates)
    return io.Stage3Data(
        kind=io.S1,
        dates=np.asarray(dates, dtype="datetime64[D]"),
        tickers=np.asarray(names),
        slot=np.zeros(count, dtype=np.int8),
        x=np.zeros((count, 1), dtype=np.float32),
        feature_names=("d_zero",),
        y=np.zeros(count, dtype=np.float32),
        extra={"r": np.asarray(rr, dtype=np.float32), "grade": np.asarray(g, dtype=np.int8)},
    )


TICKERS = ["AAA", "BBB", "CCC", "DDD", "EEE"]


# Two days: the second day's r is not known yet (NaN).
def _two_days():
    grades = [[3, 2, 2, 1, 2], [3, 3, 2, 2, 0]]
    r = [[0.01, -0.02, 0.03, 0.00, 0.02], [np.nan] * 5]
    return _export(["2026-09-29", "2026-09-30"], TICKERS, grades, r)


# The book, laggard, top name and unclean names of an entry.
def test_entry_reads_the_book_in_row_order():
    data = _two_days()
    yhat = np.array([0.5, -0.4, 0.2, -9.0, np.nan, 0.1, 0.1, -0.3, 0.2, 5.0])
    e = shadow.entry(
        data, yhat, np.datetime64("2026-09-29"), model_id="m", export_sha256="x",
        made_at="t", own_invalid=["CCC", "DDD"],
    )
    # DDD is graded B (excluded), EEE has no forecast (excluded).
    assert [b["ticker"] for b in e["book"]] == ["AAA", "BBB", "CCC"]
    assert e["n"] == 3 and e["laggard"] == "BBB" and e["top"] == "AAA"
    assert e["unclean"] == ["CCC"]
    assert e["date"] == "2026-09-29" and e["plan"] == shadow.PLAN
    # Day two: EEE is graded C; the book is the four others.
    second = shadow.entry(data, yhat, np.datetime64("2026-09-30"), model_id="m", export_sha256="x", made_at="t")
    assert [b["ticker"] for b in second["book"]] == ["AAA", "BBB", "CCC", "DDD"]
    assert second["laggard"] == "CCC" and second["top"] == "DDD"
    # Ties go to the first row.
    flat = shadow.entry(data, np.zeros(10), np.datetime64("2026-09-30"), model_id="m", export_sha256="x", made_at="t")
    assert flat["laggard"] == "AAA" and flat["top"] == "AAA"
    with pytest.raises(ValueError, match="T-S1"):
        import dataclasses

        shadow.entry(dataclasses.replace(data, kind=io.TI), yhat, np.datetime64("2026-09-29"),
                     model_id="m", export_sha256="x", made_at="t")


# The ledger refuses a second forecast for a date, in the file or the call.
def test_append_refuses_a_second_forecast_for_a_date(tmp_path):
    path = tmp_path / "shadow" / "ledger.jsonl"
    one = {"date": "2026-09-29", "book": [], "x": np.float64(1.5)}
    two = {"date": "2026-09-30", "book": []}
    assert shadow.append(path, [one]) == 1
    assert shadow.append(path, [two]) == 1
    assert [e["date"] for e in shadow.read_ledger(path)] == ["2026-09-29", "2026-09-30"]
    assert json.loads(path.read_text().splitlines()[0])["x"] == 1.5
    with pytest.raises(ValueError, match="already in the ledger"):
        shadow.append(path, [one])
    with pytest.raises(ValueError, match="already in the ledger"):
        shadow.append(path, [{"date": "2026-10-01"}, {"date": "2026-10-01"}])
    assert len(shadow.read_ledger(path)) == 2
    assert shadow.read_ledger(tmp_path / "absent.jsonl") == []
    assert shadow.append(path, []) == 0


# Scores by hand; immature and one-name entries are not scored.
def test_score_by_hand():
    data = _two_days()
    returns = shadow.r_lookup(data)
    assert ("2026-09-30", "AAA") not in returns
    e = {
        "date": "2026-09-29", "model_id": "m", "unclean": [],
        "book": [{"ticker": "AAA", "forecast": 0.5}, {"ticker": "BBB", "forecast": -0.4},
                 {"ticker": "CCC", "forecast": 0.2}],
        "laggard": "BBB", "top": "AAA",
    }
    s = shadow.score(e, returns)
    r = np.array([0.01, -0.02, 0.03], dtype=np.float32).astype(float)
    centre = r.mean()
    assert s["spread"] == pytest.approx(1e4 * (r[1] - centre))
    assert s["gain"] == pytest.approx(-s["spread"] / 2 / io.S1_HORIZON)
    assert s["top_spread"] == pytest.approx(1e4 * (r[0] - centre))
    assert s["ic_book"] == pytest.approx(io.spearman(np.array([0.5, -0.4, 0.2]), r))
    assert s["clean"] and s["n"] == 3
    immature = dict(e, date="2026-09-30")
    assert shadow.score(immature, returns) is None
    single = dict(e, book=e["book"][:1], laggard="AAA", top="AAA")
    assert shadow.score(single, returns) is None
    pair = dict(e, book=e["book"][:2])
    assert math.isnan(shadow.score(pair, returns)["ic_book"])
    assert not shadow.score(dict(e, unclean=["AAA"]), returns)["clean"]


# The verdict at the registered looks, each judged on its own first dates.
def test_verdict_reads_the_registered_looks():
    rng = np.random.default_rng(0)
    assert shadow.LOOKS == (250, 500) and shadow.THRESHOLD == -2.24 and shadow.PRIMARY_MIN == 3
    strong = list(-300 + 50 * rng.normal(size=260))
    v = shadow.verdict(strong)
    assert v["label"] == "CONFIRMED" and v["at"] == 250
    assert v["looks"][0]["n"] == 250
    assert v["looks"][0]["t"] == pytest.approx(candidate_stats.hac_t(np.array(strong[:250]), io.HAC_LAG))
    noise = list(1000 * rng.normal(size=300))
    pending = shadow.verdict(noise)
    assert pending["label"] == "PENDING" and pending["next_look"] == 500 and len(pending["looks"]) == 1
    assert shadow.verdict(noise[:100])["next_look"] == 250
    late = noise[:250] + list(-400 + 20 * rng.normal(size=250))
    v_late = shadow.verdict(late)
    assert v_late["label"] == "CONFIRMED" and v_late["at"] == 500
    closed = shadow.verdict(list(np.tile([100.0, -100.0], 260)))
    assert closed["label"] == "NOT CONFIRMED" and closed["at"] == 500 and len(closed["looks"]) == 2
    assert shadow.verdict([])["label"] == "PENDING"


# The summary: the primary keeps clean dates with three names or more in
# date order; secondary readings per minimum and per model id.
def test_summarize_filters_the_primary_series():
    scores = [
        {"date": "2026-10-02", "model_id": "a", "n": 3, "clean": True, "spread": -10.0, "gain": 0.25, "top_spread": 5.0, "ic_book": 0.5},
        {"date": "2026-10-01", "model_id": "a", "n": 5, "clean": True, "spread": -30.0, "gain": 0.4, "top_spread": 1.0, "ic_book": 0.1},
        {"date": "2026-10-05", "model_id": "b", "n": 2, "clean": True, "spread": 99.0, "gain": -5.0, "top_spread": 0.0, "ic_book": math.nan},
        {"date": "2026-10-06", "model_id": "b", "n": 6, "clean": False, "spread": 99.0, "gain": -1.0, "top_spread": 0.0, "ic_book": 0.0},
    ]
    out = shadow.summarize(scores, entries=7)
    assert out["entries"] == 7 and out["scored"] == 4 and out["unclean_scored"] == 1
    assert out["primary"]["n"] == 2 and out["primary"]["mean"] == pytest.approx(-20.0)
    assert out["verdict"]["label"] == "PENDING"
    assert out["secondary"]["5"]["spread"]["n"] == 1
    assert out["secondary"]["3"]["gain"]["mean"] == pytest.approx(0.325)
    assert out["by_model"]["a"]["n"] == 2 and out["by_model"]["b"]["n"] == 0


# Forward dates are the unique dates after the training export's last.
def test_forward_dates_and_date_rows():
    dates = np.array(["2026-09-25", "2026-09-28", "2026-09-28", "2026-09-29", "2026-09-30"], dtype="datetime64[D]")
    assert [str(d) for d in shadow.forward_dates(dates)] == ["2026-09-29", "2026-09-30"]
    assert [str(d) for d in shadow.forward_dates(dates, "2026-09-29")] == ["2026-09-30"]
    assert shadow.date_rows(dates, np.datetime64("2026-09-28")).tolist() == [1, 2]
    assert shadow.date_rows(dates, np.datetime64("2026-10-01")).tolist() == []
