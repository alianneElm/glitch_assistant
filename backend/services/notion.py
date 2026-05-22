"""Notion integration for Glitch dashboard.

Creates and manages databases in Notion:
- Agenda (calendar events)
- Recordatorios (reminders)
- To-Do (tasks)
- Compras (shopping list)
- Log Glitch (interaction log)
"""

import logging
from datetime import datetime

from notion_client import Client

from backend.config import settings

logger = logging.getLogger(__name__)

_client: Client | None = None

# Database IDs are stored after creation/lookup
_db_ids: dict[str, str] = {}

# Database schemas
DATABASES = {
    "agenda": {
        "title": "Agenda",
        "icon": "📅",
        "properties": {
            "Evento": {"title": {}},
            "Fecha": {"date": {}},
            "Duración": {"number": {"format": "number"}},
            "Notas": {"rich_text": {}},
            "Estado": {
                "select": {
                    "options": [
                        {"name": "Pendiente", "color": "yellow"},
                        {"name": "Completado", "color": "green"},
                        {"name": "Cancelado", "color": "red"},
                    ]
                }
            },
        },
    },
    "recordatorios": {
        "title": "Recordatorios",
        "icon": "⏰",
        "properties": {
            "Recordatorio": {"title": {}},
            "Fecha": {"date": {}},
            "Estado": {
                "select": {
                    "options": [
                        {"name": "Pendiente", "color": "yellow"},
                        {"name": "Enviado", "color": "green"},
                    ]
                }
            },
        },
    },
    "todo": {
        "title": "To-Do",
        "icon": "✅",
        "properties": {
            "Tarea": {"title": {}},
            "Prioridad": {
                "select": {
                    "options": [
                        {"name": "Alta", "color": "red"},
                        {"name": "Media", "color": "yellow"},
                        {"name": "Baja", "color": "blue"},
                    ]
                }
            },
            "Deadline": {"date": {}},
            "Estado": {
                "select": {
                    "options": [
                        {"name": "Pendiente", "color": "yellow"},
                        {"name": "En progreso", "color": "blue"},
                        {"name": "Completado", "color": "green"},
                    ]
                }
            },
            "Notas": {"rich_text": {}},
        },
    },
    "compras": {
        "title": "Lista de Compras",
        "icon": "🛒",
        "properties": {
            "Item": {"title": {}},
            "Cantidad": {"number": {"format": "number"}},
            "Categoria": {
                "select": {
                    "options": [
                        {"name": "Comida", "color": "green"},
                        {"name": "Hogar", "color": "blue"},
                        {"name": "Higiene", "color": "purple"},
                        {"name": "Otro", "color": "gray"},
                    ]
                }
            },
            "Comprado": {"checkbox": {}},
        },
    },
    "log": {
        "title": "Log Glitch",
        "icon": "🤖",
        "properties": {
            "Resumen": {"title": {}},
            "Fecha": {"date": {}},
            "Tipo": {
                "select": {
                    "options": [
                        {"name": "Llamada", "color": "blue"},
                        {"name": "Mensaje", "color": "green"},
                        {"name": "Evento creado", "color": "purple"},
                        {"name": "Recordatorio", "color": "yellow"},
                        {"name": "Otro", "color": "gray"},
                    ]
                }
            },
            "Detalles": {"rich_text": {}},
        },
    },
}


def _get_client() -> Client:
    """Get or create Notion client."""
    global _client
    if _client is None:
        if not settings.notion_api_key:
            raise ValueError("NOTION_API_KEY not configured")
        _client = Client(auth=settings.notion_api_key)
    return _client


def _find_page_id() -> str:
    """Find the Glitch Dashboard page.

    The user must create a page called 'Glitch Dashboard' in Notion
    and connect the Glitch integration to it.
    """
    client = _get_client()

    # Search for existing page
    results = client.search(
        query="Glitch Dashboard",
        filter={"property": "object", "value": "page"},
    ).get("results", [])

    for page in results:
        title_prop = page.get("properties", {}).get("title", {})
        if title_prop:
            title_parts = title_prop.get("title", [])
            if title_parts and "Glitch" in title_parts[0].get("plain_text", ""):
                logger.info("Found Glitch Dashboard page: %s", page["id"])
                return page["id"]

    raise ValueError(
        "No se encontró la página 'Glitch Dashboard' en Notion. "
        "Créala manualmente y conecta la integración Glitch."
    )


def _find_or_create_db(parent_page_id: str, db_key: str) -> str:
    """Find or create a Notion database under the dashboard page."""
    client = _get_client()
    schema = DATABASES[db_key]
    db_title = schema["title"]

    # Search for existing database
    results = client.search(
        query=db_title,
        filter={"property": "object", "value": "database"},
    ).get("results", [])

    for db in results:
        title_parts = db.get("title", [])
        if title_parts and title_parts[0].get("plain_text", "") == db_title:
            db_id = db["id"]
            logger.info("Found existing database '%s': %s", db_title, db_id)
            return db_id

    # Create database
    new_db = client.databases.create(
        parent={"type": "page_id", "page_id": parent_page_id},
        title=[{"type": "text", "text": {"content": db_title}}],
        icon={"type": "emoji", "emoji": schema["icon"]},
        properties=schema["properties"],
    )
    db_id = new_db["id"]
    logger.info("Created database '%s': %s", db_title, db_id)
    return db_id


