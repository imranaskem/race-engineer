"""
Tests for telemetry/provider.py — TyreData, TelemetryState dataclasses.
"""
import pytest

from telemetry.provider import TyreData, TelemetryState, CornerData, Opponent


class TestTyreData:
    def test_max_wear_returns_highest(self):
        t = TyreData(wear_fl=0.1, wear_fr=0.4, wear_rl=0.2, wear_rr=0.3)
        assert t.max_wear == pytest.approx(0.4)

    def test_max_wear_all_new(self):
        t = TyreData()
        assert t.max_wear == 0.0

    def test_avg_temp_equal_temps(self):
        t = TyreData(temp_fl=90.0, temp_fr=90.0, temp_rl=90.0, temp_rr=90.0)
        assert t.avg_temp == pytest.approx(90.0)

    def test_avg_temp_mixed(self):
        t = TyreData(temp_fl=80.0, temp_fr=100.0, temp_rl=80.0, temp_rr=100.0)
        assert t.avg_temp == pytest.approx(90.0)

    def test_defaults(self):
        t = TyreData()
        assert t.temp_fl == 80.0
        assert t.wear_fl == 0.0
        assert t.max_wear == 0.0

    def test_max_wear_fl_highest(self):
        t = TyreData(wear_fl=0.9, wear_fr=0.1, wear_rl=0.1, wear_rr=0.1)
        assert t.max_wear == pytest.approx(0.9)


class TestTelemetryStateDefaults:
    def test_fuel_defaults(self):
        s = TelemetryState()
        assert s.fuel_l == 100.0
        assert s.fuel_capacity_l == 110.0

    def test_position_defaults(self):
        s = TelemetryState()
        assert s.position == 1
        assert s.total_cars == 30

    def test_tyres_default_factory(self):
        s1 = TelemetryState()
        s2 = TelemetryState()
        # Each instance should get its own TyreData
        s1.tyres.wear_fl = 0.5
        assert s2.tyres.wear_fl == 0.0

    def test_opponents_list_default_factory(self):
        s1 = TelemetryState()
        s2 = TelemetryState()
        s1.opponents.append("x")
        assert s2.opponents == []

    def test_fcy_defaults_false(self):
        s = TelemetryState()
        assert s.fcy_active is False
        assert s.safety_car_active is False

    def test_in_pit_default_false(self):
        s = TelemetryState()
        assert s.in_pit is False

    def test_session_time_remaining_default(self):
        s = TelemetryState()
        assert s.session_time_remaining == 86400.0

    def test_override_values(self):
        s = TelemetryState(fuel_l=55.0, position=3, fcy_active=True)
        assert s.fuel_l == 55.0
        assert s.position == 3
        assert s.fcy_active is True


class TestCornerData:
    def test_construction(self):
        c = CornerData(
            name="Ford Chicane",
            entry_speed_kmh=240.0,
            apex_speed_kmh=68.0,
            exit_speed_kmh=95.0,
            time_s=6.2,
        )
        assert c.name == "Ford Chicane"
        assert c.apex_speed_kmh == 68.0


class TestOpponent:
    def test_construction(self):
        o = Opponent(
            driver_name="Klaus Brauer",
            vehicle_name="Porsche 911 GT3R",
            vehicle_class="GT3",
            position=2,
            gap_to_leader_s=4.8,
            last_lap_s=105.1,
            best_lap_s=104.9,
            laps_completed=10,
            in_pit=False,
        )
        assert o.driver_name == "Klaus Brauer"
        assert o.in_pit is False
        assert o.position == 2
