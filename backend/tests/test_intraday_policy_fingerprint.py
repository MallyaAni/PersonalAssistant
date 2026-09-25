"""Keep a behavior-setting regime dependency in the selected policy digest.

Fresh subprocesses bind each source variant before the candidate's by-value
import. This tests one known dependency, not a complete runtime attestation.
"""

import ast
import hashlib
import importlib.abc
import importlib.util
import json
import os
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

BUILDER = "market/intraday_research.py"
REGIME = "agents/trading/desk/regime.py"
PREVIOUS_INPUTS = (
    "agents/trading/desk/intraday_candidate.py",
    "agents/trading/desk/portfolio_candidate.py",
    "agents/trading/desk/entry.py",
    "agents/trading/desk/paper.py",
    "agents/trading/desk/risk.py",
    "agents/trading/desk/grading.py",
    "market/sizing.py",
    "market/holdings.py",
    "market/decision_view.py",
    "market/entry_evidence.py",
    "market/calendar.py",
    "market/data/nyse_holidays.json",
    "market/data/nyse_early_closes.json",
    "market/data/nyse_historical_sessions.json",
    "market/desk_freshness.py",
    "market/opportunity.py",
    BUILDER,
)


# Find the source tuple the actual builder consumes, without recreating its hash.
def _policy_inputs(source):
    tree = ast.parse(source)
    build = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "build"
    )
    assignment = next(
        node
        for node in build.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Subscript)
        and isinstance(node.targets[0].slice, ast.Constant)
        and node.targets[0].slice.value == "policy_sha256"
    )
    tuples = [
        node
        for node in ast.walk(assignment)
        if isinstance(node, ast.Tuple)
        and node.elts
        and all(
            isinstance(item, ast.Constant) and isinstance(item.value, str)
            for item in node.elts
        )
    ]
    assert len(tuples) == 1
    return tuple(item.value for item in tuples[0].elts)


# Change exactly the AST-located cap literal in the temporary regime source.
def _changed_cap(source):
    assignments = [
        node
        for node in ast.parse(source).body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TIGHTENING_EXPOSURE"
            for target in node.targets
        )
    ]
    assert len(assignments) == 1
    value = assignments[0].value
    original = ast.literal_eval(value)
    assert isinstance(original, (int, float))
    assert 0 < original <= 1
    alternate = original / 3
    lines = source.splitlines(keepends=True)
    assert value.lineno == value.end_lineno
    line = lines[value.lineno - 1]
    old_literal = line[value.col_offset : value.end_col_offset]
    assert ast.literal_eval(old_literal) == original
    lines[value.lineno - 1] = (
        line[: value.col_offset] + repr(alternate) + line[value.end_col_offset :]
    )
    changed = "".join(lines)
    assert changed != source
    return changed, alternate


# Load only the two source variants before their first import in a fresh process.
class _SourceOverride(importlib.abc.MetaPathFinder):
    # Retain the temporary source paths without modifying the repository package.
    def __init__(self, root):
        self.paths = {
            "backend.market.intraday_research": root / BUILDER,
            "backend.agents.trading.desk.regime": root / REGIME,
        }

    # Let normal imports resolve every module except the two explicit variants.
    def find_spec(self, fullname, path=None, target=None):
        if fullname in self.paths:
            return importlib.util.spec_from_file_location(
                fullname, self.paths[fullname]
            )
        return None


# Write strict JSON evidence only into the test's fresh temporary directory.
def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, allow_nan=False)


# Exercise the real builder with a synthetic panel and fixed non-fetching clocks.
def _build_variant(source_root, output):
    sys.meta_path.insert(0, _SourceOverride(source_root))
    from backend.agents.trading.desk import intraday_candidate, regime
    from backend.market import intraday_research
    from backend.tests.test_intraday_candidate import inputs

    assert Path(regime.__file__) == source_root / REGIME
    assert Path(intraday_research.__file__) == source_root / BUILDER
    assert intraday_candidate.TIGHTENING_EXPOSURE == regime.TIGHTENING_EXPOSURE
    record, snapshot, economic, panel, now = inputs()
    known = panel.dates <= np.datetime64(record["session"])
    history = replace(
        panel,
        dates=panel.dates[known],
        **{
            name: getattr(panel, name)[known].copy()
            for name in ("open", "high", "low", "close", "adj_close", "volume")
        },
    )
    _write_json(output / "store/desk/economics/latest.json", economic)
    rows = []
    with patch.object(intraday_research, "book_panel", return_value=(history, {})):
        for index in range(3):
            observed = now + timedelta(minutes=15 * index)
            current = deepcopy(snapshot)
            current["as_of"] = observed.isoformat()
            for quote in current["quotes"].values():
                quote["bar"] = (observed - timedelta(minutes=16)).isoformat()
            row = intraday_research.build(output / "store", record, current, observed)
            assert row["macro"]["defensive"] is True
            assert row["macro"]["exposure"] == min(
                record["regime"]["exposure"], regime.TIGHTENING_EXPOSURE
            )
            assert "execution_quotes" not in row
            rows.append(row)
    _write_json(output / "decisions.json", rows)


