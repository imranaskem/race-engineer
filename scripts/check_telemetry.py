"""
Sanity check script — verify LMU shared memory is readable and data looks correct.

Run on Windows while LMU is active on track:
    uv run python scripts/check_telemetry.py
"""
import math
import sys
import time

if sys.platform != "win32":
    print("This script must be run on Windows with LMU running.")
    sys.exit(1)

from telemetry.lmu_data import LMUConstants, SimInfo

print("Opening shared memory:", LMUConstants.LMU_SHARED_MEMORY_FILE)
try:
    sim = SimInfo()
except OSError as e:
    print(f"Failed to open shared memory: {e}")
    print("Is LMU running?")
    sys.exit(1)

print("Connected. Reading 5 samples (one per second)...\n")

for i in range(5):
    data = sim.LMUData
    tel = data.telemetry
    scor = data.scoring
    info = scor.scoringInfo

    has_vehicle = tel.playerHasVehicle
    player_idx = int(tel.playerVehicleIdx)
    num_vehicles = int(info.mNumVehicles)

    print(f"--- Sample {i + 1} ---")
    print(f"  Game version   : {data.generic.gameVersion}")
    print(f"  Track          : {info.mTrackName.decode(errors='replace')}")
    print(f"  Num vehicles   : {num_vehicles}")
    print(f"  Player has veh : {has_vehicle}  (idx={player_idx})")

    if has_vehicle and num_vehicles > 0:
        v = tel.telemInfo[player_idx]
        vx, vy, vz = v.mLocalVel.x, v.mLocalVel.y, v.mLocalVel.z
        speed_kmh = math.sqrt(vx*vx + vy*vy + vz*vz) * 3.6

        print(f"  Vehicle        : {v.mVehicleName.decode(errors='replace')}")
        print(f"  Speed          : {speed_kmh:.1f} km/h")
        print(f"  Gear           : {v.mGear}")
        print(f"  RPM            : {v.mEngineRPM:.0f}")
        print(f"  Fuel           : {v.mFuel:.2f} L  ({v.mFuel * 0.75:.2f} kg)")
        print(f"  Throttle       : {v.mUnfilteredThrottle:.2f}")
        print(f"  Brake          : {v.mUnfilteredBrake:.2f}")
        print(f"  Lap number     : {v.mLapNumber}")
        print(f"  Elapsed time   : {v.mElapsedTime:.2f}s")

        wh = v.mWheels
        def temp_c(w):
            return sum(w.mTemperature) / 3.0 - 273.15
        print(f"  Tyre temps (C) : FL={temp_c(wh[0]):.1f}  FR={temp_c(wh[1]):.1f}  RL={temp_c(wh[2]):.1f}  RR={temp_c(wh[3]):.1f}")
        print(f"  Tyre wear      : FL={wh[0].mWear:.3f}  FR={wh[1].mWear:.3f}  RL={wh[2].mWear:.3f}  RR={wh[3].mWear:.3f}")

        # Find player scoring
        for j in range(min(num_vehicles, LMUConstants.MAX_MAPPED_VEHICLES)):
            sv = scor.vehScoringInfo[j]
            if sv.mIsPlayer:
                print(f"  Position       : P{sv.mPlace} of {num_vehicles}")
                print(f"  Last lap       : {sv.mLastLapTime:.3f}s")
                print(f"  Best lap       : {sv.mBestLapTime:.3f}s")
                print(f"  In pits        : {sv.mInPits}")
                print(f"  Gap to leader  : {sv.mTimeBehindLeader:.2f}s")
                break

        print(f"  Game phase     : {info.mGamePhase}")
        print(f"  Rain           : {info.mRaining:.2f}")
        print(f"  Track temp     : {info.mTrackTemp:.1f}°C")
    else:
        print("  (no player vehicle data)")

    print()
    if i < 4:
        time.sleep(1)

sim.close()
print("Done.")
