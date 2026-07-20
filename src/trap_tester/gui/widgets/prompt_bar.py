"""The interactive gate area — the mock's "Continue / Confirm Button".

Shows the current prompt and the buttons appropriate to it: a retake question
offers Retake / Accept; a continue prompt offers a single Continue button.
Hidden while a measurement runs unattended.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PromptBar(QWidget):
    confirmed = Signal(bool)  # True = retake, False = accept
    continued = Signal()

    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(2, 2, 2, 2)

        self._label = QLabel("")
        self._label.setProperty("role", "viewer")
        self._label.setWordWrap(True)

        row = QHBoxLayout()
        self._retake = QPushButton("Retake")
        self._accept = QPushButton("Accept && Continue")
        self._continue = QPushButton("Continue")
        for b in (self._retake, self._accept, self._continue):
            b.setProperty("role", "interactive")
            row.addWidget(b)

        outer.addWidget(self._label)
        outer.addLayout(row)

        self._retake.clicked.connect(lambda: self._resolve_confirm(True))
        self._accept.clicked.connect(lambda: self._resolve_confirm(False))
        self._continue.clicked.connect(self._resolve_continue)
        self.reset()

    def reset(self) -> None:
        self._label.setText("Idle.")
        for b in (self._retake, self._accept, self._continue):
            b.setVisible(False)

    def ask_confirm(self, prompt: str) -> None:
        self._label.setText(prompt)
        self._retake.setVisible(True)
        self._accept.setVisible(True)
        self._continue.setVisible(False)

    def ask_continue(self, prompt: str) -> None:
        self._label.setText(prompt)
        self._retake.setVisible(False)
        self._accept.setVisible(False)
        self._continue.setVisible(True)

    def _resolve_confirm(self, retake: bool) -> None:
        self.reset()
        self.confirmed.emit(retake)

    def _resolve_continue(self) -> None:
        self.reset()
        self.continued.emit()
