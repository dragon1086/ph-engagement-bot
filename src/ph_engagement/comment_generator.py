"""
AI Comment Generator using Claude - Style-diversified generation
"""
import asyncio
import json
import logging
import random
import re
from typing import List

from anthropic import AsyncAnthropic

from .config import config
from .scraper import PHPost

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior software engineer who actively uses Product Hunt to discover dev tools and AI products. You browse PH daily and leave quick, honest reactions when something catches your eye.

Your commenting style:
- Casual and brief (1-2 sentences max)
- You type fast and don't overthink it
- You mention specific things you notice, not vague praise
- Sometimes you have a typo or skip punctuation — that's fine
- You never sound like a press release or marketing copy

You have NOT used this product before. You're seeing it for the first time on PH and reacting based on what you read."""

COMMENT_STYLES = {
    "curious": {
        "instruction": """React as someone who's genuinely curious about a specific technical detail or use case. Ask ONE concrete question about something not already answered in the description.

Examples of this style (DO NOT copy these, just match the vibe):
- "Does this work with monorepos? That's been a pain point for us"
- "Curious how this handles rate limiting under heavy load"
- "Any plans for a self-hosted option?"

Write exactly ONE short comment (1-2 sentences). Output ONLY the comment text, nothing else.""",
        "angle": "curious"
    },
    "skeptic": {
        "instruction": """React as someone who's interested but comparing this to what you already use. Reference a real competing tool or approach and ask what's different.

Examples of this style (DO NOT copy these, just match the vibe):
- "I've been doing this with a bash script + cron, what's the advantage here?"
- "How does this compare to just using Raycast for this?"
- "Looks cool but I tried something similar with Cursor and it worked ok. What's the edge here"

Write exactly ONE short comment (1-2 sentences). Output ONLY the comment text, nothing else.""",
        "angle": "skeptic"
    },
    "excited_user": {
        "instruction": """React as someone who immediately sees how this fits a real problem you have. Mention a specific scenario where you'd use this.

Examples of this style (DO NOT copy these, just match the vibe):
- "Been looking for exactly this for my side project's CI pipeline"
- "This would save me so much time on client onboarding, bookmarked"
- "oh nice, I was literally building something like this last weekend"

Write exactly ONE short comment (1-2 sentences). Output ONLY the comment text, nothing else.""",
        "angle": "excited_user"
    }
}

ANTI_PATTERNS = """
CRITICAL — your comment will be flagged and deleted if you use ANY of these patterns:
- Starting with "I love how..." / "Great to see..." / "This is really impressive..." / "What a great..."
- Starting with "As a [role], I..."
- The structure: [compliment] + "My question is..." or [compliment] + "I'm curious about..."
- Generic phrases: "game changer", "next level", "revolutionize", "streamline your workflow"
- More than one exclamation mark
- Any emoji
- Ending with "Keep up the great work!" or similar encouragement
- Mentioning "the team" or "the developers" generically
- Phrases like "I can see this being useful for..." (too hedging/generic)
"""


