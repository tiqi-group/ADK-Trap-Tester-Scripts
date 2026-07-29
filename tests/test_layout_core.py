"""Headless tests for the interface-layout engine (``core.layout``).

Run with ``uv run pytest tests/test_layout_core.py``. No hardware and no Qt —
these check the DSUB-50 geometry, JSON round-trip, the findings->colour mapping
and the alternate ``pin_space`` (drawing the same findings on another interface).
"""

from __future__ import annotations

import json
import pathlib

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis._common import fpc_conductor
from trap_tester.core.layout import (
    AnnotationSet,
    add_layout_dir,
    build_annotation_drawing,
    build_drawing,
    configured_layout_dirs,
    dsub50_layout,
    dsub50_layout_for_connector,
    filter_layout_connector,
    fpc_layout,
    fpc_layout_for_connector,
    generate_dsub50,
    generate_fpc,
    import_layout,
    import_mapping,
    in_rot_rect,
    layout_for,
    layout_search_dirs,
    list_mapping_files,
    list_user_layouts,
    load_layout,
    mapping_options,
    point_in_poly,
    remove_layout_dir,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.core.layout.addressing import canonical_address, is_synthetic
from trap_tester.core.layout.interface import InterfaceLayout, Slot, SlotShape
from trap_tester.core.layout.iontrap import build_iontrap, generate_iontrap
from trap_tester.core.layout.primitives import Circle, Polyline, primitive_from_dict
from trap_tester.core.layout.tiling import TESTER_CONNECTORS, tile_connector_layouts


def _four_outcome_df() -> pd.DataFrame:
    # ok, shorted, not-detected (open), over-nominal (high C)
    return pd.DataFrame(
        [
            {"DSUB connector": 0, "DSUB pin": 1, "Shorted": False,
             "C_filter_nF": 1.0, "R_filter_Ohm": 2000},
            {"DSUB connector": 0, "DSUB pin": 2, "Shorted": True,
             "C_filter_nF": -1, "R_filter_Ohm": 50},
            {"DSUB connector": 0, "DSUB pin": 3, "Shorted": False,
             "C_filter_nF": 0.01, "R_filter_Ohm": 2000},
            {"DSUB connector": 0, "DSUB pin": 4, "Shorted": False,
             "C_filter_nF": 2.1, "R_filter_Ohm": 1000},
        ]
    )


def test_dsub50_has_fifty_slots():
    lay = generate_dsub50()
    assert len(lay.slots) == 50
    pins = sorted(s.pin for s in lay.slots)
    assert pins == list(range(1, 51))
    assert {s.connector for s in lay.slots} == {0}
    assert lay.pin_space == "dsub_pin"


def test_dsub50_row_geometry():
    # front view, pin 1 top-left; rows A/B/C at descending y, ascending x.
    by_pin = {s.pin: s for s in generate_dsub50().slots}
    assert (by_pin[1].x, by_pin[1].y) == (0.0, 2.0)     # row A start
    assert (by_pin[17].x, by_pin[17].y) == (16.0, 2.0)  # row A end
    assert by_pin[18].y == 1.0 and by_pin[18].x == 0.5  # row B staggered
    assert by_pin[34].y == 0.0 and by_pin[34].x == 0.0  # row C start
    assert by_pin[50].x == 16.0 and by_pin[50].y == 0.0


def test_front_view_flip_mirrors_x():
    front = {s.pin: s.x for s in generate_dsub50(front_view=True).slots}
    solder = {s.pin: s.x for s in generate_dsub50(front_view=False).slots}
    assert solder[1] == 16.0 and front[1] == 0.0
    assert all(abs((16.0 - front[p]) - solder[p]) < 1e-9 for p in front)


def test_layout_json_round_trip():
    lay = generate_dsub50()
    rebuilt = InterfaceLayout.from_dict(lay.to_dict())
    assert [s.to_dict() for s in lay.slots] == [s.to_dict() for s in rebuilt.slots]
    assert len(rebuilt.background) == len(lay.background)
    assert isinstance(rebuilt.background[0], Polyline)


def test_primitive_round_trip():
    c = Circle(x=1.0, y=2.0, r=0.5, fill="#abcdef")
    assert primitive_from_dict(c.to_dict()) == c


def test_build_drawing_colours_match_status():
    res = A.analyse("measure_filter", _four_outcome_df(), A.FilterAnalysisSettings())
    drawing = build_drawing(res, layout_for("measure_filter"))
    assert len(drawing.pins) == 50  # every slot drawn
    measured = {p.pin: p for p in drawing.pins if p.measured}
    assert set(measured) == {1, 2, 3, 4}
    assert measured[1].status == "ok"
    assert measured[2].status == "shorted"
    assert measured[3].status == "not_detected"
    assert measured[4].status == "over_nominal"
    for p in measured.values():
        assert p.fill == A.STATUS_INFO[p.status][1]
    # untested pins are drawn faint
    assert any(not p.measured for p in drawing.pins)


def test_build_drawing_alternate_pin_space_fpc():
    # A different interface: one slot keyed by FPC conductor, not DSUB pin.
    res = A.analyse("measure_filter", _four_outcome_df(), A.FilterAnalysisSettings())
    fpc_of_pin1 = next(f.fpc_conductor for f in res.findings if f.dsub_pin == 1)
    lay = InterfaceLayout(
        name="fpc-test", pin_space="fpc_conductor",
        slots=[Slot(connector=0, pin=fpc_of_pin1, x=0.0, y=0.0)],
    )
    drawing = build_drawing(res, lay)
    assert len(drawing.pins) == 1
    assert drawing.pins[0].measured and drawing.pins[0].status == "ok"


def _point_in_polygon(x: float, y: float, poly: list[list[float]]) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[i - 1]
        if (y1 > y) != (y2 > y):
            xin = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xin:
                inside = not inside
    return inside


def test_all_pins_lie_inside_the_shell():
    lay = generate_dsub50()
    shell = next(p for p in lay.background if isinstance(p, Polyline))
    poly = shell.points
    for s in lay.slots:
        # the four cardinal edge points of each pin circle must be inside
        for dx, dy in ((s.r, 0), (-s.r, 0), (0, s.r), (0, -s.r)):
            assert _point_in_polygon(s.x + dx, s.y + dy, poly), (
                f"pin {s.pin} spills outside the D-shell"
            )


def test_layout_for_all_measurements_is_dsub50():
    for m in ("measure_filter", "measure_resistance", "measure_voltage"):
        assert layout_for(m) is dsub50_layout()  # connector 0 default is the template
    assert layout_for("nonexistent") is None


def test_layout_for_generates_missing_connector():
    # connector 0 is the JSON template; connector 2 is generated on demand
    assert dsub50_layout_for_connector(0) is dsub50_layout()
    lay2 = layout_for("measure_filter", connector=2)
    assert lay2 is not None
    assert len(lay2.slots) == 50
    assert {s.connector for s in lay2.slots} == {2}


def test_multi_connector_findings_placed_per_connector():
    # a matrix result over two connectors: nothing is dropped, each connector
    # draws its own findings.
    df = pd.DataFrame(
        [
            {"DSUB connector": 1, "DSUB pin": 1, "Shorted": False,
             "C_filter_nF": 1.0, "R_filter_Ohm": 2000},
            {"DSUB connector": 2, "DSUB pin": 1, "Shorted": True,
             "C_filter_nF": -1, "R_filter_Ohm": 50},
            {"DSUB connector": 2, "DSUB pin": 2, "Shorted": False,
             "C_filter_nF": 1.0, "R_filter_Ohm": 2000},
        ]
    )
    res = A.analyse("measure_filter", df, A.FilterAnalysisSettings())

    d1 = build_drawing(res, layout_for("measure_filter", 1))
    d2 = build_drawing(res, layout_for("measure_filter", 2))
    assert {p.pin for p in d1.pins if p.measured} == {1}
    assert {p.pin for p in d2.pins if p.measured} == {1, 2}
    m2 = {p.pin: p.status for p in d2.pins if p.measured}
    assert m2 == {1: "shorted", 2: "ok"}


# --- FPC ribbon + the canonical address as translation layer ----------------


def test_a_v1_layout_is_rejected():
    """Only schema 2 loads.

    The project has had no release, so there is nothing to stay compatible with, and
    a loader that speaks exactly one format is the point of the exercise. A v1 file
    fails with a message pointing at the generator rather than being silently
    reinterpreted.
    """
    v1 = {
        "name": "old", "units": "mm", "key_by": "dsub_pin", "background": [],
        "slots": [{"connector": 0, "pin": 1, "x": 0.0, "y": 0.0, "channel": 46}],
    }
    with pytest.raises(ValueError, match="Unsupported layout schema"):
        InterfaceLayout.from_dict(v1)


def test_slot_round_trips_without_a_channel():
    """v2 stores no channel; identity is (connector, pin) plus the optional ident."""
    s = Slot(connector=1, pin=5, x=0.0, y=0.0, ident="B25")
    back = Slot.from_dict(s.to_dict())
    assert (back.connector, back.pin, back.ident) == (1, 5, "B25")
    assert "channel" not in s.to_dict()
    assert Slot.from_dict(Slot(connector=1, pin=1, x=0, y=0).to_dict()).ident is None


def test_canonical_address_of_a_dsub_pin_is_itself():
    lay = generate_dsub50()
    assert all(
        canonical_address(s.connector, s.pin, lay.pin_space) == (s.connector, s.pin)
        for s in lay.slots
    )


def test_fpc_layout_is_conductor_keyed_with_gnd_shields():
    lay = fpc_layout()
    assert lay.pin_space == "fpc_conductor"
    # 51 physical conductors; 1 and 51 are the GND shields, declared as such.
    assert {s.pin for s in lay.slots} == set(range(1, 52))
    by_cond = {s.pin: s for s in lay.slots}
    assert by_cond[1].pad_class == "gnd" and by_cond[51].pad_class == "gnd"
    assert sum(s.is_signal for s in lay.slots) == 49
    assert all(sh.shape == "rect" for s in lay.slots for sh in s.shapes)
    assert {s.connector for s in lay.slots} == {0}


def test_canonical_address_bridges_dsub_and_fpc():
    """A DSUB pin and the conductor carrying its signal reduce to one address.

    v1 achieved this by stamping a matching ``channel`` into both JSON files; v2
    derives it, so the two layouts cannot drift out of agreement.
    """
    for s in dsub50_layout().slots:
        conductor = fpc_conductor(s.pin)  # via mux_mapping
        if conductor is None:  # DSUB pin 9 is GND: no conductor
            continue
        assert canonical_address(0, conductor, "fpc_conductor") == (0, s.pin)
    # the corrected wiring: DSUB pin 42 <-> conductor 26
    assert canonical_address(0, 26, "fpc_conductor") == (0, 42)
    assert fpc_conductor(9) is None
    # the shield conductors have no canonical address at all
    assert canonical_address(0, 1, "fpc_conductor") is None
    assert canonical_address(0, 51, "fpc_conductor") is None


def test_fpc_layout_for_connector_generates_and_stamps():
    lay2 = fpc_layout_for_connector(2)
    assert {s.connector for s in lay2.slots} == {2}
    assert len(lay2.slots) == 51
    # the conductor numbering is connector-independent
    assert {s.pin for s in lay2.slots} == {s.pin for s in fpc_layout().slots}


# --- custom layout store --------------------------------------------------


@pytest.fixture()
def layout_store(tmp_path, monkeypatch):
    """Point the user layout store at an isolated temp dir for the test.

    Returns ``(store_dir, src_dir)`` — sources are kept *outside* the store so
    they don't show up in ``list_user_layouts()``.
    """
    store = tmp_path / "store"
    src = tmp_path / "src"
    src.mkdir()
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(store))
    return store, src


