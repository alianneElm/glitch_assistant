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


@app.get("/")
async def root():
    return {"status": "alive", "name": "Glitch", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.port, reload=True)
