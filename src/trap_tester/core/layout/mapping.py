"""Setup-specific cross-interface wiring maps.

Every layout bakes in an *inherent* wiring — each :class:`~trap_tester.core.layout
.interface.Slot` carries a fixed ``(connector, pin)`` and a ``channel`` (mux
signal), and interfaces correlate by shared ``(connector, channel)``. But the
trap-tester's interfaces (DSUB-50, interposer, bond-finger ring, ion-trap
electrodes …) are joined by cables, adapter PCBs and vacuum feedthroughs that a
real setup wires differently. A **mapping** is a per-setup CSV that declares, net
by net, how the interfaces actually interconnect — overriding the inherent wiring.

CSV shape: one column per interface (its header is that layout's *display name*)
plus a **connector** column and a **DSUB-pin** column — the trap-tester's main
interface, which is always required. Each row is one net::

    hawk3,Bondfinger,LGA_Pad,N Connecgor,DSUB_Pin
    COMP_0_0,287,B25,4,31

Here the net named ``COMP_0_0`` on the ``hawk3`` interface, ``287`` on
``Bondfinger`` and ``B25`` on ``LGA_Pad`` is measured at tester connector 4, pin
31. A cell may be blank — then that net has no identifier on that interface.

:func:`apply_to` re-stamps a layout's slots for a mapping so that both tabs work
unchanged: it matches a **named** layout's slots by their per-interface ``ident``
(the LGA pad / finger / electrode name) and a **reference** layout (DSUB-50, or
any interface the CSV never names) by ``(connector, pin)``, giving every slot of a
net the same ``channel`` (the net's id). Analysis then colours the right slot and
annotations re-project along the setup's real wiring. Slots with no matching net
keep their inherent wiring — the "interface not mentioned → infer from the
standard mapping" fallback.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trap_tester.core.layout.interface import InterfaceLayout

# Header spellings that designate the trap-tester's main-interface columns (the
# only required ones). Every other column is named after a layout and holds that
# interface's per-net identifier. Spelling is tolerated the same way the ion-trap
# importer tolerates its connector column (incl. the source data's "N Connecgor").
_CONNECTOR_KEYS = (
    "N Connecgor", "N Connector", "Connector", "Connector_Num",
    "Connector number", "n_conn",
)
_PIN_KEYS = ("DSUB_Pin", "DSUB-Pin", "Pin", "dsub_pin")

# The DSUB pin is recorded with a hundreds digit that encodes the connector bank
# (e.g. 126 on connector 7 -> physical pin 26); the trap tester's DSUB-50 has only
# 50 pins, so the actual pin is the value modulo 100.
_PIN_MODULO = 100


@dataclass
class Net:
    """One electrical net: a tester pin plus its name on each named interface."""

    connector: int
    pin: int
    idents: dict[str, str]  # interface name -> this net's identifier there
    net_id: int  # stable per-mapping id; used as the shared correlation channel


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
            ident = net.idents.get(interface)
            if ident:
                out[ident] = net
        return out

    def by_connector_pin(self) -> dict[tuple[int, int], Net]:
        """``(connector, pin) -> net`` for the reference interface."""
        return {(n.connector, n.pin): n for n in self.nets}


def _find_key(
    fields: list[str], candidates: tuple[str, ...], path: Path, what: str
) -> str:
    key = next((k for k in candidates if k in fields), None)
    if key is None:
        raise ValueError(f"{path}: no {what} column (looked for {candidates})")
    return key


def load_csv(path: str | Path) -> Mapping:
    """Parse a mapping CSV into a :class:`Mapping`.

    The connector and DSUB-pin columns are detected by tolerant header spelling;
    every other column is a named interface. Rows without a tester pin are skipped
    (a net with no ``(connector, pin)`` cannot be placed), but ``net_id`` still
    tracks the source row so the mapping is deterministic.
    """
    path = Path(path)
    with path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        fields = list(reader.fieldnames or [])
        conn_key = _find_key(fields, _CONNECTOR_KEYS, path, "connector")
        pin_key = _find_key(fields, _PIN_KEYS, path, "DSUB pin")
        interfaces = [f for f in fields if f not in (conn_key, pin_key)]
        nets: list[Net] = []
        for i, row in enumerate(reader):
            conn_raw = (row.get(conn_key) or "").strip()
            pin_raw = (row.get(pin_key) or "").strip()
            if not conn_raw or not pin_raw:
                continue
            idents = {
                iface: val
                for iface in interfaces
                if (val := (row.get(iface) or "").strip())
            }
            nets.append(
                Net(connector=int(conn_raw), pin=int(pin_raw) % _PIN_MODULO,
                    idents=idents, net_id=i)
            )
    return Mapping(name=path.stem, interfaces=interfaces, nets=nets)


def _ident_column(layout: InterfaceLayout, mapping: Mapping) -> str | None:
    """The mapping column this layout's slots are identified by, or ``None``.

    Prefer an exact column named after the layout (``layout.name``). Otherwise fall
    back to the column whose identifiers overlap the layout's slot ``ident`` s the
    most — so a layout whose *display* name differs from its CSV column (e.g. an
    interposer named "Interposer" whose pads live in an "LGA_Pad" column) is still
    re-wired by identity rather than by its inherent, possibly-deviating pins.
    ``None`` when nothing matches — the reference interface (DSUB-50) whose slots
    carry no ``ident`` and are matched by ``(connector, pin)`` instead.
    """
    if layout.name in mapping.interfaces:
        return layout.name
    slot_idents = {s.ident for s in layout.slots if s.ident}
    if not slot_idents:
        return None
    best, best_overlap = None, 0
    for iface in mapping.interfaces:
        overlap = len(slot_idents & set(mapping.idents_for(iface)))
        if overlap > best_overlap:
            best, best_overlap = iface, overlap
    return best


def _match_mode(layout: InterfaceLayout, mapping: Mapping) -> tuple[str, str | None]:
    """How ``mapping`` applies to ``layout``.

    * ``("ident", column)`` — the layout is one of the mapping's interfaces (by name
      or best ``ident`` overlap); match slots by ``ident``.
    * ``("reference", None)`` — the tester reference interface (DSUB-50: no ``ident``
      s, ``key_by == "dsub_pin"``); match slots by ``(connector, pin)``.
    * ``("none", None)`` — the mapping does not describe this layout at all. Notably
      an ident-bearing custom layout the mapping never names is NOT reference-matched
      — its ``(connector, pin)`` live in a different family, so any numeric overlap
      would be coincidental and wrong (a hawk1 layout under a hawk3 mapping). The GUI
      warns and the layout keeps its inherent wiring.
    """
    column = _ident_column(layout, mapping)
    if column is not None:
        return "ident", column
    has_idents = any(s.ident for s in layout.slots)
    if not has_idents and layout.key_by == "dsub_pin":
        return "reference", None
    return "none", None


def coverage(layout: InterfaceLayout, mapping: Mapping) -> int:
    """How many of ``layout``'s slots ``mapping`` would re-wire.

    Zero means the mapping does not touch this layout at all — it can neither be
    propagated *to* nor *from* it — so a GUI should warn rather than silently show
    the inherent wiring. Uses the same match choice as :func:`apply_to`.
    """
    mode, column = _match_mode(layout, mapping)
    if mode == "ident":
        ident_map = mapping.idents_for(column)  # type: ignore[arg-type]
        return sum(1 for s in layout.slots if s.ident and s.ident in ident_map)
    if mode == "reference":
        cp_map = mapping.by_connector_pin()
        return sum(1 for s in layout.slots if (s.connector, s.pin) in cp_map)
    return 0


def apply_to(layout: InterfaceLayout, mapping: Mapping) -> InterfaceLayout:
    """Return a copy of ``layout`` re-wired for ``mapping`` (never mutates input).

    A layout identified by a CSV column (by name, else by best ``ident`` overlap —
    see :func:`_ident_column`) is matched slot-by-slot on its ``ident`` and
    re-stamped with the net's ``(connector, pin)`` and id-as-``channel``. This is
    what makes deviating wiring — a cable/adapter that routes a pad to a different
    tester pin than its inherent one — show up correctly. The tester reference
    interface (DSUB-50) is matched by ``(connector, pin)`` and only re-channelled,
    so it shares the net-id channel space and correlates with the named layouts. A
    layout the mapping does not describe (see :func:`_match_mode`) is returned
    unchanged. Slots that match no net keep their inherent wiring.
    """
    mode, column = _match_mode(layout, mapping)
    if mode == "ident":
        ident_map = mapping.idents_for(column)  # type: ignore[arg-type]
        new_slots = [
            replace(s, connector=n.connector, pin=n.pin, channel=n.net_id)
            if s.ident is not None and (n := ident_map.get(s.ident)) is not None
            else s
            for s in layout.slots
        ]
    elif mode == "reference":
        cp_map = mapping.by_connector_pin()
        new_slots = [
            replace(s, channel=n.net_id)
            if (n := cp_map.get((s.connector, s.pin))) is not None
            else s
            for s in layout.slots
        ]
    else:
        new_slots = list(layout.slots)
    return replace(layout, slots=new_slots)


__all__ = ["Mapping", "Net", "apply_to", "coverage", "load_csv"]
