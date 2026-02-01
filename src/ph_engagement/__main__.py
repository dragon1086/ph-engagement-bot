"""
PH Engagement Bot - CLI Entry Point

Usage:
    python -m ph_engagement run      # Run once
    python -m ph_engagement start    # Start scheduler
    python -m ph_engagement status   # Show status
    python -m ph_engagement login    # Open browser for login
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime

from telegram.ext import Application

from .config import config
from .storage import storage
from .scraper import scraper, PHPost
from .comment_generator import generator
from .telegram_handler import TelegramHandler
from .scheduler import scheduler
from .browser_actions import browser

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
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

        # Setup Telegram
        self.telegram_app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
        self.telegram_handler = TelegramHandler(on_approve=self.on_post_approved)
        self.telegram_handler.setup(self.telegram_app)

        # Setup scheduler
        scheduler.set_engagement_callback(self.run_engagement_check)

        logger.info("Bot initialized")

    async def on_post_approved(self, post_id: str, action: str, comment: str):
        """Called when a post is approved via Telegram."""
        logger.info(f"Post approved: {post_id}, action: {action}")
        # Browser actions will be triggered separately
        # This is just for logging/notification

    async def run_engagement_check(self):
        """Run a single engagement check cycle."""
        logger.info("Starting engagement check...")

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

                # Generate comments
                comments = await generator.generate(post)

                # Store post
                storage.add_post(
                    post_id=post.post_id,
                    post_url=post.url,
                    post_title=post.title,
                    post_tagline=post.tagline,
                    category=post.category
                )

                # Send approval request
                await self.telegram_handler.send_approval(post, comments)

                # Small delay between posts
                await asyncio.sleep(2)

            except Exception as e:
                logger.error(f"Error processing post {post.post_id}: {e}")

        logger.info("Engagement check complete")

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

        print("\n📊 PH Engagement Bot Status")
        print("=" * 40)
        print(f"\n📅 Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"\n📈 Today's Stats:")
        print(f"   Posts found: {stats['posts_found']}")
        print(f"   Approved: {stats['approved']}")
        print(f"   Skipped: {stats['skipped']}")
        print(f"   Executed: {stats['executed']}")
        print(f"   Remaining: {config.DAILY_LIMIT - stats['executed']}")
        print(f"\n⏰ Scheduler:")
        print(f"   Running: {sched_status['running']}")
        print(f"   Next run: {sched_status['next_run'] or 'N/A'}")
        print(f"\n⚙️ Config:")
        print(f"   Daily limit: {config.DAILY_LIMIT}")
        print(f"   Schedule: {config.SCHEDULE_HOURS} KST")
        print()

    def show_login_instructions(self):
        """Show browser login instructions."""
        print("\n🔐 Product Hunt Login")
        print("=" * 40)
        print("""
To login to Product Hunt:

1. The bot will open Chrome with claude-in-chrome extension
2. Navigate to https://www.producthunt.com
3. Click "Log in" and complete authentication
4. Once logged in, the session will be saved

Use this command in Claude Code with claude-in-chrome:

```
mcp__claude-in-chrome__tabs_context_mcp(createIfEmpty=true)
mcp__claude-in-chrome__navigate(url="https://www.producthunt.com/login", tabId=TAB_ID)
```

After manual login, run:
```
python -m ph_engagement run
```
""")

    def show_browser_script(self, post_url: str, comment: str):
        """Show the MCP script for browser execution."""
        print("\n🖥️ Browser Execution Script")
        print("=" * 40)
        print(browser.get_full_script(post_url, comment))


def main():
    parser = argparse.ArgumentParser(
        description="PH Engagement Bot - Semi-automated Product Hunt engagement"
    )
    parser.add_argument(
        "command",
        choices=["run", "start", "status", "login", "script"],
        help="Command to execute"
    )
    parser.add_argument("--url", help="Post URL for script command")
    parser.add_argument("--comment", help="Comment for script command")

    args = parser.parse_args()
    bot = PHEngagementBot()

    if args.command == "run":
        asyncio.run(bot.run_once())
    elif args.command == "start":
        asyncio.run(bot.start_scheduler())
    elif args.command == "status":
        bot.show_status()
    elif args.command == "login":
        bot.show_login_instructions()
    elif args.command == "script":
        if not args.url or not args.comment:
            print("Error: --url and --comment required for script command")
            sys.exit(1)
        bot.show_browser_script(args.url, args.comment)


if __name__ == "__main__":
    main()
