"""Published source bytes, causal current-book context and explicit price bases."""

import json
from datetime import datetime

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from backend.market import calendar, learned_entry_data
from backend.market import sequential_shadow_context as context


# Write realistic explicit Yahoo vintages and a prior-night research record.
def source_case(tmp_path):
    _, sessions = calendar.reviewed_sessions()
    dates = np.busday_offset(
        np.datetime64("2026-10-02"), np.arange(-300, 1), busdaycal=sessions
    )
    partition = tmp_path / "bars" / "asof=2026-10-02"
    partition.mkdir(parents=True)
    for ticker in ("ONE", "TWO", "SPY", "QQQ"):
        table = pa.table(
            {
                "session_date": pa.array(dates.astype(object).tolist(), pa.date32()),
                "adjusted_close": np.linspace(10, 15, len(dates)),
                "close": np.linspace(20, 30, len(dates)),
            }
        ).replace_schema_metadata(
            {
                b"ticker": ticker.encode(),
                b"source": b"yahoo",
                b"source_time": b"2026-10-02T23:30:07+00:00",
                b"complete_through": b"2026-10-02",
                b"asof": b"2026-10-02",
            }
        )
        pq.write_table(table, partition / f"{ticker}.parquet")
    record = tmp_path / "desk.json"
    record.write_text(
        json.dumps(
            {
                "session": "2026-10-02",
                "written": "2026-10-02T23:46:37+00:00",
                "grades": {"ONE": {"grade": "A+"}, "TWO": {"grade": "B"}},
                "provenance": {
                    "code_revision": "fixture-known-source",
                    "data": {"first_session": str(dates[0])},
                },
            }
        )
    )
    capture = datetime(2026, 10, 5, 9, 46, tzinfo=calendar.NEW_YORK)
    return record, partition, "2026-10-05", capture


# Preserve the complete EMA origin, prior-only grades, recorded book and separate bases.
def test_context_preserves_causal_feature_history_and_does_not_invent_raw_anchor(
    tmp_path,
):
    loaded = context.load_context(*source_case(tmp_path))
    assert len(loaded.panel.dates) == 302
    assert str(loaded.panel.dates[-2]) == "2026-10-02"
    assert np.isnan(loaded.panel.adj_close[-1]).all()
    assert np.all(loaded.grades[:-2] == -1)
    assert np.all(loaded.grades[-1] == -1)
    assert loaded.eligible[-2].sum() == 2
    assert not loaded.eligible[:-2].any()
    one = loaded.panel.tickers.index("ONE")
    assert loaded.grades[-2, one] == 3
    assert loaded.panel.adj_close[-2, one] == 15
    assert loaded.split_adjusted_prior_closes["ONE"] == 30
    assert loaded.raw_prior_closes == {}
    assert loaded.provenance["membership_basis"] == "recorded_current_book"
    assert len(loaded.provenance["sources"]) == 5
    features, valid = learned_entry_data._daily_context(
        loaded.panel.adj_close,
        loaded.grades,
        loaded.eligible,
        loaded.panel.tickers.index("SPY"),
    )
    assert valid[-1, one]
    assert features[-1, one, 8] == 3
    assert features[-1, one, 12] == 1
    assert not loaded.panel.adj_close.flags.writeable


# Refuse absent, naive, future or pre-close publication without mtime fallback.
@pytest.mark.parametrize(
    "written",
    [
        None,
        "2026-10-02T23:00:00",
        "2026-10-05T15:00:00+00:00",
        "2026-10-02T18:00:00+00:00",
    ],
)
def test_research_publication_is_actual_and_causal(tmp_path, written):
    args = source_case(tmp_path)
    value = json.loads(args[0].read_text())
    value["written"] = written
    args[0].write_text(json.dumps(value))
    with pytest.raises(ValueError, match="publication|timestamp|completion"):
        context.load_context(*args)


# Reject stale metadata, wrong source, missing publication and future fetch instants.
@pytest.mark.parametrize(
    ("key", "value"),
    [
        (b"complete_through", b"2026-10-01"),
        (b"source", b"unknown"),
        (b"source_time", b"2026-10-05T15:00:00+00:00"),
        (b"source_time", b"2026-10-02T23:30:00"),
    ],
)
def test_daily_metadata_requires_published_prior_vintage(tmp_path, key, value):
    args = source_case(tmp_path)
    path = args[1] / "ONE.parquet"
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    metadata = dict(table.schema.metadata)
    metadata[key] = value
    pq.write_table(table.replace_schema_metadata(metadata), path)
    with pytest.raises(ValueError, match="metadata|publication|timestamp"):
        context.load_context(*args)


# Refuse an incomplete cross-section instead of silently reducing the breadth universe.
def test_missing_recorded_name_does_not_change_book_silently(tmp_path):
    args = source_case(tmp_path)
    (args[1] / "TWO.parquet").unlink()
    with pytest.raises(FileNotFoundError):
        context.load_context(*args)


# Preserve the recorded EMA start and refuse a shortened history that would reset it.
def test_missing_ema_origin_is_not_reseeded(tmp_path):
    args = source_case(tmp_path)
    for path in args[1].glob("*.parquet"):
        table = pq.read_table(pa.BufferReader(path.read_bytes()))
        pq.write_table(table.slice(50), path)
    with pytest.raises(ValueError, match="EMA origin"):
        context.load_context(*args)


# Keep missing historical rows explicit while rejecting duplicate or future daily dates.
@pytest.mark.parametrize("defect", ["duplicate", "future"])
def test_daily_chronology_rejects_future_and_duplicate_rows(tmp_path, defect):
    args = source_case(tmp_path)
    path = args[1] / "ONE.parquet"
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    columns = table.to_pydict()
    columns["session_date"][-1] = (
        columns["session_date"][-2]
        if defect == "duplicate"
        else datetime(2026, 10, 5).date()
    )
    pq.write_table(
        pa.table(columns).replace_schema_metadata(table.schema.metadata), path
    )
    with pytest.raises(ValueError, match="ordered"):
        context.load_context(*args)


