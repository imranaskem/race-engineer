"""
LMU AI Race Engineer — asyncio entry point.

Three concurrent tasks:
  1. telemetry_loop  — polls TelemetryProvider, feeds TelemetryAggregator
  2. voice_input     — PTT recording → Whisper STT → engineer_queue
  3. engineer_loop   — dequeues driver queries, calls Claude, streams to TTS

Automatic alerts (FCY, low fuel, tyre wear) are voiced as they trigger.
"""
import asyncio
import logging
import sys

import config
from telemetry import TelemetryProvider, TelemetryAggregator
from voice.stt import WhisperSTT
from voice.tts import ElevenLabsTTS
from engineer.agent import RaceEngineerAgent
from engineer.strategy import compute_strategy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


async def telemetry_loop(
    provider: TelemetryProvider,
    aggregator: TelemetryAggregator,
    alert_queue: asyncio.Queue,
) -> None:
    """Poll telemetry and feed the aggregator. Push alerts to alert_queue."""
    log.info("Telemetry loop started.")
    while True:
        state = await provider.get_state()
        new_alerts = aggregator.update(state)
        for alert in new_alerts:
            log.info("ALERT: %s", alert.key)
            await alert_queue.put(alert.message)
        await asyncio.sleep(config.TELEMETRY_POLL_INTERVAL)


async def engineer_loop(
    agent: RaceEngineerAgent,
    aggregator: TelemetryAggregator,
    query_queue: asyncio.Queue,
    alert_queue: asyncio.Queue,
    tts: ElevenLabsTTS,
) -> None:
    """
    Process driver queries and automatic alerts.
    Queries take priority; alerts are voiced when no query is pending.
    """
    log.info("Engineer loop started.")
    while True:
        # Check for driver query first (priority)
        try:
            query = query_queue.get_nowait()
        except asyncio.QueueEmpty:
            # No driver query — check for alerts
            try:
                alert_msg = alert_queue.get_nowait()
                log.info("Voicing alert: %s", alert_msg)
                await tts.speak(alert_msg)
            except asyncio.QueueEmpty:
                await asyncio.sleep(0.05)
            continue

        log.info("Driver query: %s", query)
        context = aggregator.get_context()
        strategy = compute_strategy(context)

        async def _text_gen():
            async for chunk in agent.respond_stream(query, strategy):
                yield chunk

        await tts.stream_speak(_text_gen())


async def main() -> None:
    log.info("Starting LMU AI Race Engineer.")
    log.info("Platform: %s", sys.platform)

    # --- Validate config ---
    if not config.ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill in.")
        return
    if not config.ELEVENLABS_API_KEY:
        log.error("ELEVENLABS_API_KEY not set.")
        return

    # --- Initialise components ---
    provider = TelemetryProvider()
    aggregator = TelemetryAggregator(window_laps=config.AGGREGATOR_WINDOW_LAPS)
    stt = WhisperSTT()
    tts = ElevenLabsTTS()
    agent = RaceEngineerAgent(aggregator)

    query_queue: asyncio.Queue[str] = asyncio.Queue()
    alert_queue: asyncio.Queue[str] = asyncio.Queue()

    # Load Whisper model
    await stt.load()

    # Start telemetry
    await provider.start()
    log.info("Telemetry provider started.")

    # Register PTT callback — posts transcripts to query_queue
    def on_transcript(text: str) -> None:
        query_queue.put_nowait(text)

    audio_stream = stt.start_stream()
    stt.start_keyboard_listener(on_transcript)

    print()
    print("=" * 50)
    print("  LMU AI Race Engineer — READY")
    print(f"  Hold [{config.PTT_KEY.upper()}] to talk to your engineer.")
    print("  Ctrl+C to quit.")
    print("=" * 50)
    print()

    try:
        await asyncio.gather(
            telemetry_loop(provider, aggregator, alert_queue),
            engineer_loop(agent, aggregator, query_queue, alert_queue, tts),
        )
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        stt.stop_keyboard_listener()
        audio_stream.stop()
        audio_stream.close()
        await provider.stop()
        log.info("Goodbye.")


if __name__ == "__main__":
    asyncio.run(main())
