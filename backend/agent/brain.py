import json
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from anthropic import Anthropic, BadRequestError

from backend.agent.prompts import get_system_prompt
from backend.agent.tools.calendar import create_event, delete_event, edit_event, get_todays_events, get_upcoming_events
from backend.agent.tools.calls import make_phone_call
from backend.agent.tools.contacts import delete_contact, get_contact, list_contacts, save_contact
from backend.agent.tools.email import (
    get_recent_emails_gmail,
    get_recent_emails_yahoo,
    read_email_gmail,
    read_email_yahoo,
    reply_email_gmail,
    send_email_gmail,
    send_email_yahoo,
)
from backend.agent.tools.reminders import create_reminder, delete_reminder, list_reminders, send_scheduled_message, send_sms, send_whatsapp
from backend.agent.tools.spotify import spotify_next, spotify_now_playing, spotify_pause, spotify_play, spotify_previous, spotify_queue, spotify_recommendations, spotify_search, spotify_set_volume, spotify_top
from backend.services.memory import (
    build_memory_context,
    clear_all_memories,
    detect_and_save_preference_background,
    forget_last_memory,
    get_memory_stats,
    get_user_profile,
    save_memory_background,
    search_memories_by_text,
)
from backend.agent.tools.web_search import extract_page, web_search
from backend.config import settings
from backend.models.conversation import Message
from backend.services.database import get_session
from backend.services.notion import add_expense, add_log_entry, add_note, add_shopping_item, add_shopping_items_batch, add_todo, clear_shopping_list, delete_expense, delete_food_entry, delete_note, edit_food_entry, get_daily_nutrition, get_expenses_list, get_expenses_summary, get_notes, get_recent_logs, get_shopping_list, get_todos, log_food, log_foods_batch, mark_shopping_item, search_notes, update_todo_status

logger = logging.getLogger(__name__)

client = Anthropic(api_key=settings.anthropic_api_key)

MAX_HISTORY = 50


def _load_history(user_id: str) -> list[dict]:
    """Load conversation history from the database."""
    session = get_session()
    try:
        rows = (
            session.query(Message)
            .filter(Message.user_id == user_id)
            .order_by(Message.id.desc())
            .limit(MAX_HISTORY)
            .all()
        )
        rows.reverse()  # oldest first
        messages = [{"role": r.role, "content": r.get_content()} for r in rows]
        cleaned = _clean_history(messages)
        return _compress_old_tool_results(cleaned)
    finally:
        session.close()


def _compress_old_tool_results(messages: list[dict], keep_recent: int = 10) -> list[dict]:
    """Truncate old tool_result content to save context space.

    The most recent `keep_recent` messages keep full tool results.
    Older tool_result blocks are truncated to 200 chars max so they
    still provide context without consuming excessive tokens.
    """
    if len(messages) <= keep_recent:
        return messages

    cutoff = len(messages) - keep_recent
    compressed = []

    for i, msg in enumerate(messages):
        if i < cutoff:
            content = msg.get("content")
            if isinstance(content, list):
                new_content = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        result_text = block.get("content", "")
                        if isinstance(result_text, str) and len(result_text) > 200:
                            block = {**block, "content": result_text[:200] + "… [truncated]"}
                    new_content.append(block)
                compressed.append({**msg, "content": new_content})
            else:
                compressed.append(msg)
        else:
            compressed.append(msg)

    return compressed


