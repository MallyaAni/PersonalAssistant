"""The daily pipeline: what it refreshes, in what order, and what it records."""

import json
import sys
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

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


# Refresh the broad universe plus benchmarks and macro, then filings for
# every stock member and tone for the book, in that order; a tone runtime
# that is away does not stop the desk.
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

    def versions(store, tickers, asof):
        calls.append(("versions", tuple(tickers), asof))
        raise ConnectionError("EDGAR away")

    store = MarketStore(tmp_path)
    market_daily.refresh(
        store,
        date(2026, 9, 6),
        bars=bars,
        filings=filings,
        tone=tone,
        versions=versions,
    )
    # The filing versions follow the filings and cover the book; their
    # failure is named and does not stop the tone step or the desk.
    assert [c[0] for c in calls] == ["bars", "filings", "versions", "tone"]
    assert set(calls[2][1]) == set(market_daily.book_tickers())
    calls = [c for c in calls if c[0] != "versions"]
    bar_tickers = calls[0][1]
    assert MARKET_BENCHMARK in bar_tickers
    assert "QQQ" in bar_tickers  # a displayed benchmark is refreshed, not flat
    assert "^VIX" in bar_tickers
    assert "SNDK" in bar_tickers
    assert "SPY" not in calls[1][1]
    assert "DUK" in calls[1][1]
    assert set(calls[1][1]) == set(market_daily.research_tickers())
    assert set(market_daily.book_tickers()) < set(calls[1][1])
    # Tone is the book's alone: a release is fetched and read one at a time,
    # and the research universe's backlog ran past the next session.
    assert set(calls[2][1]) == set(market_daily.book_tickers())
    assert "DUK" not in calls[2][1]


# The frozen ML observer runs once bars and filings are on disk and before
# the release-tone scoring, so a scorer that blocks for hours (or is away)
# cannot stop a ready observation; and it runs exactly once per refresh.
def test_ml_observation_runs_before_tone_and_survives_a_blocked_scorer(
    tmp_path, monkeypatch
):
    from backend.market import opportunity_shadow

    calls = []

    def bars(store, tickers, asof):
        calls.append("bars")
        return _BarsReport()

    def filings(store, tickers, asof):
        calls.append("filings")
        return ("ZZZZ",)  # a failed name outside the frozen universe

    def tone(store, tickers, asof, **kw):
        calls.append("tone")
        raise TimeoutError("scorer blocked")

    def observe(root, enabled):
        calls.append("ml")
        return {"status": "Observed frozen policies", "sequence": 1}

    monkeypatch.setattr(opportunity_shadow, "observe_if_current", observe)
    store = MarketStore(tmp_path)
    market_daily.refresh(
        store,
        date(2026, 9, 14),
        bars=bars,
        filings=filings,
        tone=tone,
        after_filings=lambda report, failed: market_daily.observe_ml_forward(
            tmp_path, True, report.failed_tickers, failed
        ),
        versions=lambda store, tickers, asof: [],
    )
    assert calls == ["bars", "filings", "ml", "tone"]
    assert calls.count("ml") == 1
    # A historical run (an explicit --asof) never observes.
    calls.clear()
    market_daily.observe_ml_forward(tmp_path, False)
    assert calls == []


# Incomplete required data prevents the observation: a frozen-universe name
# whose bars failed to refresh stops it, a failed name outside the frozen
# universe does not. Nothing is backdated; the observer is simply not run.
def test_incomplete_bars_prevent_the_ml_observation(tmp_path, monkeypatch, capsys):
    from backend.market import opportunity_shadow

    observed = []
    monkeypatch.setattr(
        opportunity_shadow,
        "observe_if_current",
        lambda root, enabled: observed.append(1),
    )
    with np.load(opportunity_shadow.BUNDLE, allow_pickle=False) as saved:
        frozen_name = str(saved["tickers"][0])
    assert market_daily.observe_ml_forward(tmp_path, True, (frozen_name,)) is None
    assert observed == []
    assert "bars incomplete" in capsys.readouterr().out
    market_daily.observe_ml_forward(tmp_path, True, ("^VIX",))
    assert observed == [1]
    # A failed filing refresh for a frozen name is named and does not stop
    # the observation: the last successful filing snapshot is the policy.
    market_daily.observe_ml_forward(tmp_path, True, (), (frozen_name,))
    out = capsys.readouterr().out
    assert observed == [1, 1]
    assert f"filings for {frozen_name} did not refresh today" in out
    assert "code revision" in out


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
    with_paper = market_daily.record(_report(), paper={"equity": 100.0})
    assert with_paper["paper"]["equity"] == 100.0
    assert data["fundamentals_asof"] is None
    receipt = {"status": "Observed", "sequence": 1, "session": "2026-09-15"}
    with_ml = market_daily.record(_report(), ml_forward=receipt)
    assert with_ml["provenance"]["ml_forward"] == receipt
    assert data["provenance"]["ml_forward"] is None
    block = {"summary": {"grades_changed": 1}}
    assert (
        market_daily.record(_report(), fundamentals=block)["fundamentals_asof"] == block
    )
    path = market_daily.save(Path(tmp_path), data)
    assert path == Path(tmp_path) / "desk" / "asof=2026-09-03" / "desk.json"
    assert json.loads(path.read_text(encoding="utf-8"))["session"] == "2026-09-03"


# Every graded name carries the executor's band-gate flag on the record: the
# value `_band_blocked` hands `paper.plan(entry_blocked=...)` in the nightly,
# which is `exit.evidence(panel).signalled()` on the decision session (the
# predicate `simulate.run(block_overbought=True)` reads). The `/4` board's
# structure gate reads exactly this flag (`decision_view._structure_gate`).
def test_record_carries_the_executors_band_gate_for_every_name(monkeypatch):
    from types import SimpleNamespace

    from backend.agents.trading.desk import exit as exit_analyst
    from backend.market import decision_view

    report = _report()
    signal = np.zeros(report.panel.adj_close.shape, dtype=bool)
    signal[-1, report.panel.index("IREN")] = True
    signal[0, report.panel.index("SNDK")] = True  # an earlier session: ignored
    monkeypatch.setattr(
        exit_analyst,
        "evidence",
        lambda panel: SimpleNamespace(signalled=lambda: signal),
    )
    data = market_daily.record(report)
    blocked, flags = market_daily._band_blocked(report)
    assert blocked == {"IREN"}
    assert set(data["grades"]) <= set(data["levels"])
    for ticker in data["grades"]:
        assert data["levels"][ticker]["rejecting_band"] is flags[ticker]
        assert decision_view._structure_gate(data, ticker) == (
            decision_view.REJECTING if flags[ticker] else decision_view.CLEAR
        )
    assert data["levels"]["IREN"]["rejecting_band"] is True
    assert data["levels"]["SNDK"]["rejecting_band"] is False


# Persist each recorded source unchanged alongside its cited fiscal dates;
# a new calculation version must not relabel an older saved decision.
@pytest.mark.parametrize(
    "source", ["fundamentals-features/1", "fundamentals-features/2"]
)
def test_record_carries_the_fundamental_source_and_period_dates(tmp_path, source):
    from backend.agents.trading.desk.opinions import Opinion

    t = 3
    n = 3  # SNDK, IREN, SPY
    scores = np.full((t, n), np.nan)
    scores[:, 0] = 0.8  # SNDK has a fundamental view
    evidence = {"gross_margin": np.full((t, n), np.nan)}
    period_ends = {"gross_margin": np.full((t, n), np.datetime64("NaT", "D"))}
    period_ends["gross_margin"][:, 0] = np.datetime64("2025-12-31")
    opinion = Opinion(
        "fundamental",
        scores,
        evidence,
        meta={"source": source, "period_ends": period_ends},
    )
    report = replace(
        _report(),
        fundamentals_source=source,
        opinions={"fundamental": opinion},
    )
    data = market_daily.record(report)
    assert data["provenance"]["data"]["fundamentals"] == source
    block = data["fundamental"]
    assert block["source"] == source
    # SNDK has a finite score, so its cited period ends are dated.
    assert block["dates"]["SNDK"]["gross_margin"] == "2025-12-31"
    # IREN has no finite score: it is not dated.
    assert "IREN" not in block["dates"]
    path = market_daily.save(tmp_path, data)
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["provenance"]["data"]["fundamentals"] == source
    assert saved["fundamental"] == block


