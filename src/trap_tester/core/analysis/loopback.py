"""Loopback boards: which interface pads a loopback PCB joins, and which it grounds.

Fitting a loopback PCB to an interface (e.g. the interposer) shorts its pads
together, so a filter measurement through a working interface charges every
filter capacitor of a joined group at once: a pin in a group of *n* pads reads
about *n* times the nominal C (see the AFE README, "Shorts between Electrodes").
Most groups are pairs; a heater's force/sense pads are a group joined through the
heating element. Pads the board ties to ground should read as shorted. The board
file says which is which::

    {
      "schema": 1,
      "kind": "loopback",
      "name": "Interposer loopback PCB",
      "source": "loopback-pcb rev A",
      "interface": "interposer",
      "groups": [["A3", "B7"], ["N9", "N18"]],
      "gnd": ["C3", "D4"]
    }

List only pads that carry a filter channel: a group's size *is* the number of
filters a pin of it should see. Pads are named on one interface — ``interface``
is that layout's slug, i.e. the mapping CSV's column header. The file
deliberately holds **no tester address**: the same board is tested through many
cablings, so each pad's ``(connector, pin)`` comes from the selected mapping at
analysis time (:func:`resolve_board`). Anything the mapping cannot resolve is
reported as a problem, never guessed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from trap_tester.core.layout.mapping import (
    IDENT_SEPARATOR,
    normalize_header,
    normalize_ident,
)

if TYPE_CHECKING:
    from trap_tester.core.layout.mapping import Mapping

SCHEMA_VERSION = 1
KIND = "loopback"

Address = tuple[int, int]  # (connector, pin)

_MAX_LISTED = 10  # pads named in one problem line before it says "… and N more"
_MIN_GROUP = 2


@dataclass
class LoopbackBoard:
    """What one loopback PCB does to an interface: pad groups and grounded pads."""

    interface: str = ""  # layout slug == mapping column header (normalised)
    groups: list[tuple[str, ...]] = field(default_factory=list)
    gnd: list[str] = field(default_factory=list)  # pads the board shorts to GND
    name: str = ""
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.groups or self.gnd)

    def describe(self) -> str:
        if not self:
            return "none loaded"
        n_pairs = sum(1 for g in self.groups if len(g) == _MIN_GROUP)
        parts = [f"{len(self.groups)} group(s)"]
        if n_pairs != len(self.groups):
            parts[0] += f" ({n_pairs} pairs)"
        if self.gnd:
            parts.append(f"{len(self.gnd)} GND pad(s)")
        text = f"{', '.join(parts)} on '{self.interface}'"
        return f"{self.name}: {text}" if self.name else text

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "kind": KIND,
            "name": self.name,
            "source": self.source,
            "interface": self.interface,
            "groups": [list(group) for group in self.groups],
            "gnd": list(self.gnd),
        }

    @classmethod
    def from_dict(cls, data: Any) -> LoopbackBoard:
        """Validate and build. Empty or missing data is an empty board.

        Raises :class:`ValueError` naming the fix for anything malformed — this
        is acceptance data, so a silently dropped group would turn a broken loop
        into an "ungrouped" pin that passes.
        """
        if isinstance(data, LoopbackBoard):
            return data
        if not data:
            return cls()
        _check_header(data)
        interface = normalize_header(str(data.get("interface") or ""))
        raw_groups = data.get("groups") or []
        raw_gnd = data.get("gnd") or []
        if not isinstance(raw_groups, list) or not isinstance(raw_gnd, list):
            raise ValueError("'groups' must list pad lists and 'gnd' must list pads")
        if (raw_groups or raw_gnd) and not interface:
            raise ValueError(
                "'interface' is missing: name the layout slug (the mapping CSV "
                'column) the pads are named on, e.g. "interposer"'
            )
        seen: dict[str, str] = {}  # pad -> where it was first named
        groups = [_checked_group(i, raw, seen) for i, raw in enumerate(raw_groups)]
        gnd = [_checked_pad("gnd", raw, seen) for raw in raw_gnd]
        return cls(
            interface=interface, groups=groups, gnd=gnd,
            name=str(data.get("name") or ""), source=str(data.get("source") or ""),
        )


def _check_header(data: Any) -> None:
    """Reject anything that is not a loopback-board object this app can read."""
    if not isinstance(data, dict):
        raise ValueError("a loopback board must be a JSON object")
    kind = data.get("kind", KIND)
    if kind != KIND:
        raise ValueError(f"not a loopback-board file (kind {kind!r}, not {KIND!r})")
    schema = data.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, int) or schema > SCHEMA_VERSION:
        raise ValueError(
            f"loopback schema {schema} is newer than this app supports "
            f"(max {SCHEMA_VERSION})"
        )


def _checked_pad(where: str, raw: Any, seen: dict[str, str]) -> str:
    if not isinstance(raw, str) or not normalize_ident(raw):
        raise ValueError(f"{where}: pad names must be non-empty strings")
    pad = normalize_ident(raw)
    if "," in pad or IDENT_SEPARATOR in pad:
        raise ValueError(f"{where}: pad {pad!r} contains a ',' or ';'")
    if pad in seen:
        raise ValueError(f"{where}: pad {pad!r} is already named in {seen[pad]}")
    seen[pad] = where
    return pad


def _checked_group(index: int, raw: Any, seen: dict[str, str]) -> tuple[str, ...]:
    where = f"group {index + 1}"
    if not isinstance(raw, list | tuple) or len(raw) < _MIN_GROUP:
        raise ValueError(f"{where}: a group joins at least two pads, got {raw!r}")
    return tuple(_checked_pad(where, pad, seen) for pad in raw)


def load_board(path: str | Path) -> LoopbackBoard:
    """Read a board file; it must declare its kind (raises ValueError / OSError)."""
    path = Path(path)
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise ValueError(f"{path.name} is not a loopback-board file (kind {KIND!r})")
    board = LoopbackBoard.from_dict(data)
    if not board:
        raise ValueError(f"{path.name} lists no groups and no GND pads")
    if not board.source:
        board.source = path.name
    return board


# ---- resolution through a mapping ------------------------------------------
@dataclass
class Member:
    """One grouped pad, as resolved: which group, and where its partners are."""

    pad: str
    group: int  # index into LoopbackBoard.groups
    size: int  # pads in the group == filters a pin of it should see
    # the other pads of the group, each with its address (None: mapping lacks it)
    others: list[tuple[str, Address | None]]


@dataclass
class Resolution:
    """The board placed on tester addresses, plus everything that did not resolve.

    ``members`` holds every grouped pad the mapping *could* place, keyed by its
    own address — including pads whose partners did not resolve, because such a
    pin is still on the loopback and must read its group's count. ``gnd`` maps
    each placed ground pad's address to its name. ``ok`` is False when nothing
    could be resolved at all (no mapping, or the mapping lacks the interface
    column); the analysis then judges nothing.
    """

    members: dict[Address, Member] = field(default_factory=dict)
    gnd: dict[Address, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    ok: bool = True

    def groups(self) -> list[list[Address]]:
        """Each group's placed addresses, in board order (groups with ≥2 only)."""
        by_group: dict[int, list[Address]] = {}
        for addr, member in self.members.items():
            by_group.setdefault(member.group, []).append(addr)
        return [a for _, a in sorted(by_group.items()) if len(a) >= _MIN_GROUP]


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_LISTED])
    extra = len(items) - _MAX_LISTED
    return f"{shown} … and {extra} more" if extra > 0 else shown


