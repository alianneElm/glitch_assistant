"""Semantic memory service for Glitch.

Handles embedding generation, storage, retrieval, and preference
detection using pgvector + Jina AI embeddings.

All save operations run in background threads to never block responses.
"""

import json
import logging
import threading
from datetime import datetime
from typing import Optional

import httpx
from sqlalchemy import text

from backend.config import settings
from backend.services.database import get_session

logger = logging.getLogger(__name__)

JINA_EMBEDDING_URL = "https://api.jina.ai/v1/embeddings"
EMBEDDING_MODEL = "jina-embeddings-v3"
EMBEDDING_DIM = 1024  # Jina v3 default


def _generate_embedding(text_input: str) -> Optional[list[float]]:
    """Generate embedding vector using Jina AI API."""
    try:
        response = httpx.post(
            JINA_EMBEDDING_URL,
            headers={
                "Authorization": f"Bearer {settings.jina_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": EMBEDDING_MODEL,
                "input": [text_input[:8000]],
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return data["data"][0]["embedding"]
    except Exception:
        logger.exception("Failed to generate embedding")
        return None


# --- Public API ---


def save_memory(
    user_id: str,
    user_message: str,
    glitch_response: str,
    memory_type: str = "conversation",
    importance: int = 1,
    metadata: Optional[dict] = None,
) -> Optional[str]:
    """Embed and store a conversation exchange.

    Args:
        user_id: WhatsApp user identifier
        user_message: What the user said
        glitch_response: What Glitch replied
        memory_type: conversation, preference, decision, fact, reminder_outcome, event
        importance: 1-5 scale
        metadata: Optional extra data (tool used, topic, etc.)

    Returns:
        Memory ID string or None on failure.
    """
    # Combine user message + response for richer embedding
    content = f"Usuario: {user_message}\nGlitch: {glitch_response}"

    embedding = _generate_embedding(content)
    if not embedding:
        return None

    session = get_session()
    try:
        result = session.execute(
            text("""
                INSERT INTO memories (user_id, content, embedding, memory_type, importance, metadata)
                VALUES (:user_id, :content, :embedding, :memory_type, :importance, :metadata)
                RETURNING id
            """),
            {
                "user_id": user_id,
                "content": content,
                "embedding": str(embedding),
                "memory_type": memory_type,
                "importance": importance,
                "metadata": json.dumps(metadata or {}),
            },
        )
        session.commit()
        memory_id = str(result.fetchone()[0])
        logger.debug("Memory saved: %s (type=%s, importance=%d)", memory_id[:8], memory_type, importance)
        return memory_id
    except Exception:
        session.rollback()
        logger.exception("Failed to save memory")
        return None
    finally:
        session.close()


def save_memory_background(
    user_id: str,
    user_message: str,
    glitch_response: str,
    memory_type: str = "conversation",
    importance: int = 1,
    metadata: Optional[dict] = None,
):
    """Non-blocking memory save in a background thread."""
    thread = threading.Thread(
        target=save_memory,
        args=(user_id, user_message, glitch_response, memory_type, importance, metadata),
        daemon=True,
    )
    thread.start()


def get_relevant_memories(
    user_id: str,
    query: str,
    limit: int = 0,
    min_similarity: float = 0.0,
    memory_types: Optional[list[str]] = None,
) -> list[dict]:
    """Cosine similarity search for relevant memories.

    Returns list of dicts with: id, content, memory_type, importance, similarity, created_at
    """
    if not limit:
        limit = settings.memory_max_results
    if not min_similarity:
        min_similarity = settings.memory_min_similarity

    embedding = _generate_embedding(query)
    if not embedding:
        return []

    session = get_session()
    try:
        # Build type filter
        type_filter = ""
        params = {
            "user_id": user_id,
            "embedding": str(embedding),
            "min_sim": min_similarity,
            "limit": limit,
        }

        if memory_types:
            placeholders = ", ".join(f":type_{i}" for i in range(len(memory_types)))
            type_filter = f"AND memory_type IN ({placeholders})"
            for i, mt in enumerate(memory_types):
                params[f"type_{i}"] = mt

        result = session.execute(
            text(f"""
                SELECT
                    id,
                    content,
                    memory_type,
                    importance,
                    1 - (embedding <=> :embedding::vector) AS similarity,
                    created_at,
                    metadata
                FROM memories
                WHERE user_id = :user_id
                    AND 1 - (embedding <=> :embedding::vector) >= :min_sim
                    {type_filter}
                ORDER BY similarity DESC
                LIMIT :limit
            """),
            params,
        )

        memories = []
        ids_to_update = []
        for row in result:
            memories.append({
                "id": str(row[0]),
                "content": row[1],
                "memory_type": row[2],
                "importance": row[3],
                "similarity": round(float(row[4]), 3),
                "created_at": row[5].isoformat() if row[5] else "",
                "metadata": row[6] or {},
            })
            ids_to_update.append(str(row[0]))

        # Update access timestamps in background
        if ids_to_update:
            _update_access_background(ids_to_update)

        return memories

    except Exception:
        logger.exception("Failed to search memories")
        return []
    finally:
        session.close()


def _update_access_background(memory_ids: list[str]):
    """Update last_accessed_at and access_count for retrieved memories."""
    def _update():
        session = get_session()
        try:
            for mid in memory_ids:
                session.execute(
                    text("""
                        UPDATE memories
                        SET last_accessed_at = NOW(), access_count = access_count + 1
                        WHERE id = :mid
                    """),
                    {"mid": mid},
                )
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    threading.Thread(target=_update, daemon=True).start()


def build_memory_context(user_id: str, current_message: str) -> str:
    """Build memory context string to inject into Claude's system prompt.

    Returns formatted string or empty string if no relevant memories.
    """
    memories = get_relevant_memories(user_id, current_message)
    if not memories:
        return ""

    lines = []
    for mem in memories:
        # Format: [type|importance] content (date)
        date_str = mem["created_at"][:10] if mem["created_at"] else ""
        type_label = {
            "preference": "PREFERENCIA",
            "decision": "DECISION",
            "fact": "DATO",
            "event": "EVENTO",
            "conversation": "CONVERSACION",
            "reminder_outcome": "RECORDATORIO",
        }.get(mem["memory_type"], mem["memory_type"].upper())

        importance_marker = "!" * min(mem["importance"], 3)
        lines.append(f"[{type_label}{importance_marker}] {mem['content']} ({date_str})")

    return "\n".join(lines)


def detect_and_save_preference_background(
    user_id: str,
    user_message: str,
    glitch_response: str,
):
    """Detect preferences/facts in background and save with higher importance.

    Uses Claude to analyze if the message contains a user preference,
    decision, or important personal fact.
    """
    if not settings.memory_importance_auto_detect:
        return

    def _detect():
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=settings.anthropic_api_key)

            prompt = f"""Analyze this exchange and determine if it contains a user preference, decision, or important personal fact worth remembering long-term.

User: {user_message}
Assistant: {glitch_response}

Respond with JSON only:
{{"detected": true/false, "type": "preference|decision|fact", "importance": 1-5, "summary": "short summary of what to remember"}}

Rules:
- importance 1: routine chat, greetings
- importance 2: useful context (mentioned a place, time preference)
- importance 3: clear preference ("I like X", "I don't want Y", "I prefer Z")
- importance 4: important decision or personal info (health, family, work change)
- importance 5: critical fact (allergies, emergencies, key dates)
- Only detect=true if there's genuinely something worth remembering
- Most messages are importance 1-2 and should NOT be flagged

JSON only, no other text:"""

            response = client.messages.create(
                model="claude-haiku-4-20250514",
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}],
            )

            text_resp = response.content[0].text.strip()
            if text_resp.startswith("```"):
                text_resp = text_resp.split("\n", 1)[1] if "\n" in text_resp else text_resp[3:]
                if text_resp.endswith("```"):
                    text_resp = text_resp[:-3]
                text_resp = text_resp.strip()

            data = json.loads(text_resp)

            if data.get("detected") and data.get("importance", 1) >= 3:
                summary = data.get("summary", user_message[:200])
                save_memory(
                    user_id=user_id,
                    user_message=user_message,
                    glitch_response=glitch_response,
                    memory_type=data.get("type", "preference"),
                    importance=data.get("importance", 3),
                    metadata={"auto_detected": True, "summary": summary},
                )
                logger.info(
                    "Auto-detected %s (importance=%d): %s",
                    data.get("type"),
                    data.get("importance"),
                    summary[:60],
                )

        except Exception:
            logger.debug("Preference detection failed (non-critical)")

    threading.Thread(target=_detect, daemon=True).start()


