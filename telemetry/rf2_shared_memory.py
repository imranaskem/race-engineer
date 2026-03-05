"""
RF2SharedMemoryProvider — reads live LMU telemetry via LMU's built-in shared memory.

Uses struct definitions from S397's official SharedMemoryInterface header
(vendored via pyLMUSharedMemory by the TinyPedal team).

Single shared memory file: "LMU_Data" — no additional plugins required beyond
what ships with LMU by default.
"""

import asyncio
import math

from .lmu_data import LMUConstants, SimInfo
from .provider import CornerData, TelemetryProvider, TelemetryState, TyreData

# Fuel density for petrol — GT3/GTE/Hypercar ~0.750 kg/l
_FUEL_DENSITY = 0.750

# LMU game phase values (InternalsPlugin.hpp)
_PHASE_FCY          = 6   # Full course yellow / safety car
_PHASE_SESSION_STOP = 7   # Session stopped

# Yellow flag state: 2 = pits closed (SC/FCY deployed)
_YELLOW_PIT_CLOSED  = 2

# Corner detection thresholds
_CORNER_ENTRY_SPEED_KMH = 210.0
_CORNER_MIN_APEX_SPEED  = 40.0
_CORNER_MIN_DURATION_S  = 0.8


# ===========================================================================
# Corner tracker — unchanged from original, detects corners from speed minima
# ===========================================================================

class _CornerTracker:
    def __init__(self) -> None:
        self._in_corner = False
        self._corner_entry_speed: float = 0.0
        self._corner_entry_time: float = 0.0
        self._apex_speed: float = 999.0
        self._apex_time: float = 0.0
        self._prev_speed: float = 999.0
        self._corner_index: int = 0
        self._completed: list[CornerData] = []

    def update(self, speed_kmh: float, time_in_lap: float) -> None:
        if not self._in_corner:
            if speed_kmh < _CORNER_ENTRY_SPEED_KMH and self._prev_speed >= _CORNER_ENTRY_SPEED_KMH:
                self._in_corner = True
                self._corner_entry_speed = self._prev_speed
                self._corner_entry_time = time_in_lap
                self._apex_speed = speed_kmh
                self._apex_time = time_in_lap
        else:
            if speed_kmh < self._apex_speed:
                self._apex_speed = speed_kmh
                self._apex_time = time_in_lap

            if speed_kmh >= _CORNER_ENTRY_SPEED_KMH:
                duration = time_in_lap - self._corner_entry_time
                if duration >= _CORNER_MIN_DURATION_S and self._apex_speed >= _CORNER_MIN_APEX_SPEED:
                    self._corner_index += 1
                    self._completed.append(CornerData(
                        name=f"Corner {self._corner_index}",
                        entry_speed_kmh=round(self._corner_entry_speed, 1),
                        apex_speed_kmh=round(self._apex_speed, 1),
                        exit_speed_kmh=round(speed_kmh, 1),
                        time_s=round(duration, 3),
                    ))
                self._in_corner = False

        self._prev_speed = speed_kmh

    def get_and_reset(self) -> list[CornerData]:
        result = self._completed
        self._completed = []
        self._corner_index = 0
        self._in_corner = False
        return result


# ===========================================================================
# Provider
# ===========================================================================