# A legacy comparison run is labelled with the frozen source, and a name with
# no finite score is never handed a fabricated date.
def test_record_carries_the_legacy_source_when_the_desk_read_legacy():
    report = replace(_report(), fundamentals_source="edgar-frozen")
    data = market_daily.record(report)
    assert data["provenance"]["data"]["fundamentals"] == "edgar-frozen"
    assert data["fundamental"]["source"] == "edgar-frozen"
    assert data["fundamental"]["dates"] == {}


# The track-record curve names the fundamental data source its simulation's
# analysts read, separate from the execution policy, so the page can tell a
# period-checked curve from an older calculation without relabelling either.
@pytest.mark.parametrize(
    "source", ["fundamentals-features/1", "fundamentals-features/2"]
)
def test_curve_block_carries_the_fundamental_data_source(monkeypatch, source):
    from backend.agents.trading.desk import simulate as sim_module

    report = replace(_report(), fundamentals_source=source)
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 1.1 / 1.05 - 1.0]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, **kwargs: sim)
    block = market_daily.curve_block(report, None)
    assert block is not None
    assert block["fundamentals_source"] == source


# A record is the day's decision and must not be silently replaced: saving
# a second record for the same session is refused unless the caller says it
# is deliberately rewriting it. And every record says what produced it.
def test_save_refuses_to_overwrite_a_session_and_carries_provenance(tmp_path):
    data = market_daily.record(_report(), {"SNDK": {"stance": "own"}})
    first = market_daily.save(Path(tmp_path), data)
    with pytest.raises(FileExistsError):
        market_daily.save(Path(tmp_path), data)
    # The original is untouched by the refused second save.
    assert json.loads(first.read_text(encoding="utf-8"))["session"] == "2026-09-03"
    # An explicit rewrite is allowed.
    second = market_daily.save(Path(tmp_path), data, allow_overwrite=True)
    assert json.loads(second.read_text(encoding="utf-8"))["session"] == "2026-09-03"
    provenance = market_daily.record(_report(), llm_model="deepseek-v4-flash")[
        "provenance"
    ]
    assert provenance["code_revision"]  # a real revision or "unknown"
    assert provenance["strategy"]["rebalance_every"] > 0
    assert provenance["model"] == "deepseek-v4-flash"
    assert provenance["data"]["session"] == "2026-09-03"


# Without the clock the desk cannot know whether a market-on-open order
# would fill now instead of at the next open, so submission fails closed:
# every order is refused and none is sent.
def test_an_unavailable_market_clock_refuses_submission(monkeypatch):
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    class Clockless:
        def clock(self):
            raise alpaca_trading.AlpacaTradingError("clock down")

        def submit_market_on_open(self, *args):
            raise AssertionError("must not submit without the clock")

    submitted, refused = market_daily._submit(
        Clockless(),
        [paper.PaperOrder("AAA", "buy", 10, "rebalance to 0.100")],
        "2026-09-07",
        live=True,
    )
    assert submitted == []
    assert refused
    assert "clock" in refused[0].lower()


# The id an order carries at submission is the id it was planned with; a
# fallback recomputes one only for an order that never got one. Buys are
# queued for the next open and sells for the next closing auction.
def test_submission_uses_the_planned_order_id():
    from backend.agents.trading.desk import paper

    sent = []

    class Quiet:
        def clock(self):
            return {"is_open": False}

        def submit_market_on_open(self, symbol, qty, side, client_order_id):
            sent.append(("open", client_order_id))

        def submit_market_on_close(self, symbol, qty, side, client_order_id):
            sent.append(("close", client_order_id))

    planned = paper.PaperOrder(
        "AAA",
        "buy",
        10,
        "rebalance to 0.100",
        client_order_id="anios-2026-09-07-buy-aaa-3",
    )
    fallback = paper.PaperOrder("BBB", "sell", 5, "exit")
    submitted, refused = market_daily._submit(
        Quiet(), [planned, fallback], "2026-09-07", live=True
    )
    assert refused == []
    assert sent[0] == ("open", "anios-2026-09-07-buy-aaa-3")
    assert sent[1] == ("close", paper.order_id("2026-09-07", "BBB", "sell"))


# A sell goes to the closing auction and a buy to the next open: the desk
# exits on the close it has seen rather than an opening print, while a buy
# still fills at the first print after the open.
def test_sells_go_to_the_close_and_buys_to_the_open(monkeypatch):
    from backend.agents.trading.desk import paper

    calls = []

    class Broker:
        def clock(self):
            return {"is_open": False}

        def submit_market_on_open(self, symbol, qty, side, client_order_id):
            calls.append(("open", side, symbol))

        def submit_market_on_close(self, symbol, qty, side, client_order_id):
            calls.append(("close", side, symbol))

    buy = paper.PaperOrder("AAA", "buy", 10, "rebalance to 0.100")
    sell = paper.PaperOrder("BBB", "sell", 5, "leaves the book")
    submitted, refused = market_daily._submit(
        Broker(), [buy, sell], "2026-09-07", live=True
    )
    assert refused == []
    assert calls == [("open", "buy", "AAA"), ("close", "sell", "BBB")]


# The desk cancels only what it wrote down, matched by its own client order
# id prefix: an order the person placed by hand stays on the account.
def test_the_desk_cancels_only_its_own_open_orders():
    open_orders = [
        {"client_order_id": "anios-2026-09-04-buy-aaa-0"},
        {"client_order_id": "anios-2026-09-04-sell-bbb-1"},
        {"client_order_id": "manual-1002"},
        {},
    ]
    assert market_daily._desk_open_order_ids(open_orders) == [
        "anios-2026-09-04-buy-aaa-0",
        "anios-2026-09-04-sell-bbb-1",
    ]


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


# A same-session rerun is refused before any side effect: with a record on
# file, main() returns at the guard and never reaches paper_trade, so a
# duplicate invocation places no orders and persists no pending state. The
# old code traded first and refused to save afterwards, having already
# submitted and written pending state it then called "nothing was changed".
def test_a_same_session_rerun_submits_no_trade(tmp_path, monkeypatch, capsys):
    market_daily.save(Path(tmp_path), market_daily.record(_report()))
    traded = []
    seen_fundamentals = []

    # Record the requested data source while returning the fixed desk fixture.
    def fake_run(store, asof=None, fundamentals="corrected"):
        seen_fundamentals.append(fundamentals)
        return _report()

    def fake_paper_trade(*args, **kwargs):
        traded.append(args)
        return {}

    monkeypatch.setattr(market_daily.trading_desk, "run", fake_run)
    monkeypatch.setattr(market_daily, "paper_trade", fake_paper_trade)
    # The print helpers need a fuller fixture than _report(); the guard is
    # what is under test, so they are stubbed out.
    monkeypatch.setattr(market_daily, "_print_regime", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_print_grades", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_print_book", lambda *a, **k: None)
    monkeypatch.setattr(
        sys, "argv", ["market_daily", "--data-dir", str(tmp_path), "--paper-trade"]
    )
    market_daily.main()
    assert traded == []
    assert "refusing to re-run the day" in capsys.readouterr().out
    # The record on file is untouched, and no pending state was written.
    assert (Path(tmp_path) / "desk" / "asof=2026-09-03" / "desk.json").exists()
    # The nightly explicitly requests the reporting-period policy while
    # retaining the same-session guard before any trade is considered.
    assert seen_fundamentals == ["current"]


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
    from backend.agents.trading.desk import simulate as sim_module
    from backend.market import benchmarks

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 1.1 / 1.05 - 1.0]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, **kwargs: sim)
    monkeypatch.setattr(
        benchmarks,
        "load_benchmark",
        lambda store, symbol, sessions, **kw: benchmarks.BenchmarkSeries(
            symbol, True, None, np.array([1.0, 1.02, 1.03]), np.asarray(sessions)
        ),
    )
    block = market_daily.curve_block(report, object())
    assert block is not None
    assert block["rules"] == pytest.approx([0.0, 0.05, 0.1])
    assert block["spy"] == pytest.approx([0.0, 0.02, 0.03])
    assert block["qqq"] == pytest.approx([0.0, 0.02, 0.03])
    assert block["benchmark_notes"] == {}
    # The point-in-time line runs the same (patched) simulation on the
    # restricted report, so here it equals the rules line; the record
    # carries its own stats and an empty note.
    assert block["rules_point_in_time"] == pytest.approx([0.0, 0.05, 0.1])
    assert block["stats_point_in_time"]["total"] == pytest.approx(0.1)
    assert block["point_in_time_note"] == ""
    assert block["benchmark_cost_bps"] == sim_module.COST_BPS
    assert block["stats"]["total"] == pytest.approx(0.1)
    assert block["asof"] == "2026-09-03"
    assert block["funding_model"] == sim_module.FUNDING_MODEL


