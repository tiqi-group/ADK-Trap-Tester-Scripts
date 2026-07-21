"""The Analysis panel (mock page 2): two columns.

Left  — Result browser (green) + analysis-parameter form (green) + Run / Save
        report buttons. Pick a saved measurement; its analysis form appears.
Right — the result visualiser (red) over the text report (red).

Each measurement has its own analysis (see ``core.analysis``); the parameter
form and the plot rebuild for whichever measurement produced the loaded file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core import analysis as analysis_engine
from trap_tester.core import settings as settings_io
from trap_tester.gui.widgets.analysis_view import AnalysisView
from trap_tester.gui.widgets.connector_view import ConnectorView
from trap_tester.gui.widgets.file_browser import FileBrowser
from trap_tester.gui.widgets.settings_form import SettingsForm
from trap_tester.gui.widgets.terminal_output import TerminalOutput

RESULTS_DIR = Path("results")


class AnalysisPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        RESULTS_DIR.mkdir(exist_ok=True)
        self._measurement: str | None = None
        self._df: Any = None
        self._source: Path | None = None
        self._result: analysis_engine.AnalysisResult | None = None
        self._form: SettingsForm | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 780])
        outer.addWidget(splitter)

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(300)
        layout = QVBoxLayout(col)

        self._browser = FileBrowser("Measurement Result", RESULTS_DIR)
        self._browser.selected.connect(self._load_file)
        self._browser.opened.connect(self._load_file)

        self._params_box = QGroupBox("Analysis parameters")
        self._params_box.setProperty("role", "interactive")
        self._params_layout = QVBoxLayout(self._params_box)
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

        layout.addWidget(self._browser, 1)
        layout.addWidget(self._params_box)
        layout.addLayout(buttons)
        layout.addWidget(self._status)
        return col

    def _build_right(self) -> QWidget:
        col = QSplitter(Qt.Vertical)

        viz_box = QGroupBox("Result visualiser")
        viz_box.setProperty("role", "viewer")
        vv = QVBoxLayout(viz_box)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("View:"))
        self._viz_selector = QComboBox()
        self._viz_selector.setProperty("role", "interactive")
        self._viz_selector.addItems(["Connector map", "Value scatter"])
        self._viz_selector.currentIndexChanged.connect(self._on_view_changed)
        selector_row.addWidget(self._viz_selector)
        selector_row.addStretch(1)
        self._save_view_btn = QPushButton("Save view…")
        self._save_view_btn.setProperty("role", "interactive")
        self._save_view_btn.setEnabled(False)
        self._save_view_btn.clicked.connect(self._save_view)
        selector_row.addWidget(self._save_view_btn)
        vv.addLayout(selector_row)

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

    def _on_view_changed(self, index: int) -> None:
        self._viz_stack.setCurrentIndex(index)

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
        if settings_type is not None:
            self._form = SettingsForm(settings_type())
            self._params_layout.addWidget(self._form)

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
        self._connector_view.show_result(result)
        self._scatter_view.show_result(result)
        source_name = self._source.name if self._source else ""
        self._report.clear()
        self._report.appendPlainText(analysis_engine.render_report(result, source_name))
        self._save_btn.setEnabled(True)
        self._save_view_btn.setEnabled(True)
        self._status.setText(
            f"Analysed {source_name}: {result.n_faults} fault(s) "
            f"in {len(result.findings)} pins."
        )

    def _save_view(self) -> None:
        """Export the currently visible visualiser (map or scatter) as an image."""
        view = self._viz_stack.currentWidget()
        tag = "map" if self._viz_stack.currentIndex() == 0 else "scatter"
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
        out = RESULTS_DIR / f"{self._source.stem}-result.txt"
        source_name = self._source.name
        try:
            out.write_text(analysis_engine.render_report(self._result, source_name))
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"Could not write report:\n{exc}")
            return
        self._status.setText(f"Report saved to {out}.")
        self._browser.refresh()
