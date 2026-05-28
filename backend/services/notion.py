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
from zoneinfo import ZoneInfo

from notion_client import Client

from backend.config import settings

logger = logging.getLogger(__name__)


def _now() -> datetime:
    """Get current datetime in user's timezone."""
    return datetime.now(ZoneInfo(settings.user_timezone))

from typing import Optional
_client: Optional[Client] = None

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
    "nutricion": {
        "title": "Diario Nutricional",
        "icon": "🍽️",
        "properties": {
            "Comida": {"title": {}},
            "Fecha": {"date": {}},
            "Calorías": {"number": {"format": "number"}},
            "Proteínas (g)": {"number": {"format": "number"}},
            "Carbohidratos (g)": {"number": {"format": "number"}},
            "Grasas (g)": {"number": {"format": "number"}},
            "Comida del día": {
                "select": {
                    "options": [
                        {"name": "Desayuno", "color": "yellow"},
                        {"name": "Almuerzo", "color": "orange"},
                        {"name": "Cena", "color": "blue"},
                        {"name": "Snack", "color": "green"},
                    ]
                }
            },
            "Notas": {"rich_text": {}},
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
    "notas": {
        "title": "Notas Rapidas",
        "icon": "📝",
        "properties": {
            "Nota": {"title": {}},
            "Fecha": {"date": {}},
            "Categoria": {
                "select": {
                    "options": [
                        {"name": "General", "color": "gray"},
                        {"name": "Idea", "color": "purple"},
                        {"name": "Codigo", "color": "blue"},
                        {"name": "Personal", "color": "green"},
                        {"name": "Trabajo", "color": "orange"},
                        {"name": "Salud", "color": "red"},
                    ]
                }
            },
            "Detalles": {"rich_text": {}},
            "Archivada": {"checkbox": {}},
        },
    },
    "gastos": {
        "title": "Control de Gastos",
        "icon": "💰",
        "properties": {
            "Concepto": {"title": {}},
            "Monto": {"number": {"format": "number"}},
            "Moneda": {
                "select": {
                    "options": [
                        {"name": "SEK", "color": "blue"},
                        {"name": "EUR", "color": "green"},
                        {"name": "USD", "color": "yellow"},
                    ]
                }
            },
            "Categoria": {
                "select": {
                    "options": [
                        {"name": "Comida", "color": "green"},
                        {"name": "Transporte", "color": "blue"},
                        {"name": "Hogar", "color": "orange"},
                        {"name": "Entretenimiento", "color": "purple"},
                        {"name": "Salud", "color": "red"},
                        {"name": "Ropa", "color": "pink"},
                        {"name": "Servicios", "color": "yellow"},
                        {"name": "Suscripciones", "color": "gray"},
                        {"name": "Educacion", "color": "blue"},
                        {"name": "Restaurante", "color": "orange"},
                        {"name": "Otro", "color": "gray"},
                    ]
                }
            },
            "Fecha": {"date": {}},
            "Metodo": {
                "select": {
                    "options": [
                        {"name": "Tarjeta", "color": "blue"},
                        {"name": "Efectivo", "color": "green"},
                        {"name": "Swish", "color": "purple"},
                        {"name": "Transferencia", "color": "yellow"},
                    ]
                }
            },
            "Notas": {"rich_text": {}},
            "Recurrente": {"checkbox": {}},
        },
    },
    "roadmap": {
        "title": "Glitch Roadmap",
        "icon": "🚀",
        "properties": {
            "Feature": {"title": {}},
            "Estado": {
                "select": {
                    "options": [
                        {"name": "Hecho", "color": "green"},
                        {"name": "En progreso", "color": "blue"},
                        {"name": "Pendiente", "color": "yellow"},
                        {"name": "Idea", "color": "purple"},
                    ]
                }
            },
            "Categoria": {
                "select": {
                    "options": [
                        {"name": "Comunicacion", "color": "blue"},
                        {"name": "Productividad", "color": "green"},
                        {"name": "Salud", "color": "red"},
                        {"name": "Informacion", "color": "orange"},
                        {"name": "Hardware", "color": "purple"},
                        {"name": "Plataforma", "color": "pink"},
                        {"name": "IA", "color": "gray"},
                    ]
                }
            },
            "Prioridad": {
                "select": {
                    "options": [
                        {"name": "Alta", "color": "red"},
                        {"name": "Media", "color": "yellow"},
                        {"name": "Baja", "color": "blue"},
                    ]
                }
            },
            "Fecha completado": {"date": {}},
            "Notas": {"rich_text": {}},
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
        from datetime import timedelta as _td

        client = _get_client()
        db_id = _get_db_id("agenda")

        # Parse with timezone support (handles "Z" suffix and naive datetimes)
        raw = start_time
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(settings.user_timezone))
        dt = dt.astimezone(ZoneInfo(settings.user_timezone))

        end_dt = dt + _td(minutes=duration_minutes) if duration_minutes else None

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

        raw_r = remind_at.replace("Z", "+00:00") if remind_at.endswith("Z") else remind_at
        dt = datetime.fromisoformat(raw_r)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(settings.user_timezone))
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
            raw_d = deadline.replace("Z", "+00:00") if deadline.endswith("Z") else deadline
            dt = datetime.fromisoformat(raw_d)
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


def add_shopping_items_batch(items: list[dict]) -> str:
    """Add multiple items to the shopping list in one call.

    Args:
        items: List of dicts with keys: item (str), quantity (int, optional), category (str, optional)
              e.g. [{"item": "Huevos", "quantity": 12, "category": "Comida"}, ...]
    """
    try:
        client = _get_client()
        db_id = _get_db_id("compras")

        added = []
        for entry in items:
            item_name = entry.get("item", "")
            if not item_name:
                continue
            quantity = entry.get("quantity", 1)
            category = entry.get("category", "Otro")

            properties = {
                "Item": {"title": [{"text": {"content": item_name}}]},
                "Cantidad": {"number": quantity},
                "Categoria": {"select": {"name": category}},
                "Comprado": {"checkbox": False},
            }
            client.pages.create(parent={"database_id": db_id}, properties=properties)
            added.append(item_name)

        logger.info("Notion shopping batch: %d items added", len(added))
        return f"✅ {len(added)} items agregados a la lista de compras: {', '.join(added)}"
    except Exception as e:
        logger.exception("Failed to add shopping items batch to Notion")
        return f"Error Notion: {e}"


def clear_shopping_list() -> str:
    """Archive all items in the shopping list (marks as done and removes from view)."""
    try:
        client = _get_client()
        db_id = _get_db_id("compras")

        # Get all non-purchased items
        results = client.databases.query(
            database_id=db_id,
            filter={"property": "Comprado", "checkbox": {"equals": False}},
        ).get("results", [])

        if not results:
            return "La lista de compras ya está vacía."

        count = 0
        for page in results:
            # Archive the page (soft delete)
            client.pages.update(page_id=page["id"], archived=True)
            count += 1

        logger.info("Shopping list cleared: %d items archived", count)
        return f"Lista de compras vaciada ({count} items archivados). Lista limpia para la próxima semana."
    except Exception as e:
        logger.exception("Failed to clear shopping list")
        return f"Error al vaciar la lista: {e}"


def add_log_entry(summary: str, log_type: str = "Otro", details: str = "") -> str:
    """Add an interaction log entry to Notion."""
    try:
        client = _get_client()
        db_id = _get_db_id("log")

        properties: dict = {
            "Resumen": {"title": [{"text": {"content": summary}}]},
            "Fecha": {"date": {"start": _now().isoformat()}},
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


def log_food(
    description: str,
    calories: int,
    protein: float,
    carbs: float,
    fat: float,
    meal_type: str = "Snack",
    notes: str = "",
) -> str:
    """Log a food entry to the Notion nutrition diary.

    Args:
        description: What was eaten, e.g. "100g gambas con ensalada de tomate y café con leche"
        calories: Estimated total calories
        protein: Grams of protein
        carbs: Grams of carbohydrates
        fat: Grams of fat
        meal_type: "Desayuno", "Almuerzo", "Cena", or "Snack"
        notes: Optional notes (breakdown per item, etc.)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("nutricion")

        properties: dict = {
            "Comida": {"title": [{"text": {"content": description}}]},
            "Fecha": {"date": {"start": _now().isoformat()}},
            "Calorías": {"number": calories},
            "Proteínas (g)": {"number": round(protein, 1)},
            "Carbohidratos (g)": {"number": round(carbs, 1)},
            "Grasas (g)": {"number": round(fat, 1)},
            "Comida del día": {"select": {"name": meal_type}},
        }
        if notes:
            properties["Notas"] = {
                "rich_text": [{"text": {"content": notes[:2000]}}]
            }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Food logged: %s (%d kcal)", description, calories)
        return (
            f"🍽️ Registrado: {description}\n"
            f"📊 {calories} kcal | P: {protein:.1f}g | C: {carbs:.1f}g | G: {fat:.1f}g"
        )
    except Exception as e:
        logger.exception("Failed to log food to Notion")
        return f"Error al registrar comida: {e}"


def get_daily_nutrition(date_str: str = "") -> str:
    """Get today's (or a specific date's) food log with macro totals.

    Args:
        date_str: Date in YYYY-MM-DD format. Empty = today.
    """
    try:
        client = _get_client()
        db_id = _get_db_id("nutricion")

        if not date_str:
            date_str = _now().strftime("%Y-%m-%d")

        # Query all food entries for the date
        results = client.databases.query(
            database_id=db_id,
            filter={
                "property": "Fecha",
                "date": {"on_or_after": f"{date_str}T00:00:00"},
            },
            sorts=[{"property": "Fecha", "direction": "ascending"}],
        ).get("results", [])

        # Filter to only this specific date (not future dates)
        day_entries = []
        for page in results:
            fecha = page["properties"].get("Fecha", {}).get("date", {})
            if fecha and fecha.get("start", "").startswith(date_str):
                day_entries.append(page)

        if not day_entries:
            return f"No hay registros de comida para {date_str}."

        # Build summary
        total_cal = 0
        total_p = 0.0
        total_c = 0.0
        total_g = 0.0
        lines = []

        meal_icons = {
            "Desayuno": "🌅",
            "Almuerzo": "☀️",
            "Cena": "🌙",
            "Snack": "🍎",
        }

        for page in day_entries:
            props = page["properties"]
            title = props.get("Comida", {}).get("title", [])
            name = title[0]["plain_text"] if title else "Sin nombre"
            cal = props.get("Calorías", {}).get("number", 0) or 0
            prot = props.get("Proteínas (g)", {}).get("number", 0) or 0
            carb = props.get("Carbohidratos (g)", {}).get("number", 0) or 0
            fat = props.get("Grasas (g)", {}).get("number", 0) or 0
            meal = props.get("Comida del día", {}).get("select", {})
            meal_name = meal.get("name", "Snack") if meal else "Snack"
            icon = meal_icons.get(meal_name, "🍽️")

            total_cal += cal
            total_p += prot
            total_c += carb
            total_g += fat

            lines.append(f"{icon} {name} — {cal} kcal (P:{prot:.0f} C:{carb:.0f} G:{fat:.0f})")

        header = f"📋 Diario nutricional — {date_str}\n"
        entries = "\n".join(lines)
        totals = (
            f"\n━━━━━━━━━━━━━━━\n"
            f"📊 TOTAL: {total_cal} kcal\n"
            f"🥩 Proteínas: {total_p:.1f}g\n"
            f"🍞 Carbohidratos: {total_c:.1f}g\n"
            f"🧈 Grasas: {total_g:.1f}g"
        )

        return header + entries + totals
    except Exception as e:
        logger.exception("Failed to get daily nutrition from Notion")
        return f"Error al consultar nutrición: {e}"


def log_foods_batch(entries: list[dict]) -> str:
    """Log multiple food items as SEPARATE entries in one call.

    Args:
        entries: List of dicts, each with: description, calories, protein, carbs, fat, meal_type (optional), notes (optional)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("nutricion")
        now_iso = _now().isoformat()

        logged = []
        total_cal = 0
        for entry in entries:
            desc = entry.get("description", "")
            if not desc:
                continue
            cal = entry.get("calories", 0)
            prot = entry.get("protein", 0)
            carb = entry.get("carbs", 0)
            fat = entry.get("fat", 0)
            meal = entry.get("meal_type", "Almuerzo")
            notes = entry.get("notes", "")

            properties: dict = {
                "Comida": {"title": [{"text": {"content": desc}}]},
                "Fecha": {"date": {"start": now_iso}},
                "Calorías": {"number": cal},
                "Proteínas (g)": {"number": round(prot, 1)},
                "Carbohidratos (g)": {"number": round(carb, 1)},
                "Grasas (g)": {"number": round(fat, 1)},
                "Comida del día": {"select": {"name": meal}},
            }
            if notes:
                properties["Notas"] = {"rich_text": [{"text": {"content": notes[:2000]}}]}

            client.pages.create(parent={"database_id": db_id}, properties=properties)
            logged.append(f"{desc} ({cal} kcal)")
            total_cal += cal

        logger.info("Food batch logged: %d items, %d kcal total", len(logged), total_cal)
        items_str = "\n".join(f"  • {item}" for item in logged)
        return f"🍽️ {len(logged)} alimentos registrados:\n{items_str}\n📊 Total: {total_cal} kcal"
    except Exception as e:
        logger.exception("Failed to log food batch")
        return f"Error al registrar: {e}"


def edit_food_entry(
    search_text: str,
    new_description: str = "",
    new_calories: int = 0,
    new_protein: float = 0,
    new_carbs: float = 0,
    new_fat: float = 0,
    new_meal_type: str = "",
) -> str:
    """Edit a food entry in today's nutrition diary by searching its name.

    Args:
        search_text: Text to search for in food entries (partial match)
        new_description: New description (empty = keep current)
        new_calories: New calories (0 = keep current)
        new_protein: New protein grams (0 = keep current)
        new_carbs: New carbs grams (0 = keep current)
        new_fat: New fat grams (0 = keep current)
        new_meal_type: New meal type (empty = keep current)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("nutricion")
        today = _now().strftime("%Y-%m-%d")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Comida", "title": {"contains": search_text}},
                    {"property": "Fecha", "date": {"on_or_after": f"{today}T00:00:00"}},
                ]
            },
        ).get("results", [])

        # Filter to today only
        entries = [p for p in results if p["properties"].get("Fecha", {}).get("date", {}).get("start", "").startswith(today)]

        if not entries:
            return f"No encontré '{search_text}' en el diario de hoy."

        page = entries[0]
        page_id = page["id"]
        old_title = page["properties"].get("Comida", {}).get("title", [])
        old_name = old_title[0]["plain_text"] if old_title else search_text

        updated = {}
        if new_description:
            updated["Comida"] = {"title": [{"text": {"content": new_description}}]}
        if new_calories:
            updated["Calorías"] = {"number": new_calories}
        if new_protein:
            updated["Proteínas (g)"] = {"number": round(new_protein, 1)}
        if new_carbs:
            updated["Carbohidratos (g)"] = {"number": round(new_carbs, 1)}
        if new_fat:
            updated["Grasas (g)"] = {"number": round(new_fat, 1)}
        if new_meal_type:
            updated["Comida del día"] = {"select": {"name": new_meal_type}}

        if not updated:
            return "No especificaste qué cambiar."

        client.pages.update(page_id=page_id, properties=updated)
        logger.info("Food entry edited: '%s'", old_name)
        return f"✅ Entrada editada: '{old_name}'"
    except Exception as e:
        logger.exception("Failed to edit food entry")
        return f"Error al editar: {e}"


def delete_food_entry(search_text: str) -> str:
    """Delete a food entry from today's nutrition diary by searching its name.

    Args:
        search_text: Text to search for in food entries (partial match)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("nutricion")
        today = _now().strftime("%Y-%m-%d")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Comida", "title": {"contains": search_text}},
                    {"property": "Fecha", "date": {"on_or_after": f"{today}T00:00:00"}},
                ]
            },
        ).get("results", [])

        entries = [p for p in results if p["properties"].get("Fecha", {}).get("date", {}).get("start", "").startswith(today)]

        if not entries:
            return f"No encontré '{search_text}' en el diario de hoy."

        page = entries[0]
        page_id = page["id"]
        title = page["properties"].get("Comida", {}).get("title", [])
        name = title[0]["plain_text"] if title else search_text
        cal = page["properties"].get("Calorías", {}).get("number", 0) or 0

        client.pages.update(page_id=page_id, archived=True)
        logger.info("Food entry deleted: '%s' (%d kcal)", name, cal)
        return f"🗑️ Eliminado: '{name}' ({cal} kcal)"
    except Exception as e:
        logger.exception("Failed to delete food entry")
        return f"Error al eliminar: {e}"


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


