"""The `/3` board scenarios whose output must not change when the `/4` board is timed.

`test_board_level_gate.test_the_v3_board_is_identical_to_main` builds every
scenario here and compares it with `fixtures/board_v3_golden.json.gz`, which was
generated from `main` (f31346ed) before the dip-or-close timing existed, with
this file run under that checkout:

    PYTHONPATH=<main checkout>:<pytest> python backend/tests/board_v3_scenarios.py

The golden is every board as sorted-key JSON with floats written to 12
significant digits (`canonical`), so a last-bit difference in a numpy build on
another machine is not read as a change while any real change is; gzip takes
the 220 KB of repeated rows to 4 KB. Nothing here may import from a test
module the timing change edits, so the generator and the test build exactly
the same inputs.
"""

import gzip
import json
from datetime import timedelta

from backend.market.holdings import Holding

GOLDEN = "fixtures/board_v3_golden.json.gz"


# The shared fixture's record, snapshot, fresh quotes and clock, with the
# paper reset due (the same inputs `test_decision_view.setup` builds).
def _inputs():
    """Return (record, snapshot, quoted, now) for one scenario."""
    from backend.tests.test_intraday_candidate import inputs

    record, snapshot, _, _, now = inputs()
    record["paper"] = {"until_rebalance": 0}
    quoted = {
        "feed": "sip",
        "market_open": True,
        "quotes": {
            n: {"bp": 99.99, "ap": 100.01, "bs": 10, "as": 10, "t": now.isoformat()}
            for n in record["grades"]
        },
    }
    return record, snapshot, quoted, now


# Every `/3` scenario as (name, positional args, keyword args) for
# `decision_view.build`: the personal board with and without cash, holdings,
# firing and quiet band readings, a closed market, a band-rejecting name, an
# FOMC pause, an intraday downgrade of a held name, a target stamp from
# another policy, and the explicit-targets research path.
def scenarios():  # noqa: C901 - a flat list of variations, one per block
    """Return [(name, args, kwargs)] for the `/3` board."""
    out = []

    # Append one scenario built from fresh inputs changed by `change`.
    def add(name, change, held=(), **kwargs):
        record, snapshot, quoted, now = _inputs()
        change(record, snapshot, quoted, now)
        out.append((name, (record, list(held), 100000, snapshot, quoted, now), kwargs))

    # Leave the inputs as they are.
    def same(record, snapshot, quoted, now):
        return None

    add("entry-cash", same, entries={"S11": 1.5}, cash=100000)
    add("no-cash-no-entry", same)
    add(
        "held-and-uncovered",
        same,
        held=(
            Holding("S11", 5.0, 100.0, "2026-08-01"),
            Holding("S99", 999.0, 12.0, "2026-01-02"),
        ),
        entries={"S11": 1.5, "S10": 0.5},
        cash=50000,
    )

    # Shut the market for execution.
    def closed(record, snapshot, quoted, now):
        quoted["market_open"] = False

    add("market-closed", closed, entries={"S11": 1.5}, cash=100000)

    # Mark S11 as rejecting its upper band on the record.
    def band(record, snapshot, quoted, now):
        record["levels"] = {"S11": {"rejecting_band": True}}

    add("band-rejecting", band, entries={"S11": 1.5}, cash=100000)

    # Put the book in an FOMC pause.
    def paused(record, snapshot, quoted, now):
        record["event_risk"] = {"execution_pending": True}

    add("fomc-paused", paused, entries={"S11": 1.5}, cash=100000)

    # Downgrade S11 at the candle (the `/3` board exits on the re-grade).
    def downgraded(record, snapshot, quoted, now):
        snapshot["technical"]["S11"] = {"now": 0.01, "close": 0.7, "stance": -1}

    add(
        "intraday-downgrade",
        downgraded,
        held=(Holding("S11", 50.0, 100.0, "2026-08-01"),),
        cash=1000.0,
    )

    # Stamp the record with a policy that is not the active one.
    def other_policy(record, snapshot, quoted, now):
        record["paper"] = {"until_rebalance": 10}
        record["targets"] = {
            "policy": "some-other-policy/9",
            "weights": {n: 1 / 12 for n in record["grades"]},
        }

    add("other-policy", other_policy, cash=100000)

    # A stale quote on S11.
    def stale(record, snapshot, quoted, now):
        quoted["quotes"]["S11"]["t"] = (now - timedelta(seconds=31)).isoformat()

    add("stale-quote", stale, entries={"S11": 1.5}, cash=100000)
    # The explicit-targets research path (the board simulation's call).
    record, snapshot, quoted, now = _inputs()
    out.append(
        (
            "research-targets",
            (record, [], 100000, snapshot, quoted, now),
            {"targets": {n: (0.05 if n == "S11" else 0.0) for n in record["grades"]}},
        )
    )
    return out


# A JSON value with every float written to 12 significant digits, so the
# comparison is exact about everything but the last bits of a float.
def canonical(value):
    """Return `value` with its floats rounded to 12 significant digits."""
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items()}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


# Build every scenario with `extra` keyword arguments added, and return
# {name: the board as a canonical JSON value}.
def render(extra=None):
    """Return {scenario name: canonical(json round trip of build(...))}."""
    from backend.market import decision_view

    rendered = {}
    for name, args, kwargs in scenarios():
        built = decision_view.build(*args, **{**kwargs, **(extra or {})})
        rendered[name] = canonical(json.loads(json.dumps(built, default=str)))
    return rendered


# Serialise rendered boards the way the golden file stores them.
def dumps(rendered) -> bytes:
    """Return the sorted-key, compact JSON bytes of `rendered`."""
    return json.dumps(rendered, sort_keys=True, separators=(",", ":")).encode()


# Read the golden boards generated from `main`.
def golden(path):
    """Return the rendered boards stored at `path` (gzip JSON)."""
    return json.loads(gzip.decompress(path.read_bytes()))


if __name__ == "__main__":
    import sys
    from pathlib import Path

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / GOLDEN
    target.write_bytes(gzip.compress(dumps(render()), mtime=0))
    print(f"wrote {target}")
