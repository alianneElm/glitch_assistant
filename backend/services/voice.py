import logging
import tempfile
import os

from elevenlabs import ElevenLabs

from backend.config import settings

logger = logging.getLogger(__name__)

client = ElevenLabs(api_key=settings.elevenlabs_api_key)


def generate_voice(text: str) -> str | None:
    """Generate speech from text using ElevenLabs. Returns path to temp mp3 file.

    The caller is responsible for deleting the file after use (os.unlink).
    """
    try:
        audio_generator = client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model,
            text=text,
            output_format="mp3_44100_128",
        )

        # Write audio to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        for chunk in audio_generator:
            tmp.write(chunk)
        tmp.close()

        file_size = os.path.getsize(tmp.name)
        logger.info("Generated voice audio: %d bytes → %s", file_size, tmp.name)
        return tmp.name

    except Exception:
        logger.exception("Failed to generate voice audio")
        return None
