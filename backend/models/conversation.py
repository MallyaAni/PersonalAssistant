from datetime import datetime
from typing import List, Optional
import uuid

from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy import String, Text
from backend.database.session import Base

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    extra_data: Mapped[dict] = mapped_column(JSON, nullable=True)

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "user_id": self.user_id,
            "query": self.query,
            "response": self.response,
            "metadata": self.extra_data or {}
        }

# Note: We'll add a Turn model later to support multiple turns per conversation ID