def _clean_history(messages: list[dict]) -> list[dict]:
    """Remove orphaned tool_result / tool_use messages that would cause API errors.

    The Anthropic API requires that every tool_result block references a tool_use
    block in the immediately preceding assistant message.  When we load only the
    last N messages we can break that pairing.  This function walks the list and
    keeps only structurally valid message pairs.
    """
    if not messages:
        return []

    cleaned: list[dict] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        content = msg.get("content")

        # Check if this message contains tool_result blocks
        has_tool_result = (
            isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
        )

        # Check if this message contains tool_use blocks
        has_tool_use = (
            isinstance(content, list)
            and any(isinstance(b, dict) and b.get("type") == "tool_use" for b in content)
        )

        if has_tool_result:
            # This is a tool_result message — only keep it if the previous
            # message in `cleaned` is an assistant message with matching tool_use ids
            if cleaned:
                prev = cleaned[-1]
                prev_content = prev.get("content")
                prev_tool_ids = set()
                if isinstance(prev_content, list):
                    for b in prev_content:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            prev_tool_ids.add(b.get("id", ""))

                result_ids = {
                    b.get("tool_use_id", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "tool_result"
                }

                if prev.get("role") == "assistant" and result_ids <= prev_tool_ids:
                    # Valid pair — keep it
                    cleaned.append(msg)
                else:
                    # Orphaned tool_result — skip it
                    logger.warning("Skipping orphaned tool_result message (ids: %s)", result_ids)
            else:
                # No previous message at all — skip
                logger.warning("Skipping leading tool_result message")
        elif has_tool_use:
            # Assistant message with tool_use — only keep if next message
            # is a matching tool_result (peek ahead)
            next_i = i + 1
            if next_i < len(messages):
                next_msg = messages[next_i]
                next_content = next_msg.get("content")
                next_has_result = (
                    isinstance(next_content, list)
                    and any(isinstance(b, dict) and b.get("type") == "tool_result" for b in next_content)
                )
                if next_has_result:
                    # Valid pair — keep this tool_use message
                    cleaned.append(msg)
                else:
                    # tool_use without following tool_result — skip
                    logger.warning("Skipping tool_use message without following tool_result")
            else:
                # Last message is a tool_use with no result — skip
                logger.warning("Skipping trailing tool_use message")
        else:
            # Regular text message — always keep
            cleaned.append(msg)

        i += 1

    # Ensure the conversation starts with a user message (API requirement)
    while cleaned and cleaned[0].get("role") != "user":
        cleaned.pop(0)

    # Ensure alternating user/assistant roles
    # (remove consecutive same-role messages, keeping the latest)
    final: list[dict] = []
    for msg in cleaned:
        if final and final[-1].get("role") == msg.get("role"):
            # Same role twice — replace previous with current
            final[-1] = msg
        else:
            final.append(msg)

    return final


def _save_message(user_id: str, role: str, content) -> None:
    """Save a single message to the database."""
    session = get_session()
    try:
        msg = Message(user_id=user_id, role=role)
        # Content can be a string, list of dicts, or list of Anthropic content blocks
        if isinstance(content, str):
            msg.set_content(content)
        elif isinstance(content, list):
            # Convert Anthropic content blocks to serializable dicts
            serializable = []
            for item in content:
                if hasattr(item, "model_dump"):
                    serializable.append(item.model_dump())
                elif isinstance(item, dict):
                    serializable.append(item)
                else:
                    serializable.append(str(item))
            msg.set_content(serializable)
        else:
            msg.set_content(str(content))

        session.add(msg)
        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Failed to save message for user %s", user_id)
    finally:
        session.close()


def _build_tools() -> list[dict]:
    """Build tools with current date/time in descriptions."""
    now = datetime.now(ZoneInfo(settings.user_timezone)).strftime("%Y-%m-%d %H:%M")
    tz = settings.user_timezone
    return [
        {
            "name": "get_todays_events",
            "description": "Get today's calendar events. Use when the user asks about today's schedule, agenda, or events.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_upcoming_events",
            "description": "Get upcoming calendar events for the next N days.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Number of days to look ahead (default 7)", "default": 7},
                },
                "required": [],
            },
        },
        {
            "name": "create_event",
            "description": f"Create a new calendar event. Right now it is {now} ({tz}). Always use ISO format for start_time.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string", "description": "Event title"},
                    "start_time": {"type": "string", "description": "Start time in ISO format, e.g. '2026-05-22T14:00:00'"},
                    "duration_minutes": {"type": "integer", "description": "Duration in minutes (default 60)", "default": 60},
                    "description": {"type": "string", "description": "Optional event description", "default": ""},
                },
                "required": ["summary", "start_time"],
            },
        },
        {
            "name": "edit_event",
            "description": f"Edit an existing calendar event. Search by title (partial match). Right now it is {now} ({tz}). Only change the fields the user mentions — leave the rest empty.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to search for in event titles, e.g. 'dentista' or 'fika with Maria'"},
                    "new_summary": {"type": "string", "description": "New event title (empty = keep current)", "default": ""},
                    "new_start_time": {"type": "string", "description": "New start time ISO format (empty = keep current)", "default": ""},
                    "new_duration_minutes": {"type": "integer", "description": "New duration in minutes (0 = keep current)", "default": 0},
                    "new_description": {"type": "string", "description": "New description (empty = keep current)", "default": ""},
                },
                "required": ["search_text"],
            },
        },
        {
            "name": "delete_event",
            "description": "Delete a calendar event by searching for it by title. Use when the user wants to cancel or remove an event.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to search for in event titles, e.g. 'dentista' or 'fika'"},
                },
                "required": ["search_text"],
            },
        },
        {
            "name": "create_reminder",
            "description": f"Set a reminder sent via WhatsApp at specified time. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reminder_text": {"type": "string", "description": "What to remind about"},
                    "remind_at": {"type": "string", "description": "When to send the reminder, ISO format (e.g. '2026-05-22T15:00:00')"},
                },
                "required": ["reminder_text", "remind_at"],
            },
        },
        {
            "name": "list_reminders",
            "description": "List all pending reminders.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "delete_reminder",
            "description": "Delete a reminder by matching its text.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "reminder_text": {"type": "string", "description": "Text to match against existing reminders"},
                },
                "required": ["reminder_text"],
            },
        },
        {
            "name": "send_sms",
            "description": f"Send an SMS text message to a contact. PREFERRED method for sending messages to OTHER people (not the user). Use this when the user says 'mándale un mensaje a María', 'dile a Juan que...', or any request to message another person. WhatsApp only works for sending messages back to the user themselves.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string", "description": "Name of the recipient (looked up from saved contacts)", "default": ""},
                    "to_phone": {"type": "string", "description": "Phone number with country code. Can be empty if contact_name is provided.", "default": ""},
                    "message": {"type": "string", "description": "The message text to send"},
                },
                "required": ["message"],
            },
        },
        {
            "name": "send_whatsapp",
            "description": f"Send a WhatsApp message. ONLY use this to send messages/reminders back to the USER (Alianne), NOT to other contacts. For sending messages to other people, always use send_sms instead.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string", "description": "Name of the recipient (looked up from saved contacts)", "default": ""},
                    "to_phone": {"type": "string", "description": "Phone number with country code. Can be empty if contact_name is provided.", "default": ""},
                    "message": {"type": "string", "description": "The message text to send"},
                },
                "required": ["message"],
            },
        },
        {
            "name": "send_scheduled_message",
            "description": f"Schedule a WhatsApp message to a contact for a future time. Right now it is {now} ({tz}). If the user says a contact name, pass contact_name and the phone will be looked up. Recipient must have joined the Twilio sandbox.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "contact_name": {"type": "string", "description": "Name of the recipient (looked up from saved contacts)", "default": ""},
                    "to_phone": {"type": "string", "description": "Phone number with country code. Can be empty if contact_name is provided.", "default": ""},
                    "message": {"type": "string", "description": "The message text to send"},
                    "send_at": {"type": "string", "description": "When to send, ISO format (e.g. '2026-05-23T09:00:00')"},
                },
                "required": ["message", "send_at"],
            },
        },
        {
            "name": "make_phone_call",
            "description": f"Make an outbound phone call via AI voice agent. Use this when the user wants to call someone. Right now it is {now} ({tz}). If the user says a contact name without a phone number (e.g. 'llama a María'), just pass the contact_name — the phone number and language will be filled from saved contacts automatically.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "description": "Phone number with country code, e.g. '+46701234567'. Can be empty if contact_name matches a saved contact.", "default": ""},
                    "objective": {"type": "string", "description": "What the call should accomplish, e.g. 'Book a dentist appointment for next Tuesday morning'"},
                    "contact_name": {"type": "string", "description": "Name of the person being called, e.g. 'Erik'. Extract from the user's message.", "default": ""},
                    "context": {"type": "string", "description": "Additional context for the AI during the call, e.g. 'Available times: Tuesday and Thursday mornings. Prefer before 11:00.'", "default": ""},
                    "first_message": {"type": "string", "description": "Custom greeting when the person picks up. Leave empty for default.", "default": ""},
                    "language": {"type": "string", "description": "Language for the call: 'sv' (Swedish), 'es' (Spanish), 'en' (English). Default 'sv' since we're in Sweden.", "default": "sv"},
                },
                "required": ["objective"],
            },
        },
        {
            "name": "save_contact",
            "description": "Save a new contact or update an existing one. Use when the user wants to add someone to their contacts.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Contact name, e.g. 'María'"},
                    "phone": {"type": "string", "description": "Phone number with country code, e.g. '+46701234567'"},
                    "language": {"type": "string", "description": "Preferred language: 'sv' (Swedish), 'es' (Spanish), 'en' (English). Default 'sv'.", "default": "sv"},
                    "relationship": {"type": "string", "description": "Relationship type, e.g. 'amiga', 'familia', 'dentista', 'trabajo'", "default": ""},
                    "notes": {"type": "string", "description": "Optional notes about the contact", "default": ""},
                },
                "required": ["name", "phone"],
            },
        },
        {
            "name": "list_contacts",
            "description": "List all saved contacts. Use when the user asks to see their contacts.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "delete_contact",
            "description": "Delete a contact by name.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the contact to delete (partial match)"},
                },
                "required": ["name"],
            },
        },
        {
            "name": "add_todo",
            "description": "Add a task to the to-do list in Notion. Use when the user wants to add a task, pending item, or something they need to do.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "description": "Task description"},
                    "priority": {"type": "string", "description": "Priority: 'Alta', 'Media', 'Baja'", "default": "Media"},
                    "deadline": {"type": "string", "description": "Deadline in ISO format, e.g. '2026-05-25'. Empty if no deadline.", "default": ""},
                    "notes": {"type": "string", "description": "Optional notes", "default": ""},
                },
                "required": ["task"],
            },
        },
        {
            "name": "update_todo_status",
            "description": "Mark a task as completed or change its status in Notion.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_name": {"type": "string", "description": "Name of the task to update (partial match)"},
                    "status": {"type": "string", "description": "'Completado', 'En progreso', or 'Pendiente'", "default": "Completado"},
                },
                "required": ["task_name"],
            },
        },
        {
            "name": "add_shopping_item",
            "description": "Add a SINGLE item to the shopping list. For multiple items, use add_shopping_items_batch instead — it's much faster.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "item": {"type": "string", "description": "Item name, e.g. 'Leche'"},
                    "quantity": {"type": "integer", "description": "Quantity (default 1)", "default": 1},
                    "category": {"type": "string", "description": "'Comida', 'Hogar', 'Higiene', 'Otro'", "default": "Otro"},
                },
                "required": ["item"],
            },
        },
        {
            "name": "add_shopping_items_batch",
            "description": "Add MULTIPLE items to the shopping list in ONE call. ALWAYS use this instead of add_shopping_item when adding 2 or more items. Much faster — adds all items at once.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "description": "List of items to add",
                        "items": {
                            "type": "object",
                            "properties": {
                                "item": {"type": "string", "description": "Item name"},
                                "quantity": {"type": "integer", "description": "Quantity (default 1)", "default": 1},
                                "category": {"type": "string", "description": "'Comida', 'Hogar', 'Higiene', 'Otro'", "default": "Comida"},
                            },
                            "required": ["item"],
                        },
                    },
                },
                "required": ["items"],
            },
        },
        {
            "name": "mark_shopping_item",
            "description": "Mark a specific item as purchased/bought in the shopping list. Use when the user says 'ya compré X', 'ya tengo X', or marks a specific item as done.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "item_name": {"type": "string", "description": "Name of the item to mark as purchased (partial match)"},
                },
                "required": ["item_name"],
            },
        },
        {
            "name": "clear_shopping_list",
            "description": "Clear/empty the entire shopping list in Notion. Use when the user says they finished shopping, did the groceries, or wants to reset the list for next week.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_todos",
            "description": "Get tasks from the Notion to-do list. Use when the user asks about their tasks, pending items, what they need to do, or their to-do list. Can filter by status.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "status_filter": {"type": "string", "description": "Filter by status: 'Pendiente', 'En progreso', 'Completado', or empty for all tasks", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "get_shopping_list",
            "description": "Get the current shopping list from Notion. Use when the user asks what they need to buy, their shopping list, or grocery items.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "get_recent_logs",
            "description": "Get recent Glitch interaction logs from Notion (calls, events created, reminders, etc). Use when the user asks about recent activity, what Glitch has done, or call history.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of recent entries to show (default 10)", "default": 10},
                },
                "required": [],
            },
        },
        {
            "name": "log_food",
            "description": f"Log a SINGLE food item to the nutrition diary. For multiple items (e.g. 'paella con 2 cervezas'), ALWAYS use log_foods_batch instead so each item is a separate entry that can be edited/deleted individually. Only use this for truly single items. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "ONE single food item, e.g. '100g gambas a la plancha'"},
                    "calories": {"type": "integer", "description": "YOUR estimate of calories (kcal)"},
                    "protein": {"type": "number", "description": "YOUR estimate of protein in grams"},
                    "carbs": {"type": "number", "description": "YOUR estimate of carbs in grams"},
                    "fat": {"type": "number", "description": "YOUR estimate of fat in grams"},
                    "meal_type": {"type": "string", "description": "'Desayuno', 'Almuerzo', 'Cena', or 'Snack'.", "default": "Almuerzo"},
                    "notes": {"type": "string", "description": "Optional notes", "default": ""},
                },
                "required": ["description", "calories", "protein", "carbs", "fat"],
            },
        },
        {
            "name": "log_foods_batch",
            "description": f"Log MULTIPLE food items as SEPARATE entries in ONE call. ALWAYS use this when the user mentions 2+ foods (e.g. 'paella con 2 cervezas' → 2 separate entries). This way each item can be edited or deleted individually. YOU estimate the macros for each item. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "description": "Each food as a separate entry with its own macros",
                        "items": {
                            "type": "object",
                            "properties": {
                                "description": {"type": "string", "description": "ONE food item, e.g. 'Ración de paella'"},
                                "calories": {"type": "integer", "description": "Estimated kcal"},
                                "protein": {"type": "number", "description": "Estimated protein (g)"},
                                "carbs": {"type": "number", "description": "Estimated carbs (g)"},
                                "fat": {"type": "number", "description": "Estimated fat (g)"},
                                "meal_type": {"type": "string", "description": "'Desayuno', 'Almuerzo', 'Cena', 'Snack'", "default": "Almuerzo"},
                            },
                            "required": ["description", "calories", "protein", "carbs", "fat"],
                        },
                    },
                },
                "required": ["entries"],
            },
        },
        {
            "name": "edit_food_entry",
            "description": f"Edit a food entry in today's nutrition diary. Search by food name (partial match). Only change the fields the user mentions. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to search for in food entries, e.g. 'gambas' or 'café'"},
                    "new_description": {"type": "string", "description": "New food description (empty = keep current)", "default": ""},
                    "new_calories": {"type": "integer", "description": "New calories (0 = keep current)", "default": 0},
                    "new_protein": {"type": "number", "description": "New protein grams (0 = keep current)", "default": 0},
                    "new_carbs": {"type": "number", "description": "New carbs grams (0 = keep current)", "default": 0},
                    "new_fat": {"type": "number", "description": "New fat grams (0 = keep current)", "default": 0},
                    "new_meal_type": {"type": "string", "description": "New meal type: 'Desayuno', 'Almuerzo', 'Cena', 'Snack' (empty = keep current)", "default": ""},
                },
                "required": ["search_text"],
            },
        },
        {
            "name": "delete_food_entry",
            "description": "Delete a food entry from today's nutrition diary. Use when the user says they didn't actually eat something, wants to remove an entry, or logged something by mistake.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to search for in food entries, e.g. 'gambas' or 'café'"},
                },
                "required": ["search_text"],
            },
        },
        {
            "name": "get_daily_nutrition",
            "description": f"Get the food diary for today or a specific date, with calorie and macro totals. Use when the user asks '¿qué he comido hoy?', 'mis calorías', 'macros del día', 'diario nutricional', etc. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "date_str": {"type": "string", "description": "Date in YYYY-MM-DD format. Empty = today.", "default": ""},
                },
                "required": [],
            },
        },
        # ─── Email tools ───
        {
            "name": "get_recent_emails_gmail",
            "description": "Get recent emails from Gmail inbox. Use when the user asks about their Gmail, recent emails, inbox, or mail. Can also search with Gmail query syntax.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of emails to fetch (default 10, max 20)", "default": 10},
                    "query": {"type": "string", "description": "Gmail search query: 'is:unread', 'from:amazon', 'subject:factura', 'after:2026/05/20'. Empty = recent inbox.", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "read_email_gmail",
            "description": "Read the full content of a specific Gmail email. Use after get_recent_emails_gmail to read a specific message. Marks it as read.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "The email ID from get_recent_emails_gmail"},
                },
                "required": ["email_id"],
            },
        },
        {
            "name": "send_email_gmail",
            "description": "Send an email from the user's Gmail account. Use when the user says 'manda un email', 'escribe un correo', etc. Write professional but friendly emails.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                },
                "required": ["to", "subject", "body"],
            },
        },
        {
            "name": "reply_email_gmail",
            "description": "Reply to a specific Gmail email. Maintains the thread. Use when user says 'responde a ese email', 'contéstale'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "The email ID to reply to"},
                    "body": {"type": "string", "description": "Reply body text"},
                },
                "required": ["email_id", "body"],
            },
        },
        {
            "name": "get_recent_emails_yahoo",
            "description": "Get recent emails from Yahoo inbox. Use when the user asks about their Yahoo mail specifically.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Number of emails to fetch (default 10, max 20)", "default": 10},
                },
                "required": [],
            },
        },
        {
            "name": "read_email_yahoo",
            "description": "Read the full content of a specific Yahoo email.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "email_id": {"type": "string", "description": "The email ID from get_recent_emails_yahoo"},
                },
                "required": ["email_id"],
            },
        },
        {
            "name": "send_email_yahoo",
            "description": "Send an email from the user's Yahoo account.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to": {"type": "string", "description": "Recipient email address"},
                    "subject": {"type": "string", "description": "Email subject"},
                    "body": {"type": "string", "description": "Email body text"},
                },
                "required": ["to", "subject", "body"],
            },
        },
        {
            "name": "web_search",
            "description": "Search the internet for current information. Use when the user asks about anything you don't know, need to verify, or that requires up-to-date info: prices, news, businesses, products, how-to, reviews, events, recipes, etc. Use topic='news' for recent news. Use days parameter to limit to recent results.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query in the most effective language for results (usually English for global topics, Spanish or Swedish for local)"},
                    "search_depth": {"type": "string", "description": "'basic' (fast) or 'advanced' (thorough, better quality)", "default": "advanced"},
                    "topic": {"type": "string", "description": "'general' for most searches, 'news' for recent news", "default": "general"},
                    "max_results": {"type": "integer", "description": "Number of results (1-10, default 5)", "default": 5},
                    "days": {"type": "integer", "description": "Only results from last N days. Use for time-sensitive queries."},
                },
                "required": ["query"],
            },
        },
        {
            "name": "extract_page",
            "description": "Read and extract the full content of a specific web page/URL. Use AFTER web_search to get detailed info from a specific result, or when the user shares a URL and asks about its content.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to read (e.g. 'https://example.com/article')"},
                },
                "required": ["url"],
            },
        },
        # ─── Memory tools ───
        {
            "name": "search_memories",
            "description": "Search in past conversations and memories. Use when user asks 'que recuerdas de X', 'cuando hablamos de X', 'que dijimos sobre X', 'do you remember'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to search for in memories"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "get_my_preferences",
            "description": "Get a summary of user preferences, decisions, and personal facts Glitch has learned. Use when user asks 'que sabes de mi', 'mis preferencias', 'what do you know about me'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "forget_last",
            "description": "Forget/delete the most recent memory. Use when user says 'olvida eso', 'borra eso', 'forget that'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "clear_all_memories_tool",
            "description": "Delete ALL memories. Only use when user EXPLICITLY says 'borra todo lo que sabes de mi', 'reset memoria', 'clear all memories'. Ask for confirmation first.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "memory_stats",
            "description": "Get memory statistics. Use when user asks 'cuantos recuerdos tienes', 'estadisticas de memoria', 'memory stats'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        # ─── Notes tools ───
        {
            "name": "add_note",
            "description": "Save a quick note to Notion. Use when the user says 'anota', 'nota:', 'guarda esto', 'apunta que', 'recuerda que', or wants to save any piece of information for later.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "note_text": {"type": "string", "description": "The note content (short summary)"},
                    "category": {"type": "string", "description": "'General', 'Idea', 'Codigo', 'Personal', 'Trabajo', 'Salud'. Infer from context.", "default": "General"},
                    "details": {"type": "string", "description": "Optional longer details or context for the note", "default": ""},
                },
                "required": ["note_text"],
            },
        },
        {
            "name": "get_notes",
            "description": "Get recent notes from Notion. Use when the user asks 'mis notas', 'que tengo anotado', 'notas de trabajo', etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Filter by category: 'General', 'Idea', 'Codigo', 'Personal', 'Trabajo', 'Salud'. Empty = all.", "default": ""},
                    "limit": {"type": "integer", "description": "Number of notes to show (default 10)", "default": 10},
                },
                "required": [],
            },
        },
        {
            "name": "search_notes",
            "description": "Search notes by text. Use when the user says 'busca en mis notas', 'tengo una nota sobre X', 'cual era el codigo de X'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Text to search for in notes"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "delete_note",
            "description": "Delete/archive a note. Use when the user says 'borra la nota de X', 'elimina la nota X'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to find the note to delete (partial match)"},
                },
                "required": ["search_text"],
            },
        },
        # ─── Expense tools ───
        {
            "name": "add_expense",
            "description": f"Register an expense/purchase. Use when the user says 'gasté', 'pagué', 'compré', 'me costó', or mentions any spending. Infer the category from context. Default currency SEK. Right now it is {now} ({tz}).",
            "input_schema": {
                "type": "object",
                "properties": {
                    "concept": {"type": "string", "description": "What was bought, e.g. 'Almuerzo en Max', 'Gasolina', 'Netflix'"},
                    "amount": {"type": "number", "description": "How much it cost (number only, no currency symbol)"},
                    "category": {"type": "string", "description": "'Comida', 'Transporte', 'Hogar', 'Entretenimiento', 'Salud', 'Ropa', 'Servicios', 'Suscripciones', 'Educacion', 'Restaurante', 'Otro'. Infer from context.", "default": "Otro"},
                    "currency": {"type": "string", "description": "'SEK', 'EUR', 'USD'. Default SEK.", "default": "SEK"},
                    "payment_method": {"type": "string", "description": "'Tarjeta', 'Efectivo', 'Swish', 'Transferencia'. Default Tarjeta.", "default": "Tarjeta"},
                    "notes": {"type": "string", "description": "Optional notes", "default": ""},
                    "is_recurring": {"type": "boolean", "description": "True if recurring (subscription, rent, etc.)", "default": False},
                },
                "required": ["concept", "amount"],
            },
        },
        {
            "name": "get_expenses_summary",
            "description": "Get expense summary grouped by category. Use when user asks '¿cuánto gasté?', 'mis gastos del mes', 'resumen de gastos', 'how much did I spend'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "'today', 'week', 'month', 'year'. Default 'month'.", "default": "month"},
                },
                "required": [],
            },
        },
        {
            "name": "get_expenses_list",
            "description": "Get detailed list of recent expenses. Use when user wants to see individual expenses, not just totals.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "description": "'today', 'week', 'month'. Default 'week'.", "default": "week"},
                    "category": {"type": "string", "description": "Filter by category (empty = all)", "default": ""},
                    "limit": {"type": "integer", "description": "Max entries to show (default 20)", "default": 20},
                },
                "required": [],
            },
        },
        {
            "name": "delete_expense",
            "description": "Delete an expense by searching its concept. Use when user says 'borra el gasto de X', 'elimina el gasto'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "search_text": {"type": "string", "description": "Text to find the expense to delete (partial match)"},
                },
                "required": ["search_text"],
            },
        },
        # ─── Spotify tools ───
        {
            "name": "spotify_play",
            "description": "Play a song on Spotify or resume playback. Use when the user says 'pon', 'reproduce', 'play', 'ponme musica', or names a song/artist to play. If no query, resumes paused playback.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Song name, artist, or search query to play. Empty to resume.", "default": ""},
                    "uri": {"type": "string", "description": "Direct Spotify URI (optional, takes priority over query)", "default": ""},
                },
                "required": [],
            },
        },
        {
            "name": "spotify_pause",
            "description": "Pause Spotify playback. Use when the user says 'pausa', 'para la musica', 'stop', 'pause'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "spotify_next",
            "description": "Skip to the next song on Spotify. Use when the user says 'siguiente', 'skip', 'next', 'cambia de cancion'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "spotify_previous",
            "description": "Go to the previous song on Spotify. Use when the user says 'anterior', 'previous', 'vuelve a la cancion anterior'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "spotify_now_playing",
            "description": "Get what's currently playing on Spotify. Use when the user asks 'que suena', 'que cancion es esta', 'que estoy escuchando', 'what's playing'.",
            "input_schema": {"type": "object", "properties": {}, "required": []},
        },
        {
            "name": "spotify_search",
            "description": "Search Spotify for tracks, artists, albums, or playlists. Use when the user wants to find music without immediately playing it.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "search_type": {"type": "string", "description": "'track', 'artist', 'album', or 'playlist'", "default": "track"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "spotify_set_volume",
            "description": "Set the Spotify volume. Use when the user says 'sube el volumen', 'baja el volumen', 'volumen al 50', etc.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "volume": {"type": "integer", "description": "Volume level from 0 to 100"},
                },
                "required": ["volume"],
            },
        },
        {
            "name": "spotify_queue",
            "description": "Add a song to the Spotify queue. Use when the user says 'agrega X a la cola', 'pon X despues', 'queue X'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Song name to search and add to queue"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "spotify_top",
            "description": "Get user's top tracks or artists from Spotify. Use when the user asks 'mi top canciones', 'que artistas escucho mas', 'mis mas escuchadas', 'top artists'.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "top_type": {"type": "string", "description": "'tracks' for top songs, 'artists' for top artists", "default": "tracks"},
                    "time_range": {"type": "string", "description": "'short_term' (last 4 weeks), 'medium_term' (last 6 months), 'long_term' (all time)", "default": "medium_term"},
                },
                "required": [],
            },
        },
        {
            "name": "spotify_recommendations",
            "description": "Get personalized music recommendations. Use when the user says 'recomiendame musica', 'ponme algo para entrenar', 'musica para relajarme', 'algo para estudiar', or asks for music by mood/activity.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "mood": {"type": "string", "description": "Mood or activity: 'relajado', 'fiesta', 'entrenar', 'gym', 'estudiar', 'dormir', 'triste', 'feliz', 'romantico', 'correr'", "default": ""},
                    "genre": {"type": "string", "description": "Music genre: 'reggaeton', 'rock', 'jazz', 'pop', 'classical', 'hip-hop', 'electronic'", "default": ""},
                    "based_on": {"type": "string", "description": "'recent' (based on recent listens) or 'top' (based on all-time favorites)", "default": "recent"},
                },
                "required": [],
            },
        },
    ]


