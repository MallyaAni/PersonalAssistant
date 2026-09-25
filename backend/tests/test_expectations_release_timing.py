"""Keep target reports out of actual pre-report expectations feature rows.

These are synthetic, publication-boundary regressions, not fitted predictions.
The source bound is SEC acceptance or the first-filed day, whichever is earlier;
it does not prove when an issuer first published a press release elsewhere.
"""

import hashlib
import json
from datetime import UTC, date, datetime, time, timedelta

import numpy as np
import pytest

from backend.cli import market_expectations as mx
from backend.market import calendar, edgar, language
from backend.market.panel import build_panel
from backend.market.store import MarketStore
from backend.market.yahoo import DailyBar, TickerHistory
from backend.tests.test_expectations_feature_cutoff import tone_loader  # noqa: F401

TARGET = "SYNTH"
TARGET_END = date(2023, 9, 30)
VINTAGE = date(2023, 12, 15)
QUARTERS = (
    date(2021, 12, 31),
    date(2022, 3, 31),
    date(2022, 6, 30),
    date(2022, 9, 30),
    date(2022, 12, 31),
    date(2023, 3, 31),
    date(2023, 6, 30),
    TARGET_END,
)


# Refuse the fitting boundary while allowing every actual data/feature function.
@pytest.fixture(autouse=True)
def no_fit(monkeypatch):
    # Any fitted result would exceed this test's deterministic publication scope.
    def forbidden(*args, **kwargs):
        raise AssertionError("No fitting is permitted in publication acceptance")

    monkeypatch.setattr(mx, "_fit_predict", forbidden)


# Use actual reviewed exchange dates rather than invented weekday-only histories.
def exchange_dates():
    _, sessions = calendar.reviewed_sessions()
    dates = np.arange("2022-01-01", "2023-12-09", dtype="datetime64[D]")
    return dates[np.is_busday(dates, busdaycal=sessions)].astype(object).tolist()


# Construct aware SEC acceptance instants in the exchange's own timezone.
def accepted(day, hour):
    return datetime.combine(day, time(hour), calendar.NEW_YORK).astimezone(UTC)


# Keep distinct dated price series fixed across every filing/tone perturbation.
def write_prices(store):
    days = exchange_dates()
    for column, symbol in enumerate((TARGET, "PEER1", "PEER2", "SPY")):
        bars = []
        for index, day in enumerate(days):
            close = (20 + column * 15) * np.exp(
                index * 0.0005 + 0.01 * np.sin(index * 0.17 + column)
            )
            bars.append(
                DailyBar(
                    day, close * 0.99, close * 1.01, close * 0.98, close, close, 1000
                )
            )
        history = TickerHistory(
            symbol,
            tuple(bars),
            (),
            days[-1],
            datetime(2023, 12, 15, 23, tzinfo=UTC),
            "synthetic-release-timing",
        )
        assert store.write(VINTAGE, history)


# Build ordinary prior reports plus the one target report whose facts may change.
def company_record(symbol, release_at, target_filed, changed=False, same_day_fact=None):
    events, facts = [], []
    for index, quarter in enumerate(QUARTERS):
        is_target = symbol == TARGET and quarter == TARGET_END
        filed = target_filed if is_target else quarter + timedelta(days=45)
        event_at = release_at if is_target else accepted(filed, 8)
        events.append(
            edgar.EarningsEvent(
                event_at,
                event_at.astimezone(calendar.NEW_YORK).date(),
                f"{symbol}-{quarter}",
                "2.02",
            )
        )
        values = {
            "revenue": 100.0 + index * 10,
            "eps": 1.0 + index * 0.1,
            "net_income": 10.0 + index,
            "gross_profit": 40.0 + index * 4,
            "equity": 1000.0 + index * 10,
            "shares": 10.0,
        }
        if is_target and changed:
            values.update(
                revenue=400.0,
                eps=6.0,
                net_income=120.0,
                gross_profit=250.0,
                shares=30.0,
            )
        for name, value in values.items():
            fact_filed = filed
            if (
                symbol == TARGET
                and quarter == date(2023, 6, 30)
                and name == "gross_profit"
                and same_day_fact is not None
            ):
                fact_filed, value = same_day_fact
            facts.append(
                edgar.QuarterFact(
                    name, quarter - timedelta(days=89), quarter, value, fact_filed
                )
            )
    return edgar.CompanyRecord(
        symbol, 0, tuple(events), tuple(facts), datetime(2023, 12, 15, 23, tzinfo=UTC)
    )


# Write immutable real frames, preserving parser and availability behavior end to end.
def make_store(
    root, release_at, target_filed, changed=False, same_day_fact=None, extra_tone=None
):
    store = MarketStore(root)
    write_prices(store)
    for symbol in (TARGET, "PEER1", "PEER2"):
        record = company_record(
            symbol, release_at, target_filed, changed, same_day_fact
        )
        events, facts = edgar.record_frames(record)
        metadata = {"cik": "0", "source_time": record.source_time.isoformat()}
        assert store.write_frame("edgar_events", VINTAGE, symbol, events, metadata)
        assert store.write_frame("edgar_facts", VINTAGE, symbol, facts, metadata)
        tones = [
            language.ToneRecord(
                event.accession,
                event.reaction_date,
                -0.75
                if changed and symbol == TARGET and index == len(QUARTERS) - 1
                else 0.25,
                0.5,
                0.1,
                0.0,
                0.0,
                "Synthetic; no model call",
                "fixture",
                "fixture",
                False,
            )
            for index, event in enumerate(record.events)
        ]
        if symbol == TARGET and extra_tone is not None:
            day, guidance = extra_tone
            tones.append(
                language.ToneRecord(
                    "unrelated-date-only-tone",
                    day,
                    guidance,
                    0.5,
                    0.1,
                    0.0,
                    0.0,
                    "Synthetic; no model call",
                    "fixture",
                    "fixture",
                    False,
                )
            )
        assert store.write_frame(
            language.TONE_KIND, VINTAGE, symbol, language.tone_frame(tones)
        )
    return store


