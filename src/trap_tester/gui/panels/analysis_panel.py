"""The Analysis panel: three columns, like the Measurement panel.

Left   — the menus (green): a *Result view* box (view + layout + connector +
         mapping selectors, mirroring the Interfaces panel) above the
         measurement result browser.
Center — the result visualiser (red) over the text report (red), with only a
         *Save view…* button, exactly like the Interfaces panel.
Right  — the acceptance criteria (green): preset + golden reference, the
         analysis-parameter form, and Run / Save report. Scrollable, because the
         form grows with the number of quantities a measurement judges.

Each measurement has its own analysis (see ``core.analysis``); the parameter
form and the plot rebuild for whichever measurement produced the loaded file.
The layout / connector / mapping selectors let the result be re-projected onto
any interface — the same correlation the Interfaces panel offers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core import analysis as analysis_engine
from trap_tester.core import settings as settings_io
from trap_tester.core.analysis import golden
from trap_tester.core.analysis import presets as preset_store
from trap_tester.core.analysis.acceptance import CAT_TOL, Reference
from trap_tester.core.appconfig import analysis_dir, presets_dir, results_dir
from trap_tester.core.layout import (
    InterfaceLayout,
    Mapping,
    apply_to,
    build_drawing,
    coverage,
    dsub50_layout_for_connector,
    fpc_layout_for_connector,
    import_layout,
    import_mapping,
    layout_for,
    load_csv,
    load_layout,
    mapping_options,
    tile_connector_layouts,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.gui.widgets.analysis_view import AnalysisView
from trap_tester.gui.widgets.connector_view import ConnectorView
from trap_tester.gui.widgets.file_browser import FileBrowser
from trap_tester.gui.widgets.layout_folders_dialog import LayoutFoldersDialog
from trap_tester.gui.widgets.reference_dialog import ReferenceDialog
from trap_tester.gui.widgets.settings_form import SettingsForm
from trap_tester.gui.widgets.terminal_output import TerminalOutput

# The two visualisers, in stack order.
_VIEW_CONNECTOR = 0
_VIEW_SCATTER = 1


class AnalysisPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        results_dir().mkdir(parents=True, exist_ok=True)
        self._measurement: str | None = None
        self._df: Any = None
        self._source: Path | None = None
        self._result: analysis_engine.AnalysisResult | None = None
        self._form: SettingsForm | None = None
        self._connectors: list[int] = []
        self._mapping_cache: dict[str, Mapping] = {}

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())  # column 1 (view + result browser)
        splitter.addWidget(self._build_center())  # column 2 (visualiser + report)
        splitter.addWidget(self._build_right())  # column 3 (parameters)
        # only the visualiser grows; the two side columns keep their width
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        splitter.setSizes([340, 640, 400])
        outer.addWidget(splitter)

        self._refresh_layouts()
        self._refresh_mappings()
        self._clear_views()

    def reload_settings(self) -> None:
        """Re-read configured paths + folders (called after Settings changes)."""
        results_dir().mkdir(parents=True, exist_ok=True)
        self._browser.set_directory(results_dir())
        self._mapping_cache.clear()
        self._refresh_layouts()
        self._refresh_mappings()
        self._refresh_presets()

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(260)
        layout = QVBoxLayout(col)

        # The menus, moved out of the visualiser and placed above the result
        # browser (like the Interfaces panel keeps its selectors on the left).
        layout.addWidget(self._build_view_box())

        self._browser = FileBrowser("Measurement Result", results_dir(), recursive=True)
        self._browser.selected.connect(self._load_file)
        self._browser.opened.connect(self._load_file)
        layout.addWidget(self._browser, 1)
        return col

    def _build_right(self) -> QWidget:
        """The acceptance criteria, in their own column like the Measurement
        panel's settings — and scrollable, because the form grows with the
        number of quantities a measurement judges."""
        col = QWidget()
        layout = QVBoxLayout(col)  # default margins: match the other columns

        self._params_box = QGroupBox("Analysis parameters")
        self._params_box.setProperty("role", "interactive")
        self._params_layout = QVBoxLayout(self._params_box)
        # Where the criteria came from (preset + reference) sits above the
        # numbers themselves; the form is appended after it.
        self._params_layout.addWidget(self._build_preset_row())
        self._reference_label = QLabel()
        self._reference_label.setProperty("role", "viewer")
        self._reference_label.setWordWrap(True)
        self._params_layout.addWidget(self._reference_label)
        self._params_layout.addWidget(self._build_reference_row())
        self._params_hint = QLabel("Select a measurement result to analyse.")
        self._params_hint.setWordWrap(True)
        self._params_layout.addWidget(self._params_hint)

        buttons = QHBoxLayout()
        self._run_btn = QPushButton("Run analysis")
        self._run_btn.setProperty("role", "interactive")
        self._run_btn.setEnabled(False)
        self._run_btn.clicked.connect(self.run_analysis)
        self._save_btn = QPushButton("Save report")
        self._save_btn.setProperty("role", "interactive")
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_report)
        buttons.addWidget(self._run_btn, 1)
        buttons.addWidget(self._save_btn)

        self._status = QLabel("Status: idle")
        self._status.setProperty("role", "viewer")
        self._status.setWordWrap(True)

        layout.addWidget(self._params_box)
        layout.addLayout(buttons)
        layout.addWidget(self._status)
        layout.addStretch(1)  # keep the box at the top when the column is tall

        scroll = QScrollArea()
        scroll.setWidget(col)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        # Vertical is the scroll that matters; horizontal only appears if the
        # column is dragged narrower than the form, so nothing is ever clipped
        # away silently.
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setMinimumWidth(240)
        return scroll

    def _build_view_box(self) -> QWidget:
        """The moved menus: view + layout + connector + mapping selectors."""
        box = QGroupBox("Result view")
        box.setProperty("role", "interactive")
        v = QVBoxLayout(box)

        view_row = QHBoxLayout()
        view_row.addWidget(QLabel("View:"))
        self._view_selector = QComboBox()
        self._view_selector.setProperty("role", "interactive")
        self._view_selector.addItems(["Connector map", "Value scatter"])
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        view_row.addWidget(self._view_selector, 1)
        v.addLayout(view_row)

        # Layout selector + Import / Folders (only affects the connector map).
        self._layout_row = QWidget()
        layout_row = QHBoxLayout(self._layout_row)
        layout_row.setContentsMargins(0, 0, 0, 0)
        layout_row.addWidget(QLabel("Layout:"))
        self._layout_selector = QComboBox()
        self._layout_selector.setProperty("role", "interactive")
        self._layout_selector.currentIndexChanged.connect(self._on_layout_changed)
        layout_row.addWidget(self._layout_selector, 1)
        self._import_btn = QPushButton("Import…")
        self._import_btn.setProperty("role", "interactive")
        self._import_btn.setToolTip(
            f"Import a custom interface layout JSON into {user_layouts_dir()}"
        )
        self._import_btn.clicked.connect(self._import_layout)
        layout_row.addWidget(self._import_btn)
        self._folders_btn = QPushButton("Folders…")
        self._folders_btn.setProperty("role", "interactive")
        self._folders_btn.setToolTip("Add folders to search for custom layouts")
        self._folders_btn.clicked.connect(self._manage_folders)
        layout_row.addWidget(self._folders_btn)
        v.addWidget(self._layout_row)

        # Connector selector — shown only when a result spans >1 connector (and,
        # for the map, only for the single-connector built-ins).
        self._conn_row = QWidget()
        conn_row = QHBoxLayout(self._conn_row)
        conn_row.setContentsMargins(0, 0, 0, 0)
        conn_row.addWidget(QLabel("Connector:"))
        self._conn_selector = QComboBox()
        self._conn_selector.setProperty("role", "interactive")
        self._conn_selector.currentIndexChanged.connect(self._on_connector_changed)
        conn_row.addWidget(self._conn_selector)
        conn_row.addStretch(1)
        self._show_all = QCheckBox("Show all")
        self._show_all.setProperty("role", "interactive")
        self._show_all.setToolTip(
            "Render every connector of the result at once, tiled\n"
            "(connector map only; zoom / pan to inspect)."
        )
        self._show_all.toggled.connect(lambda _=False: self._render())
        conn_row.addWidget(self._show_all)
        self._conn_row.setVisible(False)
        v.addWidget(self._conn_row)

        # Mapping selector + Import (cross-interface wiring; map only).
        self._mapping_row = QWidget()
        map_row = QHBoxLayout(self._mapping_row)
        map_row.setContentsMargins(0, 0, 0, 0)
        map_row.addWidget(QLabel("Mapping:"))
        self._mapping_selector = QComboBox()
        self._mapping_selector.setProperty("role", "interactive")
        self._mapping_selector.setToolTip(
            "Cross-interface wiring CSV (found in the custom-layout folders).\n"
            "Overrides the inherent (connector, pin) wiring for this setup."
        )
        self._mapping_selector.currentIndexChanged.connect(self._on_mapping_changed)
        map_row.addWidget(self._mapping_selector, 1)
        self._import_mapping_btn = QPushButton("Import…")
        self._import_mapping_btn.setProperty("role", "interactive")
        self._import_mapping_btn.setToolTip("Import a cross-interface mapping CSV")
        self._import_mapping_btn.clicked.connect(self._import_mapping)
        map_row.addWidget(self._import_mapping_btn)
        v.addWidget(self._mapping_row)
        return box

    def _build_preset_row(self) -> QWidget:
        """Preset selector + Save as… / Import… (acceptance criteria on file)."""
        self._preset_row = QWidget()
        row = QHBoxLayout(self._preset_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Preset:"))
        self._preset_selector = QComboBox()
        self._preset_selector.setProperty("role", "interactive")
        self._preset_selector.currentIndexChanged.connect(self._on_preset_changed)
        row.addWidget(self._preset_selector, 1)
        self._save_preset_btn = QPushButton("Save as…")
        self._save_preset_btn.setProperty("role", "interactive")
        self._save_preset_btn.setToolTip("Save the parameters below as a preset")
        self._save_preset_btn.clicked.connect(self._save_preset)
        row.addWidget(self._save_preset_btn)
        self._import_preset_btn = QPushButton("Import…")
        self._import_preset_btn.setProperty("role", "interactive")
        self._import_preset_btn.setToolTip("Import an analysis preset JSON")
        self._import_preset_btn.clicked.connect(self._import_preset)
        row.addWidget(self._import_preset_btn)
        self._preset_row.setVisible(False)
        return self._preset_row

    def _build_reference_row(self) -> QWidget:
        """Golden-reference controls: capture from the loaded result, view, clear."""
        self._reference_row = QWidget()
        row = QHBoxLayout(self._reference_row)
        row.setContentsMargins(0, 0, 0, 0)
        self._golden_btn = QPushButton("Use result as reference")
        self._golden_btn.setProperty("role", "interactive")
        self._golden_btn.setToolTip(
            "Mark the loaded measurement as the golden reference: its measured\n"
            "values become the expected values, and every pin is then judged\n"
            "against them within the tolerances below.\n"
            "Save a preset afterwards to keep them."
        )
        self._golden_btn.clicked.connect(self._capture_reference)
        row.addWidget(self._golden_btn, 1)
        self._view_reference_btn = QPushButton("View…")
        self._view_reference_btn.setProperty("role", "interactive")
        self._view_reference_btn.setToolTip(
            "Show every expected value in the reference"
        )
        self._view_reference_btn.clicked.connect(self._view_reference)
        row.addWidget(self._view_reference_btn)
        self._clear_reference_btn = QPushButton("Clear")
        self._clear_reference_btn.setProperty("role", "interactive")
        self._clear_reference_btn.setToolTip(
            "Drop the reference — pins go back to the min/max limits"
        )
        self._clear_reference_btn.clicked.connect(self._clear_reference)
        row.addWidget(self._clear_reference_btn)
        self._reference_row.setVisible(False)
        return self._reference_row

    def _build_center(self) -> QWidget:
        col = QSplitter(Qt.Vertical)

        viz_box = QGroupBox("Result visualiser")
        viz_box.setProperty("role", "viewer")
        vv = QVBoxLayout(viz_box)

        top = QHBoxLayout()
        top.addStretch(1)
        self._save_view_btn = QPushButton("Save view…")
        self._save_view_btn.setProperty("role", "interactive")
        self._save_view_btn.setEnabled(False)
        self._save_view_btn.clicked.connect(self._save_view)
        top.addWidget(self._save_view_btn)
        vv.addLayout(top)

        self._viz_stack = QStackedWidget()
        self._connector_view = ConnectorView()
        self._scatter_view = AnalysisView()
        self._viz_stack.addWidget(self._connector_view)  # index 0
        self._viz_stack.addWidget(self._scatter_view)  # index 1
        vv.addWidget(self._viz_stack)

        report_box = QGroupBox("Report")
        report_box.setProperty("role", "viewer")
        rv = QVBoxLayout(report_box)
        self._report = TerminalOutput()
        self._report.setPlaceholderText("Analysis report…")
        rv.addWidget(self._report)

        col.addWidget(viz_box)
        col.addWidget(report_box)
        col.setStretchFactor(0, 3)
        col.setStretchFactor(1, 2)
        return col

    def _clear_views(self, message: str = "Run an analysis to see the result.") -> None:
        self._connector_view.clear(message)
        self._scatter_view.clear(message)

    # ---- view / render -----------------------------------------------------
    def _on_view_changed(self, index: int) -> None:
        self._render()

    def _on_connector_changed(self, index: int) -> None:
        if index >= 0:
            self._render()

    def _is_builtin(self) -> bool:
        token = self._layout_selector.currentData()
        return isinstance(token, str) and token.startswith("builtin:")

    def _selected_connector(self) -> int:
        data = self._conn_selector.currentData()
        if data is not None:
            return int(data)
        return self._connectors[0] if self._connectors else 0

    def _render(self) -> None:
        """Paint the current (result, view, layout, connector, mapping)."""
        view = self._view_selector.currentIndex()
        self._viz_stack.setCurrentIndex(view)
        is_map = view == _VIEW_CONNECTOR
        # layout + mapping only affect the connector map; grey them out otherwise
        self._layout_row.setEnabled(is_map)
        self._mapping_row.setEnabled(is_map)
        if self._result is None:
            self._conn_row.setVisible(False)
            self._show_all.setEnabled(False)
            return

        many = len(self._connectors) > 1
        connector = self._selected_connector()
        if is_map:
            # custom layouts are drawn whole, so the connector picker / "show all"
            # only apply to the single-connector built-ins
            builtin = self._is_builtin()
            self._show_all.setEnabled(builtin and many)
            show_all = builtin and many and self._show_all.isChecked()
            self._conn_row.setVisible(many and builtin and not show_all)
            if layout_for(self._measurement) is None:
                self._connector_view.clear(
                    f"No connector map for '{self._measurement}'."
                )
                return
            layout = self._selected_layout(connector)
            if layout is None:
                self._connector_view.clear(
                    f"No connector map for '{self._measurement}'."
                )
                return
            self._connector_view.fit_on_next_draw()
            self._connector_view.show_drawing(build_drawing(self._result, layout))
        else:
            self._show_all.setEnabled(False)
            self._conn_row.setVisible(many)
            self._scatter_view.show_result(
                self._result, connector if many else None
            )

    # ---- load / analyse ----------------------------------------------------
    def _load_file(self, path: str) -> None:
        try:
            measurement, _settings, df = settings_io.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", f"Could not load result:\n{exc}")
            return

        self._source = Path(path)
        self._measurement = measurement
        self._df = df
        self._report.clear()
        self._clear_views()
        self._result = None
        self._connectors = []
        self._save_btn.setEnabled(False)
        self._save_view_btn.setEnabled(False)

        if df is None or df.empty:
            self._set_no_analysis(f"{self._source.name} contains no data rows.")
            return
        if not analysis_engine.has_analysis(measurement):
            self._set_no_analysis(
                f"No analysis is available for measurement '{measurement}' yet."
            )
            return

        self._rebuild_form(analysis_engine.analysis_settings_for(measurement))
        self._params_box.setTitle(f"Analysis parameters — {measurement}")
        self._run_btn.setEnabled(True)
        self._status.setText(f"Loaded {self._source.name} ({len(df)} rows).")
        self.run_analysis()  # show an initial result immediately

    def _set_no_analysis(self, message: str) -> None:
        self._rebuild_form(None)
        self._params_hint.setText(message)
        self._run_btn.setEnabled(False)
        self._clear_views(message)
        self._status.setText(message)

    def _rebuild_form(self, settings_type: type | None) -> None:
        """Replace the parameter form (or show the hint when no analysis)."""
        if self._form is not None:
            self._params_layout.removeWidget(self._form)
            self._form.setParent(None)
            self._form.deleteLater()
            self._form = None
        self._params_hint.setVisible(settings_type is None)
        self._preset_row.setVisible(settings_type is not None)
        if settings_type is not None:
            self._form = SettingsForm(settings_type())
            self._params_layout.addWidget(self._form)
        self._refresh_presets()
        self._sync_reference()

    # ---- presets -----------------------------------------------------------
    def _refresh_presets(self) -> None:
        """List the presets saved for the loaded measurement, keeping the choice."""
        self._preset_selector.setToolTip(
            "Saved acceptance criteria for this measurement — limits, tolerances\n"
            f"and any golden reference. Stored in {presets_dir()}."
        )
        keep = self._preset_selector.currentData()
        self._preset_selector.blockSignals(True)
        self._preset_selector.clear()
        self._preset_selector.addItem("None (defaults)", None)
        if self._measurement:
            for name, path in preset_store.list_presets(self._measurement):
                self._preset_selector.addItem(name, str(path))
        idx = self._preset_selector.findData(keep) if keep else 0
        self._preset_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self._preset_selector.blockSignals(False)

    def _on_preset_changed(self, index: int) -> None:
        """Apply the chosen preset to the form and re-run (index 0 = defaults)."""
        if index < 0 or self._form is None:
            return
        token = self._preset_selector.currentData()
        settings_type = analysis_engine.analysis_settings_for(self._measurement)
        if not token:
            if settings_type is not None:
                self._form.set_settings(settings_type())
            self._sync_reference()
            self.run_analysis()
            return
        try:
            preset = preset_store.load(Path(token))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "Preset unavailable",
                f"Could not read '{Path(token).name}':\n{exc}\n\n"
                "Falling back to the defaults.",
            )
            self._preset_selector.setCurrentIndex(0)  # re-enters with the defaults
            return
        self._form.set_settings(preset.settings)
        self._sync_reference()
        self._status.setText(f"Preset '{preset.name}' applied.")
        self.run_analysis()

    # ---- golden reference --------------------------------------------------
    def _current_reference(self) -> Reference:
        if self._form is None:
            return Reference()
        return self._form.hidden("reference") or Reference()

    def _capture_reference(self) -> None:
        """Mark the loaded result as golden: its values become the expected ones."""
        if self._form is None or self._df is None or not self._measurement:
            return
        if self._current_reference():
            confirm = QMessageBox.question(
                self, "Replace reference",
                "A golden reference is already loaded.\n\n"
                "Replace it with the values measured in "
                f"{self._source.name if self._source else 'this result'}?",
            )
            if confirm != QMessageBox.Yes:
                return
        try:
            captured = golden.capture(
                self._df, self._measurement,
                source=self._source.name if self._source else "",
            )
        except (KeyError, ValueError) as exc:
            QMessageBox.warning(self, "Cannot use as reference", str(exc))
            return
        if not captured.reference:
            QMessageBox.warning(
                self, "Cannot use as reference",
                "No usable readings in this result — nothing to expect.",
            )
            return
        self._form.set_hidden("reference", captured.reference)
        self._sync_reference()
        self.run_analysis()
        self._status.setText(
            f"{captured.describe()}. Save a preset to keep this reference."
        )

    def _clear_reference(self) -> None:
        if self._form is None:
            return
        self._form.set_hidden("reference", Reference())
        self._sync_reference()
        self.run_analysis()
        self._status.setText("Reference cleared — judging against the min/max limits.")

    def _view_reference(self) -> None:
        ReferenceDialog(
            self._current_reference(), self._measurement or "", self
        ).exec()

    def _sync_reference(self) -> None:
        """Reflect the loaded reference: label, buttons, whether tolerances apply.

        The tolerances are only ever used for pins the reference covers, so they
        are greyed out (with the reason on the tooltip) until one is loaded.
        """
        if self._form is None:
            self._reference_label.setVisible(False)
            self._reference_row.setVisible(False)
            return
        reference = self._current_reference()
        active = bool(reference)
        self._reference_label.setVisible(True)
        self._reference_row.setVisible(True)
        self._reference_label.setText(f"Reference: {reference.describe()}")
        self._golden_btn.setEnabled(self._df is not None)
        self._view_reference_btn.setEnabled(active)
        self._clear_reference_btn.setEnabled(active)
        self._form.set_category_enabled(CAT_TOL, active)
        self._form.set_category_tooltip(
            CAT_TOL,
            "Applied where the reference has the pin:\n"
            "expected ± (abs tol + rel tol · |expected|)."
            if active
            else "No golden reference loaded — every pin is judged against the\n"
            "min/max limits above, so the tolerances are unused.",
        )

    def _save_preset(self) -> None:
        if self._form is None or not self._measurement:
            return
        try:
            settings = self._form.get_settings()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid parameters", str(exc))
            return
        suggested = self._preset_selector.currentText()
        if not self._preset_selector.currentData():
            suggested = f"{self._measurement} acceptance"
        name, ok = QInputDialog.getText(
            self, "Save preset", "Preset name:", text=suggested
        )
        name = name.strip()
        if not ok or not name:
            return
        try:
            path = preset_store.save(settings, self._measurement, name)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"Could not write preset:\n{exc}")
            return
        self._refresh_presets()
        idx = self._preset_selector.findData(str(path))
        if idx >= 0:
            self._preset_selector.blockSignals(True)  # already applied; don't re-run
            self._preset_selector.setCurrentIndex(idx)
            self._preset_selector.blockSignals(False)
        self._status.setText(f"Preset saved to {path}.")

    def _import_preset(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import preset", "", "Analysis preset (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            dest = preset_store.import_preset(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid analysis preset:\n{exc}",
            )
            return
        self._refresh_presets()
        idx = self._preset_selector.findData(str(dest))
        if idx >= 0:
            self._preset_selector.setCurrentIndex(idx)  # applies it
        else:
            # a preset for another measurement: stored, but not listed here
            self._status.setText(f"Preset imported to {dest} (other measurement).")

    def run_analysis(self) -> None:
        if self._df is None or self._measurement is None or self._form is None:
            return
        try:
            settings = self._form.get_settings()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid parameters", str(exc))
            return
        try:
            result = analysis_engine.analyse(self._measurement, self._df, settings)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Analysis failed", str(exc))
            return

        self._result = result
        self._connectors = sorted({int(f.connector) for f in result.findings})
        self._conn_selector.blockSignals(True)
        self._conn_selector.clear()
        for c in self._connectors:
            self._conn_selector.addItem(f"{c}", c)
        self._conn_selector.setCurrentIndex(0)
        self._conn_selector.blockSignals(False)

        self._render()
        source_name = self._source.name if self._source else ""
        self._report.clear()
        self._report.appendPlainText(analysis_engine.render_report(result, source_name))
        self._save_btn.setEnabled(True)
        self._save_view_btn.setEnabled(True)
        self._status.setText(
            f"Analysed {source_name}: {result.n_faults} fault(s) "
            f"in {len(result.findings)} pins."
        )

    # ---- layout selection / import -----------------------------------------
    def _selected_layout(self, connector: int) -> InterfaceLayout | None:
        """The layout for the current selection: a built-in or a custom file.

        The findings carry both a DSUB pin and an FPC conductor, so a result can
        be re-projected onto whichever interface is chosen (built-in DSUB-50 or
        FPC ribbon, or an imported layout) — the same correlation the Interfaces
        panel uses. A selected mapping re-wires it (with a coverage warning when
        it does not apply).
        """
        token = self._layout_selector.currentData()
        if isinstance(token, str) and token.startswith("builtin:"):
            is_dsub = token == "builtin:dsub50"
            factory = dsub50_layout_for_connector if is_dsub else fpc_layout_for_connector
            if len(self._connectors) > 1 and self._show_all.isChecked():
                conns = self._connectors
                label = ("DSUB-50" if is_dsub else "FPC ribbon") + " — all connectors"
                base = tile_connector_layouts([factory(c) for c in conns], conns, label)
            else:
                base = factory(connector)
        else:
            try:
                # Custom layouts are drawn whole (all their connectors), so a
                # multi-connector interposer looks the same here as in Interfaces.
                base = load_layout(Path(token))
            except Exception as exc:  # noqa: BLE001 — a deleted/corrupt custom file
                QMessageBox.warning(
                    self, "Layout unavailable",
                    f"Could not load '{Path(token).name}':\n{exc}\n\n"
                    "Falling back to the built-in DSUB-50.",
                )
                self._select_builtin()
                base = dsub50_layout_for_connector(connector)
        mapping = self._selected_mapping()
        if mapping is None:
            self._connector_view.set_warning(None)
            return base
        if coverage(base, mapping) == 0:
            name = self._mapping_selector.currentText()
            self._connector_view.set_warning(
                f"Mapping '{name}' does not apply to '{base.name}' — nothing to "
                "propagate here; showing inherent wiring."
            )
        else:
            self._connector_view.set_warning(None)
        return apply_to(base, mapping)

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
        if index >= 0 and self._result is not None:
            self._render()

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

    def _manage_folders(self) -> None:
        dlg = LayoutFoldersDialog(self)
        dlg.exec()
        if dlg.changed():
            self._mapping_cache.clear()
            self._refresh_layouts()
            self._refresh_mappings()
            self._render()

    # ---- mapping selection -------------------------------------------------
    def _refresh_mappings(self) -> None:
        """Rebuild the mapping selector from the search folders, keeping choice."""
        keep = self._mapping_selector.currentData()
        self._mapping_selector.blockSignals(True)
        self._mapping_selector.clear()
        self._mapping_selector.addItem("Inherent (no mapping)", None)
        for name, path in mapping_options():
            self._mapping_selector.addItem(name, path)
        idx = self._mapping_selector.findData(keep) if keep else 0
        self._mapping_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self._mapping_selector.blockSignals(False)

    def _selected_mapping(self) -> Mapping | None:
        """The parsed mapping for the current selection, or ``None`` for inherent."""
        token = self._mapping_selector.currentData()
        if not token:
            return None
        if token not in self._mapping_cache:
            try:
                self._mapping_cache[token] = load_csv(Path(token))
            except Exception as exc:  # noqa: BLE001 — deleted/malformed CSV
                QMessageBox.warning(
                    self, "Mapping unavailable",
                    f"Could not read '{Path(token).name}':\n{exc}\n\n"
                    "Falling back to the inherent wiring.",
                )
                self._mapping_selector.blockSignals(True)
                self._mapping_selector.setCurrentIndex(0)
                self._mapping_selector.blockSignals(False)
                return None
        return self._mapping_cache[token]

    def _on_mapping_changed(self, index: int) -> None:
        if index >= 0 and self._result is not None:
            self._render()

    def _import_mapping(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import mapping", "", "Mapping CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_mapping(path)
        except Exception as exc:  # noqa: BLE001 — surface any parse/IO failure
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid mapping CSV:\n{exc}",
            )
            return
        self._mapping_cache.clear()
        self._refresh_mappings()
        idx = self._mapping_selector.findData(str(dest))
        if idx >= 0:
            self._mapping_selector.setCurrentIndex(idx)  # re-renders if a result shows

    # ---- save --------------------------------------------------------------
    def _save_view(self) -> None:
        """Export the currently visible visualiser (map or scatter) as an image."""
        view = self._viz_stack.currentWidget()
        tag = "map" if self._viz_stack.currentIndex() == _VIEW_CONNECTOR else "scatter"
        stem = self._source.stem if self._source else "analysis"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save view", f"{stem}-{tag}.png", "PNG image (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            view.save_view(path)
        except Exception as exc:  # noqa: BLE001 — surface any render/IO failure
            QMessageBox.warning(self, "Save failed", f"Could not save image:\n{exc}")
            return
        self._status.setText(f"View saved to {Path(path).name}.")

    def _save_report(self) -> None:
        if self._result is None or self._source is None:
            return
        out_dir = analysis_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / f"{self._source.stem}-result.txt"
        source_name = self._source.name
        try:
            out.write_text(analysis_engine.render_report(self._result, source_name))
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"Could not write report:\n{exc}")
            return
        self._status.setText(f"Report saved to {out}.")
