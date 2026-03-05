"""
MockTelemetryProvider — realistic LMU endurance race simulation for Mac development.

Simulates a GT3 car in a 24h race:
  - ~1:45 lap times with natural variation
  - ~2.5 kg/lap fuel consumption
  - Progressive tyre wear over a stint
  - Occasional FCY periods
  - Slowly improving race position
"""
import asyncio
import math
import random
import time

from .provider import CornerData, Opponent, TelemetryProvider, TelemetryState, TyreData

# Approximate lap duration in seconds (1:45)
_LAP_DURATION_BASE: float = 105.0
# Fuel consumption per lap in litres
_FUEL_PER_LAP: float = 3.3
# Tyre wear increment per lap (fraction of total life)
_WEAR_PER_LAP: float = 0.018

# Static opponent roster — (driver_name, vehicle_name, vehicle_class, base_gap_to_leader_s)
_MOCK_OPPONENTS = [
    ("Valentino Ferrari",  "Ferrari 296 GT3",  "GT3",  0.0),    # P1 overall
    ("Klaus Brauer",       "Porsche 911 GT3R", "GT3",  4.8),    # P2
    ("Yuki Nakamura",      "Aston Martin GT3", "GT3",  9.2),    # P3
    ("Pierre Durand",      "BMW M4 GT3",       "GT3", 14.5),    # P4
    ("Scott Anderson",     "McLaren 720S GT3", "GT3", 16.1),    # P5
    # Player is P6 — gaps below are cars further behind
    ("Marco Bianchi",      "Mercedes GT3",     "GT3", 24.3),    # P7
    ("Liam O'Brien",       "Lamborghini GT3",  "GT3", 31.7),    # P8
    ("Hans Gruber",        "Ferrari 296 GT3",  "GT3", 45.2),    # P9
    ("Sébastien Moreau",   "Porsche 911 GT3R", "GT3", 52.8),    # P10
]

# Circuit corner definitions — loosely modelled on La Sarthe (Le Mans)
# Each tuple: (name, entry_kmh, apex_kmh, exit_kmh, time_s)
# time_s are tuned so they sum to ~43s, leaving ~62s for straights = 105s lap
_CIRCUIT_CORNERS = [
    ("Ford Chicane",       240,  68,  95,  6.2),
    ("Dunlop Curve",       210, 130, 160,  4.1),
    ("Tertre Rouge",       255, 200, 225,  3.8),
    ("Mulsanne Corner",    290,  78, 105,  5.9),
    ("Indianapolis",       240, 118, 148,  4.5),
    ("Arnage",             195,  57,  88,  7.3),
    ("Porsche Curves",     220, 168, 192,  5.1),
    ("Ford Chicanes Last", 220,  72, 108,  5.5),
]


