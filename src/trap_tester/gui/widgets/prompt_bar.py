"""The interactive gate area — the mock's "Continue / Confirm Button".

Shows the current prompt and the buttons appropriate to it: a retake question
offers Retake / Accept; a continue prompt offers a single Continue button; a
free-run (no-trigger) session offers Single (freeze/resume) + Continue.
Hidden while a measurement runs unattended.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PromptBar(QWidget):
    confirmed = Signal(bool)  # True = retake, False = accept
    continued = Signal()
    freerunSingle = Signal()  # "Single": freeze one frame / resume live
    freerunContinue = Signal()  # end free-run (point will be skipped)

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
        self._single = QPushButton("Single (freeze)")
        self._freerun_continue = QPushButton("Continue → skip point")
        self._buttons = (
            self._retake, self._accept, self._continue,
            self._single, self._freerun_continue,
        )
        for b in self._buttons:
            b.setProperty("role", "interactive")
            row.addWidget(b)

        outer.addWidget(self._label)
        outer.addLayout(row)

        self._retake.clicked.connect(lambda: self._resolve_confirm(True))
        self._accept.clicked.connect(lambda: self._resolve_confirm(False))
        self._continue.clicked.connect(self._resolve_continue)
        self._single.clicked.connect(self._on_single)
        self._freerun_continue.clicked.connect(self._resolve_freerun_continue)
        self.reset()

    def reset(self) -> None:
        self._label.setText("Idle.")
        self._frozen = False
        self._single.setText("Single (freeze)")
        for b in self._buttons:
            b.setVisible(False)

    def _show_only(self, *visible: QPushButton) -> None:
        for b in self._buttons:
            b.setVisible(b in visible)

    def ask_confirm(self, prompt: str) -> None:
        self._label.setText(prompt)
        self._show_only(self._retake, self._accept)

    def ask_continue(self, prompt: str) -> None:
        self._label.setText(prompt)
        self._show_only(self._continue)

    def ask_freerun(self, prompt: str) -> None:
        self._frozen = False
        self._single.setText("Single (freeze)")
        self._label.setText(prompt)
        self._show_only(self._single, self._freerun_continue)

    def _resolve_confirm(self, retake: bool) -> None:
        self.reset()
        self.confirmed.emit(retake)

    def _resolve_continue(self) -> None:
        self.reset()
        self.continued.emit()

    def _on_single(self) -> None:
        # toggle the label to reflect frozen/live; the worker owns the real state
        self._frozen = not self._frozen
        self._single.setText("Resume (live)" if self._frozen else "Single (freeze)")
        self.freerunSingle.emit()

    def _resolve_freerun_continue(self) -> None:
        self.reset()
        self.freerunContinue.emit()
