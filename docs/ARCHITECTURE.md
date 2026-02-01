# PH Engagement Bot - Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Mac Mini (Headless)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐     ┌──────────────┐     ┌──────────────┐    │
│  │  Scheduler   │────▶│  Scraper     │────▶│  Comment     │    │
│  │ (APScheduler)│     │ (Firecrawl)  │     │  Generator   │    │
│  └──────────────┘     └──────────────┘     │  (Claude)    │    │
│         │                    │              └──────┬───────┘    │
│         │                    │                     │            │
│         ▼                    ▼                     ▼            │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                     SQLite Storage                        │  │
│  │  engaged_posts | pending_approvals | daily_stats          │  │
│  └──────────────────────────────────────────────────────────┘  │
│         │                                          │            │
│         │            ┌──────────────┐              │            │
│         └───────────▶│   Telegram   │◀─────────────┘            │
│                      │   Handler    │                           │
│                      └──────┬───────┘                           │
│                             │                                   │
│                             ▼                                   │
│                      ┌──────────────┐                           │
│                      │   Executor   │                           │
│                      └──────┬───────┘                           │
│                             │                                   │
│                             ▼                                   │
│                      ┌──────────────┐                           │
│                      │  Browser     │                           │
│                      │  Driver      │                           │
│                      │ (Playwright) │                           │
│                      └──────────────┘                           │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      External Services                           │
├──────────────┬──────────────┬──────────────┬───────────────────┤
│  Firecrawl   │   Claude     │   Telegram   │   Product Hunt    │
│  (Scraping)  │   (AI)       │   (Control)  │   (Target)        │
└──────────────┴──────────────┴──────────────┴───────────────────┘
```

## Component Details

### 1. Scheduler (`scheduler.py`)
- APScheduler-based cron jobs
- Runs at 9, 13, 17, 21 KST
- Triggers engagement check cycle
- Session health checks every 30 minutes

### 2. Scraper (`scraper.py`)
- Firecrawl API for JS-rendered content
- Parses markdown output with regex
- Extracts: title, tagline, URL, category
- Fetches full product description for better comments

```python
# Key regex for parsing Firecrawl markdown
pattern = r'\[(\d+)\\\\?\.\s*([^\]]+)\]\((https://www\.producthunt\.com/products/([^)]+))\)'
```

### 3. Comment Generator (`comment_generator.py`)
- Claude API (claude-sonnet-4-20250514)
- Generates 3 comment variations per post
- Outputs: English comment, Korean translation, angle type
- Product summary in Korean for reviewer

```python
# Response format
{
  "product_summary_ko": "한글 요약",
  "comments": [
    {"comment": "English...", "comment_ko": "한글...", "angle": "question"}
  ]
}
```

### 4. Telegram Handler (`telegram_handler.py`)
- python-telegram-bot library
- Inline keyboard for approval flow
- Commands: /ph_login, /ph_run, /ph_execute, etc.
- Screenshot delivery for verification

### 5. Browser Driver (`browser_driver.py`)
- Playwright with persistent context
- playwright-stealth for bot detection evasion
- Actions: login, like, comment
- CAPTCHA detection and notification

```python
# Stealth configuration
stealth = Stealth(
    navigator_platform_override='MacIntel',
    navigator_vendor_override='Google Inc.',
)
```

### 6. Storage (`storage.py`)
- SQLite for persistence
- Tables: engaged_posts, pending_approvals, daily_stats
- Tracks: post status, comments, execution timestamps

### 7. Session Manager (`session_manager.py`)
- Login state machine
- States: LOGGED_OUT, LOGIN_PENDING, LOGGED_IN, EXPIRED
- Persists via browser profile

## Data Flow

### Engagement Check Flow
```
1. Scheduler triggers run_engagement_check()
2. Scraper fetches PH homepage via Firecrawl
3. Filter out already-engaged posts
4. For each new post:
   a. Fetch full description via get_post_details()
   b. Generate 3 AI comments via Claude
   c. Store in pending_approvals
   d. Send Telegram approval request
5. Wait for user approval/skip/edit
```

### Approval Flow
```
1. User clicks ✅ #1 (or #2/#3)
2. telegram_handler.on_approve_click()
3. Store approved comment in engaged_posts
4. Add to executor queue
5. Notify user: "Added to execution queue"
```

### Execution Flow
```
1. User runs /ph_execute
2. Get approved posts from storage
3. For each post:
   a. Navigate to post URL
   b. Check for CAPTCHA
   c. If CAPTCHA: notify user, pause
   d. Click upvote button
   e. Fill comment textarea
   f. Click submit
   g. Take screenshot
   h. Send result to Telegram
4. Update status to 'executed'
```

## Anti-Detection Strategy

### Why CAPTCHA Appears
- Cloudflare detects automated browsers
- Fresh browser profiles are suspicious
- navigator.webdriver property exposed

### Mitigation
1. **Persistent Profile**: `chrome_profile/` stores all state
2. **Stealth Mode**: Patches webdriver detection
3. **Human-like UA**: Real Chrome user agent
4. **Session Reuse**: Don't restart browser between actions

### If CAPTCHA Still Appears
1. User notified via Telegram with screenshot
2. User connects via VNC
3. User solves CAPTCHA manually
4. Retry /ph_execute

## Security Considerations

- API keys in `.env` (git-ignored)
- Browser profile contains login cookies (git-ignored)
- Telegram chat ID restricts access
- No automated credential handling

## Scalability Notes

- Current: Single Mac Mini, one PH account
- Daily limit: 10 engagements (self-imposed)
- Could scale with multiple accounts/machines
- Rate limiting built into sequential processing
