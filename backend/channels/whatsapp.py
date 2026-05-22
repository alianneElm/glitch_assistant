import asyncio
import logging
import os

from fastapi import APIRouter, BackgroundTasks, Form, Request, Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from backend.agent.brain import get_response
from backend.config import settings
from backend.services.transcription import transcribe_audio
from backend.services.voice import generate_voice

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["whatsapp"])

twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
validator = RequestValidator(settings.twilio_auth_token)

# Public base URL for serving audio files
_BASE_URL = os.environ.get(
    "RAILWAY_PUBLIC_DOMAIN",
    f"localhost:{settings.port}",
)


def _validate_twilio_request(request: Request, form_data: dict) -> bool:
    if settings.environment == "development":
        return True
    proto = request.headers.get("x-forwarded-proto", "https")
    host = request.headers.get("x-forwarded-host", request.headers.get("host", ""))
    url = f"{proto}://{host}{request.url.path}"
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(url, form_data, signature)


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
):
    form_data = {"From": From, "Body": Body, "NumMedia": str(NumMedia)}
    if not _validate_twilio_request(request, form_data):
        return Response(status_code=403)

    # Respond to Twilio immediately, process in background
    background_tasks.add_task(
        _process_message,
        user_id=From,
        body=Body.strip(),
        num_media=NumMedia,
        media_url=MediaUrl0,
        media_type=MediaContentType0,
    )

    return Response(content="<Response></Response>", media_type="application/xml")


async def _process_message(
    user_id: str,
    body: str,
    num_media: int,
    media_url: str | None,
    media_type: str | None,
):
    """Process the message in the background after responding to Twilio."""
    message = body
    is_voice = False

    if not message and num_media > 0 and media_type and "audio" in media_type:
        is_voice = True
        logger.info("Voice note received from %s, transcribing...", user_id)
        message = await transcribe_audio(
            media_url,
            settings.twilio_account_sid,
            settings.twilio_auth_token,
        )
        if not message:
            _send_whatsapp_message(user_id, "No logré entender el audio. ¿Puedes intentar de nuevo? 🎤")
            return

    if not message:
        return

    logger.info("Message from %s: %s", user_id, message[:100])

    try:
        reply = get_response(user_id, message)
    except Exception:
        logger.exception("Error generating response")
        reply = "Oops, algo falló en mi cerebro. Dame un momento y vuelve a intentarlo. 🔧"

    # If the user sent a voice note, respond with voice + text
    if is_voice and settings.elevenlabs_api_key:
        audio_path = generate_voice(reply)
        if audio_path:
            filename = os.path.basename(audio_path)
            audio_url = f"https://{_BASE_URL}/audio/{filename}"
            _send_whatsapp_voice(user_id, reply, audio_url)
        else:
            _send_whatsapp_message(user_id, reply)
    else:
        _send_whatsapp_message(user_id, reply)


def _normalize_whatsapp_number(number: str) -> str:
    """Fix WhatsApp numbers where '+' was decoded as space in form data."""
    number = number.strip()
    if number.startswith("whatsapp: "):
        number = "whatsapp:+" + number[len("whatsapp: "):]
    if not number.startswith("whatsapp:+"):
        number = number.replace("whatsapp:", "whatsapp:+", 1)
    return number


def _send_whatsapp_message(to: str, body: str):
    to = _normalize_whatsapp_number(to)
    twilio_client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=to,
        body=body,
    )


def _send_whatsapp_voice(to: str, body: str, media_url: str):
    """Send a WhatsApp message with voice audio attached."""
    to = _normalize_whatsapp_number(to)
    twilio_client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=to,
        body=body,
        media_url=[media_url],
    )
