"""The analysis connector map: an :class:`AnalysisResult` on its interface.

Builds on :class:`~trap_tester.gui.widgets.layout_canvas.LayoutCanvas` (which
does the primitive→artist painting and hover) and adds the analysis-specific
bits: a connector selector, the layout selector + import, and a fault-count
title / status legend.
"""

from __future__ import annotations

from pathlib import Path

from matplotlib.lines import Line2D
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.analysis import STATUS_INFO, AnalysisResult
from trap_tester.core.layout import (
    Drawing,
    InterfaceLayout,
    build_drawing,
    dsub50_layout_for_connector,
    fpc_layout_for_connector,
    import_layout,
    layout_for,
    load_layout,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.core.layout.interface import UNMEASURED_FILL, UNMEASURED_STROKE
from trap_tester.gui.widgets.layout_canvas import LayoutCanvas


class ConnectorView(LayoutCanvas):
    """Draw an analysis result on its physical interface (e.g. DSUB-50)."""

    def __init__(self) -> None:
        super().__init__()
        self._result: AnalysisResult | None = None
        self._connectors: list[int] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # A single compact controls row split into two divisions so it steals as
        # little height from the plot as possible: the connector selector on the
        # left, the layout selector + Import on the right. Neither combo stretches
        # to full width.
        controls = QWidget()
        controls_l = QHBoxLayout(controls)
        controls_l.setContentsMargins(0, 0, 0, 0)

        # Left division — connector selector, shown only when a result spans >1.
        self._conn_row = QWidget()
        conn_layout = QHBoxLayout(self._conn_row)
        conn_layout.setContentsMargins(0, 0, 0, 0)
        conn_layout.addWidget(QLabel("Connector:"))
        self._conn_selector = QComboBox()
        self._conn_selector.setProperty("role", "interactive")
        self._conn_selector.currentIndexChanged.connect(self._on_connector_changed)
        conn_layout.addWidget(self._conn_selector)
        self._conn_row.setVisible(False)
        controls_l.addWidget(self._conn_row)

        controls_l.addStretch(1)

        # Right division — built-in DSUB-50 plus any imported custom layouts,
        # with an Import button that pulls a layout file into the user store.
        controls_l.addWidget(QLabel("Layout:"))
        self._layout_selector = QComboBox()
        self._layout_selector.setProperty("role", "interactive")
        self._layout_selector.setMinimumWidth(150)
        self._layout_selector.currentIndexChanged.connect(self._on_layout_changed)
        controls_l.addWidget(self._layout_selector)
        self._import_btn = QPushButton("Import…")
        self._import_btn.setProperty("role", "interactive")
        self._import_btn.setToolTip(
            f"Import a custom layout JSON into {user_layouts_dir()}"
        )
        self._import_btn.clicked.connect(self._import_layout)
        controls_l.addWidget(self._import_btn)

        layout.addWidget(controls)
        layout.addWidget(self.canvas, 1)

        self._refresh_layouts()
        self.clear()

    def clear(self, message: str = "Run an analysis to see the connector map.") -> None:
        self._result = None
        self._conn_row.setVisible(False)
        super().clear(message)

    def show_result(self, result: AnalysisResult) -> None:
        """Paint ``result`` on the selected layout."""
        if layout_for(result.measurement) is None:
            self.clear(f"No connector map for '{result.measurement}'.")
            return
        self._result = result
        self._connectors = sorted({int(f.connector) for f in result.findings})

        self._conn_selector.blockSignals(True)
        self._conn_selector.clear()
        for c in self._connectors:
            self._conn_selector.addItem(f"{c}", c)
        self._conn_selector.setCurrentIndex(0)
        self._conn_selector.blockSignals(False)
        self._refresh_view()

    def _refresh_view(self) -> None:
        """Render the current (result, layout, connector) selection.

        The connector picker only applies to the single-connector built-ins; a
        custom layout carries its own connectors and is drawn *whole* (like the
        Interfaces panel), so unmeasured pads on every connector still show as
        "No data" and the picker is hidden.
        """
        if self._result is None:
            return
        builtin = self._is_builtin()
        self._conn_row.setVisible(builtin and len(self._connectors) > 1)
        data = self._conn_selector.currentData()
        connector = int(data) if data is not None else 0
        layout = self._selected_layout(connector)
        if layout is None:
            self.clear(f"No connector map for '{self._result.measurement}'.")
            return
        self.show_drawing(build_drawing(self._result, layout))

    def _on_connector_changed(self, index: int) -> None:
        if index < 0 or self._result is None:
            return
        self._refresh_view()

    def _is_builtin(self) -> bool:
        token = self._layout_selector.currentData()
        return isinstance(token, str) and token.startswith("builtin:")

    # ---- title / legend (LayoutCanvas hooks) -------------------------------
    def _title(self, drawing: Drawing) -> str:
        measured = [p for p in drawing.pins if p.measured]
        faults = [p for p in measured if p.status != "ok"]
        return f"{drawing.title} — {len(faults)} fault(s) / {len(measured)} pins"

    def _legend(self, drawing: Drawing) -> list[Line2D]:
        present = {p.status for p in drawing.pins}
        handles: list[Line2D] = []
        for status, (label, color) in STATUS_INFO.items():
            if status in present:
                handles.append(Line2D([], [], marker="o", ls="", color=color,
                                      label=label, markersize=7))
        if "unmeasured" in present:
            handles.append(Line2D([], [], marker="o", ls="", label="No data",
                                  markerfacecolor=UNMEASURED_FILL,
                                  markeredgecolor=UNMEASURED_STROKE, color="none",
                                  markersize=7))
        return handles + self._flavor_legend(drawing)

    # ---- layout selection / import -----------------------------------------
    def _selected_layout(self, connector: int) -> InterfaceLayout | None:
        """The layout for the current selection: a built-in or a custom file.

        The findings carry both a DSUB pin and an FPC conductor, so a result can
        be re-projected onto whichever interface is chosen (built-in DSUB-50 or
        FPC ribbon, or an imported layout) — the same correlation the Interfaces
        panel uses.
        """
        token = self._layout_selector.currentData()
        if token == "builtin:dsub50":
            return dsub50_layout_for_connector(connector)
        if token == "builtin:fpc":
            return fpc_layout_for_connector(connector)
        try:
            # Custom layouts are drawn whole (all their connectors), so a
            # multi-connector interposer looks the same here as in Interfaces.
            return load_layout(Path(token))
        except Exception as exc:  # noqa: BLE001 — a deleted/corrupt custom file
            QMessageBox.warning(
                self, "Layout unavailable",
                f"Could not load '{Path(token).name}':\n{exc}\n\n"
                "Falling back to the built-in DSUB-50.",
            )
            self._select_builtin()
            return dsub50_layout_for_connector(connector)

    def _refresh_layouts(self) -> None:
        """Rebuild the selector from the user store, keeping the selection."""
        keep = self._layout_selector.currentData()
        self._layout_selector.blockSignals(True)
        self._layout_selector.clear()
        self._layout_selector.addItem("DSUB-50 (built-in)", "builtin:dsub50")
        self._layout_selector.addItem("FPC ribbon (built-in)", "builtin:fpc")
        for name, path in user_layout_options():
            self._layout_selector.addItem(name, path)
        idx = self._layout_selector.findData(keep) if keep else 0
        self._layout_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self._layout_selector.blockSignals(False)

    def _select_builtin(self) -> None:
        self._layout_selector.blockSignals(True)
        self._layout_selector.setCurrentIndex(0)
        self._layout_selector.blockSignals(False)

    def _on_layout_changed(self, index: int) -> None:
        if index < 0 or self._result is None:
            return
        self._refresh_view()

    def _import_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import layout", "", "Layout JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_layout(path)
        except Exception as exc:  # noqa: BLE001 — surface any parse/IO failure
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid layout file:\n{exc}",
            )
            return
        self._refresh_layouts()
        idx = self._layout_selector.findData(str(dest))
        if idx >= 0:
            self._layout_selector.setCurrentIndex(idx)  # triggers a re-render