class MockTelemetryProvider(TelemetryProvider):
    """Simulates LMU telemetry. Used on Mac where rF2 shared memory is unavailable."""

    def __init__(self) -> None:
        self._state = TelemetryState()
        self._running = False
        self._task: asyncio.Task | None = None

        # Timing
        self._race_start: float = 0.0
        self._lap_start: float = 0.0
        self._prev_lap_count: int = 0

        # Randomise lap duration slightly per lap to feel organic
        self._current_lap_duration: float = _LAP_DURATION_BASE

        # FCY scheduling — trigger one every ~45 min, lasting 5 min
        self._fcy_next_trigger: float = 2700.0   # seconds into race
        self._fcy_end: float = 0.0

        # Initialise starting state for a mid-field GT3 at race start
        self._state.fuel_l = 110.0
        self._state.position = 6
        self._state.position_in_class = 4
        self._state.total_cars = 32
        self._state.total_cars_in_class = 12
        self._state.gap_to_car_ahead = 4.2
        self._state.gap_to_car_behind = 1.8
        self._state.gap_to_leader = 0.0
        self._state.track_name = "Circuit de la Sarthe"
        self._state.session_type = "Race"
        self._state.vehicle_name = "BMW M4 GT3"
        self._state.vehicle_class = "GT3"
        self._state.track_temp_c = 32.0
        self._state.air_temp_c = 22.0
        self._state.session_time_remaining = 86400.0

    # ------------------------------------------------------------------
    # TelemetryProvider interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._race_start = time.monotonic()
        self._lap_start = self._race_start
        self._running = True
        self._task = asyncio.create_task(self._update_loop(), name="mock_telemetry")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def get_state(self) -> TelemetryState:
        return self._state

    # ------------------------------------------------------------------
    # Simulation loop
    # ------------------------------------------------------------------

    async def _update_loop(self) -> None:
        while self._running:
            await asyncio.sleep(0.02)   # 50fps telemetry tick
            self._tick()

    def _tick(self) -> None:
        now = time.monotonic()
        elapsed = now - self._race_start
        time_in_lap = now - self._lap_start

        # --- Lap completion ---
        if time_in_lap >= self._current_lap_duration:
            self._complete_lap(time_in_lap)
            self._lap_start = now
            time_in_lap = 0.0
            self._current_lap_duration = _LAP_DURATION_BASE + random.gauss(0, 0.8)

        # --- Session time ---
        self._state.race_elapsed_time = elapsed
        self._state.session_time_remaining = max(0.0, 86400.0 - elapsed)
        self._state.lap_time_current = time_in_lap

        # --- FCY management ---
        self._update_fcy(elapsed)

        # --- Dynamic lap simulation ---
        # Progress through the lap as a phase 0→1
        phase = time_in_lap / self._current_lap_duration

        # Speed: rough circuit profile — long straights, hairpins, chicanes
        speed = self._simulate_speed(phase)
        self._state.speed_kmh = speed

        # Throttle / brake derived from speed gradient
        speed_norm = speed / 280.0
        if speed_norm > 0.7:
            self._state.throttle = min(1.0, speed_norm)
            self._state.brake = 0.0
        else:
            self._state.throttle = 0.0
            self._state.brake = min(1.0, (0.7 - speed_norm) * 3)

        self._state.gear = max(1, min(6, int(speed / 50) + 1))
        self._state.rpm = 2500 + self._state.throttle * 5000 + random.gauss(0, 80)

        # --- Tyre temps ---
        base_temp = 82 + speed * 0.08
        self._state.tyres.temp_fl = base_temp + random.gauss(0, 2)
        self._state.tyres.temp_fr = base_temp + 3 + random.gauss(0, 2)   # rear-biased circuit
        self._state.tyres.temp_rl = base_temp - 1 + random.gauss(0, 2)
        self._state.tyres.temp_rr = base_temp + 1 + random.gauss(0, 2)

        # --- Fuel (continuous drain, litres) ---
        fuel_drain_rate = (_FUEL_PER_LAP / self._current_lap_duration) * 0.02
        if not self._state.in_pit:
            self._state.fuel_l = max(0.0, self._state.fuel_l - fuel_drain_rate)

        # --- Gaps (jitter around a mean) ---
        self._state.gap_to_car_ahead = max(0.0, self._state.gap_to_car_ahead + random.gauss(0, 0.05))
        self._state.gap_to_car_behind = max(0.0, self._state.gap_to_car_behind + random.gauss(0, 0.05))

    def _complete_lap(self, actual_duration: float) -> None:
        s = self._state
        s.laps_completed += 1
        s.lap_number = s.laps_completed + 1

        # Lap time with natural variation
        lap_time = actual_duration + random.gauss(0, 0.4)
        s.lap_time_last = round(lap_time, 3)
        if s.lap_time_best == 0.0 or lap_time < s.lap_time_best:
            s.lap_time_best = round(lap_time, 3)

        # Sector splits (roughly 30/35/35 split)
        s.sector1_last = round(lap_time * 0.30 + random.gauss(0, 0.1), 3)
        s.sector2_last = round(lap_time * 0.35 + random.gauss(0, 0.1), 3)
        s.sector3_last = round(lap_time - s.sector1_last - s.sector2_last, 3)

        # Tyre wear increment
        wear_delta = _WEAR_PER_LAP + random.gauss(0, 0.001)
        t = s.tyres
        t.wear_fl = min(1.0, t.wear_fl + wear_delta * 0.95)
        t.wear_fr = min(1.0, t.wear_fr + wear_delta * 1.10)  # front-right wears hardest
        t.wear_rl = min(1.0, t.wear_rl + wear_delta * 0.90)
        t.wear_rr = min(1.0, t.wear_rr + wear_delta * 1.00)

        # Corner analysis — simulate each corner with natural lap-to-lap variation
        s.corners_last_lap = []
        for name, entry, apex, exit_, time_s in _CIRCUIT_CORNERS:
            # Tyre degradation widens variation and reduces apex speed slightly
            wear_factor = 1.0 + s.tyres.max_wear * 0.04
            s.corners_last_lap.append(CornerData(
                name=name,
                entry_speed_kmh=round(entry + random.gauss(0, 4), 1),
                apex_speed_kmh=round((apex / wear_factor) + random.gauss(0, 3), 1),
                exit_speed_kmh=round((exit_ / wear_factor) + random.gauss(0, 3), 1),
                time_s=round(time_s * wear_factor + random.gauss(0, 0.08), 3),
            ))

        # Position slowly improves over the race
        elapsed_h = s.race_elapsed_time / 3600
        s.position = max(1, 6 - int(elapsed_h * 0.3))
        s.position_in_class = max(1, 4 - int(elapsed_h * 0.2))
        s.gap_to_leader = max(0.0, s.position * 12.0 + random.gauss(0, 3))

        # Update mock opponents — gaps drift slightly each lap
        opponents = []
        for rank, (driver, car, cls, base_gap) in enumerate(_MOCK_OPPONENTS):
            pos = rank + 1 if rank < s.position - 1 else rank + 2
            gap = max(0.0, base_gap + random.gauss(0, 1.5))
            opponents.append(Opponent(
                driver_name=driver,
                vehicle_name=car,
                vehicle_class=cls,
                position=pos,
                gap_to_leader_s=round(gap, 1),
                last_lap_s=round(_LAP_DURATION_BASE + random.gauss(0, 0.8), 3),
                best_lap_s=round(_LAP_DURATION_BASE - 0.5 + random.gauss(0, 0.3), 3),
                laps_completed=s.laps_completed,
                in_pit=random.random() < 0.03,
            ))
        s.opponents = opponents

    def _simulate_speed(self, phase: float) -> float:
        """
        Approximate circuit speed profile using overlapping sinusoids.
        Produces realistic bursts of high speed (straight) and low speed (corners).
        """
        # Primary pattern: 4 straights per lap
        s1 = 130 * math.sin(phase * 2 * math.pi * 4)
        # Secondary: chicane sections
        s2 = 40 * math.sin(phase * 2 * math.pi * 7 + 0.5)
        speed = 165 + s1 + s2 + random.gauss(0, 4)
        return max(60.0, min(310.0, speed))

    def _update_fcy(self, elapsed: float) -> None:
        """Schedule and clear Full Course Yellow periods."""
        if elapsed >= self._fcy_next_trigger and self._state.fcy_active is False:
            self._state.fcy_active = True
            self._fcy_end = elapsed + 300.0   # 5 minute FCY window
            self._fcy_next_trigger = elapsed + 2700.0 + random.gauss(0, 300)

        if self._state.fcy_active and elapsed >= self._fcy_end:
            self._state.fcy_active = False
