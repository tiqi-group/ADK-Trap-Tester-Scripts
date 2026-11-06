"""Main window: the panel-selector menu bar plus a stacked panel view.

The current panel's selector is shown in bold, matching the mock's top bar.
F1, or the "? Help" button at the right end of the bar, opens the Manual at the
chapter about the panel being looked at.

The window also carries the session (see :mod:`trap_tester.core.session`): on
close it saves its geometry, the selected panel, every named splitter and each
panel's own ``session_state()``; on start it hands them back through
``restore_session()``. A panel that fails to restore is logged and skipped, so a
stale session can never stop the app from opening.
"""

from __future__ import annotations

import sys
import traceback
from typing import Any

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core import session
from trap_tester.core.appconfig import restore_session
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


# The window's own entry in the session (panel entries are keyed by panel name).
_WINDOW_KEY = "_window"


class MainWindow(QMainWindow):
    def __init__(self, persist_session: bool = True) -> None:
        """``persist_session=False`` neither restores nor saves the session
        (the frozen-bundle smoke test must not touch the operator's state)."""
        super().__init__()
        self._persist_session = persist_session
        self._skip_session_save = False
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
            settings.sessionForgotten.connect(self._on_session_forgotten)

        help_key = QShortcut(QKeySequence.StandardKey.HelpContents, self)  # F1
        help_key.activated.connect(self.show_help)

        self._select(0)
        if self._persist_session and restore_session():
            self.restore_session(session.load())

    # ---- session -----------------------------------------------------------
    def session_state(self) -> dict[str, Any]:
        """Everything the next start should get back (JSON-serialisable)."""
        names = [name for name, _ in _PANELS]
        state: dict[str, Any] = {
            _WINDOW_KEY: {
                "geometry": _encode(self.saveGeometry()),
                "panel": names[self._stack.currentIndex()],
                "splitters": {
                    key: _encode(splitter.saveState())
                    for key, splitter in self._named_splitters().items()
                },
            }
        }
        for name, panel in self._panels.items():
            save_fn = getattr(panel, "session_state", None)
            if not callable(save_fn):
                continue
            try:
                state[name] = save_fn()
            except Exception:  # noqa: BLE001 — never lose the rest of the session
                _warn(f"could not save the {name} panel's session state")
        return state

    def restore_session(self, state: dict[str, Any]) -> None:
        """Re-apply a saved :meth:`session_state` (missing parts keep defaults)."""
        for name, panel in self._panels.items():
            restore_fn = getattr(panel, "restore_session", None)
            entry = state.get(name)
            if callable(restore_fn) and isinstance(entry, dict):
                try:
                    restore_fn(entry)
                except Exception:  # noqa: BLE001 — a stale entry must not block start
                    _warn(f"could not restore the {name} panel's session state")
        # after the panels, so a panel showing/hiding a pane cannot undo the sizes
        window = session.section(state, _WINDOW_KEY)
        splitters = session.section(window, "splitters")
        for key, splitter in self._named_splitters().items():
            data = _decode(splitters.get(key))
            if data is not None:
                splitter.restoreState(data)
        geometry = _decode(window.get("geometry"))
        if geometry is not None:
            self.restoreGeometry(geometry)
        names = [name for name, _ in _PANELS]
        if window.get("panel") in names:
            self._select(names.index(window["panel"]))

    def _named_splitters(self) -> dict[str, QSplitter]:
        """``"Panel/objectName" -> splitter`` for every splitter a panel named.

        Only named ones: an unnamed splitter's position in ``findChildren`` would
        shift whenever a panel's layout changes, restoring sizes onto the wrong one.
        """
        out: dict[str, QSplitter] = {}
        for name, panel in self._panels.items():
            for splitter in panel.findChildren(QSplitter):
                if splitter.objectName():
                    out[f"{name}/{splitter.objectName()}"] = splitter
        return out

    def _on_session_forgotten(self) -> None:
        """The saved session was cleared: don't write this one back on exit."""
        self._skip_session_save = True

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 — Qt override
        if (
            self._persist_session
            and not self._skip_session_save
            and restore_session()
        ):
            try:
                session.save(self.session_state())
            except OSError:
                _warn("could not write the session file")
        super().closeEvent(event)

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


def _encode(data: QByteArray) -> str:
    return bytes(data.toBase64()).decode("ascii")


def _decode(text: Any) -> QByteArray | None:
    if not isinstance(text, str) or not text:
        return None
    return QByteArray.fromBase64(text.encode("ascii"))


def _warn(message: str) -> None:
    """Log a session problem with its traceback (no console in a windowed build)."""
    stream = sys.stderr or sys.stdout
    if stream is not None:
        print(f"trap-tester: {message}", file=stream)
        traceback.print_exc(file=stream)
