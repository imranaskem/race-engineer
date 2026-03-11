"""
Tests for voice/tts.py — sentence splitting and PCM playback logic.
"""
import asyncio
import pytest
import numpy as np

from unittest.mock import MagicMock, patch, AsyncMock

from voice.tts import _SENTENCE_RE, ElevenLabsTTS


class TestSentenceRegex:
    def _split(self, text: str) -> list[str]:
        """Mirror the splitting logic from stream_speak's producer."""
        parts = _SENTENCE_RE.split(text)
        return [p.strip() for p in parts if p.strip()]

    def test_splits_on_period(self):
        parts = self._split("First sentence. Second sentence.")
        assert len(parts) == 2
        assert parts[0] == "First sentence."
        assert parts[1] == "Second sentence."

    def test_splits_on_exclamation(self):
        parts = self._split("Box now! Tyres are gone!")
        assert len(parts) == 2

    def test_splits_on_question_mark(self):
        parts = self._split("Copy that? Understood.")
        assert len(parts) == 2

    def test_no_split_mid_sentence(self):
        parts = self._split("Holding P3 overall")
        assert len(parts) == 1

    def test_multiple_sentences(self):
        parts = self._split("One. Two. Three.")
        assert len(parts) == 3

    def test_trailing_period_no_space(self):
        """Period at end of string (no trailing space) is kept as one chunk."""
        parts = self._split("Fuel looks good.")
        assert len(parts) == 1
        assert parts[0] == "Fuel looks good."


class TestPlayPcm:
    def test_empty_bytes_returns_early(self):
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()
        # Should not raise, and should not call sd.play
        with patch("voice.tts.sd") as mock_sd:
            tts._play_pcm(b"")
            mock_sd.play.assert_not_called()

    def test_pcm_played_at_correct_sample_rate(self):
        import config
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()
        # Two 16-bit samples
        pcm = np.array([1000, -1000], dtype=np.int16).tobytes()
        with patch("voice.tts.sd") as mock_sd:
            tts._play_pcm(pcm)
            mock_sd.play.assert_called_once()
            _, kwargs = mock_sd.play.call_args
            assert kwargs.get("samplerate") == config.TTS_SAMPLE_RATE
            assert kwargs.get("blocking") is True

    def test_pcm_normalised_to_float32(self):
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()
        captured = {}

        def fake_play(audio, samplerate, blocking):
            captured["audio"] = audio

        pcm = np.array([32767, -32768, 0], dtype=np.int16).tobytes()
        with patch("voice.tts.sd.play", side_effect=fake_play):
            tts._play_pcm(pcm)

        audio = captured["audio"]
        assert audio.dtype == np.float32
        assert audio[0] == pytest.approx(32767 / 32768.0, abs=1e-4)
        assert audio[1] == pytest.approx(-1.0, abs=1e-4)
        assert audio[2] == pytest.approx(0.0, abs=1e-4)


class TestStreamSpeak:
    @pytest.mark.anyio
    async def test_sentences_are_synthesised(self):
        """stream_speak should call _synthesise_and_play once per sentence."""
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()

        synthesised = []

        async def fake_synth(text):
            synthesised.append(text)

        tts._synthesise_and_play = fake_synth

        async def text_gen():
            yield "Box this lap. "
            yield "Fuel is critical."

        await tts.stream_speak(text_gen())

        assert len(synthesised) == 2
        assert synthesised[0] == "Box this lap."
        assert synthesised[1] == "Fuel is critical."

    @pytest.mark.anyio
    async def test_empty_stream_does_nothing(self):
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()

        synthesised = []

        async def fake_synth(text):
            synthesised.append(text)

        tts._synthesise_and_play = fake_synth

        async def empty_gen():
            return
            yield  # make it an async generator

        await tts.stream_speak(empty_gen())
        assert synthesised == []

    @pytest.mark.anyio
    async def test_partial_sentence_flushed_at_end(self):
        """Text without trailing punctuation should still be spoken."""
        with patch("voice.tts.ElevenLabs"):
            tts = ElevenLabsTTS()

        synthesised = []

        async def fake_synth(text):
            synthesised.append(text)

        tts._synthesise_and_play = fake_synth

        async def text_gen():
            yield "Copy that"

        await tts.stream_speak(text_gen())
        assert synthesised == ["Copy that"]
