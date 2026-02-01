"""
AI Comment Generator using Claude
"""
import json
import logging
import re
from typing import List

from anthropic import AsyncAnthropic

from .config import config
from .scraper import PHPost

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """Generate genuine, helpful Product Hunt comments for this product.

**Product**: {title}
**Tagline**: {tagline}
**Description**: {description}
**Category**: {category}

Guidelines:
- Be specific about THIS product's features
- Ask genuine questions (usage, roadmap, tech stack)
- Keep it conversational (2-4 sentences)
- Sound like a real developer, not a bot

AVOID:
- Generic praise ("Great job!", "Love this!")
- Questions answered in the description
- Self-promotion

Generate {num} different comment options. Output as JSON array:
[{{"comment": "...", "angle": "question|feedback|use_case"}}]
"""


class CommentGenerator:
    """Generates comments using Claude."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"

    async def generate(self, post: PHPost, num: int = 3) -> List[dict]:
        """Generate comment variations for a post."""
        logger.info(f"Generating {num} comments for: {post.title}")

        prompt = PROMPT_TEMPLATE.format(
            title=post.title,
            tagline=post.tagline or "N/A",
            description=post.description or "N/A",
            category=post.category,
            num=num
        )

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text
            comments = self._parse_response(content)

            if not comments:
                comments = self._fallback_comments(post)

            logger.info(f"Generated {len(comments)} comments")
            return comments

        except Exception as e:
            logger.error(f"Error generating comments: {e}")
            return self._fallback_comments(post)

    def _parse_response(self, content: str) -> List[dict]:
        """Parse JSON from Claude response."""
        try:
            match = re.search(r'\[[\s\S]*\]', content)
            if match:
                return json.loads(match.group())
        except json.JSONDecodeError:
            pass

        # Fallback: extract quoted strings
        comments = []
        for match in re.finditer(r'"comment":\s*"([^"]+)"', content):
            comments.append({"comment": match.group(1), "angle": "general"})

        return comments[:config.COMMENT_VARIATIONS]

    def _fallback_comments(self, post: PHPost) -> List[dict]:
        """Fallback comments if AI fails."""
        return [
            {
                "comment": f"Interesting approach with {post.title}! "
                           "What was the biggest technical challenge during development?",
                "angle": "question"
            },
            {
                "comment": f"The {post.category} space is competitive. "
                           f"What makes {post.title} stand out from existing solutions?",
                "angle": "differentiation"
            },
            {
                "comment": "I can see this fitting into my workflow. "
                           "Are there integrations planned with other developer tools?",
                "angle": "use_case"
            }
        ]

    async def regenerate(self, post: PHPost, previous: str, feedback: str) -> str:
        """Regenerate comment based on user feedback."""
        prompt = f"""Improve this Product Hunt comment based on feedback.

Product: {post.title}
Tagline: {post.tagline}

Previous comment: "{previous}"
Feedback: {feedback}

Write one improved comment (2-4 sentences). Output just the comment text."""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip().strip('"\'')
        except Exception as e:
            logger.error(f"Error regenerating: {e}")
            return previous


generator = CommentGenerator()
