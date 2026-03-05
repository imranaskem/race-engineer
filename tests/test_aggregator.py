"""
Tests for TelemetryAggregator.

Run with: python -m pytest tests/ -v
"""
import pytest

from telemetry.aggregator import TelemetryAggregator, _fmt_time
from telemetry.provider import TelemetryState, TyreData
from telemetry.rf2_shared_memory import _CornerTracker


def make_state(**kwargs) -> TelemetryState:
    return TelemetryState(**kwargs)


class TestFuelCalculations:
    def test_default_fuel_per_lap_before_any_laps(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        # No laps completed yet — should use fallback of 3.3 L/lap
        assert agg.avg_fuel_per_lap == 3.3

    def test_fuel_per_lap_after_one_lap(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        agg.update(make_state(fuel_l=107.4, laps_completed=1, lap_time_last=105.3))
        assert abs(agg.avg_fuel_per_lap - 2.6) < 0.01

    def test_fuel_per_lap_rolling_average(self):
        agg = TelemetryAggregator(window_laps=3)
        fuel = 110.0
        consumptions = [2.4, 2.6, 2.5]
        laps = 0
        agg.update(make_state(fuel_l=fuel, laps_completed=laps))
        for c in consumptions:
            fuel -= c
            laps += 1
            agg.update(make_state(fuel_l=fuel, laps_completed=laps, lap_time_last=105.0))
        expected = sum(consumptions) / 3
        assert abs(agg.avg_fuel_per_lap - expected) < 0.01

    def test_laps_of_fuel_remaining(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        agg.update(make_state(fuel_l=107.5, laps_completed=1, lap_time_last=105.0))
        agg.update(make_state(fuel_l=25.0, laps_completed=2, lap_time_last=105.5))
        # avg_fuel_per_lap = (2.5 + 82.5) / 2 = 42.5... no wait
        # From lap 0→1: used 110-107.5 = 2.5
        # From lap 1→2: used 107.5-25.0 = 82.5 — but this fails the sanity check (>6kg)
        # So only 2.5 is recorded
        assert agg.avg_fuel_per_lap == pytest.approx(2.5, abs=0.01)
        assert agg.laps_of_fuel_remaining == pytest.approx(25.0 / 2.5, abs=0.1)

    def test_sanity_check_rejects_refuelling_laps(self):
        """A lap where fuel increases (refuelling) should not pollute the average."""
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=20.0, laps_completed=0))
        # Simulate pit stop — fuel jumps to 110 kg
        agg.update(make_state(fuel_l=110.0, laps_completed=1, lap_time_last=180.0))
        # avg should still be fallback since the consumption was negative
        assert agg.avg_fuel_per_lap == 3.3


class TestLapTimes:
    def test_avg_lap_time_single_lap(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        agg.update(make_state(fuel_l=107.5, laps_completed=1, lap_time_last=105.3))
        assert agg.avg_lap_time == pytest.approx(105.3)

    def test_avg_lap_time_rolling(self):
        agg = TelemetryAggregator(window_laps=3)
        times = [105.0, 106.2, 104.8]
        fuel, laps = 110.0, 0
        agg.update(make_state(fuel_l=fuel, laps_completed=laps))
        for t in times:
            fuel -= 2.5
            laps += 1
            agg.update(make_state(fuel_l=fuel, laps_completed=laps, lap_time_last=t))
        assert agg.avg_lap_time == pytest.approx(sum(times) / 3, abs=0.01)

    def test_last_vs_avg_delta_negative_when_faster(self):
        agg = TelemetryAggregator()
        fuel, laps = 110.0, 0
        agg.update(make_state(fuel_l=fuel, laps_completed=laps))
        for t in [106.0, 105.0, 104.0]:
            fuel -= 2.5
            laps += 1
            agg.update(make_state(fuel_l=fuel, laps_completed=laps, lap_time_last=t))
        # Last lap (104.0) vs avg (105.0) = -1.0
        assert agg.last_vs_avg_delta < 0


class TestAlerts:
    def _agg_with_state(self, **kwargs) -> TelemetryAggregator:
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        state_kwargs = {"fuel_l": 107.5, "laps_completed": 1, "lap_time_last": 105.0}
        state_kwargs.update(kwargs)
        agg.update(make_state(**state_kwargs))
        return agg

    def test_no_alert_with_ample_fuel(self):
        agg = self._agg_with_state(fuel_l=30.0)
        ctx = agg.get_context()
        assert "LOW_FUEL" not in ctx["active_alerts"]

    def test_low_fuel_alert_triggered(self):
        agg = TelemetryAggregator()
        # Bootstrap with one lap to get fuel consumption recorded
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        # After first lap — 2.5 kg used
        agg.update(make_state(fuel_l=107.5, laps_completed=1, lap_time_last=105.0))
        # Now simulate low fuel: 9 kg left → 9/2.5 = 3.6 laps < 5
        alerts = agg.update(make_state(fuel_l=9.0, laps_completed=2, lap_time_last=105.1))
        alert_keys = [a.key for a in alerts]
        assert "LOW_FUEL" in alert_keys

    def test_fcy_alert_triggered(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        alerts = agg.update(make_state(fuel_l=107.5, laps_completed=1, fcy_active=True))
        assert any(a.key == "FCY" for a in alerts)

    def test_fcy_alert_not_repeated(self):
        """Alert should only fire on the rising edge, not every update."""
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        first = agg.update(make_state(fuel_l=107.5, laps_completed=1, fcy_active=True))
        second = agg.update(make_state(fuel_l=107.4, laps_completed=1, fcy_active=True))
        assert any(a.key == "FCY" for a in first)
        assert not any(a.key == "FCY" for a in second)

    def test_tyre_critical_alert(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        worn_tyres = TyreData(wear_fl=0.85, wear_fr=0.90, wear_rl=0.80, wear_rr=0.82)
        alerts = agg.update(make_state(fuel_l=107.5, laps_completed=1, tyres=worn_tyres))
        assert any(a.key == "TYRE_CRITICAL" for a in alerts)


class TestContextSummary:
    def test_context_keys_present(self):
        agg = TelemetryAggregator()
        agg.update(make_state(fuel_l=110.0, laps_completed=0))
        agg.update(make_state(fuel_l=107.5, laps_completed=1, lap_time_last=105.3))
        ctx = agg.get_context()
        required = [
            "position", "fuel_l", "laps_of_fuel_remaining",
            "last_lap", "best_lap", "rolling_avg_lap",
            "tyre_wear_pct", "active_alerts",
        ]
        for key in required:
            assert key in ctx, f"Missing key: {key}"

    def test_context_returns_no_data_without_updates(self):
        agg = TelemetryAggregator()
        ctx = agg.get_context()
        assert ctx == {"status": "no_data"}


class TestCornerTracker:
    def _drive_corner(self, tracker, entry_speed=250.0, apex_speed=80.0, exit_speed=250.0,
                      entry_time=0.0, apex_time=2.0, exit_time=4.0, peak_lat_g=1.5):
        """Simulate a single corner: straight → lateral load → apex → exit."""
        tracker.update(entry_speed, 0.0, entry_time)               # straight, no lateral load
        tracker.update(entry_speed - 30, peak_lat_g, entry_time + 0.1)  # lateral load builds
        tracker.update(apex_speed, peak_lat_g, apex_time)          # apex, peak load
        tracker.update(apex_speed + 40, peak_lat_g * 0.3, exit_time - 0.3)  # unwinding
        tracker.update(exit_speed, 0.0, exit_time)                 # exit, load gone

    def test_detects_single_corner(self):
        t = _CornerTracker()
        self._drive_corner(t)
        corners = t.get_and_reset()
        assert len(corners) == 1

    def test_corner_name_increments(self):
        t = _CornerTracker()
        self._drive_corner(t, entry_time=0, apex_time=2, exit_time=4)
        self._drive_corner(t, entry_time=10, apex_time=12, exit_time=14)
        corners = t.get_and_reset()
        assert corners[0].name == "Corner 1"
        assert corners[1].name == "Corner 2"

    def test_apex_speed_is_minimum(self):
        t = _CornerTracker()
        t.update(250, 0.0, 0.0)    # straight
        t.update(200, 1.5, 0.1)    # enter corner
        t.update(120, 1.5, 1.0)
        t.update(85,  1.5, 2.0)    # apex — minimum speed
        t.update(95,  1.5, 2.5)
        t.update(200, 0.1, 4.0)    # exit
        corners = t.get_and_reset()
        assert len(corners) == 1
        assert corners[0].apex_speed_kmh == pytest.approx(85.0, abs=0.5)

    def test_brief_lateral_load_ignored(self):
        """Lateral load shorter than _CORNER_MIN_DURATION_S should not register."""
        t = _CornerTracker()
        t.update(250, 0.0, 0.0)    # straight
        t.update(200, 1.5, 0.1)    # enter corner
        t.update(180, 1.5, 0.3)    # apex
        t.update(200, 0.1, 0.5)    # exit — only 0.4s, below 0.8s minimum
        corners = t.get_and_reset()
        assert len(corners) == 0

    def test_get_and_reset_clears_state(self):
        t = _CornerTracker()
        self._drive_corner(t)
        t.get_and_reset()
        # After reset, next corner should be "Corner 1" again
        self._drive_corner(t, entry_time=20, apex_time=22, exit_time=24)
        corners = t.get_and_reset()
        assert corners[0].name == "Corner 1"

    def test_entry_and_exit_speeds_recorded(self):
        t = _CornerTracker()
        t.update(280, 0.0, 0.0)    # high-speed straight
        t.update(220, 0.8, 0.1)    # enter corner at 220 km/h
        t.update(80,  1.5, 2.0)    # apex
        t.update(260, 0.1, 4.0)    # exit at 260 km/h
        corners = t.get_and_reset()
        assert len(corners) == 1
        assert corners[0].entry_speed_kmh == pytest.approx(220, abs=1)
        assert corners[0].exit_speed_kmh == pytest.approx(260, abs=1)

    def test_no_corners_on_straight(self):
        """High-speed straight with no lateral load should produce no corners."""
        t = _CornerTracker()
        for i, speed in enumerate([280, 290, 300, 310, 320]):
            t.update(speed, 0.05, float(i))
        assert t.get_and_reset() == []

    def test_high_speed_corner_detected(self):
        """High-speed corners like Monza's Lesmos (no sharp speed reduction) are detected."""
        t = _CornerTracker()
        t.update(240, 0.0, 0.0)    # entry speed
        t.update(215, 0.9, 0.1)    # lateral load builds — still fast
        t.update(200, 0.9, 1.5)    # apex — speed barely drops
        t.update(220, 0.1, 3.0)    # exit
        corners = t.get_and_reset()
        assert len(corners) == 1
        assert corners[0].apex_speed_kmh >= 200    # high-speed corner, apex still fast

    def test_very_slow_corner_still_detected(self):
        """Hairpin with apex below 60 km/h should still be detected."""
        t = _CornerTracker()
        t.update(230, 0.0, 0.0)
        t.update(150, 2.0, 0.1)
        t.update(55,  2.5, 2.0)
        t.update(180, 0.1, 5.0)
        corners = t.get_and_reset()
        assert len(corners) == 1
        assert corners[0].apex_speed_kmh < 60


class TestFormatTime:
    def test_format_zero(self):
        assert _fmt_time(0) == "--:--.---"

    def test_format_negative(self):
        assert _fmt_time(-1) == "--:--.---"

    def test_format_one_minute(self):
        assert _fmt_time(60.0) == "1:00.000"

    def test_format_lap_time(self):
        assert _fmt_time(105.3) == "1:45.300"
