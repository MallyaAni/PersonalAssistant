"""The plain-English reason behind every grade.

The Desk view showed a letter for ninety names and an explanation for the
eight the model had briefed, and those explanations read as a list of
column names and figures. This builds a reason for every name, in code,
from the same evidence the grade came from. What has to hold: it names
measurements in English rather than in identifiers, it picks the readings
that set a name apart rather than the ones written in the largest units,
and it never states a figure the evidence does not contain.
"""

from types import SimpleNamespace

import numpy as np
import pytest

from backend.agents.trading.desk import plainly
from backend.agents.trading.desk.fundamental import CITED as FUNDAMENTAL_CITED
from backend.agents.trading.desk.sentiment import CITED as SENTIMENT_CITED
from backend.agents.trading.desk.technical import CITED as TECHNICAL_CITED
from backend.agents.trading.desk.technical import LOCATION_CITED
from backend.agents.trading.desk.value import CITED as VALUE_CITED


# Every measurement an analyst can cite has an English name. Without this
# a new feature reaches the operator as a bare identifier, which is the
# defect this module was written to remove.
@pytest.mark.parametrize(
    "measure",
    sorted(
        set(FUNDAMENTAL_CITED)
        | set(TECHNICAL_CITED)
        | set(LOCATION_CITED)
        | set(SENTIMENT_CITED)
        | set(VALUE_CITED)
    ),
)
def test_every_cited_measurement_has_an_english_name(measure: str):
    assert measure in plainly.LABELS, (
        f"{measure} would be shown to the operator as a raw column name; "
        f"add it to plainly.LABELS"
    )
    label = plainly.LABELS[measure]
    assert "_" not in label, f"{measure}'s label is still an identifier"
    assert label == label.lower() or label[0].isupper() is False


# The reason names the readings that set a name apart from the book, not
# the ones that happen to be written in the largest units. Market value is
# eleven digits for every name here, so it must never be the reason.
def test_the_biggest_number_is_not_automatically_the_reason():
    cited = {
        "market_cap": 4.57e11,  # enormous, and true of every name
        "revenue_yoy": 0.62,  # far above the book's middle
        "net_margin": 0.10,  # ordinary
    }
    scale = {
        ("fundamental", "market_cap"): (4.0e11, 5.0e10),
        ("fundamental", "revenue_yoy"): (0.10, 0.08),
        ("fundamental", "net_margin"): (0.10, 0.05),
    }
    picked = plainly._notable("fundamental", cited, scale)
    names = [m for m, _v in picked]
    assert "market_cap" not in names, "size is context, never a reason"
    assert names[0] == "revenue_yoy"
    # An ordinary reading sitting on the book's middle is not a reason.
    assert "net_margin" not in names


# The figure quoted is the figure measured: never rescaled, converted or
# rounded into something a reader cannot find in the evidence.
def test_a_quoted_figure_is_the_measured_one():
    view = {
        "grade": "C",
        "stances": {"fundamental": -1},
        "ranks": {"fundamental": 0.05},
        "evidence": {"fundamental": {"revenue_yoy": -0.311}},
    }
    text = plainly.reason(view)
    assert "-0.31" in text
    assert "revenue growth over the year" in text
    assert "revenue_yoy" not in text
    # Not turned into a percentage, which would read as a different figure.
    assert "-31" not in text


# An analyst that measured nothing is not a reason, and saying so in the
# middle of the sentence tells the reader nothing they can act on.
def test_an_analyst_with_no_evidence_is_left_out():
    view = {
        "grade": "B",
        "stances": {"fundamental": 1, "rotation": 0},
        "ranks": {"fundamental": 0.9},
        "evidence": {"fundamental": {"revenue_yoy": 0.4}, "rotation": {}},
    }
    text = plainly.reason(view)
    assert "rotation" not in text
    assert "fundamental" in text
    # With nothing at all, it says so once rather than inventing a reason.
    empty = plainly.reason({"grade": "C", "stances": {}, "evidence": {}})
    assert "No analyst had a view" in empty


# The grade decides the action, and the reason never argues with it.
@pytest.mark.parametrize(
    ("grade", "action"),
    [("A+", "own it"), ("A", "own it"), ("B", "wait"), ("C", "avoid it")],
)
def test_the_action_follows_the_grade(grade: str, action: str):
    view = {
        "grade": grade,
        "stances": {"technical": 1},
        "ranks": {"technical": 0.9},
        "evidence": {"technical": {"ema21_slope": 0.05}},
    }
    assert plainly.reason(view).startswith(f"Grade {grade}: {action}")
    assert plainly.headline(view).lower().startswith(action.split()[0])


# The headline says who is for and who is against, so a table row carries
# the shape of the argument without opening anything.
def test_the_headline_names_both_sides():
    both = {
        "grade": "C",
        "stances": {"value": 1, "technical": -1, "fundamental": -1},
    }
    line = plainly.headline(both)
    assert "for" in line
    assert "against" in line
    one_way = plainly.headline({"grade": "A", "stances": {"value": 1, "technical": 0}})
    assert "none against" in one_way
    quiet = plainly.headline({"grade": "B", "stances": {"value": 0}})
    assert "no analyst has a strong view" in quiet


# The spread each measurement is judged against comes from the book only,
# and a measurement the book barely varies on gets no spread rather than a
# zero that would divide badly.
def test_spreads_are_taken_across_the_book_only():
    rows, names = 3, 6
    values = np.zeros((rows, names))
    values[-1] = [1.0, 2.0, 3.0, 4.0, 5.0, 999.0]  # the last is not in the book
    flat = np.zeros((rows, names))
    opinion = SimpleNamespace(evidence={"revenue_yoy": values, "net_margin": flat})
    report = SimpleNamespace(
        panel=SimpleNamespace(
            dates=np.arange(rows), tickers=tuple(f"N{i}" for i in range(names))
        ),
        sides={f"N{i}": "ai" for i in range(names - 1)},
        opinions={"fundamental": opinion},
    )
    scale = plainly.spreads(report)
    middle, spread = scale[("fundamental", "revenue_yoy")]
    assert middle == pytest.approx(3.0)  # the outsider did not move it
    assert spread == pytest.approx(1.0)
    # A measurement identical across the book has no usable spread.
    assert np.isnan(scale[("fundamental", "net_margin")][1])
    # And a reading is then judged on its own size rather than by dividing.
    picked = plainly._notable("fundamental", {"net_margin": 0.4}, scale)
    assert picked == [("net_margin", 0.4)]