# The benchmark starts at zero like the rules, and its first return is the
# first one the strategy participates in - not the return into the base date,
# which the strategy never held. The off-by-one is visible only when the sim
# starts mid-panel, so this sim does.
def test_curve_benchmark_is_aligned_to_the_strategy_start(monkeypatch):
    from backend.agents.trading.desk import grading, regime
    from backend.agents.trading.desk import simulate as sim_module
    from backend.market import benchmarks
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
    monkeypatch.setattr(sim_module, "run", lambda report, **kwargs: sim)
    seen = {}

    # The strict loader is handed the simulation's own sessions, so the
    # benchmark cannot earn the -10% into the base date; it is priced from
    # that date's close forward, exactly like the rules.
    def fake_load(store, symbol, sessions, **kw):
        seen[symbol] = [str(d) for d in sessions]
        return benchmarks.BenchmarkSeries(
            symbol, True, None, np.array([1.0, 1.1, 1.21]), np.asarray(sessions)
        )

    monkeypatch.setattr(benchmarks, "load_benchmark", fake_load)
    block = market_daily.curve_block(report, object())
    assert block is not None
    assert block["rules"] == pytest.approx([0.0, 0.05, 0.1])
    assert seen["SPY"] == [str(d) for d in panel.dates[1:]]
    assert seen["QQQ"] == seen["SPY"]
    assert block["spy"] == pytest.approx([0.0, 0.1, 0.21])
    assert block["qqq"] == pytest.approx([0.0, 0.1, 0.21])


# A benchmark the strict loader cannot price is left off the chart with its
# reason on the record, never drawn as a flat 0% line from zero-filled gaps.
def test_curve_block_reports_an_unavailable_benchmark_instead_of_drawing_it(
    monkeypatch,
):
    from backend.agents.trading.desk import simulate as sim_module
    from backend.market import benchmarks

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 1.1 / 1.05 - 1.0]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, **kwargs: sim)

    def fake_load(store, symbol, sessions, **kw):
        if symbol == "QQQ":
            return benchmarks.BenchmarkSeries(
                symbol, False, None, None, np.asarray(sessions),
                reason="QQQ has no bars in the store",
            )
        return benchmarks.BenchmarkSeries(
            symbol, True, None, np.array([1.0, 1.0, 1.0]), np.asarray(sessions)
        )

    monkeypatch.setattr(benchmarks, "load_benchmark", fake_load)
    block = market_daily.curve_block(report, object())
    assert block["spy"] == pytest.approx([0.0, 0.0, 0.0])
    assert block["qqq"] == []
    assert block["benchmark_notes"] == {"QQQ": "QQQ has no bars in the store"}
    # Without a store nothing is priced, and the record says so.
    none = market_daily.curve_block(report, None)
    assert none["spy"] == [] and none["qqq"] == []
    assert set(none["benchmark_notes"]) == {"SPY", "QQQ"}


# The published backtest must run the same execution policy as the live
# paper account, or the curve silently measures a book nobody trades. Every
# flag in simulate.LIVE_POLICY is passed through curve_block; a policy that
# adds a rule without this test knowing is a backtest that has drifted.
def test_curve_block_runs_the_live_execution_policy(monkeypatch):
    from backend.agents.trading.desk import simulate as sim_module

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    seen: dict[str, object] = {}

    def fake_run(report, **kwargs):
        seen.update(kwargs)
        return sim

    monkeypatch.setattr(sim_module, "run", fake_run)
    market_daily.curve_block(report, None)
    assert sim_module.LIVE_POLICY, "the live policy must not be empty"
    for flag in sim_module.LIVE_POLICY:
        assert flag in seen, f"curve_block did not pass the live flag {flag}"
        assert seen[flag] == sim_module.LIVE_POLICY[flag]


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


# The fixture moved to sessions after SNDK and IREN joined the membership
# history (2026-09-04), so the point-in-time replay can decide on them.
def _member_report() -> DeskReport:
    report = _report()
    dates = np.array(
        [date(2026, 9, 8) + timedelta(days=i) for i in range(3)], dtype="datetime64[D]"
    )
    return replace(report, panel=replace(report.panel, dates=dates))


# Each row carries what the live policy would have done that session, and
# the file names the policy, dates a decision to the close and its fill to
# the next open, and carries the paper account's fills from the records.
def test_write_history_carries_the_policy_decisions_and_fills(tmp_path):
    from backend.agents.trading.desk import decision_history, live_policy

    folder = tmp_path / "desk" / "asof=2026-09-09"
    folder.mkdir(parents=True)
    (folder / "desk.json").write_text(
        json.dumps(
            {
                "session": "2026-09-09",
                "paper": {
                    "settled": [
                        {
                            "symbol": "SNDK",
                            "side": "buy",
                            "qty": 63,
                            "status": "filled",
                            "filled": 63,
                            "filled_price": 224.81,
                            "client_order_id": "anios-2026-09-08-buy-sndk-0",
                        }
                    ]
                },
            }
        ),
        encoding="utf-8",
    )
    count = market_daily.write_history(MarketStore(tmp_path), _member_report())
    assert count == 2
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["policy"] == decision_history.POLICY == live_policy.ACTIVE
    assert payload["policy"] == "graded-equal-weight/5"
    assert payload["decision_note"] == decision_history.DECISION_NOTE
    rows = payload["rows"]
    assert [r["date"] for r in rows] == ["2026-09-08", "2026-09-09", "2026-09-10"]
    # SNDK is the one A+ name: bought at the cap (a quarter under `/5`) on the
    # first session, held after.
    assert rows[0]["action"] == "buy"
    assert rows[0]["target_weight"] == pytest.approx(live_policy.POLICY.HOLD_CAP)
    assert rows[0]["delta_weight"] == pytest.approx(live_policy.POLICY.HOLD_CAP)
    assert rows[0]["target_weight"] == pytest.approx(0.25)
    assert [r["action"] for r in rows[1:]] == ["hold", "hold"]
    assert all(r["delta_weight"] == 0 for r in rows[1:])
    # The grade columns are as they were.
    assert rows[0]["grade"] == "A+"
    assert "forward_residual" in rows[0]
    assert payload["fills"] == [
        {"date": "2026-09-09", "side": "buy", "qty": 63, "price": 224.81}
    ]
    # IREN is graded C: never held, no fills.
    other = json.loads((tmp_path / "history" / "IREN.json").read_text())
    assert {r["action"] for r in other["rows"]} == {"hold"}
    assert all(r["target_weight"] == 0 for r in other["rows"])
    assert other["fills"] == []


# With no paper state on file there is no rebalance clock: no row is a
# reset, the note says so, and the buy and the holds read as before.
def test_write_history_says_when_no_reset_is_known(tmp_path):
    from backend.agents.trading.desk import decision_history

    market_daily.write_history(MarketStore(tmp_path), _member_report())
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["rebalance_note"] == decision_history.RESETS_UNKNOWN
    assert payload["reset_sessions"] == []
    assert [r["rebalance"] for r in payload["rows"]] == [False, False, False]
    assert [r["action"] for r in payload["rows"]] == ["buy", "hold", "hold"]


