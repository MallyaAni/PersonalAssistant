"""Exercise publication clock edges and filing provenance without any learner."""

import socket
from dataclasses import replace
from datetime import UTC, date, datetime
from unittest.mock import Mock

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import calendar, edgar, language, levels_pit
from backend.market.panel import Panel
from backend.market.yahoo import CorporateAction, TickerHistory

SYMBOL = "SYNTH"
STAMP = datetime(2023, 12, 1, tzinfo=UTC)


# Fail even if a forbidden network or learning attempt is swallowed downstream.
@pytest.fixture(autouse=True)
def forbid_network_and_learning(monkeypatch):
    guards = []
    for owner, name in (
        (socket.socket, "connect"),
        (socket, "getaddrinfo"),
        (mx, "_fit_predict"),
        (mx, "_expected"),
        (mx, "_carried"),
    ):
        guard = Mock(side_effect=AssertionError(f"Forbidden boundary: {name}"))
        monkeypatch.setattr(owner, name, guard)
        guards.append(guard)
    yield
    for guard in guards:
        guard.assert_not_called()


# Give the actual feature functions a fixed two-column daily panel.
def make_panel(days):
    dates = np.asarray(days, dtype="datetime64[D]")
    close = np.full((len(dates), 2), 100.0)
    return Panel(
        dates,
        (SYMBOL, "SPY"),
        close,
        close,
        close,
        close,
        close,
        np.full_like(close, 1000.0),
        {},
        "SPY",
    )


# Serve actual serialized records in memory without accessing data or accounts.
class FrameStore:
    # Retain immutable filing, tone and split fixtures for the actual readers.
    def __init__(self, record, tones=(), actions=(), missing_facts=False):
        self.record = record
        self.tones = tones
        self.actions = actions
        self.missing_facts = missing_facts
        self.reads = []

    # Return real EDGAR or tone frame shapes only for the synthetic company.
    def read_frame(self, kind, ticker, asof=None):
        self.reads.append((kind, ticker, asof))
        if ticker != SYMBOL:
            return None
        if kind == "edgar_facts" and self.missing_facts:
            return None
        events, facts = edgar.record_frames(self.record)
        frames = {
            "edgar_events": events,
            "edgar_facts": facts,
            language.TONE_KIND: language.tone_frame(self.tones),
        }
        return frames[kind], {"cik": "0", "source_time": STAMP.isoformat()}

    # Supply only the declared split actions to the actual valuation reader.
    def read(self, ticker, asof=None):
        if ticker != SYMBOL:
            return None
        return TickerHistory(SYMBOL, (), self.actions, STAMP.date(), STAMP, "fixture")


# Pin both sides of exact clock edges, including holidays, DST and early closes.
@pytest.mark.parametrize(
    ("instant", "before", "after"),
    [
        ("2023-11-01T09:30:00-04:00", "2023-10-31", "2023-11-01"),
        ("2023-11-01T15:59:59-04:00", "2023-10-31", "2023-11-01"),
        ("2023-11-01T16:00:00-04:00", "2023-10-31", "2023-11-02"),
        ("2023-11-01T16:00:00.000001-04:00", "2023-11-01", "2023-11-02"),
        ("2023-11-24T12:59:59-05:00", "2023-11-22", "2023-11-24"),
        ("2023-11-24T13:00:00-05:00", "2023-11-22", "2023-11-27"),
        ("2023-11-24T14:00:00-05:00", "2023-11-24", "2023-11-27"),
        ("2023-11-25T12:00:00-05:00", "2023-11-24", "2023-11-27"),
        ("2023-11-23T12:00:00-05:00", "2023-11-22", "2023-11-24"),
        ("2023-11-03T13:30:00+00:00", "2023-11-02", "2023-11-03"),
        ("2023-11-06T14:30:00+00:00", "2023-11-03", "2023-11-06"),
    ],
)
def test_publication_session_clock_boundaries(instant, before, after):
    timestamp = datetime.fromisoformat(instant)
    earlier = calendar.publication_session(timestamp, before=True)
    later = calendar.publication_session(timestamp, before=False)
    assert earlier == date.fromisoformat(before)
    assert later == date.fromisoformat(after)
    assert (
        datetime.combine(earlier, calendar.session_close(earlier), calendar.NEW_YORK)
        < timestamp
    )
    assert (
        datetime.combine(later, calendar.session_close(later), calendar.NEW_YORK)
        > timestamp
    )


# An unsupported year or naive timestamp must not acquire an inferred clock.
@pytest.mark.parametrize(
    "timestamp",
    [datetime(2039, 1, 10, 11, tzinfo=UTC), datetime(2023, 11, 1, 11)],
)
@pytest.mark.parametrize("before", [True, False])
def test_publication_session_rejects_unreviewed_or_naive_time(timestamp, before):
    assert calendar.publication_session(timestamp, before=before) is None


