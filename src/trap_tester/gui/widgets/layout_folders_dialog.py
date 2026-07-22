"""Dialog to manage the folders searched for custom interface layouts.

The writable per-user store is always searched and is shown here for reference
(read-only). Folders added through this dialog are persisted and searched in
addition — the intended home for layouts kept in a shared or version-controlled
folder (e.g. a private git repo). Folders provided via the
``TRAP_TESTER_LAYOUT_PATH`` environment variable are also shown, read-only.

The dialog only mutates the persisted list (:func:`add_layout_dir` /
:func:`remove_layout_dir`); it never writes into the folders themselves. Callers
should refresh their layout selectors after it closes — :meth:`exec` returns
``True`` when the set of folders changed.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.layout.store import (
    add_layout_dir,
    configured_layout_dirs,
    env_layout_dirs,
    remove_layout_dir,
    user_layouts_dir,
)


class LayoutFoldersDialog(QDialog):
    """Add / remove the extra folders searched for custom layouts."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Custom layout folders")
        self.setMinimumWidth(520)
        self._changed = False

        v = QVBoxLayout(self)
        v.addWidget(
            QLabel(
                "Folders searched for custom interface layouts. Add the folder "
                "holding your shared or version-controlled layouts (e.g. a private "
                "git repo); the app reads them but never modifies them."
            )
        )
        v.itemAt(0).widget().setWordWrap(True)

        self._list = QListWidget()
        self._list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._list.setProperty("role", "viewer")
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        v.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        self._add_btn = QPushButton("Add folder…")
        self._add_btn.setProperty("role", "interactive")
        self._add_btn.clicked.connect(self._add)
        self._remove_btn = QPushButton("Remove")
        self._remove_btn.setProperty("role", "interactive")
        self._remove_btn.clicked.connect(self._remove)
        btn_row.addWidget(self._add_btn)
        btn_row.addWidget(self._remove_btn)
        btn_row.addStretch(1)
        v.addLayout(btn_row)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.accept)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)

        self._reload()

    # ---- data --------------------------------------------------------------
    def changed(self) -> bool:
        """Whether the folder set was modified while the dialog was open."""
        return self._changed

    def _reload(self) -> None:
        """Rebuild the list: writable store + env dirs (read-only) + persisted."""
        self._list.clear()
        self._add_readonly(user_layouts_dir(), "writable store")
        for d in env_layout_dirs():
            self._add_readonly(d, "from TRAP_TESTER_LAYOUT_PATH")
        for d in configured_layout_dirs():
            item = QListWidgetItem(str(d))
            item.setData(Qt.ItemDataRole.UserRole, str(d))
            self._list.addItem(item)
        self._sync_buttons()

    def _add_readonly(self, path: Path, note: str) -> None:
        item = QListWidgetItem(f"{path}   — {note}")
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)  # not selectable
        self._list.addItem(item)

    def _selected_dir(self) -> str | None:
        items = self._list.selectedItems()
        data = items[0].data(Qt.ItemDataRole.UserRole) if items else None
        return str(data) if data else None

    def _sync_buttons(self) -> None:
        self._remove_btn.setEnabled(self._selected_dir() is not None)

    # ---- actions -----------------------------------------------------------
    def _add(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Add layout folder")
        if not path:
            return
        try:
            add_layout_dir(path)
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, "Cannot add folder", str(exc))
            return
        self._changed = True
        self._reload()

    def _remove(self) -> None:
        path = self._selected_dir()
        if path is None:
            return
        remove_layout_dir(path)
        self._changed = True
        self._reload()
