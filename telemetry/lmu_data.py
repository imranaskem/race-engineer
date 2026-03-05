"""
Python mapping of LMU's built-in Shared Memory Interface.

Vendored from https://github.com/TinyPedal/pyLMUSharedMemory (MIT licence).
Source: S397's official SharedMemoryInterface header file.
"""
import ctypes
import mmap


class LMUConstants:
    LMU_SHARED_MEMORY_FILE: str = "LMU_Data"
    LMU_PROCESS_NAME: str = "Le Mans Ultimate"
    MAX_MAPPED_VEHICLES: int = 104
    MAX_PATH_LENGTH: int = 260


class LMUVect3(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("x", ctypes.c_double),
        ("y", ctypes.c_double),
        ("z", ctypes.c_double),
    ]


class LMUWheel(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("mSuspensionDeflection",       ctypes.c_double),
        ("mRideHeight",                 ctypes.c_double),
        ("mSuspForce",                  ctypes.c_double),
        ("mBrakeTemp",                  ctypes.c_double),
        ("mBrakePressure",              ctypes.c_double),
        ("mRotation",                   ctypes.c_double),
        ("mLateralPatchVel",            ctypes.c_double),
        ("mLongitudinalPatchVel",       ctypes.c_double),
        ("mLateralGroundVel",           ctypes.c_double),
        ("mLongitudinalGroundVel",      ctypes.c_double),
        ("mCamber",                     ctypes.c_double),
        ("mLateralForce",               ctypes.c_double),
        ("mLongitudinalForce",          ctypes.c_double),
        ("mTireLoad",                   ctypes.c_double),
        ("mGripFract",                  ctypes.c_double),
        ("mPressure",                   ctypes.c_double),
        ("mTemperature",                ctypes.c_double * 3),   # Kelvin, left/center/right
        ("mWear",                       ctypes.c_double),        # 1.0=new, 0.0=destroyed
        ("mTerrainName",                ctypes.c_char * 16),
        ("mSurfaceType",                ctypes.c_ubyte),
        ("mFlat",                       ctypes.c_bool),
        ("mDetached",                   ctypes.c_bool),
        ("mStaticUndeflectedRadius",    ctypes.c_ubyte),
        ("mVerticalTireDeflection",     ctypes.c_double),
        ("mWheelYLocation",             ctypes.c_double),
        ("mToe",                        ctypes.c_double),
        ("mTireCarcassTemperature",     ctypes.c_double),        # Kelvin
        ("mTireInnerLayerTemperature",  ctypes.c_double * 3),    # Kelvin
        ("mExpansion",                  ctypes.c_ubyte * 24),
    ]


