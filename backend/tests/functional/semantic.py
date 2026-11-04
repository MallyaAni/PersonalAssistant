"""Assert what an answer says, not which words it used.

The functional gate flaked at roughly ten percent, and every observed flake
was the same shape: a positive marker list over sampled prose. A model that
answered "making it impossible to determine the species" failed a test whose
markers were "cannot", "not possible" and "insufficient" - the behaviour the
test exists to require, failed for its phrasing. The test's own comment
records the previous round of exactly this, where "cannot determine" missed
"the fish species cannot be determined"; the list was widened once and
drifted again. A marker list over free prose is keyword routing by another
name, and this repository already retired keyword routing for the same
reason: people rarely use the word you guessed.

So the property is judged semantically, by the routing model on the engine
that enforces JSON schemas, at temperature zero. The judge never generates
prose - the schema admits only {"holds": true|false} - so there is nothing
here for a marker to miss.

What still belongs to plain `in`: exact facts and identities. "90" must
appear when 90 is the answer; an invented species name either appears or
does not. Those checks are not about meaning and do not flake. This helper
is for the assertions that were about meaning all along.
"""

import pytest

from backend.services.semantic_judge import judge_answer


def states(answer: str, statement: str) -> bool:
    """Whether the answer, read as a whole, does what the statement says.

    Judged rather than matched, so a run is not failed by a synonym. The
    routing model is the judge because its engine enforces the schema (the
    property this repository verified before pinning six callers to it) and
    because at temperature zero the same answer gets the same verdict.

    The judge itself lives in backend/services/semantic_judge.py so the live
    sweep can call it from the runtime container, which has no pytest. Here
    an unreachable judge is a skip; the sweep treats it as a failed journey.
    """
    try:
        return judge_answer(answer, statement)
    except Exception as exc:  # pragma: no cover - depends on the host runtime
        pytest.skip(
            f"routing model unreachable for semantic assert: {type(exc).__name__}"
        )
