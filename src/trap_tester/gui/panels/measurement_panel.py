"""The Measurement panel (mock page 1): three columns.

Left   — Measurement Definition browser (choose the measurement; double-click a
         ``.py`` to view its source over the plot area) + Result browser (load a
         previous measurement's settings).
Center — Status, the Ch1/Ch2 captures (or the definition source), and the
         run / gate controls.
Right  — Settings form (green), waveform preview and terminal output (red).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
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

from trap_tester.core import settings as settings_io
from trap_tester.core.measurements import run_filter_measurement
from trap_tester.core.settings import FilterSettings
from trap_tester.gui.widgets.code_viewer import CodeViewer
from trap_tester.gui.widgets.file_browser import FileBrowser
from trap_tester.gui.widgets.prompt_bar import PromptBar
from trap_tester.gui.widgets.scope_canvas import ScopeCanvas, WaveformPreview
from trap_tester.gui.widgets.settings_form import SettingsForm
from trap_tester.gui.widgets.terminal_output import TerminalOutput
from trap_tester.gui.worker import MeasurementWorker, QtGate, QtReporter

RESULTS_DIR = Path("results")
MEASUREMENT_DIR = Path("measurement")

# Which measurement scripts are wired to a run function (and their settings type).
_MEASUREMENTS: dict[str, tuple[Callable[..., Any], type]] = {
    "measure_filter.py": (run_filter_measurement, FilterSettings),
}


class MeasurementPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        RESULTS_DIR.mkdir(exist_ok=True)
        self._worker: MeasurementWorker | None = None
        self._reporter: QtReporter | None = None
        self._gate: QtGate | None = None
        self._run_fn: Callable[..., Any] | None = run_filter_measurement

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._left = self._build_left()
        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(self._left)  # column 1 (file selectors)
        self._splitter.addWidget(self._build_center())  # column 2
        self._splitter.addWidget(self._build_right())  # column 3
        # columns 2 and 3 share the extra space; column 1 keeps its size
        self._splitter.setStretchFactor(0, 0)
        self._splitter.setStretchFactor(1, 3)
        self._splitter.setStretchFactor(2, 2)
        self._splitter.setSizes([220, 700, 360])
        outer.addWidget(self._splitter)

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QSplitter(Qt.Vertical)
        self._definition_browser = FileBrowser(
            "Measurement Definition", MEASUREMENT_DIR, pattern="*.py"
        )
        self._result_browser = FileBrowser("Measurement Result", RESULTS_DIR)
        # single click chooses the measurement; double click views the source
        self._definition_browser.selected.connect(self._choose_measurement)
        self._definition_browser.opened.connect(self._show_definition_code)
        # a result: single click loads its settings, double click views the JSON
        self._result_browser.selected.connect(self._load_settings_file)
        self._result_browser.opened.connect(self._show_result_json)
        col.addWidget(self._definition_browser)
        col.addWidget(self._result_browser)
        return col

    def _build_center(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)

        top = QHBoxLayout()
        self._toggle_files_btn = QPushButton("❮ Hide files")
        self._toggle_files_btn.setProperty("role", "interactive")
        self._toggle_files_btn.clicked.connect(self._toggle_files)
        top.addWidget(self._toggle_files_btn)
        top.addStretch(1)
        layout.addLayout(top)

        self._status = QLabel("Status / Progress: idle")
        self._status.setProperty("role", "viewer")
        self._status.setAlignment(Qt.AlignCenter)

        # the plot area doubles as a definition-source viewer
        self._center_stack = QStackedWidget()
        self._scope = ScopeCanvas()
        self._code_viewer = CodeViewer()
        self._code_viewer.closed.connect(self._hide_definition_code)
        self._center_stack.addWidget(self._scope)  # index 0
        self._center_stack.addWidget(self._code_viewer)  # index 1

        self._prompt = PromptBar()
        self._prompt.confirmed.connect(self._on_confirmed)
        self._prompt.continued.connect(self._on_continued)

        controls = QHBoxLayout()
        self._start_btn = QPushButton("▶ Start measurement")
        self._start_btn.setProperty("role", "interactive")
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setProperty("role", "interactive")
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        controls.addWidget(self._start_btn, 1)
        controls.addWidget(self._stop_btn)

        layout.addWidget(self._status)
        layout.addWidget(self._center_stack, 1)
        layout.addWidget(self._prompt)
        layout.addLayout(controls)
        return col

    def _build_right(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(260)
        layout = QVBoxLayout(col)

        settings_box = QGroupBox("Settings — measure_filter")
        settings_box.setProperty("role", "interactive")
        box_layout = QVBoxLayout(settings_box)
        self._form = SettingsForm(FilterSettings())
        self._form.changed.connect(self._refresh_preview)
        self._sim_checkbox = QCheckBox("Simulate (no hardware)")
        self._sim_checkbox.setChecked(True)
        self._sim_checkbox.setProperty("role", "interactive")
        box_layout.addWidget(self._form)
        box_layout.addWidget(self._sim_checkbox)

        preview_box = QGroupBox("Preview — applied waveform + trigger")
        preview_box.setProperty("role", "viewer")
        pv = QVBoxLayout(preview_box)
        self._preview = WaveformPreview()
        pv.addWidget(self._preview)

        terminal_box = QGroupBox("Terminal output")
        terminal_box.setProperty("role", "viewer")
        tv = QVBoxLayout(terminal_box)
        self._terminal = TerminalOutput()
        tv.addWidget(self._terminal)

        layout.addWidget(settings_box)
        layout.addWidget(preview_box)
        layout.addWidget(terminal_box, 1)
        self._refresh_preview()
        return col

    # ---- layout ------------------------------------------------------------
    def _toggle_files(self) -> None:
        show = not self._left.isVisible()
        self._left.setVisible(show)
        self._toggle_files_btn.setText("❮ Hide files" if show else "❯ Show files")

    # ---- measurement selection / source view ------------------------------
    def _choose_measurement(self, path: str) -> None:
        name = Path(path).name
        entry = _MEASUREMENTS.get(name)
        if entry is None:
            self._run_fn = None
            self._start_btn.setEnabled(False)
            self._status.setText(f"{name} is not available yet (milestone 1: measure_filter).")
            return
        self._run_fn = entry[0]
        self._start_btn.setEnabled(self._worker is None)
        self._status.setText(f"Selected {name}. Adjust settings and press Start.")

    def _show_definition_code(self, path: str) -> None:
        self._choose_measurement(path)
        self._code_viewer.show_file(path, kind="Definition")
        self._center_stack.setCurrentWidget(self._code_viewer)

    def _show_result_json(self, path: str) -> None:
        self._code_viewer.show_file(path, kind="Result")
        self._center_stack.setCurrentWidget(self._code_viewer)

    def _hide_definition_code(self) -> None:
        self._center_stack.setCurrentWidget(self._scope)

    # ---- settings load / preview ------------------------------------------
    def _load_settings_file(self, path: str) -> None:
        try:
            settings, _ = settings_io.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", f"Could not load settings:\n{exc}")
            return
        self._form.set_settings(settings)
        self._terminal.append_line(f"Loaded settings from {Path(path).name}")

    def _refresh_preview(self) -> None:
        try:
            s = self._form.get_settings()
        except (ValueError, TypeError):
            return  # mid-edit; ignore until fields are valid
        self._preview.update_preview(s.f_square, s.amplitude)

    # ---- run / stop --------------------------------------------------------
    def _start(self) -> None:
        if self._worker is not None:
            return
        if self._run_fn is None:
            QMessageBox.information(self, "Not available", "This measurement is not wired up yet.")
            return
        try:
            s = self._form.get_settings()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return

        self._center_stack.setCurrentWidget(self._scope)  # show live plots
        self._terminal.clear()
        self._reporter = QtReporter()
        self._gate = QtGate()
        self._reporter.statusChanged.connect(self._status.setText)
        self._reporter.logLine.connect(self._terminal.append_line)
        self._reporter.captured.connect(self._scope.update_capture)
        self._reporter.resulted.connect(self._on_result)
        self._gate.confirmRequested.connect(self._prompt.ask_confirm)
        self._gate.continueRequested.connect(self._prompt.ask_continue)

        self._worker = MeasurementWorker(
            self._run_fn, s, self._reporter, self._gate,
            force_mock=self._sim_checkbox.isChecked(),
        )
        self._worker.measurementDone.connect(self._on_done)
        self._worker.measurementFailed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup_worker)

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status.setText("Starting…")
        self._worker.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self._status.setText("Cancelling…")
            self._worker.cancel()

    # ---- gate resolution ---------------------------------------------------
    def _on_confirmed(self, retake: bool) -> None:
        if self._gate is not None:
            self._gate.resolve_confirm(retake)

    def _on_continued(self) -> None:
        if self._gate is not None:
            self._gate.resolve_continue()

    # ---- worker callbacks --------------------------------------------------
    def _on_result(self, row: dict[str, Any]) -> None:
        self._terminal.append_line(
            f"  → pin {row['DSUB pin']}: "
            f"{'SHORT' if row['Shorted'] else f'C={row['C_filter_nF']:.3f} nF'}"
        )

    def _on_done(self, df: Any) -> None:
        self._status.setText(f"Done — {len(df)} rows.")
        self._prompt.reset()
        self._result_browser.refresh()

    def _on_failed(self, tb: str) -> None:
        self._status.setText("Measurement failed.")
        self._terminal.append_line(tb)
        QMessageBox.critical(self, "Measurement failed", tb)

    def _cleanup_worker(self) -> None:
        self._start_btn.setEnabled(self._run_fn is not None)
        self._stop_btn.setEnabled(False)
        self._worker = None
        self._reporter = None
        self._gate = None