def _resolve_contact(contact_name: str, to_phone: str) -> tuple[str, str]:
    """Resolve phone number from contact name or return as-is.

    Returns (phone, resolved_name) or raises ValueError if not found.
    """
    if to_phone:
        return to_phone, contact_name
    if contact_name:
        contact = get_contact(contact_name)
        if contact:
            return contact["phone"], contact["name"]
        raise ValueError(f"No encontré un contacto con el nombre '{contact_name}'. Guárdalo primero con save_contact.")
    raise ValueError("Necesito un nombre de contacto o número de teléfono.")


def _smart_phone_call(**kwargs) -> str:
    """Make a phone call, auto-filling contact details from saved contacts."""
    try:
        phone, name = _resolve_contact(kwargs.get("contact_name", ""), kwargs.get("phone_number", ""))
        kwargs["phone_number"] = phone
        kwargs["contact_name"] = name
        # Also fill language from contact if not explicitly set
        if not kwargs.get("language") or kwargs.get("language") == "sv":
            contact = get_contact(name)
            if contact:
                kwargs["language"] = contact["language"]
    except ValueError as e:
        return str(e)
    return make_phone_call(**kwargs)


def _smart_send_sms(**kwargs) -> str:
    """Send SMS, resolving contact name to phone number."""
    try:
        phone, _ = _resolve_contact(kwargs.get("contact_name", ""), kwargs.get("to_phone", ""))
    except ValueError as e:
        return str(e)
    return send_sms(to_phone=phone, message=kwargs["message"])