# The reset flag on each row comes from the paper state's clock: the
# session the book last rebalanced on is flagged, the others are not, and
# the file lists the resets it found.
def test_write_history_flags_the_reset_sessions_from_the_paper_clock(tmp_path):
    from backend.agents.trading.desk import decision_history, paper

    paper.save_state(
        tmp_path,
        paper.PaperState(
            last_rebalance="2026-09-09", sessions_since_rebalance=1
        ),
    )
    market_daily.write_history(MarketStore(tmp_path), _member_report())
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["rebalance_note"] == decision_history.RESETS_FROM_CLOCK
    assert payload["reset_sessions"] == ["2026-09-09"]
    assert [(r["date"], r["rebalance"]) for r in payload["rows"]] == [
        ("2026-09-08", False),
        ("2026-09-09", True),
        ("2026-09-10", False),
    ]
    # SNDK's target does not move, so the reset places nothing: a hold.
    assert [r["action"] for r in payload["rows"]] == ["buy", "hold", "hold"]


# A replay of a policy other than the account's keeps the weight-move
# reading: no reset flag on the rows, and the note says why.
def test_write_history_keeps_the_sizing_reading_for_another_policy(
    tmp_path, monkeypatch
):
    from backend.agents.trading.desk import live_policy

    monkeypatch.setattr(live_policy, "ACTIVE", "some-other-policy/3")
    market_daily.write_history(MarketStore(tmp_path), _member_report())
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert "not the account's" in payload["rebalance_note"]
    assert payload["reset_sessions"] == []
    assert all("rebalance" not in r for r in payload["rows"])
    assert [r["action"] for r in payload["rows"]] == ["buy", "hold", "hold"]


# A replay that cannot run costs the decision columns, never the file.
def test_write_history_survives_a_failed_replay(tmp_path, monkeypatch, capsys):
    from backend.agents.trading.desk import decision_history

    def boom(report, history_path=None):
        raise ValueError("historical membership is empty")

    monkeypatch.setattr(decision_history, "target_matrix", boom)
    count = market_daily.write_history(MarketStore(tmp_path), _member_report())
    assert count == 2
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["policy"] == decision_history.POLICY
    assert "not replayed" in payload["decision_note"]
    assert "action" not in payload["rows"][0]
    assert payload["rows"][0]["grade"] == "A+"
    assert "decisions not replayed" in capsys.readouterr().out


# `--history-only` runs the desk as the nightly does and writes the history
# files, and nothing else: no record, no trade, no observation, no prose.
def test_history_only_writes_histories_and_no_record(tmp_path, monkeypatch, capsys):
    seen_fundamentals = []
    forbidden = []

    def fake_run(store, asof=None, fundamentals="corrected"):
        seen_fundamentals.append((asof, fundamentals))
        return _member_report()

    def forbid(name):
        def call(*args, **kwargs):
            forbidden.append(name)
            return {}

        return call

    monkeypatch.setattr(market_daily.trading_desk, "run", fake_run)
    monkeypatch.setattr(market_daily, "paper_trade", forbid("paper_trade"))
    monkeypatch.setattr(market_daily, "observe_ml_forward", forbid("observe"))
    monkeypatch.setattr(market_daily, "save", forbid("save"))
    monkeypatch.setattr(market_daily, "prune", forbid("prune"))
    monkeypatch.setattr(market_daily, "enrich_prose", forbid("prose"))
    monkeypatch.setattr(
        sys,
        "argv",
        ["market_daily", "--data-dir", str(tmp_path), "--history-only"]
        + ["--paper-trade"],
    )
    market_daily.main()
    out = capsys.readouterr().out
    assert "history: 2 names written" in out
    assert seen_fundamentals == [(None, "current")]
    assert forbidden == []
    assert (tmp_path / "history" / "SNDK.json").exists()
    assert (tmp_path / "history" / "IREN.json").exists()
    assert not list(tmp_path.glob("desk/asof=*"))
    payload = json.loads((tmp_path / "history" / "SNDK.json").read_text())
    assert payload["rows"][0]["action"] == "buy"


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


# The record names the revision the process started from, not whatever the
# checkout has moved to since: the intraday cron and a deploy both pull
# main under a running nightly.
def test_the_record_revision_is_the_one_the_process_started_from(monkeypatch):
    monkeypatch.setattr(market_daily, "_STARTED_FROM", None)
    readings = iter(["aaaaaaa", "bbbbbbb"])
    monkeypatch.setattr(market_daily, "_read_git_revision", lambda: next(readings))
    first = market_daily.record(_report())["provenance"]["code_revision"]
    second = market_daily.record(_report())["provenance"]["code_revision"]
    assert first == second == "aaaaaaa"


# The receipt says whether the observer's state is tonight's session: a run
# that fell back to an earlier ledger state is visible as not observed.
def test_ml_receipt_says_whether_tonight_was_observed():
    row = {"status": "Observed", "sequence": 3, "session": "2026-09-15"}
    assert market_daily._ml_forward_receipt(row, "2026-09-15")["observed_tonight"]
    stale = market_daily._ml_forward_receipt(row, "2026-09-16")
    assert stale["observed_tonight"] is False
    assert stale["session"] == "2026-09-15"
    assert market_daily._ml_forward_receipt(None, "2026-09-16") is None


# A missing or unreadable bundle skips the observation and says so; it
# never aborts the run before the record.
def test_an_unreadable_bundle_skips_the_observation(monkeypatch, tmp_path, capsys):
    from backend.market import opportunity_shadow

    monkeypatch.setattr(opportunity_shadow, "BUNDLE", tmp_path / "missing.npz")
    assert market_daily.observe_ml_forward(tmp_path, True) is None
    assert "bundle unreadable" in capsys.readouterr().out


# A refused run (another nightly holds the lock) exits non-zero so cron
# reports it instead of recording a silent success.
def test_a_refused_run_exits_non_zero(monkeypatch, tmp_path):
    from backend.market import nightly_lock

    monkeypatch.setattr(nightly_lock, "acquire", lambda root: None)
    monkeypatch.setattr(
        market_daily,
        "build_parser",
        lambda: SimpleNamespace(
            parse_args=lambda: SimpleNamespace(data_dir=str(tmp_path))
        ),
    )
    with pytest.raises(SystemExit) as raised:
        market_daily.main()
    assert raised.value.code == 75


# A panel long enough for a 21-day average, flat until the last session so
# each name's stretch is set by one close and nothing else.
def _stretch_report(last_closes: dict[str, float], grades_by_name: dict[str, str]):
    names = tuple(last_closes) + ("SPY",)
    t = 40
    close = np.full((t, len(names)), 100.0)
    for j, name in enumerate(names[:-1]):
        close[-1, j] = last_closes[name]
    dates = np.array(
        [date(2026, 8, 1) + timedelta(days=i) for i in range(t)], dtype="datetime64[D]"
    )
    panel = Panel(
        dates=dates,
        tickers=names,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={n: (AI_COMPUTE,) for n in names[:-1]},
        benchmark="SPY",
    )
    grades = np.zeros((t, len(names)), dtype=int)
    for j, name in enumerate(names[:-1]):
        grades[:, j] = grading.ORDINAL[grades_by_name[name]]
    graded = grading.Graded(
        grades, np.zeros((t, len(names))), {"fundamental": np.zeros((t, len(names)))}
    )
    state = regime.RegimeState(
        -0.06, 0.19, 0.0, -0.52, -3.6, 4.8, "software", -0.217, -0.223, 0.5, 1.0, ()
    )
    view = regime.RegimeView(
        [state] * t, Opinion("rotation", np.full((t, len(names)), np.nan))
    )
    return DeskReport(
        panel,
        {n: "ai" for n in names[:-1]},
        {},
        view,
        graded,
        grades.astype(float),
        [],
    )


# The mid-cycle entry fires on the band's upper edge only. A name pinned to
# the LOWER band is not an entry however good its grade: the dip leg was
# measured over the regime the book trades and stopped paying there.
def test_price_entries_take_the_upper_band_only():
    report = _stretch_report(
        {"UP": 120.0, "DOWN": 80.0, "UPBUTC": 120.0},
        {"UP": "A+", "DOWN": "A+", "UPBUTC": "C"},
    )
    from backend.agents.trading.desk import paper

    entries = market_daily._price_entries(report)
    assert set(entries) == {"UP"}, entries
    assert entries["UP"] >= paper.ENTRY_BAND_Z


