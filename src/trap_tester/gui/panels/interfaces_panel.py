"""The Interfaces panel: manual, cross-interface channel annotation.

Two columns:

Left  — controls (green) that are not about one view: layout Import / Folders, the
        split toggle, the mapping, and Save / Load / Clear for the annotation set,
        plus a live summary.
Right — the interactive annotation view (red): a bare interface sketch whose pins
        are clicked to cycle no comment → suspicious → faulty, with that view's own
        interface and connector selectors directly beneath its canvas.

Marks are keyed by the canonical address, so switching the interface (or connector)
re-projects the same marks — the tool for correlating an operator-reported fault
along the mechanical interfaces. The set round-trips to JSON via Save / Load.

**Split view** shows two interfaces side by side instead of switching between them.
Both views share one :class:`AnnotationSet`, so a mark made on either appears
immediately on the other — the correlation is visible without switching. Each side
picks its own interface and connector *under its own canvas*, so it is unambiguous
which pane a control drives; the mapping and the annotation set are shared, since
they describe the setup rather than one view.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPalette, QPixmap
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
    CoverageReport,
    Mapping,
    apply_to,
    coverage_report,
    dsub50_layout_for_connector,
    fpc_layout_for_connector,
    import_layout,
    import_mapping,
    is_synthetic,
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


class _InterfaceSource(QWidget):
    """One side's interface choice: which layout, plus its connector controls.

    Both the layout selector and the connector bar are placed *under that view's
    canvas* rather than in the panel's left column: in split view, two identical rows
    of controls stacked in one column give no clue which picture they drive. The panel
    owns one of these per view, so the two sides are picked independently. Emits
    :data:`changed` whenever any of the three changes.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Interface:"))
        self.selector = QComboBox()
        self.selector.setProperty("role", "interactive")
        self.selector.currentIndexChanged.connect(self.changed)
        row.addWidget(self.selector, 1)

        # The connector controls sit beside this selector under the canvas; see
        # :meth:`_build_pane`. Owned here so one object still represents "this side's
        # choice", but placed by the panel.
        self.connector_bar = _ConnectorBar()
        self.connector_bar.changed.connect(self.changed)

    # ---- state -------------------------------------------------------------
    @property
    def conn_spin(self) -> QSpinBox:
        return self.connector_bar.conn_spin

    @property
    def show_all(self) -> QCheckBox:
        return self.connector_bar.show_all

    def token(self):
        return self.selector.currentData()

    def name(self) -> str:
        return self.selector.currentText()

    def is_builtin(self) -> bool:
        token = self.token()
        return isinstance(token, str) and token.startswith("builtin:")

    def refresh_options(self) -> None:
        """Rebuild the selector from the search folders, keeping the choice."""
        keep = self.selector.currentData()
        self.selector.blockSignals(True)
        self.selector.clear()
        for label, token in _BUILTINS:
            self.selector.addItem(label, token)
        for name, path in user_layout_options():
            self.selector.addItem(name, path)
        idx = self.selector.findData(keep) if keep is not None else 0
        self.selector.setCurrentIndex(idx if idx >= 0 else 0)
        self.selector.blockSignals(False)

    def select(self, data) -> bool:
        idx = self.selector.findData(data)
        if idx < 0:
            return False
        self.selector.setCurrentIndex(idx)  # emits changed
        return True

    def select_default(self) -> None:
        self.selector.setCurrentIndex(0)

    def sync_enabled(self, conn_max: int) -> None:
        """Grey out the connector controls where they do not apply."""
        self.connector_bar.sync_enabled(self.is_builtin(), conn_max)