def get_user_profile(user_id: str) -> str:
    """Get a summary of what Glitch knows about the user.

    Returns high-importance memories: preferences, decisions, facts.
    """
    session = get_session()
    try:
        result = session.execute(
            text("""
                SELECT content, memory_type, importance, created_at
                FROM memories
                WHERE user_id = :user_id
                    AND importance >= 3
                    AND memory_type IN ('preference', 'decision', 'fact')
                ORDER BY importance DESC, created_at DESC
                LIMIT 20
            """),
            {"user_id": user_id},
        )

        rows = result.fetchall()
        if not rows:
            return "No tengo recuerdos importantes guardados sobre ti todavia."

        type_icons = {
            "preference": "Preferencia",
            "decision": "Decision",
            "fact": "Dato personal",
        }

        lines = [f"Lo que Glitch sabe sobre ti ({len(rows)} recuerdos):"]
        for row in rows:
            content = row[0]
            mtype = type_icons.get(row[1], row[1])
            importance = row[2]
            date = row[3].strftime("%d/%m/%Y") if row[3] else ""
            stars = "⭐" * min(importance, 5)
            lines.append(f"\n{stars} [{mtype}] ({date})")
            # Show just the user part if it has the format
            if "Usuario:" in content:
                user_part = content.split("Usuario:")[1].split("Glitch:")[0].strip()
                lines.append(f"  {user_part[:200]}")
            else:
                lines.append(f"  {content[:200]}")

        return "\n".join(lines)

    except Exception:
        logger.exception("Failed to get user profile")
        return "Error al consultar el perfil."
    finally:
        session.close()


