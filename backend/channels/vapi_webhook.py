"""Vapi webhook handler for function calling during phone calls.

When the Vapi voice agent needs to perform an action (check calendar,
send WhatsApp, create reminder), it calls this endpoint. We execute
the action and return the result so the agent can continue the conversation.
"""

import json
import logging

from anthropic import Anthropic
from fastapi import APIRouter, Request

from backend.agent.tools.calendar import create_event, get_todays_events, get_upcoming_events
from backend.agent.tools.reminders import create_reminder, list_reminders, send_scheduled_message
from backend.config import settings

_anthropic = Anthropic(api_key=settings.anthropic_api_key)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])

# Map of function names to their handlers
VAPI_FUNCTIONS = {
    "get_todays_events": lambda params: get_todays_events(),
    "get_upcoming_events": lambda params: get_upcoming_events(params.get("days", 7)),
    "create_event": lambda params: create_event(**params),
    "create_reminder": lambda params: create_reminder(**params),
    "list_reminders": lambda params: list_reminders(),
    "send_whatsapp_message": lambda params: _send_whatsapp(
        params.get("to", settings.my_whatsapp_number),
        params.get("message", ""),
    ),
    "send_scheduled_message": lambda params: send_scheduled_message(**params),
}


def _send_whatsapp(to: str, message: str) -> str:
    """Send a WhatsApp message immediately."""
    from twilio.rest import Client

    if not message:
        return "Error: no message provided"

    # Normalize number
    to = to.strip()
    if not to.startswith("whatsapp:"):
        if not to.startswith("+"):
            to = "+" + to
        to = f"whatsapp:{to}"

    try:
        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=to,
            body=message,
        )
        return f"Mensaje enviado por WhatsApp a {to.replace('whatsapp:', '')}"
    except Exception as e:
        logger.exception("Failed to send WhatsApp from Vapi action")
        return f"Error al enviar WhatsApp: {e}"


@router.post("/action")
async def vapi_action(request: Request):
    """Handle function call requests from Vapi during phone calls.

    Vapi sends a POST with the function name and parameters.
    We execute it and return the result.
    """
    body = await request.json()

    logger.info("Vapi webhook received: %s", json.dumps(body, ensure_ascii=False)[:500])

    message = body.get("message", {})
    msg_type = message.get("type", "")

    # Handle function-call type (legacy format)
    if msg_type == "function-call":
        function_call = message.get("functionCall", {})
        func_name = function_call.get("name", "")
        func_params = function_call.get("parameters", {})

        logger.info("Vapi function call: %s(%s)", func_name, json.dumps(func_params, ensure_ascii=False))

        handler = VAPI_FUNCTIONS.get(func_name)
        if handler:
            try:
                result = handler(func_params)
            except Exception as e:
                logger.exception("Vapi function %s failed", func_name)
                result = f"Error: {e}"
        else:
            result = f"Función '{func_name}' no encontrada"

        logger.info("Vapi function result: %s", str(result)[:200])

        return {
            "results": [
                {
                    "toolCallId": function_call.get("id", ""),
                    "result": result,
                }
            ]
        }

    # Handle tool-calls type (new Vapi format with Anthropic models)
    if msg_type == "tool-calls":
        tool_calls = message.get("toolCallList", []) or message.get("toolCalls", [])
        results = []

        for tc in tool_calls:
            func_info = tc.get("function", {})
            func_name = func_info.get("name", "")
            func_params = func_info.get("arguments", {})
            tool_call_id = tc.get("id", "")

            # Skip empty argument calls (Haiku sometimes sends empty first)
            if not func_params and func_name:
                logger.warning("Skipping tool call %s with empty arguments", func_name)
                results.append({"toolCallId": tool_call_id, "result": "Error: no arguments provided"})
                continue

            logger.info("Vapi tool call: %s(%s)", func_name, json.dumps(func_params, ensure_ascii=False))

            handler = VAPI_FUNCTIONS.get(func_name)
            if handler:
                try:
                    result = handler(func_params)
                except Exception as e:
                    logger.exception("Vapi function %s failed", func_name)
                    result = f"Error: {e}"
            else:
                result = f"Función '{func_name}' no encontrada"

            logger.info("Vapi tool call result: %s", str(result)[:200])
            results.append({"toolCallId": tool_call_id, "result": result})

        return {"results": results}

    # Handle other message types (status updates, etc.)
    if msg_type == "status-update":
        status = message.get("status", "")
        logger.info("Vapi call status: %s", status)

    if msg_type == "end-of-call-report":
        summary = message.get("summary", "")
        duration = message.get("duration", 0)
        transcript = message.get("transcript", "")
        logger.info("Vapi call ended. Duration: %ss. Summary: %s", duration, summary[:200])

        # Get contact name from call metadata
        from backend.agent.tools.calls import active_calls
        call_id = message.get("call", {}).get("id", "") or body.get("call", {}).get("id", "")
        call_meta = active_calls.pop(call_id, {})
        contact_name = call_meta.get("contact_name", "")
        logger.info("Call metadata: call_id=%s, contact_name=%s", call_id, contact_name)

        # Try to extract and create calendar event from call results
        if summary or transcript:
            try:
                _extract_and_create_event(summary, transcript, contact_name)
            except Exception:
                logger.exception("Failed to extract event from call summary")

    return {"ok": True}


