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

    # Handle function-call type
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

    # Handle other message types (status updates, etc.)
    if msg_type == "status-update":
        status = message.get("status", "")
        logger.info("Vapi call status: %s", status)

    if msg_type == "end-of-call-report":
        summary = message.get("summary", "")
        duration = message.get("duration", 0)
        transcript = message.get("transcript", "")
        logger.info("Vapi call ended. Duration: %ss. Summary: %s", duration, summary[:200])

        # Send call summary to user via WhatsApp
        if summary:
            try:
                _send_whatsapp(
                    settings.my_whatsapp_number,
                    f"📞 Resumen de llamada:\n{summary}",
                )
            except Exception:
                logger.exception("Failed to send call summary via WhatsApp")

        # Try to extract and create calendar event from call results
        if summary or transcript:
            try:
                _extract_and_create_event(summary, transcript)
            except Exception:
                logger.exception("Failed to extract event from call summary")

    return {"ok": True}


def _extract_and_create_event(summary: str, transcript: str) -> None:
    """Use Claude to extract event details from call summary and create calendar event."""
    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    tz = settings.user_timezone

    prompt = f"""Analyze this phone call summary and transcript. If an appointment, meeting, or event was agreed upon, extract the details.

Current date/time: {now} ({tz})

## Call Summary
{summary}

## Transcript (last part)
{transcript[-1000:] if transcript else "N/A"}

If an event was confirmed, respond with EXACTLY this JSON format (nothing else):
{{"event": true, "summary": "Event title", "start_time": "YYYY-MM-DDTHH:MM:SS", "duration_minutes": 60, "description": "Brief description"}}

If NO event was confirmed (call failed, person unavailable, etc.), respond with:
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
        # Try to find JSON in the response
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

        # Notify user
        _send_whatsapp(
            settings.my_whatsapp_number,
            f"📅 Evento creado automáticamente: {data['summary']} — {data['start_time']}",
        )
