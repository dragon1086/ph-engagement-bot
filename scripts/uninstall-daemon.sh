#!/bin/bash
# Uninstall PH Engagement Bot daemon

PLIST_PATH="$HOME/Library/LaunchAgents/com.ph-engagement-bot.plist"

if [ -f "$PLIST_PATH" ]; then
    echo "Stopping daemon..."
    launchctl unload "$PLIST_PATH" 2>/dev/null || true

    echo "Removing plist..."
    rm "$PLIST_PATH"

    echo "Daemon uninstalled!"
else
    echo "Daemon not installed."
fi
