"""Spotify OAuth2 authentication for Glitch.

Handles the Authorization Code Flow:
1. User visits /spotify/login -> redirected to Spotify
2. Spotify redirects back to /spotify/callback with auth code
3. We exchange code for access + refresh tokens
4. Tokens are stored in the SPOTIFY_TOKEN_JSON env var (Railway) or .env (local)
5. Access token auto-refreshes when expired
"""

import json
import logging
import time
from typing import Optional
from urllib.parse import urlencode

import httpx

from backend.config import settings

logger = logging.getLogger(__name__)

# Spotify OAuth endpoints
AUTH_URL = "https://accounts.spotify.com/authorize"
TOKEN_URL = "https://accounts.spotify.com/api/token"

# Scopes needed for playback control + search + user info
SCOPES = [
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-read-recently-played",
    "user-top-read",
    "playlist-read-private",
    "playlist-read-collaborative",
]

# In-memory token cache
_token_data: Optional[dict] = None


def get_auth_url() -> str:
    """Generate the Spotify authorization URL."""
    params = {
        "client_id": settings.spotify_client_id,
        "response_type": "code",
        "redirect_uri": settings.spotify_redirect_uri,
        "scope": " ".join(SCOPES),
        "show_dialog": "true",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


def exchange_code(code: str) -> dict:
    """Exchange authorization code for access + refresh tokens."""
    global _token_data

    with httpx.Client(timeout=15) as client:
        resp = client.post(
            TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.spotify_redirect_uri,
                "client_id": settings.spotify_client_id,
                "client_secret": settings.spotify_client_secret,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _token_data = {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_at": time.time() + data["expires_in"] - 60,  # 60s buffer
    }

    # Persist token JSON
    _save_token(_token_data)
    logger.info("Spotify OAuth completed successfully")
    return _token_data


def _save_token(token: dict):
    """Save token to settings (env var / .env file)."""
    token_json = json.dumps(token)
    settings.spotify_token_json = token_json

    # Also write to .env for local dev
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    if env_path.exists():
        content = env_path.read_text()
        if "SPOTIFY_TOKEN_JSON=" in content:
            lines = content.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("SPOTIFY_TOKEN_JSON="):
                    new_lines.append(f"SPOTIFY_TOKEN_JSON={token_json}")
                else:
                    new_lines.append(line)
            env_path.write_text("\n".join(new_lines))
        else:
            with open(env_path, "a") as f:
                f.write(f"\nSPOTIFY_TOKEN_JSON={token_json}")
        logger.info("Spotify token saved to .env")


def _load_token() -> Optional[dict]:
    """Load token from env var or settings."""
    global _token_data

    if _token_data:
        return _token_data

    if settings.spotify_token_json:
        try:
            _token_data = json.loads(settings.spotify_token_json)
            return _token_data
        except json.JSONDecodeError:
            logger.error("Invalid SPOTIFY_TOKEN_JSON")

    return None


def _refresh_token() -> Optional[str]:
    """Refresh the access token using the refresh token."""
    global _token_data

    token = _load_token()
    if not token or "refresh_token" not in token:
        logger.warning("No refresh token available")
        return None

    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(
                TOKEN_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": token["refresh_token"],
                    "client_id": settings.spotify_client_id,
                    "client_secret": settings.spotify_client_secret,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        _token_data = {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token", token["refresh_token"]),
            "expires_at": time.time() + data["expires_in"] - 60,
        }

        _save_token(_token_data)
        logger.info("Spotify token refreshed")
        return _token_data["access_token"]

    except Exception:
        logger.exception("Failed to refresh Spotify token")
        return None


def get_access_token() -> Optional[str]:
    """Get a valid access token, refreshing if needed."""
    token = _load_token()
    if not token:
        return None

    # Check if expired
    if time.time() >= token.get("expires_at", 0):
        return _refresh_token()

    return token["access_token"]


def is_authenticated() -> bool:
    """Check if we have valid Spotify credentials."""
    return get_access_token() is not None
