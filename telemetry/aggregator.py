"""
TelemetryAggregator — converts raw telemetry snapshots into race-engineer-useful data.

Responsibilities:
  - Rolling lap time averages (last N laps)
  - Rolling fuel consumption per lap
  - Laps-of-fuel-remaining calculation
  - Tyre wear rate estimation
  - Alert detection (LOW_FUEL, FCY, SAFETY_CAR, TYRE_CRITICAL)
"""
from collections import deque
from statistics import median
from typing import NamedTuple

from .provider import CornerData, TelemetryState


class Alert(NamedTuple):
    key: str            # e.g. "LOW_FUEL", "FCY"
    message: str        # human-readable, voiced by the engineer


class TelemetryAggregator:
    def __init__(self, window_laps: int = 5) -> None:
        self._window = window_laps
        self._state: TelemetryState | None = None

        # Per-lap rolling history
        self._lap_times: deque[float] = deque(maxlen=window_laps)
        self._fuel_per_lap: deque[float] = deque(maxlen=window_laps)
        self._lap_top_speeds: deque[float] = deque(maxlen=window_laps)

        # Current lap tracking
        self._current_lap_top_speed: float = 0.0

        # State tracking for lap-boundary detection
        self._prev_laps_completed: int = -1
        self._fuel_at_lap_start: float = 0.0   # litres

        # Alert state
        self._active_alerts: set[str] = set()

        # Per-corner rolling history: name -> deque of (time_s, apex_kmh)
        self._corner_history: dict[str, deque] = {}

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------

    def update(self, state: TelemetryState) -> list[Alert]:
        """
        Ingest a new telemetry snapshot. Returns any newly triggered alerts
        (alerts that were not active in the previous update).
        """
        if self._prev_laps_completed == -1:
            # First update — initialise tracking state
            self._prev_laps_completed = state.laps_completed
            self._fuel_at_lap_start = state.fuel_l
            self._state = state
            return []

        new_alerts: list[Alert] = []

        # --- Track top speed every tick ---
        if state.speed_kmh > self._current_lap_top_speed:
            self._current_lap_top_speed = state.speed_kmh

        # --- Lap boundary detection ---
        if state.laps_completed > self._prev_laps_completed:
            fuel_used = self._fuel_at_lap_start - state.fuel_l
            if 0.5 < fuel_used < 60.0:   # sanity check: positive, <60L covers 10x hypercar
                self._fuel_per_lap.append(fuel_used)

            if state.lap_time_last > 0:
                self._lap_times.append(state.lap_time_last)

            if self._current_lap_top_speed > 0:
                self._lap_top_speeds.append(self._current_lap_top_speed)
            self._current_lap_top_speed = 0.0

            for corner in state.corners_last_lap:
                if corner.name not in self._corner_history:
                    self._corner_history[corner.name] = deque(maxlen=self._window)
                self._corner_history[corner.name].append((corner.time_s, corner.apex_speed_kmh))

            self._prev_laps_completed = state.laps_completed
            self._fuel_at_lap_start = state.fuel_l

        self._state = state
        new_alerts = self._detect_alerts()
        return new_alerts

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------

    @property
    def avg_fuel_per_lap(self) -> float:
        """Average litres consumed per lap over the rolling window."""
        if not self._fuel_per_lap:
            return 3.3  # fallback estimate for GT3 (~3.3 L/lap)
        return sum(self._fuel_per_lap) / len(self._fuel_per_lap)

    @property
    def laps_of_fuel_remaining(self) -> float:
        if self._state is None or self.avg_fuel_per_lap <= 0:
            return 0.0
        return self._state.fuel_l / self.avg_fuel_per_lap

    @property
    def avg_lap_time(self) -> float:
        if not self._lap_times:
            return 0.0
        return sum(self._lap_times) / len(self._lap_times)

    @property
    def top_speed_last_lap(self) -> float:
        """Top speed (km/h) recorded during the most recently completed lap."""
        if not self._lap_top_speeds:
            return 0.0
        return self._lap_top_speeds[-1]

    @property
    def last_vs_avg_delta(self) -> float:
        """Last lap time minus rolling average. Negative = faster."""
        if self._state is None or self.avg_lap_time == 0:
            return 0.0
        return self._state.lap_time_last - self.avg_lap_time

    # ------------------------------------------------------------------
    # Alert detection
    # ------------------------------------------------------------------

    def _detect_alerts(self) -> list[Alert]:
        """Returns newly triggered alerts (edge-triggered, not level-triggered)."""
        if self._state is None:
            return []

        s = self._state
        current: set[str] = set()
        alerts: list[Alert] = []

        if self.laps_of_fuel_remaining < 5 and s.fuel_l > 0:
            current.add("LOW_FUEL")

        if s.fcy_active:
            current.add("FCY")

        if s.safety_car_active:
            current.add("SAFETY_CAR")

        if s.tyres.max_wear > 0.80:
            current.add("TYRE_CRITICAL")

        if s.damage_aero > 0.30 or s.damage_suspension > 0.20:
            current.add("DAMAGE_SIGNIFICANT")

        # Edge detection — only report newly appearing alerts
        for key in current - self._active_alerts:
            msg = _ALERT_MESSAGES.get(key, key)
            alerts.append(Alert(key=key, message=msg))

        self._active_alerts = current
        return alerts

    # ------------------------------------------------------------------
    # Context summary for AI
    # ------------------------------------------------------------------

    def get_context(self) -> dict:
        """
        Returns a structured dict injected into the Claude system context.
        Designed to give the AI maximum race-situational awareness.
        """
        if self._state is None:
            return {"status": "no_data"}

        s = self._state
        laps_fuel = self.laps_of_fuel_remaining
        session_h = s.session_time_remaining / 3600

        return {
            # Session identity
            "track_name": s.track_name,
            "session_type": s.session_type,
            "vehicle_name": s.vehicle_name,
            # Race standing
            "position": s.position,
            "position_in_class": s.position_in_class,
            "of_total": s.total_cars,
            "of_class": s.total_cars_in_class,
            # Timing
            "lap_number": s.lap_number,
            "laps_completed": s.laps_completed,
            "last_lap": _fmt_time(s.lap_time_last),
            "best_lap": _fmt_time(s.lap_time_best),
            "rolling_avg_lap": _fmt_time(self.avg_lap_time),
            "last_vs_avg_delta_s": round(self.last_vs_avg_delta, 3),
            "top_speed_last_lap_kmh": round(self.top_speed_last_lap, 1),
            # Gaps
            "gap_to_leader_s": round(s.gap_to_leader, 1),
            "gap_ahead_s": round(s.gap_to_car_ahead, 1),
            "gap_behind_s": round(s.gap_to_car_behind, 1),
            # Fuel
            "fuel_l": round(s.fuel_l, 1),
            "laps_of_fuel_remaining": round(laps_fuel, 1),
            "avg_fuel_per_lap_l": round(self.avg_fuel_per_lap, 2),
            # Energy: GT3 uses virtual energy (BOP); hypercars use a real battery
            **( {"virtual_energy_pct": round(s.battery_charge_fraction * 100, 1)}
                if "GT3" in s.vehicle_class
                else {"battery_charge_pct": round(s.battery_charge_fraction * 100, 1)}
                if s.battery_charge_fraction > 0
                else {} ),
            # Tyres
            "tyre_wear_pct": {
                "fl": round(s.tyres.wear_fl * 100, 1),
                "fr": round(s.tyres.wear_fr * 100, 1),
                "rl": round(s.tyres.wear_rl * 100, 1),
                "rr": round(s.tyres.wear_rr * 100, 1),
            },
            "tyre_temp_c": {
                "fl": round(s.tyres.temp_fl, 1),
                "fr": round(s.tyres.temp_fr, 1),
                "rl": round(s.tyres.temp_rl, 1),
                "rr": round(s.tyres.temp_rr, 1),
            },
            # Race events
            "fcy_active": s.fcy_active,
            "safety_car_active": s.safety_car_active,
            # Damage
            "damage": {
                "aero_pct": round(s.damage_aero * 100, 0),
                "engine_pct": round(s.damage_engine * 100, 0),
                "suspension_pct": round(s.damage_suspension * 100, 0),
            },
            # Weather
            "track_temp_c": s.track_temp_c,
            "air_temp_c": s.air_temp_c,
            "rain_intensity": round(s.rain_intensity, 2),
            # Session
            "session_time_remaining_h": round(session_h, 2),
            "active_alerts": list(self._active_alerts),
            # Corner-by-corner analysis vs rolling average
            "corner_analysis": self._corner_analysis(s.corners_last_lap),
            # Other participants
            "opponents": [
                {
                    "pos": o.position,
                    "driver": o.driver_name,
                    "car": o.vehicle_name,
                    "class": o.vehicle_class,
                    "gap_to_leader_s": o.gap_to_leader_s,
                    "last_lap": _fmt_time(o.last_lap_s),
                    "best_lap": _fmt_time(o.best_lap_s),
                    "in_pit": o.in_pit,
                }
                for o in sorted(s.opponents, key=lambda o: o.position)
            ],
        }


    def _corner_analysis(self, corners: list) -> list[dict]:
        """
        Compare last lap's corner times against rolling averages.
        Returns corners sorted by time loss (worst first).
        Only included once we have at least 2 laps of history per corner.
        """
        results = []
        for corner in corners:
            history = self._corner_history.get(corner.name)
            if not history or len(history) < 2:
                continue
            avg_time = sum(t for t, _ in history) / len(history)
            # Median for apex speed: robust against single outbraking/off-line laps
            avg_apex = median(a for _, a in history)
            delta = corner.time_s - avg_time  # positive = slower than average
            results.append({
                "corner": corner.name,
                "last_apex_kmh": corner.apex_speed_kmh,
                "avg_apex_kmh": round(avg_apex, 1),
                "apex_delta_kmh": round(corner.apex_speed_kmh - avg_apex, 1),
                "last_time_s": corner.time_s,
                "avg_time_s": round(avg_time, 3),
                "delta_s": round(delta, 3),   # negative = faster than avg
            })
        # Sort worst (most time lost) first — most useful ordering for the AI
        results.sort(key=lambda x: x["delta_s"], reverse=True)
        return results


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_time(seconds: float) -> str:
    if seconds <= 0:
        return "--:--.---"
    m = int(seconds // 60)
    s = seconds % 60
    return f"{m}:{s:06.3f}"


_ALERT_MESSAGES: dict[str, str] = {
    "LOW_FUEL": "Fuel warning — less than 5 laps remaining.",
    "FCY": "Full Course Yellow — pit window open.",
    "SAFETY_CAR": "Safety Car deployed.",
    "TYRE_CRITICAL": "Tyre wear critical — consider pitting.",
    "DAMAGE_SIGNIFICANT": "Significant damage detected.",
}
