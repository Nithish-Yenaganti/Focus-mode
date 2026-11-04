#!/usr/bin/env python3
import os
import random
import shlex
import subprocess
import time
from dataclasses import dataclass

import rumps
from AppKit import (
    NSApp,
    NSBackingStoreBuffered,
    NSColor,
    NSFont,
    NSRunningApplication,
    NSScreen,
    NSSound,
    NSTextField,
    NSWindow,
)
from Foundation import NSAppleScript
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateHIDSystemState,
    CGShieldingWindowLevel,
)
from ApplicationServices import (
    AXIsProcessTrusted,
    AXIsProcessTrustedWithOptions,
    kAXTrustedCheckOptionPrompt,
)

POLL_INTERVAL_SECONDS = 5
DEFAULT_MAX_IDLE_SECONDS = 10 * 60
DEFAULT_MAX_YOUTUBE_SECONDS = 15 * 60
MIN_ALERT_VOLUME_PERCENT = 65
IDLE_ALERT_SOUND = "not_idle.mp3"
YOUTUBE_ALERT_SOUND = "youtube_sound.mp3"
ICON_FILE = "icon.png"

DEFAULT_WORK_SECONDS = 25 * 60
DEFAULT_BREAK_SECONDS = 5 * 60
DEFAULT_LONG_BREAK_SECONDS = 15 * 60
POMODOROS_PER_LONG_BREAK = 4
KEEP_AWAKE_PRESETS = [
    (30, "30 minutes"),
    (60, "1 hour"),
    (120, "2 hours"),
    (240, "4 hours"),
    (480, "8 hours"),
]
LOW_BATTERY_PERCENT = 20
KEEP_AWAKE_STATE_DIR = os.path.expanduser("~/Library/Application Support/Focus Mode")
KEEP_AWAKE_STATE_FILE = os.path.join(KEEP_AWAKE_STATE_DIR, "keep_awake_until")
WATCHDOG_NAME = "focusmode-watchdog"
# Runs as root, detached from the app. Args: $1=end epoch, $2=control file, $3=min battery %.
# It restores normal sleep when time is up, the control file is deleted (Stop / Quit),
# or the battery gets low. It never reads the control file, so it cannot be extended.
WATCHDOG_SCRIPT = '''
END="$1"; CTL="$2"; MINBAT="$3"
trap "/usr/bin/pmset -a disablesleep 0" EXIT
trap "exit 0" TERM INT HUP
while [ "$(date +%s)" -lt "$END" ] && [ -f "$CTL" ]; do
  OUT=$(/usr/bin/pmset -g batt)
  case "$OUT" in
    *"Battery Power"*)
      PCT=$(echo "$OUT" | grep -o "[0-9]*%" | head -1 | tr -d "%")
      if [ -n "$PCT" ] && [ "$PCT" -lt "$MINBAT" ]; then break; fi ;;
  esac
  sleep 5
done
'''

BREAK_TIPS = [
    "Stand up and walk away from your desk",
    "Look out the window at something far away",
    "Drink a glass of water",
    "Close your eyes and breathe slowly",
    "Roll your shoulders and stretch your neck",
]
LONG_BREAK_TIPS = [
    "Take a walk, go outside if you can",
    "Stretch your back, arms and legs",
    "Get water or a snack, then rest your eyes",
]

def format_short(seconds: int) -> str:
    minutes = max(0, int(seconds)) // 60
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m" if minutes else "<1m"


