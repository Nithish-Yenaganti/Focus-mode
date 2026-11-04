# Changelog

## 1.2.0
- Keep Awake (lid closed): pick a duration (30 min to 8 hours or custom) and the Mac keeps running with the lid shut, using `pmset disablesleep`.
- One admin password prompt per session. A detached root watchdog restores normal sleep when the timer ends, on Stop or Quit, and if the battery drops below 20%, even if the app crashes.
- Menu bar shows the remaining time; a restarted app picks an active session back up and offers to restore sleep after an interrupted one.

## 1.1.0
- Pomodoro timer: 25 min work, 5 min locked break, 15 min long break after every 4th pomodoro.
- Full-screen break overlay on every display with a countdown and one short tip.
- New esc key app and menu bar icon.
- Work, break and long break lengths editable from the menu.
- Idle and YouTube monitoring pause during breaks.
- Installers are now published as GitHub Releases instead of being committed to the repo.

## 1.0.0
- Menu bar app with idle and YouTube time alerts.