class _ConnectorBar(QWidget):
    """Which connector one view shows: the spin box and "Show all".

    Sits at the bottom of its own plot pane rather than in the left column, so in
    split view it is unambiguous which canvas it drives.
    """

    changed = Signal()

    def __init__(self) -> None:
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(QLabel("Connector:"))
        self.conn_spin = QSpinBox()
        self.conn_spin.setProperty("role", "interactive")
        self.conn_spin.setRange(0, TESTER_CONNECTORS - 1)  # 0-indexed; bounded
        self.conn_spin.valueChanged.connect(self.changed)
        row.addWidget(self.conn_spin)
        row.addStretch(1)
        self.show_all = QCheckBox("Show all")
        self.show_all.setProperty("role", "interactive")
        self.show_all.setToolTip(
            "Render every connector instance at once (zoom / pan to inspect).\n"
            "Connectors come from the mapping when one is loaded, else a default set."
        )
        self.show_all.toggled.connect(self.changed)
        row.addWidget(self.show_all)

    def sync_enabled(self, builtin: bool, conn_max: int) -> None:
        """Grey out the controls where they do not apply."""
        self.show_all.setEnabled(builtin)
        # single-connector picker is moot for custom layouts and when showing all
        self.conn_spin.setEnabled(builtin and not self.show_all.isChecked())
        self.conn_spin.setMaximum(conn_max)


def _placeholder_warning(layout) -> str | None:
    """Say so when some pads are on made-up addresses rather than real wiring.

    A geometry-only import (a trap, an LGA) knows where its pads *are* but not what
    they route to; those slots get a distinct synthetic address so they can be
    browsed and marked without colliding with a physical pin. That is useful but it
    is not this setup's wiring, so it must not look like it: pick a mapping to get
    the real addresses.
    """
    synthetic = sum(is_synthetic(s.connector) for s in layout.slots)
    if not synthetic:
        return None
    return (
        f"{synthetic} of {len(layout.slots)} pads are on placeholder addresses "
        "(no mapping wires them) — they can be marked, but those marks do not "
        "correspond to a physical pin."
    )