class RF2SharedMemoryProvider(TelemetryProvider):
    """
    Reads live LMU telemetry from the game's built-in shared memory interface.
    Opens automatically when LMU starts; reconnects if the game is restarted.
    """

    def __init__(self) -> None:
        self._state = TelemetryState()
        self._running = False
        self._task: asyncio.Task | None = None
        self._sim: SimInfo | None = None
        self._corner_tracker = _CornerTracker()
        self._prev_lap_number: int = -1

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name="lmu_shmem")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._sim:
            self._sim.close()
            self._sim = None

    async def get_state(self) -> TelemetryState:
        return self._state

    # ------------------------------------------------------------------
    # Poll loop
    # ------------------------------------------------------------------

    async def _poll_loop(self) -> None:
        import config
        while self._running:
            await asyncio.sleep(config.TELEMETRY_POLL_INTERVAL)
            try:
                await asyncio.to_thread(self._read)
            except Exception:
                pass  # Never crash the loop

    def _read(self) -> None:
        """Read from shared memory and update self._state. Called in thread."""
        # Open shared memory on first call or after LMU restart
        if self._sim is None:
            try:
                self._sim = SimInfo()
            except OSError:
                return  # LMU not running yet

        try:
            data = self._sim.LMUData
        except Exception:
            self._sim = None
            return

        tel = data.telemetry
        scor = data.scoring
        info = scor.scoringInfo

        if not tel.playerHasVehicle or int(info.mNumVehicles) <= 0:
            return

        # Player's telemetry — direct index provided by the game
        idx = int(tel.playerVehicleIdx)
        v = tel.telemInfo[idx]

        # Player's scoring — find by mIsPlayer flag
        player_s = None
        for i in range(min(int(info.mNumVehicles), LMUConstants.MAX_MAPPED_VEHICLES)):
            sv = scor.vehScoringInfo[i]
            if sv.mIsPlayer:
                player_s = sv
                break

        self._apply_telemetry(v, self._state)
        if player_s is not None:
            self._apply_scoring(info, player_s, self._state)

    # ------------------------------------------------------------------
    # Telemetry
    # ------------------------------------------------------------------

    def _apply_telemetry(self, v, s: TelemetryState) -> None:
        # Speed from local velocity vector (m/s → km/h)
        vx, vy, vz = v.mLocalVel.x, v.mLocalVel.y, v.mLocalVel.z
        s.speed_kmh = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6

        s.throttle = max(0.0, min(1.0, float(v.mUnfilteredThrottle)))
        s.brake    = max(0.0, min(1.0, float(v.mUnfilteredBrake)))
        s.gear     = int(v.mGear)
        s.rpm      = float(v.mEngineRPM)

        # Fuel: mFuel is in litres → convert to kg
        s.fuel_kg  = float(v.mFuel) * _FUEL_DENSITY

        # Tyres — FL=0, FR=1, RL=2, RR=3
        wh = v.mWheels

        def _temp_c(w) -> float:
            return sum(w.mTemperature) / 3.0 - 273.15  # Kelvin → Celsius

        def _wear(w) -> float:
            return max(0.0, min(1.0, float(w.mWear)))

        s.tyres = TyreData(
            temp_fl=round(_temp_c(wh[0]), 1),
            temp_fr=round(_temp_c(wh[1]), 1),
            temp_rl=round(_temp_c(wh[2]), 1),
            temp_rr=round(_temp_c(wh[3]), 1),
            wear_fl=_wear(wh[0]),
            wear_fr=_wear(wh[1]),
            wear_rl=_wear(wh[2]),
            wear_rr=_wear(wh[3]),
        )

        # Damage: dent severity 0–2 at 8 body locations → normalise to 0.0–1.0
        dent_max = max(int(v.mDentSeverity[i]) for i in range(8))
        s.damage_aero       = dent_max / 2.0
        s.damage_engine     = 1.0 if v.mOverheating else 0.0
        s.damage_suspension = 0.0  # not directly exposed in LMU SM

        s.pit_limiter_active = bool(v.mSpeedLimiter)

        # Lap tracking
        current_lap = int(v.mLapNumber)
        s.lap_time_current = float(v.mElapsedTime) - float(v.mLapStartET)

        if current_lap != self._prev_lap_number and self._prev_lap_number != -1:
            s.corners_last_lap = self._corner_tracker.get_and_reset()

        self._prev_lap_number = current_lap
        s.lap_number = current_lap
        self._corner_tracker.update(s.speed_kmh, s.lap_time_current)

    # ------------------------------------------------------------------
    # Scoring
    # ------------------------------------------------------------------

    def _apply_scoring(self, info, v, s: TelemetryState) -> None:
        s.race_elapsed_time      = float(info.mCurrentET)
        s.session_time_remaining = max(0.0, float(info.mEndET) - float(info.mCurrentET))

        phase  = int(info.mGamePhase)
        # mYellowFlagState is c_char — convert bytes to signed int
        yellow = int.from_bytes(info.mYellowFlagState, byteorder="little", signed=True)

        s.fcy_active        = (phase == _PHASE_FCY)
        s.safety_car_active = (phase == _PHASE_SESSION_STOP or yellow >= _YELLOW_PIT_CLOSED)

        s.track_temp_c  = float(info.mTrackTemp)
        s.air_temp_c    = float(info.mAmbientTemp)
        s.rain_intensity = max(0.0, min(1.0, float(info.mRaining)))

        s.position          = int(v.mPlace)
        s.total_cars        = int(info.mNumVehicles)
        s.position_in_class = int(v.mPlace)  # class filtering requires class roster logic

        s.gap_to_leader    = max(0.0, float(v.mTimeBehindLeader))
        s.gap_to_car_ahead = max(0.0, float(v.mTimeBehindNext))

        s.laps_completed = max(0, int(v.mTotalLaps))
        s.lap_time_last  = max(0.0, float(v.mLastLapTime))
        s.lap_time_best  = max(0.0, float(v.mBestLapTime))
        s.sector1_last   = max(0.0, float(v.mLastSector1))
        s.sector2_last   = max(0.0, float(v.mLastSector2))
        s.sector3_last   = max(0.0, s.lap_time_last - s.sector1_last - s.sector2_last)

        s.in_pit = bool(v.mInPits)
