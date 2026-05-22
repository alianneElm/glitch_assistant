import json
import logging
from datetime import datetime

from anthropic import Anthropic, BadRequestError

from backend.agent.prompts import get_system_prompt
from backend.agent.tools.calendar import create_event, get_todays_events, get_upcoming_events
from backend.agent.tools.calls import make_phone_call
from backend.agent.tools.reminders import create_reminder, delete_reminder, list_reminders, send_scheduled_message
from backend.config import settings
from backend.models.conversation import Message
from backend.services.database import get_session

logger = logging.getLogger(__name__)

client = Anthropic(api_key=settings.anthropic_api_key)

MAX_HISTORY = 20


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
        return _clean_history(messages)
    finally:
        session.close()


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
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
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
            "name": "send_scheduled_message",
            "description": f"Send a WhatsApp message to another contact at a scheduled time. Right now it is {now} ({tz}). The recipient must have joined the Twilio sandbox to receive the message.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "to_phone": {"type": "string", "description": "Recipient phone number with country code, e.g. '+46701234567'"},
                    "message": {"type": "string", "description": "The message text to send"},
                    "send_at": {"type": "string", "description": "When to send, ISO format (e.g. '2026-05-23T09:00:00')"},
                },
                "required": ["to_phone", "message", "send_at"],
            },
        },
        {
            "name": "make_phone_call",
            "description": f"Make an outbound phone call via AI voice agent. Use this when the user wants to call someone (a business, a friend, a contact) to coordinate, book appointments, deliver messages, etc. Right now it is {now} ({tz}). The AI agent will handle the conversation autonomously based on the objective.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "phone_number": {"type": "string", "description": "Phone number to call with country code, e.g. '+46701234567'"},
                    "objective": {"type": "string", "description": "What the call should accomplish, e.g. 'Book a dentist appointment for next Tuesday morning'"},
                    "context": {"type": "string", "description": "Additional context for the AI during the call, e.g. 'Available times: Tuesday and Thursday mornings. Prefer before 11:00.'", "default": ""},
                    "first_message": {"type": "string", "description": "Custom greeting when the person picks up. Leave empty for default.", "default": ""},
                    "language": {"type": "string", "description": "Language for the call: 'sv' (Swedish), 'es' (Spanish), 'en' (English). Default 'sv' since we're in Sweden.", "default": "sv"},
                },
                "required": ["phone_number", "objective"],
            },
        },
    ]


TOOL_FUNCTIONS = {
    "get_todays_events": lambda **kwargs: get_todays_events(),
    "get_upcoming_events": lambda **kwargs: get_upcoming_events(kwargs.get("days", 7)),
    "create_event": lambda **kwargs: create_event(**kwargs),
    "create_reminder": lambda **kwargs: create_reminder(**kwargs),
    "list_reminders": lambda **kwargs: list_reminders(),
    "delete_reminder": lambda **kwargs: delete_reminder(**kwargs),
    "send_scheduled_message": lambda **kwargs: send_scheduled_message(**kwargs),
    "make_phone_call": lambda **kwargs: make_phone_call(**kwargs),
}


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


def get_response(user_id: str, message: str) -> str:
    # Load history from database
    history = _load_history(user_id)

    history.append({"role": "user", "content": message})
    _save_message(user_id, "user", message)

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=500,
            system=get_system_prompt(),
            messages=history,
            tools=_build_tools(),
        )
    except BadRequestError as e:
        if "tool_result" in str(e) or "tool_use" in str(e):
            logger.warning("Corrupted history detected, clearing and retrying: %s", e)
            _clear_history(user_id)
            history = [{"role": "user", "content": message}]
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                system=get_system_prompt(),
                messages=history,
                tools=_build_tools(),
            )
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

                func = TOOL_FUNCTIONS.get(tool_name)
                if func:
                    try:
                        result = func(**tool_input)
                    except Exception as e:
                        logger.exception("Tool %s failed", tool_name)
                        result = f"Error: {e}"
                else:
                    result = f"Tool '{tool_name}' not found"

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
            max_tokens=500,
            system=get_system_prompt(),
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

    return assistant_text
