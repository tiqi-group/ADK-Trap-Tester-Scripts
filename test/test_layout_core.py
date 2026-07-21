"""Headless tests for the interface-layout engine (``core.layout``).

Run with ``uv run pytest test/test_layout_core.py``. No hardware and no Qt —
these check the DSUB-50 geometry, JSON round-trip, the findings->colour mapping
and the alternate ``key_by`` (drawing the same findings on another interface).
"""

from __future__ import annotations

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis._common import fpc_conductor
from trap_tester.core.layout import (
    build_drawing,
    dsub50_layout,
    dsub50_layout_for_connector,
    filter_layout_connector,
    fpc_layout,
    fpc_layout_for_connector,
    generate_dsub50,
    generate_fpc,
    import_layout,
    layout_for,
    list_user_layouts,
    load_layout,
    user_layout_options,
    user_layouts_dir,
)
from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.primitives import Circle, Polyline, primitive_from_dict


def _four_outcome_df() -> pd.DataFrame:
    # ok, shorted, not-detected (open), over-nominal (high C)
    return pd.DataFrame(
        [
            {"DSUB connector": 1, "DSUB pin": 1, "Shorted": False,
             "C_filter_nF": 1.0, "R_filter_Ohm": 2000},
            {"DSUB connector": 1, "DSUB pin": 2, "Shorted": True,
             "C_filter_nF": -1, "R_filter_Ohm": 50},
            {"DSUB connector": 1, "DSUB pin": 3, "Shorted": False,
             "C_filter_nF": 0.01, "R_filter_Ohm": 2000},
            {"DSUB connector": 1, "DSUB pin": 4, "Shorted": False,
             "C_filter_nF": 2.1, "R_filter_Ohm": 1000},
        ]
    )


def test_dsub50_has_fifty_slots():
    lay = generate_dsub50()
    assert len(lay.slots) == 50
    pins = sorted(s.pin for s in lay.slots)
    assert pins == list(range(1, 51))
    assert {s.connector for s in lay.slots} == {1}
    assert lay.key_by == "dsub_pin"


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


def test_build_drawing_alternate_key_by_fpc():
    # A different interface: one slot keyed by FPC conductor, not DSUB pin.
    res = A.analyse("measure_filter", _four_outcome_df(), A.FilterAnalysisSettings())
    fpc_of_pin1 = next(f.fpc_conductor for f in res.findings if f.dsub_pin == 1)
    lay = InterfaceLayout(
        name="fpc-test", key_by="fpc_conductor",
        slots=[Slot(connector=1, pin=fpc_of_pin1, x=0.0, y=0.0)],
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
        assert layout_for(m) is dsub50_layout()  # connector 1 default is the template
    assert layout_for("nonexistent") is None


def test_layout_for_generates_missing_connector():
    # connector 1 is the JSON template; connector 2 is generated on demand
    assert dsub50_layout_for_connector(1) is dsub50_layout()
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


# --- FPC ribbon + channel-as-translation-layer ----------------------------


def test_slot_channel_round_trips():
    s = Slot(connector=1, pin=5, x=0.0, y=0.0, channel=43)
    assert Slot.from_dict(s.to_dict()).channel == 43
    # an unmapped slot keeps channel None through the round trip
    assert Slot.from_dict(Slot(connector=1, pin=1, x=0, y=0).to_dict()).channel is None


def test_dsub_slots_carry_a_channel():
    lay = generate_dsub50()
    assert all(s.channel is not None for s in lay.slots)  # every DSUB pin maps


def test_fpc_layout_is_conductor_keyed_and_channelled():
    lay = fpc_layout()
    assert lay.key_by == "fpc_conductor"
    # 51 physical conductors; 1 and 51 are GND shields carrying no channel.
    assert {s.pin for s in lay.slots} == set(range(1, 52))
    by_cond = {s.pin: s for s in lay.slots}
    assert by_cond[1].channel is None and by_cond[51].channel is None
    assert sum(s.channel is not None for s in lay.slots) == 49
    assert all(s.shape == "rect" for s in lay.slots)
    assert {s.connector for s in lay.slots} == {1}


def test_channel_bridges_dsub_and_fpc_from_json_alone():
    # The two layouts share a channel identity, so a DSUB pin and the FPC
    # conductor carrying the same channel agree with the mux mapping — without
    # any runtime pin<->conductor lookup, purely from the stamped channels.
    fpc_pin_by_channel = {s.channel: s.pin for s in fpc_layout().slots}
    for s in dsub50_layout().slots:
        expected = fpc_conductor(s.pin)  # via mux_mapping
        via_json = fpc_pin_by_channel.get(s.channel)
        assert via_json == expected, f"DSUB pin {s.pin} channel {s.channel}"
    # the corrected wiring: DSUB pin 42 -> conductor 26; pin 9 is GND -> nothing.
    ch_of = {s.pin: s.channel for s in dsub50_layout().slots}
    assert fpc_pin_by_channel.get(ch_of[42]) == 26
    assert fpc_conductor(9) is None


def test_fpc_layout_for_connector_generates_and_stamps():
    lay2 = fpc_layout_for_connector(2)
    assert {s.connector for s in lay2.slots} == {2}
    assert len(lay2.slots) == 51
    # channel identity is connector-independent (same conductor -> same channel)
    ch1 = {s.pin: s.channel for s in fpc_layout().slots}
    ch2 = {s.pin: s.channel for s in lay2.slots}
    assert ch1 == ch2


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
    assert len(loaded.slots) == 50 and loaded.key_by == "dsub_pin"


def test_import_rejects_invalid_file_and_stores_nothing(layout_store):
    _, src_dir = layout_store
    bad = src_dir / "bad.json"
    bad.write_text("{ this is not valid json")
    with pytest.raises(ValueError):
        import_layout(bad)
    assert list_user_layouts() == []  # nothing was written on failure


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
