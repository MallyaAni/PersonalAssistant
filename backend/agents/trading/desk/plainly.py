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

from backend.market.levels import (
    KIND_EMA50,
    KIND_EMA200,
    KIND_NONE,
    KIND_SWING,
    KIND_WEEK21,
)

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
    "share_issuance": "share issuance",
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
    "support_level": "the support level",
    "resistance_level": "the resistance level",
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
    "cheap_vs_side": "discount to its side of the book",
    "market_cap": "its size",
}

# The release reader's fields, as the thing the release spoke about. A
# reading is -1, 0 or +1: downbeat, silent or upbeat.
TONE_SUBJECT: dict[str, str] = {
    "tone_guidance": "guidance",
    "tone_demand": "demand",
    "tone_pricing": "pricing",
    "tone_capex": "capex",
}
TONE_CHANGE: dict[str, str] = {
    "tone_guidance_change": "guidance tone",
    "tone_demand_change": "demand tone",
}
# Readings that are a state, not a size: -1, 0 or +1.
FLAG_WORDS: dict[str, tuple[str, str, str]] = {
    "weekly_trend": ("weekly trend down", "weekly trend flat", "weekly trend up"),
    "daily_trend": ("daily trend down", "daily trend flat", "daily trend up"),
    "stack_order": ("averages stacked down", "averages mixed", "averages stacked up"),
    "weekly_stack": (
        "weekly averages stacked down",
        "weekly averages mixed",
        "weekly averages stacked up",
    ),
    "converging_21_50": (
        "21-day turning down to 50-day",
        "21/50 not converging",
        "21-day turning up to 50-day",
    ),
}
# Distances said as what they are: a percentage from the level, from the
# reading's own value. They used to be said as where the name sat against
# the book ("at 200-day avg" for a mid-book distance), which read as a
# fact about the chart and was not one: a name at its yearly high could be
# "near 52-week high" and "near 52-week low" in the same list.
ABSOLUTE_DISTANCE: dict[str, str] = {
    "ema21_distance": "the 21-day average",
    "ema50_distance": "the 50-day average",
    "ema200_distance": "the 200-day average",
    "sma200_distance": "the 200-day simple average",
    "high_52w_distance": "its 52-week high",
    "low_52w_distance": "its 52-week low",
}
# Rates of change said by their sign, with the book's place only as a
# qualifier at the extremes; a moderate rise is "rising", never "flat".
SLOPE_WORDS: dict[str, str] = {
    "ema21_slope": "21-day average",
    "ema50_slope": "50-day average",
}
# Short names for the sizes placed in the book.
SHORT: dict[str, str] = {
    "revenue_yoy": "revenue growth",
    "revenue_qoq": "quarterly revenue growth",
    "gross_margin": "gross margin",
    "revenue_acceleration": "revenue acceleration",
    "eps_change_yoy": "earnings growth",
    "net_margin": "net margin",
    "capex_to_revenue": "capex/revenue",
    "share_issuance": "share issuance",
    "asset_growth": "asset growth",
    "book_to_market": "book/market",
    "reward_risk": "reward/risk to levels",
    "confluence": "timeframes agreeing",
    "price_sales": "price/sales",
    "price_earnings": "price/earnings",
    "price_book": "price/book",
    "price_sales_growth": "growth-adjusted price/sales",
    "cheap_vs_side": "discount to peers",
    "expectations_gap": "cheapness vs expected growth",
    "residual_momentum_120": "6-month momentum vs the market",
}
# Where a reading sits in the book, from its percentile. Said as a place
# in the book, never as a bare "low" or "high" that reads as an absolute.
PLACE_WORDS = (
    (0.10, "bottom of book"),
    (0.30, "low in book"),
    (0.70, "mid-book"),
    (0.90, "high in book"),
    (1.01, "top of book"),
)
MARK = {1: "+", 0: "\u00b7", -1: "\u2212"}
# What each analyst actually scores. The rest of its evidence is context:
# it may be cited when nothing scored stands out, but a reader must not be
# told an unscored reading decided a stance. The technical and value sets
# are the legs of those analysts' blends (see their modules).
SCORED_BY_ANALYST: dict[str, tuple[str, ...]] = {
    "fundamental": (
        "revenue_yoy",
        "revenue_qoq",
        "gross_margin",
        "revenue_acceleration",
    ),
    "technical": (
        "weekly_trend",
        "daily_trend",
        "residual_momentum_120",
        "support_distance",
        "range_position_60",
    ),
    "sentiment": (
        "tone_guidance",
        "tone_demand",
        "tone_guidance_change",
        "tone_pricing",
    ),
    "value": ("price_sales", "cheap_vs_side"),
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
#
# The third number is which way the measurement leans: +1 when a higher
# reading goes with a higher score from that analyst across the book
# today, -1 when lower does, 0 when the two are unrelated. A reason used
# to cite the most unusual readings whatever they argued, so CRWV on
# 2026-09-04 read "the sentiment analyst is against it, on what it said
# about demand at +1.00": the two bullish tone fields were the unusual
# ones, and the bearish fields that had actually decided the stance went
# unmentioned. With the lean known, a clause cites the readings that argue
# the analyst's way, and falls back to the unusual ones only when none do.
def spreads(report) -> dict[tuple[str, str], tuple[float, float, int]]:
    """Return (middle, spread, lean) per analyst measurement across the book."""
    t = len(report.panel.dates) - 1
    in_book = np.array([x in report.sides for x in report.panel.tickers])
    out: dict[tuple[str, str], tuple[float, float, int]] = {}
    for analyst, opinion in report.opinions.items():
        scores = np.asarray(getattr(opinion, "scores", np.full(in_book.shape, np.nan)))
        score_row = scores[t] if scores.ndim == 2 else scores
        for measure, values in getattr(opinion, "evidence", {}).items():
            row = np.asarray(values)[t]
            known = row[in_book & np.isfinite(row)]
            if len(known) < 5:
                continue
            middle = float(np.median(known))
            # Median absolute deviation: a spread that a handful of
            # extreme names cannot widen out of usefulness.
            spread = float(np.median(np.abs(known - middle)))
            both = in_book & np.isfinite(row) & np.isfinite(score_row)
            lean = _lean(row[both], score_row[both]) if both.sum() >= 5 else 0
            out[(analyst, measure)] = (
                middle,
                spread if spread > 0 else float("nan"),
                lean,
                np.sort(known),
            )
    return out


# Which way a measurement argues, from its rank correlation with the
# analyst's own score across the book: the sign when it is clear, else 0.
def _lean(values: np.ndarray, scores: np.ndarray) -> int:
    """Return +1, -1 or 0 for the direction `values` pushes `scores`."""
    a = np.argsort(np.argsort(values)).astype(float)
    b = np.argsort(np.argsort(scores)).astype(float)
    if a.std() == 0 or b.std() == 0:
        return 0
    corr = float(np.corrcoef(a, b)[0, 1])
    if corr > 0.1:
        return 1
    if corr < -0.1:
        return -1
    return 0


# One analyst's view of one name, as one line: its mark, its name, and
# the readings that argue its way, fewest words that carry the fact.
def _clause(
    analyst: str,
    stance: int,
    rank: float | None,
    cited: dict,
    scale: dict | None = None,
) -> str:
    head = f"{MARK[stance]} {analyst.capitalize()}"
    if not cited:
        return f"{head}: no data"
    strongest = _notable(analyst, cited, scale, stance)
    if not strongest:
        return head
    parts = [_figure(analyst, k, v, scale) for k, v in strongest]
    return f"{head}: {'; '.join(parts)}"


# One reading, in words a person can read: a release's tone as upbeat,
# silent or downbeat; a state as the state it is in; a distance as where
# it sits against the book; anything else by where it falls among the
# book's readings. No figure is quoted. "capital spending against revenue
# at +2.99" told a reader nothing about whether that was a lot; "among the
# highest in the book" is the same fact as the desk used it.
def _figure(analyst: str, measure: str, value: float, scale: dict | None) -> str:
    entry = (scale or {}).get((analyst, measure))
    middle = float(entry[0]) if entry and np.isfinite(entry[0]) else None
    book = entry[3] if entry and len(entry) > 3 else None
    spoken = _tone_words(measure, value, middle)
    if spoken is not None:
        return spoken
    if measure in FLAG_WORDS:
        down, flat, up = FLAG_WORDS[measure]
        return up if value > 0.5 else down if value < -0.5 else flat
    if measure in ABSOLUTE_DISTANCE:
        return _distance_words(measure, value)
    if measure in SLOPE_WORDS:
        return _slope_words(measure, value, _place(value, book))
    if measure == "spread_21_50":
        return f"21-day average {_pct(value)} the 50-day"
    if measure == "spread_21_50_slope":
        return (
            "21-day average gaining on the 50-day"
            if value > 0
            else (
                "21-day average losing to the 50-day"
                if value < 0
                else "21/50 gap steady"
            )
        )
    if measure == "range_position_60":
        return f"{max(0.0, min(1.0, value)) * 100:.0f}% up its 60-day range"
    if measure == "support_distance":
        return f"nearest support {_pct_abs(value)} below the price"
    if measure == "resistance_distance":
        return f"nearest resistance {_pct_abs(value)} above the price"
    return _placed_words(measure, value, _place(value, book))


# A log distance as "12.3% above" or "4.0% below".
def _pct(value: float) -> str:
    move = (float(np.exp(value)) - 1.0) * 100
    if abs(move) < 0.05:
        return "level with"
    return f"{abs(move):.1f}% {'above' if move > 0 else 'below'}"


def _pct_abs(value: float) -> str:
    return f"{abs(float(np.exp(abs(value))) - 1.0) * 100:.1f}%"


# A distance to a level as a percentage of the price.
def _distance_words(measure: str, value: float) -> str:
    return f"{_pct(value)} {ABSOLUTE_DISTANCE[measure]}"


# A rate of change by its sign, and its place in the book only at the ends.
def _slope_words(measure: str, value: float, place: float | None) -> str:
    label = SLOPE_WORDS[measure]
    direction = "rising" if value > 0 else "falling" if value < 0 else "flat"
    if place is not None and place > 0.9:
        return f"{label} {direction}, among the book's fastest"
    if place is not None and place < 0.1:
        return f"{label} {direction}, among the book's slowest"
    return f"{label} {direction}"


# A reading of -1, 0 or +1 as its sign.
def _sign(value: float) -> int:
    return 1 if value > 0.5 else -1 if value < -0.5 else 0


# The release reader's fields in words, or None for any other reading.
def _tone_words(measure: str, value: float, middle: float | None) -> str | None:
    sign = _sign(value)
    if measure in TONE_SUBJECT:
        subject = TONE_SUBJECT[measure]
        if sign:
            return f"{'upbeat' if sign > 0 else 'downbeat'} on {subject}"
        book = _sign(middle) if middle is not None else 0
        if book:
            return f"silent on {subject} (book {'upbeat' if book > 0 else 'downbeat'})"
        return f"silent on {subject}"
    if measure in TONE_CHANGE:
        change = {1: "improved", -1: "worsened", 0: "unchanged"}[sign]
        return f"{TONE_CHANGE[measure]} {change}"
    if measure == "tone_supply_constrained":
        return "supply constrained" if sign > 0 else "not supply constrained"
    return None


# A size, said by where it falls among the book's readings.
def _placed_words(measure: str, value: float, place: float | None) -> str:
    label = SHORT.get(measure, LABELS.get(measure, measure))
    if place is None:
        return f"{label} {'high in book' if value > 0 else 'low in book'}"
    for limit, words in PLACE_WORDS:
        if place < limit:
            return f"{label} {words}"
    return f"{label} {PLACE_WORDS[-1][1]}"


# The share of the book's readings below this one, or None without a book.
def _place(value: float, book) -> float | None:
    if book is None or len(book) < 5:
        return None
    arr = np.asarray(book, dtype=float)
    below = float((arr < value).mean())
    equal = float((arr == value).mean())
    return below + 0.5 * equal


# The measurements that set this name apart from the book, largest first;
# with a stance, the ones that argue its way come first, and the rest are
# used only when none do.
def _notable(
    analyst: str, cited: dict, scale: dict | None, stance: int = 0
) -> list[tuple[str, float]]:
    ranked: list[tuple[float, str, float, bool]] = []
    for measure, value in cited.items():
        if measure in CONTEXT or not np.isfinite(value):
            continue
        entry = (scale or {}).get((analyst, measure), (0.0, float("nan"), 0))
        middle, spread = entry[0], entry[1]
        lean = entry[2] if len(entry) > 2 else 0
        if scale is None:
            # No book to compare against: fall back to the reading itself,
            # which is right for the tone fields, where every value is
            # -1, 0 or 1 and the scale is already shared.
            score = abs(float(value))
            direction = float(value)
        elif not np.isfinite(spread):
            # A book that mostly agrees has no spread to divide by, but
            # its middle still says what is unusual: a release that says
            # nothing about guidance, in a book where most guide up, is
            # the reading that set the name apart, and the bullish field
            # it shares with everyone is not.
            score = abs(float(value) - middle)
            direction = (float(value) - middle) * lean
        else:
            score = abs(float(value) - middle) / spread
            direction = (float(value) - middle) * lean
            if score < NOTABLE:
                continue
        if score > QUIET:
            # Tone-style readings with no scale lean their own way.
            argues = stance != 0 and direction * stance > 0
            ranked.append((score, measure, float(value), argues))
    if stance != 0 and any(r[3] for r in ranked):
        ranked = [r for r in ranked if r[3]]
    scored = SCORED_BY_ANALYST.get(analyst)
    if scored and any(r[1] in scored for r in ranked):
        ranked = [r for r in ranked if r[1] in scored]
    ranked.sort(key=lambda r: -r[0])
    return [(measure, value) for _score, measure, value, _argues in ranked[:CITE]]


# The whole reason for one name: the grade, what it means to do, and the
# analysts that decided it, strongest opinion first.
def reason(view: dict, scale: dict | None = None) -> str:
    """Return a plain-English reason for one name's grade."""
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
        return "No analyst had a view on it today."
    return chr(10).join(clauses[:5])


# What a level's kind means in words: a swing point from the daily bars,
# or one of the averages the price tends to respect.
LEVEL_KIND_WORDS: dict[int, str] = {
    KIND_SWING: "a swing point from the daily chart",
    KIND_EMA50: "the 50-day average",
    KIND_EMA200: "the 200-day average",
    KIND_WEEK21: "the weekly 21-day average",
}


# One support or resistance line, naming what the level is and how far away
# price sits, so a read does not say "nearest support" and leave the reader
# to guess whether that is a price from the past or an average.
def _level_words(side: str, kind: float, level: float, distance: float) -> str | None:
    """Return a plain line for one level, or None without one."""
    if not np.isfinite(kind) or int(kind) == KIND_NONE:
        return None
    if not np.isfinite(distance):
        return None
    pct = abs(float(distance)) * 100
    k = int(kind)
    if side == "support":
        what = "a swing low" if k == KIND_SWING else LEVEL_KIND_WORDS.get(k)
        return f"nearest support is {pct:.0f}% below the price — {what}"
    what = "a swing high" if k == KIND_SWING else LEVEL_KIND_WORDS.get(k)
    return f"nearest resistance is {pct:.0f}% above the price — {what}"


# Every reading the desk used for one name, in plain words, with nothing
# omitted. The reason lines above show the two most unusual readings per
# analyst, which is a sentence; this is the whole evidence, for the person
# who wants to see every trigger behind the recommendation.
def reads(view: dict, scale: dict | None = None) -> dict[str, list[str]]:
    """Return {analyst: [plain-word reading, ...]} for a name, all of them."""
    out: dict[str, list[str]] = {}
    for analyst, cited in (view.get("evidence") or {}).items():
        lines: list[str] = []
        for measure, value in cited.items():
            if measure in CONTEXT or not np.isfinite(value):
                continue
            if measure == "support_kind":
                line = _level_words(
                    "support",
                    value,
                    cited.get("support_level"),
                    cited.get("support_distance"),
                )
                if line:
                    lines.append(line)
            elif measure == "resistance_kind":
                line = _level_words(
                    "resistance",
                    value,
                    cited.get("resistance_level"),
                    cited.get("resistance_distance"),
                )
                if line:
                    lines.append(line)
            elif measure in (
                "support_distance",
                "resistance_distance",
                "support_level",
                "resistance_level",
            ):
                # The distance and the level are said together in the lines
                # above; repeating them separately would be the same fact
                # twice in one list.
                continue
            else:
                lines.append(_figure(analyst, measure, float(value), scale))
        out[analyst] = lines
    return out


# The one line a table can show without opening anything: the action and
# the analysts on each side.
def headline(view: dict) -> str:
    """Return a one-line summary of why a name is graded as it is."""
    grade = str(view.get("grade", "?"))
    action = ACTION.get(grade, "no action").split()[0].capitalize()
    stances = view.get("stances") or {}
    decisive = [a for a, s in stances.items() if s and abs(int(s)) == 1]
    if not decisive:
        return f"{action}: no analyst has a strong view"
    bulls = [a for a in decisive if int(stances[a]) > 0]
    bears = [a for a in decisive if int(stances[a]) < 0]
    if bulls and not bears:
        return f"{action}: {_names(bulls)} for, none against"
    if bears and not bulls:
        return f"{action}: {_names(bears)} against, none for"
    return f"{action}: {_names(bulls)} for; {_names(bears)} against"


# "sentiment", "fundamental and technical", "3 analysts".
def _names(analysts: list[str]) -> str:
    ordered = sorted(analysts)
    if len(ordered) <= 2:
        return " and ".join(ordered)
    return f"{len(ordered)} analysts"
