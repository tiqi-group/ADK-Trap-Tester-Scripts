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
    """

    connector: int
    pin: int
    x: float
    y: float
    r: float = 0.38
    rot: float = 0.0
    shape: str = "circle"  # circle | rect
    channel: int | None = None  # canonical mux signal; None = unmapped
    label: str | None = None  # in-shape text; None -> str(pin). "" hides it.

    @property
    def display_label(self) -> str:
        """Text drawn inside the shape (the pin number unless overridden)."""
        return self.label if self.label is not None else str(self.pin)

    def to_dict(self) -> dict[str, Any]:
        return {
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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Slot:
        raw_channel = data.get("channel")
        raw_label = data.get("label")
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
    rot: float = 0.0  # degrees; orients an elongated "finger" shape


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
            pins.append(
                PinMark(
                    x=slot.x, y=slot.y, r=slot.r, shape=slot.shape,
                    connector=slot.connector, pin=slot.pin,
                    status=f.status, fill=color, stroke="#333",
                    label=slot.display_label, message=f.message, measured=True,
                    channel=slot.channel, rot=slot.rot,
                )
            )
        else:
            pins.append(
                PinMark(
                    x=slot.x, y=slot.y, r=slot.r, shape=slot.shape,
                    connector=slot.connector, pin=slot.pin,
                    status="unmeasured", fill=UNMEASURED_FILL,
                    stroke=UNMEASURED_STROKE, label=slot.display_label,
                    message=f"Pin {slot.pin}: not measured", measured=False,
                    channel=slot.channel, rot=slot.rot,
                )
            )

    return Drawing(title=result.title, background=list(layout.background), pins=pins)


__all__ = [
    "Slot",
    "InterfaceLayout",
    "PinMark",
    "Drawing",
    "build_drawing",
    "UNMEASURED_FILL",
    "UNMEASURED_STROKE",
]
