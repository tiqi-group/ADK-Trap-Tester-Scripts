"""Global settings: where the app reads and writes its files.

Two columns of green (editable) / red (read-only) boxes:

Left  — File locations: the results directory (and its ``measurements`` /
        ``analysis`` sub-folders) plus the analysis-presets folder, each
        persisted (and reset) on its own so a change survives restarts.
Right — Custom layouts & mappings: the writable store (read-only, set by the OS
        default or ``TRAP_TESTER_LAYOUTS_DIR``) plus the extra folders searched
        for layouts/mapping CSVs (add / remove; also fed by
        ``TRAP_TESTER_LAYOUT_PATH``).

Changing anything emits :data:`changed` so the main window can refresh the other
panels' browsers and selectors without a restart.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.appconfig import (
    analysis_dir,
    measurements_dir,
    presets_dir,
    results_dir,
    set_presets_dir,
    set_results_dir,
    set_theme,
    set_ui_scale,
    theme,
    ui_scale,
)
from trap_tester.core.layout import (
    add_layout_dir,
    configured_layout_dirs,
    env_layout_dirs,
    remove_layout_dir,
    user_layouts_dir,
)


class SettingsPanel(QWidget):
    """See and change the file locations the app uses."""

    changed = Signal()  # paths / folders changed (panels re-read files)
    themeChanged = Signal(str)  # UI theme changed (apply light/dark live)

    _THEME_LABELS = [("Light", "light"), ("Dark", "dark")]
    # Offered steps. appconfig clamps to its own bounds, so a hand-edited config can
    # sit between these without being silently reset.
    _UI_SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.5)

    def __init__(self) -> None:
        super().__init__()
        outer = QHBoxLayout(self)
        left = QVBoxLayout()
        left.addWidget(self._build_output_box())
        left.addWidget(self._build_appearance_box())
        left.addStretch(1)
        outer.addLayout(left, 1)
        outer.addWidget(self._build_layouts_box(), 1)
        self._reload_folders()
        self._refresh_output()

    # ---- output locations --------------------------------------------------
    def _build_output_box(self) -> QWidget:
        box = QGroupBox("File locations")
        box.setProperty("role", "interactive")
        v = QVBoxLayout(box)

        v.addWidget(_wrap_label(
            "Where measurements and analysis reports are written, and where "
            "analysis presets are kept. A relative path is resolved against the "
            "folder the app runs in."
        ))

        self._results_setting = _PathSetting(
            "Results directory:", results_dir, set_results_dir,
            "Choose results directory",
        )
        self._presets_setting = _PathSetting(
            "Analysis presets:", presets_dir, set_presets_dir,
            "Choose analysis presets directory",
        )
        for setting in (self._results_setting, self._presets_setting):
            setting.changed.connect(self._on_path_changed)
            v.addWidget(setting)

        # resolved, read-only echo of where files actually land
        self._resolved = QLabel()
        self._resolved.setProperty("role", "viewer")
        self._resolved.setWordWrap(True)
        self._resolved.setTextInteractionFlags(Qt.TextSelectableByMouse)
        v.addWidget(self._resolved)
        v.addStretch(1)
        return box

    def _refresh_output(self) -> None:
        """Reflect the persisted paths in the edits + the resolved echo."""
        self._results_setting.refresh()
        self._presets_setting.refresh()
        self._resolved.setText(
            "Resolved to:\n"
            f"  Measurements:  {measurements_dir().resolve()}\n"
            f"  Analysis:      {analysis_dir().resolve()}\n"
            f"  Presets:       {presets_dir().resolve()}"
        )

    def _on_path_changed(self) -> None:
        self._refresh_output()
        self.changed.emit()

    # ---- appearance --------------------------------------------------------
    def _build_appearance_box(self) -> QWidget:
        box = QGroupBox("Appearance")
        box.setProperty("role", "interactive")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        row.addWidget(QLabel("Theme:"))
        self._theme_combo = QComboBox()
        self._theme_combo.setProperty("role", "interactive")
        for label, token in self._THEME_LABELS:
            self._theme_combo.addItem(label, token)
        idx = self._theme_combo.findData(theme())
        self._theme_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        row.addWidget(self._theme_combo, 1)
        v.addLayout(row)

        scale_row = QHBoxLayout()
        scale_row.addWidget(QLabel("UI scale:"))
        self._scale_combo = QComboBox()
        self._scale_combo.setProperty("role", "interactive")
        self._scale_combo.setToolTip(
            "Enlarge the whole interface on a high-DPI screen.\n"
            "100% follows the desktop's own scaling; raise it if text and controls\n"
            "are too small. Applies when the app is restarted."
        )
        for factor in self._UI_SCALES:
            self._scale_combo.addItem(f"{round(factor * 100)}%", factor)
        idx = self._scale_combo.findData(ui_scale())
        if idx < 0:  # a hand-edited config may hold a value that is not a step
            self._scale_combo.addItem(f"{round(ui_scale() * 100)}%", ui_scale())
            idx = self._scale_combo.count() - 1
        self._scale_combo.setCurrentIndex(idx)
        self._scale_combo.currentIndexChanged.connect(self._on_scale_changed)
        scale_row.addWidget(self._scale_combo, 1)
        v.addLayout(scale_row)

        # Qt fixes its scale factor when the QApplication is built, so unlike the
        # theme this cannot be applied live.
        self._scale_note = QLabel("")
        self._scale_note.setProperty("role", "viewer")
        self._scale_note.setWordWrap(True)
        self._scale_note.setVisible(False)
        v.addWidget(self._scale_note)
        return box

    def _on_theme_changed(self, _index: int) -> None:
        name = set_theme(self._theme_combo.currentData())
        self.themeChanged.emit(name)

    def _on_scale_changed(self, _index: int) -> None:
        factor = set_ui_scale(self._scale_combo.currentData())
        self._scale_note.setText(
            f"UI scale set to {round(factor * 100)}% — restart the app to apply it."
        )
        self._scale_note.setVisible(True)

    # ---- custom layout / mapping folders -----------------------------------
    def _build_layouts_box(self) -> QWidget:
        box = QGroupBox("Custom layouts / mappings")
        box.setProperty("role", "interactive")
        v = QVBoxLayout(box)

        v.addWidget(_wrap_label(
            "Interface layouts (*.json) and cross-interface mappings (*.csv) are "
            "read from these folders, recursively. Imports and deletes only ever "
            "touch the writable store; the extra folders are read-only."
        ))

        self._folders = QListWidget()
        self._folders.setSelectionMode(QAbstractItemView.SingleSelection)
        self._folders.setProperty("role", "viewer")
        self._folders.itemSelectionChanged.connect(self._sync_folder_buttons)
        v.addWidget(self._folders, 1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add folder…")
        self._add_btn.setProperty("role", "interactive")
        self._add_btn.clicked.connect(self._add_folder)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setProperty("role", "interactive")
        self._remove_btn.clicked.connect(self._remove_folder)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)
        return box

    def _reload_folders(self) -> None:
        """List the writable store + env folders (read-only) + the removable ones."""
        self._folders.clear()
        self._add_readonly(user_layouts_dir(), "writable store (imports go here)")
        for d in env_layout_dirs():
            self._add_readonly(d, "from TRAP_TESTER_LAYOUT_PATH")
        for d in configured_layout_dirs():
            item = QListWidgetItem(str(d))
            item.setData(Qt.ItemDataRole.UserRole, str(d))
            self._folders.addItem(item)
        self._sync_folder_buttons()

    def _add_readonly(self, path: Path, note: str) -> None:
        item = QListWidgetItem(f"{path}   — {note}")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)  # not selectable
        self._folders.addItem(item)

    def _selected_folder(self) -> str | None:
        items = self._folders.selectedItems()
        data = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        return str(data) if data else None

    def _sync_folder_buttons(self) -> None:
        self._remove_btn.setEnabled(self._selected_folder() is not None)

    def _add_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add layout / mapping folder")
        if not path:
            return
        try:
            add_layout_dir(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot add folder", str(exc))
            return
        self._reload_folders()
        self.changed.emit()

    def _remove_folder(self) -> None:
        path = self._selected_folder()
        if path is None:
            return
        remove_layout_dir(path)
        self._reload_folders()
        self.changed.emit()


def _wrap_label(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    return label


class _PathSetting(QWidget):
    """One configurable folder: an edit + Browse…, with its own Apply / Reset.

    Each path resets independently — sharing one "Reset to defaults" button
    would silently restore a folder the operator never touched.
    """

    changed = Signal()

    def __init__(
        self,
        label: str,
        read: Callable[[], Path],
        write: Callable[[str | Path | None], Path],
        dialog_title: str,
    ) -> None:
        super().__init__()
        self._read = read
        self._write = write
        self._dialog_title = dialog_title

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)

        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        self._edit = QLineEdit()
        self._edit.setProperty("role", "interactive")
        self._edit.returnPressed.connect(self.apply)
        row.addWidget(self._edit, 1)
        browse = QPushButton("Browse…")
        browse.setProperty("role", "interactive")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        v.addLayout(row)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Apply")
        apply_btn.setProperty("role", "interactive")
        apply_btn.clicked.connect(self.apply)
        reset_btn = QPushButton("Reset to default")
        reset_btn.setProperty("role", "interactive")
        reset_btn.clicked.connect(self.reset)
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        self.refresh()

    def refresh(self) -> None:
        self._edit.setText(str(self._read()))

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self, self._dialog_title, str(self._read().resolve())
        )
        if path:
            self._edit.setText(path)
            self.apply()

    def apply(self) -> None:
        self._write(self._edit.text())
        self.refresh()
        self.changed.emit()

    def reset(self) -> None:
        self._write(None)
        self.refresh()
        self.changed.emit()
