"""Generate the FPC ribbon layout.

The flat-flex ribbon that carries the trap channels off the DSUB connector. It
has 51 conductors in one row; conductors 1 and 51 are hardwired to GND and act
as shielding (they carry no channel), so the 49 channel-carrying conductors are
2..50. Like the DSUB-50 layout the geometry is generated here and dumped to
``layouts/fpc.json`` (run ``python -m trap_tester.core.layout.fpc``), which then
becomes the editable source of truth loaded at runtime.

A contact's ``pin`` is its ribbon conductor, so this layout's pin space is
``fpc_conductor`` rather than ``dsub_pin``. Correlating a mark between the ribbon
and the DSUB connector is the job of
:func:`~trap_tester.core.layout.addressing.canonical_address`, which reduces a
conductor to the DSUB pin carrying the same signal — no stored channel needed. The
two shield conductors are ``class="gnd"``: drawn and labelled so the whole ribbon
is visible, but inert.
"""

from __future__ import annotations

from pathlib import Path

from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.primitives import Rect, Text
from trap_tester.mux_mapping import FPC_GND_CONDUCTORS, FPC_N_CONDUCTORS

# --- geometry (arbitrary mm-like units; only the proportions matter) ---------
PITCH = 1.0          # spacing between adjacent contacts
CONTACT_R = 0.4      # half-size of a (square) contact
_MARGIN_X = 0.8
_MARGIN_Y = 0.8

def fpc_conductors() -> list[int]:
    """Every FPC conductor, in ribbon order (1..51, GND shields included)."""
    return list(range(1, FPC_N_CONDUCTORS + 1))


def generate_fpc(connector: int = 0) -> InterfaceLayout:
    """Build the :class:`InterfaceLayout` for one FPC ribbon."""
    conductors = fpc_conductors()
    slots = [
        Slot(
            connector=connector, pin=conductor, x=j * PITCH, y=0.0,
            r=CONTACT_R, shape="rect",
            pad_class="gnd" if conductor in FPC_GND_CONDUCTORS else "signal",
        )
        for j, conductor in enumerate(conductors)
    ]

    x_max = (len(conductors) - 1) * PITCH
    body = Rect(
        x=x_max / 2, y=0.0,
        w=x_max + 2 * _MARGIN_X, h=2 * CONTACT_R + 2 * _MARGIN_Y,
        style="outline",
    )
    caption = Text(
        x=0.0, y=CONTACT_R + _MARGIN_Y + 0.35,
        text=(
            f"FPC ribbon · connector {connector} · {len(conductors)} conductors "
            f"(1 & 51 = GND shield)"
        ),
        ha="left", va="bottom", style="caption",
    )
    # Label the GND shields so they read as shielding, not unmeasured channels.
    gnd_labels = [
        Text(
            x=(conductors.index(c)) * PITCH, y=-(CONTACT_R + 0.3),
            text="GND", ha="center", va="top", style="grid_label",
        )
        for c in FPC_GND_CONDUCTORS
        if c in conductors
    ]
    return InterfaceLayout(
        name=f"FPC ribbon (connector {connector})", slug="fpc",
        units="mm", pin_space="fpc_conductor", match_by="connector_pin",
        background=[body, caption, *gnd_labels], slots=slots,
    )


def default_json_path() -> Path:
    return Path(__file__).with_name("layouts") / "fpc.json"


def _dump() -> None:
    out = default_json_path()
    out.parent.mkdir(exist_ok=True)
    generate_fpc().save_json(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    _dump()
