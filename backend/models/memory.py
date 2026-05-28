"""Semantic memory model with pgvector embeddings."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Integer, SmallInteger, String, Text, Index
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.sql import func

from backend.services.database import Base


class Memory(Base):
    __tablename__ = "memories"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(String(50), nullable=False, index=True)
    content = Column(Text, nullable=False)
    embedding = Column(Vector(1024), nullable=False)
    memory_type = Column(String(30), nullable=False, default="conversation")
    importance = Column(SmallInteger, default=1)
    metadata_ = Column("metadata", JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_accessed_at = Column(DateTime(timezone=True), server_default=func.now())
    access_count = Column(Integer, default=0)

    __table_args__ = (
        Index("memories_type_idx", "memory_type"),
        Index("memories_created_at_idx", "created_at"),
    )
