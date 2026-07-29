"""Setup-specific cross-interface wiring maps.

Every layout bakes in a *nominal* wiring — each
:class:`~trap_tester.core.layout.interface.Slot` carries a ``(connector, pin)``,
the apparatus' own electrical address. But the trap-tester's interfaces (DSUB-50,
interposer, bond-finger ring, ion-trap electrodes …) are joined by cables, adapter
PCBs and vacuum feedthroughs that a real setup wires differently. A **mapping** is
a per-setup CSV that declares, net by net, how the interfaces actually
interconnect — overriding the nominal wiring.

CSV shape (schema v2): a required ``connector`` and ``pin`` column, plus one column
per interface whose header is that layout's **slug**. Each row is one net::

    connector,pin,hawk3,bondfinger,interposer
    4,31,COMP_0_0,287,B25

The net measured at tester connector 4, pin 31 is called ``COMP_0_0`` on the
``hawk3`` interface, ``287`` on ``bondfinger`` and ``B25`` on ``interposer``. A cell
may be blank — then that net has no identifier on that interface. Several idents
for one net on one interface are separated by ``;`` (never a comma: commas are not
permitted inside an ident, and the loader enforces it).

:func:`apply_to` re-stamps a layout's slots for a mapping. Which join is used is
*declared* by the layout, not guessed:

* ``match_by == "ident"`` — match slots by their ``ident`` against the column named
  by the layout's ``slug``;
* ``match_by == "connector_pin"`` — the tester's reference interfaces (DSUB-50 /
  FPC), matched on the address itself.

Slots matching no net keep their nominal wiring. :func:`coverage_report` says
exactly which idents matched and which did not, on both sides.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import TYPE_CHECKING

from trap_tester.core.layout.addressing import PINS_PER_CONNECTOR

if TYPE_CHECKING:
    from trap_tester.core.layout.interface import InterfaceLayout

# The two reserved column headers. There is deliberately no tolerance list of
# alternative spellings: headers are normalised (case, spaces, separators) and
# anything else is an error naming the fix, so odd spellings get corrected in the
# data once instead of accumulating in the parser forever.
CONNECTOR_HEADER = "connector"
PIN_HEADERS = ("pin", "dsub_pin")
IDENT_SEPARATOR = ";"

_HEADER_HINT = (
    f"the reserved headers are {CONNECTOR_HEADER!r} and one of {PIN_HEADERS}; "
    "every other column is a layout slug"
)


def normalize_header(header: str) -> str:
    """Canonical form of a CSV header: casefolded, separators collapsed to ``_``."""
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", header.casefold())).strip("_")


def normalize_ident(ident: str) -> str:
    """An ident as matched: surrounding whitespace stripped, nothing else.

    Deliberately no case-folding and no numeric normalisation — see
    :func:`coverage_report`, which reports near-misses rather than silently
    accepting them.
    """
    return ident.strip()


@dataclass
class Net:
    """One electrical net: a tester address plus its name on each named interface."""

    connector: int
    pin: int
    idents: dict[str, list[str]]  # interface slug -> this net's identifier(s) there
    row: int  # source row index, for diagnostics


@dataclass
class Mapping:
    """A parsed mapping CSV: the named interfaces and the nets across them."""

    name: str
    interfaces: list[str]  # the named (non connector/pin) column headers, in order
    nets: list[Net]

    def idents_for(self, interface: str) -> dict[str, Net]:
        """``ident -> net`` for one named interface (blank cells skipped)."""
        out: dict[str, Net] = {}
        for net in self.nets:
            for ident in net.idents.get(interface, ()):
                out[ident] = net
        return out

    def by_connector_pin(self) -> dict[tuple[int, int], Net]:
        """``(connector, pin) -> net`` for the reference interface."""
        return {(n.connector, n.pin): n for n in self.nets}


def load_csv(path: str | Path) -> Mapping:
    """Parse a mapping CSV into a :class:`Mapping`.

    Raises with an actionable message when the headers are not canonical or a pin is
    outside the tester's range — both are legacy-data problems the migration fixes,
    not things to paper over here.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        raw_fields = list(reader.fieldnames or [])
        headers = {f: normalize_header(f) for f in raw_fields}
        conn_key, pin_key = _reserved_keys(path, headers)
        ident_fields = [f for f in raw_fields if f not in (conn_key, pin_key)]

        nets: list[Net] = []
        for i, row in enumerate(reader):
            conn_raw = (row.get(conn_key) or "").strip()
            pin_raw = (row.get(pin_key) or "").strip()
            if not conn_raw or not pin_raw:
                continue  # a net with no tester address cannot be placed
            nets.append(Net(
                connector=int(conn_raw),
                pin=_checked_pin(path, i, pin_raw),
                idents=_row_idents(path, i, row, ident_fields, headers),
                row=i,
            ))
    return Mapping(
        name=path.stem, interfaces=[headers[f] for f in ident_fields], nets=nets
    )


