# LMU AI Race Engineer

An AI-powered voice race engineer for [Le Mans Ultimate](https://www.lemansultimate.com/). Talk to your engineer over push-to-talk during a race and get real-time strategy advice — fuel windows, pit timing, gap analysis, tyre wear — based on live telemetry.

## How it works

1. **Hold SPACE** to talk ("What's my fuel situation?", "Should I pit this lap?")
2. **Whisper** transcribes your voice locally
3. **Claude** reasons over live telemetry + strategy calculations and responds
4. **ElevenLabs** voices the response — first words play within ~1 second

Automatic alerts are voiced when triggered: FCY, low fuel, tyre wear critical.

## Stack

| Layer | Technology |
|---|---|
| Speech-to-text | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) `small.en` |
| AI | Claude `claude-opus-4-6` via Anthropic API |
| Text-to-speech | ElevenLabs `eleven_turbo_v2_5` |
| Push-to-talk | pynput keyboard listener |
| Audio I/O | sounddevice |
| Telemetry (dev) | Mock provider — realistic GT3 endurance race simulation |
| Telemetry (prod) | rF2 shared memory reader *(Windows, coming soon)* |

## Setup

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Anthropic API key (with credits)
- ElevenLabs API key

### Install

```bash
git clone <repo>
cd race-engineer
uv sync
```

### Configure

```bash
cp .env.example .env
```

Edit `.env`:

```
ANTHROPIC_API_KEY=your_key_here
ELEVENLABS_API_KEY=your_key_here
ELEVENLABS_VOICE_ID=onwK4e9ZLuTAKqWW03F9   # Daniel — British, authoritative
```

Browse voices at [elevenlabs.io/voice-library](https://elevenlabs.io/voice-library).

### Run

```bash
uv run python main.py
```

The Whisper model downloads on first run (~150 MB). Hold **SPACE** to talk.

## Project structure

```
race-engineer/
├── main.py                  # asyncio entry point
├── config.py                # all constants and env vars
├── telemetry/
│   ├── provider.py          # TelemetryState dataclass + abstract base
│   ├── mock.py              # MockTelemetryProvider for Mac dev
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

## Tests

```bash
uv run pytest tests/ -v
```

## Windows / live telemetry

On Windows with LMU running, the app will automatically use the rF2 shared memory provider (once `telemetry/rf2_shared_memory.py` is implemented). On Mac it always uses the mock provider.

## Latency

| Stage | Target |
|---|---|
| PTT release → STT result | ~300–600ms |
| STT → first Claude token | ~200–400ms |
| First Claude token → first audio | ~300–500ms |
| **PTT release → first word heard** | **~800–1500ms** |

Sentence-buffered TTS means the driver hears the start of the response while Claude is still generating the rest.