def _smart_send_whatsapp(**kwargs) -> str:
    """Send WhatsApp, resolving contact name to phone number.

    Auto-fallback: if recipient is NOT the user, send SMS instead
    (WhatsApp only works for the user who has the sandbox/24h window).
    """
    try:
        phone, _ = _resolve_contact(kwargs.get("contact_name", ""), kwargs.get("to_phone", ""))
    except ValueError as e:
        return str(e)

    # If recipient is NOT the user, use SMS instead (WhatsApp won't deliver)
    user_phone = settings.user_whatsapp.replace("+", "")
    clean_phone = phone.replace("+", "").replace("whatsapp:", "")
    if clean_phone != user_phone:
        logger.info("Recipient %s is not the user — switching to SMS", phone)
        return send_sms(to_phone=phone, message=kwargs["message"])

    return send_whatsapp(to_phone=phone, message=kwargs["message"])


def _smart_send_scheduled(**kwargs) -> str:
    """Schedule WhatsApp message, resolving contact name to phone number."""
    try:
        phone, _ = _resolve_contact(kwargs.get("contact_name", ""), kwargs.get("to_phone", ""))
    except ValueError as e:
        return str(e)
    return send_scheduled_message(to_phone=phone, message=kwargs["message"], send_at=kwargs["send_at"])