def test_user_layouts_dir_honours_env_override(layout_store):
    store, _ = layout_store
    assert user_layouts_dir() == store
    assert list_user_layouts() == []  # dir starts empty


def test_import_validates_copies_and_round_trips(layout_store):
    store, src_dir = layout_store
    src = src_dir / "mine.json"
    generate_dsub50().save_json(src)

    dest = import_layout(src)
    assert dest.parent == store
    assert dest.exists()
    assert [p.name for p in list_user_layouts()] == ["mine.json"]
    assert ("mine", str(dest)) in user_layout_options()

    loaded = load_layout(dest)
    assert len(loaded.slots) == 50 and loaded.pin_space == "dsub_pin"


def test_import_rejects_invalid_file_and_stores_nothing(layout_store):
    _, src_dir = layout_store
    bad = src_dir / "bad.json"
    bad.write_text("{ this is not valid json")
    with pytest.raises(ValueError):
        import_layout(bad)
    assert list_user_layouts() == []  # nothing was written on failure


def test_import_mapping_validates_copies_and_lists(layout_store):
    store, src_dir = layout_store
    src = src_dir / "wiring.csv"
    src.write_text("connector,pin,interposer\n4,31,B25\n")

    dest = import_mapping(src)
    assert dest.parent == store
    assert dest.suffix == ".csv"
    assert [p.name for p in list_mapping_files()] == ["wiring.csv"]
    assert ("wiring", str(dest)) in mapping_options()


