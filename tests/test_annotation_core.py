"""Headless tests for the manual annotation model (``core.layout.annotation``).

No Qt and no hardware: the click-cycle, JSON round-trip, and the point of the
whole feature — a mark keyed by channel correlates across interfaces (mark on a
DSUB pin shows up on the FPC conductor carrying the same channel).
"""

from __future__ import annotations

import pytest

from trap_tester.core.layout import (
    Annotation,
    AnnotationSet,
    build_annotation_drawing,
    cycle_state,
    dsub50_layout,
    dsub50_layout_for_connector,
    fpc_layout,
)


def test_cycle_order():
    assert cycle_state(None) == "suspicious"
    assert cycle_state("suspicious") == "faulty"
    assert cycle_state("faulty") is None


def test_set_get_clear_and_counts():
    a = AnnotationSet()
    assert a.is_empty() and a.state(1, 46) is None
    a.set_state(1, 46, "faulty")
    a.set_state(1, 12, "suspicious")
    assert a.state(1, 46) == "faulty"
    assert a.counts() == {"faulty": 1, "suspicious": 1}
    assert len(a) == 2
    a.clear(1, 46)
    assert a.state(1, 46) is None and len(a) == 1
    a.clear_all()
    assert a.is_empty()


def test_cycle_advances_and_preserves_note():
    a = AnnotationSet()
    assert a.cycle(1, 46) == "suspicious"
    a.set_note(1, 46, "operator says open")
    assert a.cycle(1, 46) == "faulty"
    assert a.note(1, 46) == "operator says open"  # note kept across a cycle
    assert a.cycle(1, 46) is None  # back to no comment -> mark removed
    assert a.state(1, 46) is None and a.note(1, 46) == ""


def test_set_state_none_clears():
    a = AnnotationSet()
    a.set_state(1, 46, "faulty")
    a.set_state(1, 46, None)
    assert a.state(1, 46) is None


def test_bad_state_rejected():
    a = AnnotationSet()
    with pytest.raises(ValueError):
        a.set_state(1, 46, "broken")


def test_json_round_trip(tmp_path):
    a = AnnotationSet()
    a.set_state(1, 46, "faulty", note="reported disconnected")
    a.set_state(2, 12, "suspicious")
    path = tmp_path / "marks.json"
    a.save_json(path)

    b = AnnotationSet.load_json(path)
    assert b.state(1, 46) == "faulty"
    assert b.note(1, 46) == "reported disconnected"
    assert b.state(2, 12) == "suspicious"
    assert b.counts() == a.counts()


def test_load_rejects_foreign_file(tmp_path):
    path = tmp_path / "nope.json"
    path.write_text('{"kind": "something-else", "annotations": []}')
    with pytest.raises(ValueError):
        AnnotationSet.load_json(path)


def test_annotation_from_dict_rejects_unknown_state():
    with pytest.raises(ValueError):
        Annotation.from_dict({"connector": 1, "channel": 46, "state": "??"})


def test_a_v1_annotation_file_is_rejected():
    """v1 keyed marks on a channel; that format is not read any more."""
    with pytest.raises(ValueError, match="Unsupported annotations version"):
        AnnotationSet.from_dict({
            "kind": "trap-tester-annotations", "version": 1,
            "annotations": [{"connector": 0, "channel": 46, "state": "faulty"}],
        })


def test_mark_correlates_across_interfaces():
    """A mark is keyed by canonical address, so it crosses pin spaces.

    DSUB pin 1 carries signal 46, which the FPC ribbon exposes on conductor 48. The
    mark is stored on the DSUB address (0, 1); the ribbon slot for conductor 48
    reduces to that same address, so the fault shows up there too — with no stored
    channel on either side. The built-ins are connector 0 (DSUB is 0-indexed).
    """
    a = AnnotationSet()
    a.set_state(0, 1, "faulty")  # connector 0, DSUB pin 1

    d_dsub = build_annotation_drawing(dsub50_layout(), a)  # whole (connector 0)
    by_pin = {p.pin: p for p in d_dsub.pins}
    assert by_pin[1].status == "faulty"
    # every other pin is unmarked ("clear")
    assert all(p.status == "clear" for p in d_dsub.pins if p.pin != 1)

    d_fpc = build_annotation_drawing(fpc_layout(), a)
    fpc_by_pin = {p.pin: p for p in d_fpc.pins}
    # same address, different interface -> the fault lands on conductor 48
    assert fpc_by_pin[48].status == "faulty"
    assert all(
        p.status != "faulty" for p in d_fpc.pins if p.pin != 48
    )


def test_gnd_conductors_are_inert():
    """The ribbon's shield conductors are ``class="gnd"``: drawn, never markable."""
    d = build_annotation_drawing(fpc_layout(), AnnotationSet())
    by_pin = {p.pin: p for p in d.pins}
    for gnd in (1, 51):
        assert by_pin[gnd].pad_class == "gnd"
        assert by_pin[gnd].status == "gnd"
        assert by_pin[gnd].measured is False


def test_connector_scoped():
    # a mark on connector 0 does not appear when focusing a different connector
    a = AnnotationSet()
    a.set_state(0, 1, "faulty")
    d5 = build_annotation_drawing(dsub50_layout_for_connector(5), a)
    assert all(p.status in ("clear", "unmapped", "gnd") for p in d5.pins)
