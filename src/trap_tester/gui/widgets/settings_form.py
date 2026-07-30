"""A settings form generated from a dataclass instance.

Introspects the fields of a :class:`FilterSettings` (or similar) and builds a
labelled input per field. Provides :meth:`get_settings` / :meth:`set_settings`.

Field metadata drives the rendering:

* ``choices=[...]`` -> a drop-down (``QComboBox``) instead of a text field;
* ``category="..."`` -> the field is grouped under a bold section header. Fields
  sharing a category are shown together, in first-seen order. When no field
  declares a category the form is a single flat section (no headers);
* ``hidden=True`` -> the field gets no editor (it is structured data no text box
  could express, e.g. an analysis reference table). Its value is carried through
  :meth:`get_settings` unchanged, so whatever set it keeps owning it.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
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
        # fields with no editor: kept verbatim and handed back by get_settings
        self._hidden: dict[str, Any] = {}
        # for set_category_enabled: the widgets a whole section owns
        self._headers: dict[Any, QWidget] = {}
        self._rows: dict[str, tuple[QWidget | None, QWidget]] = {}
        self._category_of: dict[str, Any] = {}
        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._build(settings)

    def _build(self, settings: Any) -> None:
        # group fields by their category metadata, preserving first-seen order
        groups: dict[Any, list] = {}
        order: list[Any] = []
        for f in fields(settings):
            if f.metadata.get("hidden"):
                self._hidden[f.name] = getattr(settings, f.name)
                continue
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
                self._headers[cat] = header
            form = QFormLayout()
            for f in groups[cat]:
                editor = self._make_editor(settings, f)
                field_widget = self._with_unit(editor, f.metadata.get("unit"))
                form.addRow(f.name.replace("_", " "), field_widget)
                self._category_of[f.name] = cat
                self._rows[f.name] = (form.labelForField(field_widget), field_widget)
            self._outer.addLayout(form)

    # ---- enabling ----------------------------------------------------------
    def set_category_enabled(self, category: str, enabled: bool) -> None:
        """Grey out (or restore) a whole section — header, labels and editors.

        Used for criteria that only apply in a certain state, e.g. the reference
        tolerances, which mean nothing until a golden reference is loaded.
        """
        header = self._headers.get(category)
        if header is not None:
            header.setEnabled(enabled)
        for name, cat in self._category_of.items():
            if cat != category:
                continue
            label, field_widget = self._rows[name]
            if label is not None:
                label.setEnabled(enabled)
            field_widget.setEnabled(enabled)

    def set_category_tooltip(self, category: str, text: str) -> None:
        """Explain a section (typically why it is greyed out)."""
        header = self._headers.get(category)
        if header is not None:
            header.setToolTip(text)
        for name, cat in self._category_of.items():
            if cat == category:
                label, field_widget = self._rows[name]
                if label is not None:
                    label.setToolTip(text)
                field_widget.setToolTip(text)

    # ---- fields with no editor ---------------------------------------------
    def hidden(self, name: str) -> Any:
        """The current value of a ``hidden=True`` field."""
        return self._hidden.get(name)

    def set_hidden(self, name: str, value: Any) -> None:
        """Replace a ``hidden=True`` field's value (emits :data:`changed`)."""
        self._hidden[name] = value
        self.changed.emit()

    @staticmethod
    def _with_unit(editor: QWidget, unit: str | None) -> QWidget:
        """Pair ``editor`` with a static, greyed-out unit box to its right.

        Returns the editor unchanged when the field declares no unit, so
        unitless fields (drop-downs, text, checkboxes) keep the full row width.
        """
        if not unit:
            return editor
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        lay.addWidget(editor, 1)
        unit_box = QLabel(unit)
        unit_box.setProperty("role", "unit")
        unit_box.setAlignment(Qt.AlignCenter)
        unit_box.setEnabled(False)  # static: not an input
        lay.addWidget(unit_box)
        return row

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
        kwargs = dict(self._hidden)
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
            value = getattr(settings, f.name)
            if f.name in self._hidden:
                self._hidden[f.name] = value
                continue
            editor = self._editors.get(f.name)
            if editor is None:
                continue
            if isinstance(editor, QComboBox):
                editor.setCurrentText(str(value))
            elif isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QLineEdit):
                editor.setText(self._to_text(value))
        self.changed.emit()