# --- Public API: Read entries ---

def get_todos(status_filter: str = "") -> str:
    """Get tasks from the Notion To-Do database.

    Args:
        status_filter: Optional filter: 'Pendiente', 'En progreso', 'Completado', or '' for all.
    """
    try:
        client = _get_client()
        db_id = _get_db_id("todo")

        kwargs: dict = {"database_id": db_id}
        if status_filter:
            kwargs["filter"] = {
                "property": "Estado",
                "select": {"equals": status_filter},
            }

        results = client.databases.query(**kwargs).get("results", [])

        if not results:
            if status_filter:
                return f"No hay tareas con estado '{status_filter}'."
            return "No hay tareas en tu lista."

        lines = []
        for page in results:
            props = page["properties"]
            # Title
            title_parts = props.get("Tarea", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "Sin título"
            # Status
            estado = props.get("Estado", {}).get("select", {})
            estado_name = estado.get("name", "?") if estado else "?"
            # Priority
            prioridad = props.get("Prioridad", {}).get("select", {})
            prio_name = prioridad.get("name", "") if prioridad else ""
            # Deadline
            deadline = props.get("Deadline", {}).get("date", {})
            deadline_str = ""
            if deadline and deadline.get("start"):
                deadline_str = f" (fecha: {deadline['start']})"
            # Notes
            notas_parts = props.get("Notas", {}).get("rich_text", [])
            notas = notas_parts[0]["plain_text"] if notas_parts else ""

            prio_icon = {"Alta": "🔴", "Media": "🟡", "Baja": "🔵"}.get(prio_name, "")
            status_icon = {"Pendiente": "⬜", "En progreso": "🔄", "Completado": "✅"}.get(estado_name, "")

            line = f"{status_icon} {prio_icon} {title}{deadline_str}"
            if notas:
                line += f"\n   📝 {notas}"
            lines.append(line)

        header = f"Tareas ({status_filter}):" if status_filter else "Todas las tareas:"
        result = f"{header}\n" + "\n".join(lines)
        result += "\n\n💡 Dime el nombre de la tarea para marcarla como completada."
        return result

    except Exception as e:
        logger.exception("Failed to get todos from Notion")
        return f"Error al leer tareas: {e}"


def get_shopping_list() -> str:
    """Get the current shopping list from Notion (non-purchased items)."""
    try:
        client = _get_client()
        db_id = _get_db_id("compras")

        results = client.databases.query(
            database_id=db_id,
            filter={"property": "Comprado", "checkbox": {"equals": False}},
        ).get("results", [])

        if not results:
            return "La lista de compras está vacía."

        # Group by category
        categories: dict[str, list[str]] = {}
        for page in results:
            props = page["properties"]
            title_parts = props.get("Item", {}).get("title", [])
            item = title_parts[0]["plain_text"] if title_parts else "?"
            cantidad = props.get("Cantidad", {}).get("number", 1) or 1
            cat_select = props.get("Categoria", {}).get("select", {})
            cat = cat_select.get("name", "Otro") if cat_select else "Otro"

            qty_str = f" x{cantidad}" if cantidad > 1 else ""
            categories.setdefault(cat, []).append(f"{item}{qty_str}")

        cat_icons = {"Comida": "🥬", "Hogar": "🏠", "Higiene": "🧴", "Otro": "📦"}
        lines = []
        for cat, items in categories.items():
            icon = cat_icons.get(cat, "📦")
            lines.append(f"\n{icon} {cat}")
            for item in items:
                lines.append(f"  ⬜ {item}")

        result = f"Lista de compras ({len(results)} items):" + "\n".join(lines)
        result += "\n\n💡 Dime qué ya compraste para marcarlo ✅"
        return result

    except Exception as e:
        logger.exception("Failed to get shopping list from Notion")
        return f"Error al leer la lista de compras: {e}"


def get_recent_logs(limit: int = 10) -> str:
    """Get recent interaction logs from Notion."""
    try:
        client = _get_client()
        db_id = _get_db_id("log")

        results = client.databases.query(
            database_id=db_id,
            sorts=[{"property": "Fecha", "direction": "descending"}],
            page_size=limit,
        ).get("results", [])

        if not results:
            return "No hay registros en el log."

        lines = []
        for page in results:
            props = page["properties"]
            title_parts = props.get("Resumen", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "?"
            tipo = props.get("Tipo", {}).get("select", {})
            tipo_name = tipo.get("name", "?") if tipo else "?"
            fecha = props.get("Fecha", {}).get("date", {})
            fecha_str = fecha.get("start", "?")[:16] if fecha else "?"

            tipo_icons = {"Llamada": "📞", "Mensaje": "💬", "Evento creado": "📅", "Recordatorio": "⏰", "Otro": "📝"}
            icon = tipo_icons.get(tipo_name, "📝")
            lines.append(f"{icon} {fecha_str} — {title}")

        return f"Últimos {len(results)} registros:\n" + "\n".join(lines)

    except Exception as e:
        logger.exception("Failed to get logs from Notion")
        return f"Error al leer el log: {e}"


def mark_shopping_item(item_name: str) -> str:
    """Mark a shopping item as purchased by searching for it."""
    try:
        client = _get_client()
        db_id = _get_db_id("compras")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Item", "title": {"contains": item_name}},
                    {"property": "Comprado", "checkbox": {"equals": False}},
                ]
            },
        ).get("results", [])

        if not results:
            return f"No encontré '{item_name}' en la lista de compras."

        page = results[0]
        actual_name = page["properties"]["Item"]["title"][0]["plain_text"]
        client.pages.update(
            page_id=page["id"],
            properties={"Comprado": {"checkbox": True}},
        )
        logger.info("Shopping item marked as purchased: %s", actual_name)
        return f"✅ {actual_name} — comprado"

    except Exception as e:
        logger.exception("Failed to mark shopping item")
        return f"Error: {e}"


