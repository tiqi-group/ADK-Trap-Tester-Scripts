"""Interface layouts: map a measured signal to a shape on a sketch.

An :class:`InterfaceLayout` is the data behind "draw the analysis on the
connector". It holds two things:

* ``background`` — static *chrome* (the connector outline, row labels, …) that
  helps a human read the result but never reacts to data;
* ``slots`` — every pad on the interface, at ``(connector, pin)``. A pad declares
  what it is via :attr:`Slot.pad_class`; only ``"signal"`` pads are measurable and
  clickable, so GND / RF / loopback pads are ordinary slots rather than the
  hand-coloured background circles they were in v1.

The whole thing round-trips to JSON, so a new interface (a different connector, an
FPC ribbon, a trap-electrode diagram, …) is just a different JSON file.

Schema v2 (see ``docs/layout-schema-v2.md``):

* there is no stored channel — the canonical address is derived, by
  :func:`~trap_tester.core.layout.addressing.canonical_address`;
* geometry is always ``shapes``; the flat ``x``/``y``/``r``/``rot``/``shape``
  arguments are a convenience for single-shape pads and are normalised into one
  :class:`SlotShape` on construction;
* colours are not stored — see :mod:`trap_tester.core.layout.style`;
* ``slug`` and ``match_by`` are declared, so a mapping CSV never has to be matched
  to a layout by guesswork;
* ``pin_space`` is an open string, not a closed enum.

Only schema 2 loads. v1 files are rejected with a message pointing at the
generator — the project has had no release, so there is nothing to stay compatible
with, and a one-file-format loader is the whole point of the exercise.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.layout.addressing import is_synthetic, synthetic_addresses
from trap_tester.core.layout.primitives import (
    Circle,
    Line,
    Polyline,
    Rect,
    Text,
    primitive_from_dict,
)
from trap_tester.core.layout.style import SIGNAL_CLASS, pad_style

if TYPE_CHECKING:  # avoid importing the (pandas-heavy) analysis package eagerly
    from trap_tester.core.analysis import AnalysisResult

_Primitive = (Circle, Rect, Line, Polyline, Text)

SCHEMA_VERSION = 2

# Slots with no measured finding are drawn as a faint empty outline so the whole
# connector is always visible even when only some pins were tested.
UNMEASURED_FILL = "#efefef"
UNMEASURED_STROKE = "#b0b0b0"

# A pin number of 0 is not valid in any pin space (DSUB pins are 1..50, FPC
# conductors 1..51), so a generator uses it to mean "wiring unknown — only the
# mapping CSV knows". :func:`assign_synthetic_addresses` then gives those slots a
# distinct address in the reserved synthetic band.
UNSET_PIN = 0


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

    def mirrored_x(self, axis: float) -> SlotShape:
        """A copy mirrored horizontally about ``axis`` (front view <-> solder side)."""
        pts = None if self.points is None else [[axis - x, y] for x, y in self.points]
        return SlotShape(
            shape=self.shape, x=axis - self.x, y=self.y, r=self.r,
            rot=-self.rot, points=pts,
        )


@dataclass
class Slot:
    """One pad on the interface.

    ``(connector, pin)`` is the *apparatus'* electrical address — mandatory, and
    meaningful whether or not the tester is attached, since the tester's connector
    interface matches the physical apparatus'. ``pin`` is a number in the layout's
    ``pin_space`` (a DSUB pin, an FPC conductor, …). Correlating across pin spaces
    goes through :func:`~trap_tester.core.layout.addressing.canonical_address`;
    there is deliberately no stored channel.

    ``ident`` is this interface's own per-net identifier — the LGA pad name, bond
    finger number or electrode name that a cross-interface *mapping* CSV lists in
    the column named after this layout's ``slug``. It is an **opaque** string at
    match time: generators may parse it to place a pad on a grid, but nothing may
    decode it when joining. ``None`` for the tester's reference interfaces
    (DSUB-50 / FPC), which a mapping matches by ``(connector, pin)`` instead.

    ``pad_class`` says what the pad *is* (see
    :data:`~trap_tester.core.layout.style.PAD_CLASSES`). Only ``"signal"`` pads are
    measurable and clickable; ``"gnd"`` / ``"rf"`` / … are drawn in their fixed
    class colours and are inert.

    A slot is ONE logical pad with ONE measurement identity, but may be *drawn* as
    several primitives — an ion-trap electrode net is several polygons on the one
    ``(connector, pin)``. ``shapes`` always holds that geometry; the flat
    ``shape``/``x``/``y``/``r``/``rot`` arguments are a convenience for the
    single-shape case and are folded into one :class:`SlotShape` on construction.
    Every shape shares the slot's status and mark, so marking one co-wired pad
    marks the whole net for free.
    """

    connector: int
    pin: int
    # convenience inputs for a single-shape pad; normalised into ``shapes`` below
    x: float = 0.0
    y: float = 0.0
    r: float = 0.38
    rot: float = 0.0
    shape: str = "circle"
    ident: str | None = None
    pad_class: str = SIGNAL_CLASS
    label: str | None = None  # in-shape text; None -> ident, else pin. "" hides it.
    shapes: list[SlotShape] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.shapes:
            self.shapes = [
                SlotShape(shape=self.shape, x=self.x, y=self.y, r=self.r, rot=self.rot)
            ]
        # keep the flat fields as the anchor of the whole pad (label + hover point),
        # so they stay meaningful for a multi-shape net rather than echoing shape 0
        xmin, xmax, ymin, ymax = self.extent()
        self.x, self.y = (xmin + xmax) / 2, (ymin + ymax) / 2
        self.r = max(max(xmax - xmin, ymax - ymin) / 2, 1e-9)

    @property
    def is_signal(self) -> bool:
        """Whether this pad is measurable / clickable."""
        return self.pad_class == SIGNAL_CLASS

    @property
    def display_label(self) -> str:
        """Text drawn inside the shape.

        ``label`` is an *override*; an empty one is no override, not a request to
        draw nothing. Without it the pad's own name is used — on a trap or an LGA the
        electrode / pad name is what an operator reads — falling back to the pin
        number on the tester's own interfaces, which have no ident.

        (Treating ``""`` as "hide" is what broke every custom layout after the v2
        change: their generators write ``label: ""`` meaning "no override, use the
        ident", so the fallback became unreachable and the electrodes went blank.
        Density is the renderer's problem, handled by its label level-of-detail, so
        nothing needs a way to blank a label from the data.)

        The pin fallback is skipped on a synthetic address: that number is made up,
        and drawing it would read as a real pin. Such a pad is left unlabelled rather
        than mislabelled.
        """
        if self.label or self.ident:
            return self.label or self.ident or ""
        return "" if is_synthetic(self.connector) else str(self.pin)

    def extent(self) -> tuple[float, float, float, float]:
        """``(xmin, xmax, ymin, ymax)`` covering every shape of the pad."""
        spans = [s.extent() for s in self.shapes]
        return (
            min(s[0] for s in spans), max(s[1] for s in spans),
            min(s[2] for s in spans), max(s[3] for s in spans),
        )

    def iter_shapes(self) -> Iterator[SlotShape]:
        """Yield the slot's drawn shapes."""
        yield from self.shapes

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "connector": self.connector,
            "pin": self.pin,
            "class": self.pad_class,
            "label": self.label,
            "shapes": [s.to_dict() for s in self.shapes],
        }
        if self.ident is not None:
            data["ident"] = self.ident
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Slot:
        raw_label = data.get("label")
        raw_ident = data.get("ident")
        return cls(
            connector=int(data["connector"]),
            pin=int(data["pin"]),
            ident=None if raw_ident is None else str(raw_ident),
            pad_class=str(data.get("class", SIGNAL_CLASS)),
            label=None if raw_label is None else str(raw_label),
            shapes=[SlotShape.from_dict(s) for s in data.get("shapes", [])],
        )