class LMUVehicleTelemetry(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("mID",                         ctypes.c_int),
        ("mDeltaTime",                  ctypes.c_double),
        ("mElapsedTime",                ctypes.c_double),
        ("mLapNumber",                  ctypes.c_int),
        ("mLapStartET",                 ctypes.c_double),
        ("mVehicleName",                ctypes.c_char * 64),
        ("mTrackName",                  ctypes.c_char * 64),
        ("mPos",                        LMUVect3),
        ("mLocalVel",                   LMUVect3),               # m/s in local vehicle frame
        ("mLocalAccel",                 LMUVect3),
        ("mOri",                        LMUVect3 * 3),
        ("mLocalRot",                   LMUVect3),
        ("mLocalRotAccel",              LMUVect3),
        ("mGear",                       ctypes.c_int),           # -1=R, 0=N, 1+=forward
        ("mEngineRPM",                  ctypes.c_double),
        ("mEngineWaterTemp",            ctypes.c_double),
        ("mEngineOilTemp",              ctypes.c_double),
        ("mClutchRPM",                  ctypes.c_double),
        ("mUnfilteredThrottle",         ctypes.c_double),        # 0.0–1.0
        ("mUnfilteredBrake",            ctypes.c_double),        # 0.0–1.0
        ("mUnfilteredSteering",         ctypes.c_double),        # -1.0–1.0
        ("mUnfilteredClutch",           ctypes.c_double),
        ("mFilteredThrottle",           ctypes.c_double),
        ("mFilteredBrake",              ctypes.c_double),
        ("mFilteredSteering",           ctypes.c_double),
        ("mFilteredClutch",             ctypes.c_double),
        ("mSteeringShaftTorque",        ctypes.c_double),
        ("mFront3rdDeflection",         ctypes.c_double),
        ("mRear3rdDeflection",          ctypes.c_double),
        ("mFrontWingHeight",            ctypes.c_double),
        ("mFrontRideHeight",            ctypes.c_double),
        ("mRearRideHeight",             ctypes.c_double),
        ("mDrag",                       ctypes.c_double),
        ("mFrontDownforce",             ctypes.c_double),
        ("mRearDownforce",              ctypes.c_double),
        ("mFuel",                       ctypes.c_double),        # litres
        ("mEngineMaxRPM",               ctypes.c_double),
        ("mScheduledStops",             ctypes.c_ubyte),
        ("mOverheating",                ctypes.c_bool),
        ("mDetached",                   ctypes.c_bool),
        ("mHeadlights",                 ctypes.c_bool),
        ("mDentSeverity",               ctypes.c_ubyte * 8),     # 0=none, 1=some, 2=more
        ("mLastImpactET",               ctypes.c_double),
        ("mLastImpactMagnitude",        ctypes.c_double),
        ("mLastImpactPos",              LMUVect3),
        ("mEngineTorque",               ctypes.c_double),
        ("mCurrentSector",              ctypes.c_int),
        ("mSpeedLimiter",               ctypes.c_ubyte),
        ("mMaxGears",                   ctypes.c_ubyte),
        ("mFrontTireCompoundIndex",     ctypes.c_ubyte),
        ("mRearTireCompoundIndex",      ctypes.c_ubyte),
        ("mFuelCapacity",               ctypes.c_double),
        ("mFrontFlapActivated",         ctypes.c_ubyte),
        ("mRearFlapActivated",          ctypes.c_ubyte),
        ("mRearFlapLegalStatus",        ctypes.c_ubyte),
        ("mIgnitionStarter",            ctypes.c_ubyte),
        ("mFrontTireCompoundName",      ctypes.c_char * 18),
        ("mRearTireCompoundName",       ctypes.c_char * 18),
        ("mSpeedLimiterAvailable",      ctypes.c_ubyte),
        ("mAntiStallActivated",         ctypes.c_ubyte),
        ("mUnused",                     ctypes.c_ubyte * 2),
        ("mVisualSteeringWheelRange",   ctypes.c_float),
        ("mRearBrakeBias",              ctypes.c_double),
        ("mTurboBoostPressure",         ctypes.c_double),
        ("mPhysicsToGraphicsOffset",    ctypes.c_float * 3),
        ("mPhysicalSteeringWheelRange", ctypes.c_float),
        ("mDeltaBest",                  ctypes.c_double),
        ("mBatteryChargeFraction",      ctypes.c_double),        # 0.0–1.0
        ("mElectricBoostMotorTorque",   ctypes.c_double),
        ("mElectricBoostMotorRPM",      ctypes.c_double),
        ("mElectricBoostMotorTemperature", ctypes.c_double),
        ("mElectricBoostWaterTemperature", ctypes.c_double),
        ("mElectricBoostMotorState",    ctypes.c_ubyte),         # 0=unavailable,1=inactive,2=propulsion,3=regen
        ("mExpansion",                  ctypes.c_ubyte * (111 - 8)),
        ("mWheels",                     LMUWheel * 4),           # FL, FR, RL, RR
    ]