def format_duration(seconds: int) -> str:
    minutes, secs = divmod(max(0, int(seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {secs}s"
    return f"{minutes}m {secs}s"


def run_applescript(script: str) -> str:
    apple_script = NSAppleScript.alloc().initWithSource_(script)
    result, error = apple_script.executeAndReturnError_(None)
    if error is not None:
        return ""
    if result is None:
        return ""
    return result.stringValue() or ""


def run_as_admin(shell_command: str, prompt: str) -> None:
    escaped = shell_command.replace("\\", "\\\\").replace('"', '\\"')
    escaped_prompt = prompt.replace("\\", "\\\\").replace('"', '\\"')
    run_applescript(
        f'do shell script "{escaped}" with prompt "{escaped_prompt}" with administrator privileges'
    )


class KeepAwake:
    """Keeps the Mac running with the lid closed via `pmset disablesleep`.

    Starting needs one admin password prompt. A detached root watchdog enforces the
    end time, so sleep is restored even if the app quits or crashes.
    """

    @staticmethod
    def sleep_disabled() -> bool:
        try:
            out = subprocess.run(
                ["/usr/bin/pmset", "-g"], capture_output=True, text=True, timeout=5
            ).stdout
        except (subprocess.SubprocessError, OSError):
            return False
        for line in out.splitlines():
            if "SleepDisabled" in line:
                return line.split()[-1] == "1"
        return False

    @staticmethod
    def watchdog_running() -> bool:
        try:
            return subprocess.run(
                ["/usr/bin/pgrep", "-f", WATCHDOG_NAME], capture_output=True, timeout=5
            ).returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    @staticmethod
    def saved_end_time() -> float | None:
        try:
            with open(KEEP_AWAKE_STATE_FILE) as handle:
                return float(handle.read().strip())
        except (OSError, ValueError):
            return None

    def start(self, seconds: int) -> float | None:
        """Returns the end epoch, or None if the user cancelled / it failed."""
        end = int(time.time()) + int(seconds)
        os.makedirs(KEEP_AWAKE_STATE_DIR, exist_ok=True)
        with open(KEEP_AWAKE_STATE_FILE, "w") as handle:
            handle.write(str(end))
        command = (
            "/usr/bin/pmset -a disablesleep 1; "
            f"/usr/bin/nohup /bin/sh -c {shlex.quote(WATCHDOG_SCRIPT)} {WATCHDOG_NAME} "
            f"{end} {shlex.quote(KEEP_AWAKE_STATE_FILE)} {LOW_BATTERY_PERCENT} "
            ">/dev/null 2>&1 &"
        )
        run_as_admin(command, "Focus Mode wants to keep your Mac awake with the lid closed.")
        if not self.sleep_disabled():
            self.stop()
            return None
        return float(end)

    def stop(self):
        """Deleting the control file makes the watchdog restore sleep within ~5s."""
        try:
            os.remove(KEEP_AWAKE_STATE_FILE)
        except OSError:
            pass

    def restore_sleep_now(self):
        self.stop()
        run_as_admin("/usr/bin/pmset -a disablesleep 0", "Focus Mode wants to restore normal sleep.")


def get_frontmost_browser_url() -> str:
    script = '''
    tell application "System Events"
        set frontApp to name of first process whose frontmost is true
    end tell

    if frontApp is "Google Chrome" then
        tell application "Google Chrome"
            if (count of windows) is 0 then return ""
            return URL of active tab of front window
        end tell
    else if frontApp is "Safari" then
        tell application "Safari"
            if (count of windows) is 0 then return ""
            return URL of current tab of front window
        end tell
    else
        return ""
    end if
    '''
    return run_applescript(script).strip().lower()


def ensure_minimum_alert_volume(min_volume_percent: int = MIN_ALERT_VOLUME_PERCENT):
    target_volume = int(min_volume_percent)
    script = f'''
    set currentSettings to get volume settings
    set currentOutputVolume to output volume of currentSettings
    set isOutputMuted to output muted of currentSettings
    if isOutputMuted is true or currentOutputVolume < {target_volume} then
        set volume output volume {target_volume} without output muted
    end if
    '''
    run_applescript(script)


def resolve_resource_path(filename: str) -> str | None:
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base_dir, "public", filename),
        os.path.join(base_dir, "..", "Resources", "public", filename),
    ]
    for candidate in candidates:
        full_path = os.path.abspath(candidate)
        if os.path.exists(full_path):
            return full_path
    return None


class BreakOverlay:
    """Full-screen, always-on-top windows on every display."""

    def __init__(self):
        self.windows = []
        self.countdown_labels = []

    @staticmethod
    def _label(text, size, frame, bold=False, alpha=1.0):
        field = NSTextField.alloc().initWithFrame_(frame)
        field.setStringValue_(text)
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setAlignment_(2)  # center
        field.setLineBreakMode_(0)  # word wrap
        field.setTextColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, alpha))
        field.setFont_(
            NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        )
        return field

    def show(self, seconds: int, long_break: bool = False):
        self.hide()
        heading = "Long break: step away from the screen" if long_break else "Break: look away from the screen"
        tip = random.choice(LONG_BREAK_TIPS if long_break else BREAK_TIPS)
        for screen in NSScreen.screens():
            frame = screen.frame()
            w, h = frame.size.width, frame.size.height
            window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_screen_(
                frame, 0, NSBackingStoreBuffered, False, screen
            )
            window.setLevel_(CGShieldingWindowLevel())
            window.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(0.04, 0.97))
            window.setOpaque_(False)
            window.setReleasedWhenClosed_(False)
            window.setCollectionBehavior_(1 | 16 | 256)  # all spaces, stationary, fullscreen aux

            content = window.contentView()
            title = self._label(heading, 34, ((0, h * 0.78), (w, 50)), bold=True)
            countdown = self._label(
                format_duration(seconds), 96, ((0, h * 0.60), (w, 120)), bold=True
            )
            tip_label = self._label(tip, 32, ((w * 0.15, h * 0.40), (w * 0.7, 80)), alpha=0.8)
            for view in (title, countdown, tip_label):
                content.addSubview_(view)

            window.makeKeyAndOrderFront_(None)
            self.windows.append(window)
            self.countdown_labels.append(countdown)
        app = NSApp()
        if app is not None:
            app.activateIgnoringOtherApps_(True)

    def set_countdown(self, seconds: int):
        for label in self.countdown_labels:
            label.setStringValue_(format_duration(seconds))

    def hide(self):
        for window in self.windows:
            window.orderOut_(None)
            window.close()
        self.windows = []
        self.countdown_labels = []


