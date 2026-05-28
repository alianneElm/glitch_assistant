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

    # Handle inbound call — Vapi asks us what assistant to use
    if msg_type == "assistant-request":
        call_info = message.get("call", {}) or body.get("call", {})
        caller_number = call_info.get("customer", {}).get("number", "unknown")
        logger.info("Inbound call from %s — returning message-taking assistant", caller_number)

        # Store as inbound call in active_calls
        from backend.agent.tools.calls import active_calls
        call_id = call_info.get("id", "")
        if call_id:
            active_calls[call_id] = {
                "contact_name": "",
                "objective": "inbound_message",
                "phone_number": caller_number,
                "language": "es",
                "retries": 0,
                "inbound": True,
            }

        return {
            "assistant": {
                "firstMessage": "Hello there! I'm Glitch, Alianne's personal assistant. She's a bit busy at the moment, but do leave me a message and I'll make sure she gets it straightaway. May I ask who's calling?",
                "model": {
                    "provider": "anthropic",
                    "model": "claude-haiku-4-5-20251001",
                    "temperature": 0.7,
                    "maxTokens": 150,
                    "messages": [
                        {
                            "role": "system",
                            "content": _get_inbound_system_prompt(caller_number),
                        }
                    ],
                },
                "voice": {
                    "provider": "11labs",
                    "voiceId": "JBFqnCBsd6RMkjVDRZzb",
                    "model": "eleven_turbo_v2_5",
                },
                "transcriber": {
                    "provider": "deepgram",
                    "model": "nova-3",
                    "language": "en",
                },
                "silenceTimeoutSeconds": 30,
                "maxDurationSeconds": 300,
                "endCallPhrases": ["goodbye", "bye", "have a great day", "take care"],
            }
        }

    # Handle other message types (status updates, etc.)
    if msg_type == "status-update":
        status = message.get("status", "")
        logger.info("Vapi call status: %s", status)

    if msg_type == "end-of-call-report":
        summary = message.get("summary", "")
        duration = message.get("duration", 0)
        transcript = message.get("transcript", "")
        ended_reason = message.get("endedReason", "")
        logger.info("Vapi call ended. Duration: %ss. Reason: %s. Summary: %s", duration, ended_reason, summary[:200])

        # Get contact name from call metadata
        from backend.agent.tools.calls import active_calls
        call_id = message.get("call", {}).get("id", "") or body.get("call", {}).get("id", "")
        call_meta = active_calls.pop(call_id, {})
        contact_name = call_meta.get("contact_name", "")
        retries = call_meta.get("retries", 0)
        logger.info("Call metadata: call_id=%s, contact_name=%s, retries=%d", call_id, contact_name, retries)

        # Detect unanswered/failed calls
        no_answer_reasons = {
            "customer-did-not-answer",  # phone rang, no pickup
            "customer-busy",            # line busy
            "no-answer",
            "busy",
            "silence-timed-out",        # connected but nobody spoke
            "voicemail",                # went to voicemail
        }
        no_answer = ended_reason in no_answer_reasons or (not transcript and duration < 10)

        is_inbound = call_meta.get("inbound", False)

        # Inbound calls: forward message to Alianne
        if is_inbound:
            caller = call_meta.get("phone_number", "desconocido")
            if summary or transcript:
                try:
                    _send_inbound_message(summary, transcript, caller)
                except Exception:
                    logger.exception("Failed to forward inbound message")
                    _send_whatsapp(
                        settings.my_whatsapp_number,
                        f"📨 Alguien llamó desde {caller} pero no pude procesar el mensaje.",
                    )
            else:
                _send_whatsapp(
                    settings.my_whatsapp_number,
                    f"📨 Llamada recibida de {caller} — no dejó mensaje.",
                )
            return {"ok": True}

        # Outbound calls: handle retries and summaries
        if no_answer and retries < 1:
            # Schedule retry in 5 minutes
            _schedule_retry(call_meta)
            _send_whatsapp(
                settings.my_whatsapp_number,
                f"📞 {contact_name or 'La persona'} no contestó. Reintentaré en 5 minutos.",
            )
        elif no_answer:
            # Already retried once, give up
            _send_whatsapp(
                settings.my_whatsapp_number,
                f"📞 {contact_name or 'La persona'} no contestó después de 2 intentos. ¿Quieres que lo intente más tarde?",
            )
        else:
            # Call was answered — process results
            if summary or transcript:
                try:
                    _extract_and_create_event(summary, transcript, contact_name)
                except Exception:
                    logger.exception("Failed to extract event from call summary")

                try:
                    objective = call_meta.get("objective", "")
                    _send_call_summary(summary, transcript, contact_name, objective)
                except Exception:
                    logger.exception("Failed to send call summary")

    return {"ok": True}


