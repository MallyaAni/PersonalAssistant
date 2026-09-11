"""The language layer: index parsing, resumable partials, point-in-time tone."""

from datetime import UTC, date, datetime, timedelta

import numpy as np

from backend.market import language
from backend.market.panel import panel_from_histories
from backend.market.yahoo import DailyBar, TickerHistory

_ROW = (
    '<tr><td>{seq}</td><td>{desc}</td><td><a href="{href}">{name}</a>{extra}</td>'
    "<td>{kind}</td><td>1000</td></tr>"
)
_INDEX = (
    '<table class="tableFile">'
    "<tr><th>Seq</th><th>Description</th><th>Document</th><th>Type</th><th>Size</th></tr>"
    + _ROW.format(
        seq=1,
        desc="8-K",
        href="/ix?doc=/Archives/edgar/data/1/000000000126000001/x-8k.htm",
        name="x-8k.htm",
        extra="&nbsp;&nbsp; iXBRL",
        kind="8-K",
    )
    + _ROW.format(
        seq=2,
        desc="EX-99.1",
        href="/Archives/edgar/data/1/000000000126000001/q2pr.htm",
        name="q2pr.htm",
        extra="",
        kind="EX-99.1",
    )
    + _ROW.format(
        seq=3,
        desc="EX-99.2",
        href="/Archives/edgar/data/1/000000000126000001/cfo.htm",
        name="cfo.htm",
        extra="",
        kind="EX-99.2",
    )
    + "</table>"
)


# A weekday-only flat history.
def _history(ticker: str, first: date, sessions: int) -> TickerHistory:
    bars = []
    day = first
    while len(bars) < sessions:
        if day.weekday() < 5:
            bars.append(DailyBar(day, 100, 100, 100, 100, 100, 1_000_000))
        day += timedelta(days=1)
    return TickerHistory(
        ticker, tuple(bars), (), bars[-1].session_date, datetime(2026, 1, 1, tzinfo=UTC)
    )


def _record(accession: str, reaction: date, guidance: float, demand: float = 0.0):
    return language.ToneRecord(
        accession=accession,
        reaction_date=reaction,
        guidance=guidance,
        demand=demand,
        pricing=0.0,
        capex=0.0,
        supply_constrained=0.0,
        summary="s",
        model="m",
        prompt_version="v",
        truncated=False,
    )


# The press release is the EX-99.1 whatever its file name; an iXBRL viewer
# link is unwrapped to the archive path.
def test_index_page_yields_the_press_release():
    documents = language.parse_index_page(_INDEX)
    assert [d[0] for d in documents] == ["8-K", "EX-99.1", "EX-99.2"]
    assert language.press_release_href(documents) == (
        "https://www.sec.gov/Archives/edgar/data/1/000000000126000001/q2pr.htm"
    )
    assert language.press_release_href(documents[:1]) is None


# Tone is known from the reaction session on, carried forward, with the
# change against the previous release; untouched names are neutral.
def test_tone_features_are_point_in_time():
    first = date(2025, 4, 1)
    panel = panel_from_histories(
        {"AAA": _history("AAA", first, 60), "SPY": _history("SPY", first, 60)},
        "SPY",
        {},
    )
    dates = list(panel.dates.astype("datetime64[D]").astype(object))
    r1 = date(2025, 4, 10)
    r2 = date(2025, 5, 12)  # a Monday
    feats = language.tone_features(
        panel, {"AAA": [_record("b", r2, 0.2, -0.5), _record("a", r1, 0.8, 0.5)]}
    )
    names = language.FEATURE_NAMES
    a = panel.index("AAA")
    t1, t2 = dates.index(r1), dates.index(r2)
    assert feats[t1 - 1, a, names.index("has_tone")] == 0.0
    assert feats[t1, a, names.index("tone_guidance")] == np.float32(0.8)
    assert feats[t1, a, names.index("tone_guidance_change")] == 0.0
    assert feats[t2 - 1, a, names.index("tone_guidance")] == np.float32(0.8)
    assert feats[t2, a, names.index("tone_guidance")] == np.float32(0.2)
    assert abs(feats[t2, a, names.index("tone_guidance_change")] - (0.2 - 0.8)) < 1e-6
    assert abs(feats[-1, a, names.index("tone_demand_change")] - (-1.0)) < 1e-6
    assert feats[:, panel.index("SPY"), :].max() == 0.0
    assert np.isfinite(feats).all()


# A partial file round-trips records and a frame round-trips them in order.
def test_partials_and_frames_round_trip(tmp_path):
    path = language.partial_path(tmp_path, date(2026, 1, 2), "AAA")
    language.append_partial(path, _record("x", date(2025, 4, 10), 0.5))
    language.append_partial(path, _record("y", date(2025, 7, 10), -0.5))
    done = language.read_partial(path)
    assert set(done) == {"x", "y"}
    assert done["y"].guidance == -0.5
    frame = language.tone_frame([done["y"], done["x"]])
    records = language.records_from_frame(frame)
    assert [r.accession for r in records] == ["x", "y"]
    assert language.read_partial(tmp_path / "none.jsonl") == {}


# A release's reported financials survive the partial file and the frame,
# and a frame written before they existed reads back as None.
def test_release_financials_round_trip_and_legacy_frames_read_none(tmp_path):
    rec = language.ToneRecord(
        accession="a",
        reaction_date=date(2025, 6, 10),
        guidance=0.2,
        demand=0.1,
        pricing=0.0,
        capex=0.0,
        supply_constrained=0.0,
        summary="s",
        model="m",
        prompt_version="v",
        truncated=False,
        quarter_end=date(2025, 5, 31),
        revenue_usd_m=200.0,
        eps_usd=2.0,
        net_income_usd_m=40.0,
        gross_margin_pct=55.0,
    )
    path = language.partial_path(tmp_path, date(2026, 1, 2), "AAA")
    language.append_partial(path, rec)
    back = language.read_partial(path)["a"]
    assert back.quarter_end == date(2025, 5, 31)
    assert back.revenue_usd_m == 200.0
    assert back.eps_usd == 2.0
    rebuilt = language.records_from_frame(language.tone_frame([rec]))[0]
    assert rebuilt.net_income_usd_m == 40.0
    assert rebuilt.gross_margin_pct == 55.0
    legacy_columns = {
        k: language.tone_frame([rec])[k]
        for k in (
            "accession",
            "reaction_date",
            "guidance",
            "demand",
            "pricing",
            "capex",
            "supply_constrained",
            "summary",
            "model",
            "prompt_version",
            "truncated",
        )
    }
    legacy = language.records_from_frame(legacy_columns)[0]
    assert legacy.quarter_end is None
    assert legacy.revenue_usd_m is None
