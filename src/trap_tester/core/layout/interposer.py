"""Build an interposer (LGA) layout from its pad→DSUB mapping.

The interposer is a land-grid-array whose pads fan out to several DSUB
connectors. Two sources describe it (both local, un-tracked — the verified
mapping is proprietary):

* a mapping CSV ``LGA pad, DSUB connector, DSUB-Pin`` — every signal pad and the
  (0-indexed) DSUB connector + pin it routes to;
* a GND list — one LGA pad per line, the pads tied to GND / shielding.

A pad name is a spreadsheet-style grid coordinate: column letter(s) + row number
(``N7`` = column N, row 7), which gives the pad its position. Signal pads become
measurable :class:`Slot` s stamped with their canonical ``channel`` (the
``mux_mapping`` signal) so the interposer correlates with the DSUB / FPC layouts.
The non-measured pads — GND, plus optional axialisation / loopback /
sensor_heater "flavor" pads read from the signal-type PDF — are drawn as
fixed-colour background circles that never react to measurement data (echoing the
PDF for orientation).

Because the interposer spans several connectors, its :class:`InterfaceLayout` is
drawn *whole* — every pad keeps its own ``connector`` — and matched/annotated per
``(connector, pin|channel)``. Run ``python -m trap_tester.core.layout.interposer``
to generate ``interposer.json`` into the user layout store (it embeds the
verified mapping, so it is never tracked in the repo).
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from trap_tester.core.layout.flavor import flavor_style
from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.primitives import Circle, Text
from trap_tester.core.layout.store import ensure_user_layouts_dir
from trap_tester.mux_mapping import dsub_to_signal

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
    flavor: list[tuple[str, str]] | None = None,
    name: str = "Interposer (signal-type v1.0)",
) -> InterfaceLayout:
    """Assemble the interposer layout from parsed pad data.

    ``mapping`` is ``(pad, connector, pin)`` per *signal* pad — these become the
    measured/annotatable :class:`Slot` s. ``gnd_pads`` and ``flavor``
    (``(pad, type)`` for axialisation / loopback / sensor_heater) are non-measured
    pads drawn as fixed-colour background circles — "flavor" that mirrors the PDF
    and never reacts to measurement data. A flavor pad that is also a signal pad
    stays a signal slot (its type is ignored). Positions come from the pad grid
    coordinate; row 1 is drawn at the top.
    """
    signal_names = {p for (p, _c, _pin) in mapping}
    parsed_signal = [(_parse_pad(p), int(c), int(pin)) for (p, c, pin) in mapping]

    flavor_all: list[tuple[str, str]] = [(p, "gnd") for p in gnd_pads]
    flavor_all += list(flavor or [])
    parsed_flavor = [
        (_parse_pad(p), t) for (p, t) in flavor_all if p not in signal_names
    ]

    all_rows = [rc[0][1] for rc in parsed_signal] + [rc[0][1] for rc in parsed_flavor]
    n_rows = max(all_rows) if all_rows else 1

    def _x(letters: str) -> float:
        return float(_col_index(letters))

    def _y(row: int) -> float:
        return float(n_rows - row)  # row 1 at top

    slots = [
        Slot(connector=c, pin=pin, x=_x(letters), y=_y(row), r=PAD_R,
             shape="circle", channel=dsub_to_signal.get(pin), label="")
        for (letters, row), c, pin in parsed_signal
    ]
    circles = [
        Circle(x=_x(letters), y=_y(row), r=PAD_R, width=0.8,
               fill=flavor_style(t)[0], stroke=flavor_style(t)[1])
        for (letters, row), t in parsed_flavor
    ]

    coords = [rc[0] for rc in parsed_signal] + [rc[0] for rc in parsed_flavor]
    background = [*circles, *_grid_labels(coords, n_rows)]
    return InterfaceLayout(
        name=name, units="grid", key_by="dsub_pin",
        background=background, slots=slots,
    )


def _grid_labels(coords: list[tuple[str, int]], n_rows: int) -> list[Text]:
    """Column-letter (top) and row-number (left) grid guides."""
    cols = {_col_index(letters): letters for letters, _row in coords}
    used_rows = {row for _letters, row in coords}
    x_min = min(cols) if cols else 0
    y_top = float(n_rows - min(used_rows)) if used_rows else 0.0

    labels: list[Text] = []
    labels.extend(Text(x=float(c), y=y_top + 1.0, text=letters, size=7,
                       color="#8a8a8a", ha="center", va="bottom")
                  for c, letters in cols.items())
    labels.extend(Text(x=float(x_min) - 1.0, y=float(n_rows - row), text=str(row),
                       size=7, color="#8a8a8a", ha="right", va="center")
                  for row in used_rows)
    return labels


def generate_interposer(
    csv_path: str | Path,
    gnd_path: str | Path,
    flavor_path: str | Path | None = None,
) -> InterfaceLayout:
    """Read the mapping CSV + GND list (+ optional flavor CSV) and build the layout.

    ``flavor_path`` is a ``LGA pad,type`` CSV (types: axialisation / loopback /
    sensor_heater), typically extracted from the signal-type PDF. If absent, only
    signal + GND pads are drawn.
    """
    with Path(csv_path).open(newline="") as fh:
        mapping: list[tuple[str, int, int]] = [
            (row["LGA pad"], int(row["DSUB connector"]), int(row["DSUB-Pin"]))
            for row in csv.DictReader(fh)
        ]
    gnd = [ln.strip() for ln in Path(gnd_path).read_text().splitlines() if ln.strip()]

    flavor: list[tuple[str, str]] | None = None
    if flavor_path is not None and Path(flavor_path).exists():
        with Path(flavor_path).open(newline="") as fh:
            flavor = [(row["LGA pad"], row["type"]) for row in csv.DictReader(fh)]
    return build_interposer(mapping, gnd, flavor)


def _dump() -> None:
    base = Path("docs_tmp")
    layout = generate_interposer(
        base / "interposer_mapping.csv",
        base / "filter_gnd.txt",
        base / "interposer_flavor.csv",
    )
    out = ensure_user_layouts_dir() / "interposer.json"
    layout.save_json(out)
    n_flavor = sum(isinstance(p, Circle) for p in layout.background)
    print(f"wrote {out} ({len(layout.slots)} signal + {n_flavor} flavor pads)")


if __name__ == "__main__":
    _dump()