def assign_synthetic_addresses(slots: list[Slot]) -> None:
    """Give every slot with an unset pin a distinct synthetic address, in place.

    Generators use ``pin=UNSET_PIN`` for a pad whose real wiring is only known from
    a mapping CSV. Rather than leaving them all on one colliding address, each gets
    one in the reserved synthetic band, enumerated in natural ident order so it is
    stable when the source data is re-sorted. A CSV overrides these; whatever stays
    synthetic is detectable as made-up by
    :func:`~trap_tester.core.layout.addressing.is_synthetic`.
    """
    unset = [s for s in slots if s.pin == UNSET_PIN]
    if not unset:
        return
    keys = [s.ident or f"~{s.y:+09.3f}{s.x:+09.3f}" for s in unset]
    addresses = synthetic_addresses(keys)
    for slot, key in zip(unset, keys, strict=True):
        slot.connector, slot.pin = addresses[key]


def slugify(name: str) -> str:
    """A stable lowercase ``[a-z0-9_]`` key from a display name."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", name.casefold())).strip("_")


@dataclass
class InterfaceLayout:
    """One interface: its identity, its chrome and its pads."""

    name: str
    slug: str = ""  # stable mapping key; defaults to slugify(name)
    units: str = "mm"
    pitch_mm: float | None = None  # grid pitch when units == "grid"
    pin_space: str = "dsub_pin"  # which numbering ``Slot.pin`` is in
    match_by: str = ""  # "ident" | "connector_pin"; defaults from the slots
    background: list[Any] = field(default_factory=list)  # chrome primitives
    slots: list[Slot] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.slug:
            self.slug = slugify(self.name)
        if not self.match_by:
            self.match_by = (
                "ident" if any(s.ident for s in self.slots) else "connector_pin"
            )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "slug": self.slug,
            "units": self.units,
            "pin_space": self.pin_space,
            "match_by": self.match_by,
            "background": [p.to_dict() for p in self.background],
            "slots": [s.to_dict() for s in self.slots],
        }
        if self.pitch_mm is not None:
            data["pitch_mm"] = self.pitch_mm
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> InterfaceLayout:
        schema = int(data.get("schema", 0))
        if schema != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported layout schema {schema} (expected {SCHEMA_VERSION}). "
                "Regenerate the layout with its generator."
            )
        raw_pitch = data.get("pitch_mm")
        return cls(
            name=str(data["name"]),
            slug=str(data.get("slug", "")),
            units=str(data.get("units", "mm")),
            pitch_mm=None if raw_pitch is None else float(raw_pitch),
            pin_space=str(data.get("pin_space", "dsub_pin")),
            match_by=str(data.get("match_by", "")),
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
    label: str  # short in-shape label (the pin number or ident)
    message: str  # full finding text, shown on hover
    measured: bool
    pad_class: str = SIGNAL_CLASS  # what the pad is; only "signal" is clickable
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

    Every shape carries the slot's identity (``connector`` / ``pin`` / ``ident``)
    and the same verdict, so they colour together and a click on any of them
    resolves to the one net. The label is drawn on *every* shape, so a net drawn as
    several pads — a co-wired ion-trap group is one net of N member polygons —
    annotates each of its members, not just the first. Single-shape slots (every
    built-in and single-electrode layout) are unaffected. The label level-of-detail
    in the renderer still hides them when the view is too dense to read.
    """
    lbl = slot.display_label if label is None else label
    return [
        PinMark(
            x=sh.x, y=sh.y, r=sh.r, shape=sh.shape,
            connector=slot.connector, pin=slot.pin, status=status,
            fill=fill, stroke=stroke, label=lbl,
            message=message, measured=measured, pad_class=slot.pad_class,
            ident=slot.ident, rot=sh.rot, points=sh.points,
        )
        for sh in slot.iter_shapes()
    ]


