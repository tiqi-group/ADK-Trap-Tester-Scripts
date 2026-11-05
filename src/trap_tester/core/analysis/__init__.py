"""GUI-agnostic analysis engine (no Qt).

Mirrors the ``core/measurements`` design: each ``analyse_*`` function takes a
loaded results :class:`pandas.DataFrame` plus an analysis-settings dataclass and
returns a :class:`AnalysisResult` — a list of per-pin :class:`Finding` objects,
a plain-text report and the metadata a viewer needs to plot the outcome. The
GUI Analysis panel and any CLI/test harness share this single source of truth.

Every analysis judges each measured/fitted quantity against a min/max acceptance
band, or — where a golden reference supplies an expected value for that pin —
against ``expected ± tolerance``. The quantities themselves are declared once in
:mod:`~trap_tester.core.analysis.quantities`; the band logic lives in
:mod:`~trap_tester.core.analysis.acceptance`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

# ---- status vocabulary -----------------------------------------------------
# status key -> (human label, plot colour). Shared by the report and the viewer
# so a pin is described and coloured consistently everywhere.
STATUS_INFO: dict[str, tuple[str, str]] = {
    "ok": ("OK", "#2a9d3f"),
    "below_limit": ("Below limit", "#e08e0b"),
    "above_limit": ("Above limit", "#d35400"),
    "not_detected": ("Not detected", "#6b6b6b"),
    "shorted": ("Shorted", "#c0392b"),
    "high_impedance": ("High impedance", "#8e44ad"),
    # loopback mode (see loopback_analysis): how many filters a pin sees
    "loop_open": ("Loop open", "#f4d03f"),  # never blue: GND pads are blue
    "extra_short": ("Extra short", "#c2185b"),
    "group_mismatch": ("Group mismatch", "#7d6608"),
    "expected_short": ("Shorted (expected)", "#7fb3d5"),
}

# Verdicts that count as a pass. A short is a fault — unless the setup puts it
# there on purpose (a loopback board grounding a pad).
PASS_STATUSES = frozenset({"ok", "expected_short"})


def is_fault(status: str) -> bool:
    return status not in PASS_STATUSES


@dataclass
class Finding:
    """The verdict for a single measured point (one DSUB pin on one connector).

    ``value`` is the primary quantity — the one plotted on the y-axis. The
    ``values`` / ``limits`` / ``expected`` maps carry *every* quantity the
    analysis judged (keyed by ``Quantity.key``), so a measurement that fits more
    than one value keeps all of them for the report, the tooltip and the plot.
    """

    connector: int
    dsub_pin: int
    fpc_conductor: int | None
    value: float  # the metric plotted on the y-axis (C_nF / R_Ohm / V_avg)
    status: str  # a key of STATUS_INFO
    message: str  # one human-readable line describing this pin
    values: dict[str, float] = field(default_factory=dict)
    limits: dict[str, tuple[float, float]] = field(default_factory=dict)
    expected: dict[str, float] = field(default_factory=dict)  # reference bands only
    failed: list[str] = field(default_factory=list)  # quantity keys that failed


@dataclass
class AnalysisResult:
    """Everything the Analysis panel needs to render a report and a plot."""

    measurement: str
    title: str
    findings: list[Finding]
    value_label: str  # y-axis label for the visualiser
    params: dict[str, Any] = field(default_factory=dict)
    # Which analysis mode produced this (an AnalysisMode.key); stamped by analyse().
    mode: str = ""
    # Problems with the analysis inputs rather than the board (e.g. a loopback
    # pad the mapping does not name). Shown above the findings in the report.
    warnings: list[str] = field(default_factory=list)
    # Points the setup joins, as ((connector, dsub_pin), (connector, dsub_pin)):
    # the connector map outlines each one (consecutive pads of a loopback group).
    links: list[tuple[tuple[int, int], tuple[int, int]]] = field(default_factory=list)
    # The band every pin shares, shaded across the plot. ``None`` when a golden
    # reference gives each pin its own — those are drawn per point from
    # ``Finding.limits`` instead.
    band: tuple[float, float] | None = None
    log_y: bool = False  # plot the value axis on a log scale

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.status] = counts.get(f.status, 0) + 1
        return counts

    @property
    def n_faults(self) -> int:
        return sum(n for s, n in self.summary.items() if is_fault(s))

    @property
    def failures_by_quantity(self) -> dict[str, int]:
        """How many pins each quantity failed on, keyed by ``Quantity.key``."""
        counts: dict[str, int] = {}
        for f in self.findings:
            for key in f.failed:
                counts[key] = counts.get(key, 0) + 1
        return counts


def render_report(result: AnalysisResult, source_name: str = "") -> str:
    """Render a plain-text report (header + parameters + faults + summary)."""
    lines: list[str] = []
    lines.append(f"{result.title}")
    if source_name:
        lines.append(f"Source: {source_name}")
    lines.append("=" * 60)
    if result.params:
        lines.append("Parameters:")
        for key, value in result.params.items():
            lines.append(f"  {key} = {value}")
        lines.append("")

    lines.extend(_warning_lines(result))
    faults = [f for f in result.findings if is_fault(f.status)]
    if faults:
        lines.append(f"Findings ({len(faults)}):")
        for f in faults:
            lines.append(f"  {f.message}")
    else:
        lines.append("No faults detected — all measured pins nominal.")
    lines.append("")

    lines.append(f"Summary ({len(result.findings)} pins):")
    for status, (label, _) in STATUS_INFO.items():
        n = result.summary.get(status, 0)
        if n:
            lines.append(f"  {label}: {n}")
    lines.append(f"  Faults total: {result.n_faults}")
    out_of_band = _out_of_band_line(result)
    if out_of_band:
        lines.append(out_of_band)
    return "\n".join(lines)


def _warning_lines(result: AnalysisResult) -> list[str]:
    """The report's warnings block (problems with the inputs), or nothing."""
    if not result.warnings:
        return []
    return [
        f"Warnings ({len(result.warnings)}):",
        *(f"  {warning}" for warning in result.warnings),
        "",
    ]


