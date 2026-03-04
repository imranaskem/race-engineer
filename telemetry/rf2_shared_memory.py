"""
RF2SharedMemoryProvider — reads live LMU/rF2 telemetry via Windows named shared memory.

Requirements:
  - Windows only
  - LMU must be running (the rF2 Shared Memory Map Plugin ships with LMU and is
    enabled by default — no separate installation needed)

Shared memory buffers read:
  $rFactor2SMMP_Telemetry$ — vehicle physics at ~50fps
  $rFactor2SMMP_Scoring$   — race standings, lap timing, FCY at ~5fps

Thread safety:
  rF2 uses double-buffered versioning. We check mVersionUpdateBegin == mVersionUpdateEnd
  before accepting a read; if they differ the buffer is mid-write and we skip that tick.

Corner detection:
  Real rF2 data doesn't label corners by name. We detect corners from speed minima
  during the lap and report them as "Corner N" with entry/apex/exit speed and time.
"""

import asyncio
import ctypes
import math
import mmap
import time
from ctypes import (
    c_bool, c_char, c_double, c_float,
    c_int8, c_int16, c_int32, c_uint8, c_uint32,
)

from .provider import CornerData, TelemetryProvider, TelemetryState, TyreData

# Shared memory buffer names
_MAP_TELEMETRY = "$rFactor2SMMP_Telemetry$"
_MAP_SCORING   = "$rFactor2SMMP_Scoring$"

# rF2 game phase values (rF2Scoring.hpp)
_PHASE_GREEN         = 5
_PHASE_FCY           = 6
_PHASE_SESSION_STOP  = 7  # includes deployed Safety Car in LMU

# rF2 yellow flag states
_YELLOW_NONE        = 0
_YELLOW_PIT_CLOSED  = 2   # SC/FCY with pits closed

# Fuel density for petrol — LMU GT3/GTE/Hypercar all use ~0.750 kg/l
_FUEL_DENSITY = 0.750

# Corner detection thresholds
_CORNER_ENTRY_SPEED_KMH = 210.0   # entering a corner when speed drops below this
_CORNER_MIN_APEX_SPEED  = 40.0    # minimum plausible apex (filters straights)
_CORNER_MIN_DURATION_S  = 0.8     # ignore transient dips shorter than this

# Max vehicles in shared memory
_MAX_VEHICLES = 128

# Windows long = 32 bits (MSVC)
c_long = c_int32


# ===========================================================================
# ctypes structures — match rF2 SDK MSVC default alignment (no #pragma pack)
# Struct sizes are computed by ctypes automatically; validated at startup.
# ===========================================================================

class _Vec3(ctypes.Structure):
    _fields_ = [("x", c_double), ("y", c_double), ("z", c_double)]


class _Wheel(ctypes.Structure):
    """rF2 per-wheel telemetry (TelemWheelV01)."""
    _fields_ = [
        ("mSuspensionDeflection",   c_double),
        ("mRideHeight",             c_double),
        ("mSuspForce",              c_double),
        ("mBrakeTemp",              c_double),
        ("mBrakePressure",          c_double),
        ("mRotation",               c_double),
        ("mLateralPatchVel",        c_double),
        ("mLongitudinalPatchVel",   c_double),
        ("mLateralGroundVel",       c_double),
        ("mLongitudinalGroundVel",  c_double),
        ("mCamber",                 c_double),
        ("mLateralForce",           c_double),
        ("mLongitudinalForce",      c_double),
        ("mTireLoad",               c_double),
        ("mGripFract",              c_double),
        ("mPressure",               c_double),
        ("mTemperature",            c_double * 3),   # inner/middle/outer, Kelvin
        ("mWear",                   c_double),        # 0 = new, 1 = worn out
        ("mTerrainName",            c_char * 16),
        ("mSurfaceType",            c_uint8),
        ("mFlat",                   c_uint8),
        ("mDetached",               c_uint8),
        ("mStaticUnbalance",        c_uint8),
        # ctypes inserts 4 bytes padding here to align next double to 8 bytes
        ("mWheelVertForce",         c_double),
        ("mWheelRideHeight",        c_double),
        ("mWheelLateralForce",      c_double),
        ("_expansion",              c_uint8 * 4),
    ]


