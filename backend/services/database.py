"""Database connection and session management."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from backend.config import settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal = None


def get_engine():
    global _engine
    if _engine is None:
        if not settings.database_url:
            raise RuntimeError("DATABASE_URL is not configured")
        _engine = create_engine(
            settings.database_url,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
        )
    return _engine


def get_session() -> Session:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine())
    return _SessionLocal()


def init_db():
    """Create all tables if they don't exist."""
    # Import models so they register with Base
    from backend.models import contact, conversation, memory, reminder  # noqa: F401

    engine = get_engine()

    # Enable pgvector extension (needed before creating tables with vector columns)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
        logger.info("pgvector extension enabled")
    except Exception:
        logger.warning("Could not enable pgvector extension (may already exist or not available)")

    # Migrate embedding column from 1536 to 1024 dimensions (Jina AI)
    # Only runs if the column is still the old 1536 size
    try:
        from sqlalchemy import text as sa_text, inspect
        insp = inspect(engine)
        if "memories" in insp.get_table_names():
            with engine.connect() as conn:
                # Check current dimension before migrating
                row = conn.execute(sa_text(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'memories'::regclass "
                    "AND attname = 'embedding'"
                )).fetchone()
                current_dim = row[0] if row else 0

                if current_dim != 1024:
                    conn.execute(sa_text("DROP INDEX IF EXISTS memories_embedding_idx"))
                    conn.execute(sa_text("DELETE FROM memories"))
                    conn.execute(sa_text(
                        "ALTER TABLE memories ALTER COLUMN embedding TYPE vector(1024)"
                    ))
                    conn.commit()
                    logger.info(
                        "Migrated memories embedding column %d → 1024 dimensions",
                        current_dim,
                    )
                else:
                    logger.debug("Embedding column already 1024 dimensions, skipping migration")
    except Exception:
        logger.debug("Embedding migration check skipped (table may not exist yet)")

    Base.metadata.create_all(bind=engine)

    # Add esp32_sent column to reminders if missing (for ESP32 audio notifications)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text(
                "ALTER TABLE reminders ADD COLUMN IF NOT EXISTS "
                "esp32_sent BOOLEAN NOT NULL DEFAULT false"
            ))
            conn.commit()
        logger.info("reminders.esp32_sent column verified")
    except Exception:
        logger.debug("esp32_sent column migration skipped (may already exist)")

    # Create HNSW index for fast similarity search (if not exists)
    try:
        from sqlalchemy import text
        with engine.connect() as conn:
            conn.execute(text("""
                CREATE INDEX IF NOT EXISTS memories_embedding_idx
                ON memories USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
            """))
            conn.commit()
        logger.info("HNSW index created/verified")
    except Exception:
        logger.warning("Could not create HNSW index (non-critical)")

    logger.info("Database tables created/verified")
