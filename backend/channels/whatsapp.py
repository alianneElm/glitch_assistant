import logging

from fastapi import APIRouter, Form, Request, Response
from twilio.request_validator import RequestValidator
from twilio.rest import Client

from backend.agent.brain import get_response
from backend.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["whatsapp"])

twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
validator = RequestValidator(settings.twilio_auth_token)


def _validate_twilio_request(request: Request, form_data: dict) -> bool:
    if settings.environment == "development":
        return True
    url = str(request.url)
    signature = request.headers.get("X-Twilio-Signature", "")
    return validator.validate(url, form_data, signature)


@router.post("/whatsapp")
async def whatsapp_webhook(
    request: Request,
    From: str = Form(...),
    Body: str = Form(""),
    NumMedia: int = Form(0),
    MediaUrl0: str = Form(None),
    MediaContentType0: str = Form(None),
):
    form_data = {"From": From, "Body": Body, "NumMedia": str(NumMedia)}
    if not _validate_twilio_request(request, form_data):
        return Response(status_code=403)

    user_id = From
    message = Body.strip()

    if not message:
        if NumMedia > 0 and MediaContentType0 and "audio" in MediaContentType0:
            message = "[voice note received — transcription coming soon]"
        else:
            message = "[empty message]"

    logger.info("Message from %s: %s", user_id, message[:100])

    try:
        reply = get_response(user_id, message)
    except Exception:
        logger.exception("Error generating response")
        reply = "Oops, algo falló en mi cerebro. Dame un momento y vuelve a intentarlo. 🔧"

    _send_whatsapp_message(user_id, reply)

    return Response(content="<Response></Response>", media_type="application/xml")


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