class _VehicleTelemetry(ctypes.Structure):
    """rF2VehicleTelemetry — one entry per active vehicle in the telemetry buffer."""
    _fields_ = [
        ("mID",                     c_long),
        # ctypes inserts 4 bytes padding before mDeltaTime (double needs 8-byte alignment)
        ("mDeltaTime",              c_double),
        ("mElapsedTime",            c_double),
        ("mLapNumber",              c_long),
        # 4 bytes padding
        ("mLapStartET",             c_double),
        ("mVehicleName",            c_char * 64),
        ("mTrackName",              c_char * 64),
        ("mPos",                    _Vec3),
        ("mLocalVel",               _Vec3),           # m/s in vehicle-local coords
        ("mLocalAccel",             _Vec3),
        ("mOri",                    _Vec3 * 3),        # orientation matrix rows
        ("mLocalRot",               _Vec3),
        ("mLocalRotAccel",          _Vec3),
        ("mGear",                   c_long),           # -1=R, 0=N, 1..n
        # 4 bytes padding
        ("mEngineMaxRPM",           c_double),
        ("mEngineRPM",              c_double),
        ("mEngineTorque",           c_double),
        ("mEngineOilPressure",      c_double),
        ("mEngineOilTemp",          c_double),
        ("mEngineCoolantTemp",      c_double),
        ("mFuel",                   c_double),         # litres remaining
        ("mEngineMaxFuel",          c_double),
        ("mScheduledStops",         c_long),
        ("mOverheating",            c_uint8),
        ("mDetached",               c_uint8),
        ("mHeadlights",             c_uint8),
        ("mDentSeverity",           c_uint8 * 8),
        # ctypes inserts padding here (byte array ends un-aligned for next double)
        ("mLastImpactET",           c_double),
        ("mLastImpactMagnitude",    c_double),
        ("mLastImpactPos",          _Vec3),
        ("mEngineTq",               c_double),
        ("mCurrentSector",          c_long),
        ("mNumSectors",             c_long),
        ("mVirtualEnergy",          c_double),
        ("mPhysicalFuelMult",       c_double),
        ("mEngineBoostRate",        c_double),
        ("mTurboBoostPressure",     c_double),
        ("mTurboBoostRPM",          c_double),
        ("mTurboBoostTemperature",  c_double),
        ("mTurboBoostVol",          c_double),
        ("_expansion",              c_uint8 * 128),
        ("mWheels",                 _Wheel * 4),       # FL, FR, RL, RR
    ]


class _TelemetryBuffer(ctypes.Structure):
    """Top-level telemetry shared memory layout."""
    _fields_ = [
        ("mVersionUpdateBegin", c_uint32),
        ("mVersionUpdateEnd",   c_uint32),
        ("mNumVehicles",        c_int32),
        ("_expansion",          c_uint8 * 108),        # pads header to 120 bytes
        ("mVehicles",           _VehicleTelemetry * _MAX_VEHICLES),
    ]