class LMUVehicleScoring(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("mID",                 ctypes.c_int),
        ("mDriverName",         ctypes.c_char * 32),
        ("mVehicleName",        ctypes.c_char * 64),
        ("mTotalLaps",          ctypes.c_short),
        ("mSector",             ctypes.c_byte),    # 0=sector3, 1=sector1, 2=sector2
        ("mFinishStatus",       ctypes.c_byte),    # 0=none,1=finished,2=dnf,3=dq
        ("mLapDist",            ctypes.c_double),
        ("mPathLateral",        ctypes.c_double),
        ("mTrackEdge",          ctypes.c_double),
        ("mBestSector1",        ctypes.c_double),
        ("mBestSector2",        ctypes.c_double),
        ("mBestLapTime",        ctypes.c_double),
        ("mLastSector1",        ctypes.c_double),
        ("mLastSector2",        ctypes.c_double),
        ("mLastLapTime",        ctypes.c_double),
        ("mCurSector1",         ctypes.c_double),
        ("mCurSector2",         ctypes.c_double),
        ("mNumPitstops",        ctypes.c_short),
        ("mNumPenalties",       ctypes.c_short),
        ("mIsPlayer",           ctypes.c_bool),
        ("mControl",            ctypes.c_byte),    # 0=local player,1=local AI,2=remote
        ("mInPits",             ctypes.c_bool),
        ("mPlace",              ctypes.c_ubyte),   # 1-based
        ("mVehicleClass",       ctypes.c_char * 32),
        ("mTimeBehindNext",     ctypes.c_double),
        ("mLapsBehindNext",     ctypes.c_int),
        ("mTimeBehindLeader",   ctypes.c_double),
        ("mLapsBehindLeader",   ctypes.c_int),
        ("mLapStartET",         ctypes.c_double),
        ("mPos",                LMUVect3),
        ("mLocalVel",           LMUVect3),
        ("mLocalAccel",         LMUVect3),
        ("mOri",                LMUVect3 * 3),
        ("mLocalRot",           LMUVect3),
        ("mLocalRotAccel",      LMUVect3),
        ("mHeadlights",         ctypes.c_ubyte),
        ("mPitState",           ctypes.c_ubyte),   # 0=none,1=request,2=entering,3=stopped,4=exiting
        ("mServerScored",       ctypes.c_ubyte),
        ("mIndividualPhase",    ctypes.c_ubyte),
        ("mQualification",      ctypes.c_int),
        ("mTimeIntoLap",        ctypes.c_double),
        ("mEstimatedLapTime",   ctypes.c_double),
        ("mPitGroup",           ctypes.c_char * 24),
        ("mFlag",               ctypes.c_ubyte),
        ("mUnderYellow",        ctypes.c_bool),
        ("mCountLapFlag",       ctypes.c_ubyte),
        ("mInGarageStall",      ctypes.c_bool),
        ("mUpgradePack",        ctypes.c_ubyte * 16),
        ("mPitLapDist",         ctypes.c_float),
        ("mBestLapSector1",     ctypes.c_float),
        ("mBestLapSector2",     ctypes.c_float),
        ("mSteamID",            ctypes.c_ulonglong),
        ("mVehFilename",        ctypes.c_char * 32),
        ("mAttackMode",         ctypes.c_short),
        ("mFuelFraction",       ctypes.c_ubyte),   # 0x00=0%, 0xFF=100%
        ("mDRSState",           ctypes.c_bool),
        ("mExpansion",          ctypes.c_ubyte * 4),
    ]


class LMUScoringInfo(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("mTrackName",          ctypes.c_char * 64),
        ("mSession",            ctypes.c_int),
        ("mCurrentET",          ctypes.c_double),
        ("mEndET",              ctypes.c_double),
        ("mMaxLaps",            ctypes.c_int),
        ("mLapDist",            ctypes.c_double),
        ("mResultsStreamPointer", ctypes.c_ubyte * 8),
        ("mNumVehicles",        ctypes.c_int),
        # Game phase: 0=before session, 5=green, 6=FCY/SC, 7=stopped, 8=over
        ("mGamePhase",          ctypes.c_ubyte),
        # Yellow flag: -1=invalid,0=none,1=pending,2=pits closed,3=pit lead lap,4=pits open,5=last lap,6=resume
        ("mYellowFlagState",    ctypes.c_char),
        ("mSectorFlag",         ctypes.c_ubyte * 3),
        ("mStartLight",         ctypes.c_ubyte),
        ("mNumRedLights",       ctypes.c_ubyte),
        ("mInRealtime",         ctypes.c_bool),
        ("mPlayerName",         ctypes.c_char * 32),
        ("mPlrFileName",        ctypes.c_char * 64),
        ("mDarkCloud",          ctypes.c_double),
        ("mRaining",            ctypes.c_double),
        ("mAmbientTemp",        ctypes.c_double),
        ("mTrackTemp",          ctypes.c_double),
        ("mWind",               LMUVect3),
        ("mMinPathWetness",     ctypes.c_double),
        ("mMaxPathWetness",     ctypes.c_double),
        ("mGameMode",           ctypes.c_ubyte),
        ("mIsPasswordProtected", ctypes.c_bool),
        ("mServerPort",         ctypes.c_ushort),
        ("mServerPublicIP",     ctypes.c_uint),
        ("mMaxPlayers",         ctypes.c_int),
        ("mServerName",         ctypes.c_char * 32),
        ("mStartET",            ctypes.c_float),
        ("mAvgPathWetness",     ctypes.c_double),
        ("mExpansion",          ctypes.c_ubyte * 200),
        ("mVehiclePointer",     ctypes.c_ubyte * 8),
    ]