# An early-close release cannot appear in event evidence before it was accepted.
def test_strict_event_features_observe_early_close_without_changing_default():
    days = np.array(
        ["2023-11-22", "2023-11-24", "2023-11-27", "2023-11-28"],
        dtype="datetime64[D]",
    )
    event = edgar.EarningsEvent(
        datetime.fromisoformat("2023-11-24T14:00:00-05:00"),
        date(2023, 11, 24),
        "early-close",
        "2.02",
    )
    residual = np.array([0.01, 0.02, 0.03, 0.04])
    since, reaction = edgar._event_series(
        (event,), days, residual, strict_publication=True
    )
    legacy = edgar._event_series((event,), days, residual)
    explicit = edgar._event_series((event,), days, residual, strict_publication=False)
    np.testing.assert_array_equal(since, [edgar.NO_EVENT_SESSIONS] * 2 + [0, 1])
    np.testing.assert_allclose(reaction, [0, 0, 0, 0.07])
    assert legacy[0][1] == 0
    assert legacy[1][2] == pytest.approx(0.05)
    for actual, expected in zip(legacy, explicit, strict=True):
        np.testing.assert_array_equal(actual, expected)


# Keep equal-valued reports distinct so their source share bases can reset.
def share_record():
    facts = (
        edgar.QuarterFact(
            "shares", date(2023, 1, 1), date(2023, 3, 31), 10.0, date(2023, 5, 31)
        ),
        edgar.QuarterFact(
            "shares", date(2023, 4, 1), date(2023, 6, 30), 10.0, date(2023, 8, 15)
        ),
    )
    return edgar.CompanyRecord(SYMBOL, 0, (), facts, STAMP)


# The strict first-visible date must not replace either report's actual filing date.
def test_strict_known_quarters_preserves_source_dates_for_equal_values():
    days = np.array(
        ["2023-05-31", "2023-06-01", "2023-06-02", "2023-08-15", "2023-08-16"],
        dtype="datetime64[D]",
    )
    record = share_record()
    strict, visible, basis = edgar._known_quarters(
        record.facts, "shares", days, strict_before_session=True
    )
    np.testing.assert_array_equal(strict[0], [np.nan, 10, 10, 10, 10])
    np.testing.assert_array_equal(visible, [np.nan, 1, 1, 1, 4])
    np.testing.assert_array_equal(
        basis,
        np.array(
            ["NaT", "2023-05-31", "2023-05-31", "2023-05-31", "2023-08-15"],
            dtype="datetime64[D]",
        ),
    )
    legacy, legacy_visible = edgar._known_series(record.facts, "shares", days)
    explicit, explicit_visible = edgar._known_series(
        record.facts, "shares", days, strict_before_session=False
    )
    np.testing.assert_array_equal(legacy[0], [10, 10, 10, 10, 10])
    np.testing.assert_array_equal(legacy[0], explicit[0])
    np.testing.assert_array_equal(legacy_visible, explicit_visible)


# A split on the first usable day applies to the original filing basis, not visibility.
def test_split_on_first_usable_day_preserves_legacy_default():
    days = np.array(["2023-06-01", "2023-06-02"], dtype="datetime64[D]")
    shares = np.array([10.0, 10.0])
    splits = [(date(2023, 6, 1), 2.0)]
    basis = np.array(["2023-05-31", "2023-05-31"], dtype="datetime64[D]")
    strict = levels_pit.split_adjusted_shares(shares, days, splits, basis_dates=basis)
    legacy = levels_pit.split_adjusted_shares(shares, days, splits)
    np.testing.assert_array_equal(strict, [20, 20])
    np.testing.assert_array_equal(legacy, [10, 10])
    np.testing.assert_array_equal(shares, [10, 10])


# Real valuation loading must propagate source bases and reset on an equal new report.
def test_strict_valuation_applies_split_and_resets_equal_new_report_basis():
    panel = make_panel(
        ["2023-05-31", "2023-06-01", "2023-06-02", "2023-08-15", "2023-08-16"]
    )
    store = FrameStore(
        share_record(), actions=(CorporateAction(date(2023, 6, 1), "split", 2.0),)
    )
    strict = levels_pit.point_in_time_levels(store, panel, strict_publication=True)
    legacy = levels_pit.point_in_time_levels(store, panel)
    explicit = levels_pit.point_in_time_levels(store, panel, strict_publication=False)
    np.testing.assert_array_equal(strict["shares"][:, 0], [np.nan, 20, 20, 20, 10])
    np.testing.assert_array_equal(legacy["shares"][:, 0], [10, 20, 20, 20, 20])
    for field in legacy:
        np.testing.assert_array_equal(legacy[field], explicit[field])
    assert store.record.facts == share_record().facts


