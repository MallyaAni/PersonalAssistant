"""Private, minimized receipts; never a trade journal or reconstructed advice.

Generation is immutable. An acknowledgement proves only that the dashboard
reported loading the accepted response, not that a person read or acted on it.
Account dollar values and share quantities are deliberately not reproducible.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.crypto import EncryptionKeyError, get_field_cipher
from backend.models.personal_decision import PersonalDecisionReceipt

ACKNOWLEDGED_DAYS = 90
UNACKNOWLEDGED_HOURS = 24
MAX_PAYLOAD_BYTES = 512_000
ROW_FIELDS = (
    "action",
    "move_weight",
    "strategy_action",
    "strategy_move_weight",
    "target_weight",
    "current_weight",
    "delta_weight",
    "executable",
    "blocker",
    "reason",
    "valid_until",
    "entry_status",
    "entry_reason",
    "missing_sessions",
    "risk_plan",
)
QUOTE_FIELDS = (
    "feed",
    "at",
    "eligible",
    "reason",
    "valid_until",
    "bid",
    "ask",
    "spread_bps",
    "bid_size",
    "ask_size",
    "spread_verified",
)
EVENT_FIELDS = (
    "factor",
    "execution_pending",
    "calendar_known",
    "version",
    "enabled",
    "session",
    "decision_date",
    "sessions_to_decision",
    "pre_sessions",
    "reduced_exposure",
    "evaluation_since",
)
LIMITATIONS = [
    "Generated advice is historical, not a current instruction or a recorded trade.",
    "Loaded into dashboard means the browser acknowledged this response; it does not prove every row was read.",
    "Raw cash, equity, share quantities and pending-order inputs are not retained; full account replay is not possible.",
    "Unacknowledged receipts expire after 24 hours; acknowledged receipts expire after 90 days. Cleanup runs on capture.",
    "Earlier advice that was never recorded cannot be reconstructed from this history.",
]


class HistoryConflict(ValueError):
    """An expected ownership-safe cursor or acknowledgement conflict."""


# Serialize deterministically and reject nonfinite or oversized receipt content.
def _json(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Personal decision receipt exceeds its size bound")
    return encoded


# Accept only explicit timezone-bearing instants for generation and expiry.
def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Receipt timestamps require a timezone")
    return parsed.astimezone(UTC)


# Hash the source files that generated the advice without retaining their contents.
def source_fingerprint() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    names = (
        "backend/api/v1/market.py",
        "backend/market/personal_history.py",
        "backend/market/decision_view.py",
        "backend/market/personal_risk.py",
        "backend/market/holdings.py",
        "backend/market/desk_freshness.py",
        "backend/market/execution_quotes.py",
        "backend/market/event_status.py",
        "backend/market/calendar.py",
        "backend/agents/trading/desk/paper.py",
        "backend/agents/trading/desk/planner.py",
    )
    return {
        name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names
    }


# Freeze only the allowlisted generated output and the evidence it actually used.
def project(decisions: dict, record: dict, snapshot: dict, entries: dict) -> dict:
    from backend.agents.trading.desk.paper import POLICY_VERSION
    from backend.market import desk_freshness, holdings

    generated = _instant(decisions["as_of"])
    technical, value = desk_freshness.grade_inputs(snapshot, record, generated)
    readings = holdings.live_grades(record, technical, value)
    rows = {}
    for ticker, decision in decisions["rows"].items():
        quote = decision.get("quote") or {}
        bar = (snapshot.get("quotes") or {}).get(ticker) or {}
        rows[ticker] = {
            **{key: decision.get(key) for key in ROW_FIELDS},
            "quote": {key: quote.get(key) for key in QUOTE_FIELDS},
            "grade": (readings.get(ticker) or {}).get("grade_live")
            or ((record.get("grades") or {}).get(ticker) or {}).get("grade"),
            "band_z": entries.get(ticker),
            "bar": {"at": bar.get("bar"), "price": bar.get("last")},
        }
    payload = {
        "schema_version": "personal-decision-receipt/1",
        "policy_version": POLICY_VERSION,
        "decision_version": decisions["version"],
        "decision_policy": decisions["policy"],
        "session": decisions["session"],
        "written": decisions.get("written"),
        "record_sha256": hashlib.sha256(
            json.dumps(record, sort_keys=True, allow_nan=False).encode()
        ).hexdigest(),
        "code_fingerprint": source_fingerprint(),
        "event_state": {
            key: (record.get("event_risk") or {}).get(key) for key in EVENT_FIELDS
        },
        "rows": rows,
    }
    # Round-trip now so later mutations cannot rewrite the generated advice.
    return json.loads(_json(payload))


# Bound acknowledgement by every generated executable action's evidence deadline.
def acknowledgement_deadline(payload: dict, generated: datetime) -> datetime:
    deadline = generated + timedelta(seconds=60)
    for row in payload["rows"].values():
        if row["executable"] and row["action"] in ("Buy", "Sell"):
            if not row["valid_until"]:
                return generated
            deadline = min(deadline, _instant(row["valid_until"]))
    return deadline


# Return owned content without exposing ORM objects or ciphertext.
def _view(row: PersonalDecisionReceipt) -> dict:
    return {
        "id": str(row.id),
        "generated_at": row.generated_at.isoformat(),
        "acknowledge_before": row.acknowledge_before.isoformat(),
        "acknowledged_at": row.acknowledged_at.isoformat()
        if row.acknowledged_at
        else None,
        "payload": json.loads(row.payload),
    }


class PersonalHistoryRepository:
    # Use the caller's database transaction and never touch account state.
    def __init__(self, session: AsyncSession):
        self.session = session

    # Persist encrypted immutable advice and expire only this owner's old receipts.
    async def capture(self, user_id: str, payload: dict, generated_at: str) -> dict:
        if not get_field_cipher().enabled:
            raise EncryptionKeyError("Personal history requires encryption")
        generated = _instant(generated_at)
        now = datetime.now(UTC)
        await self.session.execute(
            delete(PersonalDecisionReceipt).where(
                PersonalDecisionReceipt.user_id == user_id,
                PersonalDecisionReceipt.expires_at <= now,
            )
        )
        row = PersonalDecisionReceipt(
            id=uuid.uuid4(),
            user_id=user_id,
            generated_at=generated,
            acknowledge_before=acknowledgement_deadline(payload, generated),
            acknowledged_at=None,
            expires_at=now + timedelta(hours=UNACKNOWLEDGED_HOURS),
            payload=_json(payload),
        )
        self.session.add(row)
        await self.session.commit()
        return {
            "status": "generated",
            "id": str(row.id),
            "generated_at": row.generated_at.isoformat(),
            "acknowledge_before": row.acknowledge_before.isoformat(),
        }

    # Resolve an unexpired receipt only for its authenticated primary owner.
    async def get(self, user_id: str, receipt_id: uuid.UUID, *, lock=False):
        query = select(PersonalDecisionReceipt).where(
            PersonalDecisionReceipt.user_id == user_id,
            PersonalDecisionReceipt.id == receipt_id,
            PersonalDecisionReceipt.expires_at > datetime.now(UTC),
        )
        return await self.session.scalar(query.with_for_update() if lock else query)

    # Acknowledge once, refusing stale record identities and elapsed evidence.
    async def acknowledge(self, user_id, receipt_id, session, written, current_record):
        row = await self.get(user_id, receipt_id, lock=True)
        if row is None:
            return None
        payload = json.loads(row.payload)
        if (payload["session"], payload["written"]) != (session, written):
            raise HistoryConflict(
                "Receipt does not match the accepted dashboard record"
            )
        if row.acknowledged_at is None:
            now = datetime.now(UTC)
            if now >= row.acknowledge_before:
                raise HistoryConflict("Receipt acknowledgement window expired")
            if not current_record or (session, written) != (
                current_record.get("session"),
                current_record.get("written"),
            ):
                raise HistoryConflict("The dashboard record was superseded")
            row.acknowledged_at = now
            row.expires_at = now + timedelta(days=ACKNOWLEDGED_DAYS)
            await self.session.commit()
        return {
            "id": str(row.id),
            "status": "acknowledged",
            "acknowledged_at": row.acknowledged_at.isoformat(),
        }

    # Page newest-first without making a read mutate retention or account state.
    async def list(self, user_id: str, limit: int, before: uuid.UUID | None = None):
        query = select(PersonalDecisionReceipt).where(
            PersonalDecisionReceipt.user_id == user_id,
            PersonalDecisionReceipt.expires_at > datetime.now(UTC),
        )
        if before is not None:
            cursor = await self.get(user_id, before)
            if cursor is None:
                raise HistoryConflict("History cursor unavailable; refresh history")
            query = query.where(
                tuple_(PersonalDecisionReceipt.generated_at, PersonalDecisionReceipt.id)
                < tuple_(cursor.generated_at, cursor.id)
            )
        rows = list(
            (
                await self.session.scalars(
                    query.order_by(
                        PersonalDecisionReceipt.generated_at.desc(),
                        PersonalDecisionReceipt.id.desc(),
                    ).limit(limit + 1)
                )
            ).all()
        )
        return {
            "items": [_view(row) for row in rows[:limit]],
            "next_cursor": str(rows[limit - 1].id) if len(rows) > limit else None,
            "retention": {
                "acknowledged_days": ACKNOWLEDGED_DAYS,
                "unacknowledged_hours": UNACKNOWLEDGED_HOURS,
            },
            "limitations": LIMITATIONS,
        }

    # Export exactly one owned receipt, without current recalculation.
    async def export(self, user_id: str, receipt_id: uuid.UUID):
        row = await self.get(user_id, receipt_id)
        return _view(row) if row else None

    # Remove only the explicitly identified owned receipt, never an account trade.
    async def remove(self, user_id: str, receipt_id: uuid.UUID) -> bool:
        result = await self.session.execute(
            delete(PersonalDecisionReceipt).where(
                PersonalDecisionReceipt.user_id == user_id,
                PersonalDecisionReceipt.id == receipt_id,
            )
        )
        await self.session.commit()
        return bool(result.rowcount)
