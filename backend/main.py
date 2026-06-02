import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

from backend.channels.esp32 import router as esp32_router
from backend.channels.vapi_webhook import router as vapi_router
from backend.channels.whatsapp import router as whatsapp_router
from backend.config import settings
from backend.services.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database tables
    if settings.database_url:
        try:
            from backend.services.database import init_db
            init_db()
            logger.info("Database initialized successfully")
        except Exception:
            logger.exception("Failed to initialize database — running without persistence")

    # Start scheduler
    start_scheduler()

    # Reload pending reminders from database
    if settings.database_url:
        try:
            from backend.agent.tools.reminders import reload_reminders_from_db
            reload_reminders_from_db()
        except Exception:
            logger.exception("Failed to reload reminders from database")

    # Initialize Notion databases
    if settings.notion_api_key:
        try:
            from backend.services.notion import init_notion
            init_notion()
        except Exception:
            logger.exception("Failed to initialize Notion — running without dashboard")

    # Schedule daily summary
    from apscheduler.triggers.cron import CronTrigger
    from backend.agent.tools.daily_summary import send_daily_summary
    from backend.services.scheduler import scheduler

    # Weekdays (Mon-Fri) at 08:00
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(day_of_week="mon-fri", hour=8, minute=0, timezone=settings.user_timezone),
        id="daily_summary_weekday",
        replace_existing=True,
    )
    # Weekends (Sat-Sun) at 10:00
    scheduler.add_job(
        send_daily_summary,
        trigger=CronTrigger(day_of_week="sat,sun", hour=10, minute=0, timezone=settings.user_timezone),
        id="daily_summary_weekend",
        replace_existing=True,
    )
    logger.info("Daily summary scheduled: Mon-Fri 08:00, Sat-Sun 10:00")

    # Schedule proactive event alerts (every 5 minutes)
    from apscheduler.triggers.interval import IntervalTrigger
    from backend.agent.tools.event_alerts import check_upcoming_events

    scheduler.add_job(
        check_upcoming_events,
        trigger=IntervalTrigger(minutes=5),
        id="event_alerts",
        replace_existing=True,
    )
    logger.info("Event alerts scheduled: every 5 minutes")

    # Schedule email event detection (every 30 minutes)
    from backend.agent.tools.email_events import check_emails_for_events

    scheduler.add_job(
        check_emails_for_events,
        trigger=IntervalTrigger(minutes=30),
        id="email_event_detection",
        replace_existing=True,
    )
    logger.info("Email event detection scheduled: every 30 minutes")

    # Configure Vapi phone number for inbound calls
    if settings.vapi_api_key and settings.vapi_phone_number_id:
        try:
            _configure_vapi_inbound()
        except Exception:
            logger.exception("Failed to configure Vapi inbound calls")

    yield
    stop_scheduler()


def _configure_vapi_inbound():
    """Configure the Vapi phone number to route inbound calls to our webhook."""
    import httpx

    # Get the Railway public URL
    railway_domain = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "")
    if not railway_domain:
        logger.warning("RAILWAY_PUBLIC_DOMAIN not set, skipping Vapi inbound config")
        return

    server_url = f"https://{railway_domain}/vapi/action"

    with httpx.Client(timeout=15) as client:
        # Remove assistantId so Vapi asks our server via assistant-request webhook.
        # Outbound calls still work because assistantId is passed per-call in the payload.
        response = client.patch(
            f"https://api.vapi.ai/phone-number/{settings.vapi_phone_number_id}",
            headers={
                "Authorization": f"Bearer {settings.vapi_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "assistantId": None,
                "serverUrl": server_url,
            },
        )

        if response.status_code == 200:
            logger.info("Vapi inbound calls configured → %s", server_url)
        else:
            logger.error("Failed to configure Vapi inbound: %s", response.text[:300])


app = FastAPI(title="Glitch Assistant", version="0.1.0", lifespan=lifespan)

app.include_router(whatsapp_router)
app.include_router(vapi_router)
app.include_router(esp32_router)


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve temporary audio files for Twilio to fetch."""
    # Prevent path traversal — only allow simple filenames
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return {"error": "invalid filename"}
    filepath = os.path.join("/tmp", filename)
    if not os.path.exists(filepath):
        return {"error": "not found"}
    return FileResponse(filepath, media_type="audio/mpeg")


@app.get("/media/{filename}")
async def serve_media(filename: str):
    """Serve temporary media files (images, etc.) for Twilio to fetch."""
    # Prevent path traversal — only allow simple filenames
    if "/" in filename or "\\" in filename or filename.startswith("."):
        return {"error": "invalid filename"}
    filepath = os.path.join("/tmp", filename)
    if not os.path.exists(filepath):
        return {"error": "not found"}
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    ext = os.path.splitext(filename)[1].lower()
    return FileResponse(filepath, media_type=media_types.get(ext, "application/octet-stream"))


@app.get("/")
async def root():
    return {"status": "alive", "name": "Glitch", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/test/daily-summary")
async def test_daily_summary():
    """Test endpoint to trigger daily summary manually."""
    from backend.agent.tools.daily_summary import send_daily_summary
    try:
        send_daily_summary()
        return {"status": "sent"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}


# --- Spotify OAuth endpoints ---

@app.get("/spotify/login")
async def spotify_login():
    """Redirect user to Spotify authorization page."""
    from backend.services.spotify_auth import get_auth_url
    return RedirectResponse(get_auth_url())


@app.get("/spotify/callback")
async def spotify_callback(code: str = Query(None), error: str = Query(None)):
    """Handle Spotify OAuth callback."""
    if error:
        return HTMLResponse(f"<h2>Error: {error}</h2><p>Spotify authorization was denied.</p>")

    if not code:
        return HTMLResponse("<h2>Error: no authorization code received.</h2>")

    try:
        from backend.services.spotify_auth import exchange_code
        exchange_code(code)
        return HTMLResponse(
            "<h1>Spotify conectado a Glitch!</h1>"
            "<p>Ya puedes controlar tu musica desde WhatsApp.</p>"
            "<p>Prueba enviando: <b>pon Despacito</b></p>"
        )
    except Exception as e:
        logger.exception("Spotify callback failed")
        return HTMLResponse(f"<h2>Error connecting Spotify</h2><p>{e}</p>")


@app.get("/spotify/status")
async def spotify_status():
    """Check Spotify connection status."""
    from backend.services.spotify_auth import is_authenticated
    return {"connected": is_authenticated()}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.port, reload=True)
