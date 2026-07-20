"""A settings form generated from a dataclass instance.

Introspects the fields of a :class:`FilterSettings` (or similar) and builds a
labelled input per field. Provides :meth:`get_settings` / :meth:`set_settings`.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLineEdit,
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
        self._form = QFormLayout(self)
        self._build(settings)

    def _build(self, settings: Any) -> None:
        for f in fields(settings):
            value = getattr(settings, f.name)
            label = f.name.replace("_", " ")
            if isinstance(value, bool):
                editor: QWidget = QCheckBox()
                editor.setChecked(value)
                editor.toggled.connect(self.changed)
            else:
                editor = QLineEdit(self._to_text(value))
                editor.editingFinished.connect(self.changed)
            editor.setProperty("role", "interactive")
            self._editors[f.name] = editor
            self._form.addRow(label, editor)

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
            raw = editor.isChecked() if isinstance(editor, QCheckBox) else editor.text()
            kwargs[name] = self._coerce(name, raw)
        return self._type(**kwargs)

    def set_settings(self, settings: Any) -> None:
        for f in fields(settings):
            editor = self._editors.get(f.name)
            if editor is None:
                continue
            value = getattr(settings, f.name)
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QLineEdit):
                editor.setText(self._to_text(value))
        self.changed.emit()
