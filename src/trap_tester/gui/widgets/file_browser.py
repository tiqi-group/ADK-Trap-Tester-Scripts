"""A titled list of files in a directory, with a refresh button."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class FileBrowser(QWidget):
    selected = Signal(str)  # single click — choose
    opened = Signal(str)  # double click / Enter — open

    def __init__(self, title: str, directory: str | Path, pattern: str = "*.json") -> None:
        super().__init__()
        self._dir = Path(directory)
        self._pattern = pattern

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)

        header = QLabel(title)
        header.setProperty("role", "interactive")
        header.setWordWrap(True)
        self._list = QListWidget()
        self._list.setProperty("role", "interactive")
        refresh = QPushButton("↻ Refresh")
        refresh.setProperty("role", "interactive")

        layout.addWidget(header)
        layout.addWidget(self._list, 1)
        layout.addWidget(refresh)

        refresh.clicked.connect(self.refresh)
        self._list.itemClicked.connect(lambda it: self.selected.emit(it.data(256)))
        self._list.itemDoubleClicked.connect(lambda it: self.opened.emit(it.data(256)))
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        if not self._dir.exists():
            return
        for path in sorted(self._dir.glob(self._pattern), reverse=True):
            item = QListWidgetItem(path.name)
            item.setData(256, str(path.resolve()))  # Qt.UserRole == 256
            self._list.addItem(item)