def test_import_mapping_rejects_file_without_required_columns(layout_store):
    _, src_dir = layout_store
    bad = src_dir / "bad.csv"
    bad.write_text("Interposer,SomethingElse\nB25,x\n")  # no connector/pin columns
    with pytest.raises(ValueError):
        import_mapping(bad)
    assert list_mapping_files() == []  # nothing written on failure


def test_import_does_not_clobber_existing_name(layout_store):
    _, src_dir = layout_store
    src = src_dir / "dupe.json"
    generate_dsub50().save_json(src)
    first = import_layout(src)
    second = import_layout(src)
    assert first.name == "dupe.json"
    assert second.name == "dupe-2.json"
    assert len(list_user_layouts()) == 2


def test_filter_layout_connector():
    slots = [Slot(connector=1, pin=1, x=0, y=0), Slot(connector=2, pin=1, x=1, y=0)]
    lay = InterfaceLayout(name="multi", slots=slots)
    only2 = filter_layout_connector(lay, 2)
    assert {s.connector for s in only2.slots} == {2}
    # single-connector or missing-connector layouts pass through unchanged
    assert filter_layout_connector(only2, 2) is only2
    assert filter_layout_connector(lay, 9) is lay


# --- extra layout search folders ------------------------------------------


def test_add_and_remove_extra_layout_dir(layout_store, tmp_path):
    """A persisted extra folder is searched, and its layouts appear in the list."""
    extra = tmp_path / "private-repo"
    extra.mkdir()
    generate_fpc().save_json(extra / "shared.json")

    # not searched until it is added
    assert list_user_layouts() == []
    add_layout_dir(extra)

    assert extra in layout_search_dirs()
    assert [p.name for p in list_user_layouts()] == ["shared.json"]
    assert ("shared", str(extra / "shared.json")) in user_layout_options()

    # persists across calls (config file), and is removable again
    assert configured_layout_dirs() == [extra]
    remove_layout_dir(extra)
    assert configured_layout_dirs() == []
    assert list_user_layouts() == []