# The benchmark is never an entry: it is the thing the book is measured
# against, not a name the book holds.
def test_price_entries_never_return_the_benchmark():
    report = _stretch_report({"UP": 120.0}, {"UP": "A+"})
    report.panel.adj_close[-1, -1] = 150.0
    assert "SPY" not in market_daily._price_entries(report)


# The desk holds while it grades A or better and rotates out when it does not.
# Only held names can be rotated out of, and the benchmark never is.
def test_downgraded_names_are_selected_for_rotation():
    report = _stretch_report(
        {"KEEP": 100.0, "DROP": 100.0, "UNHELD": 100.0},
        {"KEEP": "A", "DROP": "C", "UNHELD": "C"},
    )
    out = market_daily._downgraded(report, {"KEEP": 10.0, "DROP": 5.0})
    assert set(out) == {"DROP"}, out
    assert "graded C" in out["DROP"]


# A B grade is below the desk's hold line too: the entry floor is A or better,
# and the rotation reads the same constant rather than a second opinion.
def test_a_b_grade_is_rotated_out_like_a_c():
    from backend.agents.trading.desk import paper

    assert "B" not in paper.ENTRY_MIN_GRADE
    report = _stretch_report({"BEE": 100.0}, {"BEE": "B"})
    assert set(market_daily._downgraded(report, {"BEE": 7.0})) == {"BEE"}


# A winter nightly at 19:30 New York time is 00:30 UTC the next day; the
# session it writes must still be the New York date.
def test_the_nightly_session_date_is_the_new_york_date_in_winter():
    from datetime import UTC, date, datetime

    from backend.cli.market_daily import _nightly_asof

    winter_run = datetime(2026, 11, 3, 0, 30, tzinfo=UTC)  # 19:30 EST, Nov 2
    assert _nightly_asof(winter_run) == date(2026, 11, 2)


# In summer 19:30 New York time is 23:30 UTC the same day, and the date agrees.
def test_the_nightly_session_date_is_unchanged_in_summer():
    from datetime import UTC, date, datetime

    from backend.cli.market_daily import _nightly_asof

    summer_run = datetime(2026, 9, 25, 23, 30, tzinfo=UTC)  # 19:30 EDT
    assert _nightly_asof(summer_run) == date(2026, 9, 25)


# When the point-in-time run cannot be drawn (here: the simulation raises on
# the restricted report only), the published line still stands and the
# record says why the second line is absent.
def test_curve_block_reports_a_missing_point_in_time_line(monkeypatch):
    from backend.agents.trading.desk import simulate as sim_module
    from backend.market import benchmarks

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 1.1 / 1.05 - 1.0]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    calls = {"n": 0}

    def fake_run(report_, **kwargs):
        calls["n"] += 1
        if calls["n"] > 1:
            raise RuntimeError("restricted run failed")
        return sim

    monkeypatch.setattr(sim_module, "run", fake_run)
    monkeypatch.setattr(
        benchmarks,
        "load_benchmark",
        lambda store, symbol, sessions, **kw: benchmarks.BenchmarkSeries(
            symbol, True, None, np.array([1.0, 1.0, 1.0]), np.asarray(sessions)
        ),
    )
    block = market_daily.curve_block(report, object())
    assert block["rules"] == pytest.approx([0.0, 0.05, 0.1])
    assert block["rules_point_in_time"] == []
    assert block["stats_point_in_time"] == {}
    assert "restricted run failed" in block["point_in_time_note"]


# A report the simulator can actually walk: eight names and SPY over
# `sessions` weekdays of random-walk prices, grades that move between A+, A,
# B and C, so the candidate has to select, cap and hold cash. The same
# shape as `test_policy_v4`'s report, built here so this module's guarantee
# does not depend on another test file's fixture.
def _walk_report(sessions: int = 160, seed: int = 3) -> DeskReport:
    names = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH")
    rng = np.random.default_rng(seed)
    n = len(names)
    days = []
    d = date(2022, 1, 3)
    while len(days) < sessions:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    dates = np.array(days, dtype="datetime64[D]")
    log = rng.normal(0.0004, 0.02, size=(sessions, n + 1)).cumsum(axis=0)
    close = 100.0 * np.exp(log)
    panel = Panel(
        dates=dates,
        tickers=names + ("SPY",),
        open=close * (1 + rng.normal(0, 0.002, size=close.shape)),
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: (AI_COMPUTE,) for t in names},
        benchmark="SPY",
    )
    grades = rng.choice(
        [grading.ORDINAL[g] for g in ("A+", "A", "B", "C")],
        size=(sessions, n + 1),
        p=[0.3, 0.3, 0.2, 0.2],
    )
    grades[:, n] = 0
    conviction = rng.normal(size=(sessions, n + 1))
    conviction[:, n] = np.nan
    graded = grading.Graded(grades, conviction.copy(), {}, conviction)
    state = regime.RegimeState(
        0.0, 0.0, 0.5, 0.0, 0.0, 0.0, "ai", 0.1, 0.0, 1.0, 1.0, (), 0.0, False
    )
    view = regime.RegimeView(
        [state] * sessions, Opinion("rotation", np.full((sessions, n + 1), np.nan))
    )
    return DeskReport(
        panel, {t: "ai" for t in names}, {}, view, graded, graded.as_scores(), []
    )


# A membership history for the walk report: six names throughout, GGG
# entering late and FFF leaving early, so the point-in-time mask changes.
def _walk_history(tmp_path: Path) -> Path:
    path = tmp_path / "membership_history.csv"
    rows = ["ticker,entered,entry_announced,exited,exit_announced,source,rule"]
    for t in ("AAA", "BBB", "CCC", "DDD", "EEE", "HHH"):
        rows.append(f"{t},2016-01-04,2016-01-04,,,test,member throughout")
    rows.append("GGG,2022-05-02,2022-05-02,,,test,enters late")
    rows.append("FFF,2016-01-04,2016-01-04,2022-06-01,2022-06-01,test,leaves early")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


# Point the nightly's restriction at a history file of the test's choosing
# (the production default is bound into the function's signature, so the
# module constant cannot be patched instead).
def _use_history(monkeypatch, history_path: Path) -> None:
    from backend.agents.trading.desk import point_in_time

    original = point_in_time.point_in_time
    monkeypatch.setattr(
        point_in_time,
        "point_in_time",
        lambda report, history_path=history_path: original(
            report, history_path=history_path
        ),
    )


# The curve block carries the `/4` candidate as a third strategy line: the
# same length as the published rules line, starting at 0, named by its
# policy version and a fixed label that says how it was priced.
def test_curve_block_carries_the_candidate_line(monkeypatch, tmp_path):
    from backend.agents.trading.desk import policy_v4

    _use_history(monkeypatch, _walk_history(tmp_path))
    block = market_daily.curve_block(_walk_report(), None)
    assert block is not None
    curve = block["candidate_point_in_time"]
    assert len(curve) == len(block["rules"]) > 2
    assert curve[0] == 0.0
    assert block["candidate_note"] == ""
    assert block["candidate_policy"] == policy_v4.POLICY_VERSION == "graded-equal-weight/4"
    assert block["candidate_label"] == market_daily.CANDIDATE_LABEL
    assert block["candidate_label"].startswith("candidate /4: every A/A+ name")
    assert "not the live executor" in block["candidate_label"]
    stats = block["stats_candidate"]
    assert set(stats) >= {"cagr", "volatility", "drawdown", "total"}
    assert all(v is None or isinstance(v, float) for v in stats.values())
    assert stats["total"] == pytest.approx(curve[-1])
    # It is a different line from the rules and from the point-in-time
    # rules, not one of them relabelled.
    assert curve != block["rules"]
    assert curve != block["rules_point_in_time"]


