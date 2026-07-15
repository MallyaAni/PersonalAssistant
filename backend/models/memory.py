from datetime import datetime
from typing import List, Optional, Dict, Any
import uuid

from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID, JSON
from sqlalchemy import String, Text, DateTime
from sqlalchemy.types import UserDefinedType
import numpy as np

class Vector(UserDefinedType):
    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    def get_col_spec(self, **kwargs):
        return f"vector({self.dimension})"

from backend.models.conversation import Base

class UserProfile(Base):
    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(100))
    preferences: Mapped[dict] = mapped_column(JSON, default={})
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "name": self.name,
            "preferences": self.preferences
        }

class EpisodicMemory(Base):
    __tablename__ = "episodic_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(server_default=func.now())
    content: Mapped[str] = mapped_column(Text, nullable=False)
    extra_data: Mapped[dict] = mapped_column(JSON, default={})

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "content": self.content,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "extra_data": self.extra_data
        }

class SemanticMemory(Base):
    __tablename__ = "semantic_memory"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1536)) # Assuming 1536 for OpenAI standard, can be adjusted
    extra_data: Mapped[dict] = mapped_column(JSON, default={})
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    def to_dict(self) -> dict:
        return {
            "content": self.content,
            "extra_data": self.extra_data,
            "created_at": self.created_at.isoformat() if self.created_at else None
        }
