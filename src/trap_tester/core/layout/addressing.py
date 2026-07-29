"""Canonical slot addressing: the one place a pin number is interpreted.

Every slot in every layout carries ``(connector, pin)`` — the *apparatus'*
electrical address, which is meaningful whether or not the tester is plugged in.
Two jobs need care, and both live here so nothing else has to know the rules:

**Canonical form.** ``pin`` is a number in the layout's ``pin_space``: a DSUB pin
for ``"dsub_pin"``, a ribbon conductor for ``"fpc_conductor"``. Those are different
numbering systems, so marks and findings correlate only after both sides are
reduced to one. :func:`canonical_address` does that, using the DSUB pin space as
the canonical one (it is the tester's own interface). This replaces the old stored
``Slot.channel``, which meant three incompatible things depending on which
generator wrote the file.

**Synthetic addresses.** Some imported layouts describe geometry whose real wiring
is only known from a mapping CSV — historically they were written with every slot
at ``(0, 0)``, which made all of them collide. :func:`synthetic_addresses` hands
those slots distinct, deterministic addresses in a reserved connector band
(:data:`SYNTHETIC_CONNECTOR_BASE` and up) so they can be browsed and marked
without ever colliding with a physical address. A CSV overrides them; anything
left synthetic is detectable with :func:`is_synthetic` so the GUI can say so.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from trap_tester.mux_mapping import signal_to_dsub, signal_to_fpc

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

# Reserved connector band for made-up addresses. Well above the tester's physical
# connector count, so a synthetic address can never be mistaken for — or collide
# with — a real one, in this layout or any other.
SYNTHETIC_CONNECTOR_BASE = 900
PINS_PER_CONNECTOR = 50  # DSUB-50: enumeration wraps to the next connector after 50

# FPC conductor -> canonical signal (the inverse of the hardware table).
_fpc_to_signal = {conductor: signal for signal, conductor in signal_to_fpc.items()}


def canonical_address(
    connector: int, pin: int, pin_space: str = "dsub_pin"
) -> tuple[int, int] | None:
    """``(connector, dsub_pin)`` for a slot, or ``None`` if it has no canonical form.

    The DSUB pin space is canonical, so ``"dsub_pin"`` layouts pass through. An
    ``"fpc_conductor"`` pin is translated conductor -> signal -> DSUB pin, which is
    what makes a mark on a DSUB pin show up on the ribbon conductor carrying the
    same signal. Synthetic addresses are their own space and pass through unchanged.

    ``None`` means "this pin carries no canonical signal" — an FPC GND/shield
    conductor, or an unknown pin space.
    """
    if is_synthetic(connector) or pin_space == "dsub_pin":
        return (connector, pin)
    if pin_space == "fpc_conductor":
        signal = _fpc_to_signal.get(pin)
        if signal is None:  # conductors 1 & 51 are the GND shield
            return None
        dsub = signal_to_dsub.get(signal)
        return None if dsub is None else (connector, dsub)
    return None


def is_synthetic(connector: int) -> bool:
    """Whether ``connector`` is a made-up address rather than a physical one."""
    return connector >= SYNTHETIC_CONNECTOR_BASE


def natural_key(text: str) -> tuple:
    """Sort key that compares digit runs numerically (``A2`` before ``A10``).

    Used to order synthetic addresses so they are stable under a reordering of the
    source data — enumerating in file order would silently move every existing
    annotation whenever the source CSV was re-sorted.
    """
    return tuple(
        int(part) if part.isdigit() else part.casefold()
        for part in re.split(r"(\d+)", text)
        if part != ""
    )


def synthetic_addresses(idents: Iterable[str]) -> dict[str, tuple[int, int]]:
    """Assign each ident a distinct synthetic ``(connector, pin)``.

    Enumerates pins ``1..PINS_PER_CONNECTOR`` and wraps to the next connector,
    starting at :data:`SYNTHETIC_CONNECTOR_BASE`, in :func:`natural_key` order of
    the idents. Deterministic and stable: the same set of idents always yields the
    same addresses, whatever order they arrive in.
    """
    ordered: Sequence[str] = sorted(set(idents), key=natural_key)
    out: dict[str, tuple[int, int]] = {}
    for index, ident in enumerate(ordered):
        connector = SYNTHETIC_CONNECTOR_BASE + index // PINS_PER_CONNECTOR
        out[ident] = (connector, index % PINS_PER_CONNECTOR + 1)
    return out


__all__ = [
    "PINS_PER_CONNECTOR",
    "SYNTHETIC_CONNECTOR_BASE",
    "canonical_address",
    "is_synthetic",
    "natural_key",
    "synthetic_addresses",
]
