"""
SQLite storage for PH engagement tracking
"""
import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .config import config


class Storage:
    """SQLite storage for engagement tracking."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or str(config.DB_PATH)
        self._init_db()

    def _init_db(self):
        """Initialize database schema."""
        with self._connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS engaged_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE,
                    post_url TEXT,
                    post_title TEXT,
                    post_tagline TEXT,
                    category TEXT,
                    comment_text TEXT,
                    action TEXT,
                    status TEXT DEFAULT 'pending',
                    approved_at TIMESTAMP,
                    executed_at TIMESTAMP,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS daily_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date DATE UNIQUE,
                    posts_found INTEGER DEFAULT 0,
                    approved INTEGER DEFAULT 0,
                    skipped INTEGER DEFAULT 0,
                    executed INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS pending_approvals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE,
                    post_url TEXT,
                    post_title TEXT,
                    post_tagline TEXT,
                    proposed_comments TEXT,
                    telegram_message_id INTEGER,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_post_id ON engaged_posts(post_id);
                CREATE INDEX IF NOT EXISTS idx_status ON engaged_posts(status);
            """)

    @contextmanager
    def _connection(self):
        """Database connection context manager."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def is_engaged(self, post_id: str) -> bool:
        """Check if post already engaged."""
        with self._connection() as conn:
            result = conn.execute(
                "SELECT 1 FROM engaged_posts WHERE post_id = ?", (post_id,)
            ).fetchone()
            return result is not None

    def add_post(self, post_id: str, post_url: str, post_title: str,
                 post_tagline: str = "", category: str = "") -> int:
        """Add new engaged post."""
        with self._connection() as conn:
            cursor = conn.execute(
                """INSERT OR REPLACE INTO engaged_posts
                   (post_id, post_url, post_title, post_tagline, category, status)
                   VALUES (?, ?, ?, ?, ?, 'pending')""",
                (post_id, post_url, post_title, post_tagline, category)
            )
            return cursor.lastrowid or 0

    def update_status(self, post_id: str, status: str,
                      action: Optional[str] = None,
                      comment_text: Optional[str] = None):
        """Update post status."""
        with self._connection() as conn:
            if action and comment_text:
                conn.execute(
                    """UPDATE engaged_posts
                       SET status = ?, action = ?, comment_text = ?, approved_at = ?
                       WHERE post_id = ?""",
                    (status, action, comment_text, datetime.now(), post_id)
                )
            elif status == "executed":
                conn.execute(
                    """UPDATE engaged_posts
                       SET status = ?, executed_at = ?
                       WHERE post_id = ?""",
                    (status, datetime.now(), post_id)
                )
            else:
                conn.execute(
                    "UPDATE engaged_posts SET status = ? WHERE post_id = ?",
                    (status, post_id)
                )

    def get_approved_posts(self) -> List[Dict[str, Any]]:
        """Get posts pending execution."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM engaged_posts WHERE status = 'approved' ORDER BY approved_at"
            ).fetchall()
            return [dict(row) for row in rows]

    # Pending approvals
    def add_pending(self, post_id: str, post_url: str, post_title: str,
                    post_tagline: str, comments: List[dict],
                    message_id: int, expires_at: datetime):
        """Add pending approval."""
        with self._connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO pending_approvals
                   (post_id, post_url, post_title, post_tagline,
                    proposed_comments, telegram_message_id, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (post_id, post_url, post_title, post_tagline,
                 json.dumps(comments), message_id, expires_at)
            )

    def get_pending(self, post_id: str) -> Optional[Dict[str, Any]]:
        """Get pending approval by post_id."""
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM pending_approvals WHERE post_id = ?", (post_id,)
            ).fetchone()
            return dict(row) if row else None

    def remove_pending(self, post_id: str):
        """Remove pending approval."""
        with self._connection() as conn:
            conn.execute("DELETE FROM pending_approvals WHERE post_id = ?", (post_id,))

    def get_expired(self) -> List[Dict[str, Any]]:
        """Get expired approvals."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM pending_approvals WHERE expires_at < ?",
                (datetime.now(),)
            ).fetchall()
            return [dict(row) for row in rows]

    # Daily stats
    def get_today_stats(self) -> Dict[str, int]:
        """Get today's statistics."""
        today = date.today()
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM daily_stats WHERE date = ?", (today,)
            ).fetchone()

            if row:
                return {
                    "posts_found": row["posts_found"],
                    "approved": row["approved"],
                    "skipped": row["skipped"],
                    "executed": row["executed"]
                }

            conn.execute("INSERT INTO daily_stats (date) VALUES (?)", (today,))
            return {"posts_found": 0, "approved": 0, "skipped": 0, "executed": 0}

    def increment_stat(self, stat: str, amount: int = 1):
        """Increment a daily stat."""
        today = date.today()
        with self._connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO daily_stats (date) VALUES (?)", (today,)
            )
            conn.execute(
                f"UPDATE daily_stats SET {stat} = {stat} + ? WHERE date = ?",
                (amount, today)
            )

    def can_engage_more(self) -> bool:
        """Check if under daily limit."""
        stats = self.get_today_stats()
        return stats["executed"] < config.DAILY_LIMIT


storage = Storage()
