"""The trading desk: analysts, a grade, a risk manager, one book.

Each analyst reads one kind of evidence about every name in the book and
gives an opinion: a score across names and a stance (bullish, neutral,
bearish) per name. The desk collects the opinions, the regime analyst says
how much to trust them and how much market to carry, the grade turns the
agreement between analysts into A+, A, B or C, and the risk manager turns
grades into sizes. Every rule here is one that was measured in the harness
first; the calibration in `desk.py` re-measures the grades so a grade that
stops paying is visible.
"""
