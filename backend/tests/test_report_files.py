"""Optional report files: atomic, and a failed write never escapes.

What has to hold: a write lands whole or not at all (no temporary file is
left behind); a write that fails, because the target is not writable,
returns False and prints why instead of raising; the FOMC gate, the
execution series and the reversal shadow all go through it, so an
injected write failure in any of them leaves the nightly free to save
its record.
"""

import json

import numpy as np

from backend.agents.trading.desk import paper
from backend.market import execution_quality, fomc_gate, report_files, reversal
from backend.market.panel import Panel


def test_write_is_atomic_and_leaves_no_temporary_file(tmp_path):
    target = tmp_path / "block.json"
    assert report_files.write_json(target, {"a": 1}, "test")
    assert json.loads(target.read_text(encoding="utf-8")) == {"a": 1}
    assert [p.name for p in tmp_path.iterdir()] == ["block.json"]


def test_a_failed_write_is_reported_not_raised(tmp_path, capsys):
    blocker = tmp_path / "desk"
    blocker.write_text("a file where a directory is needed", encoding="utf-8")
    assert not report_files.write_json(blocker / "x.json", {"a": 1}, "test block")
    assert "test block: not written" in capsys.readouterr().out


# The injection Codex used: the filesystem write fails after the block is
# computed. Each writer returns None and prints; nothing propagates.
def test_injected_write_failures_do_not_escape_the_report_writers(
    tmp_path, monkeypatch, capsys
):
    def refuse(target, block, label):
        print(f"\n{label}: not written (injected)")
        return False

    monkeypatch.setattr(report_files, "write_json", refuse)
    paper.save_state(tmp_path, paper.PaperState())
    assert execution_quality.write(tmp_path) is None
    assert fomc_gate.write(tmp_path, store=_EmptyStore()) is None
    panel = _panel()
    assert reversal.write(tmp_path, panel, [], set()) is None
    out = capsys.readouterr().out
    assert out.count("not written") >= 3


class _EmptyStore:
    def read_frame(self, kind, ticker, asof=None):
        return None


def _panel() -> Panel:
    t, n = 30, 3
    close = np.full((t, n + 1), 100.0)
    dates = np.array(
        [np.datetime64("2026-09-01") + np.timedelta64(i, "D") for i in range(t)],
        dtype="datetime64[D]",
    )
    return Panel(
        dates=dates,
        tickers=("A", "B", "C", "SPY"),
        open=close,
        high=close,
        low=close,
        close=close,
        adj_close=close.copy(),
        volume=close,
        themes={},
        benchmark="SPY",
    )
