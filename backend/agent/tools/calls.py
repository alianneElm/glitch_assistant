"""Vapi-powered outbound phone calls for Glitch."""

import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"


def make_phone_call(
    phone_number: str,
    objective: str,
    contact_name: str = "",
    context: str = "",
    first_message: str = "",
    language: str = "sv",
) -> str:
    """Make an outbound phone call via Vapi.

    Args:
        phone_number: Number to call (e.g. '+46701234567')
        objective: What the call should accomplish (e.g. 'book a dentist appointment')
        contact_name: Name of the person being called (e.g. 'Erik')
        context: Extra context for the AI (e.g. 'available times: Tuesday 10-12')
        first_message: What the AI says when the person picks up
        language: Language for the call ('sv' for Swedish, 'es' for Spanish, 'en' for English)
    """
    if not settings.vapi_api_key:
        return "Error: VAPI_API_KEY no está configurada."

    # Normalize phone number
    phone_number = phone_number.strip()
    if not phone_number.startswith("+"):
        phone_number = "+" + phone_number

    # Build dynamic system prompt for this specific call
    from datetime import datetime, timedelta

    language_names = {"sv": "Swedish", "es": "Spanish", "en": "English"}
    lang_name = language_names.get(language, "Swedish")

    contact_info = f"You are calling {contact_name}." if contact_name else ""

    # Build day-of-week reference so the model gets dates right
    now = datetime.now()
    day_names_sv = ["måndag", "tisdag", "onsdag", "torsdag", "fredag", "lördag", "söndag"]
    day_names_en = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    day_reference = []
    for d in range(7):
        date = now + timedelta(days=d)
        day_reference.append(f"  {day_names_en[date.weekday()]} ({day_names_sv[date.weekday()]}) = {date.strftime('%Y-%m-%d')}")
    day_reference_str = "\n".join(day_reference)

    system_prompt = f"""You are Glitch, Alianne's personal AI assistant, making a phone call on her behalf.
{contact_info}

## Current date/time
Today is {now.strftime('%A %Y-%m-%d %H:%M')} ({settings.user_timezone})

## Day reference (USE THIS for correct dates!)
{day_reference_str}

## Your objective for this call
{objective}

## Additional context
{context}

## Rules
- Speak in {lang_name} primarily. Switch language if the other person prefers a different one.
- Be warm, friendly, and personable — like a cheerful friend calling on behalf of another friend.
- Don't ask "do you have a moment?" — your first message already covers the intro.
- Keep responses to 2-3 short sentences. Be conversational and natural, not robotic.
- React naturally to what they say — laugh, acknowledge, be human.
- If you accomplish the objective, confirm the details and end with something nice like "Alianne will be happy!"
- If the person is unavailable or can't help, be understanding and thank them warmly.

## IMPORTANT: After confirming an appointment or event
- Once a date/time is confirmed, IMMEDIATELY use the create_event tool to save it to Alianne's calendar.
- The event title should be from Alianne's perspective, e.g. "Fika with [person's name]", NOT "Fika with Alianne".
- Use the name of the person you're calling, not Alianne's name, in the event title.
- Also use send_whatsapp_message to notify Alianne with the confirmed details.
- Do this BEFORE ending the call so nothing is forgotten.
"""

    # Default first message if not provided
    if not first_message:
        # Build a natural greeting with the contact's name
        name_greeting = f" {contact_name}" if contact_name else ""
        objective_short = objective.split(".")[0]
        if language == "sv":
            first_message = f"Hej{name_greeting}! Jag är Glitch, Aliannes assistent. Jag ringer för att Alianne är upptagen just nu men hon vill {objective_short.lower()}."
        elif language == "es":
            first_message = f"¡Hola{name_greeting}! Soy Glitch, el asistente de Alianne. Te llamo porque Alianne está ocupada ahora mismo pero quiere {objective_short.lower()}."
        else:
            first_message = f"Hi{name_greeting}! I'm Glitch, Alianne's assistant. I'm calling because Alianne is busy right now but she'd like to {objective_short.lower()}."

    # Map language to Deepgram transcriber language codes
    transcriber_languages = {"sv": "sv", "es": "es", "en": "en"}
    transcriber_lang = transcriber_languages.get(language, "sv")

    # Create the call via Vapi API
    payload = {
        "assistantId": settings.vapi_assistant_id,
        "assistantOverrides": {
            "firstMessage": first_message,
            "transcriber": {
                "provider": "deepgram",
                "model": "nova-3",
                "language": transcriber_lang,
            },
            "model": {
                "provider": "anthropic",
                "model": "claude-haiku-4-5-20251001",
                "temperature": 0.7,
                "maxTokens": 150,
                "messages": [
                    {
                        "role": "system",
                        "content": system_prompt,
                    }
                ],
            },
            "silenceTimeoutSeconds": 20,
            "maxDurationSeconds": 300,
        },
        "phoneNumberId": settings.vapi_phone_number_id,
        "customer": {
            "number": phone_number,
        },
    }

    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{VAPI_BASE_URL}/call/phone",
                headers={
                    "Authorization": f"Bearer {settings.vapi_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )

            if response.status_code == 201:
                data = response.json()
                call_id = data.get("id", "unknown")
                logger.info("Call initiated: %s to %s (objective: %s)", call_id, phone_number, objective[:50])
                return f"✅ Llamada iniciada a {phone_number}. ID: {call_id}. Te avisaré cuando termine."
            else:
                error_msg = response.text
                logger.error("Vapi call failed (%d): %s", response.status_code, error_msg)
                return f"Error al iniciar la llamada: {error_msg}"

    except Exception as e:
        logger.exception("Failed to make Vapi call")
        return f"Error al conectar con Vapi: {e}"


def get_call_status(call_id: str) -> str:
    """Check the status of a Vapi call."""
    if not settings.vapi_api_key:
        return "Error: VAPI_API_KEY no está configurada."

    try:
        with httpx.Client(timeout=15) as client:
            response = client.get(
                f"{VAPI_BASE_URL}/call/{call_id}",
                headers={
                    "Authorization": f"Bearer {settings.vapi_api_key}",
                },
            )

            if response.status_code == 200:
                data = response.json()
                status = data.get("status", "unknown")
                duration = data.get("duration", 0)
                summary = data.get("summary", "")
                transcript = data.get("transcript", "")

                result = f"Estado: {status}"
                if duration:
                    result += f" | Duración: {duration}s"
                if summary:
                    result += f"\nResumen: {summary}"
                if transcript:
                    # Only include last part of transcript to keep it concise
                    result += f"\nTranscripción (últimas líneas): ...{transcript[-500:]}"
                return result
            else:
                return f"Error al consultar estado: {response.text}"

    except Exception as e:
        logger.exception("Failed to get call status")
        return f"Error: {e}"
