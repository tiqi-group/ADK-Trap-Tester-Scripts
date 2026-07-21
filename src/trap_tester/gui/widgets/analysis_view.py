"""Matplotlib visualiser for an :class:`AnalysisResult`.

Draws the analysed metric (capacitance / resistance / voltage) per DSUB pin,
colouring each point by its verdict and shading the acceptable band. Pins with
no numeric value (not detected / shorted) are shown as ``x`` markers along the
bottom so they are still visible.

Like the connector map, a result spanning several connectors is shown one
connector at a time via a selector (hidden for single-connector results) so
pins from different connectors never collide on the x-axis.
"""

from __future__ import annotations

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.analysis import STATUS_INFO, AnalysisResult, Finding

_TITLE_KW = dict(fontsize=10, fontweight="bold", color="#b83a20")


class AnalysisView(QWidget):
    """A single plot summarising an analysis result."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Connector selector — shown only when a result spans >1 connector.
        self._conn_row = QWidget()
        conn_layout = QHBoxLayout(self._conn_row)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.addWidget(QLabel("Connector:"))
        self._conn_selector = QComboBox()
        self._conn_selector.setProperty("role", "interactive")
        self._conn_selector.currentIndexChanged.connect(self._on_connector_changed)
        conn_layout.addWidget(self._conn_selector)
        conn_layout.addStretch(1)
        self._conn_row.setVisible(False)
        layout.addWidget(self._conn_row)

        self.fig = Figure(figsize=(5, 3.2), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setProperty("role", "viewer")
        self.ax = self.fig.add_subplot(111)
        layout.addWidget(self.canvas)

        self._result: AnalysisResult | None = None
        self.clear()

    def clear(self, message: str = "Run an analysis to see the result.") -> None:
        self._result = None
        self._conn_row.setVisible(False)
        self.ax.clear()
        self.ax.set_title(message, **_TITLE_KW)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self.canvas.draw_idle()

    def show_result(self, result: AnalysisResult) -> None:
        """Store ``result`` and plot it; offer a selector if multi-connector."""
        self._result = result
        connectors = sorted({int(f.connector) for f in result.findings})

        self._conn_selector.blockSignals(True)
        self._conn_selector.clear()
        for c in connectors:
            self._conn_selector.addItem(f"{c}", c)
        self._conn_selector.setCurrentIndex(0)
        self._conn_selector.blockSignals(False)
        self._conn_row.setVisible(len(connectors) > 1)

        self._render_connector(connectors[0] if connectors else None)

    def _on_connector_changed(self, index: int) -> None:
        if index < 0 or self._result is None:
            return
        self._render_connector(int(self._conn_selector.itemData(index)))

    def _render_connector(self, connector: int | None) -> None:
        if self._result is None:
            return
        findings = [
            f for f in self._result.findings
            if connector is None or int(f.connector) == connector
        ]
        self._plot(findings)

    def _plot(self, findings: list[Finding]) -> None:
        result = self._result
        assert result is not None
        ax = self.ax
        ax.clear()
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

        # acceptable band + nominal line (drawn behind the points)
        if result.band is not None:
            lo, hi = result.band
            ax.axhspan(lo, hi, color="#2a9d3f", alpha=0.08, label="_band")
        if result.nominal is not None:
            ax.axhline(result.nominal, color="#2a9d3f", ls="--", lw=0.8)

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
            **_TITLE_KW,
        )
        ax.set_xlabel("DSUB pin")
        ax.set_ylabel(result.value_label)
        ax.grid(True, alpha=0.3)
        handles = self._legend(findings)
        if handles:
            ax.legend(handles=handles, fontsize=7, loc="center left",
                      bbox_to_anchor=(1.02, 0.5))
        self.canvas.draw_idle()

    @staticmethod
    def _legend(findings: list[Finding]) -> list[Line2D]:
        present = {f.status for f in findings}
        handles: list[Line2D] = []
        for status, (label, color) in STATUS_INFO.items():
            if status in present:
                handles.append(
                    Line2D([], [], marker="o", ls="", color=color, label=label,
                           markersize=6)
                )
        return handles