def test_add_layout_dir_rejects_non_directory(layout_store, tmp_path):
    with pytest.raises(ValueError):
        add_layout_dir(tmp_path / "does-not-exist")
    assert configured_layout_dirs() == []


def test_add_layout_dir_is_idempotent_and_skips_store(layout_store, tmp_path):
    store, _ = layout_store
    store.mkdir(parents=True, exist_ok=True)
    extra = tmp_path / "extra"
    extra.mkdir()
    add_layout_dir(extra)
    add_layout_dir(extra)  # duplicate -> no-op
    add_layout_dir(store)  # the writable store is already searched -> not persisted
    assert configured_layout_dirs() == [extra]


def test_env_var_extra_dir_is_searched(layout_store, tmp_path, monkeypatch):
    extra = tmp_path / "from-env"
    extra.mkdir()
    generate_dsub50().save_json(extra / "envlayout.json")
    monkeypatch.setenv("TRAP_TESTER_LAYOUT_PATH", str(extra))
    assert extra in layout_search_dirs()
    assert [p.name for p in list_user_layouts()] == ["envlayout.json"]


# --- multi-shape slots (ion-trap electrodes / co-wired nets) ---------------


def test_slotshape_and_multi_shape_slot_round_trip():
    poly = [[0.0, 0.0], [1.0, 0.0], [1.0, 0.5], [0.0, 0.5]]
    s = Slot(
        connector=2, pin=7, x=0.5, y=0.25, ident="E7", label="",
        shapes=[SlotShape(shape="rect", x=0.5, y=0.25, r=0.3),
                SlotShape.from_polygon(poly)],
    )
    back = Slot.from_dict(s.to_dict())
    assert len(back.shapes) == 2
    assert back.shapes[0].shape == "rect"
    assert back.shapes[1].shape == "poly"
    assert back.shapes[1].points == poly
    assert back.ident == "E7" and back.label == ""


