"""Loopback pairs: which interface pads a loopback PCB shorts together.

Fitting a loopback PCB to an interface (e.g. the interposer) shorts its pads in
pairs, so a filter measurement through a working interface charges *two* filter
capacitors per pin and reads about twice the nominal C (see the AFE README,
"Shorts between Electrodes"). The pairs file says which pads are paired::

    {
      "schema": 1,
      "kind": "loopback-pairs",
      "name": "Interposer loopback PCB",
      "source": "loopback-pcb rev A",
      "interface": "interposer",
      "pairs": [["A3", "B7"], ["C1", "C2"]]
    }

Pads are named on one interface — ``interface`` is that layout's slug, i.e. the
mapping CSV's column header. The file deliberately holds **no tester address**:
the same loopback PCB is tested through many cablings, so each pad's
``(connector, pin)`` comes from the selected mapping at analysis time
(:func:`resolve_pairs`). Anything the mapping cannot resolve is reported as a
problem, never guessed.
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
KIND = "loopback-pairs"

Address = tuple[int, int]  # (connector, pin)

_MAX_LISTED = 10  # pads named in one problem line before it says "… and N more"


@dataclass
class LoopbackPairs:
    """The pad pairs one loopback PCB shorts together, on one interface."""

    interface: str = ""  # layout slug == mapping column header (normalised)
    pairs: list[tuple[str, str]] = field(default_factory=list)
    name: str = ""
    source: str = ""

    def __bool__(self) -> bool:
        return bool(self.pairs)

    def describe(self) -> str:
        if not self.pairs:
            return "none loaded"
        text = f"{len(self.pairs)} pair(s) on '{self.interface}'"
        if self.name:
            text = f"{self.name}: {text}"
        return text

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA_VERSION,
            "kind": KIND,
            "name": self.name,
            "source": self.source,
            "interface": self.interface,
            "pairs": [list(pair) for pair in self.pairs],
        }

    @classmethod
    def from_dict(cls, data: Any) -> LoopbackPairs:
        """Validate and build. Empty or missing data is an empty set of pairs.

        Raises :class:`ValueError` naming the fix for anything malformed — a
        pairs table is acceptance data, so a silently dropped pair would turn a
        broken loop into an "unpaired" pin that passes.
        """
        if isinstance(data, LoopbackPairs):
            return data
        if not data:
            return cls()
        _check_header(data)
        interface = normalize_header(str(data.get("interface") or ""))
        raw_pairs = data.get("pairs") or []
        if raw_pairs and not interface:
            raise ValueError(
                "'interface' is missing: name the layout slug (the mapping CSV "
                'column) the pads are named on, e.g. "interposer"'
            )
        if not isinstance(raw_pairs, list):
            raise ValueError("'pairs' must be a list of [pad, pad] pairs")
        return cls(
            interface=interface,
            pairs=_checked_pairs(raw_pairs),
            name=str(data.get("name") or ""),
            source=str(data.get("source") or ""),
        )


def _check_header(data: Any) -> None:
    """Reject anything that is not a loopback-pairs object this app can read."""
    if not isinstance(data, dict):
        raise ValueError("loopback pairs must be a JSON object")
    kind = data.get("kind", KIND)
    if kind != KIND:
        raise ValueError(f"not a loopback-pairs file (kind {kind!r})")
    schema = data.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, int) or schema > SCHEMA_VERSION:
        raise ValueError(
            f"loopback-pairs schema {schema} is newer than this app supports "
            f"(max {SCHEMA_VERSION})"
        )


def _checked_pad(where: str, raw: Any) -> str:
    if not isinstance(raw, str) or not normalize_ident(raw):
        raise ValueError(f"{where}: pad names must be non-empty strings")
    pad = normalize_ident(raw)
    if "," in pad or IDENT_SEPARATOR in pad:
        raise ValueError(f"{where}: pad {pad!r} contains a ',' or ';'")
    return pad


def _checked_pairs(raw_pairs: list[Any]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    seen: dict[str, int] = {}  # pad -> index of the pair that names it
    for i, raw in enumerate(raw_pairs):
        where = f"pair {i + 1}"
        if not isinstance(raw, list | tuple) or len(raw) != 2:  # noqa: PLR2004
            raise ValueError(f"{where}: expected exactly two pads, got {raw!r}")
        a, b = (_checked_pad(where, pad) for pad in raw)
        if a == b:
            raise ValueError(f"{where}: pad {a!r} is paired with itself")
        for pad in (a, b):
            if pad in seen:
                raise ValueError(
                    f"{where}: pad {pad!r} is already in pair {seen[pad] + 1}"
                )
            seen[pad] = i
        pairs.append((a, b))
    return pairs


def load_pairs(path: str | Path) -> LoopbackPairs:
    """Read a pairs file; it must declare its kind (raises ValueError / OSError)."""
    path = Path(path)
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("kind") != KIND:
        raise ValueError(f"{path.name} is not a loopback-pairs file (kind {KIND!r})")
    pairs = LoopbackPairs.from_dict(data)
    if not pairs:
        raise ValueError(f"{path.name} lists no pairs")
    if not pairs.source:
        pairs.source = path.name
    return pairs


# ---- resolution through a mapping ------------------------------------------
@dataclass
class PadLink:
    """One paired pad, as resolved: its address and its partner's."""

    pad: str
    partner_pad: str
    partner: Address | None  # None when the mapping cannot place the partner


