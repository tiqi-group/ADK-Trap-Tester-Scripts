"""Build the HAWK_GEN1 bond-finger layout from its PCB coordinates + mapping.

The chip-carrier PCB fans out to a ring of 352 bond fingers around the die. Two
local (proprietary) sources describe it:

* ``bondfinger_fp.json`` — ``{finger: [x, y, rot]}`` in mm, extracted from the
  KiCad PCB (``bondfinger_coordinates.py``): each finger's centre and rotation;
* ``bondpad_mapping.csv`` — ``Bondfinger, DSUB Connector, DSUB-Pin``: the
  (0-indexed) DSUB connector + pin each finger routes to.

Each finger becomes a small square :class:`Slot` at its PCB position, stamped
with its canonical ``channel`` (the ``mux_mapping`` signal) so it correlates with
the DSUB / FPC / interposer layouts. The squares are sized below the finger pitch
so they never overlap. KiCad y grows downward, so y is negated to draw a top
view. Run ``python -m trap_tester.core.layout.bondfinger`` to generate
``HAWK_GEN1_Bondfinger.json`` into the user layout store (it embeds the mapping,
so it is never tracked).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.store import ensure_user_layouts_dir
from trap_tester.mux_mapping import dsub_to_signal

NAME = "HAWK_GEN1_Bondfinger"
# half-side of a finger's square pad (mm). Fingers sit ~0.21 mm apart, so keep
# this below ~0.10 to leave a gap between squares.
FINGER_R = 0.09
_NO_CONNECTOR = -1  # a finger that routes nowhere


def build_bondfinger(
    positions: dict[int, tuple[float, float, float]],
    mapping: dict[int, tuple[int, int]],
    name: str = NAME,
) -> InterfaceLayout:
    """Assemble the bond-finger layout.

    ``positions`` is ``{finger: (x, y, rot)}`` (mm, KiCad orientation);
    ``mapping`` is ``{finger: (connector, pin)}``. Every finger is drawn; those
    absent from ``mapping`` route nowhere (no channel, faint).
    """
    slots: list[Slot] = []
    for finger in sorted(positions):
        x, y, _rot = positions[finger]  # rotation unused: squares need no orientation
        cp = mapping.get(finger)
        connector, pin = cp if cp is not None else (_NO_CONNECTOR, finger)
        channel = dsub_to_signal.get(pin) if cp is not None else None
        slots.append(Slot(
            connector=connector, pin=pin, x=float(x), y=-float(y),  # KiCad y is down
            r=FINGER_R, shape="rect", channel=channel, label="",
        ))
    return InterfaceLayout(
        name=name, units="mm", key_by="dsub_pin", background=[], slots=slots,
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
    base = Path("docs_tmp/bondfinger")
    layout = generate_bondfinger(
        base / "bondfinger_fp.json", base / "bondpad_mapping.csv"
    )
    out = ensure_user_layouts_dir() / f"{NAME}.json"
    layout.save_json(out)
    print(f"wrote {out} ({len(layout.slots)} fingers)")


if __name__ == "__main__":
    _dump()
