"""Draw-tool-agnostic geometric primitives.

These dataclasses are the lowest common denominator of any Python drawing
backend (matplotlib patches, a QGraphicsScene, an SVG writer, …): a shape with a
position, a size, an optional rotation and a plain style. The layout engine
emits a list of these; a renderer walks the list and paints each one. Nothing
here imports Qt or matplotlib.

Every primitive round-trips through ``to_dict`` / :func:`primitive_from_dict` so a
whole interface layout is just JSON with coordinates. **Colours are not part of
that JSON**: a primitive declares a ``style`` name and the concrete
``fill`` / ``stroke`` / ``width`` / ``color`` / ``size`` are resolved from
:mod:`trap_tester.core.layout.style` on load. The resolved attributes stay plain
fields, so renderers keep reading ``prim.fill`` and never learn about styles.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, ClassVar

from trap_tester.core.layout.style import DEFAULT_CHROME_STYLE, chrome_attrs

# ``kind`` string -> primitive class, filled in at the bottom of the module.
_REGISTRY: dict[str, type] = {}

# Attributes resolved from ``style`` rather than stored: kept off the JSON so a
# layout file carries no colours at all.
_STYLED_FIELDS = ("fill", "stroke", "width", "color", "size")


def _register(cls: type) -> type:
    _REGISTRY[cls.kind] = cls
    return cls


@dataclass
class _Primitive:
    """Base for all primitives. ``kind`` is the JSON type discriminator."""

    kind: ClassVar[str] = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)  # ClassVar ``kind`` is excluded by asdict
        for name in _STYLED_FIELDS:
            data.pop(name, None)
        data["kind"] = self.kind
        return data

    def __post_init__(self) -> None:
        # Colours are never per-primitive: whatever was passed is replaced by what
        # the declared style resolves to.
        self.apply_style()

    def apply_style(self) -> None:
        """Resolve this primitive's ``style`` name onto its colour fields."""
        for name, value in chrome_attrs(self.style).items():
            if hasattr(self, name):
                setattr(self, name, value)


@_register
@dataclass
class Circle(_Primitive):
    kind: ClassVar[str] = "circle"
    x: float = 0.0
    y: float = 0.0
    r: float = 1.0
    rotation: float = 0.0  # kept for uniformity; irrelevant for a circle
    style: str = DEFAULT_CHROME_STYLE
    fill: str | None = None
    stroke: str | None = "#444"
    width: float = 1.0


@_register
@dataclass
class Rect(_Primitive):
    kind: ClassVar[str] = "rect"
    x: float = 0.0  # centre x
    y: float = 0.0  # centre y
    w: float = 1.0
    h: float = 1.0
    rotation: float = 0.0  # degrees, about the centre
    style: str = DEFAULT_CHROME_STYLE
    fill: str | None = None
    stroke: str | None = "#444"
    width: float = 1.0


@_register
@dataclass
class Line(_Primitive):
    kind: ClassVar[str] = "line"
    x1: float = 0.0
    y1: float = 0.0
    x2: float = 0.0
    y2: float = 0.0
    style: str = DEFAULT_CHROME_STYLE
    stroke: str | None = "#444"
    width: float = 1.0


@_register
@dataclass
class Polyline(_Primitive):
    kind: ClassVar[str] = "polyline"
    points: list[list[float]] = field(default_factory=list)  # [[x, y], …]
    closed: bool = False
    style: str = DEFAULT_CHROME_STYLE
    fill: str | None = None
    stroke: str | None = "#444"
    width: float = 1.0


@_register
@dataclass
class Text(_Primitive):
    kind: ClassVar[str] = "text"
    x: float = 0.0
    y: float = 0.0
    text: str = ""
    ha: str = "center"  # horizontal anchor: left | center | right
    va: str = "center"  # vertical anchor: top | center | bottom | baseline
    rotation: float = 0.0
    style: str = "caption"
    size: float = 8.0
    color: str = "#222"


def primitive_from_dict(data: dict[str, Any]) -> _Primitive:
    """Rebuild a primitive from its ``to_dict`` form, resolving its style."""
    payload = dict(data)
    kind = payload.pop("kind")
    try:
        cls = _REGISTRY[kind]
    except KeyError as exc:
        raise ValueError(f"Unknown primitive kind {kind!r}") from exc
    return cls(**payload)



__all__ = [
    "Circle",
    "Line",
    "Polyline",
    "Rect",
    "Text",
    "primitive_from_dict",
]
