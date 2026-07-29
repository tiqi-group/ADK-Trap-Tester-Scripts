"""Build a bond-finger ring layout from PCB coordinates + a pad→DSUB mapping.

A chip carrier fans out to a ring of bond fingers around the die. Two local
(un-tracked, device-specific) sources describe one carrier:

* a coordinates JSON — ``{finger: [x, y, rot]}`` in mm, exported from the PCB:
  each finger's centre and rotation;
* a mapping CSV — ``Bondfinger, DSUB Connector, DSUB-Pin``: the (0-indexed) DSUB
  connector + pin each finger routes to.

Each finger becomes a small square :class:`Slot` at its PCB position, addressed by
the ``(connector, pin)`` it routes to and named by its finger number (its ``ident``,
which is what a cross-interface mapping CSV lists). A finger the mapping does not
route gets a synthetic placeholder address instead of a colliding one. The squares
are sized below the finger pitch so they never overlap. PCB y grows downward, so y
is negated to draw a top view.
Run ``python -m trap_tester.core.layout.bondfinger <coords.json> <mapping.csv>``
to generate the layout JSON into the user layout store (it embeds the mapping, so
it is never tracked).
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
    assign_synthetic_addresses,
)
from trap_tester.core.layout.store import ensure_user_layouts_dir

NAME = "Bondfinger"
# half-side of a finger's square pad (mm). Fingers sit close together, so keep
# this small enough to leave a gap between adjacent squares.
FINGER_R = 0.09


def build_bondfinger(
    positions: dict[int, tuple[float, float, float]],
    mapping: dict[int, tuple[int, int]],
    name: str = NAME,
) -> InterfaceLayout:
    """Assemble the bond-finger layout.

    ``positions`` is ``{finger: (x, y, rot)}`` (mm, PCB orientation);
    ``mapping`` is ``{finger: (connector, pin)}``. Every finger is drawn; those
    absent from ``mapping`` route nowhere and are given a synthetic address.
    """
    slots: list[Slot] = []
    for finger in sorted(positions):
        x, y, _rot = positions[finger]  # rotation unused: squares need no orientation
        cp = mapping.get(finger)
        connector, pin = cp if cp is not None else (0, UNSET_PIN)
        slots.append(Slot(
            connector=connector, pin=pin, x=float(x), y=-float(y),  # PCB y is down
            r=FINGER_R, shape="rect", label="",
            ident=str(finger),  # the bond-finger number, this layout's mapping key
        ))
    assign_synthetic_addresses(slots)
    return InterfaceLayout(
        name=name, slug="bondfinger", units="mm", pin_space="dsub_pin",
        match_by="ident", background=[], slots=slots,
    )


def generate_bondfinger(fp_path: str | Path, csv_path: str | Path) -> InterfaceLayout:
    """Read the coordinate JSON + mapping CSV and build the layout."""
    raw = json.loads(Path(fp_path).read_text())
    positions = {int(k): (v[0], v[1], v[2]) for k, v in raw.items()}
    with Path(csv_path).open(newline="") as fh:
        mapping = {
            int(row["Bondfinger"]): (int(row["DSUB Connector"]), int(row["DSUB-Pin"]))
            for row in csv.DictReader(fh)
        }
    return build_bondfinger(positions, mapping)


def _dump() -> None:
    if len(sys.argv) != 3:  # noqa: PLR2004
        raise SystemExit(
            "usage: python -m trap_tester.core.layout.bondfinger "
            "<coordinates.json> <mapping.csv>"
        )
    layout = generate_bondfinger(sys.argv[1], sys.argv[2])
    out = ensure_user_layouts_dir() / f"{NAME}.json"
    layout.save_json(out)
    print(f"wrote {out} ({len(layout.slots)} fingers)")


if __name__ == "__main__":
    _dump()
