import logging
import subprocess
import tempfile
import os

from elevenlabs import ElevenLabs

from backend.config import settings

logger = logging.getLogger(__name__)

client = ElevenLabs(api_key=settings.elevenlabs_api_key)


def generate_voice_pcm(text: str, sample_rate: int = 16000) -> str | None:
    """Generate speech as PCM WAV (16-bit mono) for ESP32 playback.

    Uses ElevenLabs PCM output format directly.
    Returns path to temp WAV file, or None on failure.
    """
    try:
        import struct
        import io

        audio_generator = client.text_to_speech.convert(
            voice_id=settings.elevenlabs_voice_id,
            model_id=settings.elevenlabs_model,
            text=text,
            output_format="pcm_16000",  # Raw 16-bit PCM at 16kHz
        )

        # Collect raw PCM bytes
        pcm_data = b""
        for chunk in audio_generator:
            pcm_data += chunk

        if not pcm_data:
            logger.warning("ElevenLabs returned empty PCM audio")
            return None

        # Wrap in WAV header (16-bit, mono, 16kHz)
        channels = 1
        bits = 16
        byte_rate = sample_rate * channels * (bits // 8)
        block_align = channels * (bits // 8)
        data_size = len(pcm_data)

        wav = io.BytesIO()
        wav.write(b"RIFF")
        wav.write(struct.pack("<I", 36 + data_size))
        wav.write(b"WAVE")
        wav.write(b"fmt ")
        wav.write(struct.pack("<I", 16))
        wav.write(struct.pack("<H", 1))  # PCM
        wav.write(struct.pack("<H", channels))
        wav.write(struct.pack("<I", sample_rate))
        wav.write(struct.pack("<I", byte_rate))
        wav.write(struct.pack("<H", block_align))
        wav.write(struct.pack("<H", bits))
        wav.write(b"data")
        wav.write(struct.pack("<I", data_size))
        wav.write(pcm_data)

        # Save to temp file
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp.write(wav.getvalue())
        tmp.close()

        logger.info("Generated PCM voice: %d bytes PCM → %s", data_size, tmp.name)
        return tmp.name

    except Exception:
        logger.exception("Failed to generate PCM voice audio")
        return None


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
