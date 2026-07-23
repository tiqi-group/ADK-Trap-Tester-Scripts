"""Interface layouts: map a measured signal to a shape on a sketch.

An :class:`InterfaceLayout` is the data behind "draw the analysis on the
connector". It holds two things:

* ``background`` — static primitives (the connector outline, row labels, …) that
  help a human read the result but never change with the data.
* ``slots`` — a ``(connector, pin) -> shape`` mapping. Each :class:`Slot` says
  where a signal lives on the sketch (position, radius, rotation, shape).

The whole thing round-trips to JSON, so a new interface (a different connector,
an FPC ribbon, a trap-electrode diagram, …) is just a different JSON file. What
counts as "pin" is set by ``key_by``: with ``"dsub_pin"`` a slot matches a
finding by its DSUB pin, with ``"fpc_conductor"`` it matches by FPC conductor —
so the *same* findings can be drawn on a different interface by swapping the
layout and its key.

:func:`build_drawing` combines a layout with an :class:`AnalysisResult` into a
flat :class:`Drawing` (background primitives + coloured :class:`PinMark` s) that
any renderer can paint and hit-test for hover.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.layout.primitives import (
    Circle,
    Line,
    Polyline,
    Rect,
    Text,
    primitive_from_dict,
)

if TYPE_CHECKING:  # avoid importing the (pandas-heavy) analysis package eagerly
    from trap_tester.core.analysis import AnalysisResult

_Primitive = (Circle, Rect, Line, Polyline, Text)

# Slots with no measured finding are drawn as a faint empty outline so the whole
# connector is always visible even when only some pins were tested.
UNMEASURED_FILL = "#efefef"
UNMEASURED_STROKE = "#b0b0b0"

_KEY_ATTR = {"dsub_pin": "dsub_pin", "fpc_conductor": "fpc_conductor"}


@dataclass
class SlotShape:
    """One drawable primitive of a slot's geometry.

    A simple pad is a ``"circle"`` / ``"rect"`` / ``"finger"`` positioned at
    ``(x, y)`` with radius ``r`` and rotation ``rot``. An arbitrary electrode is a
    ``"poly"`` whose outline is ``points`` (``[[x, y], …]``); for a polygon ``x``
    / ``y`` are the bounding-box centre (label + hover anchor) and ``r`` a
    bounding radius, both derived from ``points`` by :meth:`from_polygon`.
    """

    shape: str = "circle"  # circle | rect | finger | poly
    x: float = 0.0
    y: float = 0.0
    r: float = 0.38
    rot: float = 0.0
    points: list[list[float]] | None = None  # outline for shape == "poly"

    @classmethod
    def from_polygon(cls, points: list[list[float]]) -> SlotShape:
        """A ``"poly"`` shape with centre/radius derived from its outline."""
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
        r = max(max(xs) - min(xs), max(ys) - min(ys)) / 2
        pts = [[float(p[0]), float(p[1])] for p in points]
        return cls(shape="poly", x=cx, y=cy, r=r, points=pts)

    def extent(self) -> tuple[float, float, float, float]:
        """``(xmin, xmax, ymin, ymax)`` covering this shape."""
        if self.shape == "poly" and self.points:
            xs = [p[0] for p in self.points]
            ys = [p[1] for p in self.points]
            return min(xs), max(xs), min(ys), max(ys)
        return self.x - self.r, self.x + self.r, self.y - self.r, self.y + self.r

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "shape": self.shape, "x": self.x, "y": self.y, "r": self.r, "rot": self.rot,
        }
        if self.points is not None:
            data["points"] = self.points
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SlotShape:
        raw_pts = data.get("points")
        return cls(
            shape=str(data.get("shape", "circle")),
            x=float(data.get("x", 0.0)),
            y=float(data.get("y", 0.0)),
            r=float(data.get("r", 0.38)),
            rot=float(data.get("rot", 0.0)),
            points=None if raw_pts is None else [[float(a), float(b)] for a, b in raw_pts],
        )


@dataclass
class Slot:
    """Where one signal sits on the sketch.

    ``pin`` is the value matched under the layout's ``key_by`` (a DSUB pin for
    the default ``"dsub_pin"``, an FPC conductor for ``"fpc_conductor"``).

    ``channel`` is the *canonical* channel identity this slot carries — the
    ``mux_mapping`` signal number, stamped at generation time. It is what makes
    the JSON a cross-interface translation layer: two layouts (a DSUB connector
    and an FPC ribbon, say) put the *same* physical channel on slots that share a
    ``channel``, so a mark placed on one interface can be re-projected onto the
    other purely from the JSON, with no runtime pin↔conductor lookup. ``None``
    for slots that map to no channel (a GND / spare / unconnected contact).

    ``ident`` is this interface's own per-net identifier — the LGA pad name, bond
    finger number or electrode name that a cross-interface *mapping* CSV lists in
    the column named after this layout. It is what lets a setup-specific mapping
    re-wire the slot (see :mod:`trap_tester.core.layout.mapping`); ``None`` for the
    reference ``(connector, pin)`` interfaces (DSUB-50 / FPC) that a mapping matches
    by connector and pin instead.

    A slot is ONE logical pad with ONE measurement identity, but may be *drawn*
    as several primitives — an ion-trap electrode net is several polygons on the
    one ``(connector, pin)``. ``shapes`` holds that geometry; when empty the slot
    is drawn from the flat ``x/y/r/rot/shape`` fields (the single-shape case, and
    what all existing layouts use). Every shape shares the slot's status and
    mark, so marking one co-wired pad marks the whole net for free.
    """

    connector: int
    pin: int
    x: float
    y: float
    r: float = 0.38
    rot: float = 0.0
    shape: str = "circle"  # circle | rect | finger | poly
    channel: int | None = None  # canonical mux signal; None = unmapped
    label: str | None = None  # in-shape text; None -> str(pin). "" hides it.
    ident: str | None = None  # per-interface identifier (LGA pad / finger / electrode)
    shapes: list[SlotShape] = field(default_factory=list)  # empty -> single shape

    @property
    def display_label(self) -> str:
        """Text drawn inside the shape (the pin number unless overridden)."""
        return self.label if self.label is not None else str(self.pin)

    def iter_shapes(self) -> Iterator[SlotShape]:
        """Yield the slot's drawn shapes (the flat single shape when unset)."""
        if self.shapes:
            yield from self.shapes
        else:
            yield SlotShape(shape=self.shape, x=self.x, y=self.y, r=self.r, rot=self.rot)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "connector": self.connector,
            "pin": self.pin,
            "x": self.x,
            "y": self.y,
            "r": self.r,
            "rot": self.rot,
            "shape": self.shape,
            "channel": self.channel,
            "label": self.label,
        }
        if self.ident is not None:
            data["ident"] = self.ident
        if self.shapes:
            data["shapes"] = [s.to_dict() for s in self.shapes]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Slot:
        raw_channel = data.get("channel")
        raw_label = data.get("label")
        raw_ident = data.get("ident")
        raw_shapes = data.get("shapes")
        return cls(
            connector=int(data["connector"]),
            pin=int(data["pin"]),
            x=float(data["x"]),
            y=float(data["y"]),
            r=float(data.get("r", 0.38)),
            rot=float(data.get("rot", 0.0)),
            shape=str(data.get("shape", "circle")),
            channel=None if raw_channel is None else int(raw_channel),
            label=None if raw_label is None else str(raw_label),
            ident=None if raw_ident is None else str(raw_ident),
            shapes=[SlotShape.from_dict(s) for s in raw_shapes] if raw_shapes else [],
        )


