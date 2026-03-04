"""
RaceEngineerAgent — Claude-powered race engineer.

Injects live telemetry + strategy context into every call.
Streams responses back for low-latency TTS handoff.
"""
import json
import logging
from typing import AsyncIterator

import anthropic

import config
from telemetry.aggregator import TelemetryAggregator
from engineer.strategy import StrategySnapshot

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = """\
You are a professional Le Mans endurance race engineer. You speak directly to the driver \
via radio during a live race. Your job: give concise, accurate, immediately actionable \
information. You are calm under pressure, precise with numbers, and never waffle.

Rules:
- Keep responses SHORT — 1–3 sentences unless the driver asks for more detail.
- Lead with the most critical information first.
- Use racing terminology naturally (stint, FCY, gap, delta, compound, fuel window).
- Never say "I" — address the driver as "you" or use driver-style imperatives.
- Do not repeat back what the driver said.
- Round numbers sensibly — say "two-point-five kilos a lap" not "2.4823 kilos".
- If there is an active FCY or Safety Car, always factor that into strategy advice.
- If you don't know something from the telemetry, say so briefly rather than guessing.

Tone: experienced, calm, like a real WEC/Le Mans engineer.
"""


class RaceEngineerAgent:
    def __init__(self, aggregator: TelemetryAggregator) -> None:
        self._client = anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
        self._aggregator = aggregator
        self._conversation: list[anthropic.types.MessageParam] = []

    async def respond_stream(
        self,
        driver_query: str,
        strategy: StrategySnapshot | None = None,
    ) -> AsyncIterator[str]:
        """
        Send driver's query + live telemetry context to Claude.
        Yields text chunks as they stream — hand directly to TTS.
        """
        # Build the user message with telemetry injected
        context = self._aggregator.get_context()
        user_content = self._build_user_message(driver_query, context, strategy)

        self._conversation.append({"role": "user", "content": user_content})

        log.debug("Sending to Claude: %s", driver_query)

        response_text = ""
        async with self._client.messages.stream(
            model=config.CLAUDE_MODEL,
            max_tokens=300,  # race engineer replies are short
            system=_SYSTEM_PROMPT,
            messages=self._conversation,
            # Adaptive thinking off for voice — latency matters more than depth
        ) as stream:
            async for text_chunk in stream.text_stream:
                response_text += text_chunk
                yield text_chunk

        # Maintain conversation history for follow-up questions
        self._conversation.append({"role": "assistant", "content": response_text})

        # Keep history bounded — last 10 turns is plenty
        if len(self._conversation) > 20:
            self._conversation = self._conversation[-20:]

        log.debug("Engineer response: %s", response_text)

    def reset_conversation(self) -> None:
        """Clear conversation history (e.g. at start of new stint)."""
        self._conversation.clear()

    # ------------------------------------------------------------------
    # Context building
    # ------------------------------------------------------------------

    @staticmethod
    def _build_user_message(
        query: str,
        context: dict,
        strategy: StrategySnapshot | None,
    ) -> str:
        """Combine driver query with telemetry snapshot as structured text."""
        lines = [
            "--- LIVE TELEMETRY ---",
            json.dumps(context, indent=2),
        ]
        if strategy:
            lines.append("")
            lines.append("--- STRATEGY COMPUTER ---")
            lines.append(strategy.as_text())
        lines.append("")
        lines.append(f"DRIVER: {query}")
        return "\n".join(lines)
