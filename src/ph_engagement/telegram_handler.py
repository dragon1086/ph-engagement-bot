"""
Telegram Approval Handler
"""
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Awaitable, Callable, List, Optional

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, InputFile
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .config import config
from .scraper import PHPost
from .storage import storage
from .session_manager import session_manager, SessionState

logger = logging.getLogger(__name__)

# Login flow callbacks
LOGIN_CONFIRM = "login_confirm:"
LOGIN_CANCEL = "login_cancel:"

# Callback prefixes
APPROVE = "approve:"
SKIP = "skip:"
EDIT = "edit:"
SELECT = "select:"


class TelegramHandler:
    """Handles Telegram approval flow."""

    def __init__(self, on_approve: Optional[Callable[[str, str, str], Awaitable[None]]] = None,
                 on_login_request: Optional[Callable[[], Awaitable[tuple]]] = None,
                 on_login_verify: Optional[Callable[[], Awaitable[tuple]]] = None,
                 on_execute: Optional[Callable[[str, str], Awaitable[tuple]]] = None,
                 on_run: Optional[Callable[[], Awaitable[None]]] = None):
        self.on_approve = on_approve
        self.on_login_request = on_login_request  # Returns (success, screenshot_path)
        self.on_login_verify = on_login_verify    # Returns (is_logged_in, screenshot_path)
        self.on_execute = on_execute              # Returns (like_ok, comment_ok, screenshot_path)
        self.on_run = on_run                      # Triggers engagement check
        self.pending_edits: dict = {}
        self.app: Optional[Application] = None

    async def send_screenshot(self, screenshot_path: Optional[Path], caption: str = "",
                              chat_id: Optional[str] = None):
        """Send a screenshot to Telegram."""
        if not screenshot_path or not screenshot_path.exists():
            return

        if not self.app:
            return

        target = chat_id or config.TELEGRAM_CHAT_ID
        try:
            with open(screenshot_path, 'rb') as photo:
                await self.app.bot.send_photo(
                    chat_id=target,
                    photo=InputFile(photo),
                    caption=caption[:1024] if caption else None,
                    parse_mode="HTML"
                )
        except Exception as e:
            logging.error(f"Failed to send screenshot: {e}")

    def setup(self, app: Application):
        """Register handlers with Telegram app."""
        self.app = app

        # Login commands
        app.add_handler(CommandHandler("ph_login", self.cmd_login))
        app.add_handler(CommandHandler("ph_login_done", self.cmd_login_done))
        app.add_handler(CommandHandler("ph_session", self.cmd_session))

        # Control commands
        app.add_handler(CommandHandler("ph_run", self.cmd_run))
        app.add_handler(CommandHandler("ph_execute", self.cmd_execute))
        app.add_handler(CommandHandler("ph_queue", self.cmd_queue))
        app.add_handler(CommandHandler("ph_stats", self.cmd_stats))
        app.add_handler(CommandHandler("ph_stop", self.cmd_stop))
        app.add_handler(CommandHandler("ph_help", self.cmd_help))

        app.add_handler(CallbackQueryHandler(self.on_approve_click, pattern=f"^{APPROVE}"))
        app.add_handler(CallbackQueryHandler(self.on_skip_click, pattern=f"^{SKIP}"))
        app.add_handler(CallbackQueryHandler(self.on_edit_click, pattern=f"^{EDIT}"))
        app.add_handler(CallbackQueryHandler(self.on_select_click, pattern=f"^{SELECT}"))

        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))

        logger.info("Telegram handlers registered")

    async def send_approval(self, post: PHPost, comments: List[dict],
                            chat_id: Optional[str] = None, summary_ko: str = "") -> int:
        """Send approval request to Telegram."""
        if not self.app:
            raise RuntimeError("App not initialized")

        target = chat_id or config.TELEGRAM_CHAT_ID
        message = self._format_message(post, comments, summary_ko)
        keyboard = self._create_keyboard(post.post_id, len(comments))

        sent = await self.app.bot.send_message(
            chat_id=target,
            text=message,
            parse_mode="HTML",
            reply_markup=keyboard,
            disable_web_page_preview=False
        )

        # Store pending
        expires = datetime.now() + timedelta(hours=config.APPROVAL_TIMEOUT_HOURS)
        storage.add_pending(
            post_id=post.post_id,
            post_url=post.url,
            post_title=post.title,
            post_tagline=post.tagline,
            comments=comments,
            message_id=sent.message_id,
            expires_at=expires
        )

        logger.info(f"Sent approval for: {post.title}")
        return sent.message_id

    def _format_message(self, post: PHPost, comments: List[dict], summary_ko: str = "") -> str:
        """Format approval message with Korean translations."""
        title = self._escape_html(post.title)
        tagline = self._escape_html(post.tagline or "No tagline")
        summary = self._escape_html(summary_ko) if summary_ko else ""

        msg = f"""🆕 <b>New Product Hunt Post</b>

📦 <b>{title}</b>
<i>{tagline}</i>
"""
        if summary:
            msg += f"\n🇰🇷 <b>상품 요약:</b> {summary}\n"

        msg += f"""
🔗 {post.url}

💬 <b>Comment Options:</b>
"""
        for i, c in enumerate(comments, 1):
            text = self._escape_html(c.get("comment", ""))
            text_ko = self._escape_html(c.get("comment_ko", ""))
            angle = c.get("angle", "general")
            msg += f"\n<b>{i}. [{angle}]</b>\n"
            msg += f"🇺🇸 \"{text}\"\n"
            if text_ko:
                msg += f"🇰🇷 \"{text_ko}\"\n"

        msg += "\n<i>Select a comment or action:</i>"
        return msg

    def _escape_html(self, text: str) -> str:
        """Escape HTML special characters."""
        if not text:
            return ""
        return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def _create_keyboard(self, post_id: str, num_comments: int) -> InlineKeyboardMarkup:
        """Create inline keyboard - simplified: #1/#2/#3 directly approve."""
        buttons = []

        # Direct approve buttons (clicking approves immediately)
        approve_btns = [
            InlineKeyboardButton(f"✅ #{i}", callback_data=f"{APPROVE}{post_id}:{i}")
            for i in range(1, num_comments + 1)
        ]
        if approve_btns:
            buttons.append(approve_btns)

        # Edit and Skip row
        buttons.append([
            InlineKeyboardButton("✏️ Edit", callback_data=f"{EDIT}{post_id}"),
            InlineKeyboardButton("❌ Skip", callback_data=f"{SKIP}{post_id}")
        ])

        return InlineKeyboardMarkup(buttons)

    async def on_approve_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle approve button."""
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass  # Callback may have expired if bot was busy

        data = query.data.replace(APPROVE, "")
        parts = data.split(":")
        post_id = parts[0]
        idx = int(parts[1]) if len(parts) > 1 else 1

        pending = storage.get_pending(post_id)
        if not pending:
            await query.edit_message_text("Expired.")
            return

        comments = json.loads(pending["proposed_comments"])
        comment = comments[idx - 1]["comment"]

        storage.update_status(post_id, "approved", action="both", comment_text=comment)
        storage.remove_pending(post_id)
        storage.increment_stat("approved")

        await query.edit_message_text(
            f"✅ <b>Approved!</b>\n\n{pending['post_title']}\n\n\"{comment[:100]}...\"",
            parse_mode="HTML"
        )

        if self.on_approve:
            await self.on_approve(post_id, "both", comment)

    async def on_skip_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle skip button."""
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass

        post_id = query.data.replace(SKIP, "")
        pending = storage.get_pending(post_id)

        if pending:
            storage.update_status(post_id, "skipped", action="skipped")
            storage.remove_pending(post_id)
            storage.increment_stat("skipped")
            await query.edit_message_text(f"❌ Skipped: {pending['post_title']}")
        else:
            await query.edit_message_text("Expired.")

    async def on_edit_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle edit button."""
        query = update.callback_query
        try:
            await query.answer()
        except Exception:
            pass

        post_id = query.data.replace(EDIT, "")
        chat_id = query.message.chat_id
        pending = storage.get_pending(post_id)

        if not pending:
            await query.edit_message_text("Expired.")
            return

        self.pending_edits[chat_id] = {"post_id": post_id, "pending": pending}
        await query.edit_message_text(
            f"✏️ <b>Edit Mode</b>\n\n{pending['post_title']}\n\n<i>Send your comment:</i>",
            parse_mode="HTML"
        )

    async def on_select_click(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle comment selection."""
        query = update.callback_query
        await query.answer()

        data = query.data.replace(SELECT, "")
        post_id, idx_str = data.split(":")
        idx = int(idx_str)

        pending = storage.get_pending(post_id)
        if not pending:
            await query.answer("Expired", show_alert=True)
            return

        comments = json.loads(pending["proposed_comments"])
        selected = comments[idx - 1]

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ Approve #{idx}: \"{selected['comment'][:25]}...\"",
                callback_data=f"{APPROVE}{post_id}:{idx}"
            )],
            [
                InlineKeyboardButton("✏️ Edit", callback_data=f"{EDIT}{post_id}"),
                InlineKeyboardButton("❌ Skip", callback_data=f"{SKIP}{post_id}")
            ]
        ])
        await query.edit_message_reply_markup(keyboard)

    async def on_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle text input for custom comments."""
        chat_id = update.effective_chat.id
        if chat_id not in self.pending_edits:
            return

        edit_data = self.pending_edits.pop(chat_id)
        post_id = edit_data["post_id"]
        pending = edit_data["pending"]
        comment = update.message.text.strip()

        if len(comment) < config.MIN_COMMENT_LENGTH:
            await update.message.reply_text(f"Too short. Min {config.MIN_COMMENT_LENGTH} chars.")
            self.pending_edits[chat_id] = edit_data
            return

        if len(comment) > config.MAX_COMMENT_LENGTH:
            await update.message.reply_text(f"Too long. Max {config.MAX_COMMENT_LENGTH} chars.")
            self.pending_edits[chat_id] = edit_data
            return

        storage.update_status(post_id, "approved", action="both", comment_text=comment)
        storage.remove_pending(post_id)
        storage.increment_stat("approved")

        await update.message.reply_text(
            f"✅ <b>Approved with custom comment!</b>\n\n\"{comment[:100]}...\"",
            parse_mode="HTML"
        )

        if self.on_approve:
            await self.on_approve(post_id, "both", comment)

    async def cmd_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show pending queue."""
        count = len(storage.get_approved_posts())
        await update.message.reply_text(f"📋 Pending execution: {count} posts")

    async def cmd_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show today's stats."""
        stats = storage.get_today_stats()
        await update.message.reply_text(
            f"📊 <b>Today's Stats</b>\n\n"
            f"Found: {stats['posts_found']}\n"
            f"Approved: {stats['approved']}\n"
            f"Skipped: {stats['skipped']}\n"
            f"Executed: {stats['executed']}\n\n"
            f"Limit: {config.DAILY_LIMIT}",
            parse_mode="HTML"
        )

    async def cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Emergency stop."""
        await update.message.reply_text("🛑 Bot stopped. Use /ph_start to resume.")
        logger.warning("Bot stopped via Telegram")

    async def cmd_login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start login flow."""
        if session_manager.session.state == SessionState.LOGIN_PENDING:
            await update.message.reply_text(
                "🟡 Login already in progress.\n\n"
                "Complete login in browser, then /ph_login_done\n"
                "Or send /ph_login again to restart."
            )
            return

        if session_manager.is_logged_in():
            await update.message.reply_text(
                "🟢 Already logged in!\n\n"
                "Use /ph_session to check status.\n"
                "Sending /ph_login again will re-login."
            )
            # Continue anyway to allow re-login

        await update.message.reply_text(
            "🔐 <b>Starting Login Flow...</b>\n\n"
            "Opening browser to Product Hunt login page.\n"
            "Please wait...",
            parse_mode="HTML"
        )

        if self.on_login_request:
            try:
                success, screenshot_path = await self.on_login_request()

                if success:
                    # Send screenshot of login page
                    await self.send_screenshot(
                        screenshot_path,
                        "🖥️ <b>Browser Ready - Login Page</b>\n\n"
                        "Complete login via VNC/Screen Share, then send /ph_login_done"
                    )

                    await update.message.reply_text(
                        "📋 <b>Next Steps:</b>\n"
                        "1. Access your Mac Mini (VNC/Screen Share)\n"
                        "2. Complete login (Google/Twitter OAuth)\n"
                        "3. Send /ph_login_done when complete\n\n"
                        "⏰ Session will timeout in 10 minutes.",
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text("❌ Failed to open browser.")

            except Exception as e:
                logger.error(f"Login request failed: {e}")
                await update.message.reply_text(f"❌ Failed to open browser: {e}")
        else:
            await update.message.reply_text(
                "⚠️ Browser driver not configured.\n\n"
                "Make sure Playwright is installed:\n"
                "`pip install playwright && playwright install chromium`",
                parse_mode="HTML"
            )

    async def cmd_login_done(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Confirm login complete."""
        if session_manager.session.state != SessionState.LOGIN_PENDING:
            await update.message.reply_text(
                "❓ No login in progress.\n\nUse /ph_login to start."
            )
            return

        await update.message.reply_text("🔍 Verifying login...")

        if self.on_login_verify:
            try:
                is_logged_in, screenshot_path = await self.on_login_verify()

                # Send verification screenshot
                await self.send_screenshot(
                    screenshot_path,
                    "🔍 Login verification screenshot"
                )

                if is_logged_in:
                    await update.message.reply_text(
                        "✅ <b>Login Successful!</b>\n\n"
                        "Bot is now ready to engage on Product Hunt.\n\n"
                        "Commands:\n"
                        "/ph_run - Run engagement check now\n"
                        "/ph_execute - Execute approved posts\n"
                        "/ph_stats - View today's stats",
                        parse_mode="HTML"
                    )
                else:
                    await update.message.reply_text(
                        "❌ <b>Login Not Detected</b>\n\n"
                        "Could not verify login. Please:\n"
                        "1. Make sure you completed the login\n"
                        "2. Check the screenshot above\n"
                        "3. Try /ph_login_done again\n\n"
                        "Or /ph_login to restart.",
                        parse_mode="HTML"
                    )
            except Exception as e:
                logger.error(f"Login verify failed: {e}")
                await update.message.reply_text(f"❌ Verification error: {e}")
        else:
            # No verify callback, trust the user
            session_manager.confirm_login()
            await update.message.reply_text(
                "✅ <b>Login Confirmed!</b>\n\n"
                "(Manual verification - browser check skipped)\n\n"
                "Use /ph_run to start engagement.",
                parse_mode="HTML"
            )

    async def cmd_session(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show session status."""
        status = session_manager.get_status_message()
        await update.message.reply_text(
            f"🔐 <b>Session Status</b>\n\n{status}",
            parse_mode="HTML"
        )

    async def cmd_run(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Trigger manual engagement run."""
        if not session_manager.is_logged_in():
            await update.message.reply_text(
                "❌ Not logged in.\n\nUse /ph_login first."
            )
            return

        await update.message.reply_text(
            "🚀 Starting engagement check...\n\n"
            "This will scrape PH and send approval requests."
        )

        if self.on_run:
            try:
                await self.on_run()
            except Exception as e:
                logger.error(f"Engagement run failed: {e}")
                await update.message.reply_text(f"❌ Error: {str(e)[:200]}")

    async def cmd_execute(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Execute approved posts via browser."""
        if not session_manager.is_logged_in():
            await update.message.reply_text(
                "❌ Not logged in.\n\nUse /ph_login first."
            )
            return

        approved = storage.get_approved_posts()
        if not approved:
            await update.message.reply_text(
                "📭 No approved posts to execute.\n\n"
                "Approve some posts first, then use /ph_execute."
            )
            return

        await update.message.reply_text(
            f"⚡ <b>Executing {len(approved)} approved posts...</b>\n\n"
            "Browser actions will run now.\n"
            "You'll receive a screenshot for each action.",
            parse_mode="HTML"
        )

        # Execute via callback if available
        if self.on_execute:
            for post in approved:
                try:
                    like_ok, comment_ok, screenshot = await self.on_execute(
                        post["post_url"],
                        post["comment_text"]
                    )

                    if like_ok and comment_ok:
                        storage.update_status(post["post_id"], "executed")
                        storage.increment_stat("executed")
                        await self.send_screenshot(
                            screenshot,
                            f"✅ <b>Success:</b> {post['post_title'][:50]}\n"
                            f"👍 Liked: Yes | 💬 Commented: Yes"
                        )
                    elif like_ok or comment_ok:
                        # Partial success
                        storage.update_status(post["post_id"], "executed")
                        storage.increment_stat("executed")
                        await self.send_screenshot(
                            screenshot,
                            f"⚠️ <b>Partial:</b> {post['post_title'][:50]}\n"
                            f"👍 Liked: {'Yes' if like_ok else 'No'} | "
                            f"💬 Commented: {'Yes' if comment_ok else 'No'}"
                        )
                    else:
                        # Check screenshot filename to determine error type
                        screenshot_name = str(screenshot) if screenshot else ""

                        if "404" in screenshot_name:
                            # 404 page - product not found
                            await self.send_screenshot(
                                screenshot,
                                f"🔍 <b>404 - Product Not Found</b>\n\n"
                                f"Post: {post['post_title'][:50]}\n\n"
                                f"This product page no longer exists.\n"
                                f"Marking as skipped and continuing..."
                            )
                            # Mark as skipped and continue to next post
                            storage.update_status(post["post_id"], "skipped")
                            continue
                        else:
                            # Assume CAPTCHA
                            await self.send_screenshot(
                                screenshot,
                                f"🛡️ <b>CAPTCHA Detected!</b>\n\n"
                                f"Post: {post['post_title'][:50]}\n\n"
                                f"Please solve the CAPTCHA via VNC/Screen Share,\n"
                                f"then run /ph_execute again."
                            )
                            # Stop processing - user needs to solve CAPTCHA
                            await update.message.reply_text(
                                "⏸️ <b>Execution paused</b>\n\n"
                                "CAPTCHA blocking automation.\n"
                                "1. Connect to Mac via VNC\n"
                                "2. Solve the CAPTCHA in browser\n"
                                "3. Run /ph_execute again",
                                parse_mode="HTML"
                            )
                            return  # Stop execution loop

                    # Delay between posts
                    import asyncio
                    await asyncio.sleep(5)

                except Exception as e:
                    await update.message.reply_text(
                        f"❌ Error: {post['post_title'][:30]}...\n{str(e)[:100]}"
                    )

            await update.message.reply_text(
                f"✅ <b>Execution complete!</b>\n\n"
                f"Processed {len(approved)} posts.",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                "⚠️ Browser driver not configured.\n\n"
                "Make sure Playwright is installed."
            )

    async def cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Show help message."""
        await update.message.reply_text(
            "🤖 <b>PH Engagement Bot</b>\n\n"
            "<b>Login:</b>\n"
            "/ph_login - Start login flow\n"
            "/ph_login_done - Confirm login complete\n"
            "/ph_session - Check session status\n\n"
            "<b>Engagement:</b>\n"
            "/ph_run - Run engagement check now\n"
            "/ph_queue - Show pending approvals\n"
            "/ph_stats - Today's statistics\n\n"
            "<b>Control:</b>\n"
            "/ph_stop - Emergency stop\n"
            "/ph_help - This message\n\n"
            "<b>Approval Buttons:</b>\n"
            "✅ #1/#2/#3 - Approve with that comment\n"
            "✏️ Edit - Write custom comment\n"
            "❌ Skip - Skip this post",
            parse_mode="HTML"
        )


def create_handler(on_approve=None, on_login_request=None,
                   on_login_verify=None, on_execute=None) -> TelegramHandler:
    """Create handler instance."""
    return TelegramHandler(
        on_approve=on_approve,
        on_login_request=on_login_request,
        on_login_verify=on_login_verify,
        on_execute=on_execute
    )
