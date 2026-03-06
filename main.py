"""
LMU AI Race Engineer — entry point.

Windows: launches the Qt UI (ui/app.py).
Mac/Linux: runs the terminal asyncio loop directly.
"""
import sys


def _run_terminal() -> None:
    """Terminal mode for Mac/Linux development."""
    import asyncio
    import logging

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

    async def telemetry_loop(provider, aggregator, alert_queue):
        log.info("Telemetry loop started.")
        while True:
            state = await provider.get_state()
            for alert in aggregator.update(state):
                log.info("ALERT: %s", alert.key)
                await alert_queue.put(alert.message)
            await asyncio.sleep(config.TELEMETRY_POLL_INTERVAL)

    async def engineer_loop(agent, aggregator, query_queue, alert_queue, tts):
        log.info("Engineer loop started.")
        while True:
            try:
                query = query_queue.get_nowait()
            except asyncio.QueueEmpty:
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

    async def main():
        log.info("Starting LMU AI Race Engineer (terminal mode).")
        log.info("Platform: %s", sys.platform)

        if not config.ANTHROPIC_API_KEY:
            log.error("ANTHROPIC_API_KEY not set. Copy .env.example to .env and fill in.")
            return
        if not config.ELEVENLABS_API_KEY:
            log.error("ELEVENLABS_API_KEY not set.")
            return

        provider = TelemetryProvider()
        aggregator = TelemetryAggregator(window_laps=config.AGGREGATOR_WINDOW_LAPS)
        stt = WhisperSTT()
        tts = ElevenLabsTTS()
        agent = RaceEngineerAgent(aggregator)

        query_queue: asyncio.Queue[str] = asyncio.Queue()
        alert_queue: asyncio.Queue[str] = asyncio.Queue()

        await stt.load()
        await provider.start()
        log.info("Telemetry provider started.")

        def on_transcript(text: str) -> None:
            query_queue.put_nowait(text)

        audio_stream = stt.start_stream()

        if config.PTT_TYPE == "joystick":
            ptt_label = f"joystick button [{config.PTT_JOYSTICK_BUTTON}]"
        else:
            ptt_label = f"keyboard key [{config.PTT_KEY.upper()}]"

        print()
        print("=" * 50)
        print("  LMU AI Race Engineer — READY")
        print(f"  Hold {ptt_label} to talk to your engineer.")
        if config.PTT_TYPE == "keyboard":
            print("  Press [ESC] to quit.")
        else:
            print("  Press Ctrl+C to quit.")
        print("=" * 50)
        print()

        stop_event = asyncio.Event()

        def _on_quit() -> None:
            log.info("ESC pressed — shutting down.")
            stop_event.set()

        stt.start_ptt_listener(on_transcript, on_quit=_on_quit)

        try:
            tasks = [
                asyncio.create_task(telemetry_loop(provider, aggregator, alert_queue)),
                asyncio.create_task(engineer_loop(agent, aggregator, query_queue, alert_queue, tts)),
                asyncio.create_task(stop_event.wait()),
            ]
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        except KeyboardInterrupt:
            log.info("Shutting down.")
        finally:
            stt.stop_ptt_listener()
            audio_stream.stop()
            audio_stream.close()
            await provider.stop()
            log.info("Goodbye.")

    asyncio.run(main())


if __name__ == "__main__":
    if sys.platform == "win32":
        from ui.app import run
        run()
    else:
        _run_terminal()
