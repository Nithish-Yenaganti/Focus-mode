# Taking Focus Mode to Production

This guide covers what it takes to turn Focus Mode from a project that works on one Mac into an app other people can download, install and trust.

## Why users would want it

Most people at a laptop sit for hours without a break, and their eyes, neck and back pay for it. "Take a break" notifications are easy to dismiss, so they don't work. Focus Mode doesn't ask: after each 25-minute block, the screen is covered for 5 minutes (15 after every fourth block). The break actually happens.

- **Health:** the classic Pomodoro cycle gives regular rest for eyes, neck and back, and gets people to stand up.
- **Focus:** fixed 25-minute blocks make starting easy, and optional alerts catch long idle stretches and long YouTube sessions.
- **Light and private:** a small menu bar app with no window, no account and no network use. Nothing leaves the Mac.
- **Free:** no subscription, and the source is open.

The break screen shows only a countdown and one short tip, such as "Look out the window at something far away", so people leave the screen instead of reading it.

## 1. Where things stand today

| Area | Status | Gap for production |
|---|---|---|
| Core features | Works: Pomodoro, locked breaks, idle and YouTube alerts | Settings reset on every restart |
| Build | `py2app` produces `Focus Mode.app` | Built for this Mac's architecture only; not signed |
| Distribution | `Focus-Mode.dmg` committed to git | Gatekeeper blocks it for other users; the binary bloats the repo |
| Permissions | Prompts appear at first use | No guidance if the user denies them |
| Updates | None | Users stay on old versions forever |
| Testing | Manual smoke tests | No automated tests, no CI |
| Support | README only | No license, no privacy statement, no issue process |

## 2. Release blockers (must do)

### 2.1 Developer ID signing and notarization

An unsigned app shows "cannot be opened because the developer cannot be verified" on other people's Macs. Users have to bypass Gatekeeper by hand, and most won't.

1. Join the Apple Developer Program (99 USD per year).
2. Create a **Developer ID Application** certificate in your account and install it in your keychain.
3. Sign with the hardened runtime and an entitlements file (see 2.2):
   ```bash
   codesign --deep --force --options runtime \
     --entitlements entitlements.plist \
     --sign "Developer ID Application: <Name> (<TEAMID>)" \
     "dist/Focus Mode.app"
   ```
4. Store notarization credentials once, then notarize and staple:
   ```bash
   xcrun notarytool store-credentials focusmode --apple-id <id> --team-id <TEAMID>
   ditto -c -k --keepParent "dist/Focus Mode.app" FocusMode.zip
   xcrun notarytool submit FocusMode.zip --keychain-profile focusmode --wait
   xcrun stapler staple "dist/Focus Mode.app"
   ```
5. Verify: `spctl --assess --type execute -vv "dist/Focus Mode.app"` should say "accepted, source=Notarized Developer ID".

Sign the app first, build the DMG from the signed app, then sign, notarize and staple the DMG too.

### 2.2 Entitlements and permission strings

With the hardened runtime on, the app needs an `entitlements.plist` that allows sending Apple Events (used to read the browser tab URL):

```xml
<key>com.apple.security.automation.apple-events</key><true/>
```

Python and PyObjC bundles often also need `com.apple.security.cs.allow-unsigned-executable-memory` or `com.apple.security.cs.disable-library-validation`. Add only what notarization or launch testing shows is required.

Also keep `NSAppleEventsUsageDescription` in the plist (already present in `setup.py`) and make the text specific: "Focus Mode reads the URL of your active browser tab to time YouTube use. It never records or sends it."

**Check whether Accessibility is really needed.** `CGEventSourceSecondsSinceLastEventType` generally works without the Accessibility permission. The app asks for it on launch, which makes new users nervous. Test on a clean user account without it. If idle detection works, remove the Accessibility prompt entirely.

### 2.3 Universal build

Build for both Apple Silicon and Intel, or state clearly that only Apple Silicon is supported. Use a universal2 Python (from python.org) with `py2app`, then check:

```bash
lipo -archs "dist/Focus Mode.app/Contents/MacOS/Focus Mode"   # expect: x86_64 arm64
```

Set `LSMinimumSystemVersion` in the plist to the oldest macOS you test on.

### 2.4 Stop committing binaries

`Focus-Mode.dmg` is about 24 MB per version in git history, and it is listed in `.gitignore` anyway. Remove it from git and publish builds as **GitHub Releases** assets instead:

```bash
git rm --cached Focus-Mode.dmg
gh release create v1.2.0 Focus-Mode-1.2.0.dmg --notes-file CHANGELOG.md
```

### 2.5 Persist settings

Today the work, break, idle and YouTube limits reset when the app restarts. Store them with `NSUserDefaults` (`NSUserDefaults.standardUserDefaults()`), load them at startup, and save on every change.