TOOL_FUNCTIONS = {
    "get_todays_events": lambda **kwargs: get_todays_events(),
    "get_upcoming_events": lambda **kwargs: get_upcoming_events(kwargs.get("days", 7)),
    "create_event": lambda **kwargs: create_event(**kwargs),
    "edit_event": lambda **kwargs: edit_event(**kwargs),
    "delete_event": lambda **kwargs: delete_event(**kwargs),
    "create_reminder": lambda **kwargs: create_reminder(**kwargs),
    "list_reminders": lambda **kwargs: list_reminders(),
    "delete_reminder": lambda **kwargs: delete_reminder(**kwargs),
    "send_sms": lambda **kwargs: _smart_send_sms(**kwargs),
    "send_whatsapp": lambda **kwargs: _smart_send_whatsapp(**kwargs),
    "send_scheduled_message": lambda **kwargs: _smart_send_scheduled(**kwargs),
    "make_phone_call": lambda **kwargs: _smart_phone_call(**kwargs),
    "save_contact": lambda **kwargs: save_contact(**kwargs),
    "list_contacts": lambda **kwargs: list_contacts(),
    "delete_contact": lambda **kwargs: delete_contact(**kwargs),
    "add_todo": lambda **kwargs: add_todo(**kwargs),
    "update_todo_status": lambda **kwargs: update_todo_status(**kwargs),
    "add_shopping_item": lambda **kwargs: add_shopping_item(**kwargs),
    "add_shopping_items_batch": lambda **kwargs: add_shopping_items_batch(**kwargs),
    "mark_shopping_item": lambda **kwargs: mark_shopping_item(**kwargs),
    "clear_shopping_list": lambda **kwargs: clear_shopping_list(),
    "get_todos": lambda **kwargs: get_todos(kwargs.get("status_filter", "")),
    "get_shopping_list": lambda **kwargs: get_shopping_list(),
    "get_recent_logs": lambda **kwargs: get_recent_logs(kwargs.get("limit", 10)),
    "log_food": lambda **kwargs: log_food(**kwargs),
    "log_foods_batch": lambda **kwargs: log_foods_batch(**kwargs),
    "edit_food_entry": lambda **kwargs: edit_food_entry(**kwargs),
    "delete_food_entry": lambda **kwargs: delete_food_entry(**kwargs),
    "get_daily_nutrition": lambda **kwargs: get_daily_nutrition(kwargs.get("date_str", "")),
    "get_recent_emails_gmail": lambda **kwargs: get_recent_emails_gmail(**kwargs),
    "read_email_gmail": lambda **kwargs: read_email_gmail(**kwargs),
    "send_email_gmail": lambda **kwargs: send_email_gmail(**kwargs),
    "reply_email_gmail": lambda **kwargs: reply_email_gmail(**kwargs),
    "get_recent_emails_yahoo": lambda **kwargs: get_recent_emails_yahoo(**kwargs),
    "read_email_yahoo": lambda **kwargs: read_email_yahoo(**kwargs),
    "send_email_yahoo": lambda **kwargs: send_email_yahoo(**kwargs),
    "web_search": lambda **kwargs: web_search(**kwargs),
    "extract_page": lambda **kwargs: extract_page(**kwargs),
    # Memory
    "search_memories": lambda **kwargs: search_memories_by_text(kwargs.get("_user_id", ""), kwargs["query"]),
    "get_my_preferences": lambda **kwargs: get_user_profile(kwargs.get("_user_id", "")),
    "forget_last": lambda **kwargs: forget_last_memory(kwargs.get("_user_id", "")),
    "clear_all_memories_tool": lambda **kwargs: clear_all_memories(kwargs.get("_user_id", "")),
    "memory_stats": lambda **kwargs: get_memory_stats(kwargs.get("_user_id", "")),
    # Expenses
    "add_expense": lambda **kwargs: add_expense(**kwargs),
    "get_expenses_summary": lambda **kwargs: get_expenses_summary(kwargs.get("period", "month")),
    "get_expenses_list": lambda **kwargs: get_expenses_list(**kwargs),
    "delete_expense": lambda **kwargs: delete_expense(**kwargs),
    # Notes
    "add_note": lambda **kwargs: add_note(**kwargs),
    "get_notes": lambda **kwargs: get_notes(**kwargs),
    "search_notes": lambda **kwargs: search_notes(**kwargs),
    "delete_note": lambda **kwargs: delete_note(**kwargs),
    # Spotify
    "spotify_play": lambda **kwargs: spotify_play(**kwargs),
    "spotify_pause": lambda **kwargs: spotify_pause(),
    "spotify_next": lambda **kwargs: spotify_next(),
    "spotify_previous": lambda **kwargs: spotify_previous(),
    "spotify_now_playing": lambda **kwargs: spotify_now_playing(),
    "spotify_search": lambda **kwargs: spotify_search(**kwargs),
    "spotify_set_volume": lambda **kwargs: spotify_set_volume(**kwargs),
    "spotify_queue": lambda **kwargs: spotify_queue(**kwargs),
    "spotify_top": lambda **kwargs: spotify_top(**kwargs),
    "spotify_recommendations": lambda **kwargs: spotify_recommendations(**kwargs),
}