class LMUApplicationState(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("mAppWindow",      ctypes.c_ulonglong),
        ("mWidth",          ctypes.c_uint),
        ("mHeight",         ctypes.c_uint),
        ("mRefreshRate",    ctypes.c_uint),
        ("mWindowed",       ctypes.c_uint),
        ("mOptionsLocation", ctypes.c_ubyte),
        ("mOptionsPage",    ctypes.c_char * 31),
        ("mExpansion",      ctypes.c_ubyte * 204),
    ]


class LMUScoringData(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("scoringInfo",     LMUScoringInfo),
        ("scoringStreamSize", ctypes.c_ubyte * 12),
        ("vehScoringInfo",  LMUVehicleScoring * LMUConstants.MAX_MAPPED_VEHICLES),
        ("scoringStream",   ctypes.c_char * 65536),
    ]


class LMUTelemetryData(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("activeVehicles",  ctypes.c_uint8),
        ("playerVehicleIdx", ctypes.c_uint8),
        ("playerHasVehicle", ctypes.c_bool),
        ("telemInfo",       LMUVehicleTelemetry * LMUConstants.MAX_MAPPED_VEHICLES),
    ]


class LMUPathData(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("userData",        ctypes.c_char * LMUConstants.MAX_PATH_LENGTH),
        ("customVariables", ctypes.c_char * LMUConstants.MAX_PATH_LENGTH),
        ("stewardResults",  ctypes.c_char * LMUConstants.MAX_PATH_LENGTH),
        ("playerProfile",   ctypes.c_char * LMUConstants.MAX_PATH_LENGTH),
        ("pluginsFolder",   ctypes.c_char * LMUConstants.MAX_PATH_LENGTH),
    ]


class LMUEvent(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("SME_ENTER",               ctypes.c_uint),
        ("SME_EXIT",                ctypes.c_uint),
        ("SME_STARTUP",             ctypes.c_uint),
        ("SME_SHUTDOWN",            ctypes.c_uint),
        ("SME_LOAD",                ctypes.c_uint),
        ("SME_UNLOAD",              ctypes.c_uint),
        ("SME_START_SESSION",       ctypes.c_uint),
        ("SME_END_SESSION",         ctypes.c_uint),
        ("SME_ENTER_REALTIME",      ctypes.c_uint),
        ("SME_EXIT_REALTIME",       ctypes.c_uint),
        ("SME_UPDATE_SCORING",      ctypes.c_uint),
        ("SME_UPDATE_TELEMETRY",    ctypes.c_uint),
        ("SME_INIT_APPLICATION",    ctypes.c_uint),
        ("SME_UNINIT_APPLICATION",  ctypes.c_uint),
        ("SME_SET_ENVIRONMENT",     ctypes.c_uint),
        ("SME_FFB",                 ctypes.c_uint),
    ]


class LMUGeneric(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("events",      LMUEvent),
        ("gameVersion", ctypes.c_int),
        ("FFBTorque",   ctypes.c_float),
        ("appInfo",     LMUApplicationState),
    ]


class LMUObjectOut(ctypes.Structure):
    __slots__ = ()
    _pack_ = 4
    _fields_ = [
        ("generic",   LMUGeneric),
        ("paths",     LMUPathData),
        ("scoring",   LMUScoringData),
        ("telemetry", LMUTelemetryData),
    ]


class SimInfo:
    """Opens LMU shared memory and exposes LMUObjectOut as LMUData."""

    def __init__(self) -> None:
        self._mmap = mmap.mmap(
            fileno=0,
            length=ctypes.sizeof(LMUObjectOut),
            tagname=LMUConstants.LMU_SHARED_MEMORY_FILE,
        )
        self.LMUData = LMUObjectOut.from_buffer(self._mmap)

    def close(self) -> None:
        self.LMUData = None
        try:
            self._mmap.close()
        except BufferError:
            pass

    def __del__(self) -> None:
        self.close()
