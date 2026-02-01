"""
Browser Actions for Product Hunt

Uses claude-in-chrome MCP for automated engagement.
This module defines the action interface; actual MCP calls
are made from the orchestrator.
"""
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, Optional

from .config import config

logger = logging.getLogger(__name__)


class BrowserSession:
    """Manages browser session state."""

    def __init__(self):
        self.cookie_path = config.COOKIE_PATH
        self.tab_id: Optional[int] = None
        self.is_logged_in = False

    def load_cookies(self) -> Optional[Dict[str, Any]]:
        """Load saved cookies."""
        if not self.cookie_path.exists():
            return None
        try:
            with open(self.cookie_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load cookies: {e}")
            return None

    def save_cookies(self, cookies: Dict[str, Any]):
        """Save cookies to file."""
        try:
            self.cookie_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.cookie_path, "w") as f:
                json.dump(cookies, f)
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")

    @staticmethod
    def random_delay() -> float:
        """Get random delay for human-like behavior."""
        return random.uniform(config.MIN_DELAY_SECONDS, config.MAX_DELAY_SECONDS)


class BrowserActions:
    """Product Hunt browser automation actions."""

    def __init__(self):
        self.session = BrowserSession()

    def get_like_script(self, post_url: str) -> str:
        """Get MCP script for liking a post."""
        return f"""
# Like Post: {post_url}

1. Navigate to post:
   mcp__claude-in-chrome__navigate(url="{post_url}", tabId=TAB_ID)

2. Wait for load:
   mcp__claude-in-chrome__computer(action="wait", duration=2, tabId=TAB_ID)

3. Find upvote button:
   mcp__claude-in-chrome__find(query="upvote button", tabId=TAB_ID)

4. Click upvote:
   mcp__claude-in-chrome__computer(action="left_click", ref=UPVOTE_REF, tabId=TAB_ID)

5. Verify:
   mcp__claude-in-chrome__computer(action="screenshot", tabId=TAB_ID)
"""

    def get_comment_script(self, post_url: str, comment: str) -> str:
        """Get MCP script for posting a comment."""
        # Escape quotes in comment
        safe_comment = comment.replace('"', '\\"')
        return f"""
# Comment on Post: {post_url}

1. Navigate to post:
   mcp__claude-in-chrome__navigate(url="{post_url}", tabId=TAB_ID)

2. Wait for load:
   mcp__claude-in-chrome__computer(action="wait", duration=2, tabId=TAB_ID)

3. Find comment input:
   mcp__claude-in-chrome__find(query="comment textarea or input", tabId=TAB_ID)

4. Click to focus:
   mcp__claude-in-chrome__computer(action="left_click", ref=COMMENT_REF, tabId=TAB_ID)

5. Type comment:
   mcp__claude-in-chrome__computer(action="type", text="{safe_comment}", tabId=TAB_ID)

6. Find submit button:
   mcp__claude-in-chrome__find(query="post comment button", tabId=TAB_ID)

7. Click submit:
   mcp__claude-in-chrome__computer(action="left_click", ref=SUBMIT_REF, tabId=TAB_ID)

8. Verify:
   mcp__claude-in-chrome__computer(action="screenshot", tabId=TAB_ID)
"""

    def get_full_script(self, post_url: str, comment: str) -> str:
        """Get MCP script for like + comment."""
        safe_comment = comment.replace('"', '\\"')
        return f"""
# Full Engagement: {post_url}

## Setup
1. Get tab context:
   mcp__claude-in-chrome__tabs_context_mcp(createIfEmpty=true)

2. Navigate to post:
   mcp__claude-in-chrome__navigate(url="{post_url}", tabId=TAB_ID)

3. Wait for load:
   mcp__claude-in-chrome__computer(action="wait", duration=3, tabId=TAB_ID)

## Like
4. Find upvote button:
   mcp__claude-in-chrome__find(query="upvote button", tabId=TAB_ID)

5. Click upvote:
   mcp__claude-in-chrome__computer(action="left_click", ref=UPVOTE_REF, tabId=TAB_ID)

6. Wait:
   mcp__claude-in-chrome__computer(action="wait", duration=2, tabId=TAB_ID)

## Comment
7. Find comment input:
   mcp__claude-in-chrome__find(query="comment textarea", tabId=TAB_ID)

8. Click to focus:
   mcp__claude-in-chrome__computer(action="left_click", ref=COMMENT_REF, tabId=TAB_ID)

9. Type comment:
   mcp__claude-in-chrome__computer(action="type", text="{safe_comment}", tabId=TAB_ID)

10. Find submit:
    mcp__claude-in-chrome__find(query="submit comment button", tabId=TAB_ID)

11. Click submit:
    mcp__claude-in-chrome__computer(action="left_click", ref=SUBMIT_REF, tabId=TAB_ID)

## Verify
12. Wait and screenshot:
    mcp__claude-in-chrome__computer(action="wait", duration=2, tabId=TAB_ID)
    mcp__claude-in-chrome__computer(action="screenshot", tabId=TAB_ID)
"""


browser = BrowserActions()
