"""Private continuation must conserve original unsent intents without resubmission."""

from copy import deepcopy
from datetime import date

import pytest

from backend.cli.market_strategy_continue import seed_intents


# Build a settled private seed with an unsent next-session trim.
def seed():
    order = {
        "client_order_id": "original-trim",
        "symbol": "STOCK",
        "side": "sell",
        "qty": 5,
        "session": "2026-10-09",
        "execute_on": "2026-10-12",
        "execution_timing": "dip_or_close",
        "execution": {
            "decision_at": "2026-10-09T16:01:00-04:00",
            "reference_session": "2026-10-09",
            "reference_price": 100,
            "reference_source": "daily panel close",
        },
    }
    return {
        "last": "2026-10-09",
        "nightly": {"at": "2026-10-09T16:01:00-04:00"},
        "paper_state": {"pending": [deepcopy(order)]},
        "carried_intents": [order],
    }


# Original ids, sizes, decision clocks and pending state survive detached restoration.
def test_unsent_seed_carries_original_intents_without_mutating_source():
    value = seed()
    before = deepcopy(value)
    result = seed_intents(value, date(2026, 10, 12))
    assert list(result) == ["original-trim"]
    assert result["original-trim"] == value["paper_state"]["pending"][0]
    result["original-trim"]["qty"] = 1
    assert value == before
    value["paper_state"]["pending"] = []
    value["carried_intents"] = []
    assert seed_intents(value, date(2026, 10, 12)) == {}


# Submitted, partial or misdated orders cannot become fresh unsent plans.
@pytest.mark.parametrize(
    ("path", "replacement"),
    [
        (("sent",), {"at": "2026-10-12T10:00:00-04:00"}),
        (("execution", "submitted_at"), "2026-10-12T10:00:00-04:00"),
        (("execution", "filled_qty"), 1),
        (("status",), "new"),
        (("event_id",), "event"),
        (("side",), "hold"),
        (("qty",), 1.5),
        (("qty",), True),
        (("qty",), 0),
        (("session",), "2026-10-08"),
        (("execute_on",), "2026-10-09"),
        (("execution", "decision_at"), "2026-10-09T16:01:00"),
        (("execution", "decision_at"), "2026-10-09T15:00:00-04:00"),
        (("execution", "reference_session"), "2026-10-08"),
    ],
)
def test_acknowledged_or_invalid_seed_intents_are_refused(path, replacement):
    value = seed()
    node = value["carried_intents"][0]
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = replacement
    value["paper_state"]["pending"] = deepcopy(value["carried_intents"])
    with pytest.raises(ValueError, match="Unacknowledged next-session"):
        seed_intents(value, date(2026, 10, 12))


# Missing evidence, a replaced quantity or a duplicate id must fail before replay.
@pytest.mark.parametrize("failure", ["missing", "altered", "duplicate", "overlap"])
def test_seed_evidence_and_exclusive_date_are_required(failure):
    value = seed()
    through = date(2026, 10, 12)
    if failure == "missing":
        del value["carried_intents"]
    elif failure == "altered":
        value["carried_intents"][0]["qty"] = 4
    elif failure == "duplicate":
        value["carried_intents"].append(deepcopy(value["carried_intents"][0]))
        value["paper_state"]["pending"] = deepcopy(value["carried_intents"])
    else:
        through = date(2026, 10, 9)
    with pytest.raises(ValueError, match="seed|Seed|subsequent"):
        seed_intents(value, through)
