"""Proactive calendar event alerts.

Checks upcoming events every 5 minutes and sends a WhatsApp
notification ~15 minutes before each event starts.
"""

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from backend.config import settings

logger = logging.getLogger(__name__)

# Track notified event IDs to avoid duplicates (reset daily)
_notified_events: set = set()
_last_reset_date: str = ""


def _reset_if_new_day():
    """Clear notified set at the start of each new day."""
    global _notified_events, _last_reset_date
    today = datetime.now(ZoneInfo(settings.user_timezone)).strftime("%Y-%m-%d")
    if today != _last_reset_date:
        _notified_events.clear()
        _last_reset_date = today
        logger.info("Event alerts: reset notified set for %s", today)


def check_upcoming_events():
    """Check for events starting in the next 15 minutes and send alerts.

    Runs every 5 minutes via APScheduler.
    """
    from backend.agent.tools.calendar import _get_calendar_service, _query_all_calendars

    _reset_if_new_day()

    service = _get_calendar_service()
    if not service:
        logger.warning("Event alerts: no calendar service available")
        return

    tz = ZoneInfo(settings.user_timezone)
    now = datetime.now(tz)

    # Query events starting in the next 5-20 minute window
    # We check 5-20 min ahead so the 5-min job interval catches events
    # that start in ~10-15 min from now
    window_start = now + timedelta(minutes=5)
    window_end = now + timedelta(minutes=20)

    try:
        events = _query_all_calendars(
            service,
            window_start.isoformat(),
            window_end.isoformat(),
            max_results=10,
        )
    except Exception:
        logger.exception("Event alerts: failed to query calendar")
        return

    if not events:
        return

    for event in events:
        event_id = event.get("id", "")
        if event_id in _notified_events:
            continue

        # Skip all-day events
        start_raw = event["start"].get("dateTime")
        if not start_raw:
            continue

        summary = event.get("summary", "Sin titulo")
        start_dt = datetime.fromisoformat(
            start_raw.replace("Z", "+00:00") if start_raw.endswith("Z") else start_raw
        ).astimezone(ZoneInfo(settings.user_timezone))
        minutes_until = int((start_dt - now).total_seconds() / 60)

        # Only alert for events 5-20 minutes away
        if minutes_until < 5 or minutes_until > 20:
            continue

        # Build alert message
        time_str = start_dt.strftime("%H:%M")
        location = event.get("location", "")

        msg = f"⏰ En {minutes_until} min: *{summary}* ({time_str})"
        if location:
            msg += f"\n📍 {location}"
            # Calculate travel time
            travel = _get_travel_time(location)
            if travel:
                msg += f"\n🚗 {travel}"

        # Check for meeting link
        hangout = event.get("hangoutLink", "")
        if hangout:
            msg += f"\n🔗 {hangout}"
        else:
            # Check description for links
            desc = event.get("description", "")
            if desc:
                import re
                links = re.findall(r'https?://\S+', desc)
                meet_links = [l for l in links if any(
                    k in l for k in ["meet.google", "zoom.us", "teams.microsoft"]
                )]
                if meet_links:
                    msg += f"\n🔗 {meet_links[0]}"

        # Send WhatsApp alert
        _send_alert(msg)
        _notified_events.add(event_id)
        logger.info("Event alert sent: '%s' in %d min", summary, minutes_until)


def _get_travel_time(destination: str) -> str:
    """Get travel time from user's city to event location via Google Maps.

    Returns a string like '25 min en coche' or empty string on failure.
    """
    if not settings.google_maps_api_key:
        return ""

    try:
        import httpx

        origin = f"{settings.user_city}, Sweden"

        with httpx.Client(timeout=10) as client:
            resp = client.get(
                "https://maps.googleapis.com/maps/api/directions/json",
                params={
                    "origin": origin,
                    "destination": destination,
                    "key": settings.google_maps_api_key,
                    "language": "es",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        if data.get("status") != "OK":
            logger.debug("Directions API status: %s for '%s'", data.get("status"), destination)
            return ""

        leg = data["routes"][0]["legs"][0]
        duration = leg["duration"]["text"]  # e.g. "35 mins"
        distance = leg["distance"]["text"]  # e.g. "42.3 km"

        return f"{duration} en coche ({distance})"

    except Exception:
        logger.debug("Failed to get travel time to '%s'", destination)
        return ""


def _send_alert(message: str):
    """Send a WhatsApp alert message."""
    try:
        from twilio.rest import Client

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=settings.my_whatsapp_number,
            body=message,
        )
    except Exception:
        logger.exception("Event alerts: failed to send WhatsApp")