def _reserved_keys(path: Path, headers: dict[str, str]) -> tuple[str, str]:
    """The raw header names of the ``connector`` and ``pin`` columns."""
    conn_key = next((f for f, n in headers.items() if n == CONNECTOR_HEADER), None)
    pin_key = next((f for f, n in headers.items() if n in PIN_HEADERS), None)
    if conn_key is None or pin_key is None:
        missing = "connector" if conn_key is None else "pin"
        raise ValueError(
            f"{path}: no '{missing}' column — found {sorted(headers.values())}. "
            f"Note {_HEADER_HINT}."
        )
    return conn_key, pin_key


def _checked_pin(path: Path, index: int, pin_raw: str) -> int:
    """A physical DSUB pin, rejecting the legacy bank-encoded form."""
    pin = int(pin_raw)
    if not 1 <= pin <= PINS_PER_CONNECTOR:
        raise ValueError(
            f"{path} row {index + 2}: pin {pin} is outside 1..{PINS_PER_CONNECTOR}. "
            "A pin is the physical DSUB pin; older exports encoded the connector "
            "bank in a hundreds digit, which must be stripped in the CSV."
        )
    return pin


def _row_idents(
    path: Path,
    index: int,
    row: dict[str, str | None],
    ident_fields: list[str],
    headers: dict[str, str],
) -> dict[str, list[str]]:
    """``slug -> idents`` for one row, splitting multi-ident cells."""
    idents: dict[str, list[str]] = {}
    for field_name in ident_fields:
        cell = (row.get(field_name) or "").strip()
        if not cell:
            continue
        if "," in cell:
            raise ValueError(
                f"{path} row {index + 2}: ident {cell!r} contains a comma; "
                f"use {IDENT_SEPARATOR!r} to separate several idents."
            )
        parts = [normalize_ident(p) for p in cell.split(IDENT_SEPARATOR)]
        idents[headers[field_name]] = [p for p in parts if p]
    return idents


# ---------------------------------------------------------------------------
# Applying a mapping
# ---------------------------------------------------------------------------
def _column_for(layout: InterfaceLayout, mapping: Mapping) -> str | None:
    """The mapping column this layout is identified by, or ``None``.

    Just the layout's declared ``slug``. v1 fell back to "the column whose idents
    overlap the most", which was needed only because columns were headed with
    display names; the slug makes that guess unnecessary.
    """
    return layout.slug if layout.slug in mapping.interfaces else None


@dataclass
class CoverageReport:
    """What a mapping does and does not say about one layout."""

    mode: str  # "ident" | "connector_pin" | "none"
    column: str | None
    matched: list[str] = field(default_factory=list)
    layout_only: list[str] = field(default_factory=list)  # in the layout, not the CSV
    csv_only: list[str] = field(default_factory=list)  # in the CSV, not the layout
    case_mismatches: list[tuple[str, str]] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.matched)

    def summary(self) -> str:
        """One-line human summary, naming the near-misses worth fixing."""
        if self.mode == "none":
            return "this mapping does not describe this interface"
        if self.mode == "connector_pin":
            return f"{self.count} slot(s) matched by (connector, pin)"
        parts = [f"{self.count} matched"]
        if self.layout_only:
            parts.append(f"{len(self.layout_only)} only in the layout")
        if self.csv_only:
            parts.append(f"{len(self.csv_only)} only in the CSV")
        if self.case_mismatches:
            parts.append(f"{len(self.case_mismatches)} matched only ignoring case")
        return ", ".join(parts)


