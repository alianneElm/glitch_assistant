import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse

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

    yield
    stop_scheduler()


app = FastAPI(title="Glitch Assistant", version="0.1.0", lifespan=lifespan)

app.include_router(whatsapp_router)
app.include_router(vapi_router)


@app.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve temporary audio files for Twilio to fetch."""
    filepath = os.path.join("/tmp", filename)
    if not os.path.exists(filepath):
        return {"error": "not found"}
    return FileResponse(filepath, media_type="audio/mpeg")


@app.get("/media/{filename}")
async def serve_media(filename: str):
    """Serve temporary media files (images, etc.) for Twilio to fetch."""
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.port, reload=True)
