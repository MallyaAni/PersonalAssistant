"""The daily pipeline: what it refreshes, in what order, and what it records."""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from backend.agents.trading.desk import grading, regime
from backend.agents.trading.desk.desk import DeskReport
from backend.agents.trading.desk.opinions import Opinion
from backend.agents.trading.desk.risk import Sized
from backend.cli import market_daily, market_tone
from backend.market import language
from backend.market.panel import Panel
from backend.market.sizing import Position
from backend.market.store import MarketStore
from backend.market.universe import AI_COMPUTE, MARKET_BENCHMARK


@dataclass
class _BarsReport:
    stored_count: int = 3
    failed_tickers: list = field(default_factory=list)


# The refresh pulls bars for the book plus the benchmark and the macro
# series, then filings for the book, then the tone, in that order; a tone
# runtime that is away does not stop the desk.
def test_refresh_order_and_tickers(tmp_path):
    calls = []

    def bars(store, tickers, asof):
        calls.append(("bars", tuple(tickers), asof))
        return _BarsReport()

    def filings(store, tickers, asof):
        calls.append(("filings", tuple(tickers), asof))

    def tone(store, tickers, asof, **kw):
        calls.append(("tone", tuple(tickers), asof))
        raise ConnectionError("runtime away")

    store = MarketStore(tmp_path)
    market_daily.refresh(store, date(2026, 9, 6), bars=bars, filings=filings, tone=tone)
    assert [c[0] for c in calls] == ["bars", "filings", "tone"]
    bar_tickers = calls[0][1]
    assert MARKET_BENCHMARK in bar_tickers
    assert "^VIX" in bar_tickers
    assert "SNDK" in bar_tickers
    assert "SPY" not in calls[1][1]
    assert calls[1][1] == calls[2][1]
    assert "DUK" not in calls[1][1]


def _report() -> DeskReport:
    t, n = 3, 2
    close = np.full((t, n + 1), 100.0)
    dates = np.array(
        [date(2026, 9, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    panel = Panel(
        dates=dates,
        tickers=("SNDK", "IREN", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={"SNDK": (AI_COMPUTE,), "IREN": (AI_COMPUTE,)},
        benchmark="SPY",
    )
    grades = np.zeros((t, n + 1), dtype=int)
    grades[:, 0] = grading.ORDINAL["A+"]
    stances = {"fundamental": np.array([[1, -1, 0]] * t)}
    graded = grading.Graded(grades, np.array([[3.0, -2.0, 0.0]] * t), stances)
    state = regime.RegimeState(
        -0.06,
        0.19,
        0.0,
        -0.52,
        -3.6,
        4.8,
        "software",
        -0.217,
        -0.223,
        0.5,
        1.0,
        ("participation below its two-year median",),
    )
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, n + 1), np.nan))
    )
    book = [
        Sized(
            Position(
                "SNDK", 0.08, 1.0, 1.37, (AI_COMPUTE,), "inverse-volatility weight"
            ),
            "A+",
            1.0,
            1.0,
        )
    ]
    return DeskReport(
        panel,
        {"SNDK": "ai", "IREN": "ai"},
        {},
        view,
        graded,
        grades.astype(float),
        book,
    )


# The record carries the session, the regime, every grade and the book, and
# is written under the store as JSON.
def test_record_and_save(tmp_path):
    data = market_daily.record(_report(), {"SNDK": {"stance": "own", "verdict": "v"}})
    assert data["session"] == "2026-09-03"
    assert data["grades"]["SNDK"]["grade"] == "A+"
    assert data["grades"]["IREN"]["grade"] == "C"
    assert "SPY" not in data["grades"]
    assert data["regime"]["flags"] == ["participation below its two-year median"]
    assert data["book"][0]["ticker"] == "SNDK"
    assert data["book"][0]["weight"] == 0.08
    assert data["briefs"]["SNDK"]["stance"] == "own"
    assert data["paper"] is None
    with_paper = market_daily.record(_report(), None, {"equity": 100.0})
    assert with_paper["paper"]["equity"] == 100.0
    path = market_daily.save(Path(tmp_path), data)
    assert path == Path(tmp_path) / "desk" / "asof=2026-09-03" / "desk.json"
    assert json.loads(path.read_text(encoding="utf-8"))["session"] == "2026-09-03"


# Pruning drops old bar and filing partitions but never the newest one of
# a layer, never tone, and never the desk records.
def test_prune_keeps_newest_tone_and_records(tmp_path):
    for kind, stamps in (
        ("bars", ("2026-07-01", "2026-08-30", "2026-09-06")),
        ("edgar_tone", ("2026-07-01",)),
        ("desk", ("2026-07-01",)),
        ("edgar_facts", ("2026-06-01",)),
    ):
        for stamp in stamps:
            (tmp_path / kind / f"asof={stamp}").mkdir(parents=True)
    removed = market_daily.prune(tmp_path, date(2026, 9, 6), 30)
    assert [p.name for p in removed] == ["asof=2026-07-01"]
    assert sorted(p.name for p in (tmp_path / "bars").iterdir()) == [
        "asof=2026-08-30",
        "asof=2026-09-06",
    ]
    assert (tmp_path / "edgar_tone" / "asof=2026-07-01").exists()
    assert (tmp_path / "desk" / "asof=2026-07-01").exists()
    assert (tmp_path / "edgar_facts" / "asof=2026-06-01").exists()  # the newest
    assert market_daily.prune(tmp_path, date(2026, 9, 6), 0) == []


# A new day's tone refresh starts from the scores already stored, so only
# unseen releases are scored; a different prompt version starts over.
def test_prior_tone_records_carry_forward(tmp_path):
    store = MarketStore(tmp_path)
    record = language.ToneRecord(
        accession="0001-25-1",
        reaction_date=date(2026, 8, 7),
        guidance=1.0,
        demand=1.0,
        pricing=0.0,
        capex=0.0,
        supply_constrained=0.0,
        summary="raised",
        model="m",
        prompt_version=market_tone.PROMPT_VERSION,
        truncated=False,
    )
    meta = {"cik": "1", "model": "m", "prompt_version": market_tone.PROMPT_VERSION}
    store.write_frame(
        language.TONE_KIND,
        date(2026, 9, 5),
        "SNDK",
        language.tone_frame([record]),
        meta,
    )
    carried = market_tone.prior_records(store, "SNDK", date(2026, 9, 6))
    assert list(carried) == ["0001-25-1"]
    assert carried["0001-25-1"].guidance == 1.0
    # The same day's partition is not "prior".
    assert market_tone.prior_records(store, "SNDK", date(2026, 9, 5)) == {}
    stale = dict(meta, prompt_version="release_tone/0")
    store.write_frame(
        language.TONE_KIND,
        date(2026, 9, 5),
        "IREN",
        language.tone_frame([record]),
        stale,
    )
    assert market_tone.prior_records(store, "IREN", date(2026, 9, 6)) == {}
