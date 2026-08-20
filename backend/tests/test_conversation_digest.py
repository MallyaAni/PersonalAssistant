"""The digest has to have a ceiling, and it did not.

Each interval appended that interval's verbatim exchanges to the digest before
it, and the latest digest is injected into every prompt. So a conversation's
prompt overhead grew linearly and without limit: at a ten-turn interval, a
hundred-turn conversation would have carried roughly a hundred kilobytes of
truncated transcript into every single request.

It survived unnoticed because it had barely been exercised - one row existed in
the whole store. A defect that needs a long conversation to appear is not a
defect that will stay hidden.

What this is still not: a summary. Nothing asks a model to compress meaning
here, because that costs a call and belongs behind its own setting and prompt.
What is guaranteed is the property that was missing - a ceiling - and the right
direction of loss when it binds.
"""

from backend.memory.coordinator import _digest


def _turns(count: int = 10):
    return [{"query": "q" * 400, "response": "r" * 900} for _ in range(count)]


# The defect, stated as a property: repeated compaction must converge.
def test_the_digest_stops_growing():
    previous = None
    sizes = []
    for _ in range(30):
        content = _digest(previous, _turns(), 4_000)
        previous = {"content": content}
        sizes.append(len(content))

    assert max(sizes) <= 4_000
    assert sizes[-1] == sizes[5], "the digest was still growing after 30 intervals"


def test_a_first_digest_needs_no_predecessor():
    content = _digest(None, _turns(2), 4_000)

    assert content.startswith("Recent exchanges:")
    assert len(content) <= 4_000


# When the ceiling binds, the newest material is what survives. A digest exists
# so the distant past is recoverable; the recent past is what the current turn
# is most likely to depend on.
def test_the_newest_material_survives_the_ceiling():
    previous = {"content": "OLDEST-MARKER " + "z" * 5_000}

    content = _digest(
        previous, [{"query": "newest question", "response": "newest answer"}], 800
    )

    assert "newest question" in content
    assert "OLDEST-MARKER" not in content


def test_an_older_digest_is_carried_when_there_is_room():
    previous = {"content": "an earlier exchange worth keeping"}

    content = _digest(previous, [{"query": "q", "response": "r"}], 4_000)

    assert "an earlier exchange worth keeping" in content
    assert "Previous digest:" in content


def test_an_empty_predecessor_is_not_carried_as_a_heading():
    content = _digest({"content": "   "}, [{"query": "q", "response": "r"}], 4_000)

    assert "Previous digest:" not in content


# A ceiling too small for even the newest exchange must still return something
# bounded rather than raising or returning a negative slice.
def test_a_tiny_ceiling_is_still_honoured():
    for ceiling in (1, 10, 50):
        content = _digest({"content": "x" * 1_000}, _turns(3), ceiling)
        assert len(content) <= ceiling


def test_the_exchange_text_is_still_bounded_per_turn():
    content = _digest(None, [{"query": "q" * 5_000, "response": "r" * 5_000}], 100_000)

    # Each side is clipped before it reaches the digest, so one enormous turn
    # cannot consume an interval's whole allowance.
    assert len(content) < 1_500
