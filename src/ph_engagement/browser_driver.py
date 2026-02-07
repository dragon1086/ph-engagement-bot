"""
Browser Driver - Playwright-based browser automation for Product Hunt

Uses Playwright instead of claude-in-chrome MCP for standalone operation.
This allows the bot to run completely independently on a headless Mac Mini.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright_stealth import Stealth

from .config import config
from .session_manager import session_manager, SessionState

logger = logging.getLogger(__name__)


class BrowserDriver:
    """
    Playwright-based browser automation for Product Hunt.

    Handles:
    - Login flow with cookie persistence
    - Like (upvote) posts
    - Post comments
    - Screenshot capture for Telegram
    """

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.screenshots_dir = config.BASE_DIR / "screenshots"
        self.screenshots_dir.mkdir(exist_ok=True)
        self._browser_ready = False  # Track if browser is ready for use
        self._headless = None  # Track current headless mode

    async def start(self, headless: bool = True, use_profile: bool = True):
        """Start the browser.

        Args:
            headless: Run without visible window
            use_profile: Use persistent Chrome profile (recommended for avoiding CAPTCHA)
        """
        if self._browser_ready and self.context:
            if self._headless == headless:
                logger.info("Reusing existing browser session")
                return
            else:
                logger.info(f"Restarting browser: headless={headless} (was {self._headless})")
                await self.stop(force=True)

        logger.info(f"Starting browser (headless={headless}, use_profile={use_profile})")
        self.playwright = await async_playwright().start()

        if use_profile:
            # Use persistent context with Chrome profile - much better for avoiding CAPTCHA
            user_data_dir = config.BASE_DIR / "chrome_profile"
            user_data_dir.mkdir(exist_ok=True)

            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=str(user_data_dir),
                headless=headless,
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            self.browser = None  # Not used with persistent context
        else:
            self.browser = await self.playwright.chromium.launch(
                headless=headless,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                ]
            )

            # Try to load existing cookies
            storage_state = None
            if config.COOKIE_PATH.exists():
                try:
                    storage_state = str(config.COOKIE_PATH)
                    logger.info("Loading saved cookies")
                except Exception as e:
                    logger.warning(f"Failed to load cookies: {e}")

            self.context = await self.browser.new_context(
                storage_state=storage_state,
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
            )
            self.page = await self.context.new_page()

        # Apply stealth to avoid bot detection
        stealth = Stealth(
            navigator_platform_override='MacIntel',
            navigator_vendor_override='Google Inc.',
        )
        await stealth.apply_stealth_async(self.page)
        self._browser_ready = True
        self._headless = headless
        logger.info("Browser started with stealth mode and persistent profile")

    async def stop(self, force: bool = False):
        """Stop the browser.

        Args:
            force: If True, fully close everything. If False, keep profile for reuse.
        """
        if not force and self._browser_ready:
            logger.info("Keeping browser session alive for reuse")
            return

        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

        self.page = None
        self.context = None
        self.browser = None
        self.playwright = None
        self._browser_ready = False
        self._headless = None
        logger.info("Browser stopped")

    async def save_cookies(self):
        """Save cookies to file."""
        if not self.context:
            return
        try:
            await self.context.storage_state(path=str(config.COOKIE_PATH))
            logger.info("Cookies saved")
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")

    async def take_screenshot(self, name: str = "screenshot") -> Optional[Path]:
        """Take a screenshot and return the file path."""
        if not self.page:
            return None

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = self.screenshots_dir / f"{name}_{timestamp}.png"

        try:
            await self.page.screenshot(path=str(filepath), full_page=False)
            logger.info(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.error(f"Failed to take screenshot: {e}")
            return None

    async def check_captcha(self) -> bool:
        """Check if CAPTCHA/human verification is present."""
        if not self.page:
            return False

        captcha_indicators = [
            'text="Verify you are human"',
            'text="verify you are human"',
            'iframe[title*="challenge"]',
            '#challenge-running',
            '.cf-turnstile',
            'iframe[src*="challenges.cloudflare.com"]',
        ]

        for selector in captcha_indicators:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    logger.warning(f"CAPTCHA detected: {selector}")
                    return True
            except Exception:
                continue

        return False

    async def check_404(self) -> bool:
        """Check if page is a 404 error page."""
        if not self.page:
            return False

        # Product Hunt 404 page indicators
        indicators_404 = [
            'text="We seem to have lost this page"',
            'text="404"',
            'text="Go to the homepage"',
        ]

        for selector in indicators_404:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    logger.warning(f"404 page detected: {selector}")
                    return True
            except Exception:
                continue

        return False

    async def wait_for_captcha_resolution(self, timeout: int = 120) -> bool:
        """
        Wait for user to solve CAPTCHA manually.
        Returns True if CAPTCHA resolved, False if timeout.
        """
        logger.info(f"Waiting up to {timeout}s for CAPTCHA resolution...")
        start_time = asyncio.get_event_loop().time()

        while (asyncio.get_event_loop().time() - start_time) < timeout:
            if not await self.check_captcha():
                logger.info("CAPTCHA resolved!")
                await asyncio.sleep(2)  # Wait for page to load after CAPTCHA
                return True
            await asyncio.sleep(3)  # Check every 3 seconds

        logger.warning("CAPTCHA resolution timeout")
        return False

    # ============================================================
    # Login Methods
    # ============================================================

    async def open_login_page(self) -> Tuple[bool, Optional[Path]]:
        """
        Navigate to PH login page.

        Returns:
            (success, screenshot_path)
        """
        await self.start(headless=False)  # Show browser for manual login

        try:
            await self.page.goto('https://www.producthunt.com/login', wait_until='networkidle')
            await asyncio.sleep(2)

            screenshot = await self.take_screenshot("login_page")
            session_manager.start_login(1)  # Mark login as pending

            return True, screenshot
        except Exception as e:
            logger.error(f"Failed to open login page: {e}")
            return False, None

    async def verify_login(self) -> Tuple[bool, Optional[Path]]:
        """
        Verify if user is logged in.

        Returns:
            (is_logged_in, screenshot_path)
        """
        if not self.page:
            await self.start()

        try:
            await self.page.goto('https://www.producthunt.com', wait_until='networkidle')
            await asyncio.sleep(2)

            # Look for indicators of being logged in
            # PH shows user avatar/profile when logged in
            logged_in = False

            # Check for various login indicators
            selectors = [
                '[data-test="user-menu"]',
                'img[alt*="avatar"]',
                '[href="/my/profile"]',
                'button:has-text("Post")',  # Post button only shows when logged in
            ]

            for selector in selectors:
                try:
                    element = await self.page.query_selector(selector)
                    if element:
                        logged_in = True
                        break
                except Exception:
                    continue

            screenshot = await self.take_screenshot("login_verify")

            if logged_in:
                await self.save_cookies()
                session_manager.confirm_login()
                logger.info("Login verified successfully")
            else:
                logger.warning("Login verification failed - not logged in")

            return logged_in, screenshot

        except Exception as e:
            logger.error(f"Failed to verify login: {e}")
            return False, None

    async def check_session(self) -> bool:
        """Quick check if session is still valid."""
        if not self.page:
            await self.start()

        try:
            await self.page.goto('https://www.producthunt.com', wait_until='domcontentloaded')

            # Quick check for login state
            user_menu = await self.page.query_selector('[data-test="user-menu"]')
            is_valid = user_menu is not None

            if is_valid:
                session_manager.update_verified()
            else:
                session_manager.mark_expired()

            return is_valid
        except Exception as e:
            logger.error(f"Session check failed: {e}")
            return False

    # ============================================================
    # Engagement Methods
    # ============================================================

    async def like_post(self, post_url: str) -> Tuple[bool, Optional[Path]]:
        """
        Like (upvote) a Product Hunt post.

        Returns:
            (success, screenshot_path)
        """
        if not self.page:
            await self.start()

        try:
            logger.info(f"Liking post: {post_url}")
            await self.page.goto(post_url, wait_until='networkidle')
            await asyncio.sleep(2)

            # Find and click upvote button
            # PH uses various selectors for the upvote button
            upvote_selectors = [
                '[data-test="vote-button"]',
                'button[aria-label*="Upvote"]',
                'button:has-text("UPVOTE")',
                '.vote-button',
            ]

            clicked = False
            for selector in upvote_selectors:
                try:
                    button = await self.page.query_selector(selector)
                    if button:
                        await button.click()
                        clicked = True
                        logger.info("Upvote button clicked")
                        break
                except Exception:
                    continue

            if not clicked:
                logger.warning("Could not find upvote button")
                screenshot = await self.take_screenshot("like_failed")
                return False, screenshot

            await asyncio.sleep(2)
            screenshot = await self.take_screenshot("like_success")
            return True, screenshot

        except Exception as e:
            logger.error(f"Failed to like post: {e}")
            screenshot = await self.take_screenshot("like_error")
            return False, screenshot

    async def post_comment(self, post_url: str, comment_text: str) -> Tuple[bool, Optional[Path]]:
        """
        Post a comment on a Product Hunt post.

        Product Hunt uses TipTap/ProseMirror rich text editor for comments.
        This is a contenteditable div, not a regular textarea.

        Note: Comments are only available on /posts/ URLs, not /products/ URLs.
        This method auto-converts /products/ to /posts/ format.

        Returns:
            (success, screenshot_path)
        """
        if not self.page:
            await self.start()

        # Convert /products/ URL to /posts/ URL (comments only work on /posts/)
        if '/products/' in post_url:
            post_url = post_url.replace('/products/', '/posts/')
            logger.info(f"Converted URL to posts format: {post_url}")

        try:
            logger.info(f"Posting comment on: {post_url}")

            # Navigate if not already on the page
            if self.page.url != post_url:
                await self.page.goto(post_url, wait_until='networkidle')
                await asyncio.sleep(2)

            # Take screenshot before attempting comment (for debugging)
            await self.take_screenshot("comment_before")

            # Find comment input - PH uses TipTap/ProseMirror (contenteditable div)
            # Order matters: most specific selectors first
            comment_selectors = [
                'div.tiptap.ProseMirror[contenteditable="true"]',  # PH's TipTap editor
                'div[role="textbox"][contenteditable="true"]',     # Accessible textbox
                'form div[contenteditable="true"]',                # Any contenteditable in form
                'div.ProseMirror[contenteditable="true"]',         # Generic ProseMirror
                'textarea[placeholder*="think"]',                   # Fallback: "What do you think?"
                'textarea[placeholder*="comment"]',
                '[data-test="comment-input"]',
            ]

            input_element = None
            used_selector = None
            for selector in comment_selectors:
                try:
                    input_element = await self.page.query_selector(selector)
                    if input_element:
                        used_selector = selector
                        logger.info(f"Found comment input with selector: {selector}")
                        break
                except Exception:
                    continue

            if not input_element:
                logger.warning("Could not find comment input")
                screenshot = await self.take_screenshot("comment_no_input")
                return False, screenshot

            # For contenteditable divs, we need to click first, then type
            # .fill() doesn't work on contenteditable - must use .type() or .press_sequentially()
            await input_element.click()
            await asyncio.sleep(0.5)

            # Check if it's a contenteditable element
            is_contenteditable = await input_element.get_attribute('contenteditable')

            if is_contenteditable == 'true':
                # For contenteditable, use type() which simulates keyboard input
                await input_element.type(comment_text, delay=20)  # Small delay for natural typing
                logger.info("Typed comment into contenteditable div")
            else:
                # For regular textarea/input, use fill()
                await input_element.fill(comment_text)
                logger.info("Filled comment into textarea")

            await asyncio.sleep(1)

            # Find and click submit button
            # Look specifically for button with text "Comment" inside the form
            submit_selectors = [
                'form button[type="submit"]:has-text("Comment")',  # Most specific
                'button:has-text("Comment")',                       # Any Comment button
                'form button[type="submit"]',                       # Any submit in form
                'button:has-text("Post")',
                '[data-test="submit-comment"]',
            ]

            submitted = False
            for selector in submit_selectors:
                try:
                    button = await self.page.query_selector(selector)
                    if button:
                        # Check button text to make sure it's the right one
                        button_text = await button.text_content()
                        if button_text and 'Comment' in button_text:
                            is_disabled = await button.get_attribute('disabled')
                            if not is_disabled:
                                await button.click()
                                submitted = True
                                logger.info(f"Comment submitted via selector: {selector}")
                                break
                except Exception as e:
                    logger.debug(f"Selector {selector} failed: {e}")
                    continue

            # If we didn't find a Comment-specific button, try any submit
            if not submitted:
                for selector in submit_selectors:
                    try:
                        button = await self.page.query_selector(selector)
                        if button:
                            is_disabled = await button.get_attribute('disabled')
                            if not is_disabled:
                                await button.click()
                                submitted = True
                                logger.info(f"Comment submitted via fallback selector: {selector}")
                                break
                    except Exception:
                        continue

            if not submitted:
                logger.warning("Could not find/click submit button")
                screenshot = await self.take_screenshot("comment_no_submit")
                return False, screenshot

            await asyncio.sleep(3)
            screenshot = await self.take_screenshot("comment_success")
            return True, screenshot

        except Exception as e:
            logger.error(f"Failed to post comment: {e}")
            screenshot = await self.take_screenshot("comment_error")
            return False, screenshot

    async def like_and_comment(self, post_url: str, comment_text: str) -> Tuple[bool, bool, Optional[Path]]:
        """
        Like and comment on a post.

        Returns:
            (like_success, comment_success, screenshot_path)
            If CAPTCHA detected, returns (False, False, screenshot) with CAPTCHA screenshot
        """
        import random

        if not self.page:
            # Use headless=False to avoid CAPTCHA detection
            await self.start(headless=False)

        # Convert /products/ URL to /posts/ URL (comments only work on /posts/)
        if '/products/' in post_url:
            post_url = post_url.replace('/products/', '/posts/')
            logger.info(f"Converted URL to posts format: {post_url}")

        # Warm up session by visiting homepage first (helps avoid CAPTCHA)
        try:
            logger.info("Warming up session with homepage visit...")
            await self.page.goto('https://www.producthunt.com', wait_until='domcontentloaded')
            await asyncio.sleep(random.uniform(2, 4))

            # Check for CAPTCHA on homepage
            if await self.check_captcha():
                logger.warning("CAPTCHA on homepage - waiting for resolution...")
                screenshot = await self.take_screenshot("captcha_homepage")
                # Wait up to 60 seconds for manual CAPTCHA resolution
                if not await self.wait_for_captcha_resolution(60):
                    return False, False, screenshot
        except Exception as e:
            logger.warning(f"Homepage warmup failed: {e}")

        # Navigate to post
        try:
            logger.info(f"Navigating to post: {post_url}")
            await self.page.goto(post_url, wait_until='networkidle')
            await asyncio.sleep(random.uniform(2, 4))
        except Exception as e:
            logger.error(f"Failed to navigate: {e}")
            screenshot = await self.take_screenshot("navigate_error")
            return False, False, screenshot

        # Check for CAPTCHA
        if await self.check_captcha():
            logger.warning("CAPTCHA detected! Manual intervention required.")
            screenshot = await self.take_screenshot("captcha_detected")
            # Return special result - caller should notify user
            return False, False, screenshot

        # Check for 404 page (product removed/invalid URL)
        if await self.check_404():
            logger.warning("404 page detected - product not found!")
            screenshot = await self.take_screenshot("404_not_found")
            return False, False, screenshot

        like_ok, _ = await self.like_post(post_url)

        # Random delay between actions
        await asyncio.sleep(3)

        comment_ok, screenshot = await self.post_comment(post_url, comment_text)

        return like_ok, comment_ok, screenshot


# Singleton
browser_driver = BrowserDriver()
