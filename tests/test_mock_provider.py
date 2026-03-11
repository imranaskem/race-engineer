"""
Tests for telemetry/mock.py — MockTelemetryProvider simulation logic.
"""
import asyncio
import math
import pytest

from telemetry.mock import MockTelemetryProvider, _LAP_DURATION_BASE, _WEAR_PER_LAP
from telemetry.provider import TelemetryState


class TestSimulateSpeed:
    def test_speed_in_valid_range(self):
        provider = MockTelemetryProvider()
        for i in range(20):
            phase = i / 20.0
            speed = provider._simulate_speed(phase)
            assert 60.0 <= speed <= 310.0, f"Speed {speed} out of range at phase {phase}"

    def test_speed_varies_across_lap(self):
        provider = MockTelemetryProvider()
        speeds = [provider._simulate_speed(i / 100) for i in range(100)]
        assert max(speeds) - min(speeds) > 50  # circuit has meaningful variation


class TestUpdateFcy:
    def test_fcy_activates_when_time_reached(self):
        provider = MockTelemetryProvider()
        provider._fcy_next_trigger = 100.0
        provider._update_fcy(100.0)
        assert provider._state.fcy_active is True

    def test_fcy_not_active_before_trigger(self):
        provider = MockTelemetryProvider()
        provider._fcy_next_trigger = 500.0
        provider._update_fcy(100.0)
        assert provider._state.fcy_active is False

    def test_fcy_clears_after_duration(self):
        provider = MockTelemetryProvider()
        provider._fcy_next_trigger = 100.0
        provider._update_fcy(100.0)
        assert provider._state.fcy_active is True
        # fcy_end is set to 100 + 300 = 400
        provider._update_fcy(400.0)
        assert provider._state.fcy_active is False

    def test_fcy_does_not_retrigger_while_active(self):
        provider = MockTelemetryProvider()
        provider._fcy_next_trigger = 100.0
        provider._update_fcy(100.0)
        assert provider._state.fcy_active is True
        # Calling again while active should not change next trigger
        old_next = provider._fcy_next_trigger
        provider._update_fcy(150.0)
        assert provider._fcy_next_trigger == old_next


class TestCompleteLap:
    def test_laps_completed_increments(self):
        provider = MockTelemetryProvider()
        assert provider._state.laps_completed == 0
        provider._complete_lap(_LAP_DURATION_BASE)
        assert provider._state.laps_completed == 1

    def test_lap_number_increments(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        assert provider._state.lap_number == 2

    def test_lap_time_last_recorded(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        assert provider._state.lap_time_last > 0

    def test_best_lap_set_on_first_lap(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        assert provider._state.lap_time_best > 0

    def test_tyre_wear_increases_per_lap(self):
        provider = MockTelemetryProvider()
        initial_wear = provider._state.tyres.wear_fl
        provider._complete_lap(_LAP_DURATION_BASE)
        assert provider._state.tyres.wear_fl > initial_wear

    def test_front_right_wears_hardest(self):
        provider = MockTelemetryProvider()
        # Complete enough laps to see the wear differential
        for _ in range(5):
            provider._complete_lap(_LAP_DURATION_BASE)
        t = provider._state.tyres
        # FR has 1.10 multiplier vs FL 0.95 multiplier
        assert t.wear_fr > t.wear_fl

    def test_sector_times_sum_to_approx_lap_time(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        s = provider._state
        total = s.sector1_last + s.sector2_last + s.sector3_last
        assert total == pytest.approx(s.lap_time_last, abs=0.01)

    def test_corners_populated_each_lap(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        assert len(provider._state.corners_last_lap) == 8  # _CIRCUIT_CORNERS has 8

    def test_opponents_populated_each_lap(self):
        provider = MockTelemetryProvider()
        provider._complete_lap(_LAP_DURATION_BASE)
        assert len(provider._state.opponents) > 0

    def test_position_improves_over_time(self):
        """Position should improve as race elapsed time increases (simulated improvement)."""
        provider = MockTelemetryProvider()
        provider._state.race_elapsed_time = 0.0
        provider._complete_lap(_LAP_DURATION_BASE)
        pos_early = provider._state.position

        provider._state.race_elapsed_time = 10 * 3600  # 10 hours in
        provider._complete_lap(_LAP_DURATION_BASE)
        pos_late = provider._state.position

        assert pos_late <= pos_early


class TestMockProviderInterface:
    @pytest.mark.anyio
    async def test_start_and_get_state(self):
        provider = MockTelemetryProvider()
        await provider.start()
        try:
            state = await provider.get_state()
            assert isinstance(state, TelemetryState)
        finally:
            await provider.stop()

    @pytest.mark.anyio
    async def test_state_updates_over_time(self):
        provider = MockTelemetryProvider()
        await provider.start()
        try:
            state1 = await provider.get_state()
            fuel1 = state1.fuel_l
            # Wait for a few ticks at 50fps → ~100ms
            await asyncio.sleep(0.15)
            state2 = await provider.get_state()
            fuel2 = state2.fuel_l
            # Fuel should have drained slightly
            assert fuel2 < fuel1
        finally:
            await provider.stop()

    @pytest.mark.anyio
    async def test_stop_cancels_task(self):
        provider = MockTelemetryProvider()
        await provider.start()
        assert provider._task is not None
        await provider.stop()
        assert provider._task.cancelled() or provider._task.done()

    @pytest.mark.anyio
    async def test_initial_state_values(self):
        provider = MockTelemetryProvider()
        state = await provider.get_state()
        assert state.position == 6
        assert state.fuel_l == 110.0
        assert state.track_name == "Circuit de la Sarthe"
        assert state.vehicle_name == "BMW M4 GT3"
        assert state.session_type == "Race"
