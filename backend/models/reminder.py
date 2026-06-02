"""Reminder model for persistent storage."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text, Boolean
from sqlalchemy.sql import func

from backend.services.database import Base


class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_id = Column(String(50), unique=True, nullable=False, index=True)
    user_whatsapp = Column(String(50), nullable=False)
    reminder_text = Column(Text, nullable=False)
    remind_at = Column(DateTime(timezone=True), nullable=False)
    sent = Column(Boolean, default=False, nullable=False)          # WhatsApp delivered
    esp32_sent = Column(Boolean, default=False, server_default="false", nullable=False)  # ESP32 delivered
    created_at = Column(DateTime, default=func.now(), nullable=False)
