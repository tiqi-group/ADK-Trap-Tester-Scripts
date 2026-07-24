"""Tile several single-connector layouts into one multi-instance picture.

The built-in DSUB-50 / FPC layouts describe *one* connector. A real matrix setup
has several (the trap tester has 8 DSUB banks), and — now that the canvas zooms
and pans — it is useful to see them all at once. :func:`tile_connector_layouts`
lays a list of identical single-connector layouts out in a grid, offsetting each
one's slots and background so they don't overlap, and labels every tile with its
connector number. The result is an ordinary :class:`InterfaceLayout`, so the
mapping / drawing / hit-testing code needs no special case.
"""

from __future__ import annotations

import math
from dataclasses import replace

from trap_tester.core.layout.interface import InterfaceLayout, Slot, SlotShape
from trap_tester.core.layout.primitives import Circle, Line, Polyline, Rect, Text

# Built-in DSUB/FPC tiles already carry a "… connector N …" title in their own
# background, so the tiler does not add its own connector label (it would just
# overprint that title).

# How many DSUB connectors the tester has — the bound used to render "all"
# instances when no mapping defines the connector set.
TESTER_CONNECTORS = 8


def _shift_points(points: list[list[float]], dx: float, dy: float) -> list[list[float]]:
    return [[p[0] + dx, p[1] + dy] for p in points]


def _shift_primitive(prim, dx: float, dy: float):
    if isinstance(prim, Circle):
        return replace(prim, x=prim.x + dx, y=prim.y + dy)
    if isinstance(prim, Rect):
        return replace(prim, x=prim.x + dx, y=prim.y + dy)
    if isinstance(prim, Line):
        return replace(prim, x1=prim.x1 + dx, y1=prim.y1 + dy,
                       x2=prim.x2 + dx, y2=prim.y2 + dy)
    if isinstance(prim, Polyline):
        return replace(prim, points=_shift_points(prim.points, dx, dy))
    if isinstance(prim, Text):
        return replace(prim, x=prim.x + dx, y=prim.y + dy)
    return prim


def _shift_shape(sh: SlotShape, dx: float, dy: float) -> SlotShape:
    pts = None if sh.points is None else _shift_points(sh.points, dx, dy)
    return replace(sh, x=sh.x + dx, y=sh.y + dy, points=pts)


def _shift_slot(slot: Slot, dx: float, dy: float) -> Slot:
    return replace(
        slot, x=slot.x + dx, y=slot.y + dy,
        shapes=[_shift_shape(s, dx, dy) for s in slot.shapes],
    )


def _primitive_bounds(prim) -> tuple[float, float, float, float]:
    if isinstance(prim, Circle):
        return prim.x - prim.r, prim.x + prim.r, prim.y - prim.r, prim.y + prim.r
    if isinstance(prim, Rect):
        return (prim.x - prim.w / 2, prim.x + prim.w / 2,
                prim.y - prim.h / 2, prim.y + prim.h / 2)
    if isinstance(prim, Line):
        return (min(prim.x1, prim.x2), max(prim.x1, prim.x2),
                min(prim.y1, prim.y2), max(prim.y1, prim.y2))
    if isinstance(prim, Polyline) and prim.points:
        xs = [p[0] for p in prim.points]
        ys = [p[1] for p in prim.points]
        return min(xs), max(xs), min(ys), max(ys)
    if isinstance(prim, Text):
        return prim.x, prim.x, prim.y, prim.y
    return 0.0, 0.0, 0.0, 0.0


def _layout_bounds(layout: InterfaceLayout) -> tuple[float, float, float, float]:
    """``(xmin, xmax, ymin, ymax)`` covering a layout's slots and background."""
    xs: list[float] = []
    ys: list[float] = []
    for slot in layout.slots:
        for sh in slot.iter_shapes():
            xmin, xmax, ymin, ymax = sh.extent()
            xs += [xmin, xmax]
            ys += [ymin, ymax]
    for prim in layout.background:
        xmin, xmax, ymin, ymax = _primitive_bounds(prim)
        xs += [xmin, xmax]
        ys += [ymin, ymax]
    if not xs or not ys:
        return 0.0, 1.0, 0.0, 1.0
    return min(xs), max(xs), min(ys), max(ys)


def tile_connector_layouts(
    layouts: list[InterfaceLayout],
    connectors: list[int],
    name: str,
    cols: int | None = None,
) -> InterfaceLayout:
    """Combine identical single-connector ``layouts`` into one tiled layout.

    Tiles are placed in a grid (left→right, top→bottom); ``cols`` defaults to a
    count that keeps the whole arrangement roughly square given the tile's aspect
    ratio (so a wide FPC ribbon stacks vertically, a squarer DSUB spreads out).
    Each tile keeps its slots' ``connector`` stamp, so a mapping still re-wires it
    and findings/marks colour the right connector; the built-in tiles already
    label their own connector, so no extra label is added.
    """
    if not layouts:
        return InterfaceLayout(name=name)
    if len(layouts) == 1:
        return layouts[0]

    xmin, xmax, ymin, ymax = _layout_bounds(layouts[0])
    width = (xmax - xmin) or 1.0
    height = (ymax - ymin) or 1.0
    gap_x = 0.12 * width
    gap_y = 0.28 * height

    n = len(layouts)
    if cols is None:
        cols = max(1, min(n, round(math.sqrt(n * height / width))))

    slots: list[Slot] = []
    background: list = []
    for i, (lay, _connector) in enumerate(zip(layouts, connectors)):
        col, row = i % cols, i // cols
        dx = col * (width + gap_x)
        dy = -row * (height + gap_y)
        slots += [_shift_slot(s, dx, dy) for s in lay.slots]
        background += [_shift_primitive(p, dx, dy) for p in lay.background]
    return InterfaceLayout(
        name=name, units=layouts[0].units, key_by=layouts[0].key_by,
        background=background, slots=slots,
    )


__all__ = ["TESTER_CONNECTORS", "tile_connector_layouts"]
