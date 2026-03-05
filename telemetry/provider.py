from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class CornerData:
    """Per-corner performance for a single lap."""
    name: str
    entry_speed_kmh: float      # speed at braking point
    apex_speed_kmh: float       # minimum speed through the corner
    exit_speed_kmh: float       # speed at exit
    time_s: float               # total time spent in this corner zone


@dataclass
class TyreData:
    """Per-corner tyre state."""
    temp_fl: float = 80.0   # Celsius
    temp_fr: float = 80.0
    temp_rl: float = 80.0
    temp_rr: float = 80.0
    wear_fl: float = 0.0    # 0.0 = new, 1.0 = destroyed
    wear_fr: float = 0.0
    wear_rl: float = 0.0
    wear_rr: float = 0.0

    @property
    def max_wear(self) -> float:
        return max(self.wear_fl, self.wear_fr, self.wear_rl, self.wear_rr)

    @property
    def avg_temp(self) -> float:
        return (self.temp_fl + self.temp_fr + self.temp_rl + self.temp_rr) / 4


@dataclass
class TelemetryState:
    """
    Unified telemetry snapshot. Populated from rF2 shared memory on Windows,
    or from MockTelemetryProvider on Mac (dev).
    """
    # --- Vehicle state (50fps) ---
    speed_kmh: float = 0.0
    throttle: float = 0.0       # 0.0–1.0
    brake: float = 0.0          # 0.0–1.0
    gear: int = 0               # -1 = reverse, 0 = neutral, 1–n = gear
    rpm: float = 0.0
    fuel_l: float = 100.0
    battery_charge_fraction: float = 0.0   # 0.0–1.0; 0 if no hybrid system

    tyres: TyreData = field(default_factory=TyreData)

    # --- Lap timing (5fps) ---
    lap_number: int = 1
    laps_completed: int = 0
    lap_time_current: float = 0.0   # seconds into current lap
    lap_time_last: float = 0.0
    lap_time_best: float = 0.0
    sector1_last: float = 0.0
    sector2_last: float = 0.0
    sector3_last: float = 0.0

    # --- Race standings (5fps) ---
    position: int = 1
    position_in_class: int = 1
    total_cars: int = 30
    total_cars_in_class: int = 10
    gap_to_leader: float = 0.0      # seconds, positive = behind
    gap_to_car_ahead: float = 0.0
    gap_to_car_behind: float = 0.0

    # --- Pit state ---
    in_pit: bool = False
    pit_limiter_active: bool = False

    # --- Race events (5fps extended buffer) ---
    fcy_active: bool = False
    safety_car_active: bool = False

    # --- Damage ---
    damage_aero: float = 0.0        # 0.0–1.0
    damage_engine: float = 0.0
    damage_suspension: float = 0.0

    # --- Weather (1fps) ---
    air_temp_c: float = 20.0
    track_temp_c: float = 30.0
    rain_intensity: float = 0.0     # 0.0–1.0

    # --- Session ---
    session_time_remaining: float = 86400.0  # seconds
    race_elapsed_time: float = 0.0
    track_name: str = ""
    session_type: str = ""          # e.g. "Race", "Qualifying", "Practice"
    vehicle_name: str = ""

    # --- Corner analysis (populated on lap completion) ---
    corners_last_lap: list = field(default_factory=list)  # list[CornerData]


class TelemetryProvider(ABC):
    """Abstract interface for telemetry sources (rF2 shared memory or mock)."""

    @abstractmethod
    async def start(self) -> None:
        """Initialise and begin updates."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop updates and release resources."""
        ...

    @abstractmethod
    async def get_state(self) -> TelemetryState:
        """Return the most recent telemetry snapshot."""
        ...