@dataclass
class AlertState:
    idle_alert_sent: bool = False
    youtube_alert_sent: bool = False


class FocusModeApp(rumps.App):
    def __init__(self):
        icon_path = resolve_resource_path(ICON_FILE)
        super().__init__(
            name="Focus Mode",
            icon=icon_path,
            title="" if icon_path else "Focus",
            quit_button=None,
            menu=[],
        )

        self.max_idle_seconds = DEFAULT_MAX_IDLE_SECONDS
        self.max_youtube_seconds = DEFAULT_MAX_YOUTUBE_SECONDS
        self.youtube_elapsed_seconds = 0
        self.focus_mode_enabled = True
        self.alert_state = AlertState()

        self.work_seconds = DEFAULT_WORK_SECONDS
        self.break_seconds = DEFAULT_BREAK_SECONDS
        self.long_break_seconds = DEFAULT_LONG_BREAK_SECONDS
        self.completed_pomodoros = 0
        self.pomodoro_running = False
        self.phase = "work"
        self.phase_remaining = 0
        self.overlay = BreakOverlay()
        self.keep_awake = KeepAwake()
        self.awake_end: float | None = None
        self._awake_ticks = 0
        self._pomo_title = ""

        self.toggle_focus_mode_item = rumps.MenuItem("Focus Mode: ON")
        self.status_idle = rumps.MenuItem("Idle: --")
        self.status_youtube = rumps.MenuItem("YouTube: --")
        self.status_idle.set_callback(None)
        self.status_youtube.set_callback(None)
        self.status_awake = rumps.MenuItem("Keep Awake: Off")
        self.status_awake.set_callback(None)
        self.keep_awake_menu = rumps.MenuItem("Keep Awake (lid closed)")
        for minutes, label in KEEP_AWAKE_PRESETS:
            self.keep_awake_menu.add(
                rumps.MenuItem(label, callback=lambda _, m=minutes: self.start_keep_awake(m * 60))
            )
        self.keep_awake_menu.add(rumps.MenuItem("Custom...", callback=self.start_keep_awake_custom))
        self.keep_awake_menu.add(rumps.MenuItem("Stop Keep Awake", callback=self.stop_keep_awake))
        self.pomodoro_toggle_item = rumps.MenuItem("Start Pomodoro")
        self.status_pomodoro = rumps.MenuItem("Pomodoro: Stopped")
        self.status_pomodoro.set_callback(None)

        self.menu = [
            self.toggle_focus_mode_item,
            None,
            self.pomodoro_toggle_item,
            self.status_pomodoro,
            None,
            self.keep_awake_menu,
            self.status_awake,
            None,
            self.status_idle,
            self.status_youtube,
            None,
            rumps.MenuItem("Set Max Idle Time"),
            rumps.MenuItem("Set Max YouTube Time"),
            rumps.MenuItem("Set Work Minutes"),
            rumps.MenuItem("Set Break Minutes"),
            rumps.MenuItem("Set Long Break Minutes"),
            None,
            rumps.MenuItem("Quit"),
        ]

        self.toggle_focus_mode_item.set_callback(self.toggle_focus_mode)
        self.menu["Set Max Idle Time"].set_callback(self.set_max_idle)
        self.menu["Set Max YouTube Time"].set_callback(self.set_max_youtube)
        self.menu["Set Work Minutes"].set_callback(self.set_work_minutes)
        self.menu["Set Break Minutes"].set_callback(self.set_break_minutes)
        self.menu["Set Long Break Minutes"].set_callback(self.set_long_break_minutes)
        self.pomodoro_toggle_item.set_callback(self.toggle_pomodoro)
        self.menu["Quit"].set_callback(self.quit_app)

        self.timer = rumps.Timer(self.poll, POLL_INTERVAL_SECONDS)
        self.pomodoro_timer = rumps.Timer(self.pomodoro_tick, 1)
        self.awake_timer = rumps.Timer(self.awake_tick, 1)
        self.startup_timer = rumps.Timer(self._startup_check, 3)

        self._configure_activation_policy()
        self._check_accessibility_permission()

    def _configure_activation_policy(self):
        # Keep app as UI-element style process (menu bar only).
        NSRunningApplication.currentApplication().activateWithOptions_(0)
        app = NSApp()
        if app is not None:
            app.setActivationPolicy_(1)

    def _check_accessibility_permission(self):
        if AXIsProcessTrusted():
            return

        # Trigger Accessibility prompt for idle monitoring API usage.
        options = {kAXTrustedCheckOptionPrompt: True}
        AXIsProcessTrustedWithOptions(options)

        rumps.notification(
            title="Focus Mode Permission Needed",
            subtitle="Enable Accessibility Access",
            message=(
                "Open System Settings > Privacy & Security > Accessibility "
                "and enable Focus Mode."
            ),
        )

    def _play_alert(self):
        ensure_minimum_alert_volume(MIN_ALERT_VOLUME_PERCENT)
        sound_path = "/System/Library/Sounds/Submarine.aiff"
        if os.path.exists(sound_path):
            os.system(f'afplay "{sound_path}"')
            return

        sound = NSSound.soundNamed_("Glass")
        if sound:
            sound.play()

    def _resource_path(self, filename: str) -> str | None:
        return resolve_resource_path(filename)

    def _play_sound_file(self, filename: str):
        ensure_minimum_alert_volume(MIN_ALERT_VOLUME_PERCENT)
        sound_path = self._resource_path(filename)
        if sound_path:
            os.system(f'afplay "{sound_path}"')
            return
        self._play_alert()

    def _notify(self, title: str, message: str, sound_file: str | None = None):
        if sound_file:
            self._play_sound_file(sound_file)
        else:
            self._play_alert()
        rumps.notification(title=title, subtitle="Focus Mode", message=message)

    def _current_idle_seconds(self) -> int:
        value = CGEventSourceSecondsSinceLastEventType(
            kCGEventSourceStateHIDSystemState,
            kCGAnyInputEventType,
        )
        return int(max(0, value))

    def poll(self, _):
        if self.pomodoro_running and self.phase == "break":
            return  # user is away on purpose; don't count idle/YouTube
        if not self.focus_mode_enabled:
            self.youtube_elapsed_seconds = 0
            self.alert_state.idle_alert_sent = False
            self.alert_state.youtube_alert_sent = False
            self.status_idle.title = "Idle: Paused (Focus Mode OFF)"
            self.status_youtube.title = "YouTube: Paused (Focus Mode OFF)"
            return

        idle_seconds = self._current_idle_seconds()

        if idle_seconds >= self.max_idle_seconds and not self.alert_state.idle_alert_sent:
            self._notify(
                "Idle limit reached",
                f"No activity for {format_duration(idle_seconds)}.",
                sound_file=IDLE_ALERT_SOUND,
            )
            self.alert_state.idle_alert_sent = True
        elif idle_seconds < self.max_idle_seconds:
            self.alert_state.idle_alert_sent = False

        url = get_frontmost_browser_url()
        if "youtube.com" in url:
            self.youtube_elapsed_seconds += POLL_INTERVAL_SECONDS
            if (
                self.youtube_elapsed_seconds >= self.max_youtube_seconds
                and not self.alert_state.youtube_alert_sent
            ):
                self._notify(
                    "YouTube limit reached",
                    f"YouTube active for {format_duration(self.youtube_elapsed_seconds)}.",
                    sound_file=YOUTUBE_ALERT_SOUND,
                )
                self.alert_state.youtube_alert_sent = True
        else:
            self.youtube_elapsed_seconds = 0
            self.alert_state.youtube_alert_sent = False

        self.status_idle.title = (
            f"Idle: {format_duration(idle_seconds)} / {format_duration(self.max_idle_seconds)}"
        )
        self.status_youtube.title = (
            f"YouTube: {format_duration(self.youtube_elapsed_seconds)} / "
            f"{format_duration(self.max_youtube_seconds)}"
        )

    def toggle_focus_mode(self, _):
        self.focus_mode_enabled = not self.focus_mode_enabled
        self.toggle_focus_mode_item.title = (
            "Focus Mode: ON" if self.focus_mode_enabled else "Focus Mode: OFF"
        )

        if not self.focus_mode_enabled:
            self.youtube_elapsed_seconds = 0
            self.alert_state.idle_alert_sent = False
            self.alert_state.youtube_alert_sent = False
            self.status_idle.title = "Idle: Paused (Focus Mode OFF)"
            self.status_youtube.title = "YouTube: Paused (Focus Mode OFF)"

    def _update_seconds_setting(self, title: str, current_seconds: int) -> int | None:
        current_minutes = max(1, current_seconds // 60)
        window = rumps.Window(
            title=title,
            message=f"Current value: {current_minutes} minute(s)",
            default_text=str(current_minutes),
            ok="Save",
            cancel="Cancel",
        )
        response = window.run()
        if response.clicked != 1:
            return None

        try:
            minutes = int(response.text.strip())
            if minutes <= 0:
                raise ValueError
            return minutes * 60
        except ValueError:
            rumps.alert(
                title="Invalid Value",
                message="Please enter a positive whole number of minutes.",
            )
            return None

    def set_max_idle(self, _):
        new_value = self._update_seconds_setting("Set Max Idle Time", self.max_idle_seconds)
        if new_value is not None:
            self.max_idle_seconds = new_value
            self.alert_state.idle_alert_sent = False

    def set_max_youtube(self, _):
        new_value = self._update_seconds_setting(
            "Set Max YouTube Time", self.max_youtube_seconds
        )
        if new_value is not None:
            self.max_youtube_seconds = new_value
            self.alert_state.youtube_alert_sent = False

    def set_work_minutes(self, _):
        value = self._update_seconds_setting("Set Work Minutes", self.work_seconds)
        if value is not None:
            self.work_seconds = value

    def set_break_minutes(self, _):
        value = self._update_seconds_setting("Set Break Minutes", self.break_seconds)
        if value is not None:
            self.break_seconds = value

    def set_long_break_minutes(self, _):
        value = self._update_seconds_setting("Set Long Break Minutes", self.long_break_seconds)
        if value is not None:
            self.long_break_seconds = value

    def toggle_pomodoro(self, _):
        if self.pomodoro_running:
            self._stop_pomodoro()
        else:
            self.completed_pomodoros = 0
            self._start_work()
            self.pomodoro_running = True
            self.pomodoro_toggle_item.title = "Stop Pomodoro"
            self.pomodoro_timer.start()

    def _stop_pomodoro(self):
        self.pomodoro_running = False
        self.pomodoro_timer.stop()
        self.overlay.hide()
        self.pomodoro_toggle_item.title = "Start Pomodoro"
        self.status_pomodoro.title = "Pomodoro: Stopped"
        self._pomo_title = ""
        self._refresh_title()

    def _start_work(self):
        self.phase = "work"
        self.phase_remaining = self.work_seconds

    def _start_break(self):
        self.phase = "break"
        self.completed_pomodoros += 1
        is_long = self.completed_pomodoros % POMODOROS_PER_LONG_BREAK == 0
        self.phase_remaining = self.long_break_seconds if is_long else self.break_seconds
        self._play_alert()
        self.overlay.show(self.phase_remaining, long_break=is_long)

    def pomodoro_tick(self, _):
        if not self.pomodoro_running:
            return
        self.phase_remaining -= 1

        if self.phase == "break":
            self.overlay.set_countdown(self.phase_remaining)
            self.status_pomodoro.title = f"Break: {format_duration(self.phase_remaining)}"
            self._pomo_title = f"Break {format_duration(self.phase_remaining)}"
            self._refresh_title()
            if self.phase_remaining <= 0:
                self.overlay.hide()
                self._play_alert()
                self._start_work()
            return

        done = self.completed_pomodoros % POMODOROS_PER_LONG_BREAK
        self.status_pomodoro.title = (
            f"Work {done + 1}/{POMODOROS_PER_LONG_BREAK}: "
            f"{format_duration(self.phase_remaining)}"
        )
        self._pomo_title = format_duration(self.phase_remaining)
        self._refresh_title()
        if self.phase_remaining <= 0:
            self._start_break()

    def _refresh_title(self):
        parts = [self._pomo_title]
        if self.awake_end is not None:
            parts.append(f"Awake {format_short(self.awake_end - time.time())}")
        text = " | ".join(part for part in parts if part)
        self.title = text or ("" if self.icon else "Focus")

    def start_keep_awake(self, seconds: int):
        end = self.keep_awake.start(seconds)
        if end is None:
            rumps.notification(
                "Keep Awake", "Not started", "Admin approval is needed to keep the Mac awake with the lid closed."
            )
            return
        self._begin_awake_tracking(end)
        rumps.notification(
            "Keep Awake", "Lid-closed mode ON",
            f"Mac stays awake for {format_short(seconds)}. Don't pack it in a bag while this is on.",
        )

    def start_keep_awake_custom(self, _):
        value = self._update_seconds_setting("Keep Awake (minutes)", 60 * 60)
        if value is not None:
            self.start_keep_awake(value)

    def stop_keep_awake(self, _=None):
        if self.awake_end is None and not self.keep_awake.sleep_disabled():
            return
        self.keep_awake.stop()
        self._end_awake_tracking("Keep Awake stopped", "Normal sleep will be restored in a few seconds.")

    def _begin_awake_tracking(self, end: float):
        self.awake_end = end
        self._awake_ticks = 0
        self.awake_timer.start()
        self.awake_tick(None)

    def _end_awake_tracking(self, subtitle: str, message: str):
        self.awake_end = None
        self.awake_timer.stop()
        self.status_awake.title = "Keep Awake: Off"
        self._refresh_title()
        rumps.notification("Keep Awake", subtitle, message)

    def awake_tick(self, _):
        if self.awake_end is None:
            return
        remaining = self.awake_end - time.time()
        self._awake_ticks += 1
        if remaining <= 0:
            self._end_awake_tracking("Keep Awake finished", "Normal sleep is restored.")
            return
        # Every 5s confirm the watchdog hasn't ended early (e.g. low battery).
        if self._awake_ticks % 5 == 0 and not self.keep_awake.sleep_disabled():
            self.keep_awake.stop()
            self._end_awake_tracking(
                "Keep Awake ended early",
                f"Sleep was restored (battery below {LOW_BATTERY_PERCENT}% or stopped elsewhere).",
            )
            return
        self.status_awake.title = f"Keep Awake: {format_short(remaining)} left"
        self._refresh_title()

    def _startup_check(self, _):
        self.startup_timer.stop()
        if not self.keep_awake.sleep_disabled():
            return
        if self.keep_awake.watchdog_running():
            end = self.keep_awake.saved_end_time()
            if end and end > time.time():
                self._begin_awake_tracking(end)  # app restarted mid-session
            return
        response = rumps.alert(
            title="Sleep is disabled",
            message=(
                "Your Mac is set to never sleep, probably from an interrupted Keep Awake "
                "session. Restore normal sleep? (Admin password required.)"
            ),
            ok="Restore sleep",
            cancel="Leave as is",
        )
        if response == 1:
            self.keep_awake.restore_sleep_now()

    def quit_app(self, _):
        if self.awake_end is not None:
            self.keep_awake.stop()  # watchdog restores normal sleep
        rumps.quit_application()

    def run(self, **options):
        self.timer.start()
        self.startup_timer.start()
        super().run(**options)


if __name__ == "__main__":
    app = FocusModeApp()
    app.run()