# --- Notas Rapidas ---

def add_note(note_text: str, category: str = "General", details: str = "") -> str:
    """Save a quick note to Notion.

    Args:
        note_text: Short note title/summary
        category: 'General', 'Idea', 'Codigo', 'Personal', 'Trabajo', 'Salud'
        details: Optional longer description or details
    """
    try:
        client = _get_client()
        db_id = _get_db_id("notas")

        properties: dict = {
            "Nota": {"title": [{"text": {"content": note_text}}]},
            "Fecha": {"date": {"start": _now().isoformat()}},
            "Categoria": {"select": {"name": category}},
            "Archivada": {"checkbox": False},
        }
        if details:
            properties["Detalles"] = {
                "rich_text": [{"text": {"content": details[:2000]}}]
            }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Note saved: %s (%s)", note_text, category)
        return f"📝 Nota guardada: {note_text}"
    except Exception as e:
        logger.exception("Failed to save note to Notion")
        return f"Error al guardar nota: {e}"


def get_notes(category: str = "", limit: int = 10) -> str:
    """Get recent notes from Notion.

    Args:
        category: Optional filter by category. Empty = all.
        limit: Number of notes to show (default 10)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("notas")

        query_filter: dict = {"property": "Archivada", "checkbox": {"equals": False}}

        if category:
            query_filter = {
                "and": [
                    {"property": "Archivada", "checkbox": {"equals": False}},
                    {"property": "Categoria", "select": {"equals": category}},
                ]
            }

        results = client.databases.query(
            database_id=db_id,
            filter=query_filter,
            sorts=[{"property": "Fecha", "direction": "descending"}],
            page_size=limit,
        ).get("results", [])

        if not results:
            if category:
                return f"No hay notas en la categoria '{category}'."
            return "No tienes notas guardadas."

        cat_icons = {
            "General": "📝", "Idea": "💡", "Codigo": "💻",
            "Personal": "👤", "Trabajo": "💼", "Salud": "❤️",
        }

        lines = []
        for page in results:
            props = page["properties"]
            title_parts = props.get("Nota", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "?"
            cat = props.get("Categoria", {}).get("select", {})
            cat_name = cat.get("name", "General") if cat else "General"
            fecha = props.get("Fecha", {}).get("date", {})
            fecha_str = fecha.get("start", "")[:10] if fecha else ""
            details_parts = props.get("Detalles", {}).get("rich_text", [])
            details_text = details_parts[0]["plain_text"] if details_parts else ""

            icon = cat_icons.get(cat_name, "📝")
            line = f"{icon} {title}"
            if fecha_str:
                line += f" ({fecha_str})"
            if details_text:
                # Show first 80 chars of details
                preview = details_text[:80]
                if len(details_text) > 80:
                    preview += "..."
                line += f"\n   {preview}"
            lines.append(line)

        header = f"Notas ({category}):" if category else f"Tus notas ({len(results)}):"
        return header + "\n" + "\n".join(lines)

    except Exception as e:
        logger.exception("Failed to get notes from Notion")
        return f"Error al leer notas: {e}"


def search_notes(query: str) -> str:
    """Search notes by text content.

    Args:
        query: Text to search for in note titles and details
    """
    try:
        client = _get_client()
        db_id = _get_db_id("notas")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Nota", "title": {"contains": query}},
                    {"property": "Archivada", "checkbox": {"equals": False}},
                ]
            },
        ).get("results", [])

        if not results:
            return f"No encontre notas con '{query}'."

        cat_icons = {
            "General": "📝", "Idea": "💡", "Codigo": "💻",
            "Personal": "👤", "Trabajo": "💼", "Salud": "❤️",
        }

        lines = [f"Notas con '{query}':"]
        for page in results:
            props = page["properties"]
            title_parts = props.get("Nota", {}).get("title", [])
            title = title_parts[0]["plain_text"] if title_parts else "?"
            cat = props.get("Categoria", {}).get("select", {})
            cat_name = cat.get("name", "General") if cat else "General"
            icon = cat_icons.get(cat_name, "📝")
            details_parts = props.get("Detalles", {}).get("rich_text", [])
            details_text = details_parts[0]["plain_text"] if details_parts else ""

            line = f"{icon} {title}"
            if details_text:
                preview = details_text[:80]
                if len(details_text) > 80:
                    preview += "..."
                line += f"\n   {preview}"
            lines.append(line)

        return "\n".join(lines)

    except Exception as e:
        logger.exception("Failed to search notes")
        return f"Error al buscar: {e}"


def delete_note(search_text: str) -> str:
    """Archive (soft-delete) a note by searching its title.

    Args:
        search_text: Text to search for in note titles (partial match)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("notas")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "and": [
                    {"property": "Nota", "title": {"contains": search_text}},
                    {"property": "Archivada", "checkbox": {"equals": False}},
                ]
            },
        ).get("results", [])

        if not results:
            return f"No encontre nota con '{search_text}'."

        page = results[0]
        title = page["properties"]["Nota"]["title"][0]["plain_text"]
        client.pages.update(
            page_id=page["id"],
            properties={"Archivada": {"checkbox": True}},
        )
        logger.info("Note archived: %s", title)
        return f"🗑️ Nota archivada: {title}"

    except Exception as e:
        logger.exception("Failed to delete note")
        return f"Error: {e}"


