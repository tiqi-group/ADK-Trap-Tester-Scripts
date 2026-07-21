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
from matplotlib.patches import Circle as MplCircle
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.patches import Rectangle as MplRect
from matplotlib.transforms import Affine2D
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from trap_tester.core.layout import Circle, Drawing, Line, Polyline, Rect, Text
from trap_tester.core.layout.flavor import FLAVOR_INFO

if TYPE_CHECKING:
    from trap_tester.core.layout.interface import PinMark

# A legend entry as plain data: (label, fill colour, edge colour). Rendered as Qt
# widgets beside the canvas, not drawn on it — so zoom/pan never disturbs it.
LegendItem = tuple[str, str, str]

_FINGER_ASPECT = 0.32  # width / length of an elongated "finger" pad
_ZOOM_STEP = 1.2       # limits shrink/grow by this factor per wheel notch
_DRAG_PX = 3           # a press that moves less than this is a click, not a pan

# (xlim, ylim) axis limits
_Lims = tuple[tuple[float, float], tuple[float, float]]


def text_color_for(fill: str) -> str:
    """Black or white in-pin label, whichever contrasts with ``fill``."""
    try:
        r, g, b = (int(fill[i : i + 2], 16) for i in (1, 3, 5))
    except (ValueError, IndexError):
        return "#222"
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "#222" if luminance > 150 else "#fff"


