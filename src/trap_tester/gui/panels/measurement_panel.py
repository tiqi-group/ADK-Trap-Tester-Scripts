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
    QComboBox,
    QFormLayout,
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
from trap_tester.core import measurements as _core_measurements
from trap_tester.core.appconfig import measurements_dir, results_dir
from trap_tester.core.device import enumerate_devices
from trap_tester.core.measurements import (
    digital_out_for,
    run_filter_measurement,
    run_resistance_measurement,
    run_voltage_measurement,
)
from trap_tester.core.settings import (
    FilterSettings,
    ResistanceSettings,
    VoltageSettings,
)
from trap_tester.gui.widgets.code_viewer import CodeViewer
from trap_tester.gui.widgets.file_browser import FileBrowser
from trap_tester.gui.widgets.prompt_bar import PromptBar
from trap_tester.gui.widgets.scope_canvas import (
    ScopeCanvas,
    WaveformPreview,
    channels_for,
)
from trap_tester.gui.widgets.settings_form import SettingsForm
from trap_tester.gui.widgets.terminal_output import TerminalOutput
from trap_tester.gui.worker import MeasurementWorker, QtGate, QtReporter

# The core module that implements each measurement (shown in the source viewer).
_CORE_MEAS_DIR = Path(_core_measurements.__file__).parent


def _device_priority(dev: dict[str, Any]) -> int:
    """Sort key for the device selector: prefer a plain Analog Discovery 3.

    The trap-tester frontend targets the Analog Discovery 2/3, so favour those
    over the Pro (ADP-series) models when several devices are attached.
    """
    name = str(dev.get("name", "")).lower()
    is_pro = "pro" in name or "adp" in name
    if "discovery 3" in name and not is_pro:
        return 0
    if "discovery 2" in name and not is_pro:
        return 1
    if not is_pro:
        return 2
    return 3

# Measurement key -> (run function, settings dataclass).
_MEASUREMENTS: dict[str, tuple[Callable[..., Any], type]] = {
    "measure_filter": (run_filter_measurement, FilterSettings),
    "measure_voltage": (run_voltage_measurement, VoltageSettings),
    "measure_resistance": (run_resistance_measurement, ResistanceSettings),
}

# Friendly name shown to the operator instead of the internal key / filename.
_DISPLAY_NAME: dict[str, str] = {
    "measure_filter": "Measure RC",
    "measure_resistance": "Measure DC Resistance",
    "measure_voltage": "Voltage meter",
}

# Definition-list order, and the core module implementing each measurement.
_DEFINITION_ORDER = ("measure_filter", "measure_resistance", "measure_voltage")
_SOURCE_FILE: dict[str, Path] = {
    "measure_filter": _CORE_MEAS_DIR / "filter.py",
    "measure_resistance": _CORE_MEAS_DIR / "resistance.py",
    "measure_voltage": _CORE_MEAS_DIR / "voltage.py",
}


class MeasurementPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        measurements_dir().mkdir(parents=True, exist_ok=True)
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

    def reload_settings(self) -> None:
        """Re-read the configured output paths (called after Settings changes)."""
        measurements_dir().mkdir(parents=True, exist_ok=True)
        self._result_browser.set_directory(results_dir())

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QSplitter(Qt.Vertical)
        self._definition_browser = FileBrowser(
            "Measurement Definition",
            entries=[(_DISPLAY_NAME[k], k) for k in _DEFINITION_ORDER],
        )
        self._result_browser = FileBrowser(
            "Measurement Result", results_dir(), recursive=True
        )
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
        self._prompt.freerunSingle.connect(self._on_freerun_single)
        self._prompt.freerunContinue.connect(self._on_freerun_continue)

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

        self._settings_box = QGroupBox(f"Settings — {_DISPLAY_NAME['measure_filter']}")
        self._settings_box.setProperty("role", "interactive")
        self._settings_box_layout = QVBoxLayout(self._settings_box)
        self._settings_type: type = FilterSettings
        self._form = SettingsForm(FilterSettings())
        self._form.changed.connect(self._refresh_preview)

        dev_row = QHBoxLayout()
        dev_label = QLabel("Device:")
        dev_label.setProperty("role", "interactive")
        self._device_combo = QComboBox()
        self._device_combo.setProperty("role", "interactive")
        dev_refresh = QPushButton("↻")
        dev_refresh.setProperty("role", "interactive")
        dev_refresh.setFixedWidth(32)
        dev_refresh.clicked.connect(self._populate_devices)
        dev_row.addWidget(dev_label)
        dev_row.addWidget(self._device_combo, 1)
        dev_row.addWidget(dev_refresh)

        self._settings_box_layout.addWidget(self._form)
        self._settings_box_layout.addLayout(dev_row)
        self._populate_devices()

        # read-only digital-output configuration (defined by the measurement)
        self._digital_out_box = QGroupBox("Digital out (measurement-defined)")
        self._digital_out_box.setProperty("role", "viewer")
        self._digital_out_form = QFormLayout(self._digital_out_box)
        self._update_digital_out("measure_filter")

        self._preview_box = QGroupBox("Preview — applied waveform + trigger")
        self._preview_box.setProperty("role", "viewer")
        pv = QVBoxLayout(self._preview_box)
        self._preview = WaveformPreview()
        pv.addWidget(self._preview)

        terminal_box = QGroupBox("Terminal output")
        terminal_box.setProperty("role", "viewer")
        tv = QVBoxLayout(terminal_box)
        self._terminal = TerminalOutput()
        tv.addWidget(self._terminal)

        layout.addWidget(self._settings_box)
        layout.addWidget(self._digital_out_box)
        layout.addWidget(self._preview_box)
        layout.addWidget(terminal_box, 1)
        self._refresh_preview()
        return col

    def _update_digital_out(self, key: str) -> None:
        """Show the measurement's read-only digital-output configuration."""
        while self._digital_out_form.rowCount():
            self._digital_out_form.removeRow(0)
        for label, value in digital_out_for(key).items():
            value_label = QLabel(value)
            value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._digital_out_form.addRow(f"{label}:", value_label)

    # ---- devices -----------------------------------------------------------
    def _populate_devices(self) -> None:
        """Fill the device selector with attached devices + a simulated option."""
        self._device_combo.clear()
        devices = sorted(enumerate_devices(force_mock=False), key=_device_priority)
        for dev in devices:
            label = f"{dev.get('name', 'Analog Discovery')} — {dev.get('serial', '?')}"
            self._device_combo.addItem(label, ("real", dev.get("serial")))
        self._device_combo.addItem("Simulated device (no hardware)", ("mock", None))
        # index 0 is the preferred attached device (AD3 first), or simulated if none
        self._device_combo.setCurrentIndex(0)

    # ---- layout ------------------------------------------------------------
    def _toggle_files(self) -> None:
        show = not self._left.isVisible()
        self._left.setVisible(show)
        self._toggle_files_btn.setText("❮ Hide files" if show else "❯ Show files")

    # ---- measurement selection / source view ------------------------------
    def _choose_measurement(self, key: str) -> None:
        entry = _MEASUREMENTS.get(key)
        if entry is None:
            self._run_fn = None
            self._start_btn.setEnabled(False)
            self._status.setText(f"{key} is not available yet.")
            return
        run_fn, settings_type = entry
        self._run_fn = run_fn
        self._apply_settings_type(settings_type, key)
        self._start_btn.setEnabled(self._worker is None)
        self._status.setText(
            f"Selected {_DISPLAY_NAME.get(key, key)}. Adjust settings and press Start."
        )

    def _apply_settings_type(
        self, settings_type: type, key: str, settings: Any = None
    ) -> None:
        """Rebuild the settings form for a measurement (and optionally fill it)."""
        if settings_type is not self._settings_type:
            self._rebuild_form(settings_type)
            self._settings_box.setTitle(f"Settings — {_DISPLAY_NAME.get(key, key)}")
        self._scope.set_channels(*channels_for(key))  # measurement-aware plots
        self._update_digital_out(key)
        if settings is not None:
            self._form.set_settings(settings)
        self._refresh_preview()

    def _rebuild_form(self, settings_type: type) -> None:
        self._form.changed.disconnect(self._refresh_preview)
        self._settings_box_layout.removeWidget(self._form)
        self._form.setParent(None)  # remove from view immediately, not just the layout
        self._form.deleteLater()
        self._form = SettingsForm(settings_type())
        self._form.changed.connect(self._refresh_preview)
        self._settings_box_layout.insertWidget(0, self._form)
        self._settings_type = settings_type

    def _show_definition_code(self, key: str) -> None:
        self._choose_measurement(key)
        source = _SOURCE_FILE.get(key)
        if source is None:
            return
        self._code_viewer.show_file(str(source), kind="Definition")
        self._center_stack.setCurrentWidget(self._code_viewer)

    def _show_result_json(self, path: str) -> None:
        self._code_viewer.show_file(path, kind="Result")
        self._center_stack.setCurrentWidget(self._code_viewer)

    def _hide_definition_code(self) -> None:
        self._center_stack.setCurrentWidget(self._scope)

    # ---- settings load / preview ------------------------------------------
    def _load_settings_file(self, path: str) -> None:
        try:
            measurement, settings, _ = settings_io.load(path)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Load failed", f"Could not load settings:\n{exc}")
            return
        entry = _MEASUREMENTS.get(measurement or "")
        if entry is not None:
            self._run_fn = entry[0]
            self._apply_settings_type(entry[1], measurement, settings)
            self._start_btn.setEnabled(self._worker is None)
        else:
            self._form.set_settings(settings)
        self._terminal.append_line(f"Loaded settings from {Path(path).name}")

    def _refresh_preview(self) -> None:
        try:
            s = self._form.get_settings()
        except (ValueError, TypeError):
            return  # mid-edit; ignore until fields are valid
        # only measurements that drive an excitation waveform have a preview
        amplitude = getattr(s, "amplitude", None)
        f_square = getattr(s, "f_square", None)
        if f_square is None and hasattr(s, "f_sample") and hasattr(s, "buffer_size"):
            f_square = s.f_sample / (s.buffer_size * 10)  # derived (e.g. resistance)
        if amplitude is None or f_square is None:
            self._preview_box.setVisible(False)
            return
        trigger_level = getattr(s, "trigger_level", 0.4)
        trigger_slope = getattr(s, "trigger_slope", "rising")
        self._preview.update_preview(
            f_square, amplitude,
            trigger_level=trigger_level, trigger_slope=trigger_slope,
        )
        self._preview_box.setVisible(True)

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
        self._gate.freerunRequested.connect(self._prompt.ask_freerun)
        self._gate.freerunEnded.connect(self._prompt.reset)

        kind, serial = self._device_combo.currentData() or ("mock", None)
        self._worker = MeasurementWorker(
            self._run_fn, s, self._reporter, self._gate,
            force_mock=(kind == "mock"), serial=serial,
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

    def _on_freerun_single(self) -> None:
        if self._gate is not None:
            self._gate.freerun_toggle_freeze()

    def _on_freerun_continue(self) -> None:
        if self._gate is not None:
            self._gate.freerun_continue()

    # ---- worker callbacks --------------------------------------------------
    def _on_result(self, row: dict[str, Any]) -> None:
        # each measurement already logs a detailed per-pin line to the terminal;
        # this hook is kept for future per-result UI (e.g. a live results table).
        pass

    def _on_done(self, df: Any) -> None:
        self._status.setText(f"Done — {len(df)} rows.")
        self._prompt.reset()
        self._result_browser.refresh()

    def _on_failed(self, tb: str) -> None:
        self._status.setText("Measurement failed.")
        self._terminal.append_line(tb)
        last = tb.strip().splitlines()[-1] if tb.strip() else "Measurement failed."
        msg = last
        if "ERC: 3" in tb or "being used by another application" in tb:
            msg = (
                "The selected device is in use by another application.\n\n"
                "Close the WaveForms desktop app (or any program using the "
                "device), then Refresh and try again — or pick "
                "'Simulated device (no hardware)' to run without hardware.\n\n"
                f"{last}"
            )
        QMessageBox.critical(self, "Measurement failed", msg)

    def _cleanup_worker(self) -> None:
        self._start_btn.setEnabled(self._run_fn is not None)
        self._stop_btn.setEnabled(False)
        self._worker = None
        self._reporter = None
        self._gate = None
