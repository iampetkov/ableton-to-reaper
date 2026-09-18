#!/bin/bash
# Launch the Ableton → Reaper migration GUI
# Place this next to gui.py and double-click, or run from terminal

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Use system Python 3
if command -v python3 &>/dev/null; then
    python3 gui.py
else
    echo "Python 3 not found. Install it from python.org or via Homebrew: brew install python3"
    read -p "Press Enter to exit..."
fi