def _extract_and_create_event(summary: str, transcript: str, contact_name: str = "") -> None:
    """Extract event details from call summary and create calendar event.

    Checks existing events to avoid duplicates and conflicts.
    """
    from datetime import datetime, timedelta

    now = datetime.now()
    tz = settings.user_timezone

    # Build day-of-week reference
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_reference = []
    for d in range(7):
        date = now + timedelta(days=d)
        day_reference.append(f"  {day_names[date.weekday()]} = {date.strftime('%Y-%m-%d')}")
    day_ref_str = "\n".join(day_reference)

    contact_hint = f'The person called is named "{contact_name}". Use this EXACT name in the event title.' if contact_name else ""

    prompt = f"""A phone call just ended. Extract the agreed appointment and return it as JSON.

Current date/time: {now.strftime('%A %Y-%m-%d %H:%M')} ({tz})

## Day reference (USE THIS for correct dates!)
{day_ref_str}

## Call Summary
{summary}

## Transcript (last part)
{transcript[-1000:] if transcript else "N/A"}

RULES:
{contact_hint}
- Event title must be from Alianne's perspective: "Fika with Maria", NOT "Fika with Alianne".
- Use the day reference above to get the correct date. Sunday=söndag, Saturday=lördag.
- If the call summary says an appointment was agreed, ALWAYS create it. Do NOT skip.

Respond with ONLY JSON, nothing else:
{{"event": true, "summary": "Fika with [name]", "start_time": "YYYY-MM-DDTHH:MM:SS", "duration_minutes": 60, "description": "Brief note"}}

If the call FAILED or NO appointment was agreed:
{{"event": false}}"""

    response = _anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()
    logger.info("Event extraction result: %s", text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        import re
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            logger.warning("Could not parse event extraction response: %s", text)
            return

    if data.get("event"):
        result = create_event(
            summary=data["summary"],
            start_time=data["start_time"],
            duration_minutes=data.get("duration_minutes", 60),
            description=data.get("description", ""),
        )
        logger.info("Auto-created calendar event: %s", result)

        # Format a clean notification
        from datetime import datetime as _dt
        try:
            evt_dt = _dt.fromisoformat(data["start_time"])
            evt_time = evt_dt.strftime("%A %d/%m a las %H:%M")
        except Exception:
            evt_time = data["start_time"]

        _send_whatsapp(
            settings.my_whatsapp_number,
            f"📅 {data['summary']} — {evt_time}",
        )
        # Log to Notion
        try:
            from backend.services.notion import add_log_entry
            add_log_entry(
                summary=f"Llamada: {data['summary']}",
                log_type="Llamada",
                details=f"Evento creado: {data['summary']} a las {evt_time}",
            )
        except Exception:
            logger.warning("Failed to log call to Notion")
    else:
        # No event agreed — short notification
        _send_whatsapp(
            settings.my_whatsapp_number,
            f"📞 Llamada finalizada. No se agendó nada.",
        )
        try:
            from backend.services.notion import add_log_entry
            add_log_entry(
                summary=f"Llamada a {contact_name or 'desconocido'} — sin cita",
                log_type="Llamada",
                details=summary[:500] if summary else "Sin resumen",
            )
        except Exception:
            logger.warning("Failed to log call to Notion")
