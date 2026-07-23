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
from trap_tester.core.layout.decoration import DECORATION_INFO, decoration_style
from trap_tester.core.layout.dsub50 import default_json_path, generate_dsub50
from trap_tester.core.layout.fpc import default_json_path as fpc_json_path
from trap_tester.core.layout.fpc import generate_fpc
from trap_tester.core.layout.geometry import in_rot_rect, point_in_poly
from trap_tester.core.layout.interface import (
    Drawing,
    InterfaceLayout,
    PinMark,
    Slot,
    SlotShape,
    build_drawing,
    slot_pins,
)
from trap_tester.core.layout.iontrap import build_iontrap, generate_iontrap
from trap_tester.core.layout.primitives import (
    Circle,
    Line,
    Polyline,
    Rect,
    Text,
    primitive_from_dict,
)
from trap_tester.core.layout.store import (
    add_layout_dir,
    configured_layout_dirs,
    delete_layout,
    env_layout_dirs,
    extra_layout_dirs,
    import_layout,
    layout_search_dirs,
    list_user_layouts,
    load_layout,
    remove_layout_dir,
    user_layouts_dir,
)

_CACHE: dict[str, InterfaceLayout] = {}


def dsub50_layout() -> InterfaceLayout:
    """The DSUB-50 template, loaded from JSON if it exists else generated.

    This is the geometric source of truth (connector 0). Other connectors reuse
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


def layout_for(measurement: str | None, connector: int = 0) -> InterfaceLayout | None:
    factory = _LAYOUTS.get(measurement or "")
    return factory(connector) if factory else None


def user_layout_options() -> list[tuple[str, str]]:
    """Custom layouts as ``(display_name, path)`` pairs for a GUI selector.

    When the same file name appears in more than one search folder (e.g. the
    writable store and a private-repo folder), the display name is qualified with
    the containing folder so the two entries can be told apart.
    """
    paths = list_user_layouts()
    stems = [p.stem for p in paths]
    dupes = {s for s in stems if stems.count(s) > 1}
    return [
        (f"{p.stem}  ({p.parent.name})" if p.stem in dupes else p.stem, str(p))
        for p in paths
    ]


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
    "ANNOTATION_STATES",
    "DECORATION_INFO",
    "Annotation",
    "AnnotationSet",
    "Circle",
    "Drawing",
    "InterfaceLayout",
    "Line",
    "PinMark",
    "Polyline",
    "Rect",
    "Slot",
    "SlotShape",
    "Text",
    "add_layout_dir",
    "build_annotation_drawing",
    "build_drawing",
    "build_iontrap",
    "configured_layout_dirs",
    "cycle_state",
    "decoration_style",
    "delete_layout",
    "dsub50_layout",
    "dsub50_layout_for_connector",
    "env_layout_dirs",
    "extra_layout_dirs",
    "filter_layout_connector",
    "fpc_layout",
    "fpc_layout_for_connector",
    "generate_dsub50",
    "generate_fpc",
    "generate_iontrap",
    "has_layout",
    "import_layout",
    "in_rot_rect",
    "layout_for",
    "layout_search_dirs",
    "list_user_layouts",
    "load_layout",
    "point_in_poly",
    "primitive_from_dict",
    "remove_layout_dir",
    "slot_pins",
    "user_layout_options",
    "user_layouts_dir",
]
