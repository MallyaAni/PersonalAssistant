"""Published strategy percentages never depend on current paper or personal accounts."""

import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from backend.api.v1 import market_allocation
from backend.market import market_phase
from backend.market import model_allocation_view as view
from backend.market import strategy_publication as publication
from backend.tests.test_live_model_decision import NOW, admitted
from backend.tests.test_strategy_publication import CONFIG, snapshot
from backend.tests.test_strategy_publication import NOW as PUBLISHED_AT


# Return authenticated targets, including zero, without loading an account.
def test_original_percentages_are_account_independent(monkeypatch):
    from backend.agents.trading.desk import paper
    from backend.market import alpaca_trading

    record, _, _, _ = admitted(monkeypatch)
    before = deepcopy(record)

    # Any current-account access violates the shared allocation reader's contract.
    def forbidden(*args, **kwargs):
        pytest.fail("Published model percentages must not load a current account")

    monkeypatch.setattr(paper, "load_state", forbidden)
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    result = view.read("unused", record, NOW)
    assert result["status"] == "available"
    assert result["basis"] == (
        "original_published_strategy_allocation_not_trade_quantity"
    )
    assert result["record_sha256"] == "a" * 64
    assert result["rows"] == {
        name: {"target_weight": float(value)}
        for name, value in record["targets"]["weights"].items()
    }
    assert result["rows"]["DDD"]["target_weight"] == 0
    assert result["rows"]["BBB"]["target_weight"] == 0.25
    assert record == before


# Never expose expired percentages as a current allocation.
def test_expired_plan_has_no_current_sizes(monkeypatch):
    record, _, _, _ = admitted(monkeypatch)

    # Expiry needs no expensive source/model artifact read.
    def forbidden(*args):
        pytest.fail("Expired allocations need no source materialization")

    monkeypatch.setattr(view.live_model_decision, "_authenticate", forbidden)
    result = view.read(
        "unused", record, datetime.fromisoformat("2026-10-19T18:00:00-04:00")
    )
    assert result["status"] == "stale"
    assert result["rows"] == {}
    assert "expired" in result["reason"]


# Preserve original-receipt validation for every displayed numeric target.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("weight", True),
        ("weight", float("nan")),
        ("weight", -0.1),
        ("weight", 1.1),
        ("policy", "other"),
        ("source", "0" * 64),
    ],
)
def test_corrupt_saved_allocation_is_unavailable(monkeypatch, field, value):
    record, _, _, _ = admitted(monkeypatch)
    if field == "weight":
        record["targets"]["weights"]["BBB"] = value
    elif field == "policy":
        record["targets"]["policy"] = value
    else:
        record["paper"]["joint_funded"]["receipt"]["source_sha256"] = value
    result = view.read("unused", record, NOW)
    assert result["status"] == "unavailable"
    assert result["rows"] == {}


# Publish the shared synthetic snapshot with its installed cost fixture.
def publish_fixture(tmp_path, monkeypatch):
    value = snapshot()
    publication.publish(tmp_path, value, PUBLISHED_AT)
    monkeypatch.setattr(
        publication.learned_live_holding,
        "read_configuration",
        lambda root, at: (CONFIG, {"cost_bps": 10}),
    )
    return value


# A current publication still serves the original snapshot unchanged.
def test_current_publication_is_unchanged(monkeypatch, tmp_path):
    value = publish_fixture(tmp_path, monkeypatch)
    result = market_allocation.allocation(tmp_path, PUBLISHED_AT)
    assert result == {
        **value,
        "entry_assessment": {
            "version": "strategy-numerical-entries/1",
            "status": "unavailable",
            "rows": {},
            "reason": "Fresh numerical 15-minute observation required",
        },
        "recorded_history_version": "strategy-recorded-entries/1",
        "market_phase": market_phase.describe(PUBLISHED_AT),
    }


