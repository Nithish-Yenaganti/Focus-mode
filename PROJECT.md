# Focus Mode: Project Overview

A macOS menu bar app (Python, `rumps` + PyObjC) that helps you stay focused:
a classic Pomodoro timer with locked breaks, plus idle and YouTube usage alerts.

## Features
1. **Pomodoro timer with locked breaks**
   - 25 min work, 5 min short break, 15 min long break after every 4th pomodoro.
   - Breaks show a full-screen, always-on-top overlay on every display (no skip button).
   - Repeats until stopped from the menu.
2. **Screen-free breaks**: the overlay shows only a countdown and one short tip (stand up, look far away, drink water).
   No reading material on purpose: the break is meant to get you away from the screen.
3. **Idle monitor**: alert when there is no keyboard/mouse activity for too long (default 10 min).
4. **YouTube monitor**: alert when the frontmost Chrome/Safari tab stays on YouTube too long (default 15 min).
5. All limits editable from the menu. Idle and YouTube checks pause during breaks.

## Layout
| Path | Purpose |
|---|---|
| `focus_mode.py` | The whole app: `FocusModeApp` (menu, timers), `BreakOverlay` (lock screen) |
| `setup.py` | py2app build config (version, plist, bundled `public/` resources) |
| `public/` | Icons and alert sounds |
| `requirements.txt` | Python dependencies |
| `Focus-Mode.dmg` | Prebuilt installer |

## How it works
- `rumps.Timer(poll, 5s)`: idle and YouTube checks.
- `rumps.Timer(pomodoro_tick, 1s)`: drives work/break phases and the countdown.
- Phase flow: `work -> break (short, or long every 4th) -> work ...`.
- `BreakOverlay` creates one borderless `NSWindow` per `NSScreen` at `CGShieldingWindowLevel`.

## Constants (top of `focus_mode.py`)
`DEFAULT_WORK_SECONDS`, `DEFAULT_BREAK_SECONDS`, `DEFAULT_LONG_BREAK_SECONDS`,
`POMODOROS_PER_LONG_BREAK`, `BREAK_TIPS`, `LONG_BREAK_TIPS`.

## Build and release
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python setup.py py2app            # -> dist/Focus Mode.app
hdiutil create -volname "Focus Mode" -srcfolder "dist/Focus Mode.app" -ov -format UDZO Focus-Mode.dmg
```

## Known limits
- The overlay cannot block Cmd+Tab or Force Quit; Quit from the menu bar also exits.
- Requires Accessibility (idle) and Automation (browser URL) permissions.
- Settings reset on restart (not persisted).