@dataclass
class Resolution:
    """The pairs placed on tester addresses, plus everything that did not resolve.

    ``links`` holds every paired pad the mapping *could* place, keyed by its own
    address — including pads whose partner did not resolve (``partner`` is then
    ``None``), because such a pin is still on the loopback and must read 2x.
    ``ok`` is False when nothing could be resolved at all (no mapping, or the
    mapping lacks the interface column); the analysis then judges nothing.
    """

    links: dict[Address, PadLink] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    ok: bool = True

    def pairs(self) -> list[tuple[Address, Address]]:
        """Each fully resolved pair once, as ``(address, partner address)``."""
        out: list[tuple[Address, Address]] = []
        for addr, link in self.links.items():
            if link.partner is not None and addr < link.partner:
                out.append((addr, link.partner))
        return out


def _listed(items: list[str]) -> str:
    shown = ", ".join(items[:_MAX_LISTED])
    extra = len(items) - _MAX_LISTED
    return f"{shown} … and {extra} more" if extra > 0 else shown


def resolve_pairs(pairs: LoopbackPairs, mapping: Mapping | None) -> Resolution:
    """Place every paired pad on its ``(connector, pin)`` via ``mapping``.

    Problems reported (each also leaves the affected pad or pair unresolved):

    * no mapping selected, or the mapping has no column for the interface;
    * pads the mapping does not name;
    * a pair whose two pads are the same net in the mapping;
    * one tester address claimed by two pads.
    """
    if mapping is None:
        return Resolution(
            problems=[
                "No mapping selected — loopback pads are named on "
                f"'{pairs.interface}' and need a mapping to find their tester pins."
            ],
            ok=False,
        )
    if pairs.interface not in mapping.interfaces:
        return Resolution(
            problems=[
                f"Mapping '{mapping.name}' has no '{pairs.interface}' column "
                f"(it names: {', '.join(mapping.interfaces) or 'nothing'})."
            ],
            ok=False,
        )

    nets = mapping.idents_for(pairs.interface)
    address: dict[str, Address] = {
        pad: (nets[pad].connector, nets[pad].pin)
        for pair in pairs.pairs
        for pad in pair
        if pad in nets
    }
    res = Resolution()

    missing = [pad for pair in pairs.pairs for pad in pair if pad not in address]
    if missing:
        res.problems.append(
            f"{len(missing)} paired pad(s) not in mapping '{mapping.name}': "
            f"{_listed(missing)}"
        )

    claimed: dict[Address, str] = {}  # address -> the pad that took it first
    for a, b in pairs.pairs:
        addr_a, addr_b = address.get(a), address.get(b)
        if addr_a is not None and addr_a == addr_b:
            res.problems.append(
                f"Pair {a}/{b}: both pads are the same net (connector "
                f"{addr_a[0]}, pin {addr_a[1]}) in mapping '{mapping.name}'."
            )
            continue
        _link(res, claimed, (a, addr_a), (b, addr_b))
        _link(res, claimed, (b, addr_b), (a, addr_a))
    return res


def _link(
    res: Resolution, claimed: dict[Address, str],
    this: tuple[str, Address | None], other: tuple[str, Address | None],
) -> None:
    """Record one paired pad at its address, unless another pad already holds it."""
    pad, own = this
    partner_pad, partner = other
    if own is None:
        return
    if own in claimed:
        res.problems.append(
            f"Connector {own[0]} pin {own[1]} is claimed by pads "
            f"{claimed[own]} and {pad}."
        )
        return
    claimed[own] = pad
    res.links[own] = PadLink(pad, partner_pad, partner)


__all__ = [
    "KIND",
    "SCHEMA_VERSION",
    "Address",
    "LoopbackPairs",
    "PadLink",
    "Resolution",
    "load_pairs",
    "resolve_pairs",
]
