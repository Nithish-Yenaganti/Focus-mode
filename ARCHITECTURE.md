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
        Overlay["BreakOverlay<br/>NSWindow per NSScreen"]
        Worker["Lesson worker<br/>daemon thread"]
        Alerts["Alerts<br/>afplay + notification"]
    end
    Quartz["Quartz HID idle API"]
    Browser["Chrome / Safari<br/>via AppleScript"]
    CLI["claude CLI<br/>-p --no-session-persistence"]
    Fallback["Built-in lessons"]

    User <--> Menu
    Menu -->|start / stop / settings| PomoTimer
    PollTimer -->|idle seconds| Quartz
    PollTimer -->|frontmost tab URL| Browser
    PollTimer -->|limit reached| Alerts
    PomoTimer -->|break starts| Overlay
    PomoTimer -->|break starts| Worker
    Worker -->|prompt| CLI
    CLI -->|lesson text| Worker
    Worker -.->|CLI missing / slow| Fallback
    Worker -->|pending lesson| PomoTimer
    PomoTimer -->|countdown + lesson| Overlay
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
    participant W as Worker thread
    participant C as claude CLI

    T->>T: work time reaches 0
    T->>T: completed_pomodoros += 1, pick break length
    T->>O: show(seconds, long_break)
    T->>W: start thread (generation N)
    W->>C: claude -p "teach me about <topic>" --model haiku --no-session-persistence --tools ""
    C-->>W: lesson text (or error / timeout)
    W->>W: fallback lesson if needed
    W-->>T: _pending_lesson (only if generation still N)
    loop every second
        T->>O: set_countdown(remaining)
        T->>O: set_lesson(text) once available
    end
    T->>O: hide() at 0, play sound
    T->>T: start next work phase
```

## Key design decisions
- **One process, two timers.** A 5s `poll` handles idle/YouTube; a 1s `pomodoro_tick` drives phases. `poll` returns early during breaks.
- **UI only on the main thread.** The worker thread only writes `_pending_lesson`; the 1s tick applies it to the overlay.
- **Generation counter.** Stop or a new phase bumps `_lesson_generation`, so a slow lesson can't appear in a later break.
- **Overlay.** One borderless `NSWindow` per screen at `CGShieldingWindowLevel`, on all Spaces.
- **No chat history.** The lesson call uses `--no-session-persistence` and `--tools ""`, and runs from a temp directory.
- **Graceful fallback.** Missing CLI, error or 45s timeout shows one of the built-in lessons.

See [PROJECT.md](PROJECT.md) for the feature overview.
