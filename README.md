# Focus Mode (macOS Menu Bar App)

A native Python menu bar app that monitors:
- System idle time (keyboard/mouse inactivity)
- Continuous YouTube usage in the frontmost Chrome/Safari tab

When thresholds are exceeded, it plays a loud alert and sends a desktop notification.

## Features
- Menu bar only app (`LSUIElement=True`, no Dock icon)
- Idle timer via Quartz HID idle API:
  - `CGEventSourceSecondsSinceLastEventType`
- YouTube timer via AppleScript against frontmost browser tab
- Mode-specific sounds from `public/`:
  - `not_idle.mp3` for idle alerts
  - `youtube_sound.mp3` for YouTube alerts
- Runtime settings from menu:
  - Set max idle minutes (default 10)
  - Set max YouTube minutes (default 15)
- Polling every 5 seconds (low CPU background checks)

## Requirements
- macOS
- Python 3.10+

Install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
```

## Run (development)

```bash
python focus_mode.py
```

## Build `.app` with py2app

```bash
python setup.py py2app
```

Built app output:
- `dist/Focus Mode.app`

## Permissions

This app needs the following macOS permissions:

1. Accessibility (for reliable HID idle monitoring)
- Path: `System Settings > Privacy & Security > Accessibility`
- Enable access for the built app or your Python interpreter (during development).
- The app attempts to trigger the Accessibility prompt on launch.

2. Automation / Apple Events (for reading Safari/Chrome tab URL)
- macOS prompts when the app first tries AppleScript browser access.
- Approve prompts for controlling `System Events`, `Safari`, and/or `Google Chrome`.
- If previously denied, reset in:
  - `System Settings > Privacy & Security > Automation`

## Notes
- If no browser is frontmost, browser is closed, or no active tab URL is available, YouTube timer resets to zero.
- Alerts are sent once per threshold breach and re-arm once condition clears.
