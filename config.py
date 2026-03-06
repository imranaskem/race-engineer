import os
import sys

from dotenv import load_dotenv

# When running as a PyInstaller frozen exe, load .env from alongside the exe.
# When running from source, load_dotenv() searches upward from cwd as normal.
if getattr(sys, "frozen", False):
    _base_dir = os.path.dirname(sys.executable)
    load_dotenv(os.path.join(_base_dir, ".env"))
else:
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
ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "onwK4e9ZLuTAKqWW03F9")
ELEVENLABS_MODEL: str = "eleven_turbo_v2_5"  # lowest latency model
# PCM 22050Hz 16-bit — play directly with sounddevice, no decoding needed
ELEVENLABS_OUTPUT_FORMAT: str = "pcm_22050"
TTS_SAMPLE_RATE: int = 22050

# Audio input
STT_SAMPLE_RATE: int = 16000
STT_CHANNELS: int = 1

# Push-to-talk — set PTT_TYPE to "keyboard" or "joystick"
PTT_TYPE: str = os.getenv("PTT_TYPE", "keyboard")

# Keyboard PTT: pynput key name (e.g. "space", "f1", "ctrl")
PTT_KEY: str = os.getenv("PTT_KEY", "space")

# Joystick PTT: device index and button code from the `inputs` library
# Run with PTT_TYPE=joystick to see button codes logged on press
PTT_JOYSTICK_DEVICE: int = int(os.getenv("PTT_JOYSTICK_DEVICE", "0"))
PTT_JOYSTICK_BUTTON: str = os.getenv("PTT_JOYSTICK_BUTTON", "BTN_TRIGGER")

# Telemetry polling
TELEMETRY_POLL_INTERVAL: float = 0.2  # seconds (5fps matches scoring buffer)

# Aggregator rolling window size (laps)
AGGREGATOR_WINDOW_LAPS: int = 5

# Alert cooldown — minimum seconds between the same alert being voiced
ALERT_COOLDOWN_S: float = 60.0