def coverage_report(layout: InterfaceLayout, mapping: Mapping) -> CoverageReport:
    """Diff a layout's idents against the mapping column that names them.

    Case is honoured when matching; an ident that matches only case-insensitively is
    still applied but reported in ``case_mismatches``, so the join is not blocked and
    the offending cell can be corrected. No numeric normalisation is attempted —
    ``N04`` and ``N4`` stay distinct, because a rule clever enough to equate them
    would eventually mangle a structured electrode name.
    """
    if layout.match_by == "connector_pin":
        cp = mapping.by_connector_pin()
        matched = [
            f"{s.connector}:{s.pin}" for s in layout.slots
            if (s.connector, s.pin) in cp
        ]
        return CoverageReport(mode="connector_pin", column=None, matched=matched)

    column = _column_for(layout, mapping)
    if column is None:
        return CoverageReport(mode="none", column=None)

    csv_idents = mapping.idents_for(column)
    csv_folded = {i.casefold(): i for i in csv_idents}
    slot_idents = [s.ident for s in layout.slots if s.ident]

    report = CoverageReport(mode="ident", column=column)
    seen: set[str] = set()
    for ident in slot_idents:
        if ident in csv_idents:
            report.matched.append(ident)
            seen.add(ident)
            continue
        alt = csv_folded.get(ident.casefold())
        if alt is not None:
            report.matched.append(ident)
            report.case_mismatches.append((ident, alt))
            seen.add(alt)
            continue
        report.layout_only.append(ident)
    report.csv_only = sorted(set(csv_idents) - seen)
    return report


def coverage(layout: InterfaceLayout, mapping: Mapping) -> int:
    """How many of ``layout``'s slots ``mapping`` would re-wire.

    Zero means the mapping does not touch this layout at all — it can neither be
    propagated *to* nor *from* it — so a GUI should warn rather than silently show
    the nominal wiring. See :func:`coverage_report` for the detail behind the count.
    """
    return coverage_report(layout, mapping).count


def apply_to(layout: InterfaceLayout, mapping: Mapping) -> InterfaceLayout:
    """Return a copy of ``layout`` re-wired for ``mapping`` (never mutates input).

    A layout that declares ``match_by == "ident"`` and whose ``slug`` names a column
    is matched slot-by-slot on its ``ident`` and re-stamped with the net's
    ``(connector, pin)``. This is what makes deviating wiring — a cable or adapter
    that routes a pad to a different tester pin than its nominal one — show up
    correctly, and it is what gives a geometry-only import (whose nominal address is
    a synthetic placeholder) its real address. A reference layout is matched on
    ``(connector, pin)``, which is already the net's address, so it is returned
    unchanged. A layout the mapping does not describe is returned unchanged.
    """
    if layout.match_by == "connector_pin":
        return layout
    column = _column_for(layout, mapping)
    if column is None:
        return layout

    ident_map = mapping.idents_for(column)
    folded = {i.casefold(): n for i, n in ident_map.items()}

    def rewired(slot):
        if not slot.ident:
            return slot
        net = ident_map.get(slot.ident) or folded.get(slot.ident.casefold())
        if net is None:
            return slot
        return replace(slot, connector=net.connector, pin=net.pin)

    return replace(layout, slots=[rewired(s) for s in layout.slots])


__all__ = [
    "CONNECTOR_HEADER",
    "IDENT_SEPARATOR",
    "PIN_HEADERS",
    "CoverageReport",
    "Mapping",
    "Net",
    "apply_to",
    "coverage",
    "coverage_report",
    "load_csv",
    "normalize_header",
    "normalize_ident",
]
