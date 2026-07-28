"""Interactive annotation view: click pins to mark them, correlate across interfaces.

Builds on :class:`~trap_tester.gui.widgets.layout_canvas.LayoutCanvas`. A left
click on a pin cycles its state (no comment → suspicious → faulty → no comment);
because marks are keyed by the pin's canonical channel, switching the interface
(the layout) re-projects the same marks onto the new interface. Pins with no
channel (GND / shield) are inert. Emits :data:`changed` whenever a mark is
toggled so a host panel can refresh its summary.
"""

from __future__ import annotations

from PySide6.QtCore import Signal

from trap_tester.core.layout import (
    ANNOTATION_STATES,
    AnnotationSet,
    Drawing,
    InterfaceLayout,
    build_annotation_drawing,
)
from trap_tester.core.layout.annotation import (
    CLEAR_FILL,
    CLEAR_STROKE,
    GND_FILL,
    GND_STROKE,
)
from trap_tester.gui.widgets.layout_canvas import LayoutCanvas, LegendItem

_EMPTY_MSG = "Select an interface to start marking channels."


class AnnotationView(LayoutCanvas):
    """A clickable interface sketch that records per-channel operator marks."""

    changed = Signal()  # emitted after a click toggles a mark

    def __init__(self) -> None:
        super().__init__()  # builds the canvas layout (title + canvas + legend)
        self._annset = AnnotationSet()
        self._layout: InterfaceLayout | None = None
        self.clear(_EMPTY_MSG)

    # ---- context / data ----------------------------------------------------
    def set_layout(self, layout: InterfaceLayout) -> None:
        """Show ``layout`` whole (every connector) and re-project current marks."""
        self._layout = layout
        self.fit_on_next_draw()  # a new interface fits; marking keeps the zoom
        self._redraw()

    def set_annotations(self, annotations: AnnotationSet) -> None:
        """Replace the whole set (e.g. after loading a file) and repaint."""
        self._annset = annotations
        self._redraw()

    def annotations(self) -> AnnotationSet:
        return self._annset

    def refresh(self) -> None:
        """Repaint from the current set without emitting :data:`changed`.

        Two views can share one :class:`AnnotationSet` (see the Interfaces panel's
        split view); when a click mutates it in one view, the other is refreshed
        with this. It must stay signal-free so the two do not re-trigger each other.
        """
        self._redraw()

    def clear_annotations(self) -> None:
        self._annset.clear_all()
        self._redraw()
        self.changed.emit()

    def _redraw(self) -> None:
        if self._layout is None:
            self.clear(_EMPTY_MSG)
            return
        self.show_drawing(build_annotation_drawing(self._layout, self._annset))

    # ---- interaction -------------------------------------------------------
    def _on_canvas_click(self, event) -> None:
        # a left-click that wasn't a pan (LayoutCanvas distinguishes them)
        pin = self._pin_at(event)
        if pin is None or pin.channel is None:  # GND / shield / empty space
            return
        # each pin carries its own connector, so a multi-connector layout marks
        # the right (connector, channel) even when several are shown together.
        self._annset.cycle(pin.connector, pin.channel)
        self._redraw()
        self.changed.emit()

    # ---- title / legend (LayoutCanvas hooks) -------------------------------
    def _title(self, drawing: Drawing) -> str:
        faulty = sum(p.status == "faulty" for p in drawing.pins)
        susp = sum(p.status == "suspicious" for p in drawing.pins)
        return f"{drawing.title} — {faulty} faulty, {susp} suspicious"

    def _legend(self, drawing: Drawing) -> list[LegendItem]:
        present = {p.status for p in drawing.pins}
        items: list[LegendItem] = [
            (label, color, "#333")
            for status, (label, color) in ANNOTATION_STATES.items()
            if status in present
        ]
        if "clear" in present:
            items.append(("No data", CLEAR_FILL, CLEAR_STROKE))
        if "unmapped" in present:
            items.append(("GND / shield", GND_FILL, GND_STROKE))
        return items + self._decoration_legend(drawing)
