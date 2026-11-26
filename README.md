# Focus Mode

A small macOS menu bar app that makes you take real breaks, keeps you from drifting, and can keep your Mac running with the lid closed.

- **Pomodoro with locked breaks:** 25 minutes of work, then a full-screen break you can't dismiss.
- **Keep Awake (lid closed):** run your Mac with the lid shut for a time you choose.
- **Idle and YouTube alerts:** a loud alert when you've been idle or on YouTube too long.

It runs locally, has no account, and makes no network requests. Nothing leaves your Mac.

## Install

1. Download the latest `Focus-Mode-<version>.dmg` from the [Releases page](https://github.com/Nithish-Yenaganti/Focus-mode/releases).
2. Open the DMG and drag **Focus Mode** into **Applications**.
3. The app is not yet signed with an Apple Developer ID, so macOS may block the first launch. Run this once, then open the app again:

```bash
xattr -dr com.apple.quarantine "/Applications/Focus Mode.app"
```

Focus Mode has no Dock icon and no window. Look for the esc key icon in the menu bar.

## Using it

### Pomodoro with locked breaks
- Choose **Start Pomodoro** or **Stop Pomodoro** from the menu. The menu bar shows the time left.
- The cycle follows the classic technique: 25 min work, then a locked 5 min break. After every 4th pomodoro the break is a 15 min long break. It repeats until you stop it.
- During a break a full-screen overlay covers every display with a countdown and one short tip, such as "Stand up", "Look out the window" or "Drink water". There is nothing to read, because the point is to look away.
- A sound plays when a break starts and ends.
- Change the lengths with **Set Work Minutes**, **Set Break Minutes** and **Set Long Break Minutes**.
- The overlay has no skip button. Use **Quit** from the menu bar if you really must leave.

### Keep Awake (lid closed)
- Choose **Keep Awake (lid closed)**, then 30 min, 1 h, 2 h, 4 h, 8 h or **Custom...**. Use **Stop Keep Awake** to end it early.
- While it runs, your Mac keeps working with the lid shut, also on battery. The menu bar shows `Awake 1h 12m`.
- It needs your admin password once per session. The app runs `pmset -a disablesleep 1` for you.
- A small root watchdog restores normal sleep when the time is up, when you Stop or Quit, if the app crashes, and if the battery falls below 20%. If the Mac is rebooted mid-session, the app offers to restore sleep the next time it starts.
- Don't carry a running Mac in a bag. With the lid closed and sleep disabled, it can get hot.

### Idle and YouTube alerts
- **Idle:** plays an alert if you haven't touched the keyboard or mouse for the limit (default 10 min).
- **YouTube:** plays an alert if the frontmost Chrome or Safari tab stays on YouTube for the limit (default 15 min).
- Change the limits with **Set Max Idle Time** and **Set Max YouTube Time**.
- Alerts fire once per limit and re-arm when the condition clears. Before an alert, the app raises the system volume to 65% if it is muted or lower.
- Idle and YouTube monitoring pause during Pomodoro breaks.
- **Focus Mode: ON/OFF** in the menu turns these two alerts on or off.

Settings reset when you restart the app.

## Permissions

| Permission | Why | When it appears |
|---|---|---|
| Automation (Apple Events) | Read the URL of the frontmost Chrome or Safari tab to time YouTube use | First time the app checks a browser |
| Accessibility | Requested at launch for idle monitoring | First launch |
| Administrator password | Turn lid-closed sleep on and off | Each Keep Awake session |

If you denied a permission before, change it under `System Settings > Privacy & Security > Automation` or `Accessibility`.

## Privacy
Focus Mode runs entirely on your Mac. It reads the active browser tab's URL only to check whether it is YouTube, and does not store or send it. It does not collect data or use the network.

## Troubleshooting
- **App won't open ("cannot verify developer"):** run the `xattr` command from the Install section.
- **No icon in the menu bar:** the menu bar may be full. Quit other menu bar apps or check that `Focus Mode` is running in Activity Monitor.
- **YouTube time never counts:** allow Automation for `Google Chrome` or `Safari` in System Settings.
- **My Mac won't sleep:** a Keep Awake session may still be active. Choose **Stop Keep Awake**, or run `sudo pmset -a disablesleep 0` in Terminal.
- **Uninstall:** quit the app, delete `/Applications/Focus Mode.app`, and run `rm -rf "$HOME/Library/Application Support/Focus Mode"`.

## Development

Requirements: macOS and Python 3.10+.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
python focus_mode.py
```

### Build the app

```bash
python setup.py py2app
```

The app is created at `dist/Focus Mode.app`.

### Package and publish a release

The DMG is git-ignored. Publish it as a GitHub Release instead of committing it:

```bash
hdiutil create -volname "Focus Mode" -srcfolder "dist/Focus Mode.app" -ov -format UDZO Focus-Mode-<version>.dmg
gh release create v<version> Focus-Mode-<version>.dmg --title "Focus Mode <version>" --notes-file <notes.md>
```

## More docs
- [PROJECT.md](PROJECT.md): feature overview and code layout
- [ARCHITECTURE.md](ARCHITECTURE.md): diagrams of the components, the Pomodoro cycle and Keep Awake
- [PRODUCTION.md](PRODUCTION.md): what it takes to sign, notarize and distribute the app
- [CHANGELOG.md](CHANGELOG.md): version history
