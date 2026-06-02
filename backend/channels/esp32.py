"""ESP32 device channel for Glitch.

Receives raw audio from ESP32, transcribes it, processes with the agent brain,
generates TTS response, and returns the audio URL + text.
"""

import io
import logging
import os
import struct
import uuid

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from backend.agent.brain import get_response
from backend.config import settings
from backend.services.voice import generate_voice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/esp32", tags=["esp32"])

# Public base URL for serving audio files
_BASE_URL = os.environ.get(
    "RAILWAY_PUBLIC_DOMAIN",
    f"localhost:{settings.port}",
)


def _raw_to_wav(raw_bytes: bytes, sample_rate: int = 16000, channels: int = 1, bits: int = 16) -> bytes:
    """Convert raw PCM bytes to WAV format."""
    data_size = len(raw_bytes)
    byte_rate = sample_rate * channels * (bits // 8)
    block_align = channels * (bits // 8)

    wav = io.BytesIO()
    # RIFF header
    wav.write(b"RIFF")
    wav.write(struct.pack("<I", 36 + data_size))
    wav.write(b"WAVE")
    # fmt chunk
    wav.write(b"fmt ")
    wav.write(struct.pack("<I", 16))  # chunk size
    wav.write(struct.pack("<H", 1))   # PCM format
    wav.write(struct.pack("<H", channels))
    wav.write(struct.pack("<I", sample_rate))
    wav.write(struct.pack("<I", byte_rate))
    wav.write(struct.pack("<H", block_align))
    wav.write(struct.pack("<H", bits))
    # data chunk
    wav.write(b"data")
    wav.write(struct.pack("<I", data_size))
    wav.write(raw_bytes)

    return wav.getvalue()


@router.post("/voice")
async def esp32_voice(
    request: Request,
    x_user_id: str = Header(default="+46762547179"),
    x_sample_rate: int = Header(default=16000),
    x_channels: int = Header(default=1),
    x_bits: int = Header(default=16),
):
    """Process voice input from ESP32 device.

    Receives raw PCM audio, transcribes it, processes with agent,
    generates TTS response, and returns audio URL.
    """
    try:
        # Read raw audio bytes
        raw_audio = await request.body()
        if not raw_audio or len(raw_audio) < 1000:
            return JSONResponse(
                status_code=400,
                content={"status": "error", "message": "Audio too short or empty"},
            )

        logger.info(
            "ESP32 voice: received %d bytes (rate=%d, ch=%d, bits=%d) from %s",
            len(raw_audio), x_sample_rate, x_channels, x_bits, x_user_id,
        )

        # Convert raw PCM to WAV for Whisper
        wav_bytes = _raw_to_wav(raw_audio, x_sample_rate, x_channels, x_bits)

        # Save WAV to temp file for transcription
        wav_path = f"/tmp/esp32_{uuid.uuid4().hex[:8]}.wav"
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        # Transcribe with Whisper
        transcript = await _transcribe_wav(wav_path)

        # Clean up WAV file
        try:
            os.remove(wav_path)
        except OSError:
            pass

        if not transcript:
            return JSONResponse(content={
                "status": "error",
                "message": "Could not transcribe audio",
                "transcript": "",
                "response": "",
                "audio_url": "",
            })

        logger.info("ESP32 voice transcript: %s", transcript[:100])

        # Process with Glitch brain
        try:
            reply = get_response(x_user_id, transcript)
        except Exception:
            logger.exception("Error generating response for ESP32")
            reply = "Algo falló, intenta de nuevo."

        logger.info("ESP32 voice reply: %s", reply[:100])

        # Generate TTS audio
        audio_url = ""
        if settings.elevenlabs_api_key:
            audio_path = generate_voice(reply)
            if audio_path:
                filename = os.path.basename(audio_path)
                audio_url = f"https://{_BASE_URL}/audio/{filename}"

        return JSONResponse(content={
            "status": "success",
            "transcript": transcript,
            "response": reply,
            "audio_url": audio_url,
        })

    except Exception:
        logger.exception("ESP32 voice processing failed")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Internal server error"},
        )


async def _transcribe_wav(wav_path: str) -> str:
    """Transcribe a WAV file using Whisper."""
    try:
        from backend.services.transcription import transcribe_audio
        # transcribe_audio expects a URL, but we have a local file
        # Use OpenAI Whisper directly for local files
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key)
        with open(wav_path, "rb") as f:
            response = client.audio.transcriptions.create(
                model="whisper-1",
                file=f,
                language="es",  # Primary language
            )
        return response.text.strip()
    except Exception:
        logger.exception("ESP32 transcription failed")
        return ""


@router.get("/ping")
async def esp32_ping():
    """Health check for ESP32 devices."""
    return {"status": "ok", "device": "esp32", "version": "1.0"}
