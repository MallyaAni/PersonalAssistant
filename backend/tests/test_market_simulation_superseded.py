"""The chart keeps an audited replay after a release replaced its bound sources."""

import json
from unittest.mock import patch

import pytest

from backend.api.v1 import market_simulation
from backend.market import strategy_history_publication as history
from backend.tests.test_strategy_history_publication import original


@pytest.fixture
def installed(tmp_path):
    source, binding, stock, _, _ = original(tmp_path)
    history.import_original(
        tmp_path,
        source,
        binding,
        manifest_sha256=binding["history_sha256"],
        audit_path=tmp_path / "audit.json",
        audit_sha256=binding["audit_sha256"],
    )
    return tmp_path, stock


# The audited bytes are served with their own policy and marked as no longer
# bound to the installed strategy; nothing in the decisions changes.
def test_superseded_history_serves_the_audited_replay(installed):
    root, stock = installed
    value = market_simulation._superseded_history(root, "AAA")
    assert value["decisions"] == stock["decisions"]
    assert value["policy"] == "grade-led-learned-sizing/1"
    assert value["provenance"]["verified_against_installed_strategy"] is False
    assert value["provenance"]["strategy_binding"] == "superseded"
    assert (
        value["provenance"]["strategy_contract"]["schema"]
        == "strategy-history-economics-binding/1"
    )
    assert value["grade_rows"][-1]["at"] == "2026-10-20T09:30:00-04:00"


# Every byte and accounting check the sealed reader makes still applies.
def test_superseded_history_refuses_altered_bytes(installed):
    root, _ = installed
    folder = next(p for p in (root / history.DIRECTORY).iterdir() if p.is_dir())
    with pytest.raises(ValueError, match="covered history ticker"):
        market_simulation._superseded_history(root, "ZZZ")
    (folder / "AAA.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="stock history bytes differ"):
        market_simulation._superseded_history(root, "AAA")
    audit = json.loads((folder / "audit.json").read_bytes())
    audit["status"] = "UNVERIFIED"
    (folder / "audit.json").write_bytes(json.dumps(audit, sort_keys=True).encode())
    with pytest.raises(ValueError, match="selected history publication differs"):
        market_simulation._superseded_history(root, "AAA")


# The route falls back to the superseded read only when the sealed reader refuses.
@pytest.mark.anyio
async def test_view_falls_back_when_the_binding_is_refused(installed, monkeypatch):
    root, stock = installed
    monkeypatch.setattr(market_simulation.settings, "MARKET_DATA_ROOT", str(root))
    monkeypatch.setattr(market_simulation, "_operator_only", lambda user_id: None)

    class Response:
        headers = {}

    def refused(*args, **kwargs):
        raise ValueError(
            "Original audited history economics differ from installed strategy"
        )

    with patch.object(history, "read", side_effect=refused):
        value = await market_simulation.view("vjmallya", Response(), "AAA")
    # The route stamps the frozen-model boundary on each served row.
    served = [
        {k: v for k, v in row.items() if k != "sample"} for row in value["decisions"]
    ]
    assert served == stock["decisions"]
    assert value["provenance"]["strategy_binding"] == "superseded"
    with (
        patch.object(history, "read", side_effect=refused),
        pytest.raises(market_simulation.HTTPException),
    ):
        await market_simulation.view("vjmallya", Response(), None)