# ═══════════════════════════════════════════════════════════════════
# Expense tracking — Control de Gastos
# ═══════════════════════════════════════════════════════════════════


def add_expense(
    concept: str,
    amount: float,
    category: str = "Otro",
    currency: str = "SEK",
    payment_method: str = "Tarjeta",
    notes: str = "",
    is_recurring: bool = False,
) -> str:
    """Add an expense entry.

    Args:
        concept: What was bought (e.g. "Almuerzo en Max")
        amount: How much it cost
        category: Comida, Transporte, Hogar, Entretenimiento, Salud,
                  Ropa, Servicios, Suscripciones, Educacion, Restaurante, Otro
        currency: SEK, EUR, USD
        payment_method: Tarjeta, Efectivo, Swish, Transferencia
        notes: Optional extra details
        is_recurring: Whether this is a recurring expense (e.g. subscription)
    """
    try:
        client = _get_client()
        db_id = _get_db_id("gastos")

        properties: dict = {
            "Concepto": {"title": [{"text": {"content": concept}}]},
            "Monto": {"number": amount},
            "Moneda": {"select": {"name": currency}},
            "Categoria": {"select": {"name": category}},
            "Fecha": {"date": {"start": _now().isoformat()}},
            "Metodo": {"select": {"name": payment_method}},
            "Recurrente": {"checkbox": is_recurring},
        }
        if notes:
            properties["Notas"] = {
                "rich_text": [{"text": {"content": notes[:2000]}}]
            }

        client.pages.create(parent={"database_id": db_id}, properties=properties)
        logger.info("Expense added: %s — %.2f %s (%s)", concept, amount, currency, category)
        return f"💰 Registrado: {concept} — {amount:.0f} {currency} ({category})"

    except Exception as e:
        logger.exception("Failed to add expense")
        return f"Error al registrar gasto: {e}"


