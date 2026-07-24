"""A titled list, with a refresh button.

Lists the files in a directory (``directory`` + ``pattern``), or, when
``entries`` is given, a fixed set of ``(label, data)`` rows — used for the
measurement-definition list, which shows friendly names rather than filenames.
"""

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

    def __init__(
        self,
        title: str,
        directory: str | Path | None = None,
        pattern: str = "*.json",
        entries: list[tuple[str, str]] | None = None,
        recursive: bool = False,
    ) -> None:
        super().__init__()
        self._dir = Path(directory) if directory is not None else None
        self._pattern = pattern
        self._entries = entries
        self._recursive = recursive

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

    def set_directory(self, directory: str | Path) -> None:
        """Point the browser at a different folder and re-list it."""
        self._dir = Path(directory)
        self.refresh()

    def refresh(self) -> None:
        self._list.clear()
        if self._entries is not None:
            for label, data in self._entries:
                item = QListWidgetItem(label)
                item.setData(256, data)  # Qt.UserRole == 256
                self._list.addItem(item)
            return
        if self._dir is None or not self._dir.exists():
            return
        # Recursive browsers descend into sub-folders and show the path relative
        # to the root so files with the same name in different folders stay
        # distinct; flat browsers show the bare file name.
        matches = self._dir.rglob(self._pattern) if self._recursive \
            else self._dir.glob(self._pattern)
        for path in sorted(matches, reverse=True):
            label = str(path.relative_to(self._dir)) if self._recursive else path.name
            item = QListWidgetItem(label)
            item.setData(256, str(path.resolve()))  # Qt.UserRole == 256
            self._list.addItem(item)
