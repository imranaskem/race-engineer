# LMU AI Race Engineer

An AI-powered voice race engineer for [Le Mans Ultimate](https://www.lemansultimate.com/). Talk to your engineer over push-to-talk during a race and get real-time strategy advice — fuel windows, pit timing, gap analysis, tyre wear — based on live telemetry.

## How it works

1. **Hold SPACE** (or a wheel button) to talk ("What's my fuel situation?", "Should I pit this lap?")
2. **Whisper** transcribes your voice locally on your machine
3. **Claude** reasons over live telemetry + strategy calculations and responds
4. **ElevenLabs** voices the response — first words play within ~1 second

Automatic alerts are voiced when triggered: FCY, low fuel, tyre wear critical.

## Windows — download and run (no coding required)

1. Download the latest `LMU-Race-Engineer-x.x.x-windows.zip` from the [Releases](../../releases) page
2. Extract the zip anywhere
3. Double-click **LMU-Race-Engineer.exe** to launch
4. Click **Settings** and enter your API keys
5. Start LMU, get in a session, then click **Start** in the app

The app window shows a live log. Hold **SPACE** to talk to your engineer. If API keys aren't set, the Settings dialog opens automatically when you click Start.

### API keys

| Key | Where to get it |
|---|---|
| Anthropic (Claude) | [console.anthropic.com](https://console.anthropic.com/) |
| ElevenLabs (voice) | [elevenlabs.io/app/settings/api-keys](https://elevenlabs.io/app/settings/api-keys) |

### Push-to-talk options

**Keyboard (default)** — hold SPACE. Change the key in Settings.

**Steering wheel button** — set PTT Type to `joystick` in Settings and enter your button code. Launch once, press buttons on your wheel, and the log shows each button code so you can set the right one.

---

## Stack

| Layer | Technology |
|---|---|
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `small.en` |
| AI | Claude `claude-opus-4-6` via Anthropic API |
| Text-to-speech | ElevenLabs `eleven_turbo_v2_5` |
| Push-to-talk | pynput keyboard / `inputs` joystick |
| Audio I/O | sounddevice |
| UI | PySide6 (Windows); terminal (Mac/Linux) |
| Telemetry | rF2 shared memory (Windows + LMU) / mock provider (dev) |

## Latency

| Stage | Target |
|---|---|
| PTT release -> STT result | ~300-600ms |
| STT -> first Claude token | ~200-400ms |
| First Claude token -> first audio | ~300-500ms |
| **PTT release -> first word heard** | **~800-1500ms** |

Sentence-buffered TTS means the driver hears the start of the response while Claude is still generating the rest.

---

## Developer setup (Mac/Linux)

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key
- ElevenLabs API key

### Install and run

```bash
git clone <repo>
cd race-engineer
uv sync
cp .env.example .env
# edit .env with your API keys
uv run python main.py
```

On Mac/Linux the app runs in terminal mode with a mock telemetry provider (realistic GT3 endurance race simulation). The Whisper model downloads on first run (~150 MB).

### Tests

```bash
uv run pytest tests/ -v
```

### Building the Windows exe

Requires a Windows machine (or the GitHub Actions release workflow — push a `v*` tag to trigger it):

```bash
uv run python create_icon.py      # generate images/icon.ico (once)
uv run python freeze_pyinstaller.py --release
```

Output: `dist/LMU-Race-Engineer/` + a versioned zip ready for release.

## Project structure

```
race-engineer/
├── main.py                  # entry point — Qt UI on Windows, terminal on Mac/Linux
├── config.py                # all constants and env vars
├── ui/
│   ├── app.py               # PySide6 main window + settings dialog
│   └── worker.py            # asyncio engine in a QThread
├── telemetry/
│   ├── provider.py          # TelemetryState dataclass + abstract base
│   ├── mock.py              # MockTelemetryProvider for dev
│   ├── rf2_shared_memory.py # live LMU telemetry via rF2 shared memory
│   ├── aggregator.py        # rolling averages, lap deltas, edge-triggered alerts
│   └── __init__.py          # selects provider by platform
├── voice/
│   ├── stt.py               # WhisperSTT — PTT recording + transcription
│   └── tts.py               # ElevenLabsTTS — sentence-buffered streaming playback
├── engineer/
│   ├── agent.py             # RaceEngineerAgent — Claude with telemetry context
│   └── strategy.py          # deterministic fuel/pit/tyre calculations
└── tests/
    └── test_aggregator.py
```
