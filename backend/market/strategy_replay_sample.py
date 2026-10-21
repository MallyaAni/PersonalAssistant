"""Which replayed decisions the frozen models had already seen.

The chart replays today's sizing and timing models over the past. Both heads
were fitted on data through a frozen date, so a replayed decision at or
before that date is in-sample: the model saw its outcome while fitting, and
the chart must not present it as validation. Decisions after the date are
the only ones that test the models. The stamp is added where the sealed
history is served, not inside the artefact: the history bytes and the
modules that write them are bound by the installed release approval, and a
display fact does not justify re-approving the trading sources.
"""

from datetime import date

from backend.market import daily_arithmetic_bridge as reference
from backend.market import probabilistic_execution as timing

# The sizing and timing heads were fitted through the later of their frozen
# boundaries; decisions at or before it are in-sample for the owner's replay
# check.
MODEL_FIT_THROUGH = str(max(reference.FREEZE, timing.FREEZE))
IN_SAMPLE = "in_sample"
OUT_OF_SAMPLE = "out_of_sample"


# The sample a dated row belongs to; a row without a date is left unstamped
# rather than guessed, since the chart treats an absent stamp as unknown.
def sample(row, fit_through=None):
    """Return in_sample, out_of_sample, or None for an undated row."""
    day = row.get("at") or row.get("date")
    if not isinstance(day, str) or len(day) < 10:
        return None
    boundary = fit_through or date.fromisoformat(MODEL_FIT_THROUGH)
    try:
        return IN_SAMPLE if date.fromisoformat(day[:10]) <= boundary else OUT_OF_SAMPLE
    except ValueError:
        return None


# Stamp one stock's rows and say how its decisions split. The summary view
# carries counts under the same keys, not rows, so only lists are stamped.
def stamp_stock(stock):
    """Add `sample` to each decision, trade and target; return the decision counts."""
    counts = {IN_SAMPLE: 0, OUT_OF_SAMPLE: 0}
    for key in ("decisions", "trades", "targets"):
        rows = stock.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            stamped = sample(row)
            if stamped is not None:
                row["sample"] = stamped
                if key == "decisions":
                    counts[stamped] += 1
    return counts


# Stamp a served history view - one stock or the whole summary - in place.
def stamp(value):
    """Return `value` with sample stamps and the fit date on its provenance."""
    if not isinstance(value, dict):
        return value
    counts = {IN_SAMPLE: 0, OUT_OF_SAMPLE: 0}
    stocks = value.get("stocks")
    if isinstance(stocks, dict):
        for stock in stocks.values():
            if isinstance(stock, dict):
                for key, number in stamp_stock(stock).items():
                    counts[key] += number
    else:
        counts = stamp_stock(value)
    provenance = value.get("provenance")
    if isinstance(provenance, dict):
        value["provenance"] = {**provenance, "model_fit_through": MODEL_FIT_THROUGH}
    else:
        value["model_fit_through"] = MODEL_FIT_THROUGH
    # A view with no rows to stamp (the summary's counts) gets the fit date only;
    # a zero split there would read as a measurement that was never taken.
    if isinstance(value.get("decisions"), list) or isinstance(stocks, dict):
        value["in_sample_decisions"] = counts[IN_SAMPLE]
        value["out_of_sample_decisions"] = counts[OUT_OF_SAMPLE]
    return value
