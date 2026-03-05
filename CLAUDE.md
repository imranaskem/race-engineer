# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run the app
uv run python main.py

# Run all tests
uv run pytest tests/ -v

# Run a single test file or test
uv run pytest tests/test_aggregator.py::TestAlerts::test_fcy_alert_triggered -v

# Add a dependency
uv add <package>
```

Never use `uv pip install` — always `uv add`.

## Architecture

Three asyncio tasks run concurrently in `main.py`:

1. **`telemetry_loop`** — polls `TelemetryProvider` → feeds `TelemetryAggregator` → pushes edge-triggered alerts to `alert_queue`
2. **`engineer_loop`** — drains `query_queue` (driver PTT questions) and `alert_queue`; calls `compute_strategy()` then `RaceEngineerAgent.respond_stream()` → streams text to `ElevenLabsTTS`
3. PTT audio recording runs as threads managed by `WhisperSTT`, posting transcripts into `query_queue`

### Telemetry layer (`telemetry/`)

- `provider.py` — `TelemetryState` dataclass (single source of truth for all game state) + abstract `TelemetryProvider`
- `__init__.py` — auto-selects `RF2SharedMemoryProvider` on Windows, `MockTelemetryProvider` on Mac/Linux
- `aggregator.py` — consumes `TelemetryState` snapshots, maintains rolling windows over the last N laps, computes derived metrics (`avg_fuel_per_lap`, `laps_of_fuel_remaining`, `avg_lap_time`, corner deltas), and returns edge-triggered `Alert` objects
- `rf2_shared_memory.py` — reads LMU's single `"LMU_Data"` shared memory file using `SimInfo` from `lmu_data.py`; no additional plugins required
- `lmu_data.py` — vendored ctypes struct definitions from [pyLMUSharedMemory](https://github.com/TinyPedal/pyLMUSharedMemory) (TinyPedal team), derived from S397's official `SharedMemoryInterface` header; uses `_pack_ = 4`

### Engineer layer (`engineer/`)

- `strategy.py` — deterministic math only (fuel laps remaining, pit window, fuel-to-add, tyre life estimate); produces `StrategySnapshot` injected into every Claude call
- `agent.py` — `RaceEngineerAgent` wraps the Anthropic streaming API; builds a user message combining `TelemetryAggregator.get_context()` + `StrategySnapshot.as_text()` + the driver's spoken query; keeps last 20 turns of conversation history

### Voice layer (`voice/`)

- `stt.py` — `WhisperSTT` uses faster-whisper; holds SPACE to record (pynput), releases to transcribe; CUDA on Windows, CPU on Mac
- `tts.py` — `ElevenLabsTTS` splits Claude streaming output at sentence boundaries (`[.!?]`), synthesises each sentence immediately via ElevenLabs, plays PCM 22050Hz via sounddevice; first audio within ~600–900ms

### Data flow through a driver query

```
PTT hold → sounddevice recording
PTT release → faster-whisper → transcript → query_queue
engineer_loop → aggregator.get_context() + compute_strategy()
  → RaceEngineerAgent.respond_stream() → Claude API (streaming)
    → ElevenLabsTTS.stream_speak() → sentence buffer → ElevenLabs → sounddevice
```

## Key constants (`config.py`)

| Constant | Value | Note |
|---|---|---|
| `CLAUDE_MODEL` | `claude-opus-4-6` | No adaptive thinking (latency) |
| `WHISPER_MODEL` | `small.en` | CUDA on Windows, CPU on Mac |
| `ELEVENLABS_MODEL` | `eleven_turbo_v2_5` | Lowest latency |
| `ELEVENLABS_OUTPUT_FORMAT` | `pcm_22050` | No decode needed |
| `TELEMETRY_POLL_INTERVAL` | `0.2s` | Matches scoring buffer ~5fps |
| `AGGREGATOR_WINDOW_LAPS` | `5` | Rolling average window |

## Environment

Copy `.env.example` to `.env` and fill in `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, and optionally `ELEVENLABS_VOICE_ID`.
