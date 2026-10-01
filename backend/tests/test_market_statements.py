"""The A2 study's command line: resumable scoring and the evaluate step.

What has to hold: records round-trip through the partial file and the
frame; a name's observations are scored once each and stored as one frame
with the partial removed; a rerun resumes from the partial and calls only
the unscored quarters; a failed call keeps the successes in the partial,
writes no frame and raises; a past deadline calls nothing; a prior
partition under another prompt version carries nothing forward and an
incompatible frame in the partition is refused rather than overwritten;
the plan step counts one call per observation; the null test passes on a
constant arm and the evaluate step measures a real arm against its
comparators on shared cells with the plan's criteria; the accuracy report
tallies the model against the realised direction and the persistence
baseline.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from backend.agents.trading.statement_reader import StatementCall
from backend.cli import market_statements as ms
from backend.market import fundamentals_asof as fa
from backend.market import statements as st
from backend.market.panel import Panel
from backend.tests.test_statements import filer

ASOF = date(2026, 10, 1)


class FakeStore:
    """An in-memory stand-in for MarketStore's frame methods."""

    def __init__(self, root, versions=None):
        self.root = root
        self.frames = {}
        if versions is not None:
            self.frames[(fa.KIND, "AAA", date(2026, 1, 1))] = (
                fa.frame(versions),
                {},
            )

    def _latest(self, kind, ticker, asof):
        found = [
            (d, v)
            for (k, t, d), v in self.frames.items()
            if k == kind and t == ticker and (asof is None or d <= asof)
        ]
        if not found:
            return None
        return max(found, key=lambda kv: kv[0])[1]

    def read_frame(self, kind, ticker, asof=None):
        return self._latest(kind, ticker, asof)

    def has_frame(self, kind, asof, ticker):
        return (kind, ticker, asof) in self.frames

    def write_frame(self, kind, asof, ticker, columns, metadata=None):
        if (kind, ticker, asof) in self.frames:
            return False
        self.frames[(kind, ticker, asof)] = (columns, metadata or {})
        return True


class Reader:
    """A fake reader answering a fixed probability, or None after `fail_after`."""

    def __init__(self, probability=0.7, fail_after=None):
        self.probability = probability
        self.fail_after = fail_after
        self.blocks = []

    def call_sync(self, block):
        self.blocks.append(block)
        if self.fail_after is not None and len(self.blocks) > self.fail_after:
            return None
        return StatementCall(
            "up" if self.probability >= 0.5 else "down",
            self.probability,
            "Trend up. Margins hold. Risk is seasonality.",
        )


def record(quarter_end=date(2016, 12, 31), probability=0.7, version="statements/1"):
    return ms.StatementRecord(
        quarter_end=quarter_end,
        available=quarter_end + timedelta(days=41),
        direction="up" if probability >= 0.5 else "down",
        probability=probability,
        rationale="Trend up. Margins hold. Risk is seasonality.",
        block_sha256="abc",
        lines_present=11,
        anchor="net_income",
        model="m",
        prompt_version=version,
        consistent=True,
    )


def test_records_round_trip_through_the_partial_and_the_frame(tmp_path):
    rows = [record(), record(date(2017, 3, 31), 0.4)]
    partial = ms.partial_path(tmp_path, ASOF, "AAA")
    for r in rows:
        ms.append_partial(partial, r)
    assert list(ms.read_partial(partial).values()) == rows
    assert list(ms.records_from_frame(ms.statement_frame(rows))) == rows
    assert rows[1].stance == pytest.approx(-0.1)


