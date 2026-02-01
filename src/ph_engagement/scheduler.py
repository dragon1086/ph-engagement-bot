"""
Scheduler for PH Engagement Bot
"""
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from .config import config
from .storage import storage

logger = logging.getLogger(__name__)


class Scheduler:
    """Manages scheduled engagement tasks."""

    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.is_running = False
        self.engagement_fn: Optional[Callable[[], Awaitable[None]]] = None
        self.session_check_fn: Optional[Callable[[], Awaitable[bool]]] = None
        self.session_alert_fn: Optional[Callable[[str], Awaitable[None]]] = None

    def set_engagement_callback(self, fn: Callable[[], Awaitable[None]]):
        """Set the engagement check callback."""
        self.engagement_fn = fn

    def set_session_check_callback(self, fn: Callable[[], Awaitable[bool]]):
        """Set the session check callback. Returns True if session valid."""
        self.session_check_fn = fn

    def set_session_alert_callback(self, fn: Callable[[str], Awaitable[None]]):
        """Set callback to send session alerts via Telegram."""
        self.session_alert_fn = fn

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

        # Session health check every 2 hours
        self.scheduler.add_job(
            self._check_session,
            IntervalTrigger(hours=2),
            id="session_check",
            replace_existing=True
        )
        logger.info("Scheduled session check every 2 hours")

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

    async def _check_session(self):
        """Check if session is still valid and alert if not."""
        logger.info("Running scheduled session check")

        if not self.session_check_fn:
            logger.debug("No session check callback set")
            return

        try:
            is_valid = await self.session_check_fn()

            if not is_valid:
                logger.warning("Session expired or invalid")
                if self.session_alert_fn:
                    await self.session_alert_fn(
                        "⚠️ <b>Session Alert</b>\n\n"
                        "Your Product Hunt session has expired.\n\n"
                        "Use /ph_login to re-login before the next scheduled run."
                    )
            else:
                logger.info("Session check passed")

        except Exception as e:
            logger.error(f"Session check failed: {e}")
            if self.session_alert_fn:
                await self.session_alert_fn(
                    f"⚠️ <b>Session Check Error</b>\n\n{str(e)[:200]}"
                )

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
