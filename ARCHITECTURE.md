# Architecture

Focus Mode is a single-process macOS menu bar app (`focus_mode.py`) built on `rumps` and PyObjC.

## Components

```mermaid
flowchart TD
    User([User])
    subgraph App["Focus Mode.app (single process)"]
        Menu["Menu bar UI<br/>FocusModeApp (rumps)"]
        PollTimer["poll() timer<br/>every 5s"]
        PomoTimer["pomodoro_tick() timer<br/>every 1s"]
        Overlay["BreakOverlay<br/>NSWindow per NSScreen<br/>countdown + short tip"]
        Alerts["Alerts<br/>afplay + notification"]
    end
    Quartz["Quartz HID idle API"]
    Browser["Chrome / Safari<br/>via AppleScript"]

    User <--> Menu
    Menu -->|start / stop / settings| PomoTimer
    PollTimer -->|idle seconds| Quartz
    PollTimer -->|frontmost tab URL| Browser
    PollTimer -->|limit reached| Alerts
    PomoTimer -->|break starts: show| Overlay
    PomoTimer -->|every second: countdown| Overlay
    PomoTimer -->|break ends: hide| Overlay
    PomoTimer -->|phase change| Alerts
    Overlay --> User
```

## Pomodoro state machine

```mermaid
stateDiagram-v2
    [*] --> Stopped
    Stopped --> Work: Start Pomodoro
    Work --> ShortBreak: 25 min done (pomodoro 1-3)
    Work --> LongBreak: 25 min done (every 4th)
    ShortBreak --> Work: 5 min done
    LongBreak --> Work: 15 min done
    Work --> Stopped: Stop
    ShortBreak --> Stopped: Stop
    LongBreak --> Stopped: Stop
```

## Break sequence

```mermaid
sequenceDiagram
    participant T as pomodoro_tick (1s)
    participant O as BreakOverlay
    participant U as User

    T->>T: work time reaches 0
    T->>T: completed_pomodoros += 1, pick break length
    T->>U: play sound
    T->>O: show(seconds, long_break)
    O->>O: cover every screen, pick a random tip
    loop every second
        T->>O: set_countdown(remaining)
    end
    T->>O: hide() at 0
    T->>U: play sound
    T->>T: start next work phase
```

## Key design decisions
- **One process, two timers.** A 5s `poll` handles idle/YouTube; a 1s `pomodoro_tick` drives phases. `poll` returns early during breaks.
- **Overlay.** One borderless `NSWindow` per screen at `CGShieldingWindowLevel`, on all Spaces.
- **Screen-free breaks.** The overlay shows only a countdown and one short tip. Nothing to read, so you actually look away.
- **No network, no external tools.** Everything runs locally, with no dependency on any CLI or service.

See [PROJECT.md](PROJECT.md) for the feature overview.
