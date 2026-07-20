"""Read-only text viewer shown over the plot area (measurement definition or result)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class CodeViewer(QWidget):
    """Displays a measurement definition ``.py`` file; emits ``closed`` to dismiss."""

    closed = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        header = QHBoxLayout()
        self._title = QLabel("")
        self._title.setProperty("role", "interactive")
        close_btn = QPushButton("✕ Close")
        close_btn.setProperty("role", "interactive")
        close_btn.clicked.connect(self.closed)
        header.addWidget(self._title, 1)
        header.addWidget(close_btn)

        self._editor = QPlainTextEdit()
        self._editor.setReadOnly(True)
        self._editor.setProperty("role", "viewer")
        self._editor.setFont(QFont("monospace", 10))
        self._editor.setLineWrapMode(QPlainTextEdit.NoWrap)

        layout.addLayout(header)
        layout.addWidget(self._editor, 1)

    def show_file(self, path: str, kind: str = "") -> None:
        p = Path(path)
        self._title.setText(f"{kind}: {p.name}" if kind else p.name)
        try:
            self._editor.setPlainText(p.read_text())
        except OSError as exc:
            self._editor.setPlainText(f"Could not read {p}:\n{exc}")