def _retry_with_trimmed_history(history: list[dict], current_message: str):
    """Progressively trim old messages until the API accepts the history.

    Instead of nuking everything (amnesia), we remove messages from the front
    2 at a time (to maintain user/assistant pairing), keeping recent context.
    """
    # Try trimming from the front, 2 messages at a time
    trimmed = list(history)
    for attempt in range(10):
        # Remove the 2 oldest messages (keep pairing intact)
        if len(trimmed) > 3:
            trimmed = trimmed[2:]
            # Ensure we still start with a user message
            while trimmed and trimmed[0].get("role") != "user":
                trimmed.pop(0)
        else:
            # Down to just the current message
            trimmed = [{"role": "user", "content": current_message}]

        # Re-clean the trimmed history
        trimmed = _clean_history(trimmed)

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                system=get_system_prompt(),
                messages=trimmed,
                tools=_build_tools(),
            )
            logger.info("History recovered after trimming %d messages (attempt %d)", len(history) - len(trimmed), attempt + 1)
            # Update history reference for caller
            history.clear()
            history.extend(trimmed)
            return response
        except BadRequestError:
            logger.warning("Trim attempt %d failed, removing more messages...", attempt + 1)
            continue

    # Last resort: just the current message
    logger.warning("All trim attempts failed, using only current message")
    history.clear()
    history.append({"role": "user", "content": current_message})
    return client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=get_system_prompt(),
        messages=[{"role": "user", "content": current_message}],
        tools=_build_tools(),
    )


