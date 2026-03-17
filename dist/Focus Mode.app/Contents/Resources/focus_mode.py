#!/usr/bin/env python3
import os
from dataclasses import dataclass

import rumps
from AppKit import NSApp, NSRunningApplication, NSSound
from Foundation import NSAppleScript
from Quartz import (
    CGEventSourceSecondsSinceLastEventType,
    kCGAnyInputEventType,
    kCGEventSourceStateHIDSystemState,
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

        self.toggle_focus_mode_item = rumps.MenuItem("Focus Mode: ON")
        self.status_idle = rumps.MenuItem("Idle: --")
        self.status_youtube = rumps.MenuItem("YouTube: --")
        self.status_idle.set_callback(None)
        self.status_youtube.set_callback(None)

        self.menu = [
            self.toggle_focus_mode_item,
            None,
            self.status_idle,
            self.status_youtube,
            None,
            rumps.MenuItem("Set Max Idle Time"),
            rumps.MenuItem("Set Max YouTube Time"),
            None,
            rumps.MenuItem("Quit"),
        ]

        self.toggle_focus_mode_item.set_callback(self.toggle_focus_mode)
        self.menu["Set Max Idle Time"].set_callback(self.set_max_idle)
        self.menu["Set Max YouTube Time"].set_callback(self.set_max_youtube)
        self.menu["Quit"].set_callback(self.quit_app)

        self.timer = rumps.Timer(self.poll, POLL_INTERVAL_SECONDS)

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

    def quit_app(self, _):
        rumps.quit_application()

    def run(self, **options):
        self.timer.start()
        super().run(**options)


if __name__ == "__main__":
    app = FocusModeApp()
    app.run()
