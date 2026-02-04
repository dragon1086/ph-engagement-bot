#!/bin/bash
# Install PH Engagement Bot as macOS daemon

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PLIST_NAME="com.ph-engagement-bot.plist"
PLIST_PATH="$HOME/Library/LaunchAgents/$PLIST_NAME"

echo "Installing PH Engagement Bot daemon..."
echo "Project directory: $PROJECT_DIR"

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Generate plist with actual paths
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.ph-engagement-bot</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PROJECT_DIR/venv/bin/python</string>
        <string>-m</string>
        <string>ph_engagement</string>
        <string>start</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/logs/bot.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/logs/bot.error.log</string>
</dict>
</plist>
EOF

echo "Created: $PLIST_PATH"

# Load the daemon
launchctl load "$PLIST_PATH"
echo "Daemon loaded and started!"

echo ""
echo "Commands:"
echo "  Check status: launchctl list | grep ph-engagement"
echo "  View logs:    tail -f $PROJECT_DIR/logs/bot.log"
echo "  Stop:         launchctl unload $PLIST_PATH"
echo "  Start:        launchctl load $PLIST_PATH"
