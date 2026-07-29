"""Build an interposer (LGA) layout from a pad→DSUB mapping.

An interposer land-grid-array fans out to several DSUB connectors. Two local
(un-tracked, device-specific) sources describe one interposer:

* a mapping CSV ``LGA pad, DSUB connector, DSUB-Pin`` — every signal pad and the
  (0-indexed) DSUB connector + pin it routes to;
* a GND list — one LGA pad per line, the pads tied to GND / shielding.

A pad name is a spreadsheet-style grid coordinate: column letter(s) + row number
(``N7`` = column N, row 7), which gives the pad its position. Signal pads become
measurable :class:`Slot` s addressed by the ``(connector, pin)`` they route to and
named by their pad name (their ``ident``, which a cross-interface mapping CSV
lists). The pads that carry no measurement — GND, plus the optional loopback /
sensor_heater / axialisation pads — are slots too, declaring their class; they route
to no tester pin and so get a synthetic placeholder address.

Because the interposer spans several connectors, its :class:`InterfaceLayout` is
drawn *whole* — every pad keeps its own ``connector`` — and matched/annotated per
``(connector, pin)``. Run ``python -m trap_tester.core.layout.interposer
<mapping.csv> <gnd.txt> [decoration.csv]`` to generate the layout JSON into the user
layout store (it embeds the mapping, so it is never tracked in the repo).
"""

from __future__ import annotations

import csv
import re
import sys
from pathlib import Path

from trap_tester.core.layout.interface import (
    UNSET_PIN,
    InterfaceLayout,
    Slot,
    assign_synthetic_addresses,
)
from trap_tester.core.layout.primitives import Text
from trap_tester.core.layout.store import ensure_user_layouts_dir

PAD_R = 0.42
_PAD_RE = re.compile(r"^([A-Za-z]+)(\d+)$")


def _col_index(letters: str) -> int:
    """Spreadsheet column index: A->0, B->1, … Z->25, AA->26, …"""
    idx = 0
    for ch in letters.upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _parse_pad(pad: str) -> tuple[str, int]:
    m = _PAD_RE.match(pad.strip())
    if not m:
        raise ValueError(f"Malformed LGA pad name {pad!r}")
    return m.group(1).upper(), int(m.group(2))


def build_interposer(
    mapping: list[tuple[str, int, int]],
    gnd_pads: list[str],
    decoration: list[tuple[str, str]] | None = None,
    name: str = "Interposer",
) -> InterfaceLayout:
    """Assemble the interposer layout from parsed pad data.

    ``mapping`` is ``(pad, connector, pin)`` per *signal* pad — these become the
    measured/annotatable :class:`Slot` s. ``gnd_pads`` and ``decoration``
    (``(pad, type)`` for rf / loopback / sensor_heater) are real pads that carry no
    measurement, so they are slots too, declaring their class rather than being
    hand-coloured background circles as in v1: that is what puts them in the legend
    whatever their shape. They route to no tester pin, so they get a synthetic
    address. A decoration pad that is also a signal pad stays a signal slot (its type
    is ignored). Positions come from the pad grid coordinate; row 1 is drawn at the
    top.
    """
    signal_names = {p for (p, _c, _pin) in mapping}
    parsed_signal = [(_parse_pad(p), int(c), int(pin)) for (p, c, pin) in mapping]

    decoration_all: list[tuple[str, str]] = [(p, "gnd") for p in gnd_pads]
    decoration_all += list(decoration or [])
    parsed_decoration = [
        (_parse_pad(p), t) for (p, t) in decoration_all if p not in signal_names
    ]

    all_rows = [rc[0][1] for rc in parsed_signal] + [rc[0][1] for rc in parsed_decoration]
    n_rows = max(all_rows) if all_rows else 1

    def _x(letters: str) -> float:
        return float(_col_index(letters))

    def _y(row: int) -> float:
        return float(n_rows - row)  # row 1 at top

    slots = [
        Slot(connector=c, pin=pin, x=_x(letters), y=_y(row), r=PAD_R,
             shape="circle", label="",
             ident=f"{letters}{row}")  # the LGA pad name, the interposer's mapping key
        for (letters, row), c, pin in parsed_signal
    ]
    slots += [
        Slot(connector=0, pin=UNSET_PIN, x=_x(letters), y=_y(row), r=PAD_R,
             shape="circle", label="", pad_class=t, ident=f"{letters}{row}")
        for (letters, row), t in parsed_decoration
    ]
    assign_synthetic_addresses(slots)

    coords = [rc[0] for rc in parsed_signal] + [rc[0] for rc in parsed_decoration]
    return InterfaceLayout(
        name=name, slug="interposer", units="grid", pin_space="dsub_pin",
        match_by="ident", background=_grid_labels(coords, n_rows), slots=slots,
    )


def _grid_labels(coords: list[tuple[str, int]], n_rows: int) -> list[Text]:
    """Column-letter (top) and row-number (left) grid guides."""
    cols = {_col_index(letters): letters for letters, _row in coords}
    used_rows = {row for _letters, row in coords}
    x_min = min(cols) if cols else 0
    y_top = float(n_rows - min(used_rows)) if used_rows else 0.0

    labels: list[Text] = []
    labels.extend(Text(x=float(c), y=y_top + 1.0, text=letters,
                       ha="center", va="bottom", style="grid_label")
                  for c, letters in cols.items())
    labels.extend(Text(x=float(x_min) - 1.0, y=float(n_rows - row), text=str(row),
                       ha="right", va="center", style="grid_label")
                  for row in used_rows)
    return labels


def generate_interposer(
    csv_path: str | Path,
    gnd_path: str | Path,
    decoration_path: str | Path | None = None,
) -> InterfaceLayout:
    """Read the mapping CSV + GND list (+ optional decoration CSV) and build the layout.

    ``decoration_path`` is a ``LGA pad,type`` CSV whose type is a pad class (see
    :data:`~trap_tester.core.layout.style.PAD_CLASSES`: loopback / sensor_heater /
    axialisation / rf). If absent, only signal + GND pads are drawn.
    """
    with Path(csv_path).open(newline="") as fh:
        mapping: list[tuple[str, int, int]] = [
            (row["LGA pad"], int(row["DSUB connector"]), int(row["DSUB-Pin"]))
            for row in csv.DictReader(fh)
        ]
    gnd = [ln.strip() for ln in Path(gnd_path).read_text().splitlines() if ln.strip()]

    decoration: list[tuple[str, str]] | None = None
    if decoration_path is not None and Path(decoration_path).exists():
        with Path(decoration_path).open(newline="") as fh:
            decoration = [(row["LGA pad"], row["type"]) for row in csv.DictReader(fh)]
    return build_interposer(mapping, gnd, decoration)


def _dump() -> None:
    if len(sys.argv) < 3:  # noqa: PLR2004
        raise SystemExit(
            "usage: python -m trap_tester.core.layout.interposer "
            "<mapping.csv> <gnd.txt> [decoration.csv]"
        )
    decoration_path = sys.argv[3] if len(sys.argv) > 3 else None  # noqa: PLR2004
    layout = generate_interposer(sys.argv[1], sys.argv[2], decoration_path)
    out = ensure_user_layouts_dir() / "interposer.json"
    layout.save_json(out)
    n_signal = sum(s.is_signal for s in layout.slots)
    n_other = len(layout.slots) - n_signal
    print(f"wrote {out} ({n_signal} signal + {n_other} non-signal pads)")


if __name__ == "__main__":
    _dump()
