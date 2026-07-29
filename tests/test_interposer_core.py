"""Headless tests for the interposer layout + multi-connector annotation.

No Qt, no hardware, and no dependency on the (un-tracked) docs_tmp sources:
synthetic pad data exercises the builder, the CSV/GND/flavour reader, the
signal-vs-other-class split, and the fact that a multi-connector layout is drawn
whole with each pad annotated per its own connector.

Schema v2: the non-measured pads (GND / loopback / …) are ordinary slots that
declare a ``pad_class`` rather than hand-coloured background circles, so they are
legend-able whatever their shape and no code has to recover their meaning from a
fill colour.
"""

from __future__ import annotations

from trap_tester.core.layout import AnnotationSet, build_annotation_drawing
from trap_tester.core.layout.addressing import is_synthetic
from trap_tester.core.layout.interface import InterfaceLayout, Slot
from trap_tester.core.layout.interposer import build_interposer, generate_interposer
from trap_tester.core.layout.style import pad_legend, pad_style

# A1->(0,3)  B1->(3,3)  A2->(0,37)  C5->(1,16) ; GND D1, D2. Max row = 5.
_MAPPING = [("A1", 0, 3), ("B1", 3, 3), ("A2", 0, 37), ("C5", 1, 16)]
_GND = ["D1", "D2"]
# E1 is a pure-RF pad; A1 is *also* a signal pad -> stays a signal slot.
_DECORATION = [("E1", "rf"), ("A1", "loopback")]


def _by_class(layout: InterfaceLayout, pad_class: str) -> list[Slot]:
    return [s for s in layout.slots if s.pad_class == pad_class]


def test_signal_slots_carry_pad_ident():
    # each signal slot records its LGA pad name as the cross-interface ident
    lay = build_interposer(_MAPPING, _GND)
    assert {s.ident for s in lay.slots if s.is_signal} == {"A1", "B1", "A2", "C5"}


def test_pads_declare_their_class():
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    assert lay.pin_space == "dsub_pin"
    assert lay.slug == "interposer" and lay.match_by == "ident"
    # only the 4 signal pads are measurable
    assert len(_by_class(lay, "signal")) == 4
    # GND (2) + RF E1 (1); A1-loopback is skipped because A1 is a signal pad
    assert len(_by_class(lay, "gnd")) == 2
    assert len(_by_class(lay, "rf")) == 1
    assert _by_class(lay, "loopback") == []
    # chrome is now only the grid labels — no pads hidden in the background
    assert all(p.kind == "text" for p in lay.background)


def test_non_signal_pads_get_synthetic_addresses():
    """They route to no tester pin, so they must not collide with a real address."""
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    others = [s for s in lay.slots if not s.is_signal]
    assert others and all(is_synthetic(s.connector) for s in others)
    # every address in the layout is unique — the v1 (0, 0) collision is gone
    addresses = [(s.connector, s.pin) for s in lay.slots]
    assert len(set(addresses)) == len(addresses)


def test_signal_positions_and_row1_at_top():
    lay = build_interposer(_MAPPING, _GND)
    by_xy = {(s.x, s.y): s for s in lay.slots if s.is_signal}
    a1 = by_xy[(0.0, 4.0)]  # col A=0, row 1 -> y = 5-1 = 4 (top)
    assert (a1.connector, a1.pin) == (0, 3)
    assert a1.label == ""
    a2 = by_xy[(0.0, 3.0)]
    assert a2.pin == 37 and a1.y > a2.y  # row 1 above row 2


def test_class_colours_come_from_the_style_table():
    """Colours are resolved from the class, not stored per pad."""
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    classes = {s.pad_class for s in lay.slots}
    labels = [label for label, _fill, _stroke in pad_legend(classes)]
    assert "GND" in labels and "RF lines" in labels
    assert "Loopback" not in labels  # A1 is a signal pad, so no loopback pad exists
    assert pad_style("gnd") == ("#3b6fb0", "#2c5486")


def test_a_pad_that_is_also_signal_stays_a_signal_slot():
    lay = build_interposer(_MAPPING, _GND, _DECORATION)
    a1_slots = [s for s in lay.slots if (s.x, s.y) == (0.0, 4.0)]
    assert len(a1_slots) == 1 and a1_slots[0].is_signal


def test_same_pin_different_connector_stays_distinct():
    lay = build_interposer(_MAPPING, _GND)
    assert {s.connector for s in lay.slots if s.pin == 3} == {0, 3}


def test_multi_connector_marks_are_per_connector():
    lay = build_interposer(_MAPPING, _GND)
    a = AnnotationSet()
    a.set_state(0, 3, "faulty")  # mark connector 0's pin 3 only
    by_cp = {(p.connector, p.pin): p for p in build_annotation_drawing(lay, a).pins}
    assert by_cp[(0, 3)].status == "faulty"
    assert by_cp[(3, 3)].status == "clear"  # connector 3 untouched


def test_connector_focus_filter():
    lay = build_interposer(_MAPPING, _GND)
    only3 = build_annotation_drawing(lay, AnnotationSet(), connector=3)
    assert {p.connector for p in only3.pins} == {3}


def test_slot_label_round_trips():
    s = Slot(connector=0, pin=3, x=1.0, y=2.0, label="")
    assert Slot.from_dict(s.to_dict()).label == ""
    assert Slot.from_dict(Slot(connector=0, pin=3, x=0, y=0).to_dict()).label is None
    assert Slot(connector=0, pin=5, x=0, y=0).display_label == "5"  # None -> pin
    # with an ident and no explicit label, the pad's own name is drawn
    assert Slot(connector=0, pin=5, x=0, y=0, ident="B25").display_label == "B25"


def test_generate_interposer_reads_all_sources(tmp_path):
    (tmp_path / "map.csv").write_text(
        "LGA pad,DSUB connector,DSUB-Pin\nA1,0,3\nB1,3,3\nA2,0,37\nC5,1,16\n"
    )
    (tmp_path / "gnd.txt").write_text("D1\nD2\n\n")
    (tmp_path / "flavour.csv").write_text("LGA pad,type\nE1,rf\nZ9,loopback\n")
    lay = generate_interposer(
        tmp_path / "map.csv", tmp_path / "gnd.txt", tmp_path / "flavour.csv"
    )
    assert isinstance(lay, InterfaceLayout)
    assert len(_by_class(lay, "signal")) == 4
    assert len([s for s in lay.slots if not s.is_signal]) == 4  # 2 GND + rf + loopback
    # the flavour CSV is optional
    lay2 = generate_interposer(tmp_path / "map.csv", tmp_path / "gnd.txt")
    assert len([s for s in lay2.slots if not s.is_signal]) == 2  # just the GND pads


def test_unknown_pad_type_is_kept_and_greyed(tmp_path):
    """``axialisation`` is real interposer data; v1 had no entry so it went grey.

    An unknown class still renders (grey fallback) rather than being dropped, but a
    *known* one now gets its own colour and legend row.
    """
    lay = build_interposer(_MAPPING, _GND, [("F3", "axialisation")])
    assert len(_by_class(lay, "axialisation")) == 1
    assert "Axialisation" in [label for label, _f, _s in pad_legend({"axialisation"})]
    assert pad_style("no_such_class") == ("#dddddd", "#999999")
