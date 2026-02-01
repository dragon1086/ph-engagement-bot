# PH Engagement Bot

Semi-automated Product Hunt community engagement system with human-in-the-loop approval via Telegram.

## Features

- **Smart Scraping**: Monitors AI/Developer Tools categories on Product Hunt
- **AI Comments**: Generates natural, helpful comments using Claude
- **Telegram Approval**: Review and approve comments before posting
- **Browser Automation**: Uses claude-in-chrome for actual engagement
- **Rate Limiting**: Configurable daily limits to stay safe

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    PH Engagement Bot                         │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  [Scheduler]──▶[Scraper]──▶[AI Generator]──▶[Telegram]      │
│       │            │              │              │           │
│       │       Firecrawl      Claude API    Approval UI      │
│       │                                         │           │
│       │                                         ▼           │
│       │                              ┌─────────────────┐    │
│       │                              │  User Decision  │    │
│       │                              │ ✅ ✏️ ❌        │    │
│       │                              └────────┬────────┘    │
│       │                                       │             │
│       │                                       ▼             │
│       │                              [Browser Action]       │
│       │                              (claude-in-chrome)     │
│       │                                       │             │
│       └───────────────────────────────────────┘             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:
- `TELEGRAM_BOT_TOKEN`: Your Telegram bot token
- `TELEGRAM_PH_CHAT_ID`: Chat ID for approval messages
- `ANTHROPIC_API_KEY`: Claude API key for comment generation

### 3. Login to Product Hunt

```bash
python -m ph_engagement login
```

This opens Chrome for manual login. Session cookies are saved automatically.

## Usage

### Manual Run

```bash
# Run once (scrape, generate, send approvals)
python -m ph_engagement run

# Check status
python -m ph_engagement status
```

### Scheduled Mode

```bash
# Start scheduler (runs at 9AM, 1PM, 5PM, 9PM KST)
python -m ph_engagement start

# Stop scheduler
python -m ph_engagement stop
```

### Telegram Commands

- `/ph_queue` - Show pending approvals
- `/ph_stats` - Show today's statistics
- `/ph_stop` - Emergency stop

## Configuration

Edit `src/ph_engagement/config.py`:

```python
DAILY_LIMIT = 10              # Max engagements per day
TARGET_CATEGORIES = [         # PH categories to monitor
    "developer-tools",
    "artificial-intelligence",
]
SCHEDULE_HOURS = [9, 13, 17, 21]  # Run times (KST)
```

## Safety Notes

- **Human-in-the-loop**: All actions require manual approval
- **Rate limiting**: Enforced daily limits prevent over-engagement
- **Natural delays**: Random delays between actions
- **Session management**: Manual login required, no stored passwords

## License

MIT