# Detect a file that changes while another source is being read.
def test_source_hash_guard_covers_whole_context(tmp_path, monkeypatch):
    args = source_case(tmp_path)
    original = context._daily

    # Change the already consumed record after the final daily source has been loaded.
    def mutate(*parameters):
        result = original(*parameters)
        if parameters[1] == "TWO":
            value = json.loads(args[0].read_text())
            value["grades"]["ONE"]["grade"] = "C"
            args[0].write_text(json.dumps(value))
        return result

    monkeypatch.setattr(context, "_daily", mutate)
    with pytest.raises(ValueError, match="Concurrent source"):
        context.load_context(*args)


# Reject weekend capture and stale prior records using exchange-session freshness.
def test_session_freshness_has_no_weekend_or_stale_record_fallback(tmp_path):
    args = source_case(tmp_path)
    with pytest.raises(ValueError, match="reviewed exchange"):
        context.load_context(*args[:2], "2026-10-03", args[-1])
    value = json.loads(args[0].read_text())
    value["session"] = "2026-10-01"
    args[0].write_text(json.dumps(value))
    with pytest.raises(ValueError, match="immediately preceding"):
        context.load_context(*args)


# Missing the same day everywhere must not shorten rolling sessions or reset EMAs.
def test_cross_section_missing_session_remains_nan_and_invalidates_features(tmp_path):
    args = source_case(tmp_path)
    omitted = None
    for path in args[1].glob("*.parquet"):
        table = pq.read_table(pa.BufferReader(path.read_bytes()))
        columns = table.to_pydict()
        omitted = columns["session_date"][-10]
        columns = {key: values[:-10] + values[-9:] for key, values in columns.items()}
        pq.write_table(
            pa.table(columns).replace_schema_metadata(table.schema.metadata), path
        )
    loaded = context.load_context(*args)
    assert len(loaded.panel.dates) == 302
    row = np.flatnonzero(loaded.panel.dates == np.datetime64(omitted, "D"))
    assert len(row) == 1
    assert np.isnan(loaded.panel.adj_close[row]).all()
    _, valid = learned_entry_data._daily_context(
        loaded.panel.adj_close,
        loaded.grades,
        loaded.eligible,
        loaded.panel.tickers.index("SPY"),
    )
    assert not valid[-1].any()


# Refuse published rows on weekends or holidays instead of treating them as sessions.
@pytest.mark.parametrize("extra", ["2026-09-26", "2026-09-07"])
def test_non_session_source_rows_are_rejected(tmp_path, extra):
    args = source_case(tmp_path)
    path = args[1] / "ONE.parquet"
    table = pq.read_table(pa.BufferReader(path.read_bytes()))
    columns = table.to_pydict()
    extra = datetime.fromisoformat(extra).date()
    index = np.searchsorted(columns["session_date"], extra)
    for key, values in columns.items():
        values.insert(index, extra if key == "session_date" else 10.0)
    pq.write_table(
        pa.table(columns).replace_schema_metadata(table.schema.metadata), path
    )
    with pytest.raises(ValueError, match="non-session"):
        context.load_context(*args)


# An unidentified recorded source cannot become a current-live acceptance receipt.
def test_missing_record_source_revision_is_unavailable(tmp_path):
    args = source_case(tmp_path)
    record = json.loads(args[0].read_text())
    record["provenance"]["code_revision"] = "unknown"
    args[0].write_text(json.dumps(record))
    with pytest.raises(ValueError, match="source revision"):
        context.load_context(*args)


# Older EMA origins retain observed source dates without invented calendar coverage.
def test_unreviewed_2015_origin_is_preserved_without_fabricated_sessions(
    tmp_path, monkeypatch
):
    args = source_case(tmp_path)
    years, sessions = calendar.reviewed_sessions()
    monkeypatch.setattr(
        calendar, "reviewed_sessions", lambda: (years - {2015}, sessions)
    )
    older = [datetime(2015, 1, 2).date(), datetime(2015, 1, 6).date()]
    for path in args[1].glob("*.parquet"):
        table = pq.read_table(pa.BufferReader(path.read_bytes()))
        columns = table.to_pydict()
        columns = {
            key: (older if key == "session_date" else [10.0, 11.0]) + values
            for key, values in columns.items()
        }
        pq.write_table(
            pa.table(columns).replace_schema_metadata(table.schema.metadata), path
        )
    record = json.loads(args[0].read_text())
    record["provenance"]["data"]["first_session"] = "2015-01-02"
    args[0].write_text(json.dumps(record))
    loaded = context.load_context(*args)
    days = loaded.panel.dates
    np.testing.assert_array_equal(
        days[days < np.datetime64("2016-01-01")],
        np.asarray(older, dtype="datetime64[D]"),
    )
    assert loaded.provenance["unreviewed_history_years"] == [2015]


# Reviewed older years retain missing exchange sessions rather than hiding source gaps.
def test_reviewed_2015_origin_preserves_missing_exchange_session():
    years, _ = calendar.reviewed_sessions()
    assert 2015 in years
    observed = np.asarray(["2015-01-02", "2015-01-06"], dtype="datetime64[D]")
    dates = context._session_dates(
        observed, observed[0], datetime(2015, 1, 6).date()
    )
    np.testing.assert_array_equal(
        dates,
        np.asarray(["2015-01-02", "2015-01-05", "2015-01-06"], dtype="datetime64[D]"),
    )
