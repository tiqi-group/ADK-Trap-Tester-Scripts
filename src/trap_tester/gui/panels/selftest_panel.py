"""The Self-Test panel (mock page 4): three columns.

Left   — the test selector (green), the frontend-test settings (green), the
         device selector and Run / Stop.
Center — status (red) over the loopback-correlation plot (red).
Right  — terminal output (red).

Two self-tests (see ``core.selftest``): the WaveForms install check (no
hardware, runs inline) and the frontend loopback correlation sweep (runs on the
measurement worker thread against the selected device / the mock).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.device import enumerate_devices
from trap_tester.core.selftest import (
    SelfTestSettings,
    check_waveform_install,
    run_frontend_selftest,
)
from trap_tester.gui.panels.measurement_panel import _device_priority
from trap_tester.gui.widgets.scope_canvas import ChannelSpec, ScopeCanvas
from trap_tester.gui.widgets.settings_form import SettingsForm
from trap_tester.gui.widgets.terminal_output import TerminalOutput
from trap_tester.gui.widgets.waveforms_banner import WaveformsBanner
from trap_tester.gui.worker import MeasurementWorker, QtGate, QtReporter

_INSTALL = "install"
_FRONTEND = "frontend"
_TESTS = [
    (_INSTALL, "WaveForms install check"),
    (_FRONTEND, "Frontend loopback (correlation)"),
]

# Captured channels for the frontend loopback: the DAC-MUX drive looped back
# through the ADC-MUX. Both are voltages; the correlation of the two is what the
# test reports (streamed to the terminal), while the traces are shown here.
_SCOPE_CHANNELS = (
    ChannelSpec("DAC-MUX out", "V", 1.0, "#1f77b4"),
    ChannelSpec("ADC-MUX loopback", "V", 1.0, "#d62728"),
)


class SelfTestPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: MeasurementWorker | None = None
        self._reporter: QtReporter | None = None
        self._gate: QtGate | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_center())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 2)
        splitter.setSizes([280, 640, 360])
        outer.addWidget(splitter)

        self._tests.setCurrentRow(0)  # triggers _on_test_changed

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(260)
        layout = QVBoxLayout(col)

        header = QLabel("Self-tests")
        header.setProperty("role", "interactive")
        self._tests = QListWidget()
        self._tests.setProperty("role", "interactive")
        for key, label in _TESTS:
            item = QListWidgetItem(label)
            item.setData(256, key)  # Qt.UserRole
            self._tests.addItem(item)
        self._tests.currentRowChanged.connect(self._on_test_changed)

        self._settings_box = QGroupBox("Frontend test settings")
        self._settings_box.setProperty("role", "interactive")
        sb = QVBoxLayout(self._settings_box)
        self._form = SettingsForm(SelfTestSettings())
        sb.addWidget(self._form)

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

        controls = QHBoxLayout()
        self._run_btn = QPushButton("▶ Run test")
        self._run_btn.setProperty("role", "interactive")
        self._stop_btn = QPushButton("■ Stop")
        self._stop_btn.setProperty("role", "interactive")
        self._stop_btn.setEnabled(False)
        self._run_btn.clicked.connect(self._run)
        self._stop_btn.clicked.connect(self._stop)
        controls.addWidget(self._run_btn, 1)
        controls.addWidget(self._stop_btn)

        self._waveforms_banner = WaveformsBanner()

        self._device_box = QWidget()
        db = QVBoxLayout(self._device_box)
        db.setContentsMargins(0, 0, 0, 0)
        db.addWidget(self._waveforms_banner)
        db.addLayout(dev_row)

        layout.addWidget(header)
        layout.addWidget(self._tests, 1)
        layout.addWidget(self._settings_box)
        layout.addWidget(self._device_box)
        layout.addLayout(controls)
        self._populate_devices()
        return col

    def _build_center(self) -> QWidget:
        col = QWidget()
        layout = QVBoxLayout(col)
        self._status = QLabel("Status / Progress: idle")
        self._status.setProperty("role", "viewer")
        self._status.setAlignment(Qt.AlignCenter)
        self._scope = ScopeCanvas()
        self._scope.set_channels(*_SCOPE_CHANNELS)
        self._scope.show_message("Run a test to see the captured waveforms.")
        layout.addWidget(self._status)
        layout.addWidget(self._scope, 1)
        return col

    def _build_right(self) -> QWidget:
        box = QGroupBox("Terminal output")
        box.setProperty("role", "viewer")
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        v = QVBoxLayout(box)
        self._terminal = TerminalOutput()
        v.addWidget(self._terminal)
        wl.addWidget(box)
        return wrapper

    # ---- test selection ----------------------------------------------------
    def _current_test(self) -> str:
        item = self._tests.currentItem()
        return item.data(256) if item is not None else _INSTALL

    def _on_test_changed(self, _row: int) -> None:
        is_frontend = self._current_test() == _FRONTEND
        self._settings_box.setVisible(is_frontend)
        self._device_box.setVisible(is_frontend)

    # ---- devices -----------------------------------------------------------
    def _populate_devices(self) -> None:
        self._waveforms_banner.refresh()
        self._device_combo.clear()
        devices = sorted(enumerate_devices(force_mock=False), key=_device_priority)
        for dev in devices:
            label = f"{dev.get('name', 'Analog Discovery')} — {dev.get('serial', '?')}"
            self._device_combo.addItem(label, ("real", dev.get("serial")))
        self._device_combo.addItem("Simulated device (no hardware)", ("mock", None))
        self._device_combo.setCurrentIndex(0)

    # ---- run / stop --------------------------------------------------------
    def _run(self) -> None:
        if self._worker is not None:
            return
        if self._current_test() == _INSTALL:
            self._run_install_check()
        else:
            self._run_frontend()

    def _run_install_check(self) -> None:
        self._terminal.clear()
        self._status.setText("Checking WaveForms install…")
        self._scope.show_message("WaveForms install check — see terminal output.")
        result = check_waveform_install()
        for line in result.lines:
            self._terminal.append_line(line)
        self._status.setText(
            "Install OK." if result.ok else "Install incomplete — see terminal."
        )

    def _run_frontend(self) -> None:
        try:
            s = self._form.get_settings()
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "Invalid settings", str(exc))
            return

        self._terminal.clear()
        self._scope.set_channels(*_SCOPE_CHANNELS)
        self._scope.show_message("Waiting for the first capture…")
        self._reporter = QtReporter()
        self._gate = QtGate()
        self._reporter.statusChanged.connect(self._status.setText)
        self._reporter.logLine.connect(self._terminal.append_line)
        self._reporter.captured.connect(self._scope.update_capture)

        kind, serial = self._device_combo.currentData() or ("mock", None)
        self._worker = MeasurementWorker(
            run_frontend_selftest, s, self._reporter, self._gate,
            force_mock=(kind == "mock"), serial=serial,
        )
        self._worker.measurementDone.connect(self._on_done)
        self._worker.measurementFailed.connect(self._on_failed)
        self._worker.finished.connect(self._cleanup_worker)

        self._run_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._status.setText("Starting frontend self-test…")
        self._worker.start()

    def _stop(self) -> None:
        if self._worker is not None:
            self._status.setText("Cancelling…")
            self._worker.cancel()

    # ---- worker callbacks --------------------------------------------------
    def _on_done(self, df: Any) -> None:
        self._status.setText(f"Self-test done — {len(df)} pins tested.")

    def _on_failed(self, tb: str) -> None:
        self._status.setText("Self-test failed.")
        self._terminal.append_line(tb)
        last = tb.strip().splitlines()[-1] if tb.strip() else "Self-test failed."
        msg = last
        if "ERC: 3" in tb or "being used by another application" in tb:
            msg = (
                "The selected device is in use by another application.\n\n"
                "Close the WaveForms desktop app (or any program using the "
                "device), then Refresh and try again — or pick "
                "'Simulated device (no hardware)' to run without hardware.\n\n"
                f"{last}"
            )
        QMessageBox.critical(self, "Self-test failed", msg)

    def _cleanup_worker(self) -> None:
        self._run_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._worker = None
        self._reporter = None
        self._gate = None
