"""
Tests for engineer/agent.py — RaceEngineerAgent context building and history management.
"""
import json
import pytest

from unittest.mock import MagicMock, AsyncMock, patch

from engineer.agent import RaceEngineerAgent, _SYSTEM_PROMPT
from engineer.strategy import StrategySnapshot
from telemetry.aggregator import TelemetryAggregator
from telemetry.provider import TelemetryState


def make_aggregator_with_data() -> TelemetryAggregator:
    agg = TelemetryAggregator()
    agg.update(TelemetryState(fuel_l=110.0, laps_completed=0))
    agg.update(TelemetryState(fuel_l=107.5, laps_completed=1, lap_time_last=105.0))
    return agg


def make_strategy() -> StrategySnapshot:
    return StrategySnapshot(
        forced_pit_in_laps=10.0,
        optimal_pit_window_open=True,
        recommended_pit_lap=15,
        tyre_stint_age_laps=20,
        estimated_tyre_life_laps=55,
        fuel_to_add_l=80.0,
        next_stint_laps=28,
        pit_time_loss_s=70.0,
    )


class TestBuildUserMessage:
    def test_includes_driver_query(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        msg = RaceEngineerAgent._build_user_message("How's my fuel?", ctx, None)
        assert "DRIVER: How's my fuel?" in msg

    def test_includes_telemetry_section(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        msg = RaceEngineerAgent._build_user_message("test", ctx, None)
        assert "--- LIVE TELEMETRY ---" in msg

    def test_telemetry_is_valid_json(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        msg = RaceEngineerAgent._build_user_message("test", ctx, None)
        # Extract json block between telemetry header and next section
        lines = msg.split("\n")
        start = next(i for i, l in enumerate(lines) if l == "--- LIVE TELEMETRY ---") + 1
        end = next(i for i, l in enumerate(lines) if "DRIVER:" in l)
        json_block = "\n".join(lines[start:end]).strip()
        parsed = json.loads(json_block)
        assert isinstance(parsed, dict)

    def test_includes_strategy_section_when_provided(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        strategy = make_strategy()
        msg = RaceEngineerAgent._build_user_message("test", ctx, strategy)
        assert "--- STRATEGY COMPUTER ---" in msg

    def test_excludes_strategy_section_when_none(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        msg = RaceEngineerAgent._build_user_message("test", ctx, None)
        assert "--- STRATEGY COMPUTER ---" not in msg

    def test_strategy_text_in_message(self):
        agg = make_aggregator_with_data()
        ctx = agg.get_context()
        strategy = make_strategy()
        msg = RaceEngineerAgent._build_user_message("test", ctx, strategy)
        assert "OPEN" in msg  # strategy window is open


class TestConversationHistory:
    def _make_agent(self) -> RaceEngineerAgent:
        agg = make_aggregator_with_data()
        with patch("engineer.agent.anthropic.AsyncAnthropic"):
            agent = RaceEngineerAgent(agg)
        return agent

    def test_reset_conversation_clears_history(self):
        agent = self._make_agent()
        agent._conversation = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi"},
        ]
        agent.reset_conversation()
        assert agent._conversation == []

    def test_history_starts_empty(self):
        agent = self._make_agent()
        assert agent._conversation == []

    @pytest.mark.anyio
    async def test_respond_stream_appends_to_history(self):
        agg = make_aggregator_with_data()
        mock_client = MagicMock()

        # Build a fake streaming context manager
        async def fake_text_stream():
            yield "Box"
            yield " this lap."

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)
        mock_stream.text_stream = fake_text_stream()

        mock_client.messages.stream.return_value = mock_stream

        with patch("engineer.agent.anthropic.AsyncAnthropic", return_value=mock_client):
            agent = RaceEngineerAgent(agg)

        chunks = []
        async for chunk in agent.respond_stream("Should I pit?"):
            chunks.append(chunk)

        assert len(agent._conversation) == 2
        assert agent._conversation[0]["role"] == "user"
        assert agent._conversation[1]["role"] == "assistant"
        assert agent._conversation[1]["content"] == "Box this lap."

    @pytest.mark.anyio
    async def test_history_trimmed_to_20_turns(self):
        agg = make_aggregator_with_data()
        mock_client = MagicMock()

        async def fake_text_stream():
            yield "ok"

        mock_stream = AsyncMock()
        mock_stream.__aenter__ = AsyncMock(return_value=mock_stream)
        mock_stream.__aexit__ = AsyncMock(return_value=False)

        call_count = 0

        def make_stream(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Need a fresh async generator each time
            async def _stream():
                yield "ok"
            m = AsyncMock()
            m.__aenter__ = AsyncMock(return_value=m)
            m.__aexit__ = AsyncMock(return_value=False)
            m.text_stream = _stream()
            return m

        mock_client.messages.stream.side_effect = make_stream

        with patch("engineer.agent.anthropic.AsyncAnthropic", return_value=mock_client):
            agent = RaceEngineerAgent(agg)

        # Send 12 messages → 24 turns → should be trimmed to 20
        for _ in range(12):
            async for _ in agent.respond_stream("test"):
                pass

        assert len(agent._conversation) <= 20


class TestSystemPrompt:
    def test_system_prompt_mentions_race_engineer(self):
        assert "race engineer" in _SYSTEM_PROMPT.lower()

    def test_system_prompt_mentions_le_mans(self):
        assert "Le Mans" in _SYSTEM_PROMPT
