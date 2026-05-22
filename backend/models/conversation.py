"""Conversation history model for persistent storage."""

import json
from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text
from sqlalchemy.sql import func

from backend.services.database import Base


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(50), nullable=False, index=True)
    role = Column(String(20), nullable=False)  # "user" or "assistant"
    content = Column(Text, nullable=False)  # JSON-serialized content
    created_at = Column(DateTime, default=func.now(), nullable=False)

    def set_content(self, content):
        """Serialize message content to JSON."""
        self.content = json.dumps(content, ensure_ascii=False, default=str)

    def get_content(self):
        """Deserialize message content from JSON."""
        return json.loads(self.content)