def get_expenses_summary(period: str = "month") -> str:
    """Get expense summary for a period.

    Args:
        period: 'today', 'week', 'month', 'year'
    """
    try:
        client = _get_client()
        db_id = _get_db_id("gastos")

        now = _now()
        if period == "today":
            start_date = now.strftime("%Y-%m-%d")
            label = "hoy"
        elif period == "week":
            from datetime import timedelta
            start_dt = now - timedelta(days=now.weekday())
            start_date = start_dt.strftime("%Y-%m-%d")
            label = "esta semana"
        elif period == "year":
            start_date = f"{now.year}-01-01"
            label = f"este año ({now.year})"
        else:  # month
            start_date = f"{now.year}-{now.month:02d}-01"
            month_names = [
                "enero", "febrero", "marzo", "abril", "mayo", "junio",
                "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
            ]
            label = month_names[now.month - 1]

        results = client.databases.query(
            database_id=db_id,
            filter={
                "property": "Fecha",
                "date": {"on_or_after": f"{start_date}T00:00:00"},
            },
            sorts=[{"property": "Fecha", "direction": "descending"}],
        ).get("results", [])

        if not results:
            return f"No hay gastos registrados para {label}."

        # Aggregate by category
        by_category: dict[str, float] = {}
        total = 0.0
        currency = "SEK"
        count = 0

        for page in results:
            props = page["properties"]
            amount = props.get("Monto", {}).get("number", 0) or 0
            cat_sel = props.get("Categoria", {}).get("select")
            cat = cat_sel["name"] if cat_sel else "Otro"
            cur_sel = props.get("Moneda", {}).get("select")
            if cur_sel:
                currency = cur_sel["name"]

            by_category[cat] = by_category.get(cat, 0) + amount
            total += amount
            count += 1

        # Sort categories by amount
        sorted_cats = sorted(by_category.items(), key=lambda x: x[1], reverse=True)

        lines = [f"💰 Gastos de {label}: {total:.0f} {currency} ({count} gastos)"]
        lines.append("")
        for cat, amt in sorted_cats:
            pct = (amt / total * 100) if total else 0
            bar = "█" * max(1, round(pct / 5))
            lines.append(f"  {cat}: {amt:.0f} {currency} ({pct:.0f}%) {bar}")

        return "\n".join(lines)

    except Exception as e:
        logger.exception("Failed to get expense summary")
        return f"Error al consultar gastos: {e}"