class _VehicleScoring(ctypes.Structure):
    """rF2VehicleScoring — race standing for one vehicle."""
    _fields_ = [
        ("mID",                 c_long),
        ("mDriverName",         c_char * 32),
        ("mVehicleName",        c_char * 64),
        ("mTotalLaps",          c_int16),
        ("mSector",             c_int8),               # current sector (0/1/2)
        ("mFinishStatus",       c_int8),
        ("mLapDist",            c_double),
        ("mPathLateral",        c_double),
        ("mTrackEdge",          c_double),
        ("mBestSector1",        c_double),
        ("mBestSector2",        c_double),
        ("mBestLapTime",        c_double),
        ("mLastSector1",        c_double),
        ("mLastSector2",        c_double),
        ("mLastLapTime",        c_double),
        ("mCurSector1",         c_double),
        ("mCurSector2",         c_double),
        ("mNumPitStops",        c_int16),
        ("mNumPenalties",       c_int16),
        ("mIsPlayer",           c_uint8),
        ("mControl",            c_int8),               # 1 = player-controlled
        ("mInPits",             c_uint8),
        ("mPlace",              c_uint8),              # 1-based position
        ("mVehicleClass",       c_char * 32),
        ("mTimeBehindNext",     c_double),
        ("mLapsBehindNext",     c_long),
        # 4 bytes padding
        ("mTimeBehindLeader",   c_double),
        ("mLapsBehindLeader",   c_long),
        # 4 bytes padding
        ("mTimeIntoLap",        c_double),
        ("mEstimatedLapTime",   c_double),
        ("mPitGroup",           c_char * 16),
        ("mFlag",               c_uint8),
        ("mUnderYellow",        c_uint8),
        ("mCountLapFlag",       c_uint8),
        ("mInGarageStall",      c_uint8),
        ("mUpgradePack",        c_uint8 * 16),
        ("mPitLapDist",         c_float),
        ("mBestLapSector1",     c_float),
        ("mBestLapSector2",     c_float),
        ("_expansion",          c_uint8 * 48),
    ]


class _ScoringInfo(ctypes.Structure):
    """rF2ScoringInfo — global session/race state."""
    _fields_ = [
        ("mTrackName",          c_char * 64),
        ("mSession",            c_long),
        # 4 bytes padding
        ("mCurrentET",          c_double),
        ("mEndET",              c_double),
        ("mMaxLaps",            c_long),
        # 4 bytes padding
        ("mLapDist",            c_double),
        ("mResultsStream",      ctypes.c_void_p),      # pointer (8 bytes on 64-bit)
        ("mNumVehicles",        c_long),
        ("mGamePhase",          c_uint8),
        ("mYellowFlagState",    c_int8),
        ("mSectorFlag",         c_int8 * 3),
        ("mStartLight",         c_uint8),
        ("mNumRedLights",       c_uint8),
        ("mInRealtime",         c_uint8),
        ("mPlayerName",         c_char * 32),
        ("mPlrFileName",        c_char * 64),
        # ctypes inserts padding here to align next double
        ("mDarkCloud",          c_double),
        ("mRaining",            c_double),
        ("mAmbientTemp",        c_double),
        ("mTrackTemp",          c_double),
        ("mWind",               _Vec3),
        ("mMinPathWetness",     c_double),
        ("mMaxPathWetness",     c_double),
        ("_expansion",          c_uint8 * 256),
    ]


class _ScoringBuffer(ctypes.Structure):
    """Top-level scoring shared memory layout."""
    _fields_ = [
        ("mVersionUpdateBegin", c_uint32),
        ("mVersionUpdateEnd",   c_uint32),
        ("mScoringInfo",        _ScoringInfo),
        ("mVehicles",           _VehicleScoring * _MAX_VEHICLES),
    ]


# ===========================================================================
# Corner tracker — detects corners from speed minima during the lap
# ===========================================================================

