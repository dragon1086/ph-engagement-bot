"""
Executor - Bridges approved posts to browser actions

This module connects Telegram approvals to actual browser execution.
Designed to work with claude-in-chrome MCP via Claude Code.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional, Callable, Awaitable

from .config import config
from .storage import storage
from .session_manager import session_manager, SessionState

logger = logging.getLogger(__name__)


class ExecutionStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    SUCCESS = "success"
    FAILED = "failed"
    RETRY = "retry"


@dataclass
class ExecutionTask:
    """Represents a pending browser execution task."""
    post_id: str
    post_url: str
    comment: str
    action: str  # 'like', 'comment', 'both'
    status: ExecutionStatus = ExecutionStatus.PENDING
    retry_count: int = 0
    last_error: Optional[str] = None
    created_at: datetime = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = datetime.now()


class Executor:
    """
    Manages execution of approved engagement tasks.

    The actual browser automation is performed by Claude Code with
    claude-in-chrome MCP. This class:
    1. Queues approved tasks
    2. Validates session before execution
    3. Generates MCP scripts for execution
    4. Tracks success/failure
    5. Handles retries
    """

    MAX_RETRIES = 3
    RETRY_DELAY_SECONDS = 60

    def __init__(self):
        self.queue: list[ExecutionTask] = []
        self.is_running = False
        # Callback to trigger actual MCP execution (set by orchestrator)
        self.execute_callback: Optional[Callable[[str, str, str], Awaitable[bool]]] = None
        # Callback to notify Telegram of execution result
        self.notify_callback: Optional[Callable[[str, bool, str], Awaitable[None]]] = None

    def set_execute_callback(self, callback: Callable[[str, str, str], Awaitable[bool]]):
        """Set callback for MCP execution. Returns True if successful."""
        self.execute_callback = callback

    def set_notify_callback(self, callback: Callable[[str, bool, str], Awaitable[None]]):
        """Set callback to notify user of execution result."""
        self.notify_callback = callback

    def add_task(self, post_id: str, post_url: str, comment: str, action: str = "both"):
        """Add a new execution task to the queue."""
        task = ExecutionTask(
            post_id=post_id,
            post_url=post_url,
            comment=comment,
            action=action
        )
        self.queue.append(task)
        logger.info(f"Added execution task: {post_id}")

    def get_pending_count(self) -> int:
        """Get count of pending tasks."""
        return len([t for t in self.queue if t.status == ExecutionStatus.PENDING])

    async def process_queue(self):
        """Process all pending tasks in the queue."""
        if self.is_running:
            logger.warning("Executor already running")
            return

        self.is_running = True
        logger.info(f"Processing {len(self.queue)} tasks")

        try:
            # Also load approved posts from storage
            approved = storage.get_approved_posts()
            for post in approved:
                if not any(t.post_id == post["post_id"] for t in self.queue):
                    self.add_task(
                        post_id=post["post_id"],
                        post_url=post["post_url"],
                        comment=post["comment_text"],
                        action=post["action"]
                    )

            for task in self.queue:
                if task.status not in (ExecutionStatus.PENDING, ExecutionStatus.RETRY):
                    continue

                await self._execute_task(task)

                # Delay between tasks for rate limiting
                await asyncio.sleep(config.MIN_DELAY_SECONDS)

        finally:
            self.is_running = False

        # Clean up completed tasks
        self.queue = [t for t in self.queue if t.status not in (
            ExecutionStatus.SUCCESS, ExecutionStatus.FAILED
        )]

    async def _execute_task(self, task: ExecutionTask):
        """Execute a single task."""
        logger.info(f"Executing task: {task.post_id}")
        task.status = ExecutionStatus.IN_PROGRESS

        # Check session first
        if not session_manager.is_logged_in():
            task.status = ExecutionStatus.FAILED
            task.last_error = "Not logged in"
            logger.error(f"Task {task.post_id} failed: not logged in")

            if self.notify_callback:
                await self.notify_callback(
                    task.post_id,
                    False,
                    "❌ Execution failed: Not logged in. Use /ph_login first."
                )
            return

        # Execute via callback
        if self.execute_callback:
            try:
                success = await self.execute_callback(
                    task.post_url,
                    task.comment,
                    task.action
                )

                if success:
                    task.status = ExecutionStatus.SUCCESS
                    storage.update_status(task.post_id, "executed")
                    storage.increment_stat("executed")
                    logger.info(f"Task {task.post_id} executed successfully")

                    if self.notify_callback:
                        await self.notify_callback(
                            task.post_id,
                            True,
                            f"✅ Executed: Liked and commented on post"
                        )
                else:
                    await self._handle_failure(task, "Execution returned false")

            except Exception as e:
                await self._handle_failure(task, str(e))
        else:
            # No callback - just generate script and mark as pending manual execution
            logger.warning(f"No execute_callback set. Task {task.post_id} requires manual execution.")
            task.status = ExecutionStatus.PENDING
            task.last_error = "Manual execution required"

    async def _handle_failure(self, task: ExecutionTask, error: str):
        """Handle task failure with retry logic."""
        task.retry_count += 1
        task.last_error = error

        if task.retry_count < self.MAX_RETRIES:
            task.status = ExecutionStatus.RETRY
            logger.warning(f"Task {task.post_id} failed, will retry ({task.retry_count}/{self.MAX_RETRIES}): {error}")

            # Schedule retry
            await asyncio.sleep(self.RETRY_DELAY_SECONDS)

        else:
            task.status = ExecutionStatus.FAILED
            storage.update_status(task.post_id, "failed")
            storage.increment_stat("failed")
            logger.error(f"Task {task.post_id} failed permanently: {error}")

            if self.notify_callback:
                await self.notify_callback(
                    task.post_id,
                    False,
                    f"❌ Execution failed after {self.MAX_RETRIES} retries: {error}"
                )

    def get_mcp_script(self, task: ExecutionTask) -> str:
        """Get MCP script for manual execution."""
        from .browser_actions import browser
        return browser.get_full_script(task.post_url, task.comment)

    def get_queue_status(self) -> dict:
        """Get queue status summary."""
        return {
            "total": len(self.queue),
            "pending": len([t for t in self.queue if t.status == ExecutionStatus.PENDING]),
            "in_progress": len([t for t in self.queue if t.status == ExecutionStatus.IN_PROGRESS]),
            "retry": len([t for t in self.queue if t.status == ExecutionStatus.RETRY]),
            "success": len([t for t in self.queue if t.status == ExecutionStatus.SUCCESS]),
            "failed": len([t for t in self.queue if t.status == ExecutionStatus.FAILED]),
        }


# Singleton
executor = Executor()
