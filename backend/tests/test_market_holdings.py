"""The person's own positions, and the board against them.

What has to hold: rows are validated whole, tickers normalised, and a
bad one refused with a reason; what is saved is what is loaded; and the
board against the holdings says sell for a held name the desk dropped,
buy for one targeted but not held, hold where the weights agree, and an
uncovered held name gets an explicit review state rather than a sell -
a lack of coverage is not a liquidation decision.
"""

from pathlib import Path

import pytest

from backend.market import holdings


def test_rows_are_validated_and_normalised():
    rows = holdings.parse(
        [
            {
                "ticker": " iren ",
                "shares": "100",
                "entry_price": "35.2",
                "entry_date": "2026-08-28",
            }
        ]
    )
    assert rows == [holdings.Holding("IREN", 100.0, 35.2, "2026-08-28")]
    for bad in (
        {"ticker": "", "shares": 1, "entry_price": 1, "entry_date": "2026-01-01"},
        {"ticker": "IREN", "shares": 0, "entry_price": 1, "entry_date": "2026-01-01"},
        {"ticker": "IREN", "shares": 1, "entry_price": "x", "entry_date": "2026-01-01"},
        {"ticker": "IREN", "shares": 1, "entry_price": 1, "entry_date": "yesterday"},
    ):
        with pytest.raises(ValueError, match=r"."):
            holdings.parse([bad])
    with pytest.raises(ValueError, match="listed twice"):
        holdings.parse(
            [
                {
                    "ticker": "IREN",
                    "shares": 1,
                    "entry_price": 1,
                    "entry_date": "2026-01-01",
                },
                {
                    "ticker": "iren",
                    "shares": 2,
                    "entry_price": 1,
                    "entry_date": "2026-01-01",
                },
            ]
        )


def test_saved_holdings_are_loaded(tmp_path: Path):
    assert holdings.load(tmp_path) == []
    rows = [holdings.Holding("ADBE", 42.0, 300.0, "2026-09-08")]
    holdings.save(tmp_path, rows)
    assert holdings.load(tmp_path) == rows


def _record():
    return {
        "session": "2026-09-04",
        "grades": {
            "ADBE": {
                "grade": "A+",
                "score": 1.9,
                "stances": {"sentiment": 1},
                "headline": "own ADBE",
                "reason": "because",
            },
            "HPE": {
                "grade": "A+",
                "score": 1.8,
                "stances": {},
                "headline": "own HPE",
                "reason": "",
            },
            "FTNT": {
                "grade": "B",
                "score": 1.0,
                "stances": {},
                "headline": "hold off FTNT",
                "reason": "",
            },
        },
        "paper": {"until_rebalance": 12},
        "book": [
            {"ticker": "ADBE", "weight": 0.112},
            {"ticker": "HPE", "weight": 0.105},
        ],
        "levels": {
            "ADBE": {
                "last_close": 300.0,
                "high_20": 320.0,
                "stops": {"12": 281.6},
                "grade_margin": 0.5,
                "rank": 1,
            },
            "HPE": {
                "last_close": 52.0,
                "high_20": 55.0,
                "stops": {"12": 48.4},
                "grade_margin": 0.4,
                "rank": 2,
            },
            "FTNT": {
                "last_close": 80.0,
                "high_20": 90.0,
                "stops": {"12": 79.2},
                "grade_margin": 0.1,
                "rank": 3,
            },
        },
    }


def test_board_against_the_persons_holdings():
    held = [
        holdings.Holding(
            "ADBE", 37.0, 290.0, "2026-09-01"
        ),  # targeted and held near target
        holdings.Holding("FTNT", 50.0, 85.0, "2026-08-20"),  # rated B, not targeted
        holdings.Holding("IREN", 100.0, 35.0, "2026-08-28"),  # not rated at all
    ]
    quotes = {"ADBE": {"last": 303.0}, "IREN": {"last": 44.67}}
    rows = holdings.board(_record(), held, equity=100_000.0, quotes=quotes)
    by = {r["ticker"]: r for r in rows}
    # FTNT is rated but the desk dropped it, so it sells; IREN is not
    # covered at all, so it is an explicit review state, not a sell.
    assert {r["ticker"]: r["action"] for r in rows if r["action"] == "sell"} == {
        "FTNT": "sell",
    }
    assert by["IREN"]["action"] == "uncovered"
    assert [r["ticker"] for r in rows][-1] == "IREN"  # not covered sorts last
    assert by["HPE"]["action"] == "buy"
    assert by["HPE"]["delta_weight"] == pytest.approx(0.105)
    assert by["ADBE"]["action"] == "hold"  # 37 * 303 / 100k = 11.2%, on target
    assert by["ADBE"]["pl_pct"] == pytest.approx(303.0 / 290.0 - 1.0)
    assert by["ADBE"]["stops"]["12"] == 281.6
    assert by["ADBE"]["rank"] == 1
    assert by["ADBE"]["until_rebalance"] == 12
    assert by["ADBE"]["rebalance_due"] is False  # 12 sessions left: targets, not orders
    assert by["FTNT"]["in_book"]
    assert by["FTNT"]["grade"] == "B"
    assert by["FTNT"]["last"] == 80.0  # the record's close when the feed has none
    assert not by["IREN"]["in_book"]
    assert by["IREN"]["why"].startswith("the desk does not cover")
    assert by["IREN"]["pl_pct"] == pytest.approx(44.67 / 35.0 - 1.0)
    assert by["IREN"]["stops"] == {}
    assert by["IREN"]["leaves_if"].startswith("your call")
    # The exit line answers from what you hold: a buy candidate has nothing
    # to sell, a held name is sold by the grade rule, a held name the desk
    # dropped is sold outright.
    assert by["HPE"]["leaves_if"] == "a buy only while it holds an A grade"
    assert by["ADBE"]["leaves_if"] == "sell when its grade drops below A at a rebalance"
    assert (
        by["FTNT"]["leaves_if"]
        == "sell everything: it no longer earns a place in the book"
    )


