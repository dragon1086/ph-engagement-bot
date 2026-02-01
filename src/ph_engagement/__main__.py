"""
PH Engagement Bot - CLI Entry Point

Usage:
    python -m ph_engagement run      # Run once
    python -m ph_engagement start    # Start scheduler daemon
    python -m ph_engagement status   # Show status
    python -m ph_engagement execute  # Execute approved posts
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime

from telegram.ext import Application

from .config import config
from .storage import storage
from .scraper import scraper
from .comment_generator import generator
from .telegram_handler import TelegramHandler
from .scheduler import scheduler
from .session_manager import session_manager
from .executor import executor
from .browser_driver import browser_driver

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(config.LOG_PATH, mode='a') if config.LOG_PATH.parent.exists() else logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class PHEngagementBot:
    """Main bot orchestrator."""

    def __init__(self):
        self.telegram_handler: TelegramHandler | None = None
        self.telegram_app: Application | None = None

    async def setup(self):
        """Initialize bot components."""
        if not config.validate():
            logger.error("Configuration invalid")
            sys.exit(1)

        # Ensure log directory exists
        config.LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Setup Telegram with all callbacks
        self.telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.telegram_handler = TelegramHandler(
            on_approve=self.on_post_approved,
            on_login_request=self.on_login_request,
            on_login_verify=self.on_login_verify,
            on_execute=self.on_execute_action,
            on_run=self.run_engagement_check
        )
        self.telegram_handler.setup(self.telegram_app)

        # Setup executor callbacks
        executor.set_notify_callback(self.notify_execution_result)

        # Setup scheduler with all callbacks
        scheduler.set_engagement_callback(self.run_engagement_check)
        scheduler.set_session_check_callback(self.check_session)
        scheduler.set_session_alert_callback(self.send_session_alert)

        logger.info("Bot initialized")

    async def check_session(self) -> bool:
        """Check if browser session is still valid."""
        try:
            return await browser_driver.check_session()
        except Exception as e:
            logger.error(f"Session check failed: {e}")
            return False

    async def send_session_alert(self, message: str):
        """Send session alert via Telegram."""
        if self.telegram_app:
            await self.telegram_app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="HTML"
            )

    # ============================================================
    # Telegram Callbacks
    # ============================================================

    async def on_post_approved(self, post_id: str, action: str, comment: str):
        """Called when a post is approved via Telegram."""
        logger.info(f"Post approved: {post_id}, action: {action}")

        # Get post details from storage
        approved_posts = storage.get_approved_posts()
        post = next((p for p in approved_posts if p["post_id"] == post_id), None)

        if post:
            # Add to executor queue
            executor.add_task(
                post_id=post_id,
                post_url=post["post_url"],
                comment=comment,
                action=action
            )

            # Notify user
            await self.telegram_app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text="📥 Added to execution queue.\n\nUse /ph_execute to run browser actions.",
                parse_mode="HTML"
            )
        else:
            logger.warning(f"Approved post not found in storage: {post_id}")

    async def on_login_request(self) -> tuple:
        """Called when user requests login. Returns (success, screenshot_path)."""
        logger.info("Login requested via Telegram")

        try:
            success, screenshot = await browser_driver.open_login_page()
            return success, screenshot
        except Exception as e:
            logger.error(f"Login request failed: {e}")
            return False, None

    async def on_login_verify(self) -> tuple:
        """Called to verify login status. Returns (is_logged_in, screenshot_path)."""
        logger.info("Verifying login status")

        try:
            is_logged_in, screenshot = await browser_driver.verify_login()
            return is_logged_in, screenshot
        except Exception as e:
            logger.error(f"Login verification failed: {e}")
            return False, None

    async def on_execute_action(self, post_url: str, comment: str) -> tuple:
        """Execute browser action. Returns (like_ok, comment_ok, screenshot_path)."""
        logger.info(f"Executing action for: {post_url}")

        try:
            like_ok, comment_ok, screenshot = await browser_driver.like_and_comment(
                post_url, comment
            )
            return like_ok, comment_ok, screenshot
        except Exception as e:
            logger.error(f"Execute action failed: {e}")
            return False, False, None

    async def notify_execution_result(self, post_id: str, success: bool, message: str):
        """Notify user of execution result via Telegram."""
        if self.telegram_app:
            await self.telegram_app.bot.send_message(
                chat_id=config.TELEGRAM_CHAT_ID,
                text=message,
                parse_mode="HTML"
            )

    # ============================================================
    # Core Operations
    # ============================================================

    async def run_engagement_check(self):
        """Run a single engagement check cycle."""
        logger.info("Starting engagement check...")

        # Check session
        if not session_manager.is_logged_in():
            logger.warning("Not logged in. Skipping engagement check.")
            if self.telegram_app:
                await self.telegram_app.bot.send_message(
                    chat_id=config.TELEGRAM_CHAT_ID,
                    text="⚠️ Engagement check skipped: Not logged in.\n\nUse /ph_login to login.",
                    parse_mode="HTML"
                )
            return

        # Check daily limit
        if not storage.can_engage_more():
            logger.info("Daily limit reached")
            return

        # Scrape new posts
        posts = await scraper.get_new_posts()
        if not posts:
            logger.info("No new posts found")
            return

        # Limit to remaining daily quota
        stats = storage.get_today_stats()
        remaining = config.DAILY_LIMIT - stats["executed"]
        posts = posts[:remaining]

        logger.info(f"Processing {len(posts)} posts")

        for post in posts:
            try:
                # Get post details if missing
                if not post.description:
                    details = await scraper.get_post_details(post.url)
                    if details:
                        post.description = details.get("description", "")
                        post.maker_name = details.get("maker_name", "")

                # Generate comments (returns tuple: summary_ko, comments)
                summary_ko, comments = await generator.generate(post)

                # Store post
                storage.add_post(
                    post_id=post.post_id,
                    post_url=post.url,
                    post_title=post.title,
                    post_tagline=post.tagline,
                    category=post.category
                )

                # Send approval request with Korean summary
                await self.telegram_handler.send_approval(post, comments, summary_ko=summary_ko)

                # Small delay between posts
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error processing post {post.post_id}: {e}")

        logger.info("Engagement check complete")

    async def execute_approved(self):
        """Execute all approved posts."""
        logger.info("Executing approved posts...")

        if not session_manager.is_logged_in():
            logger.error("Not logged in. Cannot execute.")
            print("❌ Not logged in. Use /ph_login first.")
            return

        await executor.process_queue()

        status = executor.get_queue_status()
        print(f"\n✅ Execution complete")
        print(f"   Success: {status['success']}")
        print(f"   Failed: {status['failed']}")
        print(f"   Pending: {status['pending']}")

    # ============================================================
    # CLI Entry Points
    # ============================================================

    async def run_once(self):
        """Run a single engagement check."""
        await self.setup()
        await self.run_engagement_check()
        await scraper.close()

    async def start_scheduler(self):
        """Start the bot with scheduler."""
        await self.setup()

        # Start Telegram polling
        await self.telegram_app.initialize()
        await self.telegram_app.start()
        await self.telegram_app.updater.start_polling()

        # Start scheduler
        scheduler.start()

        # Send startup message
        await self.telegram_app.bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID,
            text=(
                "🤖 <b>PH Engagement Bot Started</b>\n\n"
                f"Schedule: {config.SCHEDULE_HOURS} KST\n"
                f"Daily limit: {config.DAILY_LIMIT}\n\n"
                f"Session: {session_manager.session.state.value}\n\n"
                "Use /ph_help for commands."
            ),
            parse_mode="HTML"
        )

        logger.info("Bot running. Press Ctrl+C to stop.")

        # Keep running
        try:
            while True:
                await asyncio.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            scheduler.stop()
            await self.telegram_app.updater.stop()
            await self.telegram_app.stop()
            await self.telegram_app.shutdown()
            await scraper.close()

    def show_status(self):
        """Display current status."""
        stats = storage.get_today_stats()
        sched_status = scheduler.get_status()
        exec_status = executor.get_queue_status()

        print("\n📊 PH Engagement Bot Status")
        print("=" * 40)
        print(f"\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

        print(f"\n🔐 Session:")
        print(f"   {session_manager.get_status_message()}")

        print(f"\n📈 Today's Stats:")
        print(f"   Posts found: {stats['posts_found']}")
        print(f"   Approved: {stats['approved']}")
        print(f"   Skipped: {stats['skipped']}")
        print(f"   Executed: {stats['executed']}")
        print(f"   Remaining: {config.DAILY_LIMIT - stats['executed']}")

        print(f"\n📥 Execution Queue:")
        print(f"   Pending: {exec_status['pending']}")
        print(f"   In Progress: {exec_status['in_progress']}")
        print(f"   Retry: {exec_status['retry']}")

        print(f"\n⏰ Scheduler:")
        print(f"   Running: {sched_status['running']}")
        print(f"   Next run: {sched_status['next_run'] or 'N/A'}")

        print(f"\n⚙️ Config:")
        print(f"   Daily limit: {config.DAILY_LIMIT}")
        print(f"   Schedule: {config.SCHEDULE_HOURS} KST")
        print()


def main():
    parser = argparse.ArgumentParser(
        description="PH Engagement Bot - Semi-automated Product Hunt engagement"
    )
    parser.add_argument(
        "command",
        choices=["run", "start", "status", "execute"],
        help="Command to execute"
    )

    args = parser.parse_args()
    bot = PHEngagementBot()

    if args.command == "run":
        asyncio.run(bot.run_once())
    elif args.command == "start":
        asyncio.run(bot.start_scheduler())
    elif args.command == "status":
        bot.show_status()
    elif args.command == "execute":
        asyncio.run(bot.execute_approved())


if __name__ == "__main__":
    main()
