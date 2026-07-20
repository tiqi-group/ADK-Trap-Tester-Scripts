"""Read-only terminal-output viewer (captures what used to be ``print``)."""

from __future__ import annotations

from PySide6.QtWidgets import QPlainTextEdit


class TerminalOutput(QPlainTextEdit):
    def __init__(self) -> None:
        super().__init__()
        self.setReadOnly(True)
        self.setProperty("role", "viewer")
        self.setMaximumBlockCount(5000)
        self.setPlaceholderText("Terminal output…")

    def append_line(self, text: str) -> None:
        self.appendPlainText(text)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