## 3. Quality and safety (strongly recommended)

### 3.1 Safe exit from the locked screen
The break overlay has no skip button. That is the point, but production users need a safety net:
- A hidden emergency exit, such as holding a key combination for 5 seconds, or a "Skip break" button that appears after 30 seconds.
- A menu option "Skip next break" and a "Pause for 1 hour" option for meetings and presentations.
- Never lock when the screen is being shared or recorded, or when a presentation app is in full screen. Offer this as a setting.
- Test the overlay with multiple monitors, monitors that connect or disconnect mid-break, sleep and wake during a break, and Mission Control and full-screen apps.

### 3.2 Launch at login
Menu bar utilities need to start on their own. Use `SMAppService.mainApp` (macOS 13+) through PyObjC, with a "Launch at login" menu toggle that defaults to off.

### 3.3 Reliability
- If the Mac sleeps, wakes or locks mid-cycle, reset or resume the timer on purpose. Subscribe to `NSWorkspaceDidWakeNotification` and screen lock notifications.
- Count time with a monotonic clock (`time.monotonic()`) instead of counting ticks, so the timer doesn't drift if the main thread stalls.
- Write errors to a log file under `~/Library/Logs/Focus Mode/`, and add "Show Logs" to the menu.

### 3.4 Testing and CI
- Move timer logic (phase transitions, long-break rule) into a plain Python class with no UI imports, and unit test it with `pytest`.
- Add a GitHub Actions workflow on a macOS runner that installs the dependencies, runs the tests and builds the app on every push.
- Extend the workflow to sign, notarize and publish the DMG when a version tag is pushed (store certificates and credentials as encrypted repository secrets).

## 4. Distribution options

| Channel | Effort | Notes |
|---|---|---|
| **GitHub Releases** | Low | Best first step. Notarized DMG, plus release notes. |
| **Homebrew Cask** | Low-medium | `brew install --cask focus-mode` once releases are stable. Requires a notarized app. |
| **Own website** | Medium | One page: what it does, screenshot, download button, privacy note. |
| **Mac App Store** | High | Requires the App Sandbox. Reading browser URLs and global idle time are hard or restricted inside it. Probably not a fit for the current feature set. |

Recommended path: GitHub Releases first, then a Homebrew cask, then a simple website.

## 5. Automatic updates

Without updates, users run old versions and bugs live forever. Options:
- **Sparkle** (the standard for Mac apps outside the App Store): host an `appcast.xml` on GitHub Pages and sign updates with an EdDSA key. Integrating it into a Python app takes some work.
- **Lightweight check**: on launch, fetch the latest GitHub release version and show "Update available" in the menu with a link. Much simpler and a fine start.

## 6. Legal, privacy and trust

- Add a `LICENSE` file (MIT is the usual choice for a small utility).
- Add a short `PRIVACY.md`: the app runs locally, collects no data, makes no network requests, and reads the browser tab URL only to time YouTube use without storing it. Keep this true. If you ever add analytics or crash reporting, make it opt-in and say so.
- Put a `CHANGELOG.md` in the repo and follow semantic versioning (`1.2.0`).
- Add `CONTRIBUTING.md` and issue templates if you want outside help.
- The Apple Developer account is in your name, so signed builds show your name as the developer.

## 7. Documentation and onboarding

- A first-run welcome screen: what the app does, the three permissions it may ask for and why, and how to start the timer.
- Screenshots or a short GIF of the break screen and the menu in the README.
- A troubleshooting section: permission denied, icon not showing, overlay on the wrong screen, how to fully uninstall (delete the app, then `defaults delete com.focusmode.menubar`).

## 8. Suggested roadmap

| Phase | Goal | Work |
|---|---|---|
| **1. Shareable** | Friends can install it without warnings | Developer ID signing, notarization, universal build, GitHub Release, LICENSE, PRIVACY.md |
| **2. Solid** | It behaves well day to day | Persist settings, launch at login, skip-break safety exit, sleep/wake handling, unit tests, CI |
| **3. Polished** | It feels like a real product | Onboarding, update check, Homebrew cask, website, screenshots |
| **4. Growth** | People ask for more | Sparkle updates, break statistics, custom tips, per-app rules, localization |

## 9. Release checklist

- [ ] Version bumped in `setup.py` and `CHANGELOG.md` updated
- [ ] Unit tests and CI pass
- [ ] App built universal2, signed with the hardened runtime
- [ ] Notarized and stapled (app and DMG), `spctl --assess` accepted
- [ ] Tested on a clean macOS user account with no prior permissions
- [ ] Break overlay tested with multiple displays, sleep/wake, full-screen apps
- [ ] DMG uploaded to a GitHub Release with notes (not committed to git)
- [ ] README download link and PRIVACY.md current
