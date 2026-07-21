"""Interactive annotation view: click pins to mark them, correlate across interfaces.

Builds on :class:`~trap_tester.gui.widgets.layout_canvas.LayoutCanvas`. A left
click on a pin cycles its state (no comment → suspicious → faulty → no comment);
because marks are keyed by the pin's canonical channel, switching the interface
(the layout) re-projects the same marks onto the new interface. Pins with no
channel (GND / shield) are inert. Emits :data:`changed` whenever a mark is
toggled so a host panel can refresh its summary.
"""

from __future__ import annotations

from matplotlib.lines import Line2D
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QVBoxLayout

from trap_tester.core.layout import (
    ANNOTATION_STATES,
    AnnotationSet,
    Drawing,
    InterfaceLayout,
    build_annotation_drawing,
)
from trap_tester.core.layout.annotation import CLEAR_FILL, CLEAR_STROKE
from trap_tester.gui.widgets.layout_canvas import LayoutCanvas

_EMPTY_MSG = "Select an interface to start marking channels."


class AnnotationView(LayoutCanvas):
    """A clickable interface sketch that records per-channel operator marks."""

    changed = Signal()  # emitted after a click toggles a mark

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas, 1)

        self._annset = AnnotationSet()
        self._layout: InterfaceLayout | None = None
        self._connector = 1
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.clear(_EMPTY_MSG)

    # ---- context / data ----------------------------------------------------
    def set_context(self, layout: InterfaceLayout, connector: int) -> None:
        """Show ``layout`` for ``connector`` (re-projects current marks)."""
        self._layout = layout
        self._connector = connector
        self.render()

    def set_annotations(self, annotations: AnnotationSet) -> None:
        """Replace the whole set (e.g. after loading a file) and repaint."""
        self._annset = annotations
        self.render()

    def annotations(self) -> AnnotationSet:
        return self._annset

    def clear_annotations(self) -> None:
        self._annset.clear_all()
        self.render()
        self.changed.emit()

    def render(self) -> None:
        if self._layout is None:
            self.clear(_EMPTY_MSG)
            return
        self.show_drawing(
            build_annotation_drawing(self._layout, self._annset, self._connector)
        )

    # ---- interaction -------------------------------------------------------
    def _on_click(self, event) -> None:
        if event.button != 1:  # left click only
            return
        pin = self._pin_at(event)
        if pin is None or pin.channel is None:  # GND / shield / empty space
            return
        self._annset.cycle(self._connector, pin.channel)
        self.render()
        self.changed.emit()

    # ---- title / legend (LayoutCanvas hooks) -------------------------------
    def _title(self, drawing: Drawing) -> str:
        faulty = sum(p.status == "faulty" for p in drawing.pins)
        susp = sum(p.status == "suspicious" for p in drawing.pins)
        return f"{drawing.title} — {faulty} faulty, {susp} suspicious"

    def _legend(self, drawing: Drawing) -> list[Line2D]:
        present = {p.status for p in drawing.pins}
        handles: list[Line2D] = []
        for status, (label, color) in ANNOTATION_STATES.items():
            if status in present:
                handles.append(Line2D([], [], marker="o", ls="", color=color,
                                      label=label, markersize=7))
        if present & {"clear", "unmapped"}:
            handles.append(Line2D([], [], marker="o", ls="", label="No comment",
                                  markerfacecolor=CLEAR_FILL,
                                  markeredgecolor=CLEAR_STROKE, color="none",
                                  markersize=7))
        return handles
