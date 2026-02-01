"""
Scheduler for PH Engagement Bot
"""
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from .config import config
from .storage import storage

logger = logging.getLogger(__name__)


class Scheduler:
    """Manages scheduled engagement tasks."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.engagement_fn: Optional[Callable[[], Awaitable[None]]] = None

    def set_engagement_callback(self, fn: Callable[[], Awaitable[None]]):
        """Set the engagement check callback."""
        self.engagement_fn = fn

    def start(self):
        """Start scheduler with configured jobs."""
        if self.is_running:
            logger.warning("Scheduler already running")
            return

        # Schedule at configured hours (KST)
        for hour in config.SCHEDULE_HOURS:
            self.scheduler.add_job(
                self._run_engagement,
                CronTrigger(hour=hour, minute=0, timezone="Asia/Seoul"),
                id=f"engagement_{hour}",
                replace_existing=True
            )
            logger.info(f"Scheduled engagement at {hour}:00 KST")

        # Cleanup expired approvals hourly
        self.scheduler.add_job(
            self._cleanup_expired,
            CronTrigger(minute=0),
            id="cleanup",
            replace_existing=True
        )

        self.scheduler.start()
        self.is_running = True
        logger.info("Scheduler started")

    def stop(self):
        """Stop scheduler."""
        if self.is_running:
            self.scheduler.shutdown(wait=False)
            self.is_running = False
            logger.info("Scheduler stopped")

    def run_now(self):
        """Trigger immediate engagement check."""
        self.scheduler.add_job(
            self._run_engagement,
            id="immediate",
            replace_existing=True
        )

    async def _run_engagement(self):
        """Run engagement check."""
        logger.info(f"Running engagement check at {datetime.now()}")
        if self.engagement_fn:
            try:
                await self.engagement_fn()
            except Exception as e:
                logger.error(f"Engagement failed: {e}")

    async def _cleanup_expired(self):
        """Clean up expired approvals."""
        expired = storage.get_expired()
        for item in expired:
            storage.update_status(item["post_id"], "expired", action="skipped")
            storage.remove_pending(item["post_id"])
        if expired:
            logger.info(f"Cleaned {len(expired)} expired approvals")

    def get_status(self) -> dict:
        """Get scheduler status."""
        next_run = None
        if self.is_running:
            jobs = self.scheduler.get_jobs()
            times = [j.next_run_time for j in jobs if j.next_run_time]
            next_run = min(times).isoformat() if times else None

        return {
            "running": self.is_running,
            "next_run": next_run
        }


scheduler = Scheduler()