def _get_inbound_system_prompt(caller_number: str) -> str:
    """Build system prompt for inbound call message-taking."""
    return f"""You are Glitch, Alianne's personal AI assistant. Someone is calling Alianne's number.

## Your role
Take a message for Alianne. She is busy right now.

## Caller info
Phone number: {caller_number}

## LANGUAGE RULE — CRITICAL
- Speak ONLY in British English for the entire call. Never switch languages.
- Use natural British expressions and phrasing: "lovely", "brilliant", "right then", "cheers", "no worries".
- Sound like a polite, well-spoken British assistant — warm but professional.
- If the caller speaks another language, politely say: "I'm terribly sorry, I only speak English. Shall we continue in English?"
- Stay in British English regardless of what language they use.

## Conversation flow
1. Greet and ask their name
2. Ask for their message
3. Confirm what you'll pass along
4. Say goodbye warmly

## Rules
- Keep responses to 1-2 SHORT sentences. Be conversational and warm.
- Once you have name + message, confirm: "Brilliant, I'll let Alianne know that [name] called and [message]. Is there anything else?"
- If they say no: "Lovely, I'll pass that along. Cheers, have a wonderful day!"
- NEVER share Alianne's personal info (ID number, address, email, schedule).
- If they ask where Alianne is: just say "she's busy at the moment".
- NEVER hang up abruptly. Always confirm and say goodbye before ending.
- Do NOT end the call until the caller confirms they have nothing else to say.
"""


def _send_inbound_message(summary: str, transcript: str, caller_number: str) -> None:
    """Extract and forward an inbound call message to Alianne via WhatsApp."""
    prompt = f"""An inbound call just ended. Someone called Alianne's assistant to leave a message.
Extract the key info and write a clean WhatsApp message in Spanish.

## Transcript
{transcript[-2000:] if transcript else "N/A"}

## Summary
{summary}

## Caller phone
{caller_number}

FORMAT (WhatsApp message to Alianne):
📨 Mensaje recibido de [name] ({caller_number}):

[The message/what they wanted]

[Urgency if mentioned]
[Callback request if mentioned]

Keep it concise. Max 300 characters."""

    response = _anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )

    msg = response.content[0].text.strip()
    logger.info("Inbound message forwarded: %s", msg[:200])

    _send_whatsapp(settings.my_whatsapp_number, msg)

    # Log to Notion
    try:
        from backend.services.notion import add_log_entry
        add_log_entry(
            summary=f"Llamada recibida de {caller_number}",
            log_type="Llamada",
            details=msg,
        )
    except Exception:
        logger.warning("Failed to log inbound call to Notion")


def _schedule_retry(call_meta: dict) -> None:
    """Schedule a call retry in 5 minutes using APScheduler."""
    from datetime import datetime, timedelta

    from backend.agent.tools.calls import make_phone_call
    from backend.services.scheduler import scheduler

    from zoneinfo import ZoneInfo
    retry_time = datetime.now(ZoneInfo(settings.user_timezone)) + timedelta(minutes=5)
    retry_id = f"call_retry_{call_meta.get('phone_number', 'unknown')}_{int(retry_time.timestamp())}"

    def _retry_call():
        logger.info("Retrying call to %s (contact: %s)", call_meta.get("phone_number"), call_meta.get("contact_name"))
        # Mark as retry so we don't retry again
        from backend.agent.tools.calls import active_calls
        result = make_phone_call(
            phone_number=call_meta.get("phone_number", ""),
            objective=call_meta.get("objective", ""),
            contact_name=call_meta.get("contact_name", ""),
            language=call_meta.get("language", "sv"),
        )
        # After make_phone_call, find the new call_id and mark retries
        for cid, meta in active_calls.items():
            if meta.get("phone_number") == call_meta.get("phone_number"):
                meta["retries"] = call_meta.get("retries", 0) + 1
                break
        logger.info("Retry call result: %s", result)

    from apscheduler.triggers.date import DateTrigger
    scheduler.add_job(
        _retry_call,
        trigger=DateTrigger(run_date=retry_time),
        id=retry_id,
        replace_existing=True,
    )
    logger.info("Call retry scheduled at %s (job_id=%s)", retry_time.strftime("%H:%M"), retry_id)


def _send_call_summary(summary: str, transcript: str, contact_name: str = "", objective: str = "") -> None:
    """Generate and send a detailed call summary to the user via WhatsApp."""
    contact_label = contact_name or "la persona"

    prompt = f"""A phone call just ended. Generate a concise but COMPLETE summary of the conversation in Spanish.

## Call objective
{objective or "No specific objective provided"}

## Call Summary (from AI)
{summary}

## Full Transcript
{transcript[-2000:] if transcript else "N/A"}

RULES:
- Write in Spanish
- Include ALL relevant information mentioned: names, prices, addresses, phone numbers, dates, recommendations
- If questions were asked, list each question with its answer
- If there was an appointment/agreement, include all details
- If the person couldn't help or wasn't available, say so
- Keep it concise but don't omit any useful information
- Format for WhatsApp (plain text, use emojis sparingly)
- Start with "📞 Resumen de llamada con {contact_label}:"
- Maximum 500 characters"""

    response = _anthropic.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )

    summary_text = response.content[0].text.strip()
    logger.info("Call summary generated: %s", summary_text[:200])

    _send_whatsapp(settings.my_whatsapp_number, summary_text)


def _extract_and_create_event(summary: str, transcript: str, contact_name: str = "") -> None:
    """Extract event details from call summary and create calendar event.

    Checks existing events to avoid duplicates and conflicts.
    """
    from datetime import datetime, timedelta

    from zoneinfo import ZoneInfo as _ZI
    now = datetime.now(_ZI(settings.user_timezone))
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
        # No event agreed — log to Notion (summary is sent separately by _send_call_summary)
        try:
            from backend.services.notion import add_log_entry
            add_log_entry(
                summary=f"Llamada a {contact_name or 'desconocido'} — sin cita",
                log_type="Llamada",
                details=summary[:500] if summary else "Sin resumen",
            )
        except Exception:
            logger.warning("Failed to log call to Notion")
