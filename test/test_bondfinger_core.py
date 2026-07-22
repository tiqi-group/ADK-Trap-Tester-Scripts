"""Headless tests for the bond-finger layout.

No Qt / hardware / docs_tmp: synthetic finger data exercises the builder, the
JSON+CSV reader, the PCB y/rotation flip, and the channel stamping.
"""

from __future__ import annotations

import json

from trap_tester.core.layout import AnnotationSet, build_annotation_drawing
from trap_tester.core.layout.bondfinger import (
    _NO_CONNECTOR,
    build_bondfinger,
    generate_bondfinger,
)
from trap_tester.mux_mapping import dsub_to_signal

# finger 1,2 mapped; finger 3 left unmapped
_POS = {1: (8.77, -6.59, 135.0), 2: (9.07, -6.53, 133.9), 3: (1.0, 2.0, 90.0)}
_MAP = {1: (6, 30), 2: (5, 40)}


def test_build_bondfinger_shapes_and_flip():
    lay = build_bondfinger(_POS, _MAP)
    assert lay.key_by == "dsub_pin"
    assert len(lay.slots) == 3
    assert {s.shape for s in lay.slots} == {"rect"}  # small non-overlapping squares
    by_pin = {(s.connector, s.pin): s for s in lay.slots}
    f1 = by_pin[(6, 30)]
    assert f1.x == 8.77 and f1.y == 6.59  # PCB y negated for a top view
    assert f1.channel == dsub_to_signal[30]


def test_unmapped_finger_has_no_channel():
    lay = build_bondfinger(_POS, _MAP)
    unmapped = [s for s in lay.slots if s.channel is None]
    assert len(unmapped) == 1
    assert unmapped[0].connector == _NO_CONNECTOR


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
    assert all(s.channel is not None for s in lay.slots)
    assert {s.connector for s in lay.slots} == {5, 6}
