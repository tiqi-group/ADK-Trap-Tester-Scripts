"""A settings form generated from a dataclass instance.

Introspects the fields of a :class:`FilterSettings` (or similar) and builds a
labelled input per field. Provides :meth:`get_settings` / :meth:`set_settings`.

Field metadata drives the rendering:

* ``choices=[...]`` -> a drop-down (``QComboBox``) instead of a text field;
* ``category="..."`` -> the field is grouped under a bold section header. Fields
  sharing a category are shown together, in first-seen order. When no field
  declares a category the form is a single flat section (no headers).
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)


class SettingsForm(QWidget):
    changed = Signal()

    def __init__(self, settings: Any) -> None:
        super().__init__()
        if not is_dataclass(settings):
            raise TypeError("settings must be a dataclass instance")
        self._type = type(settings)
        self._editors: dict[str, QWidget] = {}
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._build(settings)

    def _build(self, settings: Any) -> None:
        # group fields by their category metadata, preserving first-seen order
        groups: dict[Any, list] = {}
        order: list[Any] = []
        for f in fields(settings):
            cat = f.metadata.get("category")
            if cat not in groups:
                groups[cat] = []
                order.append(cat)
            groups[cat].append(f)

        show_headers = order != [None]  # skip the header for an uncategorised form
        for cat in order:
            if show_headers:
                header = QLabel(cat if cat else "General")
                header.setProperty("role", "section")
                self._outer.addWidget(header)
            form = QFormLayout()
            for f in groups[cat]:
                form.addRow(f.name.replace("_", " "), self._make_editor(settings, f))
            self._outer.addLayout(form)

    def _make_editor(self, settings: Any, f: Any) -> QWidget:
        value = getattr(settings, f.name)
        choices = f.metadata.get("choices")
        if choices:
            editor: QWidget = QComboBox()
            editor.addItems([str(c) for c in choices])
            editor.setCurrentText(str(value))
            editor.currentTextChanged.connect(self.changed)
        elif isinstance(value, bool):
            editor = QCheckBox()
            editor.setChecked(value)
            editor.toggled.connect(self.changed)
        else:
            editor = QLineEdit(self._to_text(value))
            editor.editingFinished.connect(self.changed)
        editor.setProperty("role", "interactive")
        self._editors[f.name] = editor
        return editor

    @staticmethod
    def _to_text(value: Any) -> str:
        if isinstance(value, (list, tuple)):
            return ", ".join(str(v) for v in value)
        return str(value)

    def _coerce(self, name: str, raw: Any) -> Any:
        """Coerce the editor's value to the dataclass field's type."""
        default = getattr(self._type(), name)
        if isinstance(default, bool):
            return bool(raw)
        if isinstance(default, list):
            text = str(raw).strip()
            if not text:
                return []
            return [int(x) for x in text.replace(" ", "").split(",") if x]
        if isinstance(default, int) and not isinstance(default, bool):
            return int(float(raw))
        if isinstance(default, float):
            return float(raw)
        return str(raw)

    def get_settings(self) -> Any:
        kwargs = {}
        for name, editor in self._editors.items():
            if isinstance(editor, QComboBox):
                raw: Any = editor.currentText()
            elif isinstance(editor, QCheckBox):
                raw = editor.isChecked()
            else:
                raw = editor.text()
            kwargs[name] = self._coerce(name, raw)
        return self._type(**kwargs)

    def set_settings(self, settings: Any) -> None:
        for f in fields(settings):
            editor = self._editors.get(f.name)
            if editor is None:
                continue
            value = getattr(settings, f.name)
            if isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QLineEdit):
                editor.setText(self._to_text(value))
        self.changed.emit()
