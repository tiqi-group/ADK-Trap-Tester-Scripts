"""Matplotlib visualiser for an :class:`AnalysisResult`.

Draws the analysed metric (capacitance / resistance / voltage) per DSUB pin,
colouring each point by its verdict and showing the band it was judged against.
Pins with no numeric value (not detected / shorted) are shown as ``x`` markers
along the bottom so they are still visible.

The band is drawn one of two ways, matching how the verdict was reached: one
shaded region across the plot when every pin shares the same min/max limits, or
a green column per pin (plus a dash at the expected value) when a golden
reference gives each pin its own band. Pins the reference does not cover keep
their fallback limits, so a partially covered result shows both.

A result spanning several connectors is shown one connector at a time; the
connector selector lives in the Analysis panel (shared with the connector map),
so pins from different connectors never collide on the x-axis.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from PySide6.QtWidgets import QVBoxLayout, QWidget

from trap_tester.core.analysis import (
    STATUS_INFO,
    AnalysisResult,
    Finding,
    primary_quantity,
)
from trap_tester.gui import theme

_BAND_COLOR = "#2a9d3f"
_LOG_FLOOR = 1e-12  # a log axis cannot show a band edge at (or below) zero


def _title_kw() -> dict:
    """Plot-title style, themed (colour tracks the active light/dark palette)."""
    return dict(fontsize=10, fontweight="bold", color=theme.plot_title_color())


class AnalysisView(QWidget):
    """A single plot summarising an analysis result."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.fig = Figure(figsize=(5, 3.2), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setProperty("role", "viewer")
        self.ax = self.fig.add_subplot(111)
        layout.addWidget(self.canvas)

        self._result: AnalysisResult | None = None
        self._connector: int | None = None
        self._clear_msg = ""
        self.clear()

    def apply_theme(self) -> None:
        """Recolour + re-render with the active theme (live theme switch)."""
        self.fig.set_facecolor(theme.fig_bg())
        if self._result is not None:
            self.show_result(self._result, self._connector)
        else:
            self.clear(self._clear_msg)

    def save_view(self, path: str) -> None:
        """Save the plot exactly as shown (current axes/limits) to an image file.

        Grabs the canvas as a pixmap so the export matches the on-screen view;
        the format is inferred from the file suffix.
        """
        self.canvas.draw()  # flush any pending draw_idle before grabbing
        if not self.canvas.grab().save(path):
            raise OSError(f"could not write image to {path}")

    def clear(self, message: str = "Run an analysis to see the result.") -> None:
        self._result = None
        self._clear_msg = message
        self.ax.clear()
        theme.style_axes(self.fig, self.ax)
        self.ax.set_title(message, **_title_kw())
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw_idle()

    def show_result(self, result: AnalysisResult, connector: int | None = None) -> None:
        """Plot ``result``, restricted to ``connector`` (all connectors if None)."""
        self._result = result
        self._connector = connector
        findings = [
            f for f in result.findings
            if connector is None or int(f.connector) == connector
        ]
        self._plot(findings)

    def _plot(self, findings: list[Finding]) -> None:
        result = self._result
        assert result is not None
        ax = self.ax
        ax.clear()
        theme.style_axes(self.fig, ax)
        ax.set_yscale("log" if result.log_y else "linear")

        finite = [f for f in findings if np.isfinite(f.value)]
        non_finite = [f for f in findings if not np.isfinite(f.value)]

        # y position for value-less points: just below the smallest plotted value
        if finite:
            vmin = min(f.value for f in finite)
            vmax = max(f.value for f in finite)
        else:
            vmin, vmax = 0.0, 1.0
        if result.log_y:
            placeholder_y = max(vmin, 1e-12) / 3.0
        else:
            pad = 0.1 * (vmax - vmin or 1.0)
            placeholder_y = vmin - pad

        # the acceptance band, drawn behind the points: one region when every pin
        # shares it, otherwise a column per pin (a golden reference is per pin)
        banded = expected = False
        if result.band is not None:
            lo, hi = result.band
            ax.axhspan(lo, hi, color=_BAND_COLOR, alpha=0.08, label="_band")
            banded = True
        else:
            banded, expected = self._draw_per_pin_bands(findings, result)

        for group, marker, y_of in (
            (finite, "o", lambda f: f.value),
            (non_finite, "x", lambda f: placeholder_y),
        ):
            for status in STATUS_INFO:
                pts = [f for f in group if f.status == status]
                if not pts:
                    continue
                _, color = STATUS_INFO[status]
                ax.scatter(
                    [f.dsub_pin for f in pts],
                    [y_of(f) for f in pts],
                    c=color, marker=marker, s=28, zorder=3,
                )

        n_faults = sum(1 for f in findings if f.status != "ok")
        ax.set_title(
            f"{result.title} — {n_faults} fault(s) / {len(findings)} pins",
            **_title_kw(),
        )
        ax.set_xlabel("DSUB pin")
        ax.set_ylabel(result.value_label)
        ax.grid(True, alpha=0.3)
        handles = self._legend(findings, banded, expected)
        if handles:
            ax.legend(handles=handles, fontsize=7, loc="center left",
                      bbox_to_anchor=(1.02, 0.5))
        self.canvas.draw_idle()

    def _draw_per_pin_bands(
        self, findings: list[Finding], result: AnalysisResult
    ) -> tuple[bool, bool]:
        """Draw each pin's own band + expected value. Returns what was drawn.

        Only the plotted (primary) quantity is drawn; the others gate the verdict
        and are spelled out in the report and the connector map's tooltip.
        """
        quantity = primary_quantity(result.measurement)
        if quantity is None:
            return False, False
        key = quantity.key

        xs, los, his = self._band_columns(findings, key, log=result.log_y)
        if xs:
            self.ax.vlines(
                xs, los, his, color=_BAND_COLOR, alpha=0.22, lw=6, zorder=1
            )

        marks = [(f.dsub_pin, f.expected[key]) for f in findings if key in f.expected]
        if marks:
            self.ax.scatter(
                [x for x, _ in marks], [y for _, y in marks],
                marker="_", c=_BAND_COLOR, s=45, linewidths=1.2, zorder=2,
            )
        return bool(xs), bool(marks)

    @staticmethod
    def _band_columns(
        findings: list[Finding], key: str, log: bool
    ) -> tuple[list[int], list[float], list[float]]:
        """``(pins, lows, highs)`` for the pins that carry a finite band."""
        xs: list[int] = []
        los: list[float] = []
        his: list[float] = []
        for f in findings:
            limits = f.limits.get(key)
            if limits is None or not all(np.isfinite(v) for v in limits):
                continue
            lo, hi = limits
            xs.append(f.dsub_pin)
            los.append(max(lo, _LOG_FLOOR) if log else lo)
            his.append(max(hi, _LOG_FLOOR) if log else hi)
        return xs, los, his

    @staticmethod
    def _legend(
        findings: list[Finding], banded: bool, expected: bool
    ) -> list[Line2D]:
        present = {f.status for f in findings}
        handles: list[Line2D] = []
        for status, (label, color) in STATUS_INFO.items():
            if status in present:
                handles.append(
                    Line2D([], [], marker="o", ls="", color=color, label=label,
                           markersize=6)
                )
        if banded:
            handles.append(
                Line2D([], [], marker="|", ls="", color=_BAND_COLOR, alpha=0.5,
                       label="Acceptance band", markersize=10, markeredgewidth=6)
            )
        if expected:
            handles.append(
                Line2D([], [], marker="_", ls="", color=_BAND_COLOR,
                       label="Expected (reference)", markersize=8)
            )
        return handles
