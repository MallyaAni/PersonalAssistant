"""Earnings refreshes retain their version and survive interrupted processing."""

from dataclasses import asdict, replace
from datetime import date
from types import SimpleNamespace

import pytest

from backend.cli import market_tone
from backend.market import edgar, language
from backend.market.store import MarketStore

ASOF = date(2026, 9, 13)


# Build one signed-loss result with an explicit reader version.
def record(version=market_tone.PROMPT_VERSION):
    return language.ToneRecord(
        "accession",
        date(2026, 9, 10),
        0,
        0,
        0,
        0,
        0,
        "reported loss",
        "fixture",
        version,
        False,
        net_income_usd_m=-42,
    )


# Seed the filing boundary without fetching or modifying real market data.
def store_with_event(tmp_path):
    store = MarketStore(tmp_path)
    store.write_frame(
        "edgar_events",
        ASOF,
        "AAA",
        {
            "accepted": ["2026-09-10T13:00:00+00:00"],
            "filed": [date(2026, 9, 10)],
            "accession": ["accession"],
            "items": ["2.02"],
        },
        {"cik": "1"},
    )
    return store


# Drive the production refresh boundary with a deterministic reader.
def refresh(store, tone):
    reader = SimpleNamespace(score_sync=lambda text: tone)
    return market_tone._refresh_ticker(
        store, "AAA", ASOF, date(2015, 1, 1), [reader], "fixture", edgar.Pacer()
    )


# Old partial output must be rescored rather than relabelled as current.
def test_old_partial_is_rescored_and_signed_value_persists(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)
    partial = language.partial_path(store.root, ASOF, "AAA")
    language.append_partial(
        partial, replace(record("release_tone/2"), net_income_usd_m=0)
    )
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: "release")
    tone = SimpleNamespace(**asdict(record()))
    assert refresh(store, tone)[0] == 1
    columns, meta = store.read_frame(language.TONE_KIND, "AAA", ASOF)
    assert columns["net_income_usd_m"] == [-42]
    assert columns["prompt_version"] == [market_tone.PROMPT_VERSION]
    assert meta["prompt_version"] == market_tone.PROMPT_VERSION
    assert not partial.exists()


# A failed model run must remain retryable, without sealing an empty daily frame.
def test_model_failure_keeps_partial_and_does_not_publish(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)
    partial = language.partial_path(store.root, ASOF, "AAA")
    language.append_partial(partial, replace(record(), accession="earlier"))
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: "release")
    with pytest.raises(RuntimeError, match="incomplete"):
        refresh(store, None)
    assert not store.has_frame(language.TONE_KIND, ASOF, "AAA")
    assert "earlier" in language.read_partial(partial)
    assert refresh(store, SimpleNamespace(**asdict(record())))[0] == 1
    columns, _meta = store.read_frame(language.TONE_KIND, "AAA", ASOF)
    assert set(columns["accession"]) == {"accession", "earlier"}
    assert not partial.exists()


# A provider outage cannot become an apparently complete empty earnings frame.
def test_provider_failure_does_not_publish(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)

    # Reproduce the error raised after SEC retrieval retries are exhausted.
    def unavailable(*args, **kwargs):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(language, "fetch_release_text", unavailable)
    with pytest.raises(RuntimeError, match="incomplete"):
        refresh(store, None)
    assert not store.has_frame(language.TONE_KIND, ASOF, "AAA")


# A successfully retrieved filing without a results exhibit is explicit coverage.
def test_no_exhibit_is_recorded_as_missing_coverage(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: None)
    assert refresh(store, None) == (0, 1, 0)
    _columns, metadata = store.read_frame(language.TONE_KIND, "AAA", ASOF)
    assert metadata["events_considered"] == "1"
    assert metadata["without_text"] == "1"


# If another writer wins publication, resumable evidence must not be discarded.
def test_refused_publication_retains_partial(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: "release")
    monkeypatch.setattr(store, "write_frame", lambda *a, **k: False)
    with pytest.raises(RuntimeError, match="partial results retained"):
        refresh(store, SimpleNamespace(**asdict(record())))
    assert "accession" in language.read_partial(
        language.partial_path(store.root, ASOF, "AAA")
    )


# Metadata alone must not bless an old record carried into a new partition.
def test_prior_records_check_each_record_version(tmp_path):
    store = MarketStore(tmp_path)
    store.write_frame(
        language.TONE_KIND,
        date(2026, 9, 12),
        "AAA",
        language.tone_frame([record("release_tone/2")]),
        {"prompt_version": market_tone.PROMPT_VERSION},
    )
    assert market_tone.prior_records(store, "AAA", ASOF, "fixture") == {}


# An incompatible same-day frame is reported, never silently kept or overwritten.
def test_same_day_version_mismatch_is_explicit_and_immutable(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    old = language.tone_frame([record("release_tone/2")])
    store.write_frame(
        language.TONE_KIND, ASOF, "AAA", old, {"prompt_version": "release_tone/2"}
    )
    monkeypatch.setattr(market_tone, "clients", lambda *a: ([], "fixture"))
    with pytest.raises(RuntimeError, match="new as-of partition"):
        market_tone.refresh_tickers(store, ("AAA",), ASOF)
    assert store.read_frame(language.TONE_KIND, "AAA", ASOF)[0]["prompt_version"] == [
        "release_tone/2"
    ]


# Model changes cannot reuse yesterday's scores just because the prompt is unchanged.
@pytest.mark.parametrize(
    ("metadata_model", "record_model"),
    [
        ("other", "fixture"),
        ("fixture", "other"),
        (None, "fixture"),
    ],
)
def test_prior_records_require_model_in_metadata_and_record(
    tmp_path, metadata_model, record_model
):
    store = MarketStore(tmp_path)
    store.write_frame(
        language.TONE_KIND,
        date(2026, 9, 12),
        "AAA",
        language.tone_frame([replace(record(), model=record_model)]),
        {
            "prompt_version": market_tone.PROMPT_VERSION,
            **({"model": metadata_model} if metadata_model else {}),
        },
    )
    assert market_tone.prior_records(store, "AAA", ASOF, "fixture") == {}


# A same-day model mismatch fails without overwriting the immutable source partition.
def test_same_day_model_mismatch_is_explicit_and_immutable(tmp_path, monkeypatch):
    store = MarketStore(tmp_path)
    store.write_frame(
        language.TONE_KIND,
        ASOF,
        "AAA",
        language.tone_frame([record()]),
        {"prompt_version": market_tone.PROMPT_VERSION, "model": "fixture"},
    )
    monkeypatch.setattr(market_tone, "clients", lambda *a: ([], "new-model"))
    with pytest.raises(RuntimeError, match="new as-of partition"):
        market_tone.refresh_tickers(store, ("AAA",), ASOF)
    columns, meta = store.read_frame(language.TONE_KIND, "AAA", ASOF)
    assert meta["model"] == "fixture"
    assert columns["model"] == ["fixture"]


# Interrupted work from another model is rescored, not mixed into new-model records.
def test_partial_model_mismatch_is_rescored(tmp_path, monkeypatch):
    store = store_with_event(tmp_path)
    partial = language.partial_path(store.root, ASOF, "AAA")
    language.append_partial(partial, replace(record(), model="other"))
    monkeypatch.setattr(language, "fetch_release_text", lambda *a, **k: "release")
    assert refresh(store, SimpleNamespace(**asdict(record())))[0] == 1
    columns, meta = store.read_frame(language.TONE_KIND, "AAA", ASOF)
    assert columns["model"] == ["fixture"]
    assert meta["model"] == "fixture"
