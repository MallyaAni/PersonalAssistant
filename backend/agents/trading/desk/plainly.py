"""Why the desk grades a name what it does, in English, for every name.

Two gaps this closes, both found by reading the Desk view rather than the
code.

Only the held names carried an explanation. The daily run briefs the book
- eight or nine names - because each brief is a model call. The other
eighty in the grades table showed a letter and nothing else, so the view
answered "what" for ninety names and "why" for eight.

And the explanations that did exist read like a register dump: "citing
revenue_yoy +0.623, revenue_qoq +0.239, gross_margin +0.277,
revenue_acceleration +0.208". Those are the desk's own column names,
handed to the model with an instruction to copy every figure exactly. The
instruction is right - a brief that invents a number is worse than no
brief - but the column names are not English and a list of nine of them
is not a sentence.

Nothing here calls a model. Every name gets a reason built from the same
stances and evidence the grade was built from, so it is free, instant,
identical every time it is asked, and incapable of inventing anything.
The model's brief stays what it is: a longer, better-written piece for
the names actually held.

The rule for numbers is the same one the brief prompt uses. A figure is
never rescaled or converted, only named in words and quoted as it stands,
because a reader who checks it against the evidence must find the same
number.
"""

from __future__ import annotations

import numpy as np

# What each of the desk's measurements is called in English. A name absent
# here is written as-is rather than guessed at, so a new measurement shows
# up looking wrong instead of being described wrongly.
LABELS: dict[str, str] = {
    # fundamental
    "revenue_yoy": "revenue growth over the year",
    "revenue_qoq": "revenue growth over the quarter",
    "gross_margin": "gross margin",
    "revenue_acceleration": "revenue acceleration",
    "eps_change_yoy": "earnings growth over the year",
    "net_margin": "net margin",
    "capex_to_revenue": "capital spending against revenue",
    "share_issuance": "new shares issued",
    "asset_growth": "asset growth",
    "book_to_market": "book value against market value",
    "sessions_since_earnings": "sessions since it last reported",
    # technical
    "ema21_distance": "distance from its 21-day average",
    "ema50_distance": "distance from its 50-day average",
    "ema200_distance": "distance from its 200-day average",
    "sma200_distance": "distance from its 200-day simple average",
    "ema21_slope": "the slope of its 21-day average",
    "ema50_slope": "the slope of its 50-day average",
    "stack_order": "whether its averages are stacked in trend order",
    "spread_21_50": "the gap between its 21- and 50-day averages",
    "spread_21_50_slope": "whether that gap is widening",
    "converging_21_50": "whether those averages are converging",
    "weekly_stack": "whether its weekly averages are stacked in order",
    "high_52w_distance": "distance below its 52-week high",
    "low_52w_distance": "distance above its 52-week low",
    "support_distance": "distance to support",
    "resistance_distance": "distance to resistance",
    "reward_risk": "reward against risk to the next levels",
    "range_position_60": "where it sits in its 60-day range",
    "weekly_trend": "its weekly trend",
    "daily_trend": "its daily trend",
    "confluence": "how many timeframes agree",
    "residual_momentum_120": "momentum with the market's part removed",
    # sentiment, from the release reader
    "tone_guidance": "what it said about guidance",
    "tone_demand": "what it said about demand",
    "tone_guidance_change": "how guidance changed from the last release",
    "tone_pricing": "what it said about pricing",
    "tone_capex": "what it said about capital spending",
    "tone_supply_constrained": "whether it called itself supply constrained",
    "tone_demand_change": "how demand talk changed from the last release",
    # value
    "price_sales": "price against sales",
    "price_earnings": "price against earnings",
    "price_book": "price against book value",
    "price_sales_growth": "price against sales, adjusted for growth",
    "cheap_vs_side": "how cheap it is against its side of the book",
    "market_cap": "its size",
}

# What the desk does at each grade, in the operator's own words.
ACTION: dict[str, str] = {
    "A+": "own it",
    "A": "own it",
    "B": "wait",
    "C": "avoid it",
}

# How many measurements to name per analyst. Two is a sentence; nine is
# the dump this file exists to replace.
CITE = 2
# A measurement this close to zero is not worth naming as a reason.
QUIET = 1e-9
# Facts that place a name rather than argue about it. Market value is the
# clearest: every name here is worth tens of billions, so the number is
# enormous for all of them and says nothing about any one of them.
# `sessions_since_earnings` joins it: how long ago a company reported is
# a fact about the calendar, and "on sessions since it last reported at
# +59.00" is not a reason to avoid a stock.
CONTEXT = frozenset({"market_cap", "sessions_since_earnings"})
# A reading has to sit this many robust deviations from the book's middle
# before it is worth calling a reason.
NOTABLE = 0.5


