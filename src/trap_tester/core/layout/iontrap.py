"""Build an ion-trap layout from a trap geometry JSON + electrode→DSUB mapping.

An ion trap is a chip covered in electrodes (arbitrary polygons, not pads on a
grid). Two local, device-specific sources describe one trap:

* a **geometry JSON** ``{electrodes:[{name, type:"DC"|"RF", polygons:[[[x,y],…]]}],
  …}`` with coordinates in **metres**, optionally a top-level
  ``cowired_groups: {group_name: [electrode_name, …]}``;
* a **mapping CSV** ``Electrode, Connector(_Num|" number"), DSUB_Pin`` — the net
  each *measurable* electrode (or co-wired group) routes to.

A net is one measurement identity — one ``(connector, pin)`` — drawn as one
:class:`Slot`. A plain DC electrode is one net of one polygon; a co-wired group
is one net whose geometry is the *union* of its member polygons (the group name,
not the members, is what the CSV maps). Every polygon of a net becomes a
:class:`SlotShape`, so marking any co-wired pad marks the whole net for free.

RF electrodes (and any other electrode the mapping never names) route to no tester
pin: they become ``class="rf"`` slots with a synthetic placeholder address, so they
are drawn in their class colour, appear in the legend (v1 drew them as background
polygons, which the colour-sniffing legend could never see) and stay inert.

Run ``python -m trap_tester.core.layout.iontrap <geometry.json> <mapping.csv>
[name]`` to generate the layout JSON into the user layout store (it embeds the
geometry + mapping, so it is never tracked in the repo).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from trap_tester.core.layout.interface import (
    UNSET_PIN,
    InterfaceLayout,
    Slot,
    SlotShape,
    assign_synthetic_addresses,
)
from trap_tester.core.layout.store import ensure_user_layouts_dir

# geometry coords are in metres; the trap is a few mm across -> draw in mm
M_TO_MM = 1000.0
_CONNECTOR_KEYS = ("Connector_Num", "Connector number", "Connector")


def _scale(poly: list[list[float]]) -> list[list[float]]:
    return [[float(x) * M_TO_MM, float(y) * M_TO_MM] for x, y in poly]


def build_iontrap(
    geometry: dict,
    mapping: list[tuple[str, int, int]],
    name: str = "Ion trap",
) -> InterfaceLayout:
    """Assemble the trap layout from a geometry dict and parsed mapping rows.

    ``mapping`` is ``(electrode_or_group, connector, pin)`` per net. A name in
    ``geometry["cowired_groups"]`` expands to the union of its members' polygons;
    any other name is a single electrode. Electrodes never named by the mapping
    (RF rails, unrouted pads) become inert ``class="rf"`` slots on synthetic
    addresses.
    """
    electrodes = {e["name"]: e for e in geometry["electrodes"]}
    cowired: dict[str, list[str]] = geometry.get("cowired_groups", {})

    slots: list[Slot] = []
    consumed: set[str] = set()  # electrodes drawn as (part of) a measurable net
    for elec_name, connector, pin in mapping:
        members = cowired.get(elec_name, [elec_name])
        shapes: list[SlotShape] = []
        for m in members:
            elec = electrodes.get(m)
            if elec is None:
                continue
            consumed.add(m)
            shapes += [SlotShape.from_polygon(_scale(p)) for p in elec["polygons"]]
        if not shapes:  # a mapped name with no geometry we can draw
            continue
        cx = sum(s.x for s in shapes) / len(shapes)
        cy = sum(s.y for s in shapes) / len(shapes)
        slots.append(
            Slot(connector=connector, pin=pin, x=cx, y=cy,
                 label="", ident=elec_name, shapes=shapes)
        )

    slots += _unrouted_slots(geometry, consumed)
    assign_synthetic_addresses(slots)

    return InterfaceLayout(
        name=name, slug=name.casefold(), units="mm", pin_space="dsub_pin",
        match_by="ident", background=[], slots=slots,
    )


def _unrouted_slots(geometry: dict, consumed: set[str]) -> list[Slot]:
    """Slots for the electrodes the mapping never names (RF rails, unrouted pads).

    They route to no tester pin, so they carry ``UNSET_PIN`` and are given a
    synthetic address by the caller. Their class comes from the geometry's own
    ``type``, so an RF rail is declared ``"rf"`` rather than being recognised later
    by its colour.
    """
    slots: list[Slot] = []
    for elec in geometry["electrodes"]:
        if elec["name"] in consumed:
            continue
        shapes = [SlotShape.from_polygon(_scale(p)) for p in elec["polygons"]]
        if not shapes:
            continue
        raw_type = str(elec.get("type", "") or "")
        slots.append(
            Slot(connector=0, pin=UNSET_PIN,
                 x=sum(s.x for s in shapes) / len(shapes),
                 y=sum(s.y for s in shapes) / len(shapes),
                 label="", pad_class="rf" if raw_type == "RF" else raw_type,
                 ident=elec["name"], shapes=shapes)
        )
    return slots


def _read_mapping(csv_path: str | Path) -> list[tuple[str, int, int]]:
    """Parse the electrode→DSUB CSV, tolerating the connector-column spelling."""
    with Path(csv_path).open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = reader.fieldnames or []
        conn_key = next((k for k in _CONNECTOR_KEYS if k in fields), None)
        if conn_key is None:
            raise ValueError(
                f"{csv_path}: no connector column (looked for {_CONNECTOR_KEYS})"
            )
        return [
            (row["Electrode"], int(row[conn_key]), int(row["DSUB_Pin"]))
            for row in reader
        ]


def generate_iontrap(
    geometry_path: str | Path,
    mapping_path: str | Path,
    name: str | None = None,
) -> InterfaceLayout:
    """Read the geometry JSON + mapping CSV and build the trap layout."""
    geometry = json.loads(Path(geometry_path).read_text())
    mapping = _read_mapping(mapping_path)
    return build_iontrap(geometry, mapping, name=name or Path(geometry_path).stem)


def _dump() -> None:
    if len(sys.argv) < 3:  # noqa: PLR2004
        raise SystemExit(
            "usage: python -m trap_tester.core.layout.iontrap "
            "<geometry.json> <mapping.csv> [name]"
        )
    name = sys.argv[3] if len(sys.argv) > 3 else None  # noqa: PLR2004
    layout = generate_iontrap(sys.argv[1], sys.argv[2], name)
    out = ensure_user_layouts_dir() / f"{layout.name}.json"
    layout.save_json(out)
    n_signal = sum(s.is_signal for s in layout.slots)
    n_other = len(layout.slots) - n_signal
    print(f"wrote {out} ({n_signal} nets + {n_other} non-signal electrodes)")


if __name__ == "__main__":
    _dump()