# Conflicting tone dating cannot outrank its matching SEC acceptance timestamp.
@pytest.mark.parametrize("with_record", [True, False])
def test_tone_before_session_clamps_inconsistent_recorded_date(with_record):
    panel = make_panel(["2023-10-30", "2023-10-31", "2023-11-01", "2023-11-02"])
    timestamp = datetime(2023, 11, 1, 15, tzinfo=UTC)
    event = edgar.EarningsEvent(timestamp, date(2023, 11, 1), "matched", "2.02")
    record = edgar.CompanyRecord(SYMBOL, 0, (event,), (), STAMP)
    tone = language.ToneRecord(
        "matched",
        date(2023, 10, 30),
        0.75,
        0.5,
        0.25,
        0.0,
        0.0,
        "Synthetic fixture",
        "fixture",
        "fixture",
        False,
    )
    store = FrameStore(record, (tone,), missing_facts=not with_record)
    cutoff = date(2023, 11, 15)
    records = {SYMBOL: record} if with_record else {}
    strict = mx._tone_before_session(store, panel, records, cutoff)
    legacy = language.tone_features(panel, {SYMBOL: (tone,)})
    explicit = language.tone_features(
        panel, {SYMBOL: (tone,)}, strict_before_session=False
    )
    assert strict is not None
    assert not strict[:3].any()
    index = language.FEATURE_NAMES.index("tone_guidance")
    assert strict[3, 0, index] == 0.75
    np.testing.assert_array_equal(legacy[:, 0, index], [0.75] * 4)
    np.testing.assert_array_equal(legacy, explicit)
    assert tone.reaction_date == date(2023, 10, 30)
    assert record.events[0].accepted == timestamp
    assert all(request[2] == cutoff for request in store.reads)
    if not with_record:
        assert ("edgar_events", SYMBOL, cutoff) in store.reads
        assert store.read_frame("edgar_facts", SYMBOL, cutoff) is None


# Produce one real mapped release with different causal feature and return indices.
def dataset_inputs():
    candidates = np.arange("2022-01-01", "2023-12-01", dtype="datetime64[D]")
    _, sessions = calendar.reviewed_sessions()
    panel = make_panel(candidates[np.is_busday(candidates, busdaycal=sessions)])
    dates = panel.dates.astype(object).tolist()
    timestamp = datetime(2023, 11, 1, 15, tzinfo=UTC)
    event = edgar.EarningsEvent(timestamp, date(2023, 11, 1), "intraday", "2.02")
    record = edgar.CompanyRecord(SYMBOL, 0, (event,), (), STAMP)
    windows = mx._release_windows(dates, record)
    quarters = {
        SYMBOL: [
            (date(2022, 9, 30), 100.0, date(2022, 11, 10)),
            (date(2023, 9, 30), 120.0, date(2023, 11, 10)),
        ]
    }
    feats = np.repeat(np.arange(len(dates))[:, None, None], 2, axis=1)
    feats = np.repeat(feats, len(mx.NAMES), axis=2).astype(float)
    return panel, dates, quarters, {SYMBOL: windows}, feats


# Return metadata must retain the actual feature date rather than an r-minus-one guess.
def test_dataset_retains_distinct_feature_and_reaction_metadata():
    args = dataset_inputs()
    window = args[3][SYMBOL][0]
    assert isinstance(window, mx.ReleaseWindow)
    assert args[1][window.feature] == date(2023, 10, 31)
    assert args[1][window.reaction] == date(2023, 11, 2)
    x, y, meta = mx._dataset(*args)
    assert len(meta) == 1
    assert meta[0][1] == window.reaction
    assert meta[0][4] == window.feature != window.reaction - 1
    assert meta[0][5:] == (window.accepted, "intraday")
    assert meta[0][3] == date(2023, 11, 10)
    np.testing.assert_array_equal(x[0], args[4][window.feature, 0])
    np.testing.assert_allclose(y, [0.2])


# An old integer-only caller must fail closed rather than silently restoring leakage.
def test_dataset_rejects_bare_reaction_indices():
    args = dataset_inputs()
    args[3][SYMBOL] = [args[3][SYMBOL][0].reaction]
    with pytest.raises(ValueError, match="timestamp-bounded release windows"):
        mx._dataset(*args)


# A typed window cannot smuggle a feature index inconsistent with its timestamp.
@pytest.mark.parametrize("offset", [-1, 1])
def test_pre_report_index_rejects_window_timestamp_disagreement(offset):
    args = dataset_inputs()
    original = args[3][SYMBOL][0]
    wrong = replace(original, feature=original.feature + offset)
    filed = args[2][SYMBOL][-1][2]
    assert mx._pre_report_index(args[1], original, filed) == original.feature
    assert mx._pre_report_index(args[1], wrong, filed) is None
    args[3][SYMBOL] = [wrong]
    assert len(mx._dataset(*args)[1]) == 0


# An earlier target filing moves the effective feature index without redating the event.
def test_dataset_keeps_earlier_target_filing_out_of_features():
    args = dataset_inputs()
    window = args[3][SYMBOL][0]
    args[2][SYMBOL][-1] = (date(2023, 9, 30), 120.0, date(2023, 10, 27))
    x, y, meta = mx._dataset(*args)
    assert len(y) == 1
    assert args[1][meta[0][4]] == date(2023, 10, 26)
    assert meta[0][4] < window.feature
    assert meta[0][1] == window.reaction
    assert meta[0][5:] == (window.accepted, window.accession)
    np.testing.assert_array_equal(x[0], args[4][meta[0][4], 0])
