"""Shared Google OAuth authentication for Calendar + Gmail.

Centralizes the OAuth flow so both Calendar and Gmail use the same token.
When scopes change, delete token.json and re-authorize.
"""

import json
import logging
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from backend.config import settings

logger = logging.getLogger(__name__)

# All Google API scopes needed by Glitch
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CREDENTIALS_PATH = _PROJECT_ROOT / "google_credentials.json"
_TOKEN_PATH = _PROJECT_ROOT / "token.json"

from typing import Optional

_cached_creds: Optional[Credentials] = None


def get_google_credentials() -> Optional[Credentials]:
    """Get valid Google OAuth credentials (shared across Calendar + Gmail)."""
    global _cached_creds

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

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
            logger.exception("Failed to load Google token from env var")

    # Refresh if expired
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _TOKEN_PATH.write_text(creds.to_json())
        except Exception:
            logger.exception("Failed to refresh Google token")
            creds = None

    # If no valid creds, do OAuth flow (only works locally)
    if not creds or not creds.valid:
        if not _CREDENTIALS_PATH.exists():
            logger.error("No Google credentials found at %s", _CREDENTIALS_PATH)
            return None
        flow = InstalledAppFlow.from_client_secrets_file(str(_CREDENTIALS_PATH), SCOPES)
        creds = flow.run_local_server(port=0)
        _TOKEN_PATH.write_text(creds.to_json())

    _cached_creds = creds
    return creds