def test_slotshape_from_polygon_centre_and_extent():
    sh = SlotShape.from_polygon([[0.0, 0.0], [2.0, 0.0], [2.0, 1.0], [0.0, 1.0]])
    assert (sh.x, sh.y) == (1.0, 0.5)  # bounding-box centre
    assert sh.extent() == (0.0, 2.0, 0.0, 1.0)
    assert sh.r == 1.0  # half the larger span


def test_single_shape_slot_is_normalised_into_one_shape():
    """v2 has a single geometry representation: the flat args fold into ``shapes``."""
    s = Slot(connector=0, pin=1, x=0.0, y=0.0, r=0.4, shape="rect")
    shapes = list(s.iter_shapes())
    assert len(shapes) == 1 and shapes[0].shape == "rect" and shapes[0].r == 0.4
    assert len(s.to_dict()["shapes"]) == 1  # always written now


def test_multi_shape_slot_expands_to_one_pin_per_shape():
    res = A.analyse("measure_filter", _four_outcome_df(), A.FilterAnalysisSettings())
    lay = InterfaceLayout(
        name="trap-test",
        slots=[Slot(
            connector=0, pin=1, x=0.0, y=0.0, label="E1",
            shapes=[SlotShape.from_polygon([[0, 0], [1, 0], [1, 1], [0, 1]]),
                    SlotShape.from_polygon([[2, 0], [3, 0], [3, 1], [2, 1]]),
                    SlotShape.from_polygon([[4, 0], [5, 0], [5, 1], [4, 1]])],
        )],
    )
    drawing = build_drawing(res, lay)
    assert len(drawing.pins) == 3  # one PinMark per shape
    # every shape carries the one net's identity and the same verdict
    assert {p.status for p in drawing.pins} == {"ok"}
    assert {(p.connector, p.pin) for p in drawing.pins} == {(0, 1)}
    assert all(p.shape == "poly" and p.points for p in drawing.pins)
    # the label is drawn on every shape, so each co-wired member is annotated
    assert [p.label for p in drawing.pins] == ["E1", "E1", "E1"]
    # the drawing's bounds span all three polygons
    xmin, xmax, _, _ = drawing.bounds(margin=0.0)
    assert (xmin, xmax) == (0.0, 5.0)


