"""
Telemetry package — selects the appropriate provider for the current platform.

  Mac (dev):     MockTelemetryProvider
  Windows (prod): RF2SharedMemoryProvider
"""
import sys

if sys.platform == "win32":
    from .rf2_shared_memory import RF2SharedMemoryProvider as TelemetryProvider  # type: ignore[import]
else:
    from .mock import MockTelemetryProvider as TelemetryProvider  # noqa: F401

from .aggregator import TelemetryAggregator
from .provider import TelemetryState

__all__ = ["TelemetryProvider", "TelemetryAggregator", "TelemetryState"]