def _clear_history(user_id: str) -> None:
    """Delete all stored messages for a user (used when history is corrupted)."""
    session = get_session()
    try:
        session.query(Message).filter(Message.user_id == user_id).delete()
        session.commit()
        logger.info("Cleared corrupted history for user %s", user_id)
    except Exception:
        session.rollback()
        logger.exception("Failed to clear history for user %s", user_id)
    finally:
        session.close()


def _build_system_prompt_with_memory(user_id: str, message: str) -> str:
    """Build system prompt enriched with relevant memories."""
    base_prompt = get_system_prompt()

    try:
        memory_context = build_memory_context(user_id, message)
        if memory_context:
            memory_section = (
                "\n\n## Lo que recuerdas de conversaciones anteriores\n"
                f"{memory_context}\n"
                "---\n"
                "Usa estos recuerdos de forma natural. No digas 'recuerdo que...' "
                "a menos que aporte valor. Solo usa el contexto para dar mejores respuestas."
            )
            return base_prompt + memory_section
    except Exception:
        logger.debug("Memory context retrieval failed (non-critical)")

    return base_prompt


def _execute_tool(tool_name: str, tool_input: dict, user_id: str) -> str:
    """Execute a tool, injecting user_id for memory tools."""
    func = TOOL_FUNCTIONS.get(tool_name)
    if not func:
        return f"Tool '{tool_name}' not found"

    # Inject user_id for memory tools that need it
    memory_tools = {"search_memories", "get_my_preferences", "forget_last", "clear_all_memories_tool", "memory_stats"}
    if tool_name in memory_tools:
        tool_input["_user_id"] = user_id

    try:
        return func(**tool_input)
    except Exception as e:
        logger.exception("Tool %s failed", tool_name)
        return f"Error: {e}"


