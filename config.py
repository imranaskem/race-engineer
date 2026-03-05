import os
import sys
from dotenv import load_dotenv

load_dotenv()

# API keys
ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")

# Claude — Opus for best reasoning quality in race-critical decisions
CLAUDE_MODEL: str = "claude-opus-4-6"

# Whisper STT — prefer CUDA on Windows, fall back to CPU if unavailable
WHISPER_MODEL: str = "small.en"

def _whisper_device() -> tuple[str, str]:
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.WinDLL("cublas64_12.dll")
            return "cuda", "float16"
        except OSError:
            return "cpu", "int8"
    return "cpu", "int8"

WHISPER_DEVICE, WHISPER_COMPUTE_TYPE = _whisper_device()

# ElevenLabs TTS
# "Adam" — calm, authoritative, works well as a race engineer
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
ELEVENLABS_MODEL: str = "eleven_turbo_v2_5"  # lowest latency model
# PCM 22050Hz 16-bit — play directly with sounddevice, no decoding needed
ELEVENLABS_OUTPUT_FORMAT: str = "pcm_22050"
TTS_SAMPLE_RATE: int = 22050

# Audio input
STT_SAMPLE_RATE: int = 16000
STT_CHANNELS: int = 1

# Push-to-talk key (pynput key name)
PTT_KEY: str = "space"

# Telemetry polling
TELEMETRY_POLL_INTERVAL: float = 0.2  # seconds (5fps matches scoring buffer)

# Aggregator rolling window size (laps)
AGGREGATOR_WINDOW_LAPS: int = 5

# Alert cooldown — minimum seconds between the same alert being voiced
ALERT_COOLDOWN_S: float = 60.0
