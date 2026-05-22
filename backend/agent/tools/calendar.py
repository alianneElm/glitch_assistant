import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from backend.config import settings

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/calendar"]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_CREDENTIALS_PATH = _PROJECT_ROOT / "google_credentials.json"
_TOKEN_PATH = _PROJECT_ROOT / "token.json"


def _get_calendar_service():
    """Authenticate and return the Google Calendar service."""
    creds = None

    # Try loading saved token
    if _TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(_TOKEN_PATH), SCOPES)

    # If token from env var (for Railway production)
    if not creds and settings.google_token_json:
        try:
            token_data = json.loads(settings.google_token_json)
            creds = Credentials.from_authorized_user_info(token_data, SCOPES)
        except Exception:
            logger.exception("Failed to load token from env var")

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        # Save refreshed token
        _TOKEN_PATH.write_text(creds.to_json())

    # If no valid creds, do OAuth flow (only works locally)
    if not creds or not creds.valid:
        if not _CREDENTIALS_PATH.exists():
            logger.error("No Google credentials found at %s", _CREDENTIALS_PATH)
            return None
        flow = InstalledAppFlow.from_client_secrets_file(str(_CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        _TOKEN_PATH.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def get_todays_events() -> str:
    """Get today's calendar events."""
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    now = datetime.now().astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=start_of_day.isoformat(),
        timeMax=end_of_day.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    events = events_result.get("items", [])
    if not events:
        return "No tienes eventos para hoy."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        if "T" in start:
            time_str = datetime.fromisoformat(start).strftime("%H:%M")
        else:
            time_str = "Todo el día"
        summary = event.get("summary", "Sin título")
        lines.append(f"• {time_str} — {summary}")

    return "Eventos de hoy:\n" + "\n".join(lines)


def get_upcoming_events(days: int = 7) -> str:
    """Get upcoming events for the next N days."""
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    now = datetime.now().astimezone()
    end = now + timedelta(days=days)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
        maxResults=20,
    ).execute()

    events = events_result.get("items", [])
    if not events:
        return f"No tienes eventos en los próximos {days} días."

    lines = []
    current_date = ""
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        dt = datetime.fromisoformat(start)
        date_str = dt.strftime("%a %d/%m")
        if date_str != current_date:
            current_date = date_str
            lines.append(f"\n📅 {date_str}")
        if "T" in start:
            time_str = dt.strftime("%H:%M")
        else:
            time_str = "Todo el día"
        summary = event.get("summary", "Sin título")
        lines.append(f"  • {time_str} — {summary}")

    return f"Próximos {days} días:" + "".join(lines)


def create_event(summary: str, start_time: str, duration_minutes: int = 60, description: str = "") -> str:
    """Create a calendar event.

    Args:
        summary: Event title
        start_time: ISO format datetime string (e.g. "2026-05-22T14:00:00")
        duration_minutes: Duration in minutes (default 60)
        description: Optional description
    """
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    start_dt = datetime.fromisoformat(start_time)
    end_dt = start_dt + timedelta(minutes=duration_minutes)

    event = {
        "summary": summary,
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": settings.user_timezone,
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": settings.user_timezone,
        },
    }
    if description:
        event["description"] = description

    created = service.events().insert(calendarId="primary", body=event).execute()
    time_str = start_dt.strftime("%H:%M del %d/%m")
    return f"✅ Evento creado: '{summary}' a las {time_str}"
