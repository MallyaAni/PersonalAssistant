"""A tone re-score under a new prompt is named as a data revision; a new release is not.

PANW's Sep 2 release went from 1.0 to 0.8 on guidance and demand under a
new prompt version on 2026-09-11 with nothing new filed, and its vote
flipped in one night. The record must say so, and must not call a genuinely
new release a revision.
"""

from datetime import date

import pytest

from backend.market import tone_revisions
from backend.market.language import TONE_KIND


def _row(accession, guidance, version, day="2026-09-02"):
    return {
        "accession": accession,
        "reaction_date": day,
        "guidance": guidance,
        "demand": guidance,
        "pricing": 0.0,
        "capex": 0.0,
        "supply_constrained": 0.0,
        "prompt_version": version,
    }


def test_a_re_read_of_the_same_release_is_a_revision():
    before = _row("0001-19", 1.0, "release_tone/1")
    now = _row("0001-19", 0.8, "release_tone/2")
    found = tone_revisions.compare(now, before)
    assert found["accession"] == "0001-19"
    assert found["prompt_version"] == ["release_tone/1", "release_tone/2"]
    assert found["fields"] == {"guidance": [1.0, 0.8], "demand": [1.0, 0.8]}
    # A version bump that leaves every field alone is still a revision to name.
    same_fields = tone_revisions.compare(_row("0001-19", 1.0, "release_tone/3"), before)
    assert same_fields["fields"] == {}
    assert same_fields["prompt_version"][1] == "release_tone/3"


def test_a_new_release_or_an_unchanged_reading_is_not():
    before = _row("0001-19", 1.0, "release_tone/1")
    assert (
        tone_revisions.compare(
            _row("0001-20", 0.8, "release_tone/1", "2026-09-11"), before
        )
        is None
    )
    assert tone_revisions.compare(dict(before), before) is None
    assert tone_revisions.compare(None, before) is None


def test_detect_reads_the_newest_row_of_each_session(tmp_path):
    pytest.importorskip("pyarrow")
    from backend.market.store import MarketStore

    store = MarketStore(tmp_path)
    columns = lambda guidance, version: {  # noqa: E731
        "accession": ["0001-18", "0001-19"],
        "reaction_date": ["2026-06-11", "2026-09-02"],
        "guidance": [0.9, guidance],
        "demand": [0.9, guidance],
        "pricing": [0.0, 0.0],
        "capex": [0.0, 0.0],
        "supply_constrained": [0.0, 0.0],
        "prompt_version": ["release_tone/1", version],
    }
    store.write_frame(
        TONE_KIND, date(2026, 9, 10), "PANW", columns(1.0, "release_tone/1")
    )
    store.write_frame(
        TONE_KIND, date(2026, 9, 11), "PANW", columns(0.8, "release_tone/2")
    )
    store.write_frame(
        TONE_KIND, date(2026, 9, 11), "ORCL", columns(1.0, "release_tone/1")
    )
    found = tone_revisions.detect(
        store, ["PANW", "ORCL", "NONE"], date(2026, 9, 11), date(2026, 9, 10)
    )
    assert list(found) == ["PANW"]
    assert found["PANW"]["fields"]["guidance"] == [1.0, 0.8]
    assert found["PANW"]["reaction_date"] == "2026-09-02"