def test_a_name_is_scored_once_per_observation_and_stored_as_one_frame(tmp_path):
    store = FakeStore(tmp_path, filer())
    reader = Reader()
    scored, failed, stored = ms.score_ticker(store, "AAA", ASOF, [reader], "m")
    assert (scored, failed, stored) == (5, 0, 5)
    assert len(reader.blocks) == 5
    columns, meta = store.read_frame(st.KIND, "AAA", ASOF)
    records = ms.records_from_frame(columns)
    assert [r.quarter_end for r in records] == [
        o.quarter_end for o in st.observations(filer())
    ]
    assert all(
        r.probability == 0.7 and r.prompt_version == "statements/1" for r in records
    )
    assert meta["observations"] == "5"
    assert meta["inconsistent"] == "0"
    assert not ms.partial_path(tmp_path, ASOF, "AAA").exists()
    # A second run keeps the frame and calls nothing.
    again = Reader()
    assert ms.score_ticker(store, "AAA", ASOF, [again], "m") == (0, 0, 5)
    assert again.blocks == []


def test_a_rerun_resumes_from_the_partial(tmp_path):
    store = FakeStore(tmp_path, filer())
    rows = st.observations(filer())
    partial = ms.partial_path(tmp_path, ASOF, "AAA")
    ms.append_partial(partial, record(rows[0].quarter_end, 0.3))
    reader = Reader()
    scored, _failed, stored = ms.score_ticker(store, "AAA", ASOF, [reader], "m")
    assert scored == 4
    assert stored == 5
    assert len(reader.blocks) == 4
    records = ms.records_from_frame(store.read_frame(st.KIND, "AAA", ASOF)[0])
    assert records[0].probability == 0.3
    assert all(r.probability == 0.7 for r in records[1:])


def test_a_failed_call_keeps_the_partial_and_writes_no_frame(tmp_path):
    store = FakeStore(tmp_path, filer())
    reader = Reader(fail_after=2)
    with pytest.raises(RuntimeError, match="3 failures"):
        ms.score_ticker(store, "AAA", ASOF, [reader], "m")
    assert store.read_frame(st.KIND, "AAA", ASOF) is None
    assert len(ms.read_partial(ms.partial_path(tmp_path, ASOF, "AAA"))) == 2


def test_a_past_deadline_calls_nothing(tmp_path):
    store = FakeStore(tmp_path, filer())
    reader = Reader()
    with pytest.raises(RuntimeError, match="5 failures"):
        ms.score_ticker(store, "AAA", ASOF, [reader], "m", deadline=0.0)
    assert reader.blocks == []


def test_a_prior_partition_under_another_version_carries_nothing(tmp_path):
    store = FakeStore(tmp_path, filer())
    earlier = ASOF - timedelta(days=30)
    store.write_frame(
        st.KIND,
        earlier,
        "AAA",
        ms.statement_frame([record(version="statements/0")]),
        {"prompt_version": "statements/0", "model": "m"},
    )
    assert ms.prior_records(store, "AAA", ASOF, "m") == {}
    store.write_frame(
        st.KIND,
        earlier + timedelta(days=1),
        "AAA",
        ms.statement_frame([record()]),
        {"prompt_version": "statements/1", "model": "m"},
    )
    assert list(ms.prior_records(store, "AAA", ASOF, "m")) == [date(2016, 12, 31)]
    reader = Reader()
    scored, _f, stored = ms.score_ticker(store, "AAA", ASOF, [reader], "m")
    assert scored == 4
    assert stored == 5


def test_an_incompatible_frame_in_the_partition_is_refused(tmp_path):
    store = FakeStore(tmp_path, filer())
    store.write_frame(
        st.KIND,
        ASOF,
        "AAA",
        ms.statement_frame([record(version="statements/0")]),
        {"prompt_version": "statements/0", "model": "m"},
    )
    with pytest.raises(RuntimeError, match="incompatible"):
        ms.current_frame_exists(store, "AAA", ASOF, "m")


def test_a_name_without_versions_is_reported_not_scored(tmp_path):
    store = FakeStore(tmp_path)
    assert ms.score_ticker(store, "AAA", ASOF, [Reader()], "m") == (0, 0, -1)