def _out_of_band_line(result: AnalysisResult) -> str:
    """Which measured value went out of band, e.g. ``"  Out of band: C 2, R 1"``.

    The pin status alone cannot say, for a measurement that judges more than one
    quantity (the filter fits both a C and an R).
    """
    counts = result.failures_by_quantity
    parts = [
        f"{q.symbol} {counts[q.key]}"
        for q in quantities_for(result.measurement)
        if q.key in counts
    ]
    return f"  Out of band: {', '.join(parts)}" if parts else ""


# ---- registry --------------------------------------------------------------
# Imports are deferred to avoid a heavy import at package load; they are cheap
# pure-python modules but this keeps the dependency direction obvious.
from trap_tester.core.analysis.acceptance import (  # noqa: E402
    AcceptanceSettings,
    QuantityVerdict,
    Reference,
    reference_key,
)
from trap_tester.core.analysis.filter_analysis import (  # noqa: E402
    FilterAnalysisSettings,
    analyse_filter,
)
from trap_tester.core.analysis.fpc_permutation import prepare_frame  # noqa: E402
from trap_tester.core.analysis.loopback import LoopbackBoard  # noqa: E402
from trap_tester.core.analysis.loopback_analysis import (  # noqa: E402
    LoopbackAnalysisSettings,
    analyse_loopback,
)
from trap_tester.core.analysis.quantities import (  # noqa: E402
    Quantity,
    primary_quantity,
    quantities_for,
)
from trap_tester.core.analysis.resistance_analysis import (  # noqa: E402
    ResistanceAnalysisSettings,
    analyse_resistance,
)
from trap_tester.core.analysis.voltage_analysis import (  # noqa: E402
    VoltageAnalysisSettings,
    analyse_voltage,
)

DEFAULT_MODE = "standard"


@dataclass(frozen=True)
class AnalysisMode:
    """One way of analysing a measurement's results.

    A measurement can be read more than one way — a ``measure_filter`` run is a
    plain filter characterisation, or, with a loopback PCB fitted, a check that
    pads come back in their groups. The mode is chosen in the Analysis panel and
    recorded in a preset; it is never inferred from the result file, so one
    result can be analysed either way.
    """

    key: str  # recorded in presets as "analysis"; unique per measurement
    label: str  # shown in the panel's Mode selector
    settings: type  # the analysis-settings dataclass
    run: Callable[..., AnalysisResult]  # (df, settings[, mapping]) -> result
    # The mode needs the selected cross-interface mapping as an input, so the
    # panel's mapping choice changes the verdict, not just the picture.
    needs_mapping: bool = False


