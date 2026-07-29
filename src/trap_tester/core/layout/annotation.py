"""Manual, cross-interface pin annotations (Qt-free).

When a trap operator reports that channels seem disconnected, the visualiser
becomes a tool to track that fault along the mechanical interfaces: mark a pin
faulty or suspicious on one interface, then switch interfaces to see where the
*same pin* lands elsewhere and correlate visually.

An annotation is keyed by the **canonical address** — ``(connector, DSUB pin)``,
see :func:`~trap_tester.core.layout.addressing.canonical_address`. That is the
apparatus' own electrical address, so a mark means "this physical pin is
suspicious": a fact that survives loading a different mapping CSV. The mapping
changes *which geometry is drawn* at that address; the mark stays put.

:class:`AnnotationSet` is a plain container that round-trips to JSON so a session
can be saved and reloaded. :func:`build_annotation_drawing` projects a set onto any
layout, yielding the same renderer-ready :class:`Drawing` the analysis viewer uses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.layout.addressing import canonical_address, is_synthetic
from trap_tester.core.layout.interface import (
    UNMEASURED_FILL,
    UNMEASURED_STROKE,
    Drawing,
    PinMark,
    slot_pins,
)
from trap_tester.core.layout.style import pad_style

if TYPE_CHECKING:
    from collections.abc import Iterator

    from trap_tester.core.layout.interface import InterfaceLayout

# state key -> (human label, fill colour). "no comment" is the *absence* of a
# mark, so it has no entry here. Colours echo the analysis status vocabulary.
ANNOTATION_STATES: dict[str, tuple[str, str]] = {
    "suspicious": ("Suspicious", "#e08e0b"),
    "faulty": ("Faulty", "#c0392b"),
}

# The click cycle: no comment -> suspicious -> faulty -> no comment.
CYCLE: tuple[str | None, ...] = (None, "suspicious", "faulty")

# Faint styling for a markable-but-unmarked pad — reuse the analysis viewer's
# "unmeasured" look so the two visualisers feel like one tool.
CLEAR_FILL = UNMEASURED_FILL
CLEAR_STROKE = UNMEASURED_STROKE
# A signal pad with no canonical address (an FPC GND/shield conductor) gets a faint
# blue: real, but not markable.
GND_FILL = "#cfe0f3"
GND_STROKE = "#9fb8d8"

_JSON_KIND = "trap-tester-annotations"
_JSON_VERSION = 2


def cycle_state(current: str | None) -> str | None:
    """Next state in the click cycle after ``current``."""
    return CYCLE[(CYCLE.index(current) + 1) % len(CYCLE)]


@dataclass
class Annotation:
    """One operator mark on a physical pin of one connector."""

    connector: int
    pin: int
    state: str  # a key of ANNOTATION_STATES
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "pin": self.pin,
            "state": self.state,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Annotation:
        state = str(data["state"])
        if state not in ANNOTATION_STATES:
            raise ValueError(f"Unknown annotation state {state!r}")
        return cls(
            connector=int(data["connector"]),
            pin=int(data["pin"]),
            state=state,
            note=str(data.get("note", "")),
        )



@dataclass
class AnnotationSet:
    """A collection of marks keyed by canonical ``(connector, pin)``."""

    marks: dict[tuple[int, int], Annotation] = field(default_factory=dict)

    # ---- queries -----------------------------------------------------------
    def state(self, connector: int, pin: int) -> str | None:
        mark = self.marks.get((connector, pin))
        return mark.state if mark else None

    def note(self, connector: int, pin: int) -> str:
        mark = self.marks.get((connector, pin))
        return mark.note if mark else ""

    def counts(self) -> dict[str, int]:
        """How many marks of each state, e.g. ``{"faulty": 3, "suspicious": 1}``."""
        out: dict[str, int] = {}
        for mark in self.marks.values():
            out[mark.state] = out.get(mark.state, 0) + 1
        return out

    def is_empty(self) -> bool:
        return not self.marks

    def __len__(self) -> int:
        return len(self.marks)

    def __iter__(self) -> Iterator[Annotation]:
        return iter(self.marks.values())

    # ---- mutation ----------------------------------------------------------
    def set_state(
        self, connector: int, pin: int, state: str | None, note: str | None = None
    ) -> None:
        """Set (or, with ``state=None``, clear) the mark on a pin.

        ``note=None`` keeps any existing note; pass ``""`` to clear it.
        """
        key = (connector, pin)
        if state is None:
            self.marks.pop(key, None)
            return
        if state not in ANNOTATION_STATES:
            raise ValueError(f"Unknown annotation state {state!r}")
        existing = self.marks.get(key)
        kept_note = existing.note if existing else ""
        self.marks[key] = Annotation(
            connector, pin, state, kept_note if note is None else note
        )

    def set_note(self, connector: int, pin: int, note: str) -> None:
        """Attach a note (only meaningful on a pin that has a mark)."""
        mark = self.marks.get((connector, pin))
        if mark is not None:
            mark.note = note

    def cycle(self, connector: int, pin: int) -> str | None:
        """Advance a pin to the next state and return it (note preserved)."""
        nxt = cycle_state(self.state(connector, pin))
        self.set_state(connector, pin, nxt)
        return nxt

    def clear(self, connector: int, pin: int) -> None:
        self.marks.pop((connector, pin), None)

    def clear_all(self) -> None:
        self.marks.clear()

    # ---- (de)serialisation -------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": _JSON_KIND,
            "version": _JSON_VERSION,
            "annotations": [m.to_dict() for m in self.marks.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnnotationSet:
        if data.get("kind") != _JSON_KIND:
            raise ValueError("Not a trap-tester annotations file")
        version = int(data.get("version", 0))
        if version != _JSON_VERSION:
            raise ValueError(
                f"Unsupported annotations version {version} "
                f"(expected {_JSON_VERSION})"
            )
        marks: dict[tuple[int, int], Annotation] = {}
        for entry in data.get("annotations", []):
            mark = Annotation.from_dict(entry)
            marks[(mark.connector, mark.pin)] = mark
        return cls(marks=marks)

    def save_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load_json(cls, path: str | Path) -> AnnotationSet:
        return cls.from_dict(json.loads(Path(path).read_text()))


def build_annotation_drawing(
    layout: InterfaceLayout, annotations: AnnotationSet, connector: int | None = None
) -> Drawing:
    """Project ``annotations`` onto ``layout``.

    Each signal slot is coloured by the mark on *its own* canonical address — so a
    multi-connector layout (e.g. an interposer spanning several DSUB connectors) is
    drawn whole with each pad reflecting the right connector's mark. Pass
    ``connector`` to focus a single connector (others are omitted); leave it
    ``None`` to draw every connector.

    Non-signal pads (GND / RF / …) take their class colour and are inert. A signal
    pad with no canonical address — an FPC shield conductor — is faint and inert
    too. Everything else is markable: annotated slots take the state colour,
    unmarked ones are faint.
    """
    pins: list[PinMark] = []
    for slot in layout.slots:
        conn = slot.connector
        if connector is not None and conn != connector:
            continue

        if not slot.is_signal:
            fill, stroke = pad_style(slot.pad_class)
            pins += slot_pins(
                slot, status=slot.pad_class,
                fill=fill or GND_FILL, stroke=stroke or GND_STROKE,
                message=f"{slot.display_label}: {slot.pad_class} (not markable)",
                measured=False,
            )
            continue

        address = canonical_address(conn, slot.pin, layout.pin_space)
        if address is None:
            pins += slot_pins(
                slot, status="unmapped", fill=GND_FILL, stroke=GND_STROKE,
                message=f"conn {conn} · {layout.pin_space} {slot.pin}: "
                        "no canonical address",
                measured=False,
            )
            continue

        where = _describe(layout, slot, address)
        state = annotations.state(*address)
        if state is not None:
            state_label, color = ANNOTATION_STATES[state]
            note = annotations.note(*address)
            message = f"{where}: {state_label}"
            if note:
                message += f"\n{note}"
            pins += slot_pins(
                slot, status=state, fill=color, stroke="#333",
                message=message, measured=True,
            )
        else:
            pins += slot_pins(
                slot, status="clear", fill=CLEAR_FILL, stroke=CLEAR_STROKE,
                message=f"{where}: no comment", measured=False,
            )
    return Drawing(title=layout.name, background=list(layout.background), pins=pins)


def _describe(
    layout: InterfaceLayout, slot: Any, address: tuple[int, int]
) -> str:
    """Hover text locating a slot, naming its ident and flagging a made-up address."""
    parts = []
    if slot.ident:
        parts.append(str(slot.ident))
    parts.append(f"conn {slot.connector} · {layout.pin_space} {slot.pin}")
    if is_synthetic(slot.connector):
        parts.append("placeholder wiring — no mapping applied")
    elif address != (slot.connector, slot.pin):
        parts.append(f"DSUB pin {address[1]}")
    return " · ".join(parts)


__all__ = [
    "ANNOTATION_STATES",
    "CLEAR_FILL",
    "CLEAR_STROKE",
    "CYCLE",
    "GND_FILL",
    "GND_STROKE",
    "Annotation",
    "AnnotationSet",
    "build_annotation_drawing",
    "cycle_state",
]