def _mapping_note(
    name: str, report: CoverageReport, placeholder: str | None
) -> str | None:
    """The banner for an applied mapping, or ``None`` when there is nothing to act on.

    A clean full match needs no banner. Anything else — idents the CSV does not name,
    idents the layout does not have, cells that matched only ignoring case, pads left
    on placeholder addresses — is named here, because each one is a data fix the
    operator can actually make. v1 could only say "0 slots matched" or stay silent.
    """
    parts = [f"Mapping '{name}': {report.summary()}."]
    if report.case_mismatches:
        pairs = ", ".join(f"{a} ≈ {b}" for a, b in report.case_mismatches[:4])
        parts.append(f"Matched ignoring case (fix the CSV): {pairs}.")
    if placeholder:
        parts.append(placeholder)
    actionable = (
        report.layout_only or report.csv_only or report.case_mismatches or placeholder
    )
    return " ".join(parts) if actionable else None


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

        # both views annotate ONE set, so a mark on either shows up on the other
        self._view_b.set_annotations(self._view_a.annotations())

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

        self._import_btn = QPushButton("Import…")
        self._import_btn.setProperty("role", "interactive")
        self._import_btn.setToolTip(
            f"Import a custom interface layout JSON into {user_layouts_dir()}"
        )
        self._import_btn.clicked.connect(self._import_layout)
        self._folders_btn = QPushButton("Folders…")
        self._folders_btn.setProperty("role", "interactive")
        self._folders_btn.setToolTip(
            "Add folders to search for custom layouts (e.g. a private git repo)"
        )
        self._folders_btn.clicked.connect(self._manage_folders)

        # Import / Folders act on the layout store, not on one view, so they stay in
        # this column. Which interface each view shows is per-view, so those selectors
        # live under their own canvas — see :meth:`_build_pane`.
        btn_row = QHBoxLayout()
        btn_row.addWidget(self._import_btn)
        btn_row.addWidget(self._folders_btn)
        btn_row.addStretch(1)
        sel_v.addLayout(btn_row)

        self._src_a = _InterfaceSource()
        self._src_a.changed.connect(self._update_view)
        self._src_b = _InterfaceSource()
        self._src_b.changed.connect(self._update_view)

        self._split = QCheckBox("Split view (two interfaces side by side)")
        self._split.setProperty("role", "interactive")
        self._split.setToolTip(
            "Show a second interface next to the first. Both share the same marks,\n"
            "so a channel marked on one appears immediately on the other."
        )
        self._split.toggled.connect(self._on_split_toggled)
        sel_v.addWidget(self._split)

        # The mapping name plus its Import button do not fit one line in this column,
        # so label it above rather than squeezing the combo into a truncated stub.
        sel_v.addWidget(QLabel("Mapping:"))
        map_row = QHBoxLayout()
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

        self._view_a = AnnotationView()
        self._view_b = AnnotationView()
        # A click mutates the shared set; repaint the other side (refresh() is
        # signal-free, so the two views cannot re-trigger each other).
        self._view_a.changed.connect(self._on_marks_changed)
        self._view_b.changed.connect(self._on_marks_changed)

        # Each pane is its canvas plus that side's connector controls, so the
        # controls travel with the picture they change.
        self._pane_a = self._build_pane(self._view_a, self._src_a)
        self._pane_b = self._build_pane(self._view_b, self._src_b)

        # a splitter so the divider can be dragged when the two differ in shape
        self._views = QSplitter(Qt.Horizontal)
        self._views.addWidget(self._pane_a)
        self._views.addWidget(self._pane_b)
        self._views.setStretchFactor(0, 1)
        self._views.setStretchFactor(1, 1)
        self._pane_b.setVisible(False)
        v.addWidget(self._views)
        return box

    @staticmethod
    def _build_pane(view: AnnotationView, src: _InterfaceSource) -> QWidget:
        """One plot pane: the canvas, with that view's own controls beneath it.

        Reading downward: the picture, which interface it is, and which connector of
        that interface. Everything that changes *this* canvas is in this column.
        """
        pane = QWidget()
        layout = QVBoxLayout(pane)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(view, 1)
        layout.addWidget(src)
        layout.addWidget(src.connector_bar)
        return pane

    def _on_marks_changed(self) -> None:
        sender = self.sender()
        other = self._view_b if sender is self._view_a else self._view_a
        if other.isVisibleTo(self):
            other.refresh()
        self._update_summary()

    # ---- interface selection -----------------------------------------------
    def _refresh_interfaces(self) -> None:
        for src in (self._src_a, self._src_b):
            src.refresh_options()

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

    def _current_layout(
        self, src: _InterfaceSource, mapping: Mapping | None, view: AnnotationView
    ):
        token = src.token()
        if src.is_builtin():
            is_dsub = token == "builtin:dsub50"
            factory = (
                dsub50_layout_for_connector if is_dsub else fpc_layout_for_connector
            )
            if src.show_all.isChecked():
                conns = self._connector_set(mapping)
                label = ("DSUB-50" if is_dsub else "FPC ribbon") + " — all connectors"
                base = tile_connector_layouts(
                    [factory(c) for c in conns], conns, label
                )
            else:
                base = factory(src.conn_spin.value())
        else:
            try:
                # Custom layouts are shown whole — they may span several connectors
                # (e.g. an interposer over 8 DSUB connectors).
                base = load_layout(Path(token))
            except Exception as exc:
                QMessageBox.warning(
                    self, "Interface unavailable",
                    f"Could not load '{Path(token).name}':\n{exc}\n\n"
                    "Falling back to the built-in DSUB-50.",
                )
                src.select_default()
                base = dsub50_layout_for_connector(src.conn_spin.value())
        if mapping is None:
            view.set_warning(_placeholder_warning(base))
            return base
        return self._wire(base, mapping, view)

    def _wire(self, base, mapping: Mapping, view: AnnotationView):
        """Apply ``mapping`` to ``base`` and set the view's banner from the diff."""
        report = coverage_report(base, mapping)
        name = self._mapping_selector.currentText()
        if report.count == 0:
            view.set_warning(
                f"Mapping '{name}' does not apply to '{base.name}' — marks here "
                "cannot propagate to or from other interfaces via this mapping."
            )
            return base
        wired = apply_to(base, mapping)
        view.set_warning(_mapping_note(name, report, _placeholder_warning(wired)))
        return wired

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
            except Exception as exc:
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

    def _on_split_toggled(self, on: bool) -> None:
        self._pane_b.setVisible(on)
        if on and self._views.sizes()[1] == 0:
            half = max(self._views.width() // 2, 1)
            self._views.setSizes([half, half])
        self._update_view()

    def _update_view(self) -> None:
        mapping = self._selected_mapping()
        # bound the connector pickers: a mapping defines the set, else a default
        conn_max = (
            max((n.connector for n in mapping.nets), default=0)
            if mapping is not None
            else TESTER_CONNECTORS - 1
        )
        split = self._split.isChecked()
        for src, view, active in (
            (self._src_a, self._view_a, True),
            (self._src_b, self._view_b, split),
        ):
            if not active:
                continue  # don't pay to render a hidden side
            src.sync_enabled(conn_max)
            view.set_layout(self._current_layout(src, mapping, view))
        self._update_summary()

    def _import_layout(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import interface layout", "", "Layout JSON (*.json);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_layout(path)
        except Exception as exc:
            QMessageBox.warning(
                self, "Import failed",
                f"'{Path(path).name}' is not a valid layout file:\n{exc}",
            )
            return
        self._refresh_interfaces()
        # show the freshly imported layout on the first side
        if not self._src_a.select(str(dest)):
            self._update_view()

    def _import_mapping(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import mapping", "", "Mapping CSV (*.csv);;All files (*)"
        )
        if not path:
            return
        try:
            dest = import_mapping(path)
        except Exception as exc:
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
        annset = self._view_a.annotations()
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
        except Exception as exc:
            QMessageBox.warning(
                self, "Load failed",
                f"'{Path(path).name}' is not a valid annotations file:\n{exc}",
            )
            return
        # both views must go on sharing ONE set, so hand the same object to each
        self._view_a.set_annotations(annset)
        self._view_b.set_annotations(annset)
        self._update_summary()

    def _clear_all(self) -> None:
        if self._view_a.annotations().is_empty():
            return
        if QMessageBox.question(
            self, "Clear all", "Remove every mark? This cannot be undone."
        ) == QMessageBox.Yes:
            self._view_a.clear_annotations()  # shared set; _on_marks_changed syncs B

    @staticmethod
    def _view_stem(src: _InterfaceSource) -> str:
        name = src.name() or "interface"
        stem = "".join(c if c.isalnum() or c in "-_" else "_" for c in name)
        if src.is_builtin():
            stem += (
                "-all" if src.show_all.isChecked() else f"-conn{src.conn_spin.value()}"
            )
        return stem

    def _save_view(self) -> None:
        """Export the interface visualiser exactly as shown to a PNG image.

        In split view both panes are captured together, since "as shown" is the
        side-by-side comparison the operator is looking at.
        """
        split = self._split.isChecked()
        default = self._view_stem(self._src_a)
        if split:
            default += f"--{self._view_stem(self._src_b)}"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save view", f"{default}.png", "PNG image (*.png)"
        )
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        try:
            if split:
                self._save_both_panes(path)
            else:
                self._view_a.save_view(path)
        except Exception as exc:
            QMessageBox.warning(self, "Save failed", f"Could not save image:\n{exc}")
            return
        self._summary.setText(self._summary.text() + f"\nView saved to {Path(path).name}.")

    def _save_both_panes(self, path: str) -> None:
        """Write the two canvases side by side into one PNG.

        Grabs each :class:`AnnotationView` rather than the splitter, so the connector
        controls that now sit at the bottom of each pane stay out of the exported
        image — the export is the comparison, not the widgets that produced it.
        """
        self._view_a.canvas.draw()
        self._view_b.canvas.draw()
        left, right = self._view_a.grab(), self._view_b.grab()
        out = QPixmap(left.width() + right.width(), max(left.height(), right.height()))
        out.fill(self.palette().color(QPalette.Window))  # matches the active theme
        painter = QPainter(out)
        try:
            painter.drawPixmap(0, 0, left)
            painter.drawPixmap(left.width(), 0, right)
        finally:
            painter.end()
        if not out.save(path):
            raise OSError(f"could not write image to {path}")

    def _update_summary(self) -> None:
        counts = self._view_a.annotations().counts()  # shared with view B
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