# measurement key (== script stem) -> its analysis modes, the default first
ANALYSES: dict[str, list[AnalysisMode]] = {
    "measure_filter": [
        AnalysisMode(DEFAULT_MODE, "Standard", FilterAnalysisSettings, analyse_filter),
        AnalysisMode(
            "loopback", "Loopback (grouped pads)", LoopbackAnalysisSettings,
            analyse_loopback, needs_mapping=True,
        ),
    ],
    "measure_resistance": [
        AnalysisMode(
            DEFAULT_MODE, "Standard", ResistanceAnalysisSettings, analyse_resistance
        ),
    ],
    "measure_voltage": [
        AnalysisMode(
            DEFAULT_MODE, "Standard", VoltageAnalysisSettings, analyse_voltage
        ),
    ],
}


def has_analysis(measurement: str | None) -> bool:
    return (measurement or "") in ANALYSES


def analysis_modes(measurement: str | None) -> list[AnalysisMode]:
    """Every mode registered for a measurement, the default first (or none)."""
    return ANALYSES.get(measurement or "", [])


def analysis_mode(
    measurement: str | None, mode: str | None = None
) -> AnalysisMode | None:
    """One mode of a measurement — the default when ``mode`` is ``None``.

    ``None`` is returned for an unknown measurement *or* an unknown mode key, so a
    preset naming a mode this build does not have is rejected, not re-read as
    the default.
    """
    modes = analysis_modes(measurement)
    if not modes:
        return None
    if mode is None:
        return modes[0]
    return next((m for m in modes if m.key == mode), None)


def analysis_settings_for(
    measurement: str | None, mode: str | None = None
) -> type | None:
    entry = analysis_mode(measurement, mode)
    return entry.settings if entry else None


def mode_of_settings(measurement: str | None, settings: Any) -> str | None:
    """The key of the mode whose settings class ``settings`` is an instance of."""
    for m in analysis_modes(measurement):
        if type(settings) is m.settings:
            return m.key
    return None


def analyse(
    measurement: str | None, df: pd.DataFrame, settings: Any,
    mode: str | None = None, mapping: Any = None,
) -> AnalysisResult:
    """Run one analysis mode (the default unless ``mode`` is given) on ``df``.

    ``mapping`` is the selected cross-interface mapping; only modes that declare
    ``needs_mapping`` receive it. The permutations the settings enable (an
    inverted FPC) are applied to ``df`` first, so every mode — and the mapping —
    sees the device's numbering. Raises ``KeyError`` if no such analysis exists.
    """
    entry = analysis_mode(measurement, mode)
    if entry is None:
        raise KeyError(
            f"No analysis {mode or DEFAULT_MODE!r} for measurement {measurement!r}"
        )
    df = prepare_frame(df, settings)
    if entry.needs_mapping:
        result = entry.run(df, settings, mapping)
    else:
        result = entry.run(df, settings)
    result.mode = entry.key
    return result


__all__ = [
    "PASS_STATUSES",
    "STATUS_INFO",
    "AcceptanceSettings",
    "Finding",
    "AnalysisResult",
    "Quantity",
    "QuantityVerdict",
    "Reference",
    "primary_quantity",
    "quantities_for",
    "reference_key",
    "render_report",
    "ANALYSES",
    "DEFAULT_MODE",
    "AnalysisMode",
    "has_analysis",
    "is_fault",
    "analysis_mode",
    "analysis_modes",
    "analysis_settings_for",
    "mode_of_settings",
    "analyse",
    "prepare_frame",
    "FilterAnalysisSettings",
    "LoopbackAnalysisSettings",
    "LoopbackBoard",
    "ResistanceAnalysisSettings",
    "VoltageAnalysisSettings",
    "analyse_filter",
    "analyse_loopback",
    "analyse_resistance",
    "analyse_voltage",
]