def test_cowired_group_marks_all_shapes_together():
    # one net (one address) drawn as three shapes: marking the address colours
    # every shape, so clicking any co-wired pad marks the whole net.
    lay = InterfaceLayout(
        name="cowire-test",
        slots=[Slot(
            connector=0, pin=5, x=0.0, y=0.0, label="NET",
            shapes=[SlotShape(shape="rect", x=0.0, y=0.0),
                    SlotShape(shape="rect", x=1.0, y=0.0),
                    SlotShape(shape="rect", x=2.0, y=0.0)],
        )],
    )
    ann = AnnotationSet()

    # nothing marked -> all three shapes faint, none faulty
    drawing = build_annotation_drawing(lay, ann)
    assert len(drawing.pins) == 3
    assert all(p.status == "clear" for p in drawing.pins)

    # a single click on the net's address marks all three shapes at once
    ann.cycle(0, 5)  # None -> suspicious
    ann.cycle(0, 5)  # suspicious -> faulty
    drawing = build_annotation_drawing(lay, ann)
    assert [p.status for p in drawing.pins] == ["faulty", "faulty", "faulty"]


def test_point_in_poly_hit_test():
    # an L-shaped electrode: the notch must read as OUTSIDE
    ell = [[0, 0], [2, 0], [2, 1], [1, 1], [1, 2], [0, 2]]
    assert point_in_poly(0.5, 0.5, ell)   # solid corner
    assert point_in_poly(1.5, 0.5, ell)   # solid arm
    assert not point_in_poly(1.5, 1.5, ell)  # inside the bounding box but in the notch
    assert not point_in_poly(3.0, 0.5, ell)  # well outside


def test_in_rot_rect_hit_test():
    # unrotated unit square (half-size 0.5) centred at the origin
    assert in_rot_rect(0.4, 0.4, 0, 0, 0.5, 0.5, 0)
    assert not in_rot_rect(0.6, 0.0, 0, 0, 0.5, 0.5, 0)
    # rotate 45°: the axis-aligned corner (0.6, 0) now falls inside the diamond,
    # while a point out along the rotated diagonal falls outside
    assert in_rot_rect(0.6, 0.0, 0, 0, 0.5, 0.5, 45)
    assert not in_rot_rect(0.5, 0.5, 0, 0, 0.5, 0.5, 45)


# --- ion-trap importer -----------------------------------------------------


def _square(x0, y0, s=0.001):
    """A tiny square electrode polygon (in metres) at grid cell (x0, y0)."""
    return [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s]]


def _trap_geometry():
    # two DC electrodes + one co-wired group of two members + one RF rail
    return {
        "electrodes": [
            {"name": "DC_0", "type": "DC", "polygons": [_square(0.0, 0.0)]},
            {"name": "DC_1", "type": "DC", "polygons": [_square(0.002, 0.0)]},
            {"name": "CO_A", "type": "DC", "polygons": [_square(0.0, 0.002)]},
            {"name": "CO_B", "type": "DC", "polygons": [_square(0.002, 0.002)]},
            {"name": "RF_0", "type": "RF", "polygons": [_square(0.0, 0.004)]},
        ],
        "cowired_groups": {"GRP": ["CO_A", "CO_B"]},
    }


def test_iontrap_nets_shapes_and_rf_class():
    lay = build_iontrap(
        _trap_geometry(),
        mapping=[("DC_0", 0, 1), ("DC_1", 0, 2), ("GRP", 1, 5)],
        name="testtrap",
    )
    assert lay.units == "mm" and lay.pin_space == "dsub_pin"
    assert lay.match_by == "ident" and lay.slug == "testtrap"
    signal = [s for s in lay.slots if s.is_signal]
    # three nets: two single DC + one co-wired group
    assert len(signal) == 3
    by_pin = {(s.connector, s.pin): s for s in signal}
    assert len(by_pin[(0, 1)].shapes) == 1  # plain electrode -> one shape
    assert len(by_pin[(1, 5)].shapes) == 2  # co-wired group -> union of members
    assert all(sh.shape == "poly" for s in signal for sh in s.shapes)
    # metres -> mm: the 1 mm square spans 1.0 in drawing units
    xmin, xmax, _, _ = by_pin[(0, 1)].shapes[0].extent()
    assert xmax - xmin == pytest.approx(1.0)
    # the unmapped RF rail is a declared slot now, not an anonymous background
    # polygon: that is what puts it in the legend whatever its shape.
    rf = [s for s in lay.slots if s.pad_class == "rf"]
    assert len(rf) == 1 and rf[0].ident == "RF_0"
    assert is_synthetic(rf[0].connector)  # routes to no tester pin
    assert lay.background == []


