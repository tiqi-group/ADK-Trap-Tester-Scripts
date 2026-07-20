"""The Device Info panel (mock page 3): two columns.

Left  — Device List (green, interactive) with Refresh + a Simulate toggle.
Right — Device Info viewer (red): the selected device's ID / serial, type, etc.

Stepping stone toward multi-device matrix measurements: enumerates every
attached Analog Discovery via :func:`core.device.enumerate_devices`.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.device import enumerate_devices

# fields shown in the info viewer, in order: (dict key, label)
_INFO_FIELDS = [
    ("name", "Name"),
    ("serial", "Device ID / Serial"),
    ("type", "Device Type"),
    ("id", "Device ID"),
    ("revision", "Revision"),
    ("user_name", "User name"),
    ("index", "Enumeration index"),
]


class DevicePanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._devices: list[dict[str, Any]] = []

        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_list())
        splitter.addWidget(self._build_info())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 720])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.refresh()

    # ---- columns -----------------------------------------------------------
    def _build_list(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(240)
        layout = QVBoxLayout(col)

        header = QLabel("Device List")
        header.setProperty("role", "interactive")
        self._list = QListWidget()
        self._list.setProperty("role", "interactive")
        self._list.currentRowChanged.connect(self._show_selected)

        self._refresh_btn = QPushButton("↻ Refresh")
        self._refresh_btn.setProperty("role", "interactive")
        self._refresh_btn.clicked.connect(self.refresh)
        self._sim_checkbox = QCheckBox("Simulate (no hardware)")
        self._sim_checkbox.setChecked(False)  # show attached devices by default
        self._sim_checkbox.setProperty("role", "interactive")
        self._sim_checkbox.toggled.connect(self.refresh)

        layout.addWidget(header)
        layout.addWidget(self._list, 1)
        layout.addWidget(self._refresh_btn)
        layout.addWidget(self._sim_checkbox)
        return col

    def _build_info(self) -> QWidget:
        box = QGroupBox("Device Info")
        box.setProperty("role", "viewer")
        outer = QVBoxLayout(box)
        self._form = QFormLayout()
        self._value_labels: dict[str, QLabel] = {}
        for key, label in _INFO_FIELDS:
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._value_labels[key] = value
            self._form.addRow(f"{label}:", value)
        outer.addLayout(self._form)
        outer.addStretch(1)

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.addWidget(box)
        return wrapper

    # ---- data --------------------------------------------------------------
    def refresh(self) -> None:
        self._devices = enumerate_devices(force_mock=self._sim_checkbox.isChecked())
        self._list.clear()
        for dev in self._devices:
            name = dev.get("name", "Analog Discovery")
            serial = dev.get("serial", "?")
            suffix = " (simulated)" if dev.get("simulated") else ""
            item = QListWidgetItem(f"{name} — {serial}{suffix}")
            self._list.addItem(item)
        if self._devices:
            self._list.setCurrentRow(0)
        else:
            self._list.addItem(QListWidgetItem("No devices found"))
            self._clear_info()

    def _show_selected(self, row: int) -> None:
        if not (0 <= row < len(self._devices)):
            self._clear_info()
            return
        dev = self._devices[row]
        for key, value_label in self._value_labels.items():
            value_label.setText(str(dev.get(key, "—")))

    def _clear_info(self) -> None:
        for value_label in self._value_labels.values():
            value_label.setText("—")
