"""
Product Hunt Scraper
"""
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx
from bs4 import BeautifulSoup

from .config import config
from .storage import storage

logger = logging.getLogger(__name__)


@dataclass
class PHPost:
    """Product Hunt post data."""
    post_id: str
    title: str
    tagline: str
    url: str
    category: str
    maker_name: str = ""
    upvote_count: int = 0
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "post_id": self.post_id,
            "title": self.title,
            "tagline": self.tagline,
            "url": self.url,
            "category": self.category,
            "maker_name": self.maker_name,
            "upvote_count": self.upvote_count,
            "description": self.description
        }


class Scraper:
    """Product Hunt scraper."""

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/120.0.0.0 Safari/537.36"
            },
            follow_redirects=True,
            timeout=30.0
        )

    async def scrape_homepage(self) -> List[PHPost]:
        """Scrape Product Hunt homepage."""
        logger.info("Scraping PH homepage...")
        posts = []

        try:
            response = await self.client.get(config.PH_BASE_URL)
            response.raise_for_status()
            posts = self._parse_html(response.text, "homepage")
            logger.info(f"Found {len(posts)} posts on homepage")
        except Exception as e:
            logger.error(f"Error scraping homepage: {e}")

        return posts

    async def scrape_category(self, category: str) -> List[PHPost]:
        """Scrape specific category."""
        url = f"{config.PH_BASE_URL}/categories/{category}"
        logger.info(f"Scraping category: {category}")
        posts = []

        try:
            response = await self.client.get(url)
            response.raise_for_status()
            posts = self._parse_html(response.text, category)
            logger.info(f"Found {len(posts)} posts in {category}")
        except Exception as e:
            logger.error(f"Error scraping {category}: {e}")

        return posts

    async def get_new_posts(self) -> List[PHPost]:
        """Get new posts not yet engaged."""
        if not storage.can_engage_more():
            logger.info("Daily limit reached")
            return []

        # Scrape homepage
        posts = await self.scrape_homepage()

        # Filter already engaged
        new_posts = [p for p in posts if not storage.is_engaged(p.post_id)]

        storage.increment_stat("posts_found", len(new_posts))
        logger.info(f"Found {len(new_posts)} new posts")

        return new_posts

    async def get_post_details(self, post_url: str) -> Optional[Dict[str, str]]:
        """Get detailed info about a post."""
        try:
            response = await self.client.get(post_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract description from meta
            desc_meta = soup.find("meta", {"property": "og:description"})
            description = desc_meta["content"] if desc_meta else ""

            # Try to find maker name
            maker_elem = soup.find(attrs={"data-test": "maker-link"})
            maker_name = maker_elem.text.strip() if maker_elem else ""

            return {
                "description": description[:1000],
                "maker_name": maker_name
            }
        except Exception as e:
            logger.error(f"Error getting post details: {e}")
            return None

    def _parse_html(self, html: str, category: str) -> List[PHPost]:
        """Parse posts from HTML."""
        posts = []
        soup = BeautifulSoup(html, "html.parser")

        # Find post links - PH uses various selectors
        post_links = soup.find_all("a", href=re.compile(r"^/posts/"))

        seen_ids = set()
        for link in post_links[:30]:  # Limit to 30
            href = link.get("href", "")
            if not href.startswith("/posts/"):
                continue

            # Extract post ID from URL
            slug = href.replace("/posts/", "").split("?")[0].split("#")[0]
            if not slug or slug in seen_ids:
                continue
            seen_ids.add(slug)

            # Get title
            title = link.text.strip()
            if not title or len(title) < 3:
                continue

            # Find tagline (usually nearby)
            tagline = ""
            parent = link.parent
            if parent:
                tagline_elem = parent.find_next("p")
                if tagline_elem:
                    tagline = tagline_elem.text.strip()[:200]

            post = PHPost(
                post_id=slug,
                title=title,
                tagline=tagline,
                url=f"{config.PH_BASE_URL}/posts/{slug}",
                category=category
            )
            posts.append(post)

        return posts

    async def close(self):
        """Close HTTP client."""
        await self.client.aclose()


scraper = Scraper()
