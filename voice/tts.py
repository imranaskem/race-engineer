"""
ElevenLabsTTS — low-latency text-to-speech with sentence-level streaming.

Strategy:
  1. Accept a text generator (Claude streaming output)
  2. Buffer tokens into complete sentences at punctuation boundaries
  3. Send each sentence to ElevenLabs as soon as it's complete
  4. Play PCM audio with sounddevice, queuing sentences for gapless playback

This means the driver hears the first word of the engineer's response
within ~600–900ms of the question being asked.
"""
import asyncio
import logging
import re
from typing import AsyncIterator

import numpy as np
import sounddevice as sd
from elevenlabs.client import ElevenLabs

import config

log = logging.getLogger(__name__)

# Sentence boundary: end of sentence followed by space or end-of-string
_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+|(?<=[.!?])$')


class ElevenLabsTTS:
    def __init__(self) -> None:
        self._client = ElevenLabs(api_key=config.ELEVENLABS_API_KEY)
        self._playback_lock = asyncio.Lock()

    async def speak(self, text: str) -> None:
        """Synthesise and play a complete string."""
        await self._synthesise_and_play(text)

    async def stream_speak(self, text_stream: AsyncIterator[str]) -> None:
        """
        Consume a streaming text generator, splitting on sentence boundaries
        and playing audio for each sentence as soon as it's ready.

        Sentences are queued so playback is gapless even if synthesis is fast.
        """
        queue: asyncio.Queue[str | None] = asyncio.Queue()

        async def _producer() -> None:
            buffer = ""
            async for chunk in text_stream:
                buffer += chunk
                # Split on sentence boundaries
                parts = _SENTENCE_RE.split(buffer)
                # All parts except the last are complete sentences
                for sentence in parts[:-1]:
                    sentence = sentence.strip()
                    if sentence:
                        await queue.put(sentence)
                buffer = parts[-1]
            # Flush remaining text
            remaining = buffer.strip()
            if remaining:
                await queue.put(remaining)
            await queue.put(None)  # sentinel

        async def _consumer() -> None:
            while True:
                sentence = await queue.get()
                if sentence is None:
                    break
                await self._synthesise_and_play(sentence)

        await asyncio.gather(_producer(), _consumer())

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _synthesise_and_play(self, text: str) -> None:
        """
        Call ElevenLabs, get PCM bytes, play with sounddevice.
        Runs TTS API call in a thread to avoid blocking the event loop.
        """
        if not text.strip():
            return

        log.debug("TTS: %s", text[:60])

        try:
            pcm_bytes = await asyncio.to_thread(self._fetch_pcm, text)
        except Exception as exc:
            log.error("ElevenLabs error: %s", exc)
            return

        await asyncio.to_thread(self._play_pcm, pcm_bytes)

    def _fetch_pcm(self, text: str) -> bytes:
        """Synchronous ElevenLabs call — run in a thread executor."""
        audio_stream = self._client.text_to_speech.convert(
            voice_id=config.ELEVENLABS_VOICE_ID,
            text=text,
            model_id=config.ELEVENLABS_MODEL,
            output_format=config.ELEVENLABS_OUTPUT_FORMAT,
        )
        return b"".join(audio_stream)

    def _play_pcm(self, pcm_bytes: bytes) -> None:
        """Play raw 16-bit PCM audio synchronously via sounddevice."""
        if not pcm_bytes:
            return
        audio = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(audio, samplerate=config.TTS_SAMPLE_RATE, blocking=True)