# A verified snapshot past its close waits for the nightly with no current rows.
def test_expired_publication_awaits_the_nightly(monkeypatch, tmp_path):
    value = publish_fixture(tmp_path, monkeypatch)
    expired_at = datetime.fromisoformat("2026-01-07T17:00:00-05:00")
    result = market_allocation.allocation(tmp_path, expired_at)
    assert result == {
        "version": publication.VERSION,
        "status": "awaiting_nightly",
        "policy": value["policy"],
        "rows": {},
        "expired_at": value["valid_until"],
        "next_publication_at": "2026-01-07T19:30:00-05:00",
        "last_session": value["session"],
        "last_rows": value["rows"],
        "as_of": expired_at.isoformat(),
        "valid_until": None,
        "market_phase": market_phase.describe(expired_at),
    }


# A re-signed but inconsistent snapshot stays unavailable, not awaiting the nightly.
def test_tampered_expired_publication_is_unavailable(monkeypatch, tmp_path):
    publish_fixture(tmp_path, monkeypatch)
    folder = tmp_path / publication.DIRECTORY
    pointer = json.loads((folder / "latest.json").read_bytes())
    path = folder / (pointer["snapshot_id"] + ".json")
    changed = json.loads(path.read_bytes())
    changed["rows"]["AAA"]["target_weight"] = 0.18
    changed["receipt_sha256"] = publication._digest(
        {key: item for key, item in changed.items() if key != "receipt_sha256"}
    )
    raw = json.dumps(changed, sort_keys=True, allow_nan=False).encode()
    path.write_bytes(raw)
    pointer["receipt_sha256"] = changed["receipt_sha256"]
    pointer["bytes_sha256"] = publication.sha256(raw).hexdigest()
    (folder / "latest.json").write_text(json.dumps(pointer, sort_keys=True))
    expired_at = datetime.fromisoformat("2026-01-07T17:00:00-05:00")
    result = market_allocation.allocation(tmp_path, expired_at)
    assert result["status"] == "unavailable"
    assert result["rows"] == {}


# The real authenticated HTTP route rejects foreign readers and never consults a broker.
@pytest.mark.asyncio
async def test_allocation_http_owner_and_account_independence(monkeypatch, tmp_path):
    from httpx import ASGITransport, AsyncClient

    from backend.api.v1 import market_allocation
    from backend.config.settings import settings
    from backend.core.auth import issue_user_token
    from backend.main import app
    from backend.market import alpaca_trading

    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", "desk_user")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    record, _, _, _ = admitted(monkeypatch)
    monkeypatch.setattr(
        market_allocation.deskrecord, "latest_pair", lambda root: (record, None)
    )
    result = view.read(tmp_path, record, NOW)
    calls = []

    # Record the owner-only projection with its exact original record.
    def project(root, saved, now):
        assert root == tmp_path
        assert saved is record
        assert now.utcoffset() is not None
        calls.append("project")
        return result

    # A GET of shared strategy percentages cannot make a broker call.
    def forbidden():
        pytest.fail("Allocation HTTP route accessed a broker")

    monkeypatch.setattr(view, "read", project)
    monkeypatch.setattr(alpaca_trading, "client_from_env", forbidden)
    url = "/api/v1/market/desk_user/desk/model-allocation"
    owner = issue_user_token("desk_user", scopes=["memory:read"])
    other = issue_user_token("outsider", scopes=["memory:read"])
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        accepted = await client.get(url, headers={"Authorization": f"Bearer {owner}"})
        foreign = await client.get(url, headers={"Authorization": f"Bearer {other}"})
        anonymous = await client.get(url)
    assert accepted.status_code == 200
    assert accepted.json() == result
    assert accepted.headers["cache-control"] == "private, no-store"
    assert foreign.status_code == 403
    assert anonymous.status_code == 401
    assert calls == ["project"]