def test_iontrap_cowired_group_marks_together():
    lay = build_iontrap(
        _trap_geometry(), mapping=[("GRP", 1, 5)], name="t"
    )
    grp = next(s for s in lay.slots if s.is_signal)
    ann = AnnotationSet()
    ann.cycle(grp.connector, grp.pin)  # one click on the net
    drawing = build_annotation_drawing(lay, ann)
    # both member polygons colour together off the single mark
    assert len([p for p in drawing.pins if p.pad_class == "signal"]) == 2
    assert {p.status for p in drawing.pins if p.pad_class == "signal"} == {"suspicious"}


def test_iontrap_reads_real_trap_files():
    # hawk1 + mapping_sparrow: a trap whose mapping CSV is still the plain
    # Electrode/Connector/DSUB_Pin format the importer reads. (mapping_buzzard.csv
    # is now the rich cross-interface *mapping* example, a separate artifact.)
    root = pathlib.Path(__file__).resolve().parents[1] / "docs_tmp" / "traps"
    if not (root / "hawk1.json").exists():
        pytest.skip("trap definition files not present")
    lay = generate_iontrap(root / "hawk1.json", root / "mapping_sparrow.csv")
    signal = [s for s in lay.slots if s.is_signal]
    assert len(signal) == 193  # all single DC electrodes (hawk1 has no groups)
    assert sum(len(s.shapes) for s in signal) == 193
    # the 8 RF rails the mapping never names are declared slots on synthetic
    # addresses (v1 buried them in ``background`` as anonymous polygons)
    unrouted = [s for s in lay.slots if not s.is_signal]
    assert len(unrouted) == 8
    assert all(is_synthetic(s.connector) for s in unrouted)
    assert lay.background == []
    # every pad carries its electrode name as the cross-interface ident
    assert all(s.ident for s in lay.slots)


def test_iontrap_stamps_electrode_ident():
    lay = build_iontrap(
        _trap_geometry(),
        mapping=[("DC_0", 0, 1), ("GRP", 1, 5)],
        name="t",
    )
    by_pin = {(s.connector, s.pin): s for s in lay.slots}
    assert by_pin[(0, 1)].ident == "DC_0"  # plain electrode
    assert by_pin[(1, 5)].ident == "GRP"  # the co-wired GROUP name, not a member


def test_slot_ident_round_trip():
    slot = Slot(connector=2, pin=7, x=1.0, y=2.0, ident="B25")
    back = Slot.from_dict(slot.to_dict())
    assert back.ident == "B25"
    # ident is omitted from the dict when None (back-compat with old JSON)
    assert "ident" not in Slot(connector=0, pin=1, x=0.0, y=0.0).to_dict()
    assert Slot.from_dict({"connector": 0, "pin": 1, "x": 0.0, "y": 0.0}).ident is None


def test_iontrap_tolerates_connector_column_spelling(tmp_path):
    # sparrow spells it "Connector_Num"; goshawk "Connector number"
    for header in ("Connector_Num", "Connector number"):
        csv_path = tmp_path / f"m_{header.replace(' ', '_')}.csv"
        csv_path.write_text(f"Electrode,{header},DSUB_Pin\nDC_0,0,1\n")
        geom_path = tmp_path / "g.json"
        geom_path.write_text(json.dumps(_trap_geometry()))
        lay = generate_iontrap(geom_path, csv_path, name="t")
        signal = [s for s in lay.slots if s.is_signal]
        assert [(s.connector, s.pin) for s in signal] == [(0, 1)]