def get_response(user_id: str, message: str) -> str:
    # Load history from database
    history = _load_history(user_id)

    history.append({"role": "user", "content": message})
    _save_message(user_id, "user", message)

    # Build system prompt with memory context
    system_prompt = _build_system_prompt_with_memory(user_id, message)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=history,
            tools=_build_tools(),
        )
    except BadRequestError as e:
        if "tool_result" in str(e) or "tool_use" in str(e):
            logger.warning("Corrupted history detected, trimming progressively: %s", e)
            response = _retry_with_trimmed_history(history, message)
        else:
            raise

    # Handle tool use loop
    while response.stop_reason == "tool_use":
        assistant_content = response.content
        history.append({"role": "assistant", "content": assistant_content})
        _save_message(user_id, "assistant", assistant_content)

        # Process each tool call
        tool_results = []
        for block in assistant_content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                logger.info("Tool call: %s(%s)", tool_name, json.dumps(tool_input, ensure_ascii=False))

                result = _execute_tool(tool_name, tool_input, user_id)

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": result,
                })

        history.append({"role": "user", "content": tool_results})
        _save_message(user_id, "user", tool_results)

        # Get next response
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=system_prompt,
            messages=history,
            tools=_build_tools(),
        )

    # Extract final text
    assistant_text = ""
    for block in response.content:
        if hasattr(block, "text"):
            assistant_text += block.text

    history.append({"role": "assistant", "content": response.content})
    _save_message(user_id, "assistant", response.content)

    # Save memory in background (non-blocking)
    if assistant_text and message:
        save_memory_background(user_id, message, assistant_text)
        # Detect preferences/facts in background
        detect_and_save_preference_background(user_id, message, assistant_text)

    return assistant_text