def get_expenses_list(
    period: str = "week",
    category: str = "",
    limit: int = 20,
) -> str:
    """Get detailed list of recent expenses.

    Args:
        period: 'today', 'week', 'month'
        category: Filter by category (empty = all)
        limit: Max entries to show
    """
    try:
        client = _get_client()
        db_id = _get_db_id("gastos")

        now = _now()
        if period == "today":
            start_date = now.strftime("%Y-%m-%d")
        elif period == "month":
            start_date = f"{now.year}-{now.month:02d}-01"
        else:  # week
            from datetime import timedelta
            start_dt = now - timedelta(days=now.weekday())
            start_date = start_dt.strftime("%Y-%m-%d")

        filters: list = [
            {"property": "Fecha", "date": {"on_or_after": f"{start_date}T00:00:00"}},
        ]
        if category:
            filters.append({"property": "Categoria", "select": {"equals": category}})

        query_filter = {"and": filters} if len(filters) > 1 else filters[0]

        results = client.databases.query(
            database_id=db_id,
            filter=query_filter,
            sorts=[{"property": "Fecha", "direction": "descending"}],
            page_size=limit,
        ).get("results", [])

        if not results:
            cat_msg = f" en {category}" if category else ""
            return f"No hay gastos{cat_msg} en este periodo."

        lines = []
        total = 0.0
        for page in results:
            props = page["properties"]
            concept = props["Concepto"]["title"][0]["plain_text"] if props["Concepto"]["title"] else "?"
            amount = props.get("Monto", {}).get("number", 0) or 0
            cat_sel = props.get("Categoria", {}).get("select")
            cat = cat_sel["name"] if cat_sel else ""
            cur_sel = props.get("Moneda", {}).get("select")
            currency = cur_sel["name"] if cur_sel else "SEK"
            date_prop = props.get("Fecha", {}).get("date")
            date_str = date_prop["start"][:10] if date_prop else ""

            total += amount
            lines.append(f"• {date_str} — {concept}: {amount:.0f} {currency} [{cat}]")

        header = f"Últimos gastos ({len(results)} entradas, total: {total:.0f}):"
        return header + "\n" + "\n".join(lines)

    except Exception as e:
        logger.exception("Failed to list expenses")
        return f"Error: {e}"


def delete_expense(search_text: str) -> str:
    """Delete an expense by searching its concept.

    Args:
        search_text: Text to search for in expense concepts
    """
    try:
        client = _get_client()
        db_id = _get_db_id("gastos")

        results = client.databases.query(
            database_id=db_id,
            filter={
                "property": "Concepto",
                "title": {"contains": search_text},
            },
            sorts=[{"property": "Fecha", "direction": "descending"}],
            page_size=1,
        ).get("results", [])

        if not results:
            return f"No encontré un gasto con '{search_text}'."

        page = results[0]
        concept = page["properties"]["Concepto"]["title"][0]["plain_text"]
        amount = page["properties"].get("Monto", {}).get("number", 0)

        client.pages.update(page_id=page["id"], archived=True)
        logger.info("Expense deleted: %s (%.2f)", concept, amount or 0)
        return f"🗑️ Gasto eliminado: {concept} ({amount:.0f})"

    except Exception as e:
        logger.exception("Failed to delete expense")
        return f"Error: {e}"