def _legend_row(label: str, fill: str, edge: str) -> QWidget:
    """One legend entry: a coloured swatch next to its label."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 1, 0, 1)
    lay.setSpacing(6)
    swatch = QLabel()
    swatch.setFixedSize(12, 12)
    swatch.setStyleSheet(
        f"background: {fill}; border: 1px solid {edge}; border-radius: 6px;"
    )
    lay.addWidget(swatch)
    lay.addWidget(QLabel(label))
    lay.addStretch(1)
    return row


class LayoutCanvas(QWidget):
    """A matplotlib canvas that paints a :class:`Drawing` and hovers its pins."""

    def __init__(self) -> None:
        super().__init__()
        self.fig = Figure(figsize=(5, 3.2))
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.canvas.setProperty("role", "viewer")
        # Absorb all spare vertical space so the controls row a subclass stacks
        # above stays at its natural height instead of splitting the column.
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # The figure holds ONLY the axes now (title + legend are Qt widgets), so
        # the axes fills it entirely. No constrained layout — that recomputed the
        # axes position on resize and left patch clip-boxes stale (circles clipped
        # to a narrower rectangle than the data spanned).
        self.ax = self.fig.add_axes((0.0, 0.0, 1.0, 1.0))
        self._pins: list[PinMark] = []
        # view state: _fit_lims fits the whole drawing; _preserved_lims is the
        # current zoom/pan kept across re-renders (None => fit on next draw).
        self._fit_lims: _Lims | None = None
        self._preserved_lims: _Lims | None = None
        self._pan_start_pix: tuple[float, float] | None = None
        self._pan_start_lims: _Lims | None = None
        self._dragged = False
        self._make_annot()

        # Widget layout: an (optional) controls bar a subclass fills, the title
        # as a QLabel, then the canvas beside a legend strip. Title + legend are
        # Qt widgets — never drawn on the axes — so zoom/pan can't disturb them.
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)
        self._controls_bar = QWidget()
        self._controls_layout = QHBoxLayout(self._controls_bar)
        self._controls_layout.setContentsMargins(0, 0, 0, 0)
        self._controls_bar.setVisible(False)  # shown once a subclass adds controls
        root.addWidget(self._controls_bar)
        self._title_label = QLabel("")
        self._title_label.setAlignment(Qt.AlignCenter)
        self._title_label.setStyleSheet("color: #b83a20; font-weight: bold;")
        root.addWidget(self._title_label)
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.addWidget(self.canvas, 1)
        self._legend_bar = QWidget()
        self._legend_layout = QVBoxLayout(self._legend_bar)
        self._legend_layout.setContentsMargins(4, 4, 4, 4)
        self._legend_layout.setAlignment(Qt.AlignTop)
        self._legend_bar.setVisible(False)
        mid.addWidget(self._legend_bar)
        root.addLayout(mid, 1)

        self.canvas.mpl_connect("motion_notify_event", self._on_motion)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self.canvas.mpl_connect("button_press_event", self._on_press)
        self.canvas.mpl_connect("button_release_event", self._on_release)
        self.canvas.mpl_connect("resize_event", self._on_resize)

    def add_control(self, widget: QWidget) -> None:
        """Add a control widget to the bar above the title (used by subclasses)."""
        self._controls_layout.addWidget(widget)
        self._controls_bar.setVisible(True)

    # ---- public API --------------------------------------------------------
    def clear(self, message: str) -> None:
        self._pins = []
        self._fit_lims = None
        self._preserved_lims = None  # nothing to zoom into
        self._title_label.setText(message)
        self._render_legend([])
        self.ax.clear()
        self.ax.set_xticks([])
        self.ax.set_yticks([])
        self._make_annot()  # ax.clear() removed it
        self.canvas.draw_idle()

    def reset_view(self) -> None:
        """Drop any zoom/pan and fit the whole drawing (double-click action)."""
        self._preserved_lims = None
        if self._fit_lims is not None:
            self._apply_lims(*self._fit_lims)
            self.canvas.draw_idle()

    def _apply_lims(self, xlim: tuple[float, float], ylim: tuple[float, float]) -> None:
        """Set limits, expanding one axis so data-per-pixel is equal (round pins).

        With ``aspect="auto"`` the axes fills the canvas; matching the data span
        to the pixel span in both directions keeps circles circular. The wider
        axis is kept and the other grown about its centre.
        """
        bbox = self.ax.get_window_extent()
        w, h = bbox.width, bbox.height
        if w > 0 and h > 0:
            xr, yr = xlim[1] - xlim[0], ylim[1] - ylim[0]
            if xr / w >= yr / h:  # x limits the view -> grow y to match
                yc, half = (ylim[0] + ylim[1]) / 2, xr / w * h / 2
                ylim = (yc - half, yc + half)
            else:                 # y limits the view -> grow x to match
                xc, half = (xlim[0] + xlim[1]) / 2, yr / h * w / 2
                xlim = (xc - half, xc + half)
        self.ax.set_xlim(*xlim)
        self.ax.set_ylim(*ylim)

    def fit_on_next_draw(self) -> None:
        """Make the next :meth:`show_drawing` fit instead of keeping the view.

        Subclasses call this on a genuine content change (new layout / connector /
        result); re-renders of the *same* content omit it, so zoom/pan persists.
        """
        self._preserved_lims = None

    def show_drawing(self, drawing: Drawing) -> None:
        ax = self.ax
        ax.clear()
        # The axes fills the whole canvas (aspect="auto"); we keep pins circular
        # ourselves in _apply_lims by matching data-per-pixel in x and y. This
        # way the title sits at the top of the window and pan/zoom (which rely on
        # event.inaxes) work everywhere — not only inside a shrunk, centred box.
        ax.set_aspect("auto")
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)

        for prim in drawing.background:
            self._draw_primitive(prim)

        self._pins = drawing.pins
        for pin in drawing.pins:
            self._draw_pin(pin)

        self._title_label.setText(self._title(drawing))
        xmin, xmax, ymin, ymax = drawing.bounds()
        self._fit_lims = ((xmin, xmax), (ymin, ymax))
        # keep the current zoom/pan across re-renders, else fit the whole drawing
        self._apply_lims(*(self._preserved_lims or self._fit_lims))
        self._make_annot()
        self._render_legend(self._legend(drawing))
        self.canvas.draw_idle()

    # ---- hooks for subclasses ----------------------------------------------
    def _title(self, drawing: Drawing) -> str:
        return drawing.title

    def _legend(self, drawing: Drawing) -> list[LegendItem]:
        return []

    def _flavor_legend(self, drawing: Drawing) -> list[LegendItem]:
        """Legend entries for the fixed-colour flavor pads in the background.

        Flavor pads (GND / axialisation / …) are static background circles, so we
        recover which classes are present by matching their fill colour against
        :data:`FLAVOR_INFO`. Shared by every layout view so all tabs agree.
        """
        fills = {p.fill for p in drawing.background if isinstance(p, Circle)}
        return [(label, fill, stroke)
                for label, fill, stroke in FLAVOR_INFO.values() if fill in fills]

    def _render_legend(self, items: list[LegendItem]) -> None:
        """Rebuild the Qt legend strip beside the canvas from ``items``."""
        while self._legend_layout.count():
            w = self._legend_layout.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        for label, fill, edge in items:
            self._legend_layout.addWidget(_legend_row(label, fill, edge))
        self._legend_bar.setVisible(bool(items))

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
        if pin.shape == "finger":
            # an elongated pad oriented by ``rot`` (e.g. a bond finger)
            length, width = 2 * pin.r, 2 * pin.r * _FINGER_ASPECT
            patch = MplRect(
                (pin.x - length / 2, pin.y - width / 2), length, width,
                facecolor=pin.fill, edgecolor=pin.stroke, lw=0.5, zorder=3)
            patch.set_transform(
                Affine2D().rotate_deg_around(pin.x, pin.y, pin.rot) + ax.transData)
        elif pin.shape == "rect":
            patch = MplRect(
                (pin.x - pin.r, pin.y - pin.r), 2 * pin.r, 2 * pin.r,
                facecolor=pin.fill, edgecolor=pin.stroke, lw=1.1, zorder=3)
        else:
            patch = MplCircle((pin.x, pin.y), pin.r, facecolor=pin.fill,
                              edgecolor=pin.stroke, lw=1.1, zorder=3)
        ax.add_patch(patch)
        if pin.label:
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

    # ---- zoom + pan --------------------------------------------------------
    def _remember_view(self) -> None:
        self._preserved_lims = (self.ax.get_xlim(), self.ax.get_ylim())

    def _on_scroll(self, event) -> None:
        """Wheel: zoom towards the cursor (up = in, down = out)."""
        if event.inaxes is not self.ax or event.xdata is None:
            return
        scale = 1 / _ZOOM_STEP if event.button == "up" else _ZOOM_STEP
        cx, cy = event.xdata, event.ydata
        x0, x1 = self.ax.get_xlim()
        y0, y1 = self.ax.get_ylim()
        self._apply_lims((cx + (x0 - cx) * scale, cx + (x1 - cx) * scale),
                         (cy + (y0 - cy) * scale, cy + (y1 - cy) * scale))
        self._remember_view()
        self.canvas.draw_idle()

    def _on_press(self, event) -> None:
        if event.x is None or event.inaxes is not self.ax:
            return
        if event.dblclick:
            self.reset_view()
            return
        if event.button == 1:  # begin a possible pan (or a click, if it doesn't move)
            self._pan_start_pix = (event.x, event.y)
            self._pan_start_lims = (self.ax.get_xlim(), self.ax.get_ylim())
            self._dragged = False

    def _on_motion(self, event) -> None:
        if self._pan_start_pix is not None:
            self._do_pan(event)
            return
        self._on_hover(event)

    def _do_pan(self, event) -> None:
        if event.x is None or self._pan_start_lims is None:
            return
        dx_pix = event.x - self._pan_start_pix[0]
        dy_pix = event.y - self._pan_start_pix[1]
        if abs(dx_pix) + abs(dy_pix) > _DRAG_PX:
            self._dragged = True
            self._hide_annot()
        bbox = self.ax.get_window_extent()
        (x0, x1), (y0, y1) = self._pan_start_lims
        dx = -dx_pix / bbox.width * (x1 - x0)   # from the press lims -> no drift
        dy = -dy_pix / bbox.height * (y1 - y0)
        self._apply_lims((x0 + dx, x1 + dx), (y0 + dy, y1 + dy))
        self.canvas.draw_idle()

    def _on_resize(self, event) -> None:
        # re-equalise data-per-pixel so pins stay circular after a window resize
        lims = self._preserved_lims or self._fit_lims
        if lims is not None:
            self._apply_lims(*lims)

    def _on_release(self, event) -> None:
        if self._pan_start_pix is None:
            return
        dragged = self._dragged
        self._pan_start_pix = None
        if dragged:
            self._remember_view()  # persist the pan across re-renders
        else:
            self._on_canvas_click(event)  # a click, not a drag

    def _on_canvas_click(self, event) -> None:
        """Left-click that wasn't a drag. Subclasses override (e.g. to mark)."""
