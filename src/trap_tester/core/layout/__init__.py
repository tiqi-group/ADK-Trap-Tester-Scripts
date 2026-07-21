"""GUI-agnostic interface-layout engine (no Qt).

Turns an :class:`~trap_tester.core.analysis.AnalysisResult` into a
:class:`Drawing` — a flat list of geometric primitives + coloured pins — laid
out on a chosen physical interface (today: the DSUB-50 connector). A renderer in
the GUI paints the drawing; the layout maths and colours live here so they are
testable and reusable (e.g. a headless PNG for a report).

``layout_for(measurement)`` picks the interface for a measurement. Every
measurement currently maps to the DSUB-50 connector, loaded from
``layouts/dsub50.json`` when present (the editable source of truth) or generated
on the fly otherwise.
"""

from __future__ import annotations

from trap_tester.core.layout.annotation import (
    ANNOTATION_STATES,
    Annotation,
    AnnotationSet,
    build_annotation_drawing,
    cycle_state,
)
from trap_tester.core.layout.dsub50 import default_json_path, generate_dsub50
from trap_tester.core.layout.fpc import default_json_path as fpc_json_path
from trap_tester.core.layout.fpc import generate_fpc
from trap_tester.core.layout.interface import (
    Drawing,
    InterfaceLayout,
    PinMark,
    Slot,
    build_drawing,
)
from trap_tester.core.layout.primitives import (
    Circle,
    Line,
    Polyline,
    Rect,
    Text,
    primitive_from_dict,
)
from trap_tester.core.layout.store import (
    delete_layout,
    import_layout,
    list_user_layouts,
    load_layout,
    user_layouts_dir,
)

_CACHE: dict[str, InterfaceLayout] = {}


def dsub50_layout() -> InterfaceLayout:
    """The DSUB-50 template, loaded from JSON if it exists else generated.

    This is the geometric source of truth (connector 1). Other connectors reuse
    this geometry via :func:`dsub50_layout_for_connector`.
    """
    if "dsub50" not in _CACHE:
        path = default_json_path()
        _CACHE["dsub50"] = (
            InterfaceLayout.load_json(path) if path.exists() else generate_dsub50()
        )
    return _CACHE["dsub50"]


def dsub50_layout_for_connector(connector: int) -> InterfaceLayout:
    """A single-connector DSUB-50 layout for ``connector``.

    Uses the JSON template's slots when it already defines that connector;
    otherwise generates an identical tile stamped with the requested connector
    number — so a matrix measurement across many feedthroughs can be viewed one
    connector at a time without hand-authoring every connector in JSON.
    """
    base = dsub50_layout()
    present = {s.connector for s in base.slots}
    if present == {connector}:
        return base
    if connector in present:
        slots = [s for s in base.slots if s.connector == connector]
        return InterfaceLayout(
            name=f"DSUB-50 (connector {connector})", units=base.units,
            key_by=base.key_by, background=base.background, slots=slots,
        )
    return generate_dsub50(connector=connector)


def fpc_layout() -> InterfaceLayout:
    """The FPC-ribbon template, loaded from JSON if it exists else generated."""
    if "fpc" not in _CACHE:
        path = fpc_json_path()
        _CACHE["fpc"] = (
            InterfaceLayout.load_json(path) if path.exists() else generate_fpc()
        )
    return _CACHE["fpc"]


def fpc_layout_for_connector(connector: int) -> InterfaceLayout:
    """A single-connector FPC-ribbon layout for ``connector`` (see DSUB-50)."""
    base = fpc_layout()
    present = {s.connector for s in base.slots}
    if present == {connector}:
        return base
    if connector in present:
        return InterfaceLayout(
            name=f"FPC ribbon (connector {connector})", units=base.units,
            key_by=base.key_by, background=base.background,
            slots=[s for s in base.slots if s.connector == connector],
        )
    return generate_fpc(connector=connector)


# measurement key (== script stem) -> layout factory (connector -> layout). All
# connector-facing measurements currently share the DSUB-50 interface.
_LAYOUTS = {
    "measure_filter": dsub50_layout_for_connector,
    "measure_resistance": dsub50_layout_for_connector,
    "measure_voltage": dsub50_layout_for_connector,
}


def has_layout(measurement: str | None) -> bool:
    return (measurement or "") in _LAYOUTS


def layout_for(measurement: str | None, connector: int = 1) -> InterfaceLayout | None:
    factory = _LAYOUTS.get(measurement or "")
    return factory(connector) if factory else None


def user_layout_options() -> list[tuple[str, str]]:
    """Custom layouts as ``(display_name, path)`` pairs for a GUI selector."""
    return [(p.stem, str(p)) for p in list_user_layouts()]


def filter_layout_connector(
    layout: InterfaceLayout, connector: int
) -> InterfaceLayout:
    """Restrict a (possibly multi-connector) layout to one connector.

    Returned unchanged when it defines a single connector — or none matching
    ``connector`` — so a custom layout that ignores the connector concept is
    always drawn in full rather than blanked out.
    """
    present = {s.connector for s in layout.slots}
    if len(present) <= 1 or connector not in present:
        return layout
    return InterfaceLayout(
        name=f"{layout.name} (connector {connector})",
        units=layout.units, key_by=layout.key_by, background=layout.background,
        slots=[s for s in layout.slots if s.connector == connector],
    )


__all__ = [
    "Circle",
    "Rect",
    "Line",
    "Polyline",
    "Text",
    "primitive_from_dict",
    "Slot",
    "InterfaceLayout",
    "PinMark",
    "Drawing",
    "build_drawing",
    "generate_dsub50",
    "generate_fpc",
    "dsub50_layout",
    "dsub50_layout_for_connector",
    "fpc_layout",
    "fpc_layout_for_connector",
    "layout_for",
    "has_layout",
    "user_layout_options",
    "filter_layout_connector",
    "user_layouts_dir",
    "list_user_layouts",
    "load_layout",
    "import_layout",
    "delete_layout",
    "ANNOTATION_STATES",
    "Annotation",
    "AnnotationSet",
    "build_annotation_drawing",
    "cycle_state",
]