class _Claims:
    """Hands out tester addresses, reporting any address two pads both want."""

    def __init__(self, address: dict[str, Address], res: Resolution, name: str):
        self._address = address
        self._res = res
        self._name = name
        self._claimed: dict[Address, str] = {}  # address -> the pad that took it

    def __call__(self, pad: str) -> Address | None:
        own = self._address.get(pad)
        if own is None:
            return None
        if own in self._claimed:
            self._res.problems.append(
                f"Connector {own[0]} pin {own[1]} is claimed by pads "
                f"{self._claimed[own]} and {pad} (one net in mapping '{self._name}')."
            )
            return None
        self._claimed[own] = pad
        return own


def _unusable_mapping(board: LoopbackBoard, mapping: Mapping | None) -> str:
    """Why ``mapping`` cannot place any of the board's pads ("" when it can)."""
    if mapping is None:
        return (
            "No mapping selected — loopback pads are named on "
            f"'{board.interface}' and need a mapping to find their tester pins."
        )
    if board.interface not in mapping.interfaces:
        return (
            f"Mapping '{mapping.name}' has no '{board.interface}' column "
            f"(it names: {', '.join(mapping.interfaces) or 'nothing'})."
        )
    return ""


def resolve_board(board: LoopbackBoard, mapping: Mapping | None) -> Resolution:
    """Place every grouped and grounded pad on its ``(connector, pin)``.

    Problems reported (each also leaves the affected pad unresolved):

    * no mapping selected, or the mapping has no column for the interface;
    * pads the mapping does not name;
    * one tester address claimed by two pads (e.g. two pads of a group that are
      the same net in the mapping).
    """
    unusable = _unusable_mapping(board, mapping)
    if unusable:
        return Resolution(problems=[unusable], ok=False)
    assert mapping is not None  # narrowed by _unusable_mapping

    nets = mapping.idents_for(board.interface)
    address = {pad: (net.connector, net.pin) for pad, net in nets.items()}
    res = Resolution()
    named = [pad for group in board.groups for pad in group] + list(board.gnd)
    missing = [pad for pad in named if pad not in address]
    if missing:
        res.problems.append(
            f"{len(missing)} loopback pad(s) not in mapping '{mapping.name}': "
            f"{_listed(missing)}"
        )

    _place(board, address, res, _Claims(address, res, mapping.name))
    return res


def _place(
    board: LoopbackBoard, address: dict[str, Address], res: Resolution, claim: _Claims
) -> None:
    """Record every grouped and grounded pad at the address it can claim."""
    for g, group in enumerate(board.groups):
        for pad in group:
            own = claim(pad)
            if own is not None:
                others = [(o, address.get(o)) for o in group if o != pad]
                res.members[own] = Member(pad, g, len(group), others)
    for pad in board.gnd:
        own = claim(pad)
        if own is not None:
            res.gnd[own] = pad


__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "Address",
    "LoopbackBoard",
    "Member",
    "Resolution",
    "load_board",
    "resolve_board",
]
