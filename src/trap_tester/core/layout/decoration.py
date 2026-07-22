"""Fixed-colour "decoration" pad classes shared by generators and viewers.

Some pads on an interface are not driven by measurement data — GND, RF lines,
loopback, sensor/heater on the interposer — but are drawn (in their datasheet
colours) so the picture reads like the physical part. A layout generator paints
them as background circles using :func:`decoration_style`; a viewer builds the
matching legend from :data:`DECORATION_INFO` by spotting those fill colours in the
drawing's background. Keeping the palette here means both sides never drift.
"""

from __future__ import annotations

# pad type -> (legend label, fill colour, stroke colour)
DECORATION_INFO: dict[str, tuple[str, str, str]] = {
    "gnd": ("GND", "#3b6fb0", "#2c5486"),
    "rf_lines": ("RF lines", "#2e9e4f", "#237a3c"),
    "loopback": ("Loopback", "#1fb6c9", "#178795"),
    "sensor_heater": ("Sensor / Heater", "#2a8f8f", "#1f6b6b"),
}
_FALLBACK = ("#dddddd", "#999999")


def decoration_style(pad_type: str) -> tuple[str, str]:
    """``(fill, stroke)`` for a decoration pad type (grey fallback if unknown)."""
    info = DECORATION_INFO.get(pad_type)
    return (info[1], info[2]) if info else _FALLBACK


__all__ = ["DECORATION_INFO", "decoration_style"]
