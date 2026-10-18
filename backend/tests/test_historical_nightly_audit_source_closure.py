"""Synthetic combined CURRENT imports; no original account or model invocation."""

import gzip
import json
import shutil
from copy import deepcopy
from hashlib import sha256
from pathlib import Path

import pytest

from backend.market import historical_conditional_nightly as adapter
from backend.market import live_model_history_stream_audit as audit
from backend.market import original_history_json as streamed

CLOSURE = (
    "live_model_history_stream_audit.py",
    "original_history_json.py",
    "live_model_history_nightly_model.py",
    "live_model_history_pending_audit.py",
    "live_model_history_nightly_audit.py",
    "live_model_history_observation_context.py",
)


# Require each actual transitive audit helper in the CURRENT source declaration.
def test_current_manifest_binds_complete_audit_helper_closure():
    declared = adapter.sources()
    for name in CLOSURE:
        path = "backend/market/" + name
        assert path in declared
    assert audit.streamed is streamed
    assert audit.numerical.streamed is streamed
    assert audit.pending.streamed is streamed
    assert audit.pending.numerical is audit.numerical
    assert audit.controls is audit.numerical.controls


# Alter one private copy at a time and require refusal by the real source verifier.
@pytest.mark.parametrize("name", CLOSURE)
def test_changed_transitive_helper_cannot_reuse_current_declaration(
    tmp_path, monkeypatch, name
):
    original = Path(adapter.__file__).resolve().parents[2]
    files = (*adapter.SOURCES, "backend/market/historical_conditional_nightly.py")
    for relative in files:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / relative, target)
    monkeypatch.setattr(
        adapter,
        "__file__",
        str(tmp_path / "backend/market/historical_conditional_nightly.py"),
    )
    assert adapter.sources() == {
        **adapter.SOURCES,
        "backend/market/historical_conditional_nightly.py": sha256(
            (original / "backend/market/historical_conditional_nightly.py").read_bytes()
        ).hexdigest(),
    }
    target = tmp_path / "backend/market" / name
    with target.open("ab") as output:
        output.write(b"\n# Synthetic dependency-byte corruption.\n")
    with pytest.raises(ValueError, match="Source|source"):
        adapter.sources()


# Compare all ordered independent rows through the combined numerical/parser graph.
def test_current_imports_preserve_full_ordered_history_comparison(tmp_path):
    rows = [
        {"session": "2019-02-28", "qty": 0, "note": "synthetic initial"},
        {"session": "2019-03-01", "qty": 2, "note": "synthetic é"},
    ]
    history = streamed.History(tmp_path / "derived")
    for row in rows:
        history.record(row)
    expected = {"cash": 99980.0, "pending": [], "history": []}
    actual = {**deepcopy(expected), "history": deepcopy(rows)}
    audit.numerical.compare_state(
        actual, expected, "Synthetic combined state", history=history
    )
    assert audit.digest({**expected, "history": history.view()}) == audit.digest(actual)
    actual["history"][0]["qty"] = 1
    with pytest.raises(ValueError):
        audit.numerical.compare_state(
            actual, expected, "Changed initial row", history=history
        )


# Read exact opaque archive bytes without permitting a physical nonfinite projection.
def test_current_pending_archive_reference_preserves_raw_identity(tmp_path):
    value = {
        "session": "2019-03-01",
        "forecast_decisions": [],
        "observations": [],
        "attempts": [],
        "paper_state": {"history": [{"session": "2019-02-28"}]},
    }
    path = tmp_path / "synthetic.json.gz"
    raw = gzip.compress(json.dumps(value).encode(), mtime=0)
    path.write_bytes(raw)
    digest = sha256(raw).hexdigest()
    evidence = audit.pending.OriginalProxyEvidence(
        streamed.ArchiveRef(path, digest), digest, audit.pending.ORIGINAL_SOURCES
    )
    assert evidence.records(value["session"]) == {
        key: [] for key in ("forecast_decisions", "observations", "attempts")
    }
    assert path.read_bytes() == raw
    path.write_bytes(raw + b"changed")
    with pytest.raises(ValueError):
        evidence.records(value["session"])
