import logging

from fastapi import FastAPI

from backend.channels.whatsapp import router as whatsapp_router
from backend.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(title="Glitch Assistant", version="0.1.0")

app.include_router(whatsapp_router)


@app.get("/")
async def root():
    return {"status": "alive", "name": "Glitch", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("backend.main:app", host="0.0.0.0", port=settings.port, reload=True)
