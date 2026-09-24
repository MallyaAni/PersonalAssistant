"""Exercise actual advice capture, encryption and ownership against isolated Postgres.

Run with ANIOS_HISTORY_DATABASE_TESTS=1 and POSTGRES_DB=test_history_... .
The guarded fixture creates only the new table in that disposable database;
no live schema or account is used. Market providers are deterministic inputs,
but routing, the planner, receipt projection and persistence are real.
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, text, update

from backend.config.settings import settings
from backend.core.auth import issue_user_token
from backend.core.crypto import generate_key, reset_field_cipher
from backend.database.session import AsyncSessionLocal, async_engine
from backend.main import app
from backend.market import personal_history
from backend.models.auth import UserAccount
from backend.models.personal_decision import PersonalDecisionReceipt
from backend.tests.test_decision_view import FIRING, setup

pytestmark = pytest.mark.skipif(
    os.environ.get("ANIOS_HISTORY_DATABASE_TESTS") != "1",
    reason="Requires explicitly isolated personal-history Postgres acceptance",
)


# Refuse live databases, install deterministic market inputs and create a scoped client.
@pytest_asyncio.fixture
async def environment(monkeypatch, tmp_path):
    assert settings.POSTGRES_DB.startswith("test_history_")
    from backend.api.v1 import market
    from backend.market import desk_freshness, event_status, execution_quotes

    record, snapshot, quoted, now = setup()
    record["written"] = now.isoformat()
    owner = f"history_{uuid.uuid4().hex[:10]}"

    class Clock(datetime):
        # Hold the HTTP path and the persistence clock at one known evidence instant.
        @classmethod
        def now(cls, tz=None):
            return now

    monkeypatch.setattr(market, "datetime", Clock)
    monkeypatch.setattr(personal_history, "datetime", Clock)
    monkeypatch.setattr(desk_freshness, "datetime", Clock)
    monkeypatch.setattr(settings, "MARKET_DESK_USER", owner)
    monkeypatch.setattr(settings, "MARKET_DESK_USERS", "viewer")
    monkeypatch.setattr(settings, "MARKET_DATA_ROOT", str(tmp_path))
    monkeypatch.setattr(settings, "AUTH_REQUIRED", True)
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", generate_key())
    reset_field_cipher()
    monkeypatch.setattr(market.deskrecord, "latest_pair", lambda root: (record, None))
    monkeypatch.setattr(market, "_live_snapshot", lambda: snapshot)
    monkeypatch.setattr(event_status, "for_planning", lambda record, root: record)
    monkeypatch.setattr(execution_quotes, "fetch", lambda names: quoted)
    monkeypatch.setattr(
        market.live_technical,
        "entry_now",
        lambda *args: {s: {"band_z": z} for s, z in FIRING.items()},
    )
    # Account-state sentinels must survive the whole journey byte-for-byte.
    (tmp_path / "paper").mkdir()
    (tmp_path / "paper/state.json").write_text('{"sentinel":"no-orders"}')
    (tmp_path / "desk").mkdir()
    (tmp_path / "desk/holdings.json").write_text("[]")
    async with async_engine.begin() as connection:
        await connection.run_sync(UserAccount.__table__.create, checkfirst=True)
        await connection.run_sync(
            PersonalDecisionReceipt.__table__.create, checkfirst=True
        )
    headers = {"Authorization": f"Bearer {issue_user_token(owner)}"}
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test", headers=headers
        ) as client:
            yield client, owner, record, snapshot, quoted, now, tmp_path
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(PersonalDecisionReceipt).where(
                    PersonalDecisionReceipt.user_id.in_([owner, "viewer"])
                )
            )
            await db.commit()
        reset_field_cipher()


# Walk capture through HTTP and read the database, then prove later prices cannot rewrite it.
@pytest.mark.asyncio
async def test_capture_acknowledge_export_delete_is_persistent_and_nontrading(
    environment,
):
    client, owner, record, snapshot, quoted, _now, root = environment
    base = f"/api/v1/market/{owner}/desk"
    inputs = {"equity": 98765.43, "available_cash": 87654.32}
    assert (await client.post(base + "/mine", json=inputs)).status_code == 200
    assert (await client.get(base + "/mine?equity=100000")).status_code == 200
    initial = await client.get(base + "/personal-history")
    assert initial.status_code == 200, initial.text
    assert initial.json()["items"] == []
    response = await client.post(
        base + "/mine", json={**inputs, "record_history": True}
    )
    assert response.status_code == 200, response.text
    advice = response.json()
    receipt = advice["history_receipt"]
    assert receipt["status"] == "generated", receipt
    rid = receipt["id"]
    path = base + f"/personal-history/{rid}"
    exported = (await client.get(path)).json()
    assert exported["acknowledged_at"] is None
    assert exported["payload"]["rows"]["S11"]["action"] == "Buy"
    for field in personal_history.ROW_FIELDS:
        assert (
            exported["payload"]["rows"]["S11"][field]
            == advice["decisions"]["rows"]["S11"][field]
        )
    async with AsyncSessionLocal() as db:
        raw = await db.scalar(
            text("select payload from personal_decision_receipts where id=:id"),
            {"id": uuid.UUID(rid)},
        )
        assert raw.startswith("enc:1:")
        assert "S11" not in raw and "98765.43" not in raw
        stored = await db.scalar(
            select(PersonalDecisionReceipt).where(
                PersonalDecisionReceipt.id == uuid.UUID(rid)
            )
        )
        assert json.loads(stored.payload) == exported["payload"]
        assert all(
            secret not in stored.payload
            for secret in (
                "98765.43",
                "87654.32",
                '"holdings"',
                '"portfolio_allocation"',
            )
        )
    body = {"session": record["session"], "written": record["written"]}
    ack = await client.post(path + "/acknowledge", json=body)
    assert ack.status_code == 200, ack.text
    assert (await client.post(path + "/acknowledge", json=body)).json() == ack.json()
    snapshot["quotes"]["S11"]["last"] = 1
    quoted["market_open"] = False
    changed = await client.post(base + "/mine", json={**inputs, "record_history": True})
    assert changed.json()["decisions"]["rows"]["S11"]["action"] == "Hold"
    assert (await client.get(path)).json()["payload"] == exported["payload"]
    history = (await client.get(base + "/personal-history?limit=1")).json()
    assert len(history["items"]) == 1 and history["next_cursor"]
    page2 = (
        await client.get(
            base + "/personal-history",
            params={"before": history["next_cursor"], "limit": 1},
        )
    ).json()
    assert len(page2["items"]) == 1
    assert page2["items"][0]["id"] != history["items"][0]["id"]
    assert (await client.delete(path)).status_code == 200
    assert (await client.get(path)).status_code == 404
    async with AsyncSessionLocal() as db:
        assert await db.get(PersonalDecisionReceipt, uuid.UUID(rid)) is None
    assert (root / "desk/holdings.json").read_text() == "[]"
    assert (root / "paper/state.json").read_text() == '{"sentinel":"no-orders"}'


# Enforce primary ownership, token scope, record identity, expiry and absent encryption.
@pytest.mark.asyncio
async def test_receipts_fail_closed_on_access_context_expiry_and_encryption(
    environment, monkeypatch
):
    client, owner, record, _snapshot, _quoted, now, _root = environment
    base = f"/api/v1/market/{owner}/desk"
    inputs = {"equity": 100000, "available_cash": 100000, "record_history": True}
    receipt = (await client.post(base + "/mine", json=inputs)).json()["history_receipt"]
    assert receipt["status"] == "generated", receipt
    path = base + f"/personal-history/{receipt['id']}"
    body = {"session": record["session"], "written": record["written"]}
    assert (
        await client.post(path + "/acknowledge", json={**body, "written": "wrong"})
    ).status_code == 409
    record["written"] = "changed-revision"
    assert (await client.post(path + "/acknowledge", json=body)).status_code == 409
    record["written"] = body["written"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PersonalDecisionReceipt)
            .where(PersonalDecisionReceipt.id == uuid.UUID(receipt["id"]))
            .values(acknowledge_before=now - timedelta(seconds=1))
        )
        await db.commit()
    assert (await client.post(path + "/acknowledge", json=body)).status_code == 409
    for headers in (
        {"Authorization": "Bearer invalid"},
        {"Authorization": f"Bearer {issue_user_token('viewer')}"},
    ):
        assert (await client.get(path, headers=headers)).status_code in (401, 403)
    viewer = "/api/v1/market/viewer/desk"
    viewer_headers = {"Authorization": f"Bearer {issue_user_token('viewer')}"}
    assert (
        await client.post(viewer + "/mine", json=inputs, headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.get(viewer + "/personal-history", headers=viewer_headers)
    ).status_code == 403
    assert (
        await client.delete(
            path,
            headers={
                "Authorization": f"Bearer {issue_user_token(owner, scopes=['memory:read'])}"
            },
        )
    ).status_code == 403
    monkeypatch.setattr(settings, "ENCRYPTION_KEY", "")
    reset_field_cipher()
    failed = await client.post(base + "/mine", json=inputs)
    assert failed.status_code == 200
    assert failed.json()["history_receipt"]["status"] == "unavailable"
    assert failed.json()["decisions"]["rows"]["S11"]["action"] == "Buy"


# Concurrent acknowledgements serialize, and retention never removes another owner.
@pytest.mark.asyncio
async def test_concurrent_ack_and_retention_are_owned_and_read_only(environment):
    client, owner, record, _snapshot, _quoted, now, _root = environment
    base = f"/api/v1/market/{owner}/desk"
    inputs = {"equity": 100000, "available_cash": 100000, "record_history": True}
    receipt = (await client.post(base + "/mine", json=inputs)).json()["history_receipt"]
    path = base + f"/personal-history/{receipt['id']}"
    body = {"session": record["session"], "written": record["written"]}
    first, second = await asyncio.gather(
        client.post(path + "/acknowledge", json=body),
        client.post(path + "/acknowledge", json=body),
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    async with AsyncSessionLocal() as db:
        row = await db.get(PersonalDecisionReceipt, uuid.UUID(receipt["id"]))
        assert row.acknowledged_at == now
        assert row.expires_at == now + timedelta(days=90)
        other = await personal_history.PersonalHistoryRepository(db).capture(
            "viewer", json.loads(row.payload), now.isoformat()
        )
        await db.execute(
            update(PersonalDecisionReceipt)
            .where(PersonalDecisionReceipt.id == row.id)
            .values(expires_at=now - timedelta(seconds=1))
        )
        await db.commit()
    assert (await client.get(base + "/personal-history")).json()["items"] == []
    async with AsyncSessionLocal() as db:
        assert (
            await db.get(PersonalDecisionReceipt, uuid.UUID(receipt["id"])) is not None
        )
    assert (await client.post(base + "/mine", json=inputs)).json()["history_receipt"][
        "status"
    ] == "generated"
    async with AsyncSessionLocal() as db:
        assert await db.get(PersonalDecisionReceipt, uuid.UUID(receipt["id"])) is None
        assert await db.get(PersonalDecisionReceipt, uuid.UUID(other["id"])) is not None
    # An owned path cannot export/delete a receipt belonging to someone else.
    assert (
        await client.get(base + f"/personal-history/{other['id']}")
    ).status_code == 404
    assert (
        await client.delete(base + f"/personal-history/{other['id']}")
    ).status_code == 404


# A damaged receipt surfaces as unavailable instead of silently becoming an empty history.
@pytest.mark.asyncio
async def test_corrupt_receipt_is_explicitly_unavailable(environment):
    client, owner, _record, _snapshot, _quoted, _now, _root = environment
    base = f"/api/v1/market/{owner}/desk"
    receipt = (
        await client.post(
            base + "/mine",
            json={
                "equity": 100000,
                "available_cash": 100000,
                "record_history": True,
            },
        )
    ).json()["history_receipt"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PersonalDecisionReceipt)
            .where(PersonalDecisionReceipt.id == uuid.UUID(receipt["id"]))
            .values(payload="invalid-private-json-sentinel")
        )
        await db.commit()
    for path in ("/personal-history", f"/personal-history/{receipt['id']}"):
        response = await client.get(base + path)
        assert response.status_code == 503
        assert response.json() == {"detail": "Personal decision history unavailable"}
        assert "sentinel" not in response.text


# A new-only encrypted store must not accept valid JSON substituted as plaintext.
@pytest.mark.asyncio
async def test_plaintext_replacement_is_not_treated_as_an_authentic_receipt(
    environment,
):
    client, owner, _record, _snapshot, _quoted, _now, _root = environment
    base = f"/api/v1/market/{owner}/desk"
    receipt = (
        await client.post(
            base + "/mine",
            json={
                "equity": 100000,
                "available_cash": 100000,
                "record_history": True,
            },
        )
    ).json()["history_receipt"]
    path = base + f"/personal-history/{receipt['id']}"
    original = (await client.get(path)).json()["payload"]
    original["rows"]["S11"]["action"] = "Sell"
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("update personal_decision_receipts set payload=:payload where id=:id"),
            {
                "payload": json.dumps(original),
                "id": uuid.UUID(receipt["id"]),
            },
        )
        await db.commit()
    response = await client.get(path)
    assert response.status_code == 503, (
        "Plaintext replacement bypassed receipt authentication"
    )
    assert response.json() == {"detail": "Personal decision history unavailable"}
