"""Proactive email event detection.

Scans recent Gmail for emails containing events (meetings, reservations,
appointments, flights, etc.) and sends WhatsApp notifications asking
the user if they want to add them to the calendar.
"""

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from backend.config import settings

logger = logging.getLogger(__name__)

# Track processed email IDs to avoid duplicates
_processed_emails: set = set()
_last_reset_date: str = ""


def _reset_if_new_day():
    """Clear processed set daily to keep memory bounded."""
    global _processed_emails, _last_reset_date
    today = datetime.now(ZoneInfo(settings.user_timezone)).strftime("%Y-%m-%d")
    if today != _last_reset_date:
        _processed_emails.clear()
        _last_reset_date = today
        logger.info("Email events: reset processed set for %s", today)


def _get_gmail_service():
    """Get Gmail API service."""
    from googleapiclient.discovery import build
    from backend.services.google_auth import get_google_credentials

    creds = get_google_credentials()
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


def _extract_body(payload: dict) -> str:
    """Extract plain text body from Gmail payload."""
    import base64

    body = ""
    if payload.get("mimeType") == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    elif payload.get("mimeType", "").startswith("multipart"):
        parts = payload.get("parts", [])
        for part in parts:
            if part.get("mimeType") == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    body = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                    break
        if not body:
            for part in parts:
                if part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        body = re.sub(r"<[^>]+>", "", html)
                        body = re.sub(r"\s+", " ", body).strip()
                        break
    return body[:3000]  # Limit to save tokens


def _detect_event_with_ai(subject: str, sender: str, body: str, today_iso: str) -> Optional[dict]:
    """Use Claude to detect if email contains an event.

    Returns dict with event details or None.
    """
    from anthropic import Anthropic

    client = Anthropic(api_key=settings.anthropic_api_key)

    prompt = f"""Analyze this email and determine if it contains a concrete event, appointment, reservation, meeting, or scheduled activity.

Today's date: {today_iso}

Email from: {sender}
Subject: {subject}
Body (excerpt):
{body[:2000]}

If there IS a concrete event with a date/time, respond with JSON:
{{
    "has_event": true,
    "event_name": "short descriptive title",
    "date": "YYYY-MM-DD",
    "time": "HH:MM" or null if no specific time,
    "end_time": "HH:MM" or null,
    "location": "location" or null,
    "description": "brief 1-line description"
}}

If there is NO concrete event (newsletters, promotions, notifications without dates, etc.), respond:
{{"has_event": false}}

Only detect FUTURE events. Ignore past events, general newsletters, marketing emails, and notifications that don't have a specific date/time.
Respond ONLY with the JSON, no other text."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Clean potential markdown wrapping
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        data = json.loads(text)

        if data.get("has_event"):
            return data
        return None

    except Exception:
        logger.debug("AI event detection failed for: %s", subject[:50])
        return None


def check_emails_for_events():
    """Scan recent Gmail for emails containing events.

    Runs every 30 minutes via APScheduler.
    """
    _reset_if_new_day()

    service = _get_gmail_service()
    if not service:
        logger.warning("Email events: no Gmail service available")
        return

    tz = ZoneInfo(settings.user_timezone)
    now = datetime.now(tz)
    today_iso = now.strftime("%Y-%m-%d")

    # Search for recent unread emails (last 2 hours to catch up)
    try:
        two_hours_ago = now - timedelta(hours=2)
        after_date = two_hours_ago.strftime("%Y/%m/%d")

        results = service.users().messages().list(
            userId="me",
            q=f"in:inbox is:unread after:{after_date}",
            maxResults=10,
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return

    except Exception:
        logger.exception("Email events: failed to list Gmail messages")
        return

    events_found = []

    for msg_data in messages:
        msg_id = msg_data["id"]

        if msg_id in _processed_emails:
            continue

        _processed_emails.add(msg_id)

        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_id,
                format="full",
            ).execute()

            headers = {
                h["name"]: h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            subject = headers.get("Subject", "")
            sender = headers.get("From", "")

            # Quick filter: skip obvious non-event emails
            skip_senders = ["noreply", "no-reply", "newsletter", "marketing", "promo"]
            sender_lower = sender.lower()
            if any(s in sender_lower for s in skip_senders):
                continue

            body = _extract_body(msg.get("payload", {}))
            if not body:
                continue

            # Use AI to detect event
            event = _detect_event_with_ai(subject, sender, body, today_iso)
            if event:
                event["email_subject"] = subject
                event["email_sender"] = sender
                events_found.append(event)
                logger.info(
                    "Event detected in email '%s': %s on %s",
                    subject[:40],
                    event.get("event_name"),
                    event.get("date"),
                )

        except Exception:
            logger.debug("Email events: failed to process email %s", msg_id)

    # Send WhatsApp notifications for detected events
    for event in events_found:
        _notify_event(event)


def _notify_event(event: dict):
    """Send WhatsApp notification about a detected event."""
    try:
        from twilio.rest import Client

        name = event.get("event_name", "Evento")
        date = event.get("date", "")
        time_str = event.get("time", "")
        location = event.get("location", "")
        description = event.get("description", "")
        sender = event.get("email_sender", "")
        subject = event.get("email_subject", "")

        # Clean sender name
        if "<" in sender:
            sender = sender.split("<")[0].strip().strip('"')

        msg = f"📧 Detecte un evento en un email de *{sender}*:\n"
        msg += f"📅 *{name}*"
        if date:
            msg += f" — {date}"
        if time_str:
            msg += f" a las {time_str}"
        if location:
            msg += f"\n📍 {location}"
        if description:
            msg += f"\n📝 {description}"
        msg += "\n\n¿Lo agrego al calendario? (si/no)"

        client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=settings.my_whatsapp_number,
            body=msg,
        )
        logger.info("Event notification sent: %s", name)

    except Exception:
        logger.exception("Email events: failed to send notification")
