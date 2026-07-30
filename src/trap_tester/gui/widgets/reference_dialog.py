"""Read-only view of the golden reference held by the analysis settings.

The reference is a table of expected values per (connector, pin) — captured from
a measurement marked as the golden reference, or loaded with a preset. It is not
editable here: the way to change it is to capture a different result or to hand-
edit the preset JSON, both of which keep the table and its provenance together.

Round-based measurements (resistance, voltage) have no connector, so their
entries use the wildcard connector ``*`` and apply to every round.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.analysis.acceptance import WILDCARD, Reference
from trap_tester.core.analysis.quantities import quantities_for


def _sort_key(key: str) -> tuple[int, int, int]:
    """Sort ``"<conn>:<pin>"`` by pin, wildcard connectors first."""
    connector, _, pin = key.partition(":")
    wildcard = connector == WILDCARD
    try:
        pin_number = int(pin)
    except ValueError:
        pin_number = 0
    try:
        connector_number = 0 if wildcard else int(connector)
    except ValueError:
        connector_number = 0
    return (0 if wildcard else 1, connector_number, pin_number)


class ReferenceDialog(QDialog):
    """Show every expected value the current reference carries."""

    def __init__(
        self, reference: Reference, measurement: str, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Golden reference")
        self.setMinimumSize(460, 420)

        quantities = quantities_for(measurement)
        v = QVBoxLayout(self)

        header = QLabel(self._provenance(reference, measurement))
        header.setWordWrap(True)
        header.setProperty("role", "viewer")
        v.addWidget(header)

        keys = sorted(reference.values, key=_sort_key)
        table = QTableWidget(len(keys), 2 + len(quantities))
        table.setProperty("role", "viewer")
        table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        table.setSelectionMode(QAbstractItemView.SingleSelection)
        table.setHorizontalHeaderLabels(
            ["Connector", "Pin", *(f"{q.symbol} [{q.unit}]" for q in quantities)]
        )
        table.verticalHeader().setVisible(False)
        for r, key in enumerate(keys):
            connector, _, pin = key.partition(":")
            entry = reference.values[key]
            cells = [connector, pin]
            cells += [
                f"{entry[q.key]:.6g}" if q.key in entry else "—" for q in quantities
            ]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if c:  # numbers read better right-aligned; the connector stays left
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        v.addWidget(table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        v.addWidget(buttons)

    @staticmethod
    def _provenance(reference: Reference, measurement: str) -> str:
        if not reference:
            return "No golden reference loaded."
        lines = [f"{reference.n_points} point(s) for {measurement}."]
        if reference.source:
            lines.append(f"Captured from {reference.source}")
        if reference.captured:
            lines.append(f"on {reference.captured}")
        return " ".join(lines)