# Fingerprint persisted inputs so feature construction cannot silently rewrite them.
def stored_hashes(store):
    return {
        str(path.relative_to(store.root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in store.root.rglob("*.parquet")
    }


# Build the real dataset and select its target report through the returned metadata.
def target_row(store):
    before = stored_hashes(store)
    panel = build_panel(store, (TARGET, "PEER1", "PEER2"), "SPY", {}, VINTAGE)
    dates = panel.dates.astype(object).tolist()
    records, quarters, timing = mx._records(store, panel, dates, VINTAGE)
    fund, fidx, tone, tidx, _beta, mom, ratios = mx._features(
        store, panel, records, VINTAGE
    )
    feats, _implied = mx._block(
        panel,
        {name: "Synthetic" for name in (TARGET, "PEER1", "PEER2")},
        fund,
        fidx,
        tone,
        tidx,
        mom,
        ratios,
    )
    x, y, meta = mx._dataset(panel, dates, quarters, timing, feats)
    selected = [
        index
        for index, row in enumerate(meta)
        if row[0] == panel.index(TARGET) and dates[row[1]] > TARGET_END
    ]
    assert len(selected) == 1
    index = selected[0]
    assert meta[index][1] >= 131
    assert stored_hashes(store) == before
    return x[index], y[index], meta[index], panel


# Record numerical evidence even when the central noninterference assertion fails.
def compare_target_rows(first, second, expected_price_day, record_property):
    x, y, meta, panel = first
    changed_x, changed_y, changed_meta, _ = second
    changed = [
        name
        for name, a, b in zip(mx.NAMES, x, changed_x, strict=True)
        if not (a == b or np.isnan(a) and np.isnan(b))
    ]
    record_property("changed_feature_names", json.dumps(changed))
    record_property("target_y_before_after", json.dumps([float(y), float(changed_y)]))
    record_property("return_index", str(meta[1]))
    record_property("expected_price_day", expected_price_day.isoformat())
    assert y != changed_y
    assert meta[0:2] == changed_meta[0:2]
    np.testing.assert_array_equal(x, changed_x)
    price_row = panel.dates.astype(object).tolist().index(expected_price_day)
    expected_cap = panel.close[price_row, panel.index(TARGET)] * 10.0
    assert x[mx.NAMES.index("log_cap")] == pytest.approx(
        np.log(expected_cap), abs=1e-12
    )
    assert np.isfinite(x[mx.NAMES.index("ps_implied_growth")])


# A report's own outcome and tone must not enter the features predicting that outcome.
@pytest.mark.parametrize(
    ("release_day", "hour", "filed", "price_day"),
    [
        (date(2023, 11, 15), 8, date(2023, 11, 15), date(2023, 11, 14)),
        (date(2023, 11, 15), 11, date(2023, 11, 15), date(2023, 11, 14)),
        (date(2023, 11, 15), 17, date(2023, 11, 15), date(2023, 11, 14)),
        (date(2023, 11, 24), 14, date(2023, 11, 24), date(2023, 11, 22)),
        (date(2023, 11, 18), 11, date(2023, 11, 18), date(2023, 11, 17)),
        (date(2023, 11, 15), 17, date(2023, 11, 16), date(2023, 11, 15)),
        (date(2023, 11, 17), 8, date(2023, 11, 15), date(2023, 11, 14)),
    ],
    ids=[
        "preopen",
        "intraday",
        "afterclose-same-filed-day",
        "early-close",
        "weekend",
        "afterclose-later-filing",
        "delayed-associated-event",
    ],
)
def test_target_release_cannot_change_its_own_features(
    tmp_path, record_property, release_day, hour, filed, price_day
):
    release_at = accepted(release_day, hour)
    first = target_row(make_store(tmp_path / "before", release_at, filed))
    second = target_row(
        make_store(tmp_path / "changed", release_at, filed, changed=True)
    )
    compare_target_rows(first, second, price_day, record_property)


# Same-day price may be known before an after-close release, unlike date-only data.
@pytest.mark.parametrize("component", ["fact", "tone"])
def test_afterclose_price_day_does_not_admit_unordered_same_day_information(
    tmp_path, record_property, component
):
    release_day = date(2023, 11, 15)
    release_at = accepted(release_day, 17)
    filed = date(2023, 11, 16)
    args = (
        (
            {"same_day_fact": (release_day, 60.0)},
            {"same_day_fact": (release_day, 240.0)},
        )
        if component == "fact"
        else (
            {"extra_tone": (release_day, 0.1)},
            {"extra_tone": (release_day, 0.9)},
        )
    )
    x, y, meta, panel = target_row(
        make_store(tmp_path / "before", release_at, filed, **args[0])
    )
    other, other_y, other_meta, _ = target_row(
        make_store(tmp_path / "changed", release_at, filed, **args[1])
    )
    record_property("date_only_component", component)
    record_property("feature_before", json.dumps(x.tolist()))
    record_property("feature_after", json.dumps(other.tolist()))
    assert y == other_y
    assert meta[0:2] == other_meta[0:2]
    np.testing.assert_array_equal(x, other)
    index = panel.dates.astype(object).tolist().index(release_day)
    expected = np.log(panel.close[index, panel.index(TARGET)] * 10.0)
    assert x[mx.NAMES.index("log_cap")] == pytest.approx(expected, abs=1e-12)