# How unusual each measurement is across the book, so a reason can name the
# readings that set a name apart rather than the ones that happen to be
# written in the largest units.
#
# Picking the largest absolute value does not work: these measurements
# share no scale. Market value runs to eleven digits and a margin runs to
# one, so "largest" always chose market value and the reason read "on its
# size at +457286396484.38", which is true of every name in the book and
# explains nothing. The middle and spread come from the book itself, so a
# reading is judged against its peers exactly as a stance is.
def spreads(report) -> dict[tuple[str, str], tuple[float, float]]:
    """Return (middle, spread) per analyst measurement across the book."""
    t = len(report.panel.dates) - 1
    in_book = np.array([x in report.sides for x in report.panel.tickers])
    out: dict[tuple[str, str], tuple[float, float]] = {}
    for analyst, opinion in report.opinions.items():
        for measure, values in getattr(opinion, "evidence", {}).items():
            row = np.asarray(values)[t]
            known = row[in_book & np.isfinite(row)]
            if len(known) < 5:
                continue
            middle = float(np.median(known))
            # Median absolute deviation: a spread that a handful of
            # extreme names cannot widen out of usefulness.
            spread = float(np.median(np.abs(known - middle)))
            out[(analyst, measure)] = (middle, spread if spread > 0 else float("nan"))
    return out


# One analyst's view of one name, as a clause.
def _clause(
    analyst: str,
    stance: int,
    rank: float | None,
    cited: dict,
    scale: dict | None = None,
) -> str:
    mood = {1: "likes it", 0: "is neutral on it", -1: "is against it"}[stance]
    where = ""
    if rank is not None and rank == rank:
        if rank >= 0.8:
            where = ", ranking it near the top of the book"
        elif rank <= 0.2:
            where = ", ranking it near the bottom"
    if not cited:
        return f"the {analyst} analyst has no data for it"
    strongest = _notable(analyst, cited, scale)
    if not strongest:
        return f"the {analyst} analyst {mood}{where}"
    parts = [f"{LABELS.get(k, k)} at {v:+.2f}" for k, v in strongest]
    joined = parts[0] if len(parts) == 1 else f"{parts[0]} and {parts[1]}"
    return f"the {analyst} analyst {mood}{where}, on {joined}"


# The measurements that set this name apart from the book, largest first.
def _notable(analyst: str, cited: dict, scale: dict | None) -> list[tuple[str, float]]:
    ranked: list[tuple[float, str, float]] = []
    for measure, value in cited.items():
        if measure in CONTEXT or not np.isfinite(value):
            continue
        middle, spread = (scale or {}).get((analyst, measure), (0.0, float("nan")))
        if scale is None or not np.isfinite(spread):
            # No book to compare against: fall back to the reading itself,
            # which is right for the tone fields, where every value is
            # -1, 0 or 1 and the scale is already shared.
            score = abs(float(value))
        else:
            score = abs(float(value) - middle) / spread
            if score < NOTABLE:
                continue
        if score > QUIET:
            ranked.append((score, measure, float(value)))
    ranked.sort(key=lambda r: -r[0])
    return [(measure, value) for _score, measure, value in ranked[:CITE]]


# The whole reason for one name: the grade, what it means to do, and the
# analysts that decided it, strongest opinion first.
def reason(view: dict, scale: dict | None = None) -> str:
    """Return a plain-English reason for one name's grade."""
    grade = str(view.get("grade", "?"))
    action = ACTION.get(grade, "no action")
    stances = view.get("stances") or {}
    ranks = view.get("ranks") or {}
    evidence = view.get("evidence") or {}
    clauses = []
    # Analysts with an opinion come before the ones without, because a
    # neutral analyst did not decide anything.
    for analyst in sorted(stances, key=lambda a: (abs(stances[a]) == 0, a)):
        stance = stances.get(analyst)
        cited = evidence.get(analyst, {})
        # An analyst that measured nothing is not a reason. Saying "the
        # rotation analyst has no data for it" in the middle of a sentence
        # about why a name is graded C tells the reader nothing they can use.
        if stance is None or not cited:
            continue
        clauses.append(_clause(analyst, int(stance), ranks.get(analyst), cited, scale))
    if not clauses:
        return f"Grade {grade}: {action}. No analyst had a view on it today."
    body = "; ".join(clauses[:3])
    return f"Grade {grade}: {action}, because {body}."


# The one line a table can show without opening anything: the grade, the
# action, and the single analyst that mattered most.
def headline(view: dict) -> str:
    """Return a one-clause summary of why a name is graded as it is."""
    grade = str(view.get("grade", "?"))
    action = ACTION.get(grade, "no action")
    stances = view.get("stances") or {}
    decisive = [a for a, s in stances.items() if s and abs(int(s)) == 1]
    if not decisive:
        return f"{action.capitalize()}: no analyst has a strong view."
    bulls = [a for a in decisive if int(stances[a]) > 0]
    bears = [a for a in decisive if int(stances[a]) < 0]
    if bulls and not bears:
        return f"{action.capitalize()}: {_names(bulls)} in favour, none against."
    if bears and not bulls:
        return f"{action.capitalize()}: {_names(bears)} against, none in favour."
    return f"{action.capitalize()}: {_names(bulls)} for, {_names(bears)} against."


# "the fundamental analyst", "fundamental and technical", "three analysts".
def _names(analysts: list[str]) -> str:
    ordered = sorted(analysts)
    if len(ordered) == 1:
        return f"the {ordered[0]} analyst"
    if len(ordered) == 2:
        return f"{ordered[0]} and {ordered[1]}"
    return f"{len(ordered)} analysts"
