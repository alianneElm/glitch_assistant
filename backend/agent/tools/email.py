"""Email integration for Glitch — Gmail API + Yahoo IMAP/SMTP.

Supports reading, searching, sending, and replying to emails
from both Gmail and Yahoo accounts.
"""

import base64
import email
import imaplib
import logging
import re
import smtplib
from email.header import decode_header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from backend.config import settings
from backend.services.google_auth import get_google_credentials

logger = logging.getLogger(__name__)


# ─── Gmail ────────────────────────────────────────────────────────────


def _get_gmail_service():
    """Get authenticated Gmail API service."""
    creds = get_google_credentials()
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


def get_recent_emails_gmail(limit: int = 10, query: str = "") -> str:
    """Get recent emails from Gmail inbox.

    Args:
        limit: Number of emails to fetch (max 20)
        query: Optional Gmail search query (e.g. 'from:amazon', 'is:unread', 'subject:factura')
    """
    service = _get_gmail_service()
    if not service:
        return "No puedo acceder a Gmail ahora."

    try:
        search_query = query or "in:inbox"
        if query and "in:" not in query and "is:" not in query:
            search_query = f"in:inbox {query}"

        results = service.users().messages().list(
            userId="me",
            q=search_query,
            maxResults=min(limit, 20),
        ).execute()

        messages = results.get("messages", [])
        if not messages:
            return f"No hay emails{' con esa búsqueda' if query else ' recientes'} en Gmail."

        lines = []
        for msg_data in messages:
            msg = service.users().messages().get(
                userId="me",
                id=msg_data["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date"],
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            from_addr = headers.get("From", "Desconocido")
            subject = headers.get("Subject", "(sin asunto)")
            date_str = headers.get("Date", "")
            snippet = msg.get("snippet", "")[:80]
            is_unread = "UNREAD" in msg.get("labelIds", [])
            marker = "🔵" if is_unread else "⚪"

            # Clean from address
            if "<" in from_addr:
                from_name = from_addr.split("<")[0].strip().strip('"')
                if not from_name:
                    from_name = from_addr.split("<")[1].split(">")[0]
            else:
                from_name = from_addr

            lines.append(
                f"{marker} **{from_name}**\n"
                f"   {subject}\n"
                f"   _{snippet}_\n"
                f"   ID: {msg_data['id']}"
            )

        header = f"📧 Gmail — {len(lines)} emails:\n\n"
        return header + "\n\n".join(lines)

    except Exception as e:
        logger.exception("Failed to fetch Gmail messages")
        return f"Error al leer Gmail: {e}"


def read_email_gmail(email_id: str) -> str:
    """Read the full content of a specific Gmail email.

    Args:
        email_id: The email ID (from get_recent_emails_gmail)
    """
    service = _get_gmail_service()
    if not service:
        return "No puedo acceder a Gmail ahora."

    try:
        msg = service.users().messages().get(
            userId="me",
            id=email_id,
            format="full",
        ).execute()

        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        from_addr = headers.get("From", "Desconocido")
        to_addr = headers.get("To", "")
        subject = headers.get("Subject", "(sin asunto)")
        date_str = headers.get("Date", "")

        # Extract body
        body = _extract_gmail_body(msg.get("payload", {}))

        # Mark as read
        service.users().messages().modify(
            userId="me",
            id=email_id,
            body={"removeLabelIds": ["UNREAD"]},
        ).execute()

        return (
            f"📧 Email completo:\n"
            f"De: {from_addr}\n"
            f"Para: {to_addr}\n"
            f"Asunto: {subject}\n"
            f"Fecha: {date_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{body[:3000]}"
        )

    except Exception as e:
        logger.exception("Failed to read Gmail message %s", email_id)
        return f"Error al leer email: {e}"


def _extract_gmail_body(payload: dict) -> str:
    """Extract text body from Gmail message payload."""
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
        # Fallback to HTML if no plain text
        if not body:
            for part in parts:
                if part.get("mimeType") == "text/html":
                    data = part.get("body", {}).get("data", "")
                    if data:
                        html = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
                        body = re.sub(r"<[^>]+>", "", html)
                        body = re.sub(r"\s+", " ", body).strip()
                        break

    return body or "(No se pudo extraer el contenido del email)"


def send_email_gmail(to: str, subject: str, body: str) -> str:
    """Send an email from Gmail.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
    """
    service = _get_gmail_service()
    if not service:
        return "No puedo acceder a Gmail ahora."

    try:
        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        message.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId="me",
            body={"raw": raw},
        ).execute()

        logger.info("Gmail sent to %s: %s", to, subject)
        return f"✅ Email enviado desde Gmail a {to}: {subject}"

    except Exception as e:
        logger.exception("Failed to send Gmail")
        return f"Error al enviar email: {e}"


def reply_email_gmail(email_id: str, body: str) -> str:
    """Reply to a specific Gmail email.

    Args:
        email_id: The email ID to reply to
        body: Reply body text
    """
    service = _get_gmail_service()
    if not service:
        return "No puedo acceder a Gmail ahora."

    try:
        # Get original message for headers
        original = service.users().messages().get(
            userId="me",
            id=email_id,
            format="metadata",
            metadataHeaders=["From", "Subject", "Message-ID"],
        ).execute()

        headers = {h["name"]: h["value"] for h in original.get("payload", {}).get("headers", [])}
        to = headers.get("From", "")
        subject = headers.get("Subject", "")
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        message_id = headers.get("Message-ID", "")
        thread_id = original.get("threadId", "")

        message = MIMEMultipart()
        message["to"] = to
        message["subject"] = subject
        if message_id:
            message["In-Reply-To"] = message_id
            message["References"] = message_id
        message.attach(MIMEText(body, "plain"))

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        service.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id},
        ).execute()

        logger.info("Gmail reply sent to %s: %s", to, subject)
        return f"✅ Respuesta enviada a {to}"

    except Exception as e:
        logger.exception("Failed to reply to Gmail %s", email_id)
        return f"Error al responder: {e}"


