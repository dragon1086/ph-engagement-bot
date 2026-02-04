# CLAUDE.md - PH Engagement Bot

> AI-assisted Product Hunt engagement system with human-in-the-loop approval

## Quick Overview

```yaml
Stack: Python 3.9+, Playwright, Firecrawl, Claude API, Telegram Bot
Purpose: Semi-automated Product Hunt engagement (likes + comments)
Control: Telegram bot for approval workflow
Execution: Headless Mac Mini with browser automation
```

## Project Structure

```
ph-engagement-bot/
├── src/ph_engagement/
│   ├── __main__.py          # CLI entry point, orchestrator
│   ├── scraper.py           # Firecrawl-based PH scraper
│   ├── comment_generator.py # Claude AI comment generation
│   ├── telegram_handler.py  # Telegram approval UI
│   ├── browser_driver.py    # Playwright automation + stealth
│   ├── executor.py          # Execution queue management
│   ├── scheduler.py         # APScheduler for scheduled runs
│   ├── session_manager.py   # Login session state
│   ├── storage.py           # SQLite persistence
│   └── config.py            # Configuration
├── chrome_profile/          # Persistent browser profile (git-ignored)
├── screenshots/             # Execution screenshots (git-ignored)
└── ph_engagement.db         # SQLite database (git-ignored)
```

## Key Commands

```bash
# Start the bot (daemon mode with Telegram)
python -m ph_engagement start

# Single run (no scheduler)
python -m ph_engagement run

# Check status
python -m ph_engagement status

# Execute approved posts
python -m ph_engagement execute
```

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/ph_login` | Start login flow (opens browser) |
| `/ph_login_done` | Confirm login complete |
| `/ph_session` | Check session status |
| `/ph_run` | Trigger engagement check now |
| `/ph_execute` | Execute approved posts |
| `/ph_queue` | Show pending approvals |
| `/ph_stats` | Today's statistics |
| `/ph_help` | Show help |

## Approval Flow

```
Scrape PH → Generate AI Comments → Telegram Approval Request
                                          ↓
                                   ✅ #1/#2/#3 (approve)
                                   ✏️ Edit (custom comment)
                                   ❌ Skip
                                          ↓
                               /ph_execute → Browser Action
```

## Configuration (.env)

```bash
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_PH_CHAT_ID=your_chat_id
ANTHROPIC_API_KEY=your_api_key
FIRECRAWL_API_KEY=your_firecrawl_key
```

## Key Technical Details

### Firecrawl for Scraping
Product Hunt is a JavaScript SPA - httpx/BeautifulSoup won't work. Firecrawl renders JS and returns markdown.

### Playwright Stealth
Uses `playwright-stealth` + persistent Chrome profile to avoid Cloudflare CAPTCHA:
- `chrome_profile/` stores login state, cookies, browsing history
- Stealth patches `navigator.webdriver` and browser fingerprint

### Comment Generation
Claude generates 3 comment options with:
- English comment (for posting)
- Korean translation (for reviewer understanding)
- Product summary in Korean

### Session Management
- Login via `/ph_login` opens browser for manual OAuth
- Verify with `/ph_login_done`
- Session persists in `chrome_profile/`

## Daily Limits & Schedule

```python
DAILY_LIMIT = 10  # Max engagements per day
SCHEDULE_HOURS = [9, 13, 17, 21]  # KST
TARGET_CATEGORIES = ["developer-tools", "artificial-intelligence", "productivity", "open-source"]
```

## Database Schema

```sql
-- Tracked posts
engaged_posts (post_id, post_url, status, comment_text, ...)
-- status: pending, approved, skipped, executed

-- Pending approvals (waiting for Telegram response)
pending_approvals (post_id, proposed_comments, expires_at, ...)

-- Daily statistics
daily_stats (date, posts_found, approved, skipped, executed)
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Found 0 new posts" | All posts already in DB. Clear `ph_engagement.db` or wait for new launches |
| CAPTCHA detected | Clear `chrome_profile/`, re-login via `/ph_login` |
| Telegram conflict | Kill all instances: `pkill -9 -f ph_engagement` |
| Comment too generic | Check that `get_post_details()` is fetching full description |
| Comment not posting | Check URL format - comments only work on `/posts/` URLs |

## Development Notes

- **Comment Editor**: PH uses TipTap/ProseMirror (contenteditable div), not textarea
  - Selector: `div.tiptap.ProseMirror[contenteditable="true"]`
  - Use `.type()` instead of `.fill()` for contenteditable elements

- **URL Format**: Scraper returns `/products/` URLs, but comments only work on `/posts/`
  - Browser driver auto-converts: `/products/slug` → `/posts/slug`

- **CAPTCHA avoidance**:
  - Homepage warmup visit before navigating to posts
  - Persistent Chrome profile maintains session trust
  - `headless=False` reduces CAPTCHA triggers
  - If persistent issues, clear `chrome_profile/` and re-login

- **Scraper regex**: `r'\[(\d+)\\\\?\.\s*([^\]]+)\]\((https://www\.producthunt\.com/products/([^)]+))\)'`
  - Handles escaped backslash in Firecrawl markdown: `[1\. Product]`

- **Rate limits**: Sequential comment generation (not parallel) to avoid API limits.
