import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.database.session import Base
from backend.database.types import EncryptedText


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        index=True,
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    query: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    response: Mapped[str] = mapped_column(EncryptedText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    extra_data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # What the user said, embedded, so recall can search it directly rather
    # than only searching what a classifier chose to promote out of it.
    # Nullable: turns written before this existed have no vector, and the
    # search skips them rather than matching everything.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(768), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(200), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "conversation_id": str(self.conversation_id),
            "user_id": self.user_id,
            "query": self.query,
            "response": self.response,
            "metadata": self.extra_data or {},
        }
