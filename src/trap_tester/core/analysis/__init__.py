"""GUI-agnostic analysis engine (no Qt).

Mirrors the ``core/measurements`` design: each ``analyse_*`` function takes a
loaded results :class:`pandas.DataFrame` plus an analysis-settings dataclass and
returns a :class:`AnalysisResult` — a list of per-pin :class:`Finding` objects,
a plain-text report and the metadata a viewer needs to plot the outcome. The
GUI Analysis panel and any CLI/test harness share this single source of truth.

The filter analysis is refactored from ``analysis/filter_tester_analysis.py``
(same C/tolerance decision tree); resistance and voltage analyses summarise the
flags/values their measurements already produce.
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
    "off_nominal": ("Off-nominal", "#e08e0b"),
    "over_nominal": ("Above nominal (possible short)", "#d35400"),
    "not_detected": ("Not detected", "#6b6b6b"),
    "shorted": ("Shorted", "#c0392b"),
    "high_impedance": ("High impedance", "#8e44ad"),
}


@dataclass
class Finding:
    """The verdict for a single measured point (one DSUB pin on one connector)."""

    connector: int
    dsub_pin: int
    fpc_conductor: int | None
    value: float  # the metric plotted on the y-axis (C_nF / R_Ohm / V_avg)
    status: str  # a key of STATUS_INFO
    message: str  # one human-readable line describing this pin


@dataclass
class AnalysisResult:
    """Everything the Analysis panel needs to render a report and a plot."""

    measurement: str
    title: str
    findings: list[Finding]
    value_label: str  # y-axis label for the visualiser
    params: dict[str, Any] = field(default_factory=dict)
    band: tuple[float, float] | None = None  # shaded acceptable y-region
    nominal: float | None = None  # dashed nominal line
    log_y: bool = False  # plot the value axis on a log scale

    @property
    def summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for f in self.findings:
            counts[f.status] = counts.get(f.status, 0) + 1
        return counts

    @property
    def n_faults(self) -> int:
        return sum(n for s, n in self.summary.items() if s != "ok")


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

    faults = [f for f in result.findings if f.status != "ok"]
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
    return "\n".join(lines)


# ---- registry --------------------------------------------------------------
# Imports are deferred to avoid a heavy import at package load; they are cheap
# pure-python modules but this keeps the dependency direction obvious.
from trap_tester.core.analysis.filter_analysis import (  # noqa: E402
    FilterAnalysisSettings,
    analyse_filter,
)
from trap_tester.core.analysis.resistance_analysis import (  # noqa: E402
    ResistanceAnalysisSettings,
    analyse_resistance,
)
from trap_tester.core.analysis.voltage_analysis import (  # noqa: E402
    VoltageAnalysisSettings,
    analyse_voltage,
)

# measurement key (== script stem) -> (analysis-settings dataclass, analyse fn)
ANALYSES: dict[str, tuple[type, Callable[[pd.DataFrame, Any], AnalysisResult]]] = {
    "measure_filter": (FilterAnalysisSettings, analyse_filter),
    "measure_resistance": (ResistanceAnalysisSettings, analyse_resistance),
    "measure_voltage": (VoltageAnalysisSettings, analyse_voltage),
}


def has_analysis(measurement: str | None) -> bool:
    return (measurement or "") in ANALYSES


def analysis_settings_for(measurement: str | None) -> type | None:
    entry = ANALYSES.get(measurement or "")
    return entry[0] if entry else None


def analyse(measurement: str | None, df: pd.DataFrame, settings: Any) -> AnalysisResult:
    """Run the analysis registered for ``measurement`` on ``df``.

    Raises ``KeyError`` if no analysis is registered for the measurement.
    """
    entry = ANALYSES.get(measurement or "")
    if entry is None:
        raise KeyError(f"No analysis available for measurement {measurement!r}")
    return entry[1](df, settings)


__all__ = [
    "STATUS_INFO",
    "Finding",
    "AnalysisResult",
    "render_report",
    "ANALYSES",
    "has_analysis",
    "analysis_settings_for",
    "analyse",
    "FilterAnalysisSettings",
    "ResistanceAnalysisSettings",
    "VoltageAnalysisSettings",
    "analyse_filter",
    "analyse_resistance",
    "analyse_voltage",
]