# Build both source-backed policies once, retaining subprocess logs and source bytes.
@pytest.fixture(scope="module")
def source_variants(tmp_path_factory):
    backend = Path(__file__).resolve().parents[1]
    root = tmp_path_factory.mktemp("intraday-policy-sources")
    names = _policy_inputs((backend / BUILDER).read_text())
    before = {
        name: (backend / name).read_bytes() for name in dict.fromkeys((*names, REGIME))
    }
    changed, alternate = _changed_cap(before[REGIME].decode())
    outputs = []
    manifests = []
    for label in ("original", "changed"):
        directory = root / label
        source_root = directory / "backend"
        for name, content in before.items():
            path = source_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                changed.encode() if label == "changed" and name == REGIME else content
            )
        environment = {
            **os.environ,
            "ANIOS_TEST_MODE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPYCACHEPREFIX": str(directory / "pycache"),
            "PYTHONPATH": os.pathsep.join(
                (str(backend.parent), os.environ.get("PYTHONPATH", ""))
            ),
        }
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                str(Path(__file__).resolve()),
                "--build-variant",
                str(source_root),
                str(directory),
            ],
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        (directory / "stdout.txt").write_text(result.stdout)
        (directory / "stderr.txt").write_text(result.stderr)
        assert result.returncode == 0, result.stdout + result.stderr
        outputs.append(json.loads((directory / "decisions.json").read_text()))
        manifests.append(
            {
                name: hashlib.sha256((source_root / name).read_bytes()).hexdigest()
                for name in before
            }
        )
    assert [name for name in before if manifests[0][name] != manifests[1][name]] == [
        REGIME
    ]
    assert {name: (backend / name).read_bytes() for name in before} == before
    _write_json(
        root / "manifest.json",
        {"sources": manifests, "inputs": names, "alternate_cap": alternate},
    )
    return names, outputs[0], outputs[1]


# Keep all earlier selected dependencies in their original relative order.
def test_regime_is_added_without_dropping_existing_inputs(source_variants):
    names, _, _ = source_variants
    assert tuple(name for name in names if name in PREVIOUS_INPUTS) == PREVIOUS_INPUTS
    assert REGIME in names


# Identical data under genuinely different cap source must have distinct identities.
def test_behavior_source_change_changes_builder_policy_hash(source_variants):
    _, original, changed = source_variants
    for before, after in zip(original, changed, strict=True):
        assert before["version"] == after["version"]
        assert before["input_sha256"] == after["input_sha256"]
        assert before["record_sha256"] == after["record_sha256"]
        assert before["entry_evidence"] == after["entry_evidence"]
        assert before["technical_targets"] == after["technical_targets"]
        assert before["macro"]["exposure"] != after["macro"]["exposure"]
        assert before["targets"] != after["targets"]
        assert before["policy_sha256"] != after["policy_sha256"]


# Preserve real source-built decisions through the publisher's first-candle rule.
def _publish_variants(root, original, changed, monkeypatch):
    from backend.market import intraday_research

    # Supply real source-built results without invoking publication's live clock.
    def built(*args):
        return deepcopy(selected)

    monkeypatch.setattr(intraday_research, "build", built)
    selected = original[0]
    first = intraday_research.publish(root, {}, {})
    archive = next((root / "desk/intraday-research").glob("decision-*.json"))
    first_bytes = archive.read_bytes()
    selected = changed[0]
    assert intraday_research.publish(root, {}, {}) == first
    assert archive.read_bytes() == first_bytes
    for selected in changed[1:]:
        assert intraday_research.publish(root, {}, {})["bar"] == selected["bar"]
    assert archive.read_bytes() == first_bytes


# Supply labelled synthetic corporate-action coverage through real local Parquet I/O.
def _save_action_coverage(root, prices):
    from backend.market.store import MarketStore
    from backend.market.yahoo import DailyBar, TickerHistory
    from backend.tests.test_intraday_candidate import inputs

    store = MarketStore(root)
    day = date(2026, 9, 14)
    *_, clock = inputs()
    for symbol, price in prices.items():
        history = TickerHistory(
            ticker=symbol,
            bars=(DailyBar(day, price, price, price, price, price, 100000),),
            actions=(),
            complete_through=day,
            source_time=clock.replace(hour=21),
            source="synthetic-policy-fingerprint-test",
        )
        assert store.write(day, history)


# Separate later source-policy candles without rewriting the first candle or old rows.
@pytest.mark.parametrize("require_actions", [False, True])
def test_saved_policies_remain_separate_in_report(
    source_variants, tmp_path, monkeypatch, require_actions
):
    from backend.market import forward_evidence

    _, original, changed = source_variants
    _publish_variants(tmp_path, original, changed, monkeypatch)
    folder = tmp_path / "desk/intraday-research"
    before = {path.name: path.read_bytes() for path in folder.glob("decision-*.json")}
    assert len(before) == 3
    if require_actions:
        _save_action_coverage(tmp_path, original[0]["prices"])
    result = forward_evidence.report(tmp_path, require_actions=require_actions)
    _write_json(tmp_path / "report.json", result)
    assert {
        path.name: path.read_bytes() for path in folder.glob("decision-*.json")
    } == before
    assert result["status"] == "collecting_forward_evidence"
    assert len(result["versions"]) == 2
    assert sorted(group["decision_count"] for group in result["versions"]) == [1, 2]
    assert all(group["pending_daily_validation"] == 0 for group in result["versions"])


if __name__ == "__main__":
    assert len(sys.argv) == 4
    assert sys.argv[1] == "--build-variant"
    _build_variant(Path(sys.argv[2]), Path(sys.argv[3]))
