"""Manual, cross-interface pin annotations (Qt-free).

When a trap operator reports that channels seem disconnected, the visualiser
becomes a tool to track that fault along the mechanical interfaces: mark a pin
faulty or suspicious on one interface, then switch interfaces to see where the
*same channel* lands elsewhere and correlate visually.

An annotation is therefore keyed by the **canonical channel** (the ``Slot.channel``
stamped into every layout JSON), not by a DSUB pin or FPC conductor — so it
follows the channel across interfaces for free. :class:`AnnotationSet` is a plain
container of these marks that round-trips to JSON so a session can be saved and
reloaded. :func:`build_annotation_drawing` projects a set onto any layout,
yielding the same renderer-ready :class:`Drawing` the analysis viewer uses.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.layout.interface import (
    UNMEASURED_FILL,
    UNMEASURED_STROKE,
    Drawing,
    PinMark,
)

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

# Faint styling for a mapped-but-unmarked contact — reuse the analysis viewer's
# "unmeasured" look so the two visualisers feel like one tool.
CLEAR_FILL = UNMEASURED_FILL
CLEAR_STROKE = UNMEASURED_STROKE
# GND / shield / unmapped pads get a faint blue so the ground pattern reads at a
# glance (they carry no channel and are never clickable).
GND_FILL = "#cfe0f3"
GND_STROKE = "#9fb8d8"

_JSON_KIND = "trap-tester-annotations"
_JSON_VERSION = 1


def cycle_state(current: str | None) -> str | None:
    """Next state in the click cycle after ``current``."""
    return CYCLE[(CYCLE.index(current) + 1) % len(CYCLE)]


@dataclass
class Annotation:
    """One operator mark on a physical channel of one connector."""

    connector: int
    channel: int
    state: str  # a key of ANNOTATION_STATES
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector": self.connector,
            "channel": self.channel,
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
            channel=int(data["channel"]),
            state=state,
            note=str(data.get("note", "")),
        )


@dataclass
class AnnotationSet:
    """A collection of marks keyed by ``(connector, channel)``."""

    marks: dict[tuple[int, int], Annotation] = field(default_factory=dict)

    # ---- queries -----------------------------------------------------------
    def state(self, connector: int, channel: int) -> str | None:
        mark = self.marks.get((connector, channel))
        return mark.state if mark else None

    def note(self, connector: int, channel: int) -> str:
        mark = self.marks.get((connector, channel))
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
        self, connector: int, channel: int, state: str | None, note: str | None = None
    ) -> None:
        """Set (or, with ``state=None``, clear) the mark on a channel.

        ``note=None`` keeps any existing note; pass ``""`` to clear it.
        """
        key = (connector, channel)
        if state is None:
            self.marks.pop(key, None)
            return
        if state not in ANNOTATION_STATES:
            raise ValueError(f"Unknown annotation state {state!r}")
        existing = self.marks.get(key)
        kept_note = existing.note if existing else ""
        self.marks[key] = Annotation(
            connector, channel, state, kept_note if note is None else note
        )

    def set_note(self, connector: int, channel: int, note: str) -> None:
        """Attach a note (only meaningful on a channel that has a mark)."""
        mark = self.marks.get((connector, channel))
        if mark is not None:
            mark.note = note

    def cycle(self, connector: int, channel: int) -> str | None:
        """Advance a channel to the next state and return it (note preserved)."""
        nxt = cycle_state(self.state(connector, channel))
        self.set_state(connector, channel, nxt)
        return nxt

    def clear(self, connector: int, channel: int) -> None:
        self.marks.pop((connector, channel), None)

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
        marks: dict[tuple[int, int], Annotation] = {}
        for entry in data.get("annotations", []):
            mark = Annotation.from_dict(entry)
            marks[(mark.connector, mark.channel)] = mark
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

    Each slot is coloured by the mark on *its own* ``(connector, channel)`` — so a
    multi-connector layout (e.g. an interposer spanning several DSUB connectors)
    is drawn whole with each pad reflecting the right connector's mark. Pass
    ``connector`` to focus a single connector (others are omitted); leave it
    ``None`` to draw every connector.

    Annotated slots take the state colour; mapped-but-unmarked slots are faint;
    slots with no channel (GND / shield / unmapped) are faint and carry
    ``channel=None`` so a renderer knows they are not clickable.
    """
    pins: list[PinMark] = []
    for slot in layout.slots:
        conn = slot.connector
        if connector is not None and conn != connector:
            continue
        channel = slot.channel
        state = annotations.state(conn, channel) if channel is not None else None
        ident = f"conn {conn} · {layout.key_by} {slot.pin} · channel {channel}"
        if state is not None:
            state_label, color = ANNOTATION_STATES[state]
            note = annotations.note(conn, channel)
            message = f"{ident}: {state_label}"
            if note:
                message += f"\n{note}"
            pins.append(
                PinMark(
                    x=slot.x, y=slot.y, r=slot.r, shape=slot.shape,
                    connector=conn, pin=slot.pin, status=state,
                    fill=color, stroke="#333", label=slot.display_label,
                    message=message, measured=True, channel=channel, rot=slot.rot,
                )
            )
        else:
            unmapped = channel is None
            message = (
                f"conn {conn} · {layout.key_by} {slot.pin}: no channel (GND / unmapped)"
                if unmapped
                else f"{ident}: no comment"
            )
            pins.append(
                PinMark(
                    x=slot.x, y=slot.y, r=slot.r, shape=slot.shape,
                    connector=conn, pin=slot.pin,
                    status="unmapped" if unmapped else "clear",
                    fill=GND_FILL if unmapped else CLEAR_FILL,
                    stroke=GND_STROKE if unmapped else CLEAR_STROKE,
                    label=slot.display_label,
                    message=message, measured=False, channel=channel, rot=slot.rot,
                )
            )
    return Drawing(title=layout.name, background=list(layout.background), pins=pins)


__all__ = [
    "ANNOTATION_STATES",
    "CYCLE",
    "cycle_state",
    "Annotation",
    "AnnotationSet",
    "build_annotation_drawing",
    "CLEAR_FILL",
    "CLEAR_STROKE",
    "GND_FILL",
    "GND_STROKE",
]
