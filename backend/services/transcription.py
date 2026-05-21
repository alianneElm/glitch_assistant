import logging
import tempfile

import httpx
from openai import OpenAI

from backend.config import settings

logger = logging.getLogger(__name__)

# Groq provides a Whisper-compatible API for free
client = OpenAI(
    api_key=settings.groq_api_key,
    base_url="https://api.groq.com/openai/v1",
)


async def transcribe_audio(media_url: str, twilio_sid: str, twilio_token: str) -> str:
    """Download audio from Twilio and transcribe with Whisper via Groq."""
    try:
        async with httpx.AsyncClient() as http:
            response = await http.get(
                media_url,
                auth=(twilio_sid, twilio_token),
                follow_redirects=True,
            )
            response.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=True) as tmp:
            tmp.write(response.content)
            tmp.flush()

            with open(tmp.name, "rb") as audio_file:
                transcription = client.audio.transcriptions.create(
                    model="whisper-large-v3",
                    file=audio_file,
                )

        text = transcription.text.strip()
        logger.info("Transcribed audio (%d bytes) → '%s'", len(response.content), text[:80])
        return text

    except Exception:
        logger.exception("Failed to transcribe audio from %s", media_url)
        return ""
