"""The measured / fitted quantities each analysis judges.

One :class:`Quantity` per value a measurement produces and its analysis gates:
``measure_filter`` fits a capacitance *and* a resistance, the other two record a
single number each. Everything downstream is derived from this registry — the
acceptance bands, the settings-form fields and their units, the report wording,
the plotted axis and (later) the golden-reference capture — so adding a quantity
to an existing analysis, or a whole new measurement, is a declaration here
rather than new code in four places.

Each quantity names the settings fields that carry its limits, so the settings
dataclasses keep readable, unit-bearing field names (``c_min_nf``, ``r_max_ohm``)
instead of a generic ``limits["c"]`` dictionary the GUI form could not render.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Quantity:
    """One measured/fitted value, and how it is judged and described."""

    key: str  # short id used in the reference table JSON ("c", "r", "v")
    column: str  # the column it lives in, in the results frame
    symbol: str  # short name used in report lines ("C", "R", "V")
    label: str  # settings-form section header ("Capacitance")
    unit: str
    min_field: str  # settings field holding the lower acceptance limit
    max_field: str  # ... and the upper one
    abs_tol_field: str  # ... and its absolute tolerance (reference mode only)
    primary: bool = False  # plotted on the y-axis; becomes Finding.value
    log: bool = False  # the value axis is logarithmic
    # Physically non-negative, so the measurements' "-1" marks a skipped point
    # rather than a reading. False for a signed quantity such as a voltage.
    non_negative: bool = True
    fail_low: str = "below_limit"  # STATUS_INFO key when below the band
    fail_high: str = "above_limit"  # ... and when above it
    low_hint: str = ""  # diagnostic appended to a below-the-band message
    high_hint: str = ""  # ... and to an above-the-band one

    def format(self, value: float) -> str:
        """A value with its unit, as report lines and tooltips show it."""
        return f"{value:.4g} {self.unit}".strip()

    def band_text(self, lo: float, hi: float) -> str:
        return f"{lo:.4g}…{hi:.4g} {self.unit}".strip()


C_FILTER = Quantity(
    key="c",
    column="C_filter_nF",
    symbol="C",
    label="Capacitance",
    unit="nF",
    min_field="c_min_nf",
    max_field="c_max_nf",
    abs_tol_field="c_abs_tol_nf",
    primary=True,
    # Both filter caps charged -> several channels driven at once (see the AFE
    # README, "Shorts between Electrodes").
    high_hint="possible inter-electrode/board short",
)

R_FILTER = Quantity(
    key="r",
    column="R_filter_Ohm",
    symbol="R",
    label="Filter resistance",
    unit="Ohm",
    min_field="r_min_ohm",
    max_field="r_max_ohm",
    abs_tol_field="r_abs_tol_ohm",
)

R_EST = Quantity(
    key="r",
    column="R_est",
    symbol="R",
    label="Resistance to ground",
    unit="Ohm",
    min_field="r_min_ohm",
    max_field="r_max_ohm",
    abs_tol_field="r_abs_tol_ohm",
    primary=True,
    log=True,
    # For this measurement the limits *are* the short / high-impedance
    # thresholds, so the verdicts keep their specific names.
    fail_low="shorted",
    fail_high="high_impedance",
)

V_AVG = Quantity(
    key="v",
    column="V_avg",
    symbol="V",
    label="Voltage",
    unit="V",
    min_field="v_min",
    max_field="v_max",
    abs_tol_field="v_abs_tol_v",
    primary=True,
    non_negative=False,  # a measured voltage may legitimately be negative
)


# measurement key (== script stem) -> the quantities its analysis judges
QUANTITIES: dict[str, list[Quantity]] = {
    "measure_filter": [C_FILTER, R_FILTER],
    "measure_resistance": [R_EST],
    "measure_voltage": [V_AVG],
}


def quantities_for(measurement: str | None) -> list[Quantity]:
    """The quantities judged for a measurement (empty when unknown)."""
    return QUANTITIES.get(measurement or "", [])


def primary_quantity(measurement: str | None) -> Quantity | None:
    """The quantity plotted on the value axis, or ``None`` when unknown."""
    for q in quantities_for(measurement):
        if q.primary:
            return q
    return None


__all__ = [
    "C_FILTER",
    "QUANTITIES",
    "R_EST",
    "R_FILTER",
    "V_AVG",
    "Quantity",
    "primary_quantity",
    "quantities_for",
]
