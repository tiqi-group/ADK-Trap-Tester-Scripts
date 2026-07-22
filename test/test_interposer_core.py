"""Headless tests for the interposer layout + multi-connector annotation.

No Qt, no hardware, and no dependency on the (un-tracked) docs_tmp sources:
synthetic pad data exercises the builder, the CSV/GND/decoration reader, the
measured-vs-decoration split, and the fact that a multi-connector layout is drawn
whole with each pad annotated per its own connector.
"""

from __future__ import annotations

from trap_tester.core.layout import AnnotationSet, build_annotation_drawing
from trap_tester.core.layout.decoration import DECORATION_INFO
from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.interposer import build_interposer, generate_interposer
from trap_tester.core.layout.primitives import Circle
from trap_tester.mux_mapping import dsub_to_signal

# A1->(0,3)  B1->(3,3)  A2->(0,37)  C5->(1,16) ; GND D1, D2. Max row = 5.
_MAPPING = [("A1", 0, 3), ("B1", 3, 3), ("A2", 0, 37), ("C5", 1, 16)]
_GND = ["D1", "D2"]
# E1 is a pure-decoration RF-lines pad; A1 is *also* a signal pad -> stays a slot.
_DECORATION = [("E1", "rf_lines"), ("A1", "loopback")]


def _circles(layout: InterfaceLayout) -> list[Circle]:
    return [p for p in layout.background if isinstance(p, Circle)]


def test_signal_pads_are_slots_decoration_is_background():
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    assert lay.key_by == "dsub_pin"
    # only the 4 signal pads are measurable slots
    assert len(lay.slots) == 4
    assert all(s.channel is not None for s in lay.slots)
    # GND (2) + RF-lines E1 (1) are decoration circles; A1-loopback skipped (signal)
    assert len(_circles(lay)) == 3


def test_signal_positions_and_row1_at_top():
    lay = build_interposer(_MAPPING, _GND)
    by_xy = {(s.x, s.y): s for s in lay.slots}
    a1 = by_xy[(0.0, 4.0)]  # col A=0, row 1 -> y = 5-1 = 4 (top)
    assert (a1.connector, a1.pin) == (0, 3)
    assert a1.channel == dsub_to_signal[3]
    assert a1.label == ""
    a2 = by_xy[(0.0, 3.0)]
    assert a2.pin == 37 and a1.y > a2.y  # row 1 above row 2


def test_decoration_circles_use_pdf_colours():
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    fills = {c.fill for c in _circles(lay)}
    assert DECORATION_INFO["gnd"][1] in fills          # GND blue
    assert DECORATION_INFO["rf_lines"][1] in fills  # RF lines green
    # A1 is a signal pad, so no loopback (cyan) circle was added for it
    assert DECORATION_INFO["loopback"][1] not in fills


def test_decoration_pad_that_is_also_signal_stays_a_slot():
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    a1_slots = [s for s in lay.slots if (s.x, s.y) == (0.0, 4.0)]
    assert len(a1_slots) == 1 and a1_slots[0].channel is not None


def test_same_pin_different_connector_stays_distinct():
    lay = build_interposer(_MAPPING, _GND)
    ch = dsub_to_signal[3]
    assert {s.connector for s in lay.slots if s.channel == ch} == {0, 3}


def test_multi_connector_marks_are_per_connector():
    lay = build_interposer(_MAPPING, _GND)
    ch = dsub_to_signal[3]
    a = AnnotationSet()
    a.set_state(0, ch, "faulty")  # mark connector 0's pin 3 only
    by_cc = {(p.connector, p.channel): p for p in build_annotation_drawing(lay, a).pins}
    assert by_cc[(0, ch)].status == "faulty"
    assert by_cc[(3, ch)].status == "clear"  # connector 3 untouched


def test_connector_focus_filter():
    lay = build_interposer(_MAPPING, _GND)
    only3 = build_annotation_drawing(lay, AnnotationSet(), connector=3)
    assert {p.connector for p in only3.pins} == {3}


def test_slot_label_round_trips():
    s = Slot(connector=0, pin=3, x=1.0, y=2.0, label="")
    assert Slot.from_dict(s.to_dict()).label == ""
    assert Slot.from_dict(Slot(connector=0, pin=3, x=0, y=0).to_dict()).label is None
    assert Slot(connector=0, pin=5, x=0, y=0).display_label == "5"  # None -> pin


def test_generate_interposer_reads_all_sources(tmp_path):
    (tmp_path / "map.csv").write_text(
        "LGA pad,DSUB connector,DSUB-Pin\nA1,0,3\nB1,3,3\nA2,0,37\nC5,1,16\n"
    )
    (tmp_path / "gnd.txt").write_text("D1\nD2\n\n")
    (tmp_path / "decoration.csv").write_text("LGA pad,type\nE1,rf_lines\nZ9,loopback\n")
    lay = generate_interposer(
        tmp_path / "map.csv", tmp_path / "gnd.txt", tmp_path / "decoration.csv"
    )
    assert isinstance(lay, InterfaceLayout)
    assert len(lay.slots) == 4  # signal only
    assert len(_circles(lay)) == 4  # 2 GND + RF lines + loopback
    # decoration CSV is optional
    lay2 = generate_interposer(tmp_path / "map.csv", tmp_path / "gnd.txt")
    assert len(_circles(lay2)) == 2  # just the GND pads
