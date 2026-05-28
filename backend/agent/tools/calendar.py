import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build

from backend.config import settings
from backend.services.google_auth import get_google_credentials

logger = logging.getLogger(__name__)


def _get_calendar_service():
    """Authenticate and return the Google Calendar service."""
    creds = get_google_credentials()
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def _get_all_calendar_ids(service) -> list[str]:
    """Get ALL calendar IDs including subscribed/hidden ones (Outlook, etc)."""
    try:
        # showHidden=True and showDeleted=False to include ICS subscriptions
        calendar_list = service.calendarList().list(showHidden=True).execute()
        ids = []
        all_names = []
        for cal in calendar_list.get("items", []):
            cal_id = cal["id"]
            cal_name = cal.get("summary", cal_id)[:30]
            ids.append(cal_id)
            hidden = cal.get("hidden", False)
            all_names.append(f"{cal_name}{'(hidden)' if hidden else ''}")
        logger.info("Found %d calendars: %s", len(ids), all_names)
        return ids or ["primary"]
    except Exception:
        logger.warning("Failed to list calendars, falling back to primary")
        return ["primary"]


def _query_all_calendars(service, time_min: str, time_max: str, max_results: int = 100) -> list[dict]:
    """Query events from all calendars and merge them sorted by start time.

    Deduplicates by event ID AND by (title + start time) to catch
    the same event appearing in multiple calendars with different IDs
    (common with imported/ICS calendars).
    """
    calendar_ids = _get_all_calendar_ids(service)
    all_events = []
    seen_ids = set()  # Deduplicate by event ID
    seen_keys = set()  # Deduplicate by title + start time

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
            for event in events_result.get("items", []):
                eid = event.get("id", "")
                # Build a content key for cross-calendar deduplication
                summary = event.get("summary", "").lower().strip()
                start = event["start"].get("dateTime", event["start"].get("date", ""))
                content_key = f"{summary}|{start}"

                if eid not in seen_ids and content_key not in seen_keys:
                    seen_ids.add(eid)
                    seen_keys.add(content_key)
                    all_events.append(event)
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

    now = datetime.now(ZoneInfo(settings.user_timezone))
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    events = _query_all_calendars(service, start_of_day.isoformat(), end_of_day.isoformat())
    if not events:
        return "No tienes eventos para hoy."

    lines = []
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        if "T" in start:
            time_str = _parse_iso(start).strftime("%H:%M")
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

    now = datetime.now(ZoneInfo(settings.user_timezone))
    end = now + timedelta(days=days)

    events = _query_all_calendars(service, now.isoformat(), end.isoformat())
    if not events:
        return f"No tienes eventos en los próximos {days} días."

    lines = []
    current_date = ""
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        dt = _parse_iso(start)
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

    IMPORTANT: Uses "to" instead of "-" between times so TTS doesn't
    read it as "minus". Also groups by day and shows FREE slots to make
    it crystal clear when Alianne is available.
    """
    service = _get_calendar_service()
    if not service:
        return "WARNING: Could not load calendar."

    now = datetime.now(ZoneInfo(settings.user_timezone))
    end = now + timedelta(days=days)

    events = _query_all_calendars(service, now.isoformat(), end.isoformat(), max_results=100)
    if not events:
        return "Alianne has NO events scheduled. All times are free."

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    # Group events by date
    events_by_date: dict[str, list] = {}
    for event in events:
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        end_raw = event["end"].get("dateTime", event["end"].get("date", ""))
        summary = event.get("summary", "Busy")

        if "T" in start_raw:
            start_dt = _parse_iso(start_raw)
            if end_raw and "T" in end_raw:
                end_dt = _parse_iso(end_raw)
            else:
                end_dt = start_dt + timedelta(hours=1)
            date_key = start_dt.strftime("%Y-%m-%d")
            events_by_date.setdefault(date_key, []).append({
                "start": start_dt,
                "end": end_dt,
                "summary": summary,
            })
        else:
            dt = _parse_iso(start_raw)
            date_key = dt.strftime("%Y-%m-%d")
            events_by_date.setdefault(date_key, []).append({
                "start": dt,
                "end": dt + timedelta(hours=24),
                "summary": summary,
                "all_day": True,
            })

    lines = []
    lines.append("ALIANNE'S CALENDAR (all calendars combined):")
    lines.append("IMPORTANT: Do NOT book any time that overlaps with BUSY slots.")
    lines.append("")

    for date_key in sorted(events_by_date.keys()):
        day_events = sorted(events_by_date[date_key], key=lambda e: e["start"])
        dt = day_events[0]["start"]
        day_name = day_names[dt.weekday()]
        lines.append(f"=== {day_name} {dt.strftime('%d %B %Y')} ===")

        for ev in day_events:
            if ev.get("all_day"):
                lines.append(f"  BUSY ALL DAY: {ev['summary']}")
            else:
                lines.append(
                    f"  BUSY from {ev['start'].strftime('%H:%M')} to {ev['end'].strftime('%H:%M')}: {ev['summary']}"
                )

        # Calculate free slots (between 7:00 and 21:00)
        if not any(ev.get("all_day") for ev in day_events):
            free_slots = _calculate_free_slots(day_events, dt)
            if free_slots:
                for slot in free_slots:
                    lines.append(f"  FREE from {slot[0]} to {slot[1]}")

        lines.append("")

    logger.info("Loaded busy times for %d days for voice agent", len(events_by_date))
    return "\n".join(lines)


def _calculate_free_slots(
    events: list[dict], day_dt: datetime
) -> list[tuple[str, str]]:
    """Calculate free time slots between events on a given day.

    Only considers slots between 7:00 and 21:00.
    """
    day_start_hour = 7
    day_end_hour = 21

    day_start = day_dt.replace(hour=day_start_hour, minute=0, second=0, microsecond=0)
    day_end = day_dt.replace(hour=day_end_hour, minute=0, second=0, microsecond=0)

    # Sort events by start time
    sorted_events = sorted(events, key=lambda e: e["start"])

    free = []
    current = day_start

    for ev in sorted_events:
        ev_start = ev["start"]
        ev_end = ev["end"]

        # Skip events outside our window
        if ev_end <= day_start or ev_start >= day_end:
            continue

        # Clamp to our window
        ev_start = max(ev_start, day_start)
        ev_end = min(ev_end, day_end)

        if ev_start > current:
            gap_minutes = (ev_start - current).total_seconds() / 60
            if gap_minutes >= 30:  # Only show slots >= 30 min
                free.append((
                    current.strftime("%H:%M"),
                    ev_start.strftime("%H:%M"),
                ))
        current = max(current, ev_end)

    # Free time after last event
    if current < day_end:
        gap_minutes = (day_end - current).total_seconds() / 60
        if gap_minutes >= 30:
            free.append((current.strftime("%H:%M"), day_end.strftime("%H:%M")))

    return free


def _parse_iso(raw: str) -> datetime:
    """Parse ISO datetime string, handling trailing Z for Python 3.9 compat.

    Always returns a timezone-aware datetime converted to the user's timezone.
    This ensures all displayed times match the user's local time regardless of
    the source timezone (UTC, other offset, etc.).
    """
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo(settings.user_timezone))
    return dt.astimezone(ZoneInfo(settings.user_timezone))


def _ensure_tz(dt: datetime) -> datetime:
    """Ensure a datetime has timezone info; default to user's timezone if naive."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(settings.user_timezone))
    return dt


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

    start_dt = _ensure_tz(_parse_iso(start_time))
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