# The guarantee behind the line: value for value, the dashboard's candidate
# curve is the scorecard's `ew_graded_20` arm priced the plain way the
# scorecard prices an arm (next-open fills at the default cost, the arm's
# rebalance clock, no exits, no live policy) on the same report and the
# same sessions. If either side drifts - a flag added here, a constant
# changed in the arm - the page would be showing a number the scorecard
# never measured, and this is what notices.
def test_candidate_line_is_the_scorecard_arm_priced_plain(monkeypatch, tmp_path):
    from backend.agents.trading.desk import paper, point_in_time, simulate
    from backend.cli import market_pit_scorecard as sc

    history = _walk_history(tmp_path)
    _use_history(monkeypatch, history)
    report = _walk_report()
    block = market_daily.curve_block(report, None)
    assert block["candidate_note"] == ""
    restricted, mask = point_in_time.point_in_time(report, history_path=history)
    arm = simulate.run(
        restricted,
        since=date.fromisoformat(block["dates"][0]),
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        cost_bps=simulate.COST_BPS,
        allocator=sc.ARMS["ew_graded_20"](restricted, mask),
    )
    assert [str(d) for d in arm.dates] == block["dates"]
    expected = arm.equity / arm.equity[0] - 1.0
    np.testing.assert_allclose(
        block["candidate_point_in_time"], expected, rtol=0, atol=1e-12
    )
    # Not a vacuous match: the arm traded and moved.
    assert np.abs(expected).max() > 0
    assert arm.rebalances > 1
    for key, value in arm.stats().items():
        if value != value:
            assert block["stats_candidate"][key] is None
        else:
            assert block["stats_candidate"][key] == pytest.approx(value)


# Without the membership file the candidate cannot be placed on the
# point-in-time book: the curve is empty, the stats are empty and the note
# says why, while the published rules line still stands.
def test_curve_block_reports_a_missing_candidate_line(monkeypatch, tmp_path):
    _use_history(monkeypatch, tmp_path / "no-such-membership.csv")
    block = market_daily.curve_block(_walk_report(), None)
    assert block is not None
    assert len(block["rules"]) > 2
    assert block["candidate_point_in_time"] == []
    assert block["stats_candidate"] == {}
    assert block["candidate_note"].startswith("candidate line not drawn:")
    assert "FileNotFoundError" in block["candidate_note"]
    # The same failure takes the point-in-time rules line with it.
    assert block["rules_point_in_time"] == []
    assert block["point_in_time_note"].startswith("point-in-time line not drawn:")
    # The line is absent, not mislabelled: the policy and label still say
    # what would have been drawn.
    assert block["candidate_policy"] == "graded-equal-weight/4"
    assert block["candidate_label"] == market_daily.CANDIDATE_LABEL


# The record carries the policy shadows' receipts under their own key, and
# an empty map when none were passed, so older records read the same way.
def test_record_carries_the_policy_shadows():
    receipt = {
        "sequence": 3,
        "equity": 101_000.0,
        "return_1d": 0.01,
        "orders_decided": 0,
    }
    data = market_daily.record(
        _report(), policy_shadows={"graded-equal-weight/4": receipt}
    )
    assert data["policy_shadows"]["graded-equal-weight/4"] == receipt
    assert market_daily.record(_report())["policy_shadows"] == {}


# The active policy's shadow is observed on tonight's report and prices,
# and its receipt lands under the active version (`/5` since 2026-09-29);
# an exception becomes a note, so the record is still written and says
# what happened.
def test_policy_shadow_receipt_lands_and_a_failure_becomes_a_note(
    tmp_path, monkeypatch, capsys
):
    from backend.agents.trading.desk import live_policy, shadow_ledger

    assert live_policy.ACTIVE == "graded-equal-weight/5"

    seen = {}

    def fake_observe(root, report, opens, closes, session, now=None, migrations=None):
        seen.update(root=root, opens=opens, closes=closes, session=session)
        return {
            "sequence": 2,
            "session": session,
            "equity": 100_500.0,
            "return_1d": 0.005,
            "pending": {"orders": {"SNDK": 200}},
            "fills": [],
            "refusals": [],
            "status": "Observed; targets reset",
        }

    monkeypatch.setattr(shadow_ledger, "observe", fake_observe)
    block = market_daily._policy_shadows(tmp_path, _report(), "2026-09-03", True)
    assert set(block) == {live_policy.ACTIVE}
    receipt = block["graded-equal-weight/5"]
    assert receipt["sequence"] == 2
    assert receipt["equity"] == 100_500.0
    assert receipt["return_1d"] == 0.005
    assert receipt["orders_decided"] == 1
    assert receipt["note"] == "Observed; targets reset"
    assert seen["session"] == "2026-09-03"
    assert seen["root"] == tmp_path
    assert seen["closes"] == {"SNDK": 100.0, "IREN": 100.0, "SPY": 100.0}
    assert seen["opens"] == seen["closes"]
    assert "policy shadow graded-equal-weight/5: sequence 2" in capsys.readouterr().out

    def broken(*args, **kwargs):
        raise RuntimeError("ledger folder unwritable")

    monkeypatch.setattr(shadow_ledger, "observe", broken)
    block = market_daily._policy_shadows(tmp_path, _report(), "2026-09-03", True)
    assert block == {
        "graded-equal-weight/5": {
            "note": "shadow not observed: RuntimeError: ledger folder unwritable"
        }
    }
    assert "not observed (RuntimeError" in capsys.readouterr().out
    # A historical run is not an observation.
    calls = []
    monkeypatch.setattr(shadow_ledger, "observe", lambda *a, **k: calls.append(a))
    block = market_daily._policy_shadows(tmp_path, _report(), "2026-09-03", False)
    assert (
        block["graded-equal-weight/5"]["note"] == "shadow not observed: historical run"
    )
    assert calls == []


