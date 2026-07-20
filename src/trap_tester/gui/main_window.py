"""Main window: the panel-selector menu bar plus a stacked panel view.

The current panel's selector is shown in bold, matching the mock's top bar.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trap_tester.gui.panels.measurement_panel import MeasurementPanel
from trap_tester.gui.panels.placeholder import PlaceholderPanel

_PANELS = [
    ("Measurement", None),
    ("Analysis", "Analyse a saved measurement and generate a report. (Milestone 2)"),
    ("Device Info", "Inspect attached Analog Discovery devices. (Milestone 3)"),
    ("Self-Test", "Verify the WaveForms install and the analog frontend. (Milestone 4)"),
]


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Trap Tester")
        self.resize(1280, 800)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        self._buttons: list[QPushButton] = []
        layout.addWidget(self._build_menu_bar())
        layout.addWidget(self._stack, 1)

        # Measurement is the only live panel in milestone 1.
        self._stack.addWidget(MeasurementPanel())
        for name, note in _PANELS[1:]:
            self._stack.addWidget(PlaceholderPanel(name, note or ""))

        self._select(0)

    def _build_menu_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("menuBar")
        row = QHBoxLayout(bar)
        row.setContentsMargins(8, 4, 8, 4)
        group = QButtonGroup(self)
        group.setExclusive(True)
        for i, (name, _) in enumerate(_PANELS):
            btn = QPushButton(name)
            btn.setCheckable(True)
            btn.setProperty("role", "menu")
            btn.clicked.connect(lambda _=False, idx=i: self._select(idx))
            group.addButton(btn, i)
            self._buttons.append(btn)
            row.addWidget(btn)
        row.addStretch(1)
        return bar

    def _select(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
            font = btn.font()
            font.setBold(i == index)
            btn.setFont(font)