@dataclass
class InterfaceLayout:
    name: str
    units: str = "mm"
    key_by: str = "dsub_pin"  # which Finding attribute a slot's ``pin`` matches
    background: list[Any] = field(default_factory=list)  # primitives
    slots: list[Slot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "units": self.units,
            "key_by": self.key_by,
            "background": [p.to_dict() for p in self.background],
            "slots": [s.to_dict() for s in self.slots],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterfaceLayout:
        if data.get("key_by", "dsub_pin") not in _KEY_ATTR:
            raise ValueError(f"Unsupported key_by {data.get('key_by')!r}")
        return cls(
            name=str(data["name"]),
            units=str(data.get("units", "mm")),
            key_by=str(data.get("key_by", "dsub_pin")),
            background=[primitive_from_dict(p) for p in data.get("background", [])],
            slots=[Slot.from_dict(s) for s in data.get("slots", [])],
        )

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load_json(cls, path: str | Path) -> InterfaceLayout:
        return cls.from_dict(json.loads(Path(path).read_text()))


@dataclass
class PinMark:
    """One drawn, hit-testable signal shape carrying its verdict."""

    x: float
    y: float
    r: float
    shape: str
    connector: int
    pin: int
    status: str  # STATUS_INFO key, or "unmeasured"
    fill: str
    stroke: str
    label: str  # short in-shape label (the pin number)
    message: str  # full finding text, shown on hover
    measured: bool
    channel: int | None = None  # canonical channel; lets a click resolve identity
    ident: str | None = None  # per-interface identifier (LGA pad / finger / electrode)
    rot: float = 0.0  # degrees; orients an elongated "finger" shape
    points: list[list[float]] | None = None  # outline when shape == "poly"


def slot_pins(
    slot: Slot,
    *,
    status: str,
    fill: str,
    stroke: str,
    message: str,
    measured: bool,
    label: str | None = None,
) -> list[PinMark]:
    """Expand a slot into one :class:`PinMark` per drawn shape.

    Every shape carries the slot's identity (``connector`` / ``pin`` / ``channel``)
    and the same verdict, so they colour together and a click on any of them
    resolves to the one net. The label is drawn on the first shape only.
    """
    lbl = slot.display_label if label is None else label
    marks: list[PinMark] = []
    for i, sh in enumerate(slot.iter_shapes()):
        marks.append(
            PinMark(
                x=sh.x, y=sh.y, r=sh.r, shape=sh.shape,
                connector=slot.connector, pin=slot.pin, status=status,
                fill=fill, stroke=stroke, label=lbl if i == 0 else "",
                message=message, measured=measured, channel=slot.channel,
                ident=slot.ident, rot=sh.rot, points=sh.points,
            )
        )
    return marks


@dataclass
class Drawing:
    """A flat, renderer-ready picture: static background + coloured pins."""

    title: str
    background: list[Any]
    pins: list[PinMark]

    def bounds(self, margin: float = 0.6) -> tuple[float, float, float, float]:
        """Return ``(xmin, xmax, ymin, ymax)`` covering everything drawn."""
        xs: list[float] = []
        ys: list[float] = []
        for p in self.pins:
            if p.shape == "poly" and p.points:
                xs += [pt[0] for pt in p.points]
                ys += [pt[1] for pt in p.points]
            else:
                xs += [p.x - p.r, p.x + p.r]
                ys += [p.y - p.r, p.y + p.r]
        for prim in self.background:
            if isinstance(prim, Circle):
                xs += [prim.x - prim.r, prim.x + prim.r]
                ys += [prim.y - prim.r, prim.y + prim.r]
            elif isinstance(prim, Rect):
                xs += [prim.x - prim.w / 2, prim.x + prim.w / 2]
                ys += [prim.y - prim.h / 2, prim.y + prim.h / 2]
            elif isinstance(prim, Line):
                xs += [prim.x1, prim.x2]
                ys += [prim.y1, prim.y2]
            elif isinstance(prim, Polyline):
                xs += [pt[0] for pt in prim.points]
                ys += [pt[1] for pt in prim.points]
            elif isinstance(prim, Text):
                xs.append(prim.x)
                ys.append(prim.y)
        if not xs or not ys:
            return (0.0, 1.0, 0.0, 1.0)
        return (min(xs) - margin, max(xs) + margin, min(ys) - margin, max(ys) + margin)


def build_drawing(result: AnalysisResult, layout: InterfaceLayout) -> Drawing:
    """Colour ``layout``'s slots by the verdicts in ``result``.

    Every slot becomes a :class:`PinMark`: matched slots take their finding's
    status colour, unmatched slots are drawn faint ("unmeasured"). Findings with
    no slot in the layout are ignored (they simply have nowhere to be drawn).
    """
    from trap_tester.core.analysis import STATUS_INFO

    key_attr = _KEY_ATTR[layout.key_by]
    by_key: dict[tuple[int, int], Any] = {}
    for f in result.findings:
        k = getattr(f, key_attr)
        if k is None:
            continue
        by_key[(int(f.connector), int(k))] = f

    pins: list[PinMark] = []
    for slot in layout.slots:
        f = by_key.get((slot.connector, slot.pin))
        if f is not None:
            _label, color = STATUS_INFO.get(f.status, (f.status, "#000"))
            pins += slot_pins(
                slot, status=f.status, fill=color, stroke="#333",
                message=f.message, measured=True,
            )
        else:
            pins += slot_pins(
                slot, status="unmeasured", fill=UNMEASURED_FILL,
                stroke=UNMEASURED_STROKE, message=f"Pin {slot.pin}: not measured",
                measured=False,
            )

    return Drawing(title=result.title, background=list(layout.background), pins=pins)


__all__ = [
    "Slot",
    "SlotShape",
    "InterfaceLayout",
    "PinMark",
    "Drawing",
    "build_drawing",
    "slot_pins",
    "UNMEASURED_FILL",
    "UNMEASURED_STROKE",
]
