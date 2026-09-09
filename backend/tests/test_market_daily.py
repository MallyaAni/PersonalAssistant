"""The daily pipeline: what it refreshes, in what order, and what it records."""

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

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


# The record's curve block: the rules walked forward against SPY and QQQ,
# from the simulation the nightly run already has, plus the headline stats.
def test_curve_block_writes_the_rules_against_the_market(monkeypatch):
    from backend.agents.trading.desk import scorecard
    from backend.agents.trading.desk import simulate as sim_module

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 1.1 / 1.05 - 1.0]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, use_exits=False: sim)
    monkeypatch.setattr(
        scorecard,
        "index_returns",
        lambda store, ticker, dates: np.array([0.0, 0.0, 0.01, 0.0]),
    )
    block = market_daily.curve_block(report, None)
    assert block is not None
    assert block["rules"] == pytest.approx([0.0, 0.05, 0.1])
    assert len(block["spy"]) == 3
    assert len(block["qqq"]) == 4  # one entry per return given
    assert block["stats"]["total"] == pytest.approx(0.1)
    assert block["asof"] == "2026-09-03"


# The benchmark starts at zero like the rules, and its first return is the
# first one the strategy participates in - not the return into the base date,
# which the strategy never held. The off-by-one is visible only when the sim
# starts mid-panel, so this sim does.
def test_curve_benchmark_is_aligned_to_the_strategy_start(monkeypatch):
    from backend.agents.trading.desk import grading, regime, scorecard
    from backend.agents.trading.desk import simulate as sim_module
    from backend.agents.trading.desk.desk import DeskReport
    from backend.agents.trading.desk.opinions import Opinion
    from backend.agents.trading.desk.risk import Sized
    from backend.market.panel import Panel
    from backend.market.sizing import Position
    from backend.market.universe import AI_COMPUTE

    t, n = 4, 2
    close = np.full((t, n + 1), 100.0)
    # The benchmark falls 10% into the base date, then rises 10% a day: the
    # fall must not appear in the curve, and the first rise must.
    close[:, 2] = [100.0, 90.0, 99.0, 108.9]
    dates = np.array(
        [date(2026, 9, 1) + timedelta(days=i) for i in range(t)],
        dtype="datetime64[D]",
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
    report = DeskReport(
        panel,
        {"SNDK": "ai", "IREN": "ai"},
        {},
        view,
        graded,
        grades.astype(float),
        book,
    )
    sim = sim_module.SimResult(
        dates=panel.dates[1:],
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, use_exits=False: sim)
    monkeypatch.setattr(
        scorecard,
        "index_returns",
        lambda store, ticker, dates: np.array([0.0, 0.1, 0.1]),
    )
    block = market_daily.curve_block(report, None)
    assert block is not None
    assert block["rules"] == pytest.approx([0.0, 0.05, 0.1])
    # The benchmark curve starts at 0 (it did not earn the -10% into the base
    # date) and its cumulative return is the two +10% periods the strategy held.
    assert block["spy"] == pytest.approx([0.0, 0.1, 0.21])
    assert block["qqq"] == pytest.approx([0.0, 0.1, 0.21])


# The paper account's live equity history becomes the overlay for the same
# chart, and an empty history is nothing rather than an error.
def test_paper_curve_block_reads_the_live_history(tmp_path):
    state = {
        "sessions_seen": ["2026-09-04"],
        "last_rebalance": None,
        "sessions_since_rebalance": 0,
        "opened": {},
        "start_equity": 100000.0,
        "history": [
            {
                "session": "2026-09-04",
                "equity": 100000.0,
                "pl_pct": 0.0,
                "pl": 0.0,
            }
        ],
        "pending": [],
        "unconfirmed_rebalance": None,
        "previous_rebalance": None,
    }
    root = tmp_path / "paper"
    root.mkdir()
    (root / "state.json").write_text(json.dumps(state), encoding="utf-8")
    block = market_daily.paper_curve_block(tmp_path)
    assert block is not None
    assert block["sessions"] == ["2026-09-04"]
    assert block["equity"] == [100000.0]
    assert market_daily.paper_curve_block(tmp_path / "empty") is None


# The drill-down files: one JSON per book name with the session rows and
# the name's own backtest, so the page reads a single name without running
# the desk again.
def test_write_history_writes_one_file_per_book_name(tmp_path):
    report = _report()
    count = market_daily.write_history(MarketStore(tmp_path), report)
    assert count == 2  # SNDK and IREN, the book sides
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["ticker"] == "SNDK"
    assert payload["horizon"] == 20
    assert payload["rows"]
    row = payload["rows"][0]
    assert row["date"]
    assert row["grade"] == "A+"
    assert "forward" in row
    assert "forward_residual" in row
    assert "earnings" in row
    assert payload["backtest"]["ticker"] == "SNDK"


# A curve that cannot be drawn is a missing block, never a lost record.
def test_curves_never_raise(monkeypatch, tmp_path):
    from backend.agents.trading.desk import paper

    def boom(root):
        raise OSError("the history file is unreadable")

    monkeypatch.setattr(paper, "load_state", boom)
    monkeypatch.setattr(market_daily, "curve_block", lambda report, store: {"ok": 1})
    out = market_daily.curves(None, None, tmp_path)
    assert out == {"backtest": {"ok": 1}, "paper": None}

    def boom2(report, store):
        raise RuntimeError("no simulation")

    monkeypatch.setattr(market_daily, "curve_block", boom2)
    monkeypatch.setattr(paper, "load_state", lambda root: paper.PaperState())
    out = market_daily.curves(None, None, tmp_path)
    assert out == {"backtest": None, "paper": None}
