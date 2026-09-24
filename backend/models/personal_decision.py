"""Private generated advice and a separate dashboard-load acknowledgement."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.core.crypto import DecryptionError, EncryptionKeyError, get_field_cipher
from backend.database.session import Base
from backend.database.types import EncryptedText


class EncryptedReceiptText(EncryptedText):
    """Unlike legacy stores, this new table has no legitimate plaintext rows."""

    cache_ok = True

    # Reject every unencrypted write, including callers outside the receipt repository.
    def process_bind_param(self, value, dialect):
        if not get_field_cipher().enabled:
            raise EncryptionKeyError("Personal history requires encryption")
        return super().process_bind_param(value, dialect)

    # Never mistake a valid-looking plaintext replacement for authenticated advice.
    def process_result_value(self, value, dialect):
        if not isinstance(value, str) or not get_field_cipher().is_sealed(value):
            raise DecryptionError("Personal decision receipt is not sealed")
        return super().process_result_value(value, dialect)


class PersonalDecisionReceipt(Base):
    __tablename__ = "personal_decision_receipts"
    __table_args__ = (
        Index("ix_personal_decisions_owner_time", "user_id", "generated_at", "id"),
        Index("ix_personal_decisions_expiry", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledge_before: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload: Mapped[str] = mapped_column(EncryptedReceiptText, nullable=False)