# The whole nightly, with the data steps stubbed: the real ledger is written
# under the store and its receipt is in the saved record, beside the paper
# entry and without disturbing it.
def test_the_nightly_writes_the_shadow_ledger_and_its_receipt(tmp_path, monkeypatch):
    from backend.cli import market_economics

    monkeypatch.setattr(
        market_daily.trading_desk,
        "run",
        lambda store, asof=None, fundamentals="c": _report(),
    )
    monkeypatch.setattr(market_daily, "paper_trade", lambda *a, **k: {"equity": 5.0})
    for name in ("_print_regime", "_print_grades", "_print_book", "_reversal_shadows"):
        monkeypatch.setattr(market_daily, name, lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "observe_ml_forward", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_fundamentals_block", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "_tone_revisions", lambda *a, **k: {})
    monkeypatch.setattr(market_daily, "curves", lambda *a, **k: None)
    monkeypatch.setattr(market_daily, "write_history", lambda *a, **k: 0)
    monkeypatch.setattr(market_daily, "prune", lambda *a, **k: [])
    monkeypatch.setattr(market_daily, "enrich_prose", lambda *a, **k: ("skipped", ""))
    monkeypatch.setattr(market_economics, "refresh_if_current", lambda *a, **k: None)
    monkeypatch.setattr(
        sys, "argv", ["market_daily", "--data-dir", str(tmp_path), "--paper-dry-run"]
    )
    market_daily.main()
    record = json.loads(
        (Path(tmp_path) / "desk" / "asof=2026-09-03" / "desk.json").read_text()
    )
    assert set(record["policy_shadows"]) == {"graded-equal-weight/5"}
    receipt = record["policy_shadows"]["graded-equal-weight/5"]
    assert receipt["sequence"] == 1
    assert receipt["equity"] == 100_000.0
    # SNDK is the one A+ name at 100: a quarter of the account, 250 shares.
    assert receipt["orders_decided"] == 1
    assert record["paper"] == {"equity": 5.0}
    rows = sorted((Path(tmp_path) / "desk/shadow/graded-equal-weight-5").glob("*.json"))
    assert [p.name for p in rows] == ["00000000.json", "00000001.json"]
    last = json.loads(rows[-1].read_text())
    assert last["pending"]["orders"] == {"SNDK": 250}
    assert last["session"] == "2026-09-03"
    assert last["policy"] == "graded-equal-weight/5"
    # The `/4` ledger's folder is not where tonight's shadow writes.
    assert not (Path(tmp_path) / "desk/shadow/graded-equal-weight-4").exists()


# ---------------------------------------------------------------------------
# The redeploy of idle cash on the nightly (execution policy /4).
# ---------------------------------------------------------------------------


# A paper broker with a book: positions and cash as given, whole-share
# fills at 100, every order accepted and reported filled on the next read.
class _Broker:
    def __init__(self, cash: float, positions: dict[str, int]):
        self.cash = cash
        self.held = dict(positions)
        self.orders: list[dict] = []
        self.sent: list[tuple] = []

    def account(self):
        equity = self.cash + 100.0 * sum(self.held.values())
        return SimpleNamespace(equity=equity, cash=self.cash)

    def positions(self):
        return [
            SimpleNamespace(
                symbol=s, qty=q, market_value=100.0 * q, avg_entry_price=100.0,
                current_price=100.0, unrealized_pl=0.0,
            )
            for s, q in self.held.items()
            if q > 0
        ]

    def clock(self):
        return {"is_open": False}

    def _accept(self, symbol, qty, side, client_order_id):
        self.sent.append((side, symbol, qty))
        self.orders.append(
            {
                "client_order_id": client_order_id, "symbol": symbol, "qty": qty,
                "side": side, "status": "filled", "filled_qty": qty,
                "filled_avg_price": 100.0,
            }
        )
        return {"submitted_at": "2026-09-04T00:01:02Z", "time_in_force": "day"}

    def submit_market_on_open(self, symbol, qty, side, client_order_id):
        return self._accept(symbol, qty, side, client_order_id)

    def submit_market_on_close(self, symbol, qty, side, client_order_id):
        return self._accept(symbol, qty, side, client_order_id)

    def orders_since(self, since):
        return self.orders

    def cancel_orders(self, ids):
        return None


# The ordinary-session setup: the broker in place, no FOMC cycle, and a
# state stamped with the active policy two sessions after a reset that
# wanted SNDK at the active policy's cap, so tonight is a plain mid-cycle
# session.
def _midcycle_state(tmp_path, monkeypatch, broker):
    from backend.agents.trading.desk import event_risk, live_policy, paper
    from backend.market import alpaca_trading

    monkeypatch.setattr(alpaca_trading, "client_from_env", lambda: broker)
    monkeypatch.setattr(
        event_risk, "decision",
        lambda panel: {
            "calendar_known": True, "factor": 1.0, "decision_date": "2026-09-16"
        },
    )
    paper.save_state(
        tmp_path,
        paper.PaperState(
            last_rebalance="2026-09-01", sessions_since_rebalance=1,
            policy_version=live_policy.ACTIVE,
            rebalance_targets={"SNDK": live_policy.POLICY.HOLD_CAP},
        ),
    )


# A dry run plans the redeploy and submits nothing: SNDK (the one A+ name,
# target 25% under `/5`) is held at 10% with 90% of the book in cash, so
# the redeploy wants 150 more shares; the dry run prints that order with
# its reason and "[dry run]", sends nothing to the broker, saves no state,
# and the entry it returns carries the idle cash share and the redeploy
# block.
def test_a_dry_run_plans_the_redeploy_without_submitting(tmp_path, monkeypatch, capsys):
    from backend.agents.trading.desk import paper

    broker = _Broker(cash=90_000.0, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    before = paper.state_path(tmp_path).read_text()
    entry = market_daily.paper_trade(_report(), tmp_path, "2026-09-03", False)
    out = capsys.readouterr().out
    assert "paper book (graded-equal-weight/5; redeploy)" in out
    assert (
        "redeploy: 1 buys put 15,000 of idle cash back to the targets "
        "(buffer 2% of equity)"
    ) in out
    assert (
        "buy    150 SNDK   redeploy: cash beyond the buffer put back to its "
        "target weights  [dry run]"
    ) in out
    assert broker.sent == []
    assert paper.state_path(tmp_path).read_text() == before
    assert entry["orders"] == []
    assert entry["refused"] == []
    assert entry["plan"] == "redeploy"
    assert entry["idle_cash_share"] == pytest.approx(0.75)
    assert entry["redeploy"] == {
        "enabled": True, "buffer": 0.02, "orders": 1, "notional": 15_000.0
    }


# A live session submits the redeploy as a next-open buy carrying its kind,
# on the record's orders and the state's pending rows; the session after,
# once the broker reports it filled, the settled row carries the kind too,
# the fills history reads it, and the book reads fully invested but for the
# policy's own idle share (SNDK at its 25% cap; nothing else is graded).
def test_a_live_redeploy_carries_its_kind_to_the_record_and_the_fills(
    tmp_path, monkeypatch, capsys
):
    from backend.agents.trading.desk import decision_history, paper

    broker = _Broker(cash=90_000.0, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    report = _report()
    entry = market_daily.paper_trade(report, tmp_path, "2026-09-03", True)
    assert broker.sent == [("buy", "SNDK", 150)]
    assert [(o["symbol"], o["qty"], o["kind"]) for o in entry["orders"]] == [
        ("SNDK", 150, paper.REDEPLOY_KIND)
    ]
    state = paper.load_state(tmp_path)
    assert [row["kind"] for row in state.pending] == [paper.REDEPLOY_KIND]
    assert entry["idle_cash_share"] == pytest.approx(0.75)
    # Filled overnight: the book holds 250 SNDK and 75,000 cash.
    broker.held["SNDK"] = 250
    broker.cash = 75_000.0
    later = market_daily.paper_trade(report, tmp_path, "2026-09-04", True)
    assert [(r["symbol"], r["status"], r["kind"]) for r in later["settled"]] == [
        ("SNDK", "filled", paper.REDEPLOY_KIND)
    ]
    # SNDK is at its 25% cap, so nothing is bought and the idle share is the
    # policy's own 75%, not the executor's.
    assert later["orders"] == []
    assert later["plan"] == "hold"
    assert later["idle_cash_share"] == pytest.approx(0.75)
    assert later["redeploy"]["orders"] == 0
    journal = {row["symbol"]: row for row in paper.load_state(tmp_path).journal}
    assert journal["SNDK"]["kind"] == paper.REDEPLOY_KIND
    # The record's fills history names the leg (dated to the record's
    # session, which on this fixed fixture is the panel's last date).
    market_daily.save(Path(tmp_path), market_daily.record(report, paper=later))
    assert decision_history.fills(tmp_path, "SNDK") == [
        {"date": "2026-09-03", "side": "buy", "qty": 150, "price": 100.0,
         "kind": paper.REDEPLOY_KIND},
    ]


# With the rule switched off the same session plans nothing, prints no
# redeploy line and says so on the entry, so the operator can read the
# switch off the record.
def test_the_redeploy_switch_off_plans_nothing(tmp_path, monkeypatch, capsys):
    from backend.agents.trading.desk import paper

    monkeypatch.setattr(paper, "REDEPLOY_IDLE_CASH", False)
    broker = _Broker(cash=90_000.0, positions={"SNDK": 100})
    _midcycle_state(tmp_path, monkeypatch, broker)
    entry = market_daily.paper_trade(_report(), tmp_path, "2026-09-03", False)
    out = capsys.readouterr().out
    assert "redeploy:" not in out
    assert entry["plan"] == "hold"
    assert entry["idle_cash_share"] == pytest.approx(0.9)
    assert entry["redeploy"]["enabled"] is False
    assert entry["redeploy"]["orders"] == 0


# The published curve says which flags it ran. Under the active graded
# equal-weight policy (`/5` since 2026-09-29) the executor's redeploy of
# idle cash is among them - passed explicitly, never through `LIVE_POLICY`
# (which every study's control is priced from) - and the record says so
# (`redeploy_priced` True, the option and its buffer in
# `execution_options`). The record labels the executor /4 in the same
# block, and the line's allocator is the active policy's: SNDK, the one A+
# name, at `/5`'s quarter.
def test_curve_block_prices_the_redeploy_under_the_active_policy(monkeypatch):
    from backend.agents.trading.desk import live_policy, paper, policy_v5
    from backend.agents.trading.desk import simulate as sim_module

    assert live_policy.ACTIVE == policy_v5.POLICY_VERSION
    assert live_policy.is_equal_weight()
    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    calls: list[dict] = []

    def fake_run(report, **kwargs):
        calls.append(kwargs)
        return sim

    monkeypatch.setattr(sim_module, "run", fake_run)
    block = market_daily.curve_block(report, None)
    assert block["strategy_policy"] == "graded-equal-weight/5"
    assert block["execution_policy"] == paper.POLICY_VERSION
    assert paper.POLICY_VERSION == "cash-bounded-breakout-rotation/4"
    assert block["execution_options"] == {
        **sim_module.LIVE_POLICY,
        "midcycle_redeploy": True,
        "redeploy_buffer": paper.REDEPLOY_BUFFER,
    }
    assert block["redeploy_priced"] is True
    # The first call is the published (hindsight) rules line.
    seen = calls[0]
    assert seen["midcycle_redeploy"] is True
    assert seen["redeploy_buffer"] == paper.REDEPLOY_BUFFER
    assert callable(seen["allocator"])
    row = seen["allocator"](report, report.panel, None, len(report.panel.dates) - 1)
    assert list(row) == [0.25, 0.0, 0.0]
    assert "midcycle_redeploy" not in sim_module.LIVE_POLICY


# Under a policy other than `/4` (the `/3` book, monkeypatched active) the
# published curve is priced exactly as it was before the `/4` allocator was
# wired in: the simulator's built-in targets, the live flags, no redeploy.
# The keyword set is pinned in full so a `/3` record cannot change by a byte.
def test_curve_block_keeps_the_v3_call_unchanged(monkeypatch):
    from backend.agents.trading.desk import event_risk, live_policy, paper
    from backend.agents.trading.desk import simulate as sim_module

    monkeypatch.setattr(live_policy, "ACTIVE", "graded-equal-weight/3")
    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    calls: list[dict] = []

    def fake_run(report, **kwargs):
        calls.append(kwargs)
        return sim

    monkeypatch.setattr(sim_module, "run", fake_run)
    monkeypatch.setattr(
        market_daily, "_candidate_curve", lambda report, sessions: ([], {}, "off")
    )
    block = market_daily.curve_block(report, None)
    assert block["strategy_policy"] == "graded-equal-weight/3"
    assert block["execution_options"] == sim_module.LIVE_POLICY
    assert block["redeploy_priced"] is False
    hindsight, pit = calls
    expected = dict(
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_lifecycle=True,
        **sim_module.LIVE_POLICY,
    )
    for call in (hindsight, pit):
        exposure = call.pop("event_exposure")
        np.testing.assert_array_equal(exposure, event_risk.live_path(report.panel))
    assert hindsight == expected
    assert pit == {**expected, "since": report.panel.dates[0].astype(object)}


# The record names both rules lines for what they are: the hindsight line
# is today's names back-cast and is not an expectation; the point-in-time
# line is the names known at the time under the live executor.
def test_curve_block_labels_the_hindsight_and_point_in_time_lines(monkeypatch):
    from backend.agents.trading.desk import simulate as sim_module

    report = _report()
    sim = sim_module.SimResult(
        dates=report.panel.dates,
        returns=np.array([0.0, 0.05, 0.1]),
        invested=np.zeros(3),
        trades=[],
        rebalances=0,
        equity=np.array([1.0, 1.05, 1.1]),
    )
    monkeypatch.setattr(sim_module, "run", lambda report, **kwargs: sim)
    block = market_daily.curve_block(report, None)
    assert block["universe"] == "hindsight"
    assert block["rules_label"] == market_daily.HINDSIGHT_RULES_LABEL
    assert block["rules_label"] == (
        "today's names back-cast to 2015 (hindsight universe); not an expectation"
    )
    assert block["point_in_time_label"] == market_daily.POINT_IN_TIME_LABEL
    assert block["point_in_time_label"] == "names known at the time, live executor"


# The guarantee behind the published rules lines: element for element, both
# the hindsight `rules` curve and `rules_point_in_time` are `simulate.run`
# with the active policy's allocator (`policy_v5.allocator` since
# 2026-09-29) on the matching book under the live options plus the redeploy
# - the same call the mid-cycle study prices `mc-redeploy` with - and their
# stats are those runs' stats. Before 2026-09-27 a record labelled `/4`
# carried the `/3` book's curve under the `/4` name; the last check here is
# that the `/5` line is not `/4`'s relabelled either.
def test_rules_lines_are_the_active_policy_under_the_live_executor(
    monkeypatch, tmp_path
):
    from backend.agents.trading.desk import (
        event_risk,
        live_policy,
        paper,
        point_in_time,
        policy_v4,
        policy_v5,
        simulate,
    )

    assert live_policy.POLICY is policy_v5
    history = _walk_history(tmp_path)
    _use_history(monkeypatch, history)
    report = _walk_report()
    block = market_daily.curve_block(report, None)
    assert block["point_in_time_note"] == ""
    assert block["strategy_policy"] == policy_v5.POLICY_VERSION
    live = dict(
        use_exits=False,
        rebalance=paper.REBALANCE_EVERY,
        event_exposure=event_risk.live_path(report.panel),
        event_lifecycle=True,
        midcycle_redeploy=True,
        redeploy_buffer=paper.REDEPLOY_BUFFER,
        **simulate.LIVE_POLICY,
    )
    everyone = np.ones((len(report.panel.dates), len(report.panel.tickers)), bool)
    everyone[:, report.panel.index(report.panel.benchmark)] = False
    hindsight = simulate.run(report, allocator=policy_v5.allocator(everyone), **live)
    assert [str(d) for d in hindsight.dates] == block["dates"]
    np.testing.assert_allclose(
        block["rules"], hindsight.equity / hindsight.equity[0] - 1.0, rtol=0, atol=1e-12
    )
    restricted, mask = point_in_time.point_in_time(report, history_path=history)
    pit = simulate.run(
        restricted,
        since=date.fromisoformat(block["dates"][0]),
        allocator=policy_v5.allocator(mask),
        **live,
    )
    np.testing.assert_allclose(
        block["rules_point_in_time"], pit.equity / pit.equity[0] - 1.0, rtol=0, atol=1e-12
    )
    # Not a vacuous match: both books traded, and the restriction changed
    # the line (GGG enters late, FFF leaves early in the walk history).
    assert hindsight.rebalances > 1 and pit.rebalances > 1
    assert np.abs(block["rules"]).max() > 0
    assert block["rules"] != block["rules_point_in_time"]
    for key, value in hindsight.stats().items():
        assert block["stats"][key] == (None if value != value else pytest.approx(value))
    for key, value in pit.stats().items():
        assert block["stats_point_in_time"][key] == (
            None if value != value else pytest.approx(value)
        )
    # And neither is the plainly-priced candidate line: the executor differs.
    assert block["rules_point_in_time"] != block["candidate_point_in_time"]
    # Nor `/4` relabelled: the same executor on `/4`'s allocator draws a
    # different line, because the walk report has sessions with fewer than
    # five A/A+ names, where the two caps disagree.
    v4 = simulate.run(report, allocator=policy_v4.allocator(everyone), **live)
    assert not np.allclose(block["rules"], v4.equity / v4.equity[0] - 1.0)


# The idle cash share is what the plan leaves: cash less the buys plus the
# sells over equity, clipped to [0, 1], None without equity.
def test_idle_cash_share_reads_the_plan():
    from backend.agents.trading.desk import paper

    prices = {"AAA": 100.0, "BBB": 50.0}
    orders = [
        paper.PaperOrder("AAA", "buy", 100, "x"),
        paper.PaperOrder("BBB", "sell", 200, "y"),
    ]
    share = market_daily._idle_cash_share
    assert share(orders, prices, 20_000.0, 100_000.0) == pytest.approx(0.2)
    assert share([], prices, 5_000.0, 100_000.0) == pytest.approx(0.05)
    assert share(orders, prices, 0.0, 100_000.0) == 0.0
    assert share([], prices, 1.0, 0.0) is None
