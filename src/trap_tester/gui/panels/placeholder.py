"""Placeholder panels for features arriving in later milestones."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class PlaceholderPanel(QWidget):
    def __init__(self, title: str, note: str) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        label = QLabel(f"<h2>{title}</h2><p>{note}</p>")
        label.setAlignment(Qt.AlignCenter)
        label.setWordWrap(True)
        label.setProperty("role", "viewer")
        layout.addWidget(label)
