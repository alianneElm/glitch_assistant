"""Contact model for storing Alianne's contacts."""

from sqlalchemy import Column, Integer, String, Text
from sqlalchemy.sql import func
from sqlalchemy import DateTime

from backend.services.database import Base


class Contact(Base):
    __tablename__ = "contacts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    phone = Column(String(20), nullable=False, unique=True)
    language = Column(String(5), nullable=False, default="sv")  # sv, es, en
    relationship = Column(String(50), nullable=True)  # amigo, familia, dentista, trabajo...
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=func.now(), nullable=False)