def _find_event(service, search_text: str, days_ahead: int = 30) -> Optional[dict]:
    """Find an event by searching its title across all calendars."""
    now = datetime.now(ZoneInfo(settings.user_timezone))
    end = now + timedelta(days=days_ahead)

    events = _query_all_calendars(service, now.isoformat(), end.isoformat(), max_results=50)

    search_lower = search_text.lower()
    for event in events:
        title = event.get("summary", "").lower()
        if search_lower in title:
            return event

    return None


def edit_event(
    search_text: str,
    new_summary: str = "",
    new_start_time: str = "",
    new_duration_minutes: int = 0,
    new_description: str = "",
) -> str:
    """Edit an existing calendar event by searching for it.

    Args:
        search_text: Text to search for in event titles (partial match)
        new_summary: New title (empty = keep current)
        new_start_time: New start time ISO format (empty = keep current)
        new_duration_minutes: New duration in minutes (0 = keep current)
        new_description: New description (empty = keep current)
    """
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    event = _find_event(service, search_text)
    if not event:
        return f"No encontré un evento con '{search_text}' en los próximos 30 días."

    event_id = event["id"]
    old_summary = event.get("summary", "Sin título")
    # Events can only be edited on the calendar they belong to
    cal_id = event.get("organizer", {}).get("email", "primary")

    # Build updated fields
    updated = {}
    if new_summary:
        updated["summary"] = new_summary
    if new_start_time:
        start_dt = _ensure_tz(_parse_iso(new_start_time))
        duration = new_duration_minutes or 60
        end_dt = start_dt + timedelta(minutes=duration)

        # Check conflicts at new time (exclude this event)
        existing = _query_all_calendars(service, start_dt.isoformat(), end_dt.isoformat())
        conflicts = [e for e in existing if e.get("id") != event_id]
        if conflicts:
            conflict_names = [e.get("summary", "Sin título") for e in conflicts[:3]]
            return f"❌ Conflicto: ya tienes '{', '.join(conflict_names)}' a esa hora."

        updated["start"] = {"dateTime": start_dt.isoformat(), "timeZone": settings.user_timezone}
        updated["end"] = {"dateTime": end_dt.isoformat(), "timeZone": settings.user_timezone}
    elif new_duration_minutes:
        # Keep same start, change duration
        start_raw = event["start"].get("dateTime", event["start"].get("date"))
        start_dt = _parse_iso(start_raw)
        end_dt = start_dt + timedelta(minutes=new_duration_minutes)
        updated["end"] = {"dateTime": end_dt.isoformat(), "timeZone": settings.user_timezone}
    if new_description:
        updated["description"] = new_description

    if not updated:
        return "No especificaste qué cambiar del evento."

    try:
        service.events().patch(calendarId=cal_id, eventId=event_id, body=updated).execute()
        changes = []
        if new_summary:
            changes.append(f"título: {new_summary}")
        if new_start_time:
            changes.append(f"hora: {_parse_iso(new_start_time).strftime('%H:%M del %d/%m')}")
        if new_duration_minutes:
            changes.append(f"duración: {new_duration_minutes} min")
        if new_description:
            changes.append("descripción actualizada")

        logger.info("Event edited: '%s' → %s", old_summary, ", ".join(changes))
        return f"✅ Evento '{old_summary}' actualizado: {', '.join(changes)}"
    except Exception as e:
        logger.exception("Failed to edit event '%s'", old_summary)
        return f"❌ Error al editar: {e}"


def delete_event(search_text: str) -> str:
    """Delete a calendar event by searching for it.

    Args:
        search_text: Text to search for in event titles (partial match)
    """
    service = _get_calendar_service()
    if not service:
        return "No puedo acceder al calendario ahora."

    event = _find_event(service, search_text)
    if not event:
        return f"No encontré un evento con '{search_text}' en los próximos 30 días."

    event_id = event["id"]
    summary = event.get("summary", "Sin título")
    cal_id = event.get("organizer", {}).get("email", "primary")

    start_raw = event["start"].get("dateTime", event["start"].get("date"))
    if "T" in start_raw:
        time_str = _parse_iso(start_raw).strftime("%H:%M del %d/%m")
    else:
        time_str = start_raw

    try:
        service.events().delete(calendarId=cal_id, eventId=event_id).execute()
        logger.info("Event deleted: '%s' at %s", summary, time_str)
        return f"✅ Evento eliminado: '{summary}' ({time_str})"
    except Exception as e:
        logger.exception("Failed to delete event '%s'", summary)
        return f"❌ Error al eliminar: {e}"