def init_notion() -> dict[str, str]:
    """Initialize all Notion databases. Returns dict of db_key -> db_id."""
    global _db_ids

    if not settings.notion_api_key:
        logger.info("Notion API key not configured, skipping init")
        return {}

    try:
        page_id = _find_page_id()

        for db_key in DATABASES:
            _db_ids[db_key] = _find_or_create_db(page_id, db_key)

        logger.info("Notion initialized: %s", {k: v[:8] + "..." for k, v in _db_ids.items()})
        return _db_ids
    except Exception:
        logger.exception("Failed to initialize Notion")
        return {}


def _get_db_id(db_key: str) -> str:
    """Get database ID, initializing if needed."""
    if db_key not in _db_ids:
        init_notion()
    db_id = _db_ids.get(db_key)
    if not db_id:
        raise ValueError(f"Notion database '{db_key}' not initialized")
    return db_id


# --- Public API: Add entries ---

def add_agenda_entry(
    event_title: str,
    start_time: str,
    duration_minutes: int = 60,
    notes: str = "",
) -> str:
    """Add a calendar event to the Notion Agenda database."""
    try:
        client = _get_client()
        db_id = _get_db_id("agenda")

        dt = datetime.fromisoformat(start_time)
        end_dt = dt.replace(minute=dt.minute + duration_minutes) if duration_minutes else None

        properties: dict = {
            "Evento": {"title": [{"text": {"content": event_title}}]},
            "Fecha": {
                "date": {
                    "start": dt.isoformat(),
                    **({"end": end_dt.isoformat()} if end_dt else {}),
                }
            },
            "Duración": {"number": duration_minutes},
            "Estado": {"select": {"name": "Pendiente"}},
        }
        if notes:
            properties["Notas"] = {"rich_text": [{"text": {"content": notes}}]}

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Notion agenda entry added: %s", event_title)
        return f"Agregado a Notion: {event_title}"
    except Exception as e:
        logger.exception("Failed to add agenda entry to Notion")
        return f"Error Notion: {e}"


def add_reminder_entry(reminder_text: str, remind_at: str, sent: bool = False) -> str:
    """Add a reminder to the Notion Recordatorios database."""
    try:
        client = _get_client()
        db_id = _get_db_id("recordatorios")

        dt = datetime.fromisoformat(remind_at)
        properties = {
            "Recordatorio": {"title": [{"text": {"content": reminder_text}}]},
            "Fecha": {"date": {"start": dt.isoformat()}},
            "Estado": {"select": {"name": "Enviado" if sent else "Pendiente"}},
        }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Notion reminder added: %s", reminder_text)
        return f"Recordatorio en Notion: {reminder_text}"
    except Exception as e:
        logger.exception("Failed to add reminder to Notion")
        return f"Error Notion: {e}"


def add_todo(
    task: str,
    priority: str = "Media",
    deadline: str = "",
    notes: str = "",
) -> str:
    """Add a task to the Notion To-Do database."""
    try:
        client = _get_client()
        db_id = _get_db_id("todo")

        properties: dict = {
            "Tarea": {"title": [{"text": {"content": task}}]},
            "Prioridad": {"select": {"name": priority}},
            "Estado": {"select": {"name": "Pendiente"}},
        }
        if deadline:
            dt = datetime.fromisoformat(deadline)
            properties["Deadline"] = {"date": {"start": dt.date().isoformat()}}
        if notes:
            properties["Notas"] = {"rich_text": [{"text": {"content": notes}}]}

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Notion to-do added: %s", task)
        return f"Tarea agregada: {task}"
    except Exception as e:
        logger.exception("Failed to add to-do to Notion")
        return f"Error Notion: {e}"


def add_shopping_item(item: str, quantity: int = 1, category: str = "Otro") -> str:
    """Add an item to the Notion shopping list."""
    try:
        client = _get_client()
        db_id = _get_db_id("compras")

        properties = {
            "Item": {"title": [{"text": {"content": item}}]},
            "Cantidad": {"number": quantity},
            "Categoria": {"select": {"name": category}},
            "Comprado": {"checkbox": False},
        }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Notion shopping item added: %s", item)
        return f"Agregado a compras: {item}"
    except Exception as e:
        logger.exception("Failed to add shopping item to Notion")
        return f"Error Notion: {e}"


def add_log_entry(summary: str, log_type: str = "Otro", details: str = "") -> str:
    """Add an interaction log entry to Notion."""
    try:
        client = _get_client()
        db_id = _get_db_id("log")

        properties: dict = {
            "Resumen": {"title": [{"text": {"content": summary}}]},
            "Fecha": {"date": {"start": datetime.now().isoformat()}},
            "Tipo": {"select": {"name": log_type}},
        }
        if details:
            # Truncate details to Notion's limit (2000 chars)
            properties["Detalles"] = {
                "rich_text": [{"text": {"content": details[:2000]}}]
            }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Notion log entry added: %s (%s)", summary, log_type)
        return f"Log registrado: {summary}"
    except Exception as e:
        logger.exception("Failed to add log entry to Notion")
        return f"Error Notion: {e}"


def update_todo_status(task_name: str, status: str = "Completado") -> str:
    """Update a to-do item's status by searching for it."""
    try:
        client = _get_client()
        db_id = _get_db_id("todo")

        # Search for the task
        results = client.databases.query(
            database_id=db_id,
            filter={
                "property": "Tarea",
                "title": {"contains": task_name},
            },
        ).get("results", [])

        if not results:
            return f"No encontré la tarea '{task_name}' en Notion."

        page_id = results[0]["id"]
        client.pages.update(
            page_id=page_id,
            properties={"Estado": {"select": {"name": status}}},
        )
        logger.info("Notion to-do updated: %s -> %s", task_name, status)
        return f"Tarea actualizada: {task_name} -> {status}"
    except Exception as e:
        logger.exception("Failed to update to-do in Notion")
        return f"Error Notion: {e}"
