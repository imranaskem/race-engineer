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
    ) -> None:
        """
        Start a background keyboard listener for push-to-talk.
        Calls on_transcript(text) when a recording is transcribed.
        Calls on_quit() when ESC is pressed (if provided).
        Uses asyncio.get_event_loop() so the callback posts back to the event loop.
        """
        loop = asyncio.get_event_loop()

        def _on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
            try:
                if key == keyboard.Key.esc and on_quit is not None:
                    loop.call_soon_threadsafe(on_quit)
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
                                text = self._transcribe(audio)
                                if text:
                                    loop.call_soon_threadsafe(on_transcript, text)

                            threading.Thread(target=_transcribe_and_post, daemon=True).start()
            except Exception:
                pass

        self._listener = keyboard.Listener(on_press=_on_press, on_release=_on_release)
        self._listener.start()
        log.info("PTT listener started — hold SPACE to talk. Press ESC to quit.")

    def stop_keyboard_listener(self) -> None:
        if self._listener:
            self._listener.stop()

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def _start_recording(self) -> None:
        with self._lock:
            self._audio_chunks.clear()
        self._recording.set()
        log.debug("Recording started.")

    def _stop_recording(self) -> np.ndarray | None:
        self._recording.clear()
        with self._lock:
            if not self._audio_chunks:
                return None
            audio = np.concatenate(self._audio_chunks, axis=0).flatten()
        log.debug("Recording stopped. %.1f s captured.", len(audio) / config.STT_SAMPLE_RATE)
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

        segments, _info = self._model.transcribe(
            audio,
            beam_size=5,
            language="en",
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        if text:
            log.info("STT: %s", text)
        return text
