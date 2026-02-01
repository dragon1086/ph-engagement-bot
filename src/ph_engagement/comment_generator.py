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
**Full Description**: {description}
**Category**: {category}

IMPORTANT: Read the description carefully before writing comments. Your comments should:
- Reference specific features mentioned in the description
- Ask questions that aren't already answered
- Show you actually understand what this product does

Guidelines:
- Be specific about THIS product's unique features
- Ask genuine questions (usage, roadmap, tech stack, pricing)
- Keep it conversational (2-4 sentences)
- Sound like a real developer/user, not a bot

AVOID:
- Generic praise ("Great job!", "Love this!")
- Questions that are already answered in the description
- Self-promotion
- Vague comments that could apply to any product

Generate {num} different comment options. For each comment, provide:
1. English comment (for actual submission)
2. Korean translation (한글 번역 - for reviewer understanding)
3. Korean product summary (상품 요약)

Output as JSON:
{{
  "product_summary_ko": "이 상품에 대한 간략한 한글 설명 (1-2문장, 주요 기능 포함)",
  "comments": [
    {{"comment": "English comment...", "comment_ko": "한글 번역...", "angle": "question|feedback|use_case"}}
  ]
}}
"""


class CommentGenerator:
    """Generates comments using Claude."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = "claude-sonnet-4-20250514"

    async def generate(self, post: PHPost, num: int = 3) -> tuple:
        """Generate comment variations for a post. Returns (product_summary_ko, comments)."""
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
                max_tokens=1500,
                messages=[{"role": "user", "content": prompt}]
            )

            content = response.content[0].text
            result = self._parse_response(content)

            if isinstance(result, dict):
                summary_ko = result.get("product_summary_ko", "")
                comments = result.get("comments", [])
            else:
                summary_ko = ""
                comments = result if result else []

            if not comments:
                comments = self._fallback_comments(post)

            logger.info(f"Generated {len(comments)} comments")
            return summary_ko, comments

        except Exception as e:
            logger.error(f"Error generating comments: {e}")
            return "", self._fallback_comments(post)

    def _parse_response(self, content: str):
        """Parse JSON from Claude response. Returns dict with product_summary_ko and comments."""
        try:
            # Try to parse full JSON object first
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                data = json.loads(match.group())
                if "comments" in data:
                    return data
                # If it's a single comment object, wrap it
                if "comment" in data:
                    return {"product_summary_ko": "", "comments": [data]}
        except json.JSONDecodeError:
            pass

        try:
            # Try array format
            match = re.search(r'\[[\s\S]*\]', content)
            if match:
                comments = json.loads(match.group())
                return {"product_summary_ko": "", "comments": comments}
        except json.JSONDecodeError:
            pass

        # Fallback: extract quoted strings
        comments = []
        for match in re.finditer(r'"comment":\s*"([^"]+)"', content):
            comments.append({"comment": match.group(1), "comment_ko": "", "angle": "general"})

        return {"product_summary_ko": "", "comments": comments[:config.COMMENT_VARIATIONS]}

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
