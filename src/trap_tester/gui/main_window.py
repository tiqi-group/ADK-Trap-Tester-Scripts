"""Main window: the panel-selector menu bar plus a stacked panel view.

The current panel's selector is shown in bold, matching the mock's top bar.
F1, or the "? Help" button at the right end of the bar, opens the Manual at the
chapter about the panel being looked at.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trap_tester.gui import theme

from trap_tester.gui.panels.analysis_panel import AnalysisPanel
from trap_tester.gui.panels.device_panel import DevicePanel
from trap_tester.gui.panels.interfaces_panel import InterfacesPanel
from trap_tester.gui.panels.manual_panel import ManualPanel
from trap_tester.gui.panels.measurement_panel import MeasurementPanel
from trap_tester.gui.panels.placeholder import PlaceholderPanel
from trap_tester.gui.panels.selftest_panel import SelfTestPanel
from trap_tester.gui.panels.settings_panel import SettingsPanel

_PANELS = [
    ("Measurement", None),
    ("Analysis", None),
    ("Interfaces", None),
    ("Device Info", None),
    ("Self-Test", None),
    ("Settings", None),
    ("Manual", None),
]

# Panel -> the manual chapter (``core.manual.CHAPTERS`` key) that F1 opens.
_HELP_TOPICS = {
    "Measurement": "measurement",
    "Analysis": "analysis",
    "Interfaces": "interfaces",
    "Device Info": "device",
    "Self-Test": "selftest",
    "Settings": "settings",
}


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

        # Live panels; the rest are placeholders for later milestones.
        live = {
            "Measurement": MeasurementPanel,
            "Analysis": AnalysisPanel,
            "Interfaces": InterfacesPanel,
            "Device Info": DevicePanel,
            "Self-Test": SelfTestPanel,
            "Settings": SettingsPanel,
            "Manual": ManualPanel,
        }
        self._panels: dict[str, QWidget] = {}
        for name, note in _PANELS:
            factory = live.get(name)
            widget = factory() if factory else PlaceholderPanel(name, note or "")
            self._panels[name] = widget
            self._stack.addWidget(widget)

        # When settings change, re-read paths/folders in the panels that use them.
        settings = self._panels.get("Settings")
        if isinstance(settings, SettingsPanel):
            settings.changed.connect(self._on_settings_changed)
            settings.themeChanged.connect(self._on_theme_changed)

        help_key = QShortcut(QKeySequence.StandardKey.HelpContents, self)  # F1
        help_key.activated.connect(self.show_help)

        self._select(0)

    def show_help(self) -> None:
        """Open the manual at the chapter for the current panel (F1)."""
        names = [name for name, _ in _PANELS]
        current = names[self._stack.currentIndex()]
        manual_panel = self._panels.get("Manual")
        if current == "Manual" or not isinstance(manual_panel, ManualPanel):
            return
        manual_panel.show_topic(_HELP_TOPICS.get(current, "start"))
        self._select(names.index("Manual"))

    def _on_settings_changed(self) -> None:
        """Refresh panels that read configurable paths / layout folders."""
        for name in ("Measurement", "Analysis", "Interfaces"):
            panel = self._panels.get(name)
            reload_fn = getattr(panel, "reload_settings", None)
            if callable(reload_fn):
                reload_fn()

    def _on_theme_changed(self, name: str) -> None:
        """Apply a light/dark switch live: stylesheet + every matplotlib canvas."""
        app = QApplication.instance()
        if app is not None:
            theme.apply(app, name)  # active theme + stylesheet + rcParams
        for widget in self.findChildren(QWidget):
            apply_fn = getattr(widget, "apply_theme", None)
            if callable(apply_fn):
                apply_fn()

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
            if name == "Manual":
                btn.setToolTip("The manual. Press F1 on any panel to open its chapter.")
            btn.clicked.connect(lambda _=False, idx=i: self._select(idx))
            group.addButton(btn, i)
            self._buttons.append(btn)
            row.addWidget(btn)
        row.addStretch(1)
        # Not a panel selector: not checkable, not in the group.
        self._help_btn = QPushButton("? Help")
        self._help_btn.setProperty("role", "menu")
        self._help_btn.setToolTip("Open the manual at this panel's chapter (F1)")
        self._help_btn.clicked.connect(self.show_help)
        row.addWidget(self._help_btn)
        return bar

    def _select(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        # on the Manual itself there is no other chapter to jump to
        self._help_btn.setEnabled(_PANELS[index][0] != "Manual")
        for i, btn in enumerate(self._buttons):
            btn.setChecked(i == index)
            font = btn.font()
            font.setBold(i == index)
            btn.setFont(font)
