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
    QCheckBox,
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
    TESTER_CONNECTORS,
    AnnotationSet,
    Mapping,
    apply_to,
    coverage,
    dsub50_layout_for_connector,
    fpc_layout_for_connector,
    import_layout,
    import_mapping,
    load_csv,
    load_layout,
    mapping_options,
    tile_connector_layouts,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.gui.widgets.annotation_view import AnnotationView
from trap_tester.gui.widgets.layout_folders_dialog import LayoutFoldersDialog

_BUILTINS = [
    ("DSUB-50 (built-in)", "builtin:dsub50"),
    ("FPC ribbon (built-in)", "builtin:fpc"),
]


class InterfacesPanel(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._mapping_cache: dict[str, Mapping] = {}
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
        self._refresh_mappings()
        self._update_view()

    def reload_settings(self) -> None:
        """Re-scan the layout / mapping folders (called after Settings changes)."""
        self._mapping_cache.clear()
        self._refresh_interfaces()
        self._refresh_mappings()
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
        self._folders_btn = QPushButton("Folders…")
        self._folders_btn.setProperty("role", "interactive")
        self._folders_btn.setToolTip(
            "Add folders to search for custom layouts (e.g. a private git repo)"
        )
        self._folders_btn.clicked.connect(self._manage_folders)
        iface_row.addWidget(self._folders_btn)
        sel_v.addLayout(iface_row)

        conn_row = QHBoxLayout()
        conn_row.addWidget(QLabel("Connector:"))
        self._conn_spin = QSpinBox()
        self._conn_spin.setProperty("role", "interactive")
        self._conn_spin.setRange(0, TESTER_CONNECTORS - 1)  # 0-indexed; bounded
        self._conn_spin.valueChanged.connect(self._update_view)
        conn_row.addWidget(self._conn_spin)
        conn_row.addStretch(1)
        self._show_all = QCheckBox("Show all")
        self._show_all.setProperty("role", "interactive")
        self._show_all.setToolTip(
            "Render every connector instance at once (zoom / pan to inspect).\n"
            "Connectors come from the mapping when one is loaded, else a default set."
        )
        self._show_all.toggled.connect(self._update_view)
        conn_row.addWidget(self._show_all)
        sel_v.addLayout(conn_row)

        map_row = QHBoxLayout()
        map_row.addWidget(QLabel("Mapping:"))
        self._mapping_selector = QComboBox()
        self._mapping_selector.setProperty("role", "interactive")
        self._mapping_selector.setToolTip(
            "Cross-interface wiring CSV (found in the custom-layout folders).\n"
            "Overrides the inherent (connector, pin) wiring so marks re-project\n"
            "along this setup's real cabling."
        )
        self._mapping_selector.currentIndexChanged.connect(self._update_view)
        map_row.addWidget(self._mapping_selector, 1)
        self._import_mapping_btn = QPushButton("Import…")
        self._import_mapping_btn.setProperty("role", "interactive")
        self._import_mapping_btn.setToolTip(
            f"Import a cross-interface mapping CSV into {user_layouts_dir()}"
        )
        self._import_mapping_btn.clicked.connect(self._import_mapping)
        map_row.addWidget(self._import_mapping_btn)
        sel_v.addLayout(map_row)

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

    def _connector_set(self, mapping: Mapping | None) -> list[int]:
        """Which connectors "Show all" renders.

        A loaded mapping defines the exact set (its nets' connectors); without a
        mapping there is no inherent bound, so fall back to the tester's connector
        count so the tiled view stays finite.
        """
        if mapping is not None:
            conns = sorted({n.connector for n in mapping.nets})
            return conns or [0]
        return list(range(TESTER_CONNECTORS))

    def _current_layout(self, mapping: Mapping | None):
        token = self._iface_selector.currentData()
        if isinstance(token, str) and token.startswith("builtin:"):
            is_dsub = token == "builtin:dsub50"
            factory = dsub50_layout_for_connector if is_dsub else fpc_layout_for_connector
            if self._show_all.isChecked():
                conns = self._connector_set(mapping)
                label = ("DSUB-50" if is_dsub else "FPC ribbon") + " — all connectors"
                base = tile_connector_layouts(
                    [factory(c) for c in conns], conns, label
                )
            else:
                base = factory(self._conn_spin.value())
        else:
            try:
                # Custom layouts are shown whole — they may span several connectors
                # (e.g. an interposer over 8 DSUB connectors).
                base = load_layout(Path(token))
            except Exception as exc:  # noqa: BLE001 — deleted / corrupt custom file
                QMessageBox.warning(
                    self, "Interface unavailable",
                    f"Could not load '{Path(token).name}':\n{exc}\n\n"
                    "Falling back to the built-in DSUB-50.",
                )
                self._iface_selector.setCurrentIndex(0)
                base = dsub50_layout_for_connector(self._conn_spin.value())
        if mapping is None:
            self._view.set_warning(None)
            return base
        if coverage(base, mapping) == 0:
            name = self._mapping_selector.currentText()
            self._view.set_warning(
                f"Mapping '{name}' does not apply to '{base.name}' — marks here "
                "cannot propagate to or from other interfaces via this mapping."
            )
        else:
            self._view.set_warning(None)
        return apply_to(base, mapping)

    def _refresh_mappings(self) -> None:
        """Rebuild the mapping selector from the search folders, keeping choice."""
        keep = self._mapping_selector.currentData()
        self._mapping_selector.blockSignals(True)
        self._mapping_selector.clear()
        self._mapping_selector.addItem("Inherent (no mapping)", None)
        for name, path in mapping_options():
            self._mapping_selector.addItem(name, path)
        idx = self._mapping_selector.findData(keep) if keep else 0
        self._mapping_selector.setCurrentIndex(idx if idx >= 0 else 0)
        self._mapping_selector.blockSignals(False)

    def _selected_mapping(self) -> Mapping | None:
        """The parsed mapping for the current selection, or ``None`` for inherent."""
        token = self._mapping_selector.currentData()
        if not token:
            return None
        if token not in self._mapping_cache:
            try:
                self._mapping_cache[token] = load_csv(Path(token))
            except Exception as exc:  # noqa: BLE001 — deleted / malformed CSV
                QMessageBox.warning(
                    self, "Mapping unavailable",
                    f"Could not read '{Path(token).name}':\n{exc}\n\n"
                    "Falling back to the inherent wiring.",
                )
                self._mapping_selector.blockSignals(True)
                self._mapping_selector.setCurrentIndex(0)
                self._mapping_selector.blockSignals(False)
                return None
        return self._mapping_cache[token]

    def _update_view(self) -> None:
        token = self._iface_selector.currentData()
        # The connector picker only applies to the single-connector built-ins;
        # custom layouts carry their own connectors and are drawn whole.
        is_builtin = isinstance(token, str) and token.startswith("builtin:")
        mapping = self._selected_mapping()
        show_all = self._show_all.isChecked()
        self._show_all.setEnabled(is_builtin)
        # single-connector picker is moot for custom layouts and when showing all
        self._conn_spin.setEnabled(is_builtin and not show_all)
        # bound the picker: a mapping defines the connector set, else a default
        if mapping is not None:
            self._conn_spin.setMaximum(max((n.connector for n in mapping.nets), default=0))
        else:
            self._conn_spin.setMaximum(TESTER_CONNECTORS - 1)
        self._view.set_layout(self._current_layout(mapping))
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

    def _import_mapping(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import mapping", "", "Mapping CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_mapping(path)
        except Exception as exc:  # noqa: BLE001 — surface any parse/IO failure
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid mapping CSV:\n{exc}",
            )
            return
        self._mapping_cache.clear()
        self._refresh_mappings()
        idx = self._mapping_selector.findData(str(dest))
        if idx >= 0:
            self._mapping_selector.setCurrentIndex(idx)  # triggers _update_view

    def _manage_folders(self) -> None:
        dlg = LayoutFoldersDialog(self)
        dlg.exec()
        if dlg.changed():
            self._mapping_cache.clear()
            self._refresh_interfaces()
            self._refresh_mappings()
            self._update_view()

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
            default += "-all" if self._show_all.isChecked() else f"-conn{self._conn_spin.value()}"
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
