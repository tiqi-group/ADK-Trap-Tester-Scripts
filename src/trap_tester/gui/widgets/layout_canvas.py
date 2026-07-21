"""Shared matplotlib canvas for painting a :class:`~trap_tester.core.layout.Drawing`.

Both the analysis connector map (``ConnectorView``) and the interactive
annotation view (``AnnotationView``) build on this: it turns the layout engine's
geometric primitives + coloured pins into matplotlib artists and reports the pin
under the cursor on hover. Subclasses supply their own title and legend (their
status vocabulary differs) and add their own controls around the canvas; the
drawing, hit-testing and hover tooltip live here once.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle as MplCircle
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.patches import Rectangle as MplRect
from matplotlib.transforms import Affine2D
from PySide6.QtWidgets import QSizePolicy, QWidget

from trap_tester.core.layout import Circle, Drawing, Line, Polyline, Rect, Text
from trap_tester.core.layout.flavor import FLAVOR_INFO

if TYPE_CHECKING:
    from trap_tester.core.layout.interface import PinMark

TITLE_KW = dict(fontsize=10, fontweight="bold", color="#b83a20")


def text_color_for(fill: str) -> str:
    """Black or white in-pin label, whichever contrasts with ``fill``."""
    try:
        r, g, b = (int(fill[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return "#222"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#222" if luminance > 150 else "#fff"


class LayoutCanvas(QWidget):
    """A matplotlib canvas that paints a :class:`Drawing` and hovers its pins."""

    def __init__(self) -> None:
        super().__init__()
        self.fig = Figure(figsize=(5, 3.2), layout="constrained")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setProperty("role", "viewer")
        # Absorb all spare vertical space so the controls row a subclass stacks
        # above stays at its natural height instead of splitting the column.
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax = self.fig.add_subplot(111)
        self._pins: list[PinMark] = []
        self._make_annot()
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)

    # ---- public API --------------------------------------------------------
    def clear(self, message: str) -> None:
        self._pins = []
        self.ax.clear()
        self.ax.set_title(message, **TITLE_KW)
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self._make_annot()  # ax.clear() removed it
        self.canvas.draw_idle()

    def show_drawing(self, drawing: Drawing) -> None:
        ax = self.ax
        ax.clear()
        ax.set_aspect("equal")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        for prim in drawing.background:
            self._draw_primitive(prim)

        self._pins = drawing.pins
        for pin in drawing.pins:
            self._draw_pin(pin)

        ax.set_title(self._title(drawing), **TITLE_KW)
        xmin, xmax, ymin, ymax = drawing.bounds()
        ax.set_xlim(xmin, xmax)
        ax.set_ylim(ymin, ymax)
        self._make_annot()

        handles = self._legend(drawing)
        if handles:
            ax.legend(handles=handles, fontsize=7, loc="center left",
                      bbox_to_anchor=(1.02, 0.5), framealpha=0.9, borderpad=0.4)
        self.canvas.draw_idle()

    # ---- hooks for subclasses ----------------------------------------------
    def _title(self, drawing: Drawing) -> str:
        return drawing.title

    def _legend(self, drawing: Drawing) -> list[Line2D]:
        return []

    def _flavor_legend(self, drawing: Drawing) -> list[Line2D]:
        """Legend handles for the fixed-colour flavor pads in the background.

        Flavor pads (GND / axialisation / …) are static background circles, so we
        recover which classes are present by matching their fill colour against
        :data:`FLAVOR_INFO`. Shared by every layout view so all tabs agree.
        """
        fills = {p.fill for p in drawing.background if isinstance(p, Circle)}
        return [
            Line2D([], [], marker="o", ls="", label=label, color="none",
                   markerfacecolor=fill, markeredgecolor=stroke, markersize=7)
            for label, fill, stroke in FLAVOR_INFO.values()
            if fill in fills
        ]

    # ---- drawing helpers ---------------------------------------------------
    def _make_annot(self) -> None:
        self._annot = self.ax.annotate(
            "", xy=(0, 0), xytext=(12, 12), textcoords="offset points",
            fontsize=8, ha="left", va="bottom", zorder=10,
            bbox=dict(boxstyle="round", fc="#ffffe0", ec="#888", alpha=0.95),
        )
        self._annot.set_visible(False)

    def _draw_primitive(self, prim) -> None:
        ax = self.ax
        if isinstance(prim, Circle):
            ax.add_patch(MplCircle(
                (prim.x, prim.y), prim.r, facecolor=prim.fill or "none",
                edgecolor=prim.stroke or "none", lw=prim.width, zorder=1))
        elif isinstance(prim, Rect):
            patch = MplRect(
                (prim.x - prim.w / 2, prim.y - prim.h / 2), prim.w, prim.h,
                facecolor=prim.fill or "none", edgecolor=prim.stroke or "none",
                lw=prim.width, zorder=1)
            if prim.rotation:
                patch.set_transform(
                    Affine2D().rotate_deg_around(prim.x, prim.y, prim.rotation)
                    + ax.transData)
            ax.add_patch(patch)
        elif isinstance(prim, Line):
            ax.plot([prim.x1, prim.x2], [prim.y1, prim.y2],
                    color=prim.stroke or "#444", lw=prim.width, zorder=1)
        elif isinstance(prim, Polyline):
            if prim.closed:
                ax.add_patch(MplPolygon(
                    prim.points, closed=True, facecolor=prim.fill or "none",
                    edgecolor=prim.stroke or "none", lw=prim.width, zorder=1))
            else:
                xs = [p[0] for p in prim.points]
                ys = [p[1] for p in prim.points]
                ax.plot(xs, ys, color=prim.stroke or "#444", lw=prim.width, zorder=1)
        elif isinstance(prim, Text):
            ax.text(prim.x, prim.y, prim.text, fontsize=prim.size, color=prim.color,
                    ha=prim.ha, va=prim.va, rotation=prim.rotation, zorder=2)

    def _draw_pin(self, pin: PinMark) -> None:
        ax = self.ax
        if pin.shape == "rect":
            patch = MplRect(
                (pin.x - pin.r, pin.y - pin.r), 2 * pin.r, 2 * pin.r,
                facecolor=pin.fill, edgecolor=pin.stroke, lw=1.1, zorder=3)
        else:
            patch = MplCircle((pin.x, pin.y), pin.r, facecolor=pin.fill,
                              edgecolor=pin.stroke, lw=1.1, zorder=3)
        ax.add_patch(patch)
        ax.text(pin.x, pin.y, pin.label, fontsize=5.5, ha="center", va="center",
                color=text_color_for(pin.fill), zorder=4)

    # ---- hit-test + hover --------------------------------------------------
    def _pin_at(self, event) -> PinMark | None:
        if event.inaxes is not self.ax or event.xdata is None or not self._pins:
            return None
        for pin in self._pins:
            if (event.xdata - pin.x) ** 2 + (event.ydata - pin.y) ** 2 <= pin.r ** 2:
                return pin
        return None

    def _on_hover(self, event) -> None:
        hit = self._pin_at(event)
        if hit is None:
            self._hide_annot()
            return
        self._annot.xy = (hit.x, hit.y)
        self._annot.set_text(hit.message)
        self._annot.set_visible(True)
        self.canvas.draw_idle()

    def _hide_annot(self) -> None:
        if self._annot.get_visible():
            self._annot.set_visible(False)
            self.canvas.draw_idle()
