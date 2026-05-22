import logging
import uuid
from datetime import datetime

from apscheduler.triggers.date import DateTrigger
from twilio.rest import Client

from backend.config import settings
from backend.services.scheduler import scheduler

logger = logging.getLogger(__name__)

_twilio_client = Client(settings.twilio_account_sid, settings.twilio_auth_token)


def _send_reminder(to: str, message: str, job_id: str, is_scheduled_msg: bool = False):
    """Callback that sends a WhatsApp reminder/message and marks it as sent in DB."""
    logger.info("Sending %s to %s: %s", "scheduled message" if is_scheduled_msg else "reminder", to, message[:80])
    body = message if is_scheduled_msg else f"⏰ Recordatorio: {message}"
    _twilio_client.messages.create(
        from_=settings.twilio_whatsapp_number,
        to=to,
        body=body,
    )
    # Mark as sent in database
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            reminder = session.query(ReminderModel).filter(ReminderModel.job_id == job_id).first()
            if reminder:
                reminder.sent = True
                session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to mark reminder %s as sent", job_id)


def create_reminder(reminder_text: str, remind_at: str, user_whatsapp: str = "") -> str:
    """Schedule a reminder and persist it to the database."""
    if not user_whatsapp:
        user_whatsapp = settings.my_whatsapp_number

    try:
        remind_dt = datetime.fromisoformat(remind_at)
    except ValueError:
        return f"No entendí la fecha '{remind_at}'. Usa formato como '2026-05-22T15:00:00'."

    now = datetime.now().astimezone()
    if remind_dt.tzinfo is None:
        from zoneinfo import ZoneInfo
        remind_dt = remind_dt.replace(tzinfo=ZoneInfo(settings.user_timezone))

    if remind_dt <= now:
        return "Esa fecha ya pasó. ¿Quieres que te recuerde en otro momento?"

    job_id = f"reminder_{uuid.uuid4().hex[:8]}"

    # Save to database first
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            db_reminder = ReminderModel(
                job_id=job_id,
                user_whatsapp=user_whatsapp,
                reminder_text=reminder_text,
                remind_at=remind_dt,
            )
            session.add(db_reminder)
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to save reminder to DB")

    # Schedule in APScheduler
    scheduler.add_job(
        _send_reminder,
        trigger=DateTrigger(run_date=remind_dt),
        id=job_id,
        args=[user_whatsapp, reminder_text, job_id],
        replace_existing=True,
    )

    time_str = remind_dt.strftime("%H:%M del %d/%m/%Y")
    logger.info("Reminder scheduled: '%s' at %s (job_id=%s)", reminder_text, time_str, job_id)

    # Sync to Notion
    try:
        from backend.services.notion import add_reminder_entry
        add_reminder_entry(reminder_text, remind_at)
    except Exception:
        logger.warning("Failed to sync reminder to Notion (non-critical)")

    return f"✅ Te recordaré '{reminder_text}' a las {time_str}"


def list_reminders() -> str:
    """List all pending reminders from the database."""
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            reminders = (
                session.query(ReminderModel)
                .filter(ReminderModel.sent == False)
                .filter(ReminderModel.remind_at > datetime.now().astimezone())
                .order_by(ReminderModel.remind_at)
                .all()
            )
            if not reminders:
                return "No tienes recordatorios pendientes."

            lines = []
            for r in reminders:
                time_str = r.remind_at.strftime("%H:%M del %d/%m")
                lines.append(f"• {time_str} — {r.reminder_text}")
            return "Recordatorios pendientes:\n" + "\n".join(lines)
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to list reminders from DB")
        # Fallback to APScheduler
        return _list_reminders_from_scheduler()


def list_todays_reminders() -> str:
    """List only today's pending reminders."""
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            now = datetime.now().astimezone()
            end_of_day = now.replace(hour=23, minute=59, second=59)
            reminders = (
                session.query(ReminderModel)
                .filter(ReminderModel.sent == False)
                .filter(ReminderModel.remind_at > now)
                .filter(ReminderModel.remind_at <= end_of_day)
                .order_by(ReminderModel.remind_at)
                .all()
            )
            if not reminders:
                return ""

            lines = []
            for r in reminders:
                time_str = r.remind_at.strftime("%H:%M")
                lines.append(f"{time_str} — {r.reminder_text}")
            return "\n".join(lines)
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to list today's reminders from DB")
        return ""


def _list_reminders_from_scheduler() -> str:
    """Fallback: list reminders from APScheduler."""
    jobs = scheduler.get_jobs()
    reminder_jobs = [j for j in jobs if j.id.startswith("reminder_")]
    if not reminder_jobs:
        return "No tienes recordatorios pendientes."
    lines = []
    for job in reminder_jobs:
        run_time = job.next_run_time.strftime("%H:%M del %d/%m")
        text = job.args[1] if len(job.args) > 1 else "?"
        lines.append(f"• {run_time} — {text}")
    return "Recordatorios pendientes:\n" + "\n".join(lines)


