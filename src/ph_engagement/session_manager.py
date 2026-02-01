"""
Session Manager for Product Hunt Login

Handles browser session lifecycle via claude-in-chrome MCP.
Designed for headless Mac Mini operation with Telegram control.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from .config import config

logger = logging.getLogger(__name__)


class SessionState(Enum):
    """Session states."""
    NOT_INITIALIZED = "not_initialized"
    LOGIN_PENDING = "login_pending"  # Browser open, waiting for manual login
    LOGGED_IN = "logged_in"
    EXPIRED = "expired"
    ERROR = "error"


@dataclass
class SessionInfo:
    """Session information."""
    state: SessionState
    tab_id: Optional[int] = None
    logged_in_at: Optional[datetime] = None
    last_verified: Optional[datetime] = None
    error_message: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "tab_id": self.tab_id,
            "logged_in_at": self.logged_in_at.isoformat() if self.logged_in_at else None,
            "last_verified": self.last_verified.isoformat() if self.last_verified else None,
            "error_message": self.error_message
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SessionInfo":
        return cls(
            state=SessionState(data.get("state", "not_initialized")),
            tab_id=data.get("tab_id"),
            logged_in_at=datetime.fromisoformat(data["logged_in_at"]) if data.get("logged_in_at") else None,
            last_verified=datetime.fromisoformat(data["last_verified"]) if data.get("last_verified") else None,
            error_message=data.get("error_message")
        )


class SessionManager:
    """
    Manages Product Hunt browser session.

    Usage with claude-in-chrome (executed by orchestrator):

    1. User: /ph_login
    2. Bot: Opens browser, navigates to PH, sends screenshot
    3. User: Manually logs in (via VNC/screen share to Mac Mini)
    4. User: /ph_login_done
    5. Bot: Verifies login, saves session state
    """

    def __init__(self):
        self.session_file = config.BASE_DIR / "session_state.json"
        self.session = self._load_session()

    def _load_session(self) -> SessionInfo:
        """Load session state from file."""
        if self.session_file.exists():
            try:
                with open(self.session_file) as f:
                    data = json.load(f)
                    return SessionInfo.from_dict(data)
            except Exception as e:
                logger.error(f"Failed to load session: {e}")
        return SessionInfo(state=SessionState.NOT_INITIALIZED)

    def _save_session(self):
        """Save session state to file."""
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.session_file, "w") as f:
                json.dump(self.session.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    def is_logged_in(self) -> bool:
        """Check if session is logged in."""
        return self.session.state == SessionState.LOGGED_IN

    def needs_login(self) -> bool:
        """Check if login is needed."""
        return self.session.state in (
            SessionState.NOT_INITIALIZED,
            SessionState.EXPIRED,
            SessionState.ERROR
        )

    def start_login(self, tab_id: int):
        """Mark login as started."""
        self.session = SessionInfo(
            state=SessionState.LOGIN_PENDING,
            tab_id=tab_id
        )
        self._save_session()
        logger.info(f"Login started on tab {tab_id}")

    def confirm_login(self):
        """Confirm login successful."""
        self.session.state = SessionState.LOGGED_IN
        self.session.logged_in_at = datetime.now()
        self.session.last_verified = datetime.now()
        self._save_session()
        logger.info("Login confirmed")

    def mark_expired(self):
        """Mark session as expired."""
        self.session.state = SessionState.EXPIRED
        self._save_session()
        logger.warning("Session marked as expired")

    def mark_error(self, message: str):
        """Mark session as error."""
        self.session.state = SessionState.ERROR
        self.session.error_message = message
        self._save_session()
        logger.error(f"Session error: {message}")

    def update_verified(self):
        """Update last verified timestamp."""
        self.session.last_verified = datetime.now()
        self._save_session()

    def get_status_message(self) -> str:
        """Get human-readable status message."""
        s = self.session

        if s.state == SessionState.NOT_INITIALIZED:
            return "🔴 Not logged in. Use /ph_login to start."

        elif s.state == SessionState.LOGIN_PENDING:
            return (
                "🟡 Login in progress...\n\n"
                f"Tab ID: {s.tab_id}\n\n"
                "Complete login in browser, then send /ph_login_done"
            )

        elif s.state == SessionState.LOGGED_IN:
            login_time = s.logged_in_at.strftime("%Y-%m-%d %H:%M") if s.logged_in_at else "Unknown"
            verify_time = s.last_verified.strftime("%H:%M") if s.last_verified else "Never"
            return (
                "🟢 Logged in\n\n"
                f"Since: {login_time}\n"
                f"Last verified: {verify_time}"
            )

        elif s.state == SessionState.EXPIRED:
            return "🔴 Session expired. Use /ph_login to re-login."

        elif s.state == SessionState.ERROR:
            return f"🔴 Session error: {s.error_message}\n\nUse /ph_login to retry."

        return "Unknown state"

    # MCP Script generators for claude-in-chrome

    def get_login_start_script(self) -> str:
        """Get MCP script to start login flow."""
        return """
# Start PH Login Flow

1. Get or create tab:
   result = mcp__claude-in-chrome__tabs_context_mcp(createIfEmpty=true)
   TAB_ID = result.tabs[0].id  # Save this tab ID

2. Navigate to Product Hunt login:
   mcp__claude-in-chrome__navigate(url="https://www.producthunt.com/login", tabId=TAB_ID)

3. Wait for page load:
   mcp__claude-in-chrome__computer(action="wait", duration=3, tabId=TAB_ID)

4. Take screenshot and send to Telegram:
   screenshot = mcp__claude-in-chrome__computer(action="screenshot", tabId=TAB_ID)
   # Send screenshot to user via Telegram

5. Wait for user to manually log in and confirm with /ph_login_done
"""

    def get_login_verify_script(self) -> str:
        """Get MCP script to verify login."""
        tab_id = self.session.tab_id or "TAB_ID"
        return f"""
# Verify PH Login

1. Navigate to PH homepage:
   mcp__claude-in-chrome__navigate(url="https://www.producthunt.com", tabId={tab_id})

2. Wait for page load:
   mcp__claude-in-chrome__computer(action="wait", duration=2, tabId={tab_id})

3. Look for user profile indicator:
   result = mcp__claude-in-chrome__find(query="user avatar or profile menu", tabId={tab_id})

4. Check result:
   if result.elements:
       # Logged in successfully
       return True
   else:
       # Not logged in
       return False

5. Take screenshot for confirmation:
   mcp__claude-in-chrome__computer(action="screenshot", tabId={tab_id})
"""

    def get_session_check_script(self) -> str:
        """Get MCP script to check if session is still valid."""
        tab_id = self.session.tab_id or "TAB_ID"
        return f"""
# Check PH Session

1. Navigate to PH:
   mcp__claude-in-chrome__navigate(url="https://www.producthunt.com", tabId={tab_id})

2. Wait:
   mcp__claude-in-chrome__computer(action="wait", duration=2, tabId={tab_id})

3. Find profile element:
   result = mcp__claude-in-chrome__find(query="user profile menu or notifications", tabId={tab_id})

4. Return logged in status:
   logged_in = len(result.elements) > 0

5. If not logged in, mark session expired
"""


# Singleton
session_manager = SessionManager()
