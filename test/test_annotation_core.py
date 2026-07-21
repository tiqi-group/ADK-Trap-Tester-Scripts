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


def test_mark_correlates_across_interfaces():
    # DSUB pin 1 carries channel 46, which the FPC ribbon exposes on conductor 48.
    a = AnnotationSet()
    a.set_state(1, 46, "faulty")

    d_dsub = build_annotation_drawing(dsub50_layout(), a, connector=1)
    by_channel = {p.channel: p for p in d_dsub.pins}
    assert by_channel[46].status == "faulty" and by_channel[46].pin == 1
    # every other channel is unmarked ("clear")
    assert all(p.status == "clear" for p in d_dsub.pins if p.channel not in (None, 46))

    d_fpc = build_annotation_drawing(fpc_layout(), a, connector=1)
    fpc_by_channel = {p.channel: p for p in d_fpc.pins}
    # same channel, different interface -> the fault lands on conductor 48
    assert fpc_by_channel[46].status == "faulty" and fpc_by_channel[46].pin == 48


def test_gnd_conductors_are_unmapped_and_not_clickable():
    d = build_annotation_drawing(fpc_layout(), AnnotationSet(), connector=1)
    by_pin = {p.pin: p for p in d.pins}
    for gnd in (1, 51):
        assert by_pin[gnd].channel is None
        assert by_pin[gnd].status == "unmapped"
        assert by_pin[gnd].measured is False


def test_connector_scoped():
    # a mark on connector 1 does not appear when projecting connector 2
    a = AnnotationSet()
    a.set_state(1, 46, "faulty")
    d2 = build_annotation_drawing(dsub50_layout(), a, connector=2)
    assert all(p.status in ("clear", "unmapped") for p in d2.pins)
