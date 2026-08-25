"""Does the real reranker actually rank?

The structural suite proves fail-soft; this proves the point of the stage:
query and candidate read together must beat vector adjacency. Asserted on an
unambiguous case - a candidate that answers the question outranking two that
merely share its words - because a reranker that cannot get this right is
adding latency, not precision.
"""

import pytest

from backend.core.reranker import rerank, reranker_enabled

pytestmark = pytest.mark.asyncio


async def test_the_answer_outranks_the_lexically_similar():
    if not reranker_enabled():
        pytest.skip("no reranker configured")
    query = "what wine goes well with roast duck?"
    documents = [
        "The duck pond in the park freezes over most winters.",
        "A pinot noir pairs beautifully with roast duck - light enough "
        "not to fight the fat.",
        "Wine glasses should be stored upside down to keep dust out.",
    ]
    scores = await rerank(query, documents)
    assert scores is not None, "reranker configured but unreachable"
    assert scores[1] == max(scores), (
        f"the actual answer did not win: {scores}"
    )


async def test_scores_align_by_index_not_arrival_order():
    if not reranker_enabled():
        pytest.skip("no reranker configured")
    query = "how do I reset my router?"
    documents = [
        "Hold the reset button for ten seconds until the lights blink.",
        "Routers route packets between networks.",
    ]
    scores = await rerank(query, documents)
    assert scores is not None
    assert scores[0] > scores[1]
