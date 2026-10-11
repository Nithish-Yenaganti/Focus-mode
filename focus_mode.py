#!/usr/bin/env python3
import os
import random
import shutil
import subprocess
import tempfile
import threading
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
LESSON_TIMEOUT_SECONDS = 45
LESSON_TOPICS = [
    "tech industry history",
    "computer science fundamentals",
    "algorithms and data structures",
    "artificial intelligence and machine learning",
    "software engineering practices",
    "distributed systems",
    "databases",
    "operating systems",
    "networking and the internet",
    "programming language design",
    "cybersecurity",
    "system design",
    "developer tooling and version control",
    "tech startups and business models",
]
FALLBACK_LESSONS = [
    "Big-O notation describes how an algorithm's cost grows with input size. "
    "An O(n log n) sort stays practical on millions of items, while O(n^2) quickly collapses.",
    "The CAP theorem says a distributed system facing a network partition must choose "
    "between consistency and availability. Every database design makes that trade-off somewhere.",
    "Conway's Law: organizations design systems that mirror their own communication structure. "
    "If you want a different architecture, you often have to change the team layout first.",
    "A transformer model uses attention to weigh how relevant every token is to every other token, "
    "which lets it capture long-range context without processing text strictly in sequence.",
    "Idempotent operations can be repeated safely with the same result. That is why retries "
    "in payment and API design depend on idempotency keys.",
]

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


def find_claude_cli() -> str | None:
    found = shutil.which("claude")
    if found:
        return found
    for candidate in (
        os.path.expanduser("~/.local/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ):
        if os.path.exists(candidate):
            return candidate
    return None


def fetch_lesson() -> str:
    """Ask the Claude CLI for a short lesson. Nothing is saved to chat history."""
    cli = find_claude_cli()
    if cli:
        topic = random.choice(LESSON_TOPICS)
        prompt = (
            f"Teach me one specific, interesting thing about {topic}. "
            "Pick something non-obvious (variation seed: "
            f"{random.randint(1, 10**6)}). Use 3 to 4 short sentences, plain text only, "
            "no markdown, no preamble."
        )
        try:
            result = subprocess.run(
                [cli, "-p", prompt, "--model", "haiku",
                 "--no-session-persistence", "--tools", ""],
                capture_output=True,
                text=True,
                timeout=LESSON_TIMEOUT_SECONDS,
                cwd=tempfile.gettempdir(),
            )
            text = result.stdout.strip()
            if result.returncode == 0 and text:
                return text
        except (subprocess.SubprocessError, OSError):
            pass
    return random.choice(FALLBACK_LESSONS)


class BreakOverlay:
    """Full-screen, always-on-top windows on every display."""

    def __init__(self):
        self.windows = []
        self.countdown_labels = []
        self.lesson_labels = []

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
        heading = (
            "Long break: stand up, stretch, look away"
            if long_break
            else "Break: look away from the screen"
        )
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
            lesson = self._label(
                "Fetching something to learn...", 24,
                ((w * 0.15, h * 0.18), (w * 0.7, h * 0.36)), alpha=0.85,
            )
            for view in (title, countdown, lesson):
                content.addSubview_(view)

            window.makeKeyAndOrderFront_(None)
            self.windows.append(window)
            self.countdown_labels.append(countdown)
            self.lesson_labels.append(lesson)
        app = NSApp()
        if app is not None:
            app.activateIgnoringOtherApps_(True)

    def set_countdown(self, seconds: int):
        for label in self.countdown_labels:
            label.setStringValue_(format_duration(seconds))

    def set_lesson(self, text: str):
        for label in self.lesson_labels:
            label.setStringValue_(text)

    def hide(self):
        for window in self.windows:
            window.orderOut_(None)
            window.close()
        self.windows = []
        self.countdown_labels = []
        self.lesson_labels = []


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
        self._pending_lesson: str | None = None
        self._lesson_generation = 0

        self.toggle_focus_mode_item = rumps.MenuItem("Focus Mode: ON")
        self.status_idle = rumps.MenuItem("Idle: --")
        self.status_youtube = rumps.MenuItem("YouTube: --")
        self.status_idle.set_callback(None)
        self.status_youtube.set_callback(None)
        self.pomodoro_toggle_item = rumps.MenuItem("Start Pomodoro")
        self.status_pomodoro = rumps.MenuItem("Pomodoro: Stopped")
        self.status_pomodoro.set_callback(None)

        self.menu = [
            self.toggle_focus_mode_item,
            None,
            self.pomodoro_toggle_item,
            self.status_pomodoro,
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
        self._lesson_generation += 1  # discard any in-flight lesson
        self.pomodoro_timer.stop()
        self.overlay.hide()
        self.pomodoro_toggle_item.title = "Start Pomodoro"
        self.status_pomodoro.title = "Pomodoro: Stopped"
        self.title = "" if self.icon else "Focus"

    def _start_work(self):
        self.phase = "work"
        self.phase_remaining = self.work_seconds

    def _start_break(self):
        self.phase = "break"
        self.completed_pomodoros += 1
        is_long = self.completed_pomodoros % POMODOROS_PER_LONG_BREAK == 0
        self.phase_remaining = self.long_break_seconds if is_long else self.break_seconds
        self._pending_lesson = None
        self._lesson_generation += 1
        generation = self._lesson_generation
        self._play_alert()
        self.overlay.show(self.phase_remaining, long_break=is_long)

        def worker():
            text = fetch_lesson()
            if generation == self._lesson_generation:
                self._pending_lesson = text

        threading.Thread(target=worker, daemon=True).start()

    def pomodoro_tick(self, _):
        if not self.pomodoro_running:
            return
        self.phase_remaining -= 1

        if self.phase == "break":
            if self._pending_lesson is not None:
                self.overlay.set_lesson(self._pending_lesson)
                self._pending_lesson = None
            self.overlay.set_countdown(self.phase_remaining)
            self.status_pomodoro.title = f"Break: {format_duration(self.phase_remaining)}"
            self.title = f"Break {format_duration(self.phase_remaining)}"
            if self.phase_remaining <= 0:
                self._lesson_generation += 1
                self.overlay.hide()
                self._play_alert()
                self._start_work()
            return

        done = self.completed_pomodoros % POMODOROS_PER_LONG_BREAK
        self.status_pomodoro.title = (
            f"Work {done + 1}/{POMODOROS_PER_LONG_BREAK}: "
            f"{format_duration(self.phase_remaining)}"
        )
        self.title = format_duration(self.phase_remaining)
        if self.phase_remaining <= 0:
            self._start_break()

    def quit_app(self, _):
        rumps.quit_application()

    def run(self, **options):
        self.timer.start()
        super().run(**options)


if __name__ == "__main__":
    app = FocusModeApp()
    app.run()
