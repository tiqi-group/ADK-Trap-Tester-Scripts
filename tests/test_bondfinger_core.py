"""Headless tests for the bond-finger layout.

No Qt / hardware / docs_tmp: synthetic finger data exercises the builder, the
JSON+CSV reader, the PCB y/rotation flip, and the addressing of a finger the
mapping does not route.
"""

from __future__ import annotations

import json

from trap_tester.core.layout import AnnotationSet, build_annotation_drawing
from trap_tester.core.layout.addressing import is_synthetic
from trap_tester.core.layout.bondfinger import build_bondfinger, generate_bondfinger

# finger 1,2 mapped; finger 3 left unmapped
_POS = {1: (8.77, -6.59, 135.0), 2: (9.07, -6.53, 133.9), 3: (1.0, 2.0, 90.0)}
_MAP = {1: (6, 30), 2: (5, 40)}


def test_slots_carry_finger_ident():
    # each finger slot records its bond-finger number as the cross-interface ident
    lay = build_bondfinger(_POS, _MAP)
    assert {s.ident for s in lay.slots} == {"1", "2", "3"}


def test_build_bondfinger_shapes_and_flip():
    lay = build_bondfinger(_POS, _MAP)
    assert lay.pin_space == "dsub_pin"
    assert lay.slug == "bondfinger" and lay.match_by == "ident"
    assert len(lay.slots) == 3
    # small non-overlapping squares
    assert {sh.shape for s in lay.slots for sh in s.shapes} == {"rect"}
    by_pin = {(s.connector, s.pin): s for s in lay.slots}
    f1 = by_pin[(6, 30)]
    assert f1.x == 8.77 and f1.y == 6.59  # PCB y negated for a top view


def test_unrouted_finger_gets_a_synthetic_address():
    """v1 parked it on connector -1 with the finger number as its pin, which could
    collide with a real address; it now lands in the reserved synthetic band."""
    lay = build_bondfinger(_POS, _MAP)
    unrouted = [s for s in lay.slots if is_synthetic(s.connector)]
    assert [s.ident for s in unrouted] == ["3"]
    addresses = [(s.connector, s.pin) for s in lay.slots]
    assert len(set(addresses)) == len(addresses)


def test_pinmark_shape_is_square():
    lay = build_bondfinger(_POS, _MAP)
    pins = build_annotation_drawing(lay, AnnotationSet()).pins
    assert {p.shape for p in pins} == {"rect"}


def test_generate_bondfinger_reads_sources(tmp_path):
    (tmp_path / "fp.json").write_text(json.dumps(
        {"1": [8.77, -6.59, 135.0], "2": [9.07, -6.53, 133.9]}
    ))
    (tmp_path / "map.csv").write_text(
        "Bondfinger,DSUB Connector,DSUB-Pin\n1,6,30\n2,5,40\n"
    )
    lay = generate_bondfinger(tmp_path / "fp.json", tmp_path / "map.csv")
    assert len(lay.slots) == 2
    assert {s.connector for s in lay.slots} == {5, 6}
    assert {s.ident for s in lay.slots} == {"1", "2"}