def test_the_plan_counts_one_call_per_observation(tmp_path, capsys):
    store = FakeStore(tmp_path, filer())
    out = ms.run_plan(store, ("AAA", "BBB"), None, tmp_path / "blocks.jsonl")
    assert out == {"AAA": 5, "BBB": -1}
    assert "5 model calls over 1 names" in capsys.readouterr().out
    lines = (tmp_path / "blocks.jsonl").read_text().splitlines()
    assert len(lines) == 5
    # An observation available before --since is not planned or scored.
    later = ms.run_plan(store, ("AAA",), None, None, since=date(2017, 6, 1))
    assert later == {"AAA": 3}
    reader = Reader()
    assert (
        ms.score_ticker(store, "AAA", ASOF, [reader], "m", since=date(2017, 6, 1))[2]
        == 3
    )


# A synthetic panel: `names` random-walk names plus SPY, `rows` sessions.
def _panel(rows=600, names=20, seed=0):
    rng = np.random.default_rng(seed)
    steps = rng.normal(0, 0.02, size=(rows, names + 1))
    close = 100.0 * np.exp(np.cumsum(steps, axis=0))
    dates = np.array(
        [date(2024, 1, 1) + timedelta(days=i) for i in range(rows)],
        dtype="datetime64[D]",
    )
    tickers = tuple(f"N{i}" for i in range(names)) + ("SPY",)
    return Panel(
        dates=dates,
        tickers=tickers,
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close,
        volume=np.full_like(close, 1e6),
        themes={t: () for t in tickers if t != "SPY"},
        benchmark="SPY",
    )


def _windows(panel):
    return {
        "in_window": (date(2024, 1, 1), date(2025, 2, 28)),
        "post_window": (date(2025, 3, 1), None),
    }


def test_the_null_test_passes_on_a_constant_arm(monkeypatch):
    panel = _panel()
    monkeypatch.setattr(ms, "WINDOWS", _windows(panel))
    in_book = np.array([t != "SPY" for t in panel.tickers])
    observed = np.ones(panel.close.shape, dtype=bool) & in_book[None, :]
    result = ms.null_test(panel, observed, in_book)
    assert result["pass"], result
    assert result["checks"][-1]["stance_table_empty"]
    assert all(c["defined_periods"] == 0 for c in result["checks"][:-1])


def test_evaluate_measures_the_arm_against_comparators_on_shared_cells(monkeypatch):
    panel = _panel()
    monkeypatch.setattr(ms, "WINDOWS", _windows(panel))
    rng = np.random.default_rng(1)
    shape = panel.close.shape
    arm = rng.uniform(-0.5, 0.5, size=shape)
    arm[:, -1] = np.nan
    comparators = {
        ms.ARM_FUNDAMENTAL: rng.uniform(0, 1, size=shape),
        ms.ARM_VALUE: rng.uniform(0, 1, size=shape),
    }
    sides = {t: "ai" for t in panel.tickers if t != "SPY"}
    payload = ms.evaluate_arm(panel, sides, arm, comparators)
    assert payload["null_test"]["pass"]
    window = payload["horizons"]["20"]["in_window"]
    assert set(window["arms"]) == {ms.ARM_A2, ms.ARM_FUNDAMENTAL, ms.ARM_VALUE}
    assert ms.ARM_A2 in window["paired_vs_fundamental"]
    assert ms.ARM_VALUE in window["paired_vs_fundamental"]
    assert set(window["correlation_with"]) == {ms.ARM_FUNDAMENTAL, ms.ARM_VALUE}
    assert window["cells"] == 20 * int(
        ms.window_mask(panel.dates, *_windows(panel)["in_window"]).sum()
    )
    crit = payload["criteria"]
    assert set(crit["correlation_with"]) == {ms.ARM_FUNDAMENTAL, ms.ARM_VALUE}
    assert payload["verdict"] in ("RECORD",) or payload["verdict"].startswith(
        "CANDIDATE"
    )
    table = ms.stance_table(panel, arm)
    assert table["ticker"]
    assert set(table["stance"]) <= {-1, 1}


