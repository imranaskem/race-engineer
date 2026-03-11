"""
Tests for engineer/strategy.py — deterministic strategy calculations.
"""
import pytest

from engineer.strategy import StrategySnapshot, _parse_lap_time, compute_strategy


class TestParseLapTime:
    def test_standard_format(self):
        assert _parse_lap_time("1:45.300") == pytest.approx(105.3)

    def test_zero_minutes(self):
        assert _parse_lap_time("0:59.500") == pytest.approx(59.5)

    def test_plain_seconds(self):
        assert _parse_lap_time("105.3") == pytest.approx(105.3)

    def test_invalid_string(self):
        assert _parse_lap_time("invalid") == 0.0

    def test_empty_string(self):
        assert _parse_lap_time("") == 0.0

    def test_two_minutes(self):
        assert _parse_lap_time("2:00.000") == pytest.approx(120.0)


class TestStrategySnapshotAsText:
    def _make_snapshot(self, **kwargs) -> StrategySnapshot:
        defaults = dict(
            forced_pit_in_laps=8.0,
            optimal_pit_window_open=True,
            recommended_pit_lap=5,
            tyre_stint_age_laps=25,
            estimated_tyre_life_laps=55,
            fuel_to_add_l=82.5,
            next_stint_laps=30,
            pit_time_loss_s=70.0,
        )
        defaults.update(kwargs)
        return StrategySnapshot(**defaults)

    def test_contains_window_open(self):
        snap = self._make_snapshot(optimal_pit_window_open=True)
        assert "OPEN" in snap.as_text()

    def test_contains_window_closed(self):
        snap = self._make_snapshot(optimal_pit_window_open=False)
        assert "CLOSED" in snap.as_text()

    def test_contains_pit_lap(self):
        snap = self._make_snapshot(recommended_pit_lap=12)
        assert "lap 12" in snap.as_text()

    def test_contains_fuel_to_add(self):
        snap = self._make_snapshot(fuel_to_add_l=82.5)
        assert "82.5 L" in snap.as_text()

    def test_contains_tyre_age(self):
        snap = self._make_snapshot(tyre_stint_age_laps=25, estimated_tyre_life_laps=55)
        assert "25 laps old" in snap.as_text()
        assert "est. life 55 laps" in snap.as_text()

    def test_contains_pit_time_loss(self):
        snap = self._make_snapshot(pit_time_loss_s=70.0)
        assert "70s" in snap.as_text()


class TestComputeStrategy:
    def _base_context(self, **overrides) -> dict:
        ctx = {
            "laps_of_fuel_remaining": 20.0,
            "lap_number": 10,
            "avg_fuel_per_lap_l": 3.3,
            "fuel_l": 66.0,
            "fuel_capacity_l": 110.0,
            "tyre_wear_pct": {},
            "session_time_remaining_h": 20.0,
            "rolling_avg_lap": "1:45.000",
            "fcy_active": False,
        }
        ctx.update(overrides)
        return ctx

    def test_pit_window_closed_with_ample_fuel_and_tyres(self):
        ctx = self._base_context(laps_of_fuel_remaining=30.0, tyre_wear_pct={})
        snap = compute_strategy(ctx)
        assert snap.optimal_pit_window_open is False

    def test_pit_window_open_when_fuel_low(self):
        ctx = self._base_context(laps_of_fuel_remaining=10.0)
        snap = compute_strategy(ctx)
        assert snap.optimal_pit_window_open is True

    def test_pit_window_open_when_tyres_worn(self):
        # max_wear=72, tyre_laps_used = int(72 / 1.8) = 40
        # estimated_life = int(100 / 1.8) = 55
        # tyre_laps_remaining = 55 - 40 = 15 → within buffer of 15 → open
        ctx = self._base_context(
            laps_of_fuel_remaining=30.0,
            tyre_wear_pct={"fl": 72.0, "fr": 72.0, "rl": 72.0, "rr": 72.0},
        )
        snap = compute_strategy(ctx)
        assert snap.optimal_pit_window_open is True

    def test_pit_window_open_during_fcy(self):
        ctx = self._base_context(laps_of_fuel_remaining=30.0, fcy_active=True)
        snap = compute_strategy(ctx)
        assert snap.optimal_pit_window_open is True

    def test_forced_pit_in_laps_matches_fuel_laps(self):
        ctx = self._base_context(laps_of_fuel_remaining=12.3)
        snap = compute_strategy(ctx)
        assert snap.forced_pit_in_laps == pytest.approx(12.3, abs=0.05)

    def test_recommended_pit_lap_is_future(self):
        ctx = self._base_context(lap_number=10, laps_of_fuel_remaining=8.0)
        snap = compute_strategy(ctx)
        assert snap.recommended_pit_lap >= 10

    def test_fuel_to_add_not_negative(self):
        ctx = self._base_context(fuel_l=5.0)
        snap = compute_strategy(ctx)
        assert snap.fuel_to_add_l >= 0.0

    def test_fuel_to_add_zero_when_full_tank(self):
        # Full tank, high fuel per lap
        ctx = self._base_context(fuel_l=110.0, fuel_capacity_l=110.0, avg_fuel_per_lap_l=3.3)
        snap = compute_strategy(ctx)
        assert snap.fuel_to_add_l == 0.0

    def test_next_stint_laps_positive(self):
        snap = compute_strategy(self._base_context())
        assert snap.next_stint_laps > 0

    def test_pit_time_loss_is_70(self):
        snap = compute_strategy(self._base_context())
        assert snap.pit_time_loss_s == 70.0

    def test_fallback_when_lap_time_zero(self):
        """If rolling_avg_lap parses to 0, should use 105s fallback (not divide by zero)."""
        ctx = self._base_context(rolling_avg_lap="invalid")
        snap = compute_strategy(ctx)  # should not raise
        assert snap.next_stint_laps > 0

    def test_tyre_age_increases_with_wear(self):
        ctx_fresh = self._base_context(tyre_wear_pct={})
        ctx_worn = self._base_context(tyre_wear_pct={"fl": 36.0})
        fresh = compute_strategy(ctx_fresh)
        worn = compute_strategy(ctx_worn)
        assert worn.tyre_stint_age_laps > fresh.tyre_stint_age_laps

    def test_missing_keys_use_defaults(self):
        """compute_strategy should not crash on a near-empty context dict."""
        snap = compute_strategy({})
        assert isinstance(snap, StrategySnapshot)
