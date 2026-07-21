"""The Interfaces panel: manual, cross-interface channel annotation.

Two columns:

Left  — controls (green): interface selector + Import, connector, and
        Save / Load / Clear for the annotation set, plus a live summary.
Right — the interactive annotation view (red): a bare interface sketch whose
        pins are clicked to cycle no comment → suspicious → faulty.

Marks are keyed by canonical channel, so switching the interface (or connector)
re-projects the same marks — the tool for correlating an operator-reported fault
along the mechanical interfaces. The set round-trips to JSON via Save / Load.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.layout import (
    AnnotationSet,
    dsub50_layout_for_connector,
    fpc_layout_for_connector,
    import_layout,
    load_layout,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.gui.widgets.annotation_view import AnnotationView

_BUILTINS = [
    ("DSUB-50 (built-in)", "builtin:dsub50"),
    ("FPC ribbon (built-in)", "builtin:fpc"),
]


class InterfacesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_left())
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([320, 900])
        outer.addWidget(splitter)

        self._refresh_interfaces()
        self._update_view()

    # ---- columns -----------------------------------------------------------
    def _build_left(self) -> QWidget:
        col = QWidget()
        col.setMinimumWidth(300)
        layout = QVBoxLayout(col)
        layout.addWidget(self._build_interface_box())
        layout.addWidget(self._build_annotations_box())
        layout.addStretch(1)
        return col

    def _build_interface_box(self) -> QWidget:
        sel_box = QGroupBox("Interface")
        sel_box.setProperty("role", "interactive")
        sel_v = QVBoxLayout(sel_box)

        iface_row = QHBoxLayout()
        self._iface_selector = QComboBox()
        self._iface_selector.setProperty("role", "interactive")
        self._iface_selector.currentIndexChanged.connect(self._update_view)
        iface_row.addWidget(self._iface_selector, 1)
        self._import_btn = QPushButton("Import…")
        self._import_btn.setProperty("role", "interactive")
        self._import_btn.setToolTip(
            f"Import a custom interface layout JSON into {user_layouts_dir()}"
        )
        self._import_btn.clicked.connect(self._import_layout)
        iface_row.addWidget(self._import_btn)
        sel_v.addLayout(iface_row)

        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Connector:"))
        self._conn_spin = QSpinBox()
        self._conn_spin.setProperty("role", "interactive")
        self._conn_spin.setRange(0, 99)  # DSUB connectors are 0-indexed
        self._conn_spin.valueChanged.connect(self._update_view)
        conn_row.addWidget(self._conn_spin)
        conn_row.addStretch(1)
        sel_v.addLayout(conn_row)

        hint = QLabel(
            "Click a pin to cycle its mark:\n"
            "no comment → suspicious → faulty → no comment.\n"
            "Switch interface or connector to see the same channels elsewhere."
        )
        hint.setWordWrap(True)
        sel_v.addWidget(hint)
        return sel_box

    def _build_annotations_box(self) -> QWidget:
        marks_box = QGroupBox("Annotations")
        marks_box.setProperty("role", "interactive")
        marks_v = QVBoxLayout(marks_box)
        btn_row = QHBoxLayout()
        self._save_btn = QPushButton("Save…")
        self._save_btn.setProperty("role", "interactive")
        self._save_btn.clicked.connect(self._save)
        self._load_btn = QPushButton("Load…")
        self._load_btn.setProperty("role", "interactive")
        self._load_btn.clicked.connect(self._load)
        self._clear_btn = QPushButton("Clear all")
        self._clear_btn.setProperty("role", "interactive")
        self._clear_btn.clicked.connect(self._clear_all)
        btn_row.addWidget(self._save_btn)
        btn_row.addWidget(self._load_btn)
        btn_row.addWidget(self._clear_btn)
        marks_v.addLayout(btn_row)

        self._summary = QLabel("No channels marked.")
        self._summary.setProperty("role", "viewer")
        self._summary.setWordWrap(True)
        marks_v.addWidget(self._summary)
        return marks_box

    def _build_right(self) -> QWidget:
        box = QGroupBox("Interface visualiser")
        box.setProperty("role", "viewer")
        v = QVBoxLayout(box)

        top = QHBoxLayout()
        top.addStretch(1)
        self._save_view_btn = QPushButton("Save view…")
        self._save_view_btn.setProperty("role", "interactive")
        self._save_view_btn.clicked.connect(self._save_view)
        top.addWidget(self._save_view_btn)
        v.addLayout(top)

        self._view = AnnotationView()
        self._view.changed.connect(self._update_summary)
        v.addWidget(self._view)
        return box

    # ---- interface selection -----------------------------------------------
    def _refresh_interfaces(self) -> None:
        keep = self._iface_selector.currentData()
        self._iface_selector.blockSignals(True)
        self._iface_selector.clear()
        for label, token in _BUILTINS:
            self._iface_selector.addItem(label, token)
        for name, path in user_layout_options():
            self._iface_selector.addItem(name, path)
        idx = self._iface_selector.findData(keep) if keep is not None else 0
        self._iface_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self._iface_selector.blockSignals(False)

    def _current_layout(self):
        token = self._iface_selector.currentData()
        if token == "builtin:dsub50":
            return dsub50_layout_for_connector(self._conn_spin.value())
        if token == "builtin:fpc":
            return fpc_layout_for_connector(self._conn_spin.value())
        try:
            # Custom layouts are shown whole — they may span several connectors
            # (e.g. an interposer over 8 DSUB connectors).
            return load_layout(Path(token))
        except Exception as exc:  # noqa: BLE001 — deleted / corrupt custom file
            QMessageBox.warning(
                self, "Interface unavailable",
                f"Could not load '{Path(token).name}':\n{exc}\n\n"
                "Falling back to the built-in DSUB-50.",
            )
            self._iface_selector.setCurrentIndex(0)
            return dsub50_layout_for_connector(self._conn_spin.value())

    def _update_view(self) -> None:
        token = self._iface_selector.currentData()
        # The connector picker only applies to the single-connector built-ins;
        # custom layouts carry their own connectors and are drawn whole.
        is_builtin = isinstance(token, str) and token.startswith("builtin:")
        self._conn_spin.setEnabled(is_builtin)
        self._view.set_layout(self._current_layout())
        self._update_summary()

    def _import_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import interface layout", "", "Layout JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_layout(path)
        except Exception as exc:  # noqa: BLE001 — surface any parse/IO failure
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid layout file:\n{exc}",
            )
            return
        self._refresh_interfaces()
        idx = self._iface_selector.findData(str(dest))
        if idx >= 0:
            self._iface_selector.setCurrentIndex(idx)  # triggers _update_view

    # ---- annotation set: save / load / clear -------------------------------
    def _save(self) -> None:
        annset = self._view.annotations()
        if annset.is_empty():
            QMessageBox.information(self, "Nothing to save", "No channels are marked.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save annotations", "annotations.json", "Annotations JSON (*.json)"
        )
        if not path:
            return
        try:
            annset.save_json(path)
        except OSError as exc:
            QMessageBox.warning(self, "Save failed", f"Could not write file:\n{exc}")
            return
        self._summary.setText(self._summary.text() + f"\nSaved to {Path(path).name}.")

    def _load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Load annotations", "", "Annotations JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            annset = AnnotationSet.load_json(path)
        except Exception as exc:  # noqa: BLE001 — parse / validation failure
            QMessageBox.warning(
                self, "Load failed",
                f"'{Path(path).name}' is not a valid annotations file:\n{exc}",
            )
            return
        self._view.set_annotations(annset)
        self._update_summary()

    def _clear_all(self) -> None:
        if self._view.annotations().is_empty():
            return
        if QMessageBox.question(
            self, "Clear all", "Remove every mark? This cannot be undone."
        ) == QMessageBox.Yes:
            self._view.clear_annotations()

    def _save_view(self) -> None:
        """Export the interface visualiser exactly as shown to a PNG image."""
        name = self._iface_selector.currentText() or "interface"
        default = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        token = self._iface_selector.currentData()
        if isinstance(token, str) and token.startswith("builtin:"):
            default += f"-conn{self._conn_spin.value()}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save view", f"{default}.png", "PNG image (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            self._view.save_view(path)
        except Exception as exc:  # noqa: BLE001 — surface any render/IO failure
            QMessageBox.warning(self, "Save failed", f"Could not save image:\n{exc}")
            return
        self._summary.setText(self._summary.text() + f"\nView saved to {Path(path).name}.")

    def _update_summary(self) -> None:
        counts = self._view.annotations().counts()
        total = sum(counts.values())
        if not total:
            self._summary.setText("No channels marked.")
            return
        faulty = counts.get("faulty", 0)
        susp = counts.get("suspicious", 0)
        self._summary.setText(
            f"Faulty: {faulty}   Suspicious: {susp}\n"
            f"{total} channel(s) marked across all connectors."
        )