def test_colliding_stems_are_disambiguated(layout_store, tmp_path):
    store, src_dir = layout_store
    generate_dsub50().save_json(src_dir / "dsub50.json")
    import_layout(src_dir / "dsub50.json")  # -> store/dsub50.json
    extra = tmp_path / "repo"
    extra.mkdir()
    generate_dsub50().save_json(extra / "dsub50.json")  # same stem, other folder
    add_layout_dir(extra)

    labels = [name for name, _ in user_layout_options()]
    # both are listed, each qualified by its folder name (not a bare "dsub50")
    assert len(labels) == 2
    assert all("dsub50" in name and "(" in name for name in labels)


# ---- multi-connector tiling (the "show all instances" toggle) -------------
def test_tile_connector_layouts_merges_and_offsets():
    conns = [0, 1, 2]
    tiled = tile_connector_layouts(
        [dsub50_layout_for_connector(c) for c in conns], conns, "DSUB all"
    )
    # every connector's slots are present, each keeping its own connector stamp
    assert {s.connector for s in tiled.slots} == {0, 1, 2}
    per_conn = len(dsub50_layout_for_connector(0).slots)
    assert len(tiled.slots) == per_conn * 3
    # tiles are offset (not overlaid), so the merged bounding area grows with N
    single = dsub50_layout_for_connector(0)
    sx0, sx1, sy0, sy1 = _bounds(single)
    tx0, tx1, ty0, ty1 = _bounds(tiled)
    single_area = (sx1 - sx0) * (sy1 - sy0)
    tiled_area = (tx1 - tx0) * (ty1 - ty0)
    assert tiled_area > 2 * single_area
    # every tile contributes its own background (shell + its connector title)
    assert len(tiled.background) == 3 * len(single.background)


def test_tile_single_connector_is_passthrough():
    only = dsub50_layout_for_connector(3)
    assert tile_connector_layouts([only], [3], "x") is only


def test_tiled_layout_colours_all_connectors():
    conns = [0, 1]
    tiled = tile_connector_layouts(
        [dsub50_layout_for_connector(c) for c in conns], conns, "DSUB all"
    )
    # a result spanning both connectors colours pins on both tiles
    import pandas as pd
    rows = []
    for c in conns:
        rows.append({"DSUB connector": c, "DSUB pin": 1, "Shorted": False,
                     "C_filter_nF": 1.0, "R_filter_Ohm": 2000})
    res = A.analyse("measure_filter", pd.DataFrame(rows), A.FilterAnalysisSettings())
    drawing = build_drawing(res, tiled)
    measured = [p for p in drawing.pins if p.measured]
    assert {p.connector for p in measured} == {0, 1}


def _bounds(layout):
    from trap_tester.core.layout.tiling import _layout_bounds
    return _layout_bounds(layout)


def test_discovery_is_recursive(layout_store):
    store, _ = layout_store
    store.mkdir()
    (store / "top.json").write_text('{"name": "t", "slots": []}')
    nested = store / "traps" / "hawk3"
    nested.mkdir(parents=True)
    (nested / "deep.json").write_text('{"name": "d", "slots": []}')
    (nested / "buzzard.csv").write_text("hawk3,Connector,DSUB_Pin\nA,0,1\n")

    layouts = {p.name for p in list_user_layouts()}
    assert layouts == {"top.json", "deep.json"}  # descends into sub-folders
    assert {p.name for p in list_mapping_files()} == {"buzzard.csv"}


def test_recursive_duplicate_stems_qualified_by_subpath(layout_store):
    store, _ = layout_store
    for sub in ("a", "b"):
        d = store / sub
        d.mkdir(parents=True)
        (d / "map.csv").write_text("hawk3,Connector,DSUB_Pin\nA,0,1\n")
    (store / "unique.csv").write_text("hawk1,Connector,DSUB_Pin\nB,0,2\n")

    names = {name for name, _ in mapping_options()}
    # the unique stem stays bare; the colliding ones are qualified by sub-path
    assert "unique" in names
    qualified = {n for n in names if n.startswith("map")}
    assert qualified == {f"map  ({store.name}/a)", f"map  ({store.name}/b)"}
