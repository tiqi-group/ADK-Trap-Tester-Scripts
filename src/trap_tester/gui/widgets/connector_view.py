"""The analysis connector map: an :class:`AnalysisResult` on its interface.

A thin renderer built on
:class:`~trap_tester.gui.widgets.layout_canvas.LayoutCanvas` (which does the
primitive→artist painting and hover). All selection controls — the layout,
connector and mapping selectors plus Import / Folders — live in the Analysis
panel now, exactly as the Interfaces panel drives its ``AnnotationView``; this
widget only paints a prepared :class:`Drawing` and supplies the fault-count
title and status legend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from trap_tester.core.analysis import STATUS_INFO
from trap_tester.core.layout.interface import UNMEASURED_FILL, UNMEASURED_STROKE
from trap_tester.gui.widgets.layout_canvas import LayoutCanvas, LegendItem

if TYPE_CHECKING:
    from trap_tester.core.layout import Drawing


class ConnectorView(LayoutCanvas):
    """Draw an analysis result on its physical interface (e.g. DSUB-50)."""

    def __init__(self) -> None:
        super().__init__()
        self.clear()

    def clear(self, message: str = "Run an analysis to see the connector map.") -> None:
        super().clear(message)

    # ---- title / legend (LayoutCanvas hooks) -------------------------------
    def _title(self, drawing: Drawing) -> str:
        measured = [p for p in drawing.pins if p.measured]
        faults = [p for p in measured if p.status != "ok"]
        return f"{drawing.title} — {len(faults)} fault(s) / {len(measured)} pins"

    def _legend(self, drawing: Drawing) -> list[LegendItem]:
        present = {p.status for p in drawing.pins}
        items: list[LegendItem] = [
            (label, color, "#333")
            for status, (label, color) in STATUS_INFO.items() if status in present
        ]
        if "unmeasured" in present:
            items.append(("No data", UNMEASURED_FILL, UNMEASURED_STROKE))
        return items + self._decoration_legend(drawing)
