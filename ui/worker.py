"""
EngineWorker — asyncio race engineer running in a QThread.

Emits Qt signals so the UI can reflect status and log updates.

PTT (pynput) is intentionally NOT started here — on macOS, the
HIToolbox keyboard APIs require the main thread. The worker emits
`ptt_ready` carrying the WhisperSTT instance; MainWindow starts the
pynput listener on the main thread and calls post_transcript() to
feed queries back into the asyncio loop.
"""
import asyncio
import logging

from PySide6.QtCore import QThread, Signal

import config
from engineer.agent import RaceEngineerAgent
from engineer.strategy import compute_strategy
from telemetry import TelemetryAggregator, TelemetryProvider
from voice.stt import WhisperSTT
from voice.tts import ElevenLabsTTS

log = logging.getLogger(__name__)

STATUS_IDLE = "idle"
STATUS_LOADING = "loading"
STATUS_READY = "ready"
STATUS_LISTENING = "listening"
STATUS_THINKING = "thinking"
STATUS_SPEAKING = "speaking"
STATUS_ERROR = "error"


class EngineWorker(QThread):
    """Runs the full asyncio engine loop in a background thread."""

    status_changed = Signal(str)   # one of the STATUS_* constants
    log_entry = Signal(str, str)   # (category, text)
    ptt_ready = Signal(object)     # carries WhisperSTT — main thread must start listener

    def __init__(self) -> None:
        super().__init__()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._query_queue: asyncio.Queue | None = None  # fed by post_transcript()

    # ------------------------------------------------------------------
    # Thread-safe public API (called from main thread)
    # ------------------------------------------------------------------

    def request_stop(self) -> None:
        if self._loop and self._stop_event:
            self._loop.call_soon_threadsafe(self._stop_event.set)

    def post_transcript(self, text: str) -> None:
        """Called from main thread (pynput callback) to feed a query."""
        if self._loop and self._query_queue:
            self._loop.call_soon_threadsafe(self._query_queue.put_nowait, text)

    # ------------------------------------------------------------------
    # QThread entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_main())
        except BaseException as exc:
            log.exception("Worker crashed")
            self.log_entry.emit("system", f"Fatal error: {type(exc).__name__}: {exc}")
            self.status_changed.emit(STATUS_ERROR)
        finally:
            self._loop.close()
            self._loop = None
            self.status_changed.emit(STATUS_IDLE)

    # ------------------------------------------------------------------
    # Async engine
    # ------------------------------------------------------------------

    async def _async_main(self) -> None:
        self.status_changed.emit(STATUS_LOADING)
        self.log_entry.emit("system", "Loading Whisper model…")

        provider = TelemetryProvider()
        aggregator = TelemetryAggregator(window_laps=config.AGGREGATOR_WINDOW_LAPS)
        stt = WhisperSTT()
        tts = ElevenLabsTTS()
        agent = RaceEngineerAgent(aggregator)

        self._query_queue = asyncio.Queue()
        alert_queue: asyncio.Queue[str] = asyncio.Queue()
        self._stop_event = asyncio.Event()

        await stt.load()
        self.log_entry.emit("system", "Whisper ready.")

        await provider.start()

        # Start audio capture (sounddevice — fine in any thread)
        audio_stream = stt.start_stream()

        # Signal main thread to start pynput listener there (macOS requires main thread)
        self.ptt_ready.emit(stt)

        self.status_changed.emit(STATUS_READY)
        if config.PTT_TYPE == "joystick":
            ptt_label = f"joystick [{config.PTT_JOYSTICK_BUTTON}]"
        else:
            ptt_label = f"[{config.PTT_KEY.upper()}]"
        self.log_entry.emit("system", f"Ready — hold {ptt_label} to talk.")

        try:
            tasks = [
                asyncio.create_task(self._telemetry_loop(provider, aggregator, alert_queue)),
                asyncio.create_task(self._engineer_loop(agent, aggregator, alert_queue, tts)),
                asyncio.create_task(self._stop_event.wait()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        finally:
            audio_stream.stop()
            audio_stream.close()
            await provider.stop()
            self.log_entry.emit("system", "Engineer stopped.")

    async def _telemetry_loop(
        self,
        provider: TelemetryProvider,
        aggregator: TelemetryAggregator,
        alert_queue: asyncio.Queue,
    ) -> None:
        assert self._stop_event is not None
        while not self._stop_event.is_set():
            state = await provider.get_state()
            for alert in aggregator.update(state):
                await alert_queue.put(alert.message)
            await asyncio.sleep(config.TELEMETRY_POLL_INTERVAL)

    async def _engineer_loop(
        self,
        agent: RaceEngineerAgent,
        aggregator: TelemetryAggregator,
        alert_queue: asyncio.Queue,
        tts: ElevenLabsTTS,
    ) -> None:
        assert self._stop_event is not None
        assert self._query_queue is not None
        while not self._stop_event.is_set():
            try:
                query = self._query_queue.get_nowait()
            except asyncio.QueueEmpty:
                try:
                    alert_msg = alert_queue.get_nowait()
                    self.log_entry.emit("alert", alert_msg)
                    self.status_changed.emit(STATUS_SPEAKING)
                    await tts.speak(alert_msg)
                    self.status_changed.emit(STATUS_READY)
                except asyncio.QueueEmpty:
                    await asyncio.sleep(0.05)
                continue

            context = aggregator.get_context()
            strategy = compute_strategy(context)
            response_buf: list[str] = []

            async def _text_gen():
                async for chunk in agent.respond_stream(query, strategy):
                    response_buf.append(chunk)
                    yield chunk

            self.status_changed.emit(STATUS_SPEAKING)
            await tts.stream_speak(_text_gen())
            self.log_entry.emit("engineer", "".join(response_buf))
            self.status_changed.emit(STATUS_READY)
