# PH Engagement Bot

Semi-automated Product Hunt community engagement system with human-in-the-loop approval via Telegram.

## Features

- **Smart Scraping**: Monitors AI/Developer Tools categories on Product Hunt
- **AI Comments**: Generates natural, helpful comments using Claude
- **Telegram Approval**: Review and approve comments before posting
- **Browser Automation**: Uses Playwright with stealth mode for actual engagement
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
│       │                              (Playwright+Stealth)   │
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

### First Time Login (Important!)

Before the bot can engage, you need to login to Product Hunt:

```
1. Send /ph_login in Telegram
2. Bot opens Chrome to PH login page
3. Access your Mac Mini via VNC/Screen Share
4. Complete login (Google/Twitter OAuth)
5. Send /ph_login_done in Telegram
6. Bot verifies and saves session
```

Session persists until it expires or you re-login.

### Daily Operation

```bash
# Start the bot (recommended for Mac Mini)
python -m ph_engagement start

# The bot will:
# - Run at 9AM, 1PM, 5PM, 9PM KST
# - Scrape PH for new posts
# - Generate AI comments
# - Send approval requests to Telegram
# - Execute approved actions via browser
```

### Telegram Commands

**Login:**
- `/ph_login` - Start login flow (opens browser)
- `/ph_login_done` - Confirm login complete
- `/ph_session` - Check session status

**Engagement:**
- `/ph_run` - Run engagement check now
- `/ph_execute` - Execute approved posts (browser action)
- `/ph_queue` - Show pending approvals
- `/ph_stats` - Today's statistics

**Control:**
- `/ph_stop` - Emergency stop
- `/ph_help` - Show all commands

### CLI Commands

```bash
python -m ph_engagement run      # Single run
python -m ph_engagement start    # Start scheduler daemon
python -m ph_engagement status   # Show status
python -m ph_engagement login    # Show login instructions
```

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

## Background Daemon (Mac Mini)

### Option 1: nohup (Simple)

```bash
cd /path/to/ph-engagement-bot
nohup ./venv/bin/python -m ph_engagement start > bot.log 2>&1 &
echo $! > bot.pid

# Check status
tail -f bot.log

# Stop
kill $(cat bot.pid)
```

### Option 2: launchd (Recommended for Mac)

Create `~/Library/LaunchAgents/com.ph-engagement-bot.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ph-engagement-bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>/path/to/ph-engagement-bot/venv/bin/python</string>
        <string>-m</string>
        <string>ph_engagement</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/path/to/ph-engagement-bot</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>/path/to/ph-engagement-bot/logs/bot.log</string>
    <key>StandardErrorPath</key>
    <string>/path/to/ph-engagement-bot/logs/bot.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
```

```bash
# Load (start)
launchctl load ~/Library/LaunchAgents/com.ph-engagement-bot.plist

# Unload (stop)
launchctl unload ~/Library/LaunchAgents/com.ph-engagement-bot.plist

# Check status
launchctl list | grep ph-engagement
```

### Option 3: tmux/screen (Interactive)

```bash
# Start tmux session
tmux new -s phbot

# Run bot
cd /path/to/ph-engagement-bot
./venv/bin/python -m ph_engagement start

# Detach: Ctrl+B, then D

# Reattach later
tmux attach -t phbot
```

### Important Notes

- **headless=False**: Browser window must be visible for CAPTCHA solving
- **VNC Access**: Keep VNC/Screen Sharing enabled for manual intervention
- **Login First**: Run `/ph_login` via Telegram before starting daemon

## Safety Notes

- **Human-in-the-loop**: All actions require manual approval
- **Rate limiting**: Enforced daily limits prevent over-engagement
- **Natural delays**: Random delays between actions
- **Session management**: Manual login required, no stored passwords

## License

MIT
