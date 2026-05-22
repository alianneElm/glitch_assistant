"""Vapi-powered outbound phone calls for Glitch."""

import logging

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

VAPI_BASE_URL = "https://api.vapi.ai"


def make_phone_call(
    phone_number: str,
    objective: str,
    context: str = "",
    first_message: str = "",
    language: str = "sv",
) -> str:
    """Make an outbound phone call via Vapi.

    Args:
        phone_number: Number to call (e.g. '+46701234567')
        objective: What the call should accomplish (e.g. 'book a dentist appointment')
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
    language_names = {"sv": "Swedish", "es": "Spanish", "en": "English"}
    lang_name = language_names.get(language, "Swedish")

    system_prompt = f"""You are Glitch, Alianne's personal AI assistant, making a phone call on her behalf.

## Your objective for this call
{objective}

## Additional context
{context}

## Rules
- Speak in {lang_name} primarily. Switch language if the other person prefers a different one.
- Be polite, friendly, and professional.
- Introduce yourself as Alianne's personal assistant.
- Stay focused on the objective. Don't go off-topic.
- If you accomplish the objective, confirm the details clearly before ending the call.
- If the person is unavailable or can't help, politely thank them and end the call.
- Keep responses short and natural — this is a phone conversation, not an essay.
- When you have all the information needed, summarize what was agreed and say goodbye.

## IMPORTANT: After confirming an appointment or event
- Once a date/time is confirmed, IMMEDIATELY use the create_event tool to save it to Alianne's calendar.
- Also use send_whatsapp_message to notify Alianne with the confirmed details.
- Do this BEFORE ending the call so nothing is forgotten.
"""

    # Default first message if not provided
    if not first_message:
        if language == "sv":
            first_message = "Hej! Jag är Glitch, Aliannes personliga assistent. Har du en stund?"
        elif language == "es":
            first_message = "¡Hola! Soy Glitch, el asistente personal de Alianne. ¿Tienes un momento?"
        else:
            first_message = "Hi! I'm Glitch, Alianne's personal assistant. Do you have a moment?"

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