# The served numerical rows carry one verdict each, added from the evidence
# the sealed engines already wrote, so the board never derives it twice.
def test_served_rows_carry_a_verdict(monkeypatch, tmp_path):
    value = publish_fixture(tmp_path, monkeypatch)
    name = next(iter(value["rows"]))
    rows = {
        name: {
            "state": "execute",
            "action": "Buy",
            "size_weight": 0.1,
            "quote_at": "2026-01-06T15:00:00-05:00",
            "valid_until": "x",
            "evidence": {},
        },
        "ZZZ": {
            "state": "wait",
            "action": "Buy",
            "size_weight": 0.0,
            "quote_at": "2026-01-06T15:00:00-05:00",
            "valid_until": "x",
            "evidence": {},
        },
        "YYY": {
            "state": "unavailable",
            "action": None,
            "size_weight": 0.0,
            "quote_at": None,
            "valid_until": "x",
            "evidence": {},
            "reason": "Fresh compatible IEX quote required",
        },
        "WWW": {
            "state": "unavailable",
            "action": "Buy",
            "size_weight": 1e-5,
            "model_position_weight": 0.22,
            "reference_position_weight": 0.0,
            "quote_at": None,
            "valid_until": "x",
            "evidence": {},
            "reason": "Fresh compatible IEX quote required",
        },
    }
    monkeypatch.setattr(
        market_allocation.strategy_entries,
        "read",
        lambda root, snapshot, now: {"status": "available", "rows": rows},
    )
    monkeypatch.setattr(
        market_allocation.strategy_position_view,
        "read",
        lambda root, snapshot, now: {
            "status": "available",
            "rows": {
                name: {
                    "state": "no_trade",
                    "action": None,
                    "trade_weight": 0.0,
                    "model_position_weight": 0.1,
                    "reference_position_weight": 0.1,
                    "reason": "No funded model reference change",
                }
            },
        },
    )
    result = market_allocation.allocation(tmp_path, PUBLISHED_AT)
    served = result["entry_assessment"]["rows"]
    assert (served[name]["verdict"], served[name]["reason_code"]) == (
        "buy",
        "execute_now",
    )
    assert (served["ZZZ"]["verdict"], served["ZZZ"]["reason_code"]) == (
        "nothing",
        "waiting_better_price",
    )
    assert (served["YYY"]["verdict"], served["YYY"]["reason_code"]) == (
        "nothing",
        "quote_stale",
    )
    # A planned buy whose price is not yet confirmed keeps its direction and
    # shows the plan's trade, not the engine's placeholder size.
    assert (served["WWW"]["verdict"], served["WWW"]["reason_code"]) == (
        "buy",
        "entry_pending",
    )
    assert served["WWW"]["plan_weight"] == pytest.approx(0.22)
    assert served["WWW"]["size_weight"] == 1e-5
    assert served[name]["reason"] == "Act now at the current price"
    # Reference rows are served as written: a target for the next session is
    # the plan, not a verdict about this one.
    reference = result["reference_positions"]["rows"][name]
    assert "verdict" not in reference
    assert reference["reason"] == "No funded model reference change"


# A verified snapshot whose policy has since been replaced is the last plan
# until the nightly publishes under the new one, dated by the replacement.
def test_replaced_policy_keeps_the_last_plan_until_the_nightly(monkeypatch, tmp_path):
    value = publish_fixture(tmp_path, monkeypatch)
    config_path = tmp_path / market_allocation.learned_live_holding.CONFIG
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_bytes(b'{"policy": "grade-led-leader-weight/1"}')
    monkeypatch.setattr(
        publication.learned_live_holding,
        "read_configuration",
        lambda root, at: (
            config_path.read_bytes(),
            {"cost_bps": 10, "policy": "grade-led-leader-weight/1"},
        ),
    )
    now = PUBLISHED_AT + timedelta(hours=1)
    result = market_allocation.allocation(tmp_path, now)
    assert result["status"] == "awaiting_nightly"
    assert result["policy"] == "grade-led-leader-weight/1"
    assert result["superseded_policy"] == value["policy"]
    assert result["expired_at"] is None
    assert result["last_rows"] == value["rows"]
    assert result["last_session"] == value["session"]
    assert datetime.fromisoformat(result["superseded_at"]).utcoffset() is not None
    # Past its own close the same plan is both expired and superseded.
    late = datetime.fromisoformat("2026-01-07T17:00:00-05:00")
    result = market_allocation.allocation(tmp_path, late)
    assert result["status"] == "awaiting_nightly"
    assert result["expired_at"] == value["valid_until"]
    assert result["superseded_policy"] == value["policy"]
