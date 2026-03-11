"""
WhisperSTT — push-to-talk speech-to-text using faster-whisper.

Usage:
    stt = WhisperSTT()
    await stt.load()
    transcript = await stt.listen()   # blocks until PTT released and transcribed
"""
import asyncio
import logging
import threading
from typing import Callable

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from pynput import keyboard

import config

log = logging.getLogger(__name__)


class WhisperSTT:
    def __init__(self) -> None:
        self._model: WhisperModel | None = None
        self._recording = threading.Event()
        self._audio_chunks: list[np.ndarray] = []
        self._lock = threading.Lock()
        self._listener: keyboard.Listener | None = None
        self._joystick_running = False
        self._on_listening_start: Callable[[], None] | None = None
        self._on_listening_end: Callable[[], None] | None = None

    async def load(self) -> None:
        """Load the Whisper model (blocking, run once at startup)."""
        log.info("Loading Whisper model '%s' on %s...", config.WHISPER_MODEL, config.WHISPER_DEVICE)
        self._model = await asyncio.to_thread(
            WhisperModel,
            config.WHISPER_MODEL,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
        log.info("Whisper model loaded.")

    def start_keyboard_listener(
        self,
        on_transcript: Callable[[str], None],
        on_quit: Callable[[], None] | None = None,
        on_no_speech: Callable[[], None] | None = None,
    ) -> None:
        """
        Start a background keyboard listener for push-to-talk.
        Calls on_transcript(text) when a recording is transcribed.
        Calls on_quit() when ESC is pressed (if provided).
        Calls on_no_speech() when PTT is released but nothing was detected.
        Both callbacks are expected to be thread-safe.
        """
        def _on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
            try:
                if key == keyboard.Key.esc and on_quit is not None:
                    on_quit()
                    return
                if str(key) == f"Key.{config.PTT_KEY}" or (
                    hasattr(key, "char") and key.char == config.PTT_KEY
                ):
                    if not self._recording.is_set():
                        self._start_recording()
            except Exception:
                pass

        def _on_release(key: keyboard.Key | keyboard.KeyCode) -> None:
            try:
                if str(key) == f"Key.{config.PTT_KEY}" or (
                    hasattr(key, "char") and key.char == config.PTT_KEY
                ):
                    if self._recording.is_set():
                        audio = self._stop_recording()
                        if audio is not None and len(audio) > config.STT_SAMPLE_RATE * 0.3:
                            # Transcribe in a thread so we don't block the listener
                            def _transcribe_and_post() -> None:
                                try:
                                    text = self._transcribe(audio)
                                except Exception:
                                    log.exception("Transcription error")
                                    text = ""
                                if text:
                                    on_transcript(text)
                                elif on_no_speech:
                                    on_no_speech()

                            threading.Thread(target=_transcribe_and_post, daemon=True).start()
                        elif on_no_speech:
                            on_no_speech()
            except Exception:
                pass

        self._listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        self._listener.start()
        log.info("PTT listener started — hold SPACE to talk. Press ESC to quit.")

    def stop_keyboard_listener(self) -> None:
        if self._listener:
            self._listener.stop()

    def start_joystick_listener(
        self,
        on_transcript: Callable[[str], None],
        on_no_speech: Callable[[], None] | None = None,
    ) -> None:
        """
        Start a background thread that polls for joystick/wheel button events.
        Uses the `inputs` library. PTT button is config.PTT_JOYSTICK_BUTTON
        (an `inputs` event code, e.g. 'BTN_TRIGGER').
        All button presses are logged so you can discover the right code for
        your wheel.
        """
        try:
            import inputs as _inputs
        except ImportError:
            raise RuntimeError("The 'inputs' package is required for joystick PTT. Run: uv add inputs")

        self._joystick_running = True

        def _joystick_thread() -> None:
            controllers = _inputs.devices.gamepads
            if not controllers:
                log.error(
                    "No game controller/wheel found (PTT_TYPE=joystick). "
                    "Check device is connected or switch to PTT_TYPE=keyboard."
                )
                return
            device = controllers[config.PTT_JOYSTICK_DEVICE] if config.PTT_JOYSTICK_DEVICE < len(controllers) else controllers[0]
            log.info("Joystick PTT active — device: '%s', button: '%s'", device.name, config.PTT_JOYSTICK_BUTTON)

            while self._joystick_running:
                try:
                    events = device.read()
                except Exception as exc:
                    log.error("Joystick read error: %s", exc)
                    break
                for event in events:
                    if event.ev_type != "Key":
                        continue
                    log.debug("Joystick button event: code=%s state=%s", event.code, event.state)
                    if event.code != config.PTT_JOYSTICK_BUTTON:
                        # Log unmatched presses so users can discover their button code
                        if event.state == 1:
                            log.info(
                                "Joystick button pressed (not PTT): code='%s' — "
                                "set PTT_JOYSTICK_BUTTON=%s to use this button",
                                event.code, event.code,
                            )
                        continue
                    if event.state == 1 and not self._recording.is_set():
                        self._start_recording()
                    elif event.state == 0 and self._recording.is_set():
                        audio = self._stop_recording()
                        if audio is not None and len(audio) > config.STT_SAMPLE_RATE * 0.3:
                            def _transcribe_and_post() -> None:
                                try:
                                    text = self._transcribe(audio)
                                except Exception:
                                    log.exception("Transcription error")
                                    text = ""
                                if text:
                                    on_transcript(text)
                                elif on_no_speech:
                                    on_no_speech()
                            threading.Thread(target=_transcribe_and_post, daemon=True).start()
                        elif on_no_speech:
                            on_no_speech()

        threading.Thread(target=_joystick_thread, daemon=True).start()
        log.info("Joystick PTT listener started.")

    def stop_joystick_listener(self) -> None:
        self._joystick_running = False

    def start_ptt_listener(
        self,
        on_transcript: Callable[[str], None],
        on_quit: Callable[[], None] | None = None,
        on_listening_start: Callable[[], None] | None = None,
        on_listening_end: Callable[[], None] | None = None,
        on_no_speech: Callable[[], None] | None = None,
    ) -> None:
        """Start the configured PTT listener (keyboard or joystick)."""
        self._on_listening_start = on_listening_start
        self._on_listening_end = on_listening_end
        if config.PTT_TYPE == "joystick":
            self.start_joystick_listener(on_transcript, on_no_speech=on_no_speech)
        else:
            self.start_keyboard_listener(on_transcript, on_quit=on_quit, on_no_speech=on_no_speech)

    def stop_ptt_listener(self) -> None:
        """Stop whichever PTT listener is running."""
        if config.PTT_TYPE == "joystick":
            self.stop_joystick_listener()
        else:
            self.stop_keyboard_listener()

    # ------------------------------------------------------------------
    # Recording — public API for Qt key-event PTT (macOS)
    # ------------------------------------------------------------------

    def begin_ptt(self) -> None:
        """Start recording. Thread-safe; can be called from the Qt main thread."""
        if not self._recording.is_set():
            self._start_recording()

    def end_ptt(self) -> np.ndarray | None:
        """Stop recording and return captured audio (or None). Thread-safe."""
        if self._recording.is_set():
            return self._stop_recording()
        return None

    # ------------------------------------------------------------------
    # Recording (internal)
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        with self._lock:
            self._audio_chunks.clear()
        self._recording.set()
        if self._on_listening_start:
            self._on_listening_start()
        log.debug("Recording started.")

    def _stop_recording(self) -> np.ndarray | None:
        self._recording.clear()
        if self._on_listening_end:
            self._on_listening_end()
        with self._lock:
            if not self._audio_chunks:
                return None
            audio = np.concatenate(self._audio_chunks, axis=0).flatten()
        rms = float(np.sqrt(np.mean(audio ** 2)))
        log.info("Recording stopped. %.1f s captured, RMS level: %.4f.", len(audio) / config.STT_SAMPLE_RATE, rms)
        return audio

    def _audio_callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: sd.CallbackFlags,
    ) -> None:
        if self._recording.is_set():
            with self._lock:
                self._audio_chunks.append(indata.copy())

    def start_stream(self) -> sd.InputStream:
        """Open and return the sounddevice input stream. Must be kept alive."""
        default_device = sd.query_devices(kind="input")
        log.info("Audio input device: %s", default_device.get("name", "unknown"))
        stream = sd.InputStream(
            samplerate=config.STT_SAMPLE_RATE,
            channels=config.STT_CHANNELS,
            dtype="float32",
            callback=self._audio_callback,
            blocksize=1024,
        )
        stream.start()
        return stream

    # ------------------------------------------------------------------
    # Transcription
    # ------------------------------------------------------------------

    def _transcribe(self, audio: np.ndarray) -> str:
        """Run faster-whisper on a float32 mono audio array. Returns transcript."""
        if self._model is None:
            raise RuntimeError("Model not loaded. Call load() first.")

        # faster-whisper expects float32 mono audio normalised to [-1, 1]
        audio = audio.astype(np.float32)
        if audio.max() > 1.0:
            audio = audio / 32768.0

        transcribe_kwargs: dict = dict(beam_size=5, language="en", vad_filter=config.STT_VAD_FILTER)
        if config.STT_VAD_FILTER:
            transcribe_kwargs["vad_parameters"] = {
                "min_silence_duration_ms": 300,
                "threshold": 0.1,  # lowered — more sensitive on noisy Windows setups
            }
        segments, _info = self._model.transcribe(audio, **transcribe_kwargs)
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            log.info("STT: %s", text)
        else:
            log.info("STT: (no speech detected)")
        return text
