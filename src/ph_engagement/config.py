"""
Configuration for PH Engagement Bot
"""
import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Bot configuration settings."""

    # Daily engagement limits
    DAILY_LIMIT: int = 10

    # Target categories on Product Hunt
    TARGET_CATEGORIES: List[str] = [
        "developer-tools",
        "artificial-intelligence",
        "productivity",
        "open-source",
    ]

    # Schedule times (KST hours)
    SCHEDULE_HOURS: List[int] = [9, 13, 17, 21]

    # Telegram settings
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_PH_CHAT_ID", "")

    # Anthropic API
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Firecrawl API
    FIRECRAWL_API_KEY: str = os.getenv("FIRECRAWL_API_KEY", "")

    # Paths
    BASE_DIR: Path = Path(__file__).parent.parent.parent
    DB_PATH: Path = BASE_DIR / "ph_engagement.db"
    COOKIE_PATH: Path = BASE_DIR / "ph_cookies.json"
    LOG_PATH: Path = BASE_DIR / "logs" / "ph_engagement.log"

    # Product Hunt URLs
    PH_BASE_URL: str = "https://www.producthunt.com"

    # Comment generation settings
    COMMENT_MODEL: str = "claude-sonnet-4-5-20250929"
    COMMENT_VARIATIONS: int = 3
    MAX_COMMENT_LENGTH: int = 500
    MIN_COMMENT_LENGTH: int = 50

    # Safety settings
    MIN_DELAY_SECONDS: int = 30
    MAX_DELAY_SECONDS: int = 120
    APPROVAL_TIMEOUT_HOURS: int = 24

    @classmethod
    def validate(cls) -> bool:
        """Validate required configuration."""
        errors = []
        if not cls.TELEGRAM_BOT_TOKEN:
            errors.append("TELEGRAM_BOT_TOKEN not set")
        if not cls.TELEGRAM_CHAT_ID:
            errors.append("TELEGRAM_PH_CHAT_ID not set")
        if not cls.ANTHROPIC_API_KEY:
            errors.append("ANTHROPIC_API_KEY not set")

        for error in errors:
            print(f"Config Error: {error}")
        return len(errors) == 0


config = Config()
