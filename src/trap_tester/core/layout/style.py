"""The single style table: class/style name -> colours.

Layout JSON carries **no colours**. A pad declares what it *is*
(:data:`PAD_CLASSES` via ``Slot.pad_class``) and a background primitive declares
what it *is for* (:data:`CHROME_STYLES` via its ``style``); the colours are
resolved here, in one place, at load and draw time.

This replaces the v1 arrangement where generators wrote hex into the JSON and the
renderer recovered a pad's meaning by *matching its fill colour* against a table —
which silently failed for any shape that was not a circle, so ion-trap RF rails
(polygons) could never appear in a legend. Declaring the class fixes that for
every shape, and keeps a single palette that light/dark theming can re-resolve.

Replaces the old ``decoration.py``; ``rf_lines`` is now spelled ``rf``.
"""

from __future__ import annotations

# Pad class -> (legend label, fill, stroke). Only "signal" pads are measurable and
# clickable; their colour comes from the measurement status or annotation state, so
# they have no fixed fill here and never appear as a class legend entry.
PAD_CLASSES: dict[str, tuple[str | None, str | None, str | None]] = {
    "signal": (None, None, None),
    "gnd": ("GND", "#3b6fb0", "#2c5486"),
    "rf": ("RF lines", "#2e9e4f", "#237a3c"),
    "loopback": ("Loopback", "#1fb6c9", "#178795"),
    "sensor_heater": ("Sensor / Heater", "#2a8f8f", "#1f6b6b"),
    # present in the interposer flavour CSV; v1 had no entry for it, so it fell
    # through to the grey fallback and never appeared in a legend.
    "axialisation": ("Axialisation", "#8e6fb0", "#6b5286"),
}
SIGNAL_CLASS = "signal"
_PAD_FALLBACK = ("#dddddd", "#999999")

# Background (chrome) style -> the primitive attributes it resolves to. Chrome is
# never data-driven: it is the connector shell, the ribbon body, row/column labels.
CHROME_STYLES: dict[str, dict[str, object]] = {
    "outline": {"stroke": "#8a8a8a", "width": 2.0, "fill": "#fbfbfb"},
    "hairline": {"stroke": "#8a8a8a", "width": 0.6, "fill": None},
    "caption": {"color": "#8a8a8a", "size": 9.0},
    "grid_label": {"color": "#8a8a8a", "size": 7.0},
}
DEFAULT_CHROME_STYLE = "outline"


def pad_style(pad_class: str) -> tuple[str | None, str | None]:
    """``(fill, stroke)`` for a non-signal pad class (grey fallback if unknown)."""
    info = PAD_CLASSES.get(pad_class)
    if info is None:
        return _PAD_FALLBACK
    return (info[1], info[2])


def pad_legend(pad_classes: set[str]) -> list[tuple[str, str, str]]:
    """``(label, fill, stroke)`` legend rows for the non-signal classes present.

    Driven by what the drawing actually declares, in :data:`PAD_CLASSES` order, so
    the legend is stable and works for circles, rectangles and polygons alike.
    """
    rows: list[tuple[str, str, str]] = []
    for name, (label, fill, stroke) in PAD_CLASSES.items():
        if label is None or fill is None or stroke is None:
            continue  # the signal class carries no fixed colour
        if name in pad_classes:
            rows.append((label, fill, stroke))
    return rows


def chrome_attrs(style: str) -> dict[str, object]:
    """Resolved primitive attributes for a chrome ``style`` name."""
    return dict(CHROME_STYLES.get(style, CHROME_STYLES[DEFAULT_CHROME_STYLE]))



__all__ = [
    "CHROME_STYLES",
    "DEFAULT_CHROME_STYLE",
    "PAD_CLASSES",
    "SIGNAL_CLASS",
    "chrome_attrs",
    "pad_legend",
    "pad_style",
]
