"""Generate the standard HD-50 (DSUB-50) connector layout.

High-density DSUB-50: three staggered rows of 17 / 16 / 17 pins. Front (mating)
view, pin 1 at the top-left, numbered left-to-right per row::

    row A:  1 ............... 17
    row B:    18 ......... 33
    row C: 34 ............... 50

The geometry is generated here (rather than hand-typing 50 coordinates) and can
be dumped to ``layouts/dsub50.json`` — run ``python -m
trap_tester.core.layout.dsub50`` — which then becomes the editable source of
truth loaded at runtime. Flip ``front_view`` for the solder-/wire-side mirror.
"""

from __future__ import annotations

import math
from pathlib import Path

from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.primitives import Polyline, Text
from trap_tester.mux_mapping import dsub_to_signal

# --- geometry (arbitrary mm-like units; only the proportions matter) ---------
PITCH = 1.0          # horizontal spacing between adjacent pins in a row
ROW_DY = 1.0         # vertical spacing between rows
PIN_R = 0.38         # pin circle radius
_ROWS = (
    (1, 17, 0.0),    # row A: pins 1..17,  x offset 0.0
    (18, 33, 0.5),   # row B: pins 18..33, x offset +0.5 (staggered)
    (34, 50, 0.0),   # row C: pins 34..50, x offset 0.0
)
_X_MAX = 16.0        # (17 pins - 1) * PITCH — used for the mirror transform


def generate_dsub50(connector: int = 1, front_view: bool = True) -> InterfaceLayout:
    """Build the :class:`InterfaceLayout` for one DSUB-50 connector."""
    slots: list[Slot] = []
    top_y = (len(_ROWS) - 1) * ROW_DY
    for row_idx, (first, last, x_off) in enumerate(_ROWS):
        y = top_y - row_idx * ROW_DY
        for j, pin in enumerate(range(first, last + 1)):
            slots.append(
                Slot(
                    connector=connector, pin=pin, x=(j + x_off) * PITCH, y=y,
                    r=PIN_R, channel=dsub_to_signal.get(pin),
                )
            )

    # D-shell outline: a trapezoid that flares *outward* toward the top so both
    # full-width outer rows sit comfortably inside, with rounded corners. The
    # margins clear the pin radius on every side.
    mx, my, taper = 0.85, 0.85, 1.2
    x_lo, x_hi = -mx, _X_MAX + mx
    y_hi, y_lo = top_y + my, -my
    corners = [
        [x_lo - taper, y_hi],  # top-left (widest)
        [x_hi + taper, y_hi],  # top-right
        [x_hi, y_lo],          # bottom-right
        [x_lo, y_lo],          # bottom-left
    ]
    shell = Polyline(
        points=_round_corners(corners, radius=0.9),
        closed=True, stroke="#8a8a8a", width=2.0, fill="#fbfbfb",
    )
    caption = Text(
        x=_X_MAX / 2, y=y_hi + 0.5, text=f"DSUB-50 · connector {connector} · front view",
        size=9, color="#8a8a8a", va="bottom",
    )
    background = [shell, caption]

    layout = InterfaceLayout(
        name=f"DSUB-50 (connector {connector})",
        units="mm", key_by="dsub_pin", background=background, slots=slots,
    )
    if not front_view:
        _mirror_x(layout)
    return layout


def _round_corners(
    verts: list[list[float]], radius: float, samples: int = 6
) -> list[list[float]]:
    """Round every corner of a closed polygon with a quadratic-Bézier fillet.

    At each vertex we step ``radius`` back along both adjacent edges (clamped to
    half the edge length) and sweep a Bézier through the vertex, so the result is
    a smooth outline made of plain points — no arc primitive needed.
    """

    def _step(a: list[float], b: list[float], d: float) -> list[float]:
        dx, dy = b[0] - a[0], b[1] - a[1]
        length = math.hypot(dx, dy) or 1.0
        d = min(d, length / 2)
        return [a[0] + dx / length * d, a[1] + dy / length * d]

    out: list[list[float]] = []
    n = len(verts)
    for i in range(n):
        prev, cur, nxt = verts[i - 1], verts[i], verts[(i + 1) % n]
        p_in = _step(cur, prev, radius)
        p_out = _step(cur, nxt, radius)
        for k in range(samples + 1):
            t = k / samples
            u = 1 - t
            out.append([
                u * u * p_in[0] + 2 * u * t * cur[0] + t * t * p_out[0],
                u * u * p_in[1] + 2 * u * t * cur[1] + t * t * p_out[1],
            ])
    return out


def _mirror_x(layout: InterfaceLayout) -> None:
    """Mirror horizontally in place (front view <-> solder side)."""
    for s in layout.slots:
        s.x = _X_MAX - s.x
    for prim in layout.background:
        if isinstance(prim, Polyline):
            prim.points = [[_X_MAX - x, y] for x, y in prim.points]
        elif isinstance(prim, Text):
            prim.x = _X_MAX - prim.x


def default_json_path() -> Path:
    return Path(__file__).with_name("layouts") / "dsub50.json"


def _dump() -> None:
    out = default_json_path()
    out.parent.mkdir(exist_ok=True)
    generate_dsub50().save_json(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    _dump()