@dataclass
class Drawing:
    """A flat, renderer-ready picture: static background + coloured pins."""

    title: str
    background: list[Any]
    pins: list[PinMark]

    def pad_classes(self) -> set[str]:
        """Which pad classes this drawing contains (drives the legend)."""
        return {p.pad_class for p in self.pins}

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
    """Colour ``layout``'s signal slots by the verdicts in ``result``.

    Every signal slot becomes a :class:`PinMark`: matched slots take their finding's
    status colour, unmatched slots are drawn faint ("unmeasured"). Non-signal pads
    (GND / RF / …) take their class colour and are never measured. Findings with no
    slot in the layout are ignored (they simply have nowhere to be drawn).

    Findings are matched on the layout's ``pin_space``: whichever attribute of a
    finding that names. A layout keyed on something a finding does not carry simply
    matches nothing — no exception, so a new interface family needs no code change.
    """
    from trap_tester.core.analysis import STATUS_INFO

    by_key: dict[tuple[int, int], Any] = {}
    for f in result.findings:
        k = getattr(f, layout.pin_space, None)
        if k is None:
            continue
        by_key[(int(f.connector), int(k))] = f

    pins: list[PinMark] = []
    for slot in layout.slots:
        if not slot.is_signal:
            fill, stroke = pad_style(slot.pad_class)
            pins += slot_pins(
                slot, status=slot.pad_class, fill=fill or UNMEASURED_FILL,
                stroke=stroke or UNMEASURED_STROKE,
                message=f"{slot.display_label}: {slot.pad_class}", measured=False,
            )
            continue
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
    "SCHEMA_VERSION",
    "UNMEASURED_FILL",
    "UNMEASURED_STROKE",
    "UNSET_PIN",
    "Drawing",
    "InterfaceLayout",
    "PinMark",
    "Slot",
    "SlotShape",
    "assign_synthetic_addresses",
    "build_drawing",
    "slot_pins",
    "slugify",
]
