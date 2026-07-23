"""Qt-free hit-testing geometry for interface layouts.

The renderer paints pins as circles, rectangles, rotated "finger" pads and
arbitrary electrode polygons; picking which one a click landed on is pure
coordinate maths. Keeping it here (rather than in the Qt canvas) means the
hit-test can be unit-tested headlessly and reused by any renderer.
"""

from __future__ import annotations

import math


def point_in_poly(x: float, y: float, pts: list[list[float]]) -> bool:
    """Ray-cast point-in-polygon test for an arbitrary (electrode) outline."""
    inside = False
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[i - 1]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def in_rot_rect(
    x: float, y: float, cx: float, cy: float, hw: float, hh: float, rot_deg: float
) -> bool:
    """Whether ``(x, y)`` is inside a rect of half-size ``(hw, hh)`` centred at
    ``(cx, cy)`` and rotated ``rot_deg`` degrees about its centre."""
    theta = math.radians(rot_deg)
    dx, dy = x - cx, y - cy
    # rotate the point into the rect's own frame (by -rot), then test the box
    lx = dx * math.cos(theta) + dy * math.sin(theta)
    ly = -dx * math.sin(theta) + dy * math.cos(theta)
    return abs(lx) <= hw and abs(ly) <= hh


__all__ = ["point_in_poly", "in_rot_rect"]
