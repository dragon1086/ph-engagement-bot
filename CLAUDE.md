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

## Setup & Run (Mac Mini)

```bash
# 1. Setup (최초 1회)
cd /Users/rocky/Downloads/ph-engagement-bot
python3.12 -m venv venv
source venv/bin/activate
pip install -e .
pip install firecrawl-py playwright-stealth
playwright install chromium

# 2. .env 파일 설정 (TELEGRAM_BOT_TOKEN, ANTHROPIC_API_KEY 등)
```

### Daemon 시작/중지

```bash
# 시작 (백그라운드 데몬)
nohup /Users/rocky/Downloads/ph-engagement-bot/venv/bin/python -m ph_engagement start \
  >> /Users/rocky/Downloads/ph-engagement-bot/bot.log 2>&1 &

# 중지
pkill -f "ph_engagement start"

# 재시작 (중지 → SingletonLock 정리 → 시작)
pkill -f "ph_engagement start" && sleep 3 \
  && rm -f /Users/rocky/Downloads/ph-engagement-bot/chrome_profile/SingletonLock \
  && nohup /Users/rocky/Downloads/ph-engagement-bot/venv/bin/python -m ph_engagement start \
     >> /Users/rocky/Downloads/ph-engagement-bot/bot.log 2>&1 &
```

### CLI Commands

```bash
# venv 활성화 후 사용
source /Users/rocky/Downloads/ph-engagement-bot/venv/bin/activate

python -m ph_engagement start    # 스케줄러 데몬 시작
python -m ph_engagement run      # 1회 실행
python -m ph_engagement status   # 상태 확인
python -m ph_engagement execute  # 승인된 포스트 실행
```

### 로그 확인

```bash
# 메인 로그
tail -f /Users/rocky/Downloads/ph-engagement-bot/logs/ph_engagement.log

# 프로세스 확인
ps aux | grep ph_engagement | grep -v grep
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
| "Failed to open browser" / SingletonLock | `rm chrome_profile/SingletonLock` 후 재시작. 기존 Chrome 프로세스가 남아있으면 `pkill -f chrome_profile` |
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