# ─── Yahoo (IMAP/SMTP) ───────────────────────────────────────────────


def _decode_header_value(value: str) -> str:
    """Decode an email header that might be encoded."""
    if not value:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            result.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            result.append(part)
    return " ".join(result)


def get_recent_emails_yahoo(limit: int = 10, folder: str = "INBOX") -> str:
    """Get recent emails from Yahoo inbox via IMAP.

    Args:
        limit: Number of emails to fetch (max 20)
        folder: Mail folder (default INBOX)
    """
    if not settings.yahoo_email or not settings.yahoo_app_password:
        return "Yahoo email no está configurado. Necesito YAHOO_EMAIL y YAHOO_APP_PASSWORD."

    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(settings.yahoo_email, settings.yahoo_app_password)
        mail.select(folder, readonly=True)

        # Search for recent messages
        _, data = mail.search(None, "ALL")
        msg_ids = data[0].split()

        if not msg_ids:
            mail.logout()
            return "No hay emails en Yahoo."

        # Get last N messages
        recent_ids = msg_ids[-min(limit, 20):]
        recent_ids.reverse()  # newest first

        lines = []
        for msg_id in recent_ids:
            _, msg_data = mail.fetch(msg_id, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")
            if not msg_data or not msg_data[0]:
                continue

            raw_header = msg_data[0][1]
            msg = email.message_from_bytes(raw_header)

            from_addr = _decode_header_value(msg.get("From", "Desconocido"))
            subject = _decode_header_value(msg.get("Subject", "(sin asunto)"))
            date_str = msg.get("Date", "")

            # Check if unread
            flags = msg_data[0][0].decode() if msg_data[0][0] else ""
            is_unread = "\\Seen" not in flags
            marker = "🔵" if is_unread else "⚪"

            # Clean from address
            if "<" in from_addr:
                from_name = from_addr.split("<")[0].strip().strip('"')
                if not from_name:
                    from_name = from_addr.split("<")[1].split(">")[0]
            else:
                from_name = from_addr

            lines.append(
                f"{marker} **{from_name}**\n"
                f"   {subject}\n"
                f"   ID: {msg_id.decode()}"
            )

        mail.logout()

        header = f"📧 Yahoo — {len(lines)} emails:\n\n"
        return header + "\n\n".join(lines)

    except Exception as e:
        logger.exception("Failed to fetch Yahoo emails")
        return f"Error al leer Yahoo: {e}"


def read_email_yahoo(email_id: str) -> str:
    """Read the full content of a specific Yahoo email.

    Args:
        email_id: The email sequence number (from get_recent_emails_yahoo)
    """
    if not settings.yahoo_email or not settings.yahoo_app_password:
        return "Yahoo email no está configurado."

    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(settings.yahoo_email, settings.yahoo_app_password)
        mail.select("INBOX")

        _, msg_data = mail.fetch(email_id.encode(), "(RFC822)")
        if not msg_data or not msg_data[0]:
            mail.logout()
            return f"No encontré el email con ID {email_id}."

        raw = msg_data[0][1]
        msg = email.message_from_bytes(raw)

        from_addr = _decode_header_value(msg.get("From", "Desconocido"))
        to_addr = _decode_header_value(msg.get("To", ""))
        subject = _decode_header_value(msg.get("Subject", "(sin asunto)"))
        date_str = msg.get("Date", "")

        # Extract body
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    payload = part.get_payload(decode=True)
                    if payload:
                        charset = part.get_content_charset() or "utf-8"
                        body = payload.decode(charset, errors="replace")
                        break
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                charset = msg.get_content_charset() or "utf-8"
                body = payload.decode(charset, errors="replace")

        mail.logout()

        return (
            f"📧 Email completo (Yahoo):\n"
            f"De: {from_addr}\n"
            f"Para: {to_addr}\n"
            f"Asunto: {subject}\n"
            f"Fecha: {date_str}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"{body[:3000]}"
        )

    except Exception as e:
        logger.exception("Failed to read Yahoo email %s", email_id)
        return f"Error al leer email: {e}"


def send_email_yahoo(to: str, subject: str, body: str) -> str:
    """Send an email from Yahoo.

    Args:
        to: Recipient email address
        subject: Email subject
        body: Email body (plain text)
    """
    if not settings.yahoo_email or not settings.yahoo_app_password:
        return "Yahoo email no está configurado."

    try:
        message = MIMEMultipart()
        message["From"] = settings.yahoo_email
        message["To"] = to
        message["Subject"] = subject
        message.attach(MIMEText(body, "plain"))

        with smtplib.SMTP("smtp.mail.yahoo.com", 587) as server:
            server.starttls()
            server.login(settings.yahoo_email, settings.yahoo_app_password)
            server.send_message(message)

        logger.info("Yahoo email sent to %s: %s", to, subject)
        return f"✅ Email enviado desde Yahoo a {to}: {subject}"

    except Exception as e:
        logger.exception("Failed to send Yahoo email")
        return f"Error al enviar email: {e}"
