import json
import logging
from datetime import datetime

from anthropic import Anthropic

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

    When we load only the last N messages, we may cut off a tool_use assistant
    message while keeping its tool_result follow-up, or end with a tool_use that
    has no tool_result after it.  The Anthropic API rejects both cases.
    """
    if not messages:
        return []

    # 1. Skip leading messages that contain tool_result blocks (orphaned)
    start = 0
    for i, msg in enumerate(messages):
        content = msg.get("content")
        if isinstance(content, list) and any(
            isinstance(item, dict) and item.get("type") == "tool_result"
            for item in content
        ):
            start = i + 1
        else:
            break

    result = messages[start:]

    # 2. Trim trailing assistant messages that contain tool_use (no result follows)
    while result:
        last = result[-1]
        content = last.get("content")
        if isinstance(content, list) and any(
            (isinstance(item, dict) and item.get("type") == "tool_use")
            for item in content
        ):
            result.pop()
        else:
            break

    # 3. Ensure the conversation starts with a user message (API requirement)
    while result and result[0].get("role") != "user":
        result.pop(0)

    return result


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


def get_response(user_id: str, message: str) -> str:
    # Load history from database
    history = _load_history(user_id)

    history.append({"role": "user", "content": message})
    _save_message(user_id, "user", message)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        system=get_system_prompt(),
        messages=history,
        tools=_build_tools(),
    )

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
