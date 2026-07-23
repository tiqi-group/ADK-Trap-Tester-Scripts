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
Because the trap's connectors/pins are a different family than the project's
``mux_mapping``, the ``channel`` is not looked up — the importer assigns a
unique channel per net itself.

RF electrodes (and any other electrode the mapping never names) are unmapped:
they render as fixed-colour background polygons — "decoration" that never reacts
to measurement data.

Run ``python -m trap_tester.core.layout.iontrap <geometry.json> <mapping.csv>
[name]`` to generate the layout JSON into the user layout store (it embeds the
geometry + mapping, so it is never tracked in the repo).
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

from trap_tester.core.layout.decoration import decoration_style
from trap_tester.core.layout.interface import InterfaceLayout, Slot, SlotShape
from trap_tester.core.layout.primitives import Polyline
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
    (RF rails, unrouted pads) become fixed-colour background decoration. Channels
    are assigned sequentially in mapping order so the layout is deterministic.
    """
    electrodes = {e["name"]: e for e in geometry["electrodes"]}
    cowired: dict[str, list[str]] = geometry.get("cowired_groups", {})

    slots: list[Slot] = []
    consumed: set[str] = set()  # electrodes drawn as (part of) a measurable net
    channel = 0
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
                 channel=channel, label="", shapes=shapes)
        )
        channel += 1

    background: list[Polyline] = []
    for elec in geometry["electrodes"]:
        if elec["name"] in consumed:
            continue
        # RF rails get their datasheet colour; anything else falls back to grey
        pad_type = "rf_lines" if elec.get("type") == "RF" else elec.get("type", "")
        fill, stroke = decoration_style(pad_type)
        background += [
            Polyline(points=_scale(p), closed=True, fill=fill, stroke=stroke, width=0.6)
            for p in elec["polygons"]
        ]

    return InterfaceLayout(
        name=name, units="mm", key_by="dsub_pin",
        background=background, slots=slots,
    )


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
    n_dec = len(layout.background)
    print(f"wrote {out} ({len(layout.slots)} nets + {n_dec} decoration polygons)")


if __name__ == "__main__":
    _dump()