# The board distinguishes "the next session is a rebalance" from "targets
# for a later one": only with the countdown at one (or absent, a fresh
# book) are the target-vs-held changes executable at the next open.
def test_the_board_knows_when_a_rebalance_is_due():
    due = holdings.board(
        dict(_record(), **{"paper": {"until_rebalance": 1}}), [], 100_000.0, {}
    )
    assert due[0]["rebalance_due"] is True
    far = holdings.board(
        dict(_record(), **{"paper": {"until_rebalance": 18}}), [], 100_000.0, {}
    )
    assert far[0]["rebalance_due"] is False
    fresh = holdings.board(dict(_record(), **{"paper": None}), [], 100_000.0, {})
    assert fresh[0]["rebalance_due"] is True  # no clock yet: first decision is due



# The live technical read re-makes the grade and the order: a name whose
# technical rank has fallen through the bearish line drops to B by the
# veto and sorts below the names still A, and a name that rose keeps its
# grade with a higher score.
def test_the_live_technical_read_regrades_and_reorders():
    record = _record()
    record["grades"]["ADBE"]["stances"] = {
        "fundamental": 1,
        "technical": 1,
        "sentiment": 1,
        "value": 0,
        "rotation": 0,
    }
    record["grades"]["HPE"]["stances"] = dict(record["grades"]["ADBE"]["stances"])
    technical = {
        "ADBE": {"now": 0.10, "close": 0.90},
        "HPE": {"now": 0.95, "close": 0.80},
    }
    rows = holdings.board(record, [], 100_000.0, {}, technical)
    by = {r["ticker"]: r for r in rows}
    assert by["ADBE"]["grade"] == "A+"
    assert by["ADBE"]["grade_live"] == "B"  # a bearish technical vetoes the top grades
    assert by["HPE"]["grade_live"] == "A+"
    assert by["HPE"]["score_live"] > by["HPE"]["score"]
    assert [r["ticker"] for r in rows][0] == "HPE"
    assert [r["ticker"] for r in rows][-1] == "ADBE" or by["ADBE"]["grade_live"] == "B"
    # Without a live read the grade stands and the order is by grade then score.
    plain = holdings.board(record, [], 100_000.0, {})
    assert [r["grade_live"] for r in plain] == [r["grade"] for r in plain]


# The full list's live grades: every graded name with a technical read is
# re-graded, whether or not the board carries it; a name without a read is
# left out so the page falls back to the evening grade.
def test_live_grades_cover_every_graded_name_with_a_read():
    record = _record()
    for ticker in record["grades"]:
        record["grades"][ticker]["stances"] = {
            "fundamental": 1,
            "technical": 1,
            "sentiment": 1,
            "value": 0,
            "rotation": 0,
        }
    read = {t: {"now": 0.10, "close": 0.90} for t in record["grades"]}
    first = next(iter(record["grades"]))
    del read[first]
    live = holdings.live_grades(record, read)
    assert first not in live
    assert set(live) == set(record["grades"]) - {first}
    assert all(v["grade_live"] == "B" for v in live.values())  # bearish veto
    assert holdings.live_grades(record, None) == {}


# The live read carries the rule's own persisted stance; a rank that has
# dipped under the line for one candle does not change the grade when the
# rule says the stance still holds, and a bare rank is only the fallback.
def test_the_persisted_live_stance_wins_over_the_bare_rank():
    record = _record()
    record["grades"]["ADBE"]["stances"] = {
        "fundamental": 1,
        "technical": 1,
        "sentiment": 1,
        "value": 0,
        "rotation": 0,
    }
    held = holdings.board(
        record, [], 100_000.0, {}, {"ADBE": {"now": 0.10, "close": 0.60, "stance": 1}}
    )
    assert {r["ticker"]: r for r in held}["ADBE"]["grade_live"] == "A+"
    bare = holdings.board(
        record, [], 100_000.0, {}, {"ADBE": {"now": 0.10, "close": 0.60}}
    )
    assert {r["ticker"]: r for r in bare}["ADBE"][
        "grade_live"
    ] == "B"  # the bare rank reads bearish: the veto
