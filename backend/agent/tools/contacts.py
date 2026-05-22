"""Contact management for Glitch."""

import logging

from backend.models.contact import Contact
from backend.services.database import get_session

logger = logging.getLogger(__name__)


def save_contact(
    name: str,
    phone: str,
    language: str = "sv",
    relationship: str = "",
    notes: str = "",
) -> str:
    """Save or update a contact."""
    phone = phone.strip()
    if not phone.startswith("+"):
        phone = "+" + phone

    session = get_session()
    try:
        existing = session.query(Contact).filter(Contact.phone == phone).first()
        if existing:
            existing.name = name
            existing.language = language
            if relationship:
                existing.relationship = relationship
            if notes:
                existing.notes = notes
            session.commit()
            return f"✅ Contacto actualizado: {name} ({phone})"
        else:
            contact = Contact(
                name=name,
                phone=phone,
                language=language,
                relationship=relationship or None,
                notes=notes or None,
            )
            session.add(contact)
            session.commit()
            return f"✅ Contacto guardado: {name} ({phone}, {language})"
    except Exception as e:
        session.rollback()
        logger.exception("Failed to save contact")
        return f"Error al guardar contacto: {e}"
    finally:
        session.close()


def get_contact(name: str) -> dict | None:
    """Find a contact by name (case-insensitive partial match)."""
    session = get_session()
    try:
        contact = (
            session.query(Contact)
            .filter(Contact.name.ilike(f"%{name}%"))
            .first()
        )
        if contact:
            return {
                "name": contact.name,
                "phone": contact.phone,
                "language": contact.language,
                "relationship": contact.relationship or "",
                "notes": contact.notes or "",
            }
        return None
    finally:
        session.close()


def list_contacts() -> str:
    """List all saved contacts."""
    session = get_session()
    try:
        contacts = session.query(Contact).order_by(Contact.name).all()
        if not contacts:
            return "No tienes contactos guardados."

        lines = []
        for c in contacts:
            rel = f" ({c.relationship})" if c.relationship else ""
            lang = {"sv": "🇸🇪", "es": "🇪🇸", "en": "🇬🇧"}.get(c.language, c.language)
            lines.append(f"• {c.name}{rel} — {c.phone} {lang}")

        return "Contactos:\n" + "\n".join(lines)
    finally:
        session.close()


def delete_contact(name: str) -> str:
    """Delete a contact by name."""
    session = get_session()
    try:
        contact = (
            session.query(Contact)
            .filter(Contact.name.ilike(f"%{name}%"))
            .first()
        )
        if contact:
            deleted_name = contact.name
            session.delete(contact)
            session.commit()
            return f"✅ Contacto eliminado: {deleted_name}"
        return f"No encontré ningún contacto con el nombre '{name}'."
    except Exception as e:
        session.rollback()
        logger.exception("Failed to delete contact")
        return f"Error: {e}"
    finally:
        session.close()
