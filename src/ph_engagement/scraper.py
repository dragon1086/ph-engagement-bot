"""
Product Hunt Scraper - Firecrawl-based for JS-rendered content
"""
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from firecrawl import FirecrawlApp

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
    """Product Hunt scraper using Firecrawl."""

    def __init__(self):
        self.app = FirecrawlApp(api_key=config.FIRECRAWL_API_KEY) if config.FIRECRAWL_API_KEY else None

    async def scrape_homepage(self) -> List[PHPost]:
        """Scrape Product Hunt homepage."""
        logger.info("Scraping PH homepage with Firecrawl...")
        posts = []

        if not self.app:
            logger.error("Firecrawl API key not configured")
            return posts

        try:
            result = self.app.scrape(config.PH_BASE_URL, formats=['markdown', 'links'])

            markdown = result.markdown or ""
            posts = self._parse_markdown(markdown, "homepage")
            logger.info(f"Found {len(posts)} posts on homepage")
        except Exception as e:
            logger.error(f"Error scraping homepage: {e}")

        return posts

    async def scrape_category(self, category: str) -> List[PHPost]:
        """Scrape specific category."""
        url = f"{config.PH_BASE_URL}/topics/{category}"
        logger.info(f"Scraping category: {category}")
        posts = []

        if not self.app:
            logger.error("Firecrawl API key not configured")
            return posts

        try:
            result = self.app.scrape(url, formats=['markdown', 'links'])
            markdown = result.markdown or ""
            posts = self._parse_markdown(markdown, category)
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
        if not self.app:
            return None

        try:
            logger.info(f"Fetching product details: {post_url}")
            result = self.app.scrape(post_url, formats=['markdown'])
            markdown = result.markdown or ""

            # Extract meaningful description (skip image links, headers, navigation)
            lines = []
            for line in markdown.split('\n'):
                line = line.strip()
                # Skip empty, images, links, headers, navigation items
                if not line:
                    continue
                if line.startswith('!') or line.startswith('#') or line.startswith('['):
                    continue
                if line.startswith('-') or line.startswith('•'):
                    continue
                if len(line) < 20:  # Skip short lines (likely UI elements)
                    continue
                # This is likely content
                lines.append(line)
                if len(' '.join(lines)) > 500:
                    break

            description = ' '.join(lines)[:1000]
            logger.info(f"Got description ({len(description)} chars)")

            return {
                "description": description,
                "maker_name": ""
            }
        except Exception as e:
            logger.error(f"Error getting post details: {e}")
            return None

    def _parse_markdown(self, markdown: str, category: str) -> List[PHPost]:
        """Parse posts from Firecrawl markdown."""
        posts = []

        # Pattern: [1\. ProductName](url) - note the escaped backslash before period
        # Match: [number\. Title](https://www.producthunt.com/products/slug)
        pattern = r'\[(\d+)\\\\?\.\s*([^\]]+)\]\((https://www\.producthunt\.com/products/([^)]+))\)'

        matches = re.findall(pattern, markdown)
        seen_ids = set()

        for match in matches[:20]:  # Limit to 20 posts
            rank, title, url, slug = match

            if slug in seen_ids:
                continue
            seen_ids.add(slug)

            # Find tagline - text after the link, before next section
            tagline = ""
            link_pos = markdown.find(url)
            if link_pos > 0:
                after_link = markdown[link_pos + len(url):link_pos + len(url) + 200]
                # Get first line of text after the link
                lines = [l.strip() for l in after_link.split('\n') if l.strip() and not l.startswith('[') and not l.startswith('!')]
                if lines:
                    tagline = lines[0][:150]

            post = PHPost(
                post_id=slug,
                title=title.strip()[:100],
                tagline=tagline,
                url=url,
                category=category
            )
            posts.append(post)

        return posts

    async def close(self):
        """Cleanup (no-op for Firecrawl)."""
        pass


scraper = Scraper()
