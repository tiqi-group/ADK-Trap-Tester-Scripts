"""Refactored, callback-driven measurement routines.

Each ``run_*_measurement(ctx)`` takes a
:class:`~trap_tester.core.reporter.MeasurementContext` (already-open device +
settings + reporter + gate) and returns a :class:`pandas.DataFrame` of results.
"""

from trap_tester.core.measurements.filter import (
    DIGITAL_OUT as _FILTER_DO,
    run_filter_measurement,
)
from trap_tester.core.measurements.resistance import (
    DIGITAL_OUT as _RESISTANCE_DO,
    run_resistance_measurement,
)
from trap_tester.core.measurements.voltage import (
    DIGITAL_OUT as _VOLTAGE_DO,
    run_voltage_measurement,
)

# measurement key (== script stem) -> read-only digital-output configuration
DIGITAL_OUT_BY_KEY: dict[str, dict[str, str]] = {
    "measure_filter": _FILTER_DO,
    "measure_voltage": _VOLTAGE_DO,
    "measure_resistance": _RESISTANCE_DO,
}


def digital_out_for(measurement: str | None) -> dict[str, str]:
    """The measurement-defined digital-output configuration (empty if unknown)."""
    return DIGITAL_OUT_BY_KEY.get(measurement or "", {})


__all__ = [
    "DIGITAL_OUT_BY_KEY",
    "digital_out_for",
    "run_filter_measurement",
    "run_resistance_measurement",
    "run_voltage_measurement",
]