def delete_reminder(reminder_text: str) -> str:
    """Delete a reminder by matching its text."""
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            reminders = (
                session.query(ReminderModel)
                .filter(ReminderModel.sent == False)
                .all()
            )
            for r in reminders:
                if reminder_text.lower() in r.reminder_text.lower():
                    # Remove from scheduler
                    try:
                        scheduler.remove_job(r.job_id)
                    except Exception:
                        pass  # Job might not exist in scheduler
                    # Remove from database
                    session.delete(r)
                    session.commit()
                    return f"✅ Recordatorio '{r.reminder_text}' eliminado."
            return f"No encontré un recordatorio con '{reminder_text}'."
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to delete reminder from DB")
        # Fallback to APScheduler-only deletion
        return _delete_reminder_from_scheduler(reminder_text)


def _delete_reminder_from_scheduler(reminder_text: str) -> str:
    """Fallback: delete from APScheduler only."""
    jobs = scheduler.get_jobs()
    for job in jobs:
        if job.id.startswith("reminder_") and len(job.args) > 1:
            if reminder_text.lower() in job.args[1].lower():
                scheduler.remove_job(job.id)
                return f"✅ Recordatorio '{job.args[1]}' eliminado."
    return f"No encontré un recordatorio con '{reminder_text}'."


def send_whatsapp(to_phone: str, message: str) -> str:
    """Send a WhatsApp message immediately to a contact.

    Args:
        to_phone: Recipient phone number (e.g. '+46701234567')
        message: Message text to send
    """
    to_phone = to_phone.strip()
    if not to_phone.startswith("whatsapp:"):
        if not to_phone.startswith("+"):
            to_phone = "+" + to_phone
        to_phone = f"whatsapp:{to_phone}"

    try:
        _twilio_client.messages.create(
            from_=settings.twilio_whatsapp_number,
            to=to_phone,
            body=message,
        )
        short_phone = to_phone.replace("whatsapp:", "")
        logger.info("WhatsApp sent to %s: %s", short_phone, message[:80])
        return f"✅ Mensaje enviado a {short_phone}"
    except Exception as e:
        logger.exception("Failed to send WhatsApp to %s", to_phone)
        return f"❌ Error al enviar: {e}"


def send_scheduled_message(to_phone: str, message: str, send_at: str) -> str:
    """Schedule a WhatsApp message to another contact at a specific time.

    Args:
        to_phone: Recipient phone number (e.g. '+46701234567')
        message: Message text to send
        send_at: When to send, ISO format (e.g. '2026-05-22T15:00:00')
    """
    # Normalize phone number to whatsapp: format
    to_phone = to_phone.strip()
    if not to_phone.startswith("whatsapp:"):
        if not to_phone.startswith("+"):
            to_phone = "+" + to_phone
        to_phone = f"whatsapp:{to_phone}"

    try:
        send_dt = datetime.fromisoformat(send_at)
    except ValueError:
        return f"No entendí la fecha '{send_at}'. Usa formato como '2026-05-22T15:00:00'."

    now = datetime.now().astimezone()
    if send_dt.tzinfo is None:
        from zoneinfo import ZoneInfo
        send_dt = send_dt.replace(tzinfo=ZoneInfo(settings.user_timezone))

    if send_dt <= now:
        return "Esa fecha ya pasó. ¿Quieres programarlo para otro momento?"

    job_id = f"scheduled_msg_{uuid.uuid4().hex[:8]}"

    # Save to database
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            db_entry = ReminderModel(
                job_id=job_id,
                user_whatsapp=to_phone,
                reminder_text=f"[MSG] {message}",
                remind_at=send_dt,
            )
            session.add(db_entry)
            session.commit()
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to save scheduled message to DB")

    # Schedule in APScheduler
    scheduler.add_job(
        _send_reminder,
        trigger=DateTrigger(run_date=send_dt),
        id=job_id,
        args=[to_phone, message, job_id],
        kwargs={"is_scheduled_msg": True},
        replace_existing=True,
    )

    time_str = send_dt.strftime("%H:%M del %d/%m/%Y")
    short_phone = to_phone.replace("whatsapp:", "")
    logger.info("Scheduled message to %s: '%s' at %s (job_id=%s)", short_phone, message[:50], time_str, job_id)
    return f"✅ Mensaje programado para {short_phone} a las {time_str}: '{message[:60]}'"


def reload_reminders_from_db():
    """Reload pending reminders from DB into APScheduler on startup.

    This ensures reminders survive server restarts.
    """
    try:
        from backend.models.reminder import Reminder as ReminderModel
        from backend.services.database import get_session
        session = get_session()
        try:
            now = datetime.now().astimezone()
            pending = (
                session.query(ReminderModel)
                .filter(ReminderModel.sent == False)
                .filter(ReminderModel.remind_at > now)
                .all()
            )
            count = 0
            for r in pending:
                try:
                    is_scheduled = r.reminder_text.startswith("[MSG] ")
                    msg_text = r.reminder_text[6:] if is_scheduled else r.reminder_text
                    scheduler.add_job(
                        _send_reminder,
                        trigger=DateTrigger(run_date=r.remind_at),
                        id=r.job_id,
                        args=[r.user_whatsapp, msg_text, r.job_id],
                        kwargs={"is_scheduled_msg": is_scheduled},
                        replace_existing=True,
                    )
                    count += 1
                except Exception:
                    logger.exception("Failed to reload reminder %s", r.job_id)

            logger.info("Reloaded %d pending reminders from database", count)
        finally:
            session.close()
    except Exception:
        logger.exception("Failed to reload reminders from database")