def search_memories_by_text(user_id: str, query: str) -> str:
    """Search memories and return formatted results for the user."""
    memories = get_relevant_memories(user_id, query, limit=5, min_similarity=0.5)

    if not memories:
        return f"No encontre recuerdos relacionados con '{query}'."

    lines = [f"Recuerdos sobre '{query}':"]
    for i, mem in enumerate(memories, 1):
        date = mem["created_at"][:10] if mem["created_at"] else ""
        similarity_pct = int(mem["similarity"] * 100)
        content = mem["content"]
        if "Usuario:" in content:
            user_part = content.split("Usuario:")[1].split("Glitch:")[0].strip()
        else:
            user_part = content
        lines.append(f"\n{i}. ({date}, {similarity_pct}% relevancia)")
        lines.append(f"   {user_part[:200]}")

    return "\n".join(lines)


def forget_memory(user_id: str, memory_id: str) -> bool:
    """Delete a specific memory by ID."""
    session = get_session()
    try:
        result = session.execute(
            text("DELETE FROM memories WHERE id = :mid AND user_id = :uid"),
            {"mid": memory_id, "uid": user_id},
        )
        session.commit()
        deleted = result.rowcount > 0
        if deleted:
            logger.info("Memory deleted: %s", memory_id[:8])
        return deleted
    except Exception:
        session.rollback()
        logger.exception("Failed to delete memory")
        return False
    finally:
        session.close()


def forget_last_memory(user_id: str) -> str:
    """Delete the most recent memory for a user."""
    session = get_session()
    try:
        result = session.execute(
            text("""
                DELETE FROM memories
                WHERE id = (
                    SELECT id FROM memories
                    WHERE user_id = :uid
                    ORDER BY created_at DESC
                    LIMIT 1
                )
                RETURNING content
            """),
            {"uid": user_id},
        )
        session.commit()
        row = result.fetchone()
        if row:
            content_preview = row[0][:80]
            return f"Olvidado: {content_preview}..."
        return "No tenia nada que olvidar."
    except Exception:
        session.rollback()
        logger.exception("Failed to forget last memory")
        return "Error al olvidar."
    finally:
        session.close()


def clear_all_memories(user_id: str) -> str:
    """Delete ALL memories for a user."""
    session = get_session()
    try:
        result = session.execute(
            text("DELETE FROM memories WHERE user_id = :uid"),
            {"uid": user_id},
        )
        session.commit()
        count = result.rowcount
        logger.info("All memories cleared for %s: %d deleted", user_id, count)
        return f"Borrados {count} recuerdos. Memoria limpia."
    except Exception:
        session.rollback()
        logger.exception("Failed to clear memories")
        return "Error al borrar memorias."
    finally:
        session.close()


def get_memory_stats(user_id: str) -> str:
    """Get memory statistics for a user."""
    session = get_session()
    try:
        result = session.execute(
            text("""
                SELECT
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE memory_type = 'conversation') as conversations,
                    COUNT(*) FILTER (WHERE memory_type = 'preference') as preferences,
                    COUNT(*) FILTER (WHERE memory_type = 'fact') as facts,
                    COUNT(*) FILTER (WHERE memory_type = 'decision') as decisions,
                    COUNT(*) FILTER (WHERE importance >= 3) as important
                FROM memories
                WHERE user_id = :uid
            """),
            {"uid": user_id},
        )
        row = result.fetchone()
        if not row or row[0] == 0:
            return "No tengo memorias guardadas todavia."

        return (
            f"Memoria de Glitch:\n"
            f"  Total: {row[0]} recuerdos\n"
            f"  Conversaciones: {row[1]}\n"
            f"  Preferencias: {row[2]}\n"
            f"  Datos personales: {row[3]}\n"
            f"  Decisiones: {row[4]}\n"
            f"  Importantes: {row[5]}"
        )
    except Exception:
        logger.exception("Failed to get memory stats")
        return "Error al consultar estadisticas."
    finally:
        session.close()
