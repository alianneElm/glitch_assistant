import logging
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.triggers.date import DateTrigger

from backend.config import settings

logger = logging.getLogger(__name__)

# Use memory store for now. Switch to Redis jobstore when Redis is added.
jobstores = {"default": MemoryJobStore()}

scheduler = AsyncIOScheduler(
    jobstores=jobstores,
    timezone=settings.user_timezone,
)


def start_scheduler():
    """Start the scheduler if not already running."""
    if not scheduler.running:
        scheduler.start()
        logger.info("Scheduler started (timezone: %s)", settings.user_timezone)


def stop_scheduler():
    """Shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        logger.info("Scheduler stopped")