def test_criteria_and_verdict_follow_the_plan():
    def block(ic, t, delta, pt, corr_f, corr_v, ic_post=0.0, t_post=0.0):
        return {
            "in_window": {
                "arms": {ms.ARM_A2: {"ic": ic, "t": t}},
                "paired_vs_fundamental": {ms.ARM_A2: {"delta": delta, "t": pt}},
                "correlation_with": {
                    ms.ARM_FUNDAMENTAL: {ms.ARM_A2: {"mean": corr_f}},
                    ms.ARM_VALUE: {ms.ARM_A2: {"mean": corr_v}},
                },
            },
            "post_window": {"arms": {ms.ARM_A2: {"ic": ic_post, "t": t_post}}},
        }

    crit = ms.criteria(block(0.03, 2.5, 0.01, 0.5, 0.1, -0.05))
    assert crit["1_clears_ic_floor"]
    assert crit["2_post_window_not_negative"]
    assert crit["3_not_worse_than_fundamental"]
    assert crit["role"] == "sixth analyst"
    assert ms.verdict(crit, True).startswith("CANDIDATE (sixth analyst)")
    assert ms.verdict(crit, False).startswith("INVALID")
    # Correlated with the fundamental analyst: a replacement candidate.
    crit = ms.criteria(block(0.03, 2.5, 0.01, 0.5, 0.6, 0.1))
    assert crit["role"] == f"replacement candidate for the {ms.ARM_FUNDAMENTAL}"
    # Below the floor, or negative post-cutoff at t <= -1, or worse than the
    # fundamental analyst at t <= -1: RECORD.
    assert (
        ms.verdict(ms.criteria(block(0.01, 2.5, 0.0, 0.0, 0.1, 0.1)), True) == "RECORD"
    )
    assert (
        ms.verdict(
            ms.criteria(
                block(0.03, 2.5, 0.0, 0.0, 0.1, 0.1, ic_post=-0.02, t_post=-1.5)
            ),
            True,
        )
        == "RECORD"
    )
    assert (
        ms.verdict(ms.criteria(block(0.03, 2.5, -0.02, -1.5, 0.1, 0.1)), True)
        == "RECORD"
    )
    # A post-cutoff IC that is negative but not at t <= -1 does not block.
    crit = ms.criteria(block(0.03, 2.5, 0.0, 0.0, 0.1, 0.1, ic_post=-0.02, t_post=-0.4))
    assert crit["2_post_window_not_negative"]


def test_the_accuracy_report_tallies_the_model_against_the_realised_sign():
    net = [10, 20, 30, 40, 50, 60, 70, 80, 45, 100, 110, 120]
    from backend.tests.test_statements import flow_rows

    rows = st.observations(filer(NetIncomeLoss=flow_rows([v * 1e6 for v in net])))
    # The model says "up" for every quarter; the first realised YoY is down.
    records = {"AAA": tuple(record(r.quarter_end, 0.7) for r in rows)}
    report = ms.accuracy_report(records, {"AAA": rows})
    block = report["windows"]["all"]
    assert block["n"] == 4  # the last observation has no next quarter
    assert block["correct"] == 3
    assert block["accuracy"] == pytest.approx(0.75)
    # Persistence (the sign of each observation's own Q8 - Q4) is wrong on
    # the first two (80 > 40 before the dip; 45 < 50 before the rebound)
    # and right on the last two.
    assert block["persistence_accuracy"] == pytest.approx(0.5)
    assert block["sequential_n"] == 4
    assert block["sequential_correct"] == 3
    assert report["paper_accuracy"] == 0.604
    # Every observation here is in-window (available before 2025-06).
    assert report["windows"]["in_window"]["n"] == 4
    assert report["windows"]["post_window"]["n"] == 0


def test_arm_stances_align_records_to_the_panel():
    panel = _panel(rows=30, names=16)
    records = {
        "N0": (record(date(2023, 12, 31), 0.9),),  # available 2024-02-10
        "N1": (record(date(2023, 11, 30), 0.2),),  # available 2024-01-10
    }
    arm = ms.arm_stances(panel, records)
    assert np.isnan(arm[:9, 1]).all()
    assert arm[9, 1] == pytest.approx(-0.3)
    assert np.isnan(arm[:, 0]).all()  # N0 is available after the panel ends
    assert np.isnan(arm[:, 2]).all()