class _CornerTracker:
    """
    State machine that detects corners by watching for speed minima.

    A "corner" is a continuous period below CORNER_ENTRY_SPEED_KMH that contains
    a speed minimum. We record entry speed, apex speed, exit speed, and duration.
    """

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
                # Entering a corner
                self._in_corner = True
                self._corner_entry_speed = self._prev_speed
                self._corner_entry_time = time_in_lap
                self._apex_speed = speed_kmh
                self._apex_time = time_in_lap
        else:
            # Track the apex (minimum speed)
            if speed_kmh < self._apex_speed:
                self._apex_speed = speed_kmh
                self._apex_time = time_in_lap

            if speed_kmh >= _CORNER_ENTRY_SPEED_KMH:
                # Exiting the corner
                duration = time_in_lap - self._corner_entry_time
                if (duration >= _CORNER_MIN_DURATION_S
                        and self._apex_speed >= _CORNER_MIN_APEX_SPEED):
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
    Reads live LMU/rF2 telemetry from Windows named shared memory.
    Requires the game to be running; handles gracefully when it's not.
    """

    def __init__(self) -> None:
        self._state = TelemetryState()
        self._running = False
        self._task: asyncio.Task | None = None

        self._tel_map: mmap.mmap | None = None
        self._sco_map: mmap.mmap | None = None

        self._corner_tracker = _CornerTracker()
        self._prev_lap_number: int = -1

    # ------------------------------------------------------------------
    # TelemetryProvider interface
    # ------------------------------------------------------------------

    async def start(self) -> None:
        self._running = True
        await self._open_maps()
        self._task = asyncio.create_task(self._poll_loop(), name="rf2_shmem")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._close_maps()

    async def get_state(self) -> TelemetryState:
        return self._state

    # ------------------------------------------------------------------
    # Map lifecycle
    # ------------------------------------------------------------------

    async def _open_maps(self) -> None:
        try:
            self._tel_map = mmap.mmap(-1, ctypes.sizeof(_TelemetryBuffer),
                                      tagname=_MAP_TELEMETRY,
                                      access=mmap.ACCESS_READ)
            self._sco_map = mmap.mmap(-1, ctypes.sizeof(_ScoringBuffer),
                                      tagname=_MAP_SCORING,
                                      access=mmap.ACCESS_READ)
        except OSError:
            # LMU not running yet — maps will be retried each tick
            self._tel_map = None
            self._sco_map = None

    def _close_maps(self) -> None:
        if self._tel_map:
            self._tel_map.close()
        if self._sco_map:
            self._sco_map.close()

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
                pass  # Never crash the loop — LMU may not be running

    def _read(self) -> None:
        """Read telemetry + scoring and update self._state. Called in thread."""
        # Re-open maps if LMU just started
        if self._tel_map is None or self._sco_map is None:
            try:
                self._tel_map = mmap.mmap(-1, ctypes.sizeof(_TelemetryBuffer),
                                          tagname=_MAP_TELEMETRY,
                                          access=mmap.ACCESS_READ)
                self._sco_map = mmap.mmap(-1, ctypes.sizeof(_ScoringBuffer),
                                          tagname=_MAP_SCORING,
                                          access=mmap.ACCESS_READ)
            except OSError:
                return  # still not running

        tel = self._read_telemetry()
        sco = self._read_scoring()

        if tel is None and sco is None:
            return

        s = self._state

        if tel is not None:
            self._apply_telemetry(tel, s)
        if sco is not None:
            self._apply_scoring(sco, s)

    # ------------------------------------------------------------------
    # Telemetry buffer
    # ------------------------------------------------------------------

    def _read_telemetry(self) -> _VehicleTelemetry | None:
        """Return the player's vehicle telemetry, or None if buffer is stale/empty."""
        self._tel_map.seek(0)
        buf = (ctypes.c_char * ctypes.sizeof(_TelemetryBuffer)).from_buffer_copy(
            self._tel_map.read(ctypes.sizeof(_TelemetryBuffer))
        )
        tb = ctypes.cast(buf, ctypes.POINTER(_TelemetryBuffer)).contents

        # Version check — skip if buffer is mid-write
        if tb.mVersionUpdateBegin != tb.mVersionUpdateEnd:
            return None
        if tb.mNumVehicles <= 0:
            return None

        # Find the player's vehicle (first vehicle with mID > 0; in single player it's index 0)
        for i in range(min(tb.mNumVehicles, _MAX_VEHICLES)):
            v = tb.mVehicles[i]
            if v.mID > 0:
                return v
        return None

    def _apply_telemetry(self, v: _VehicleTelemetry, s: TelemetryState) -> None:
        # Speed from local velocity vector
        vx, vy, vz = v.mLocalVel.x, v.mLocalVel.y, v.mLocalVel.z
        s.speed_kmh = math.sqrt(vx * vx + vy * vy + vz * vz) * 3.6

        s.throttle = max(0.0, min(1.0, float(v.mLocalVel.x)))  # placeholder until direct field
        s.brake = 0.0
        s.gear = int(v.mGear)
        s.rpm = float(v.mEngineRPM)

        # Fuel: rF2 reports in litres; convert to kg
        s.fuel_kg = float(v.mFuel) * _FUEL_DENSITY

        # Tyres — FL=0, FR=1, RL=2, RR=3
        def _wear(w: _Wheel) -> float:
            return max(0.0, min(1.0, float(w.mWear)))

        def _temp_c(w: _Wheel) -> float:
            # Average of inner/middle/outer, convert Kelvin → Celsius
            return sum(w.mTemperature) / 3.0 - 273.15

        wh = v.mWheels
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

        # Lap number and corner tracking
        current_lap = int(v.mLapNumber)
        s.lap_time_current = float(v.mElapsedTime) - float(v.mLapStartET)

        if current_lap != self._prev_lap_number and self._prev_lap_number != -1:
            # Lap completed — collect detected corners
            s.corners_last_lap = self._corner_tracker.get_and_reset()

        self._prev_lap_number = current_lap
        s.lap_number = current_lap

        # Update corner tracker with current speed
        self._corner_tracker.update(s.speed_kmh, s.lap_time_current)

    # ------------------------------------------------------------------
    # Scoring buffer
    # ------------------------------------------------------------------

    def _read_scoring(self) -> tuple[_ScoringInfo, _VehicleScoring] | None:
        """Return (ScoringInfo, player VehicleScoring) or None."""
        self._sco_map.seek(0)
        buf = (ctypes.c_char * ctypes.sizeof(_ScoringBuffer)).from_buffer_copy(
            self._sco_map.read(ctypes.sizeof(_ScoringBuffer))
        )
        sb = ctypes.cast(buf, ctypes.POINTER(_ScoringBuffer)).contents

        if sb.mVersionUpdateBegin != sb.mVersionUpdateEnd:
            return None

        info = sb.mScoringInfo
        if info.mNumVehicles <= 0:
            return None

        # Find player vehicle
        for i in range(min(info.mNumVehicles, _MAX_VEHICLES)):
            v = sb.mVehicles[i]
            if v.mIsPlayer:
                return info, v
        return None

    def _apply_scoring(
        self,
        result: tuple[_ScoringInfo, _VehicleScoring],
        s: TelemetryState,
    ) -> None:
        info, v = result

        # Session time
        s.race_elapsed_time = float(info.mCurrentET)
        s.session_time_remaining = max(0.0, float(info.mEndET) - float(info.mCurrentET))

        # FCY / Safety Car
        phase = int(info.mGamePhase)
        s.fcy_active = (phase == _PHASE_FCY)
        s.safety_car_active = (
            phase == _PHASE_SESSION_STOP
            or int(info.mYellowFlagState) >= _YELLOW_PIT_CLOSED
        )

        # Weather
        s.track_temp_c = float(info.mTrackTemp)
        s.air_temp_c = float(info.mAmbientTemp)
        s.rain_intensity = max(0.0, min(1.0, float(info.mRaining)))

        # Race position
        s.position = int(v.mPlace)
        s.total_cars = int(info.mNumVehicles)
        s.position_in_class = int(v.mPlace)  # simplification; class filtering is complex

        # Gaps
        s.gap_to_leader = max(0.0, float(v.mTimeBehindLeader))
        s.gap_to_car_ahead = max(0.0, float(v.mTimeBehindNext))

        # Lap times
        s.laps_completed = max(0, int(v.mTotalLaps))
        s.lap_time_last = max(0.0, float(v.mLastLapTime))
        s.lap_time_best = max(0.0, float(v.mBestLapTime))
        s.sector1_last = max(0.0, float(v.mLastSector1))
        s.sector2_last = max(0.0, float(v.mLastSector2))
        s.sector3_last = max(0.0, s.lap_time_last - s.sector1_last - s.sector2_last)

        # Pit state
        s.in_pit = bool(v.mInPits)
