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


def _get_all_calendar_ids(service) -> list[str]:
    """Get all visible calendar IDs (primary + subscribed like Outlook)."""
    try:
        calendar_list = service.calendarList().list().execute()
        ids = []
        for cal in calendar_list.get("items", []):
            # Include all non-hidden calendars
            if not cal.get("hidden", False):
                ids.append(cal["id"])
        logger.info("Found %d calendars: %s", len(ids), [c.get("summary", c["id"])[:20] for c in calendar_list.get("items", []) if not c.get("hidden", False)])
        return ids or ["primary"]
    except Exception:
        logger.warning("Failed to list calendars, falling back to primary")
        return ["primary"]


def _query_all_calendars(service, time_min: str, time_max: str, max_results: int = 50) -> list[dict]:
    """Query events from all calendars and merge them sorted by start time."""
    calendar_ids = _get_all_calendar_ids(service)
    all_events = []

    for cal_id in calendar_ids:
        try:
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=time_min,
                timeMax=time_max,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            ).execute()
            all_events.extend(events_result.get("items", []))
        except Exception:
            logger.warning("Failed to query calendar %s", cal_id[:30])

    # Sort by start time
    def sort_key(e):
        start = e["start"].get("dateTime", e["start"].get("date", ""))
        return start

    all_events.sort(key=sort_key)
    return all_events


def get_todays_events() -> str:
    """Get today's calendar events."""
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    now = datetime.now().astimezone()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events = _query_all_calendars(service, start_of_day.isoformat(), end_of_day.isoformat())
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

    events = _query_all_calendars(service, now.isoformat(), end.isoformat())
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


def get_busy_times(days: int = 14) -> str:
    """Get busy time slots in a simple format for the voice agent.

    Returns a flat list like:
      BUSY: Saturday 24 May, 14:00-15:00
      BUSY: Sunday 25 May, 10:00-11:00
    """
    service = _get_calendar_service()
    if not service:
        return "WARNING: Could not load calendar."

    now = datetime.now().astimezone()
    end = now + timedelta(days=days)

    events = _query_all_calendars(service, now.isoformat(), end.isoformat(), max_results=30)
    if not events:
        return "Alianne has NO events scheduled. All times are free."

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    lines = []
    for event in events:
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        end_raw = event["end"].get("dateTime", event["end"].get("date", ""))

        if "T" in start_raw:
            start_dt = datetime.fromisoformat(start_raw)
            if end_raw and "T" in end_raw:
                end_dt = datetime.fromisoformat(end_raw)
            else:
                end_dt = start_dt + timedelta(hours=1)
            day_name = day_names[start_dt.weekday()]
            lines.append(
                f"BUSY: {day_name} {start_dt.strftime('%d %B')}, "
                f"{start_dt.strftime('%H:%M')}-{end_dt.strftime('%H:%M')}"
            )
        else:
            dt = datetime.fromisoformat(start_raw)
            day_name = day_names[dt.weekday()]
            lines.append(f"BUSY: {day_name} {dt.strftime('%d %B')}, ALL DAY")

    return "\n".join(lines)


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

    # Check for conflicts across ALL calendars before creating
    existing = _query_all_calendars(
        service,
        start_dt.isoformat(),
        end_dt.isoformat(),
    )
    if existing:
        conflict_names = [e.get("summary", "Sin título") for e in existing[:3]]
        conflicts_str = ", ".join(conflict_names)
        logger.warning("Event conflict detected: '%s' conflicts with: %s", summary, conflicts_str)
        return f"❌ Conflicto: ya tienes '{conflicts_str}' a esa hora. Elige otro horario."

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

    # Sync to Notion
    try:
        from backend.services.notion import add_agenda_entry
        add_agenda_entry(summary, start_time, duration_minutes, description)
    except Exception:
        logger.warning("Failed to sync event to Notion (non-critical)")

    return f"✅ Evento creado: '{summary}' a las {time_str}"
