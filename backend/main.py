import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

from backend.channels.whatsapp import router as whatsapp_router
from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Glitch Assistant", version="0.1.0")

app.include_router(whatsapp_router)


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
