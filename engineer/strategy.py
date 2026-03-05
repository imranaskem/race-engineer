"""
StrategyEngine — deterministic race strategy calculations.

These run client-side before calling Claude, providing hard numbers
that the AI reasons around (pit windows, fuel math, tyre stint lengths).
"""
from dataclasses import dataclass


@dataclass
class StrategySnapshot:
    """Computed strategy data derived from the telemetry aggregator context."""

    # Pit stop timing
    forced_pit_in_laps: float       # Laps until fuel forces a stop
    optimal_pit_window_open: bool   # Is the strategic pit window open?
    recommended_pit_lap: int        # Absolute lap number to target

    # Tyre status
    tyre_stint_age_laps: int        # Laps on current set
    estimated_tyre_life_laps: int   # Total expected life of current compound

    # Fuel to add at next stop
    fuel_to_add_l: float            # Enough for next_stint_laps laps (litres)
    next_stint_laps: int

    # Time-loss estimate
    pit_time_loss_s: float          # Approx lap time lost to a pit stop

    def as_text(self) -> str:
        """Format strategy snapshot as readable text for the AI context."""
        window = "OPEN" if self.optimal_pit_window_open else "CLOSED"
        return (
            f"Strategy: pit window {window}, "
            f"forced stop in {self.forced_pit_in_laps:.1f} laps (lap {self.recommended_pit_lap}), "
            f"tyres {self.tyre_stint_age_laps} laps old "
            f"(est. life {self.estimated_tyre_life_laps} laps), "
            f"add {self.fuel_to_add_l:.1f} L for {self.next_stint_laps}-lap stint, "
            f"pit time loss ~{self.pit_time_loss_s:.0f}s."
        )


def compute_strategy(context: dict) -> StrategySnapshot:
    """
    Derive strategy numbers from the aggregator context dict.
    All math is deterministic — no AI involved.
    """
    fuel_laps = float(context.get("laps_of_fuel_remaining", 0))
    lap_number = int(context.get("lap_number", 1))
    avg_fuel_l = float(context.get("avg_fuel_per_lap_l", 3.3))
    current_fuel_l = float(context.get("fuel_l", 0.0))
    tank_capacity_l = float(context.get("fuel_capacity_l", 110.0))
    tyre_wear = context.get("tyre_wear_pct", {})
    session_h = float(context.get("session_time_remaining_h", 24.0))
    avg_lap_s_str = context.get("rolling_avg_lap", "0:00.000")
    fcy = bool(context.get("fcy_active", False))

    # Parse lap time string back to seconds
    avg_lap_s = _parse_lap_time(avg_lap_s_str)
    if avg_lap_s == 0:
        avg_lap_s = 105.0  # fallback

    # Laps remaining in session
    session_laps_remaining = (session_h * 3600) / avg_lap_s if avg_lap_s > 0 else 999

    # Tyre stint estimate: 55-lap life for a GT3 medium compound
    # Adjust downward if current wear rate is high
    max_wear = max(tyre_wear.values(), default=0.0)
    if max_wear > 0:
        # Extrapolate: if N% worn in M laps, life = 100/rate laps
        # We don't have stint age directly, so use max_wear as a proxy
        # Assume tyre life degrades at ~1.8% per lap for a medium
        estimated_life = int(100 / 1.8)
        tyre_laps_used = int(max_wear / 1.8)
    else:
        estimated_life = 55
        tyre_laps_used = 0

    tyre_laps_remaining = max(0, estimated_life - tyre_laps_used)

    # Pit window: open when BOTH fuel and tyre need ≤ 15 laps margin
    PIT_WINDOW_BUFFER = 15
    forced_pit_in_laps = fuel_laps

    # Strategic window: pit when within buffer of either fuel or tyre limit
    within_fuel_window = fuel_laps <= PIT_WINDOW_BUFFER
    within_tyre_window = tyre_laps_remaining <= PIT_WINDOW_BUFFER
    fcy_bonus = fcy  # FCY always a good time to pit

    pit_window_open = within_fuel_window or within_tyre_window or fcy_bonus

    # Recommended pit lap: whichever limit hits first
    laps_to_deadline = min(fuel_laps, tyre_laps_remaining)
    recommended_pit_lap = lap_number + max(0, int(laps_to_deadline) - 2)

    # Next stint length: how long can we go on a full tank, minus safety margin
    safety_reserve_laps = 3
    next_stint_laps = int((tank_capacity_l / avg_fuel_l) - safety_reserve_laps)
    next_stint_laps = min(next_stint_laps, int(session_laps_remaining))
    # Fuel to ADD at the stop = target level minus what's already in the tank
    target_fuel_l = min(tank_capacity_l, next_stint_laps * avg_fuel_l * 1.05)  # 5% buffer
    fuel_to_add_l = max(0.0, target_fuel_l - current_fuel_l)

    # Pit time loss estimate (in-lap, stationary, out-lap premium)
    # A typical LMU pit stop: ~25s stationary + 30s in-lap loss + 15s out-lap = ~70s
    pit_time_loss_s = 70.0

    return StrategySnapshot(
        forced_pit_in_laps=round(forced_pit_in_laps, 1),
        optimal_pit_window_open=pit_window_open,
        recommended_pit_lap=recommended_pit_lap,
        tyre_stint_age_laps=tyre_laps_used,
        estimated_tyre_life_laps=estimated_life,
        fuel_to_add_l=round(fuel_to_add_l, 1),
        next_stint_laps=next_stint_laps,
        pit_time_loss_s=pit_time_loss_s,
    )


def _parse_lap_time(time_str: str) -> float:
    """Parse 'M:SS.mmm' → float seconds. Returns 0.0 on failure."""
    try:
        if ":" in time_str:
            m, rest = time_str.split(":", 1)
            return int(m) * 60 + float(rest)
        return float(time_str)
    except (ValueError, AttributeError):
        return 0.0