class CommentGenerator:
    """Generates comments using Claude with style-diversified prompts."""

    def __init__(self):
        self.client = AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self.model = config.COMMENT_MODEL

    async def generate(self, post: PHPost, num: int = 3) -> tuple:
        """Generate comment variations for a post. Returns (product_summary_ko, comments).

        Each comment is generated with a separate API call using a different style.
        """
        logger.info(f"Generating {num} comments for: {post.title}")

        styles = list(COMMENT_STYLES.keys())
        if num < len(styles):
            styles = random.sample(styles, num)

        # Generate summary first
        summary_ko = await self._generate_summary(post)

        # Generate each comment with a separate API call (sequential to avoid rate limits)
        comments = []
        for style_name in styles[:num]:
            try:
                comment = await self._generate_single(post, style_name)
                if comment:
                    comments.append(comment)
            except Exception as e:
                logger.error(f"Error generating {style_name} comment: {e}")

            # Small delay between API calls
            if len(comments) < num:
                await asyncio.sleep(1)

        if not comments:
            comments = self._fallback_comments(post)

        logger.info(f"Generated {len(comments)} comments")
        return summary_ko, comments

    async def _generate_summary(self, post: PHPost) -> str:
        """Generate Korean product summary."""
        prompt = f"""제품 정보:
- 이름: {post.title}
- 태그라인: {post.tagline or 'N/A'}
- 설명: {post.description or 'N/A'}
- 카테고리: {post.category}

이 제품에 대해 한글로 1-2문장으로 간략히 요약해줘. 주요 기능과 타겟 사용자를 포함해.
요약만 출력해."""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logger.error(f"Error generating summary: {e}")
            return ""

    async def _generate_single(self, post: PHPost, style_name: str) -> dict | None:
        """Generate a single comment in the given style."""
        style = COMMENT_STYLES[style_name]

        maker_info = ""
        if post.maker_name:
            maker_info = f"\n**Maker**: {post.maker_name}"

        user_prompt = f"""Product page you just opened:

**{post.title}** — {post.tagline or 'N/A'}{maker_info}
**Category**: {post.category}

**Description**:
{post.description or 'No description available.'}

---

{style['instruction']}
{ANTI_PATTERNS}"""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}]
            )

            comment_text = response.content[0].text.strip()
            # Clean up any quotes wrapping the response
            comment_text = comment_text.strip('"\'')
            # Remove any leading "Comment:" or similar prefixes
            comment_text = re.sub(r'^(Comment|Here\'s my comment|My comment):\s*', '', comment_text, flags=re.IGNORECASE)
            comment_text = comment_text.strip('"\'')

            if not comment_text or len(comment_text) < 15:
                return None

            # Generate Korean translation
            comment_ko = await self._translate_to_korean(comment_text)

            return {
                "comment": comment_text,
                "comment_ko": comment_ko,
                "angle": style["angle"]
            }

        except Exception as e:
            logger.error(f"Error in _generate_single ({style_name}): {e}")
            return None

    async def _translate_to_korean(self, comment: str) -> str:
        """Translate comment to Korean for reviewer."""
        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=200,
                messages=[{"role": "user", "content": f"다음 영어 댓글을 자연스러운 한국어로 번역해줘. 번역만 출력해.\n\n\"{comment}\""}]
            )
            return response.content[0].text.strip().strip('"\'')
        except Exception:
            return ""

    def _parse_response(self, content: str):
        """Parse JSON from Claude response. Returns dict with product_summary_ko and comments."""
        try:
            match = re.search(r'\{[\s\S]*\}', content)
            if match:
                data = json.loads(match.group())
                if "comments" in data:
                    return data
                if "comment" in data:
                    return {"product_summary_ko": "", "comments": [data]}
        except json.JSONDecodeError:
            pass

        try:
            match = re.search(r'\[[\s\S]*\]', content)
            if match:
                comments = json.loads(match.group())
                return {"product_summary_ko": "", "comments": comments}
        except json.JSONDecodeError:
            pass

        comments = []
        for match in re.finditer(r'"comment":\s*"([^"]+)"', content):
            comments.append({"comment": match.group(1), "comment_ko": "", "angle": "general"})

        return {"product_summary_ko": "", "comments": comments[:config.COMMENT_VARIATIONS]}

    def _fallback_comments(self, post: PHPost) -> List[dict]:
        """Fallback comments if AI generation fails entirely."""
        title = post.title
        fallbacks = [
            {
                "comment": f"Does {title} have a free tier or is it paid only?",
                "comment_ko": "",
                "angle": "curious"
            },
            {
                "comment": f"What stack is {title} built on?",
                "comment_ko": "",
                "angle": "skeptic"
            },
            {
                "comment": f"Bookmarked, want to try this for my next project",
                "comment_ko": "",
                "angle": "excited_user"
            }
        ]
        return fallbacks

    async def regenerate(self, post: PHPost, previous: str, feedback: str) -> str:
        """Regenerate comment based on user feedback."""
        prompt = f"""Product: {post.title}
Tagline: {post.tagline}

Previous comment: "{previous}"
Feedback: {feedback}

Write one improved comment (1-2 sentences). Be casual and specific. Output just the comment text."""

        try:
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=150,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip().strip('"\'')
        except Exception as e:
            logger.error(f"Error regenerating: {e}")
            return previous


generator = CommentGenerator()
