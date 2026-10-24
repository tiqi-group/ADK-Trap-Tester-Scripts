"""Headless tests for the loopback analysis mode (``core.analysis.loopback*``).

Run with ``uv run pytest tests/test_loopback_core.py``. A loopback board names its
pads on an interface and they are placed on tester pins through a mapping CSV,
so every test builds a small mapping in ``tmp_path``.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from trap_tester.core import analysis as A
from trap_tester.core.analysis import presets
from trap_tester.core.analysis.loopback import (
    KIND,
    LoopbackBoard,
    load_board,
    resolve_board,
)
from trap_tester.core.layout.mapping import load_csv

# pad -> (connector, pin) on the "interposer" column
_WIRING = {
    "A1": (0, 1), "B1": (0, 2),  # a working loop
    "A2": (0, 3), "B2": (0, 4),  # an open loop
    "C1": (0, 5), "C2": (0, 6),  # a pair whose pins disagree
    "D1": (0, 7),  # ungrouped
    "E1": (0, 9), "E2": (1, 9),  # partner on an unmeasured connector
    "F1": (0, 11), "F2": (1, 11),  # an extra short
    "H1": (0, 12), "H2": (0, 13), "H3": (0, 14),  # a group of three (heater)
    "G1": (0, 15), "G2": (0, 16),  # grounded by the board
}
_GROUPS = [
    ["A1", "B1"], ["A2", "B2"], ["C1", "C2"], ["E1", "E2"], ["F1", "F2"],
    ["H1", "H2", "H3"],
]
_GND = ["G1", "G2"]


def _board(groups=_GROUPS, gnd=_GND, interface="interposer") -> LoopbackBoard:
    return LoopbackBoard.from_dict({"interface": interface, "groups": groups, "gnd": gnd})


@pytest.fixture
def mapping(tmp_path):
    lines = ["connector,pin,interposer"]
    lines += [f"{c},{p},{pad}" for pad, (c, p) in _WIRING.items()]
    path = tmp_path / "loop_cabling.csv"
    path.write_text("\n".join(lines) + "\n")
    return load_csv(path)


def _result(rows: list[tuple[int, int, float]], shorted=(), r_ohm=2000.0) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "DSUB connector": c, "DSUB pin": p, "Shorted": (c, p) in shorted,
                "C_filter_nF": cap, "R_filter_Ohm": r_ohm,
            }
            for c, p, cap in rows
        ]
    )


def _by_pin(result) -> dict[tuple[int, int], A.Finding]:
    return {(f.connector, f.dsub_pin): f for f in result.findings}


# ---- the board file ----------------------------------------------------------
def test_board_round_trip_and_normalised_interface():
    board = LoopbackBoard.from_dict({
        "interface": "Interposer", "groups": [[" A1 ", "B1"], ["H1", "H2", "H3"]],
        "gnd": ["G1"], "name": "PCB",
    })
    assert board.interface == "interposer"
    assert board.groups == [("A1", "B1"), ("H1", "H2", "H3")]
    assert board.gnd == ["G1"]
    assert LoopbackBoard.from_dict(board.to_dict()) == board
    assert board.to_dict()["kind"] == KIND
    assert board.describe() == "PCB: 2 group(s) (1 pairs), 1 GND pad(s) on 'interposer'"


@pytest.mark.parametrize(
    ("raw", "fragment"),
    [
        ({"interface": "x", "groups": [["A1"]]}, "at least two pads"),
        ({"interface": "x", "groups": [["A1", "A1"]]}, "already named in group 1"),
        ({"interface": "x", "groups": [["A1", "B1"], ["B1", "C1"]]}, "already named"),
        ({"interface": "x", "groups": [["A1", "B1"]], "gnd": ["A1"]}, "already named"),
        ({"interface": "x", "groups": [["A,1", "B1"]]}, "contains a ','"),
        ({"interface": "x", "groups": [["A1", 3]]}, "non-empty strings"),
        ({"groups": [["A1", "B1"]]}, "'interface' is missing"),
        ({"kind": "loopback-pairs"}, "not a loopback-board file"),
    ],
)
def test_malformed_boards_are_rejected(raw, fragment):
    with pytest.raises(ValueError, match=fragment):
        LoopbackBoard.from_dict(raw)


def test_load_board_requires_the_kind_and_records_the_source(tmp_path):
    good = tmp_path / "loop.json"
    good.write_text(json.dumps({"kind": KIND, "interface": "interposer", "groups": _GROUPS}))
    board = load_board(good)
    assert len(board.groups) == len(_GROUPS)
    assert board.source == "loop.json"

    unmarked = tmp_path / "unmarked.json"
    unmarked.write_text(json.dumps({"interface": "interposer", "groups": _GROUPS}))
    with pytest.raises(ValueError, match="not a loopback-board file"):
        load_board(unmarked)


# ---- resolution through the mapping ------------------------------------------
def test_resolution_places_every_pad(mapping):
    res = resolve_board(_board(), mapping)
    assert res.ok
    assert not res.problems
    a1 = res.members[(0, 1)]
    assert (a1.pad, a1.size, a1.others) == ("A1", 2, [("B1", (0, 2))])
    assert res.members[(0, 12)].size == 3
    assert [(0, 12), (0, 13), (0, 14)] in res.groups()
    assert len(res.groups()) == len(_GROUPS)
    assert res.gnd == {(0, 15): "G1", (0, 16): "G2"}


def test_no_mapping_or_missing_column_resolves_nothing(mapping):
    res = resolve_board(_board(), None)
    assert not res.ok
    assert "No mapping selected" in res.problems[0]

    res = resolve_board(_board(interface="bondfinger"), mapping)
    assert not res.ok
    assert "no 'bondfinger' column" in res.problems[0]
    assert "interposer" in res.problems[0]  # says which columns it does have


def test_pad_missing_from_mapping_is_reported_and_member_kept(mapping):
    res = resolve_board(_board([["A1", "ZZ9"]], gnd=["ZZ8"]), mapping)
    assert res.ok
    assert "2 loopback pad(s) not in mapping" in res.problems[0]
    assert "ZZ9, ZZ8" in res.problems[0]
    # A1 is still on the loopback (it must read 2x); its partner is unplaceable
    assert res.members[(0, 1)].others == [("ZZ9", None)]
    assert res.groups() == []  # nothing left to outline


def test_double_claimed_addresses_are_reported(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text(
        "connector,pin,interposer\n"
        "0,1,A1;B1\n"  # A1 and B1 are one net
        "0,3,C2\n"
    )
    res = resolve_board(_board([["A1", "B1"], ["C1", "C2"]], gnd=[]), load_csv(path))
    text = "\n".join(res.problems)
    assert "claimed by pads A1 and B1" in text
    assert "not in mapping" in text  # C1


# ---- the analysis ------------------------------------------------------------
def _settings(**kw) -> A.LoopbackAnalysisSettings:
    kw.setdefault("c_nominal_nf", 1.0)  # readings below are written in filters
    return A.LoopbackAnalysisSettings(board=_board(), **kw)


def test_nominal_defaults_to_one_filter_through_the_fpc():
    assert A.LoopbackAnalysisSettings().c_nominal_nf == 1.4


def test_loopback_verdicts(mapping):
    df = _result([
        (0, 1, 2.05), (0, 2, 1.95),  # A1/B1: loop closes
        (0, 3, 1.02), (0, 4, 0.98),  # A2/B2: loop open
        (0, 5, 2.0), (0, 6, 1.0),  # C1/C2: disagree
        (0, 7, 1.01),  # D1: ungrouped, single filter
        (0, 8, 2.0),  # not in the mapping at all: ungrouped, doubled
        (0, 9, 2.0),  # E1: partner on connector 1, not measured
        (0, 10, 0.5),  # shorted to GND
        (0, 11, 3.1),  # F1: three filters
        (0, 12, 3.0), (0, 13, 2.9), (0, 14, 3.1),  # H1-H3: a closed group of three
        (0, 15, 0.5),  # G1: grounded by the board, shorted -> expected
        (0, 16, 1.0),  # G2: grounded by the board, NOT shorted -> loop open
    ], shorted={(0, 10), (0, 15)})
    res = A.analyse("measure_filter", df, _settings(), mode="loopback", mapping=mapping)
    got = {k: f.status for k, f in _by_pin(res).items()}
    assert got == {
        (0, 1): "ok", (0, 2): "ok",
        (0, 3): "loop_open", (0, 4): "loop_open",
        (0, 5): "group_mismatch", (0, 6): "group_mismatch",
        (0, 7): "ok",
        (0, 8): "extra_short",
        (0, 9): "ok",
        (0, 10): "shorted",
        (0, 11): "extra_short",
        (0, 12): "ok", (0, 13): "ok", (0, 14): "ok",
        (0, 15): "expected_short",
        (0, 16): "loop_open",
    }
    assert res.mode == "loopback"
    assert not res.warnings
    # the expected short is a pass, not a fault
    assert res.n_faults == sum(1 for s in got.values() if s not in ("ok", "expected_short"))

    by_pin = _by_pin(res)
    assert "pad A1, grouped with B1" in by_pin[(0, 1)].message
    assert "B1 reads 1.95 nF" in by_pin[(0, 1)].message
    assert "pad D1, ungrouped" in by_pin[(0, 7)].message
    assert "E2 not measured" in by_pin[(0, 9)].message
    assert "disagree" in by_pin[(0, 5)].message
    assert "expects 3" in by_pin[(0, 12)].message
    assert "grounds pad G2" in by_pin[(0, 16)].message
    # per-pin bands: n x nominal ± 0.5 for grouped pins, below 1.5x when ungrouped
    assert by_pin[(0, 1)].limits["c"] == (1.5, 2.5)
    assert by_pin[(0, 12)].limits["c"] == (2.5, 3.5)
    assert by_pin[(0, 7)].limits["c"] == (0.1, 1.5)


def test_a_group_reading_one_filter_short_is_open(mapping):
    # one pad of the three-group not reached: each pin sees two filters, not three
    df = _result([(0, 12, 2.0), (0, 13, 2.0), (0, 14, 2.0)])
    res = A.analyse("measure_filter", df, _settings(), mode="loopback", mapping=mapping)
    assert {f.status for f in res.findings} == {"loop_open"}


def test_r_is_still_judged(mapping):
    df = _result([(0, 1, 2.0), (0, 2, 2.0)], r_ohm=5000.0)
    res = A.analyse(
        "measure_filter", df, _settings(r_max_ohm=3000.0), mode="loopback",
        mapping=mapping,
    )
    finding = _by_pin(res)[(0, 1)]
    assert finding.status == "above_limit"
    assert finding.failed == ["r"]


def test_ratio_follows_the_nominal(mapping):
    df = _result([(0, 1, 4.0), (0, 2, 4.0)])
    res = A.analyse(
        "measure_filter", df, _settings(c_nominal_nf=2.0), mode="loopback",
        mapping=mapping,
    )
    assert {f.status for f in res.findings} == {"ok"}


def test_nothing_is_judged_without_board_or_mapping(mapping):
    df = _result([(0, 1, 2.0)])
    no_board = A.analyse(
        "measure_filter", df, A.LoopbackAnalysisSettings(), mode="loopback",
        mapping=mapping,
    )
    assert no_board.findings == []
    assert "No loopback board loaded" in no_board.warnings[0]

    no_mapping = A.analyse("measure_filter", df, _settings(), mode="loopback")
    assert no_mapping.findings == []
    assert "No mapping selected" in no_mapping.warnings[0]
    assert "Warnings (1)" in A.render_report(no_mapping)


# ---- modes + presets ---------------------------------------------------------
def test_filter_has_two_modes_the_others_one():
    assert [m.key for m in A.analysis_modes("measure_filter")] == ["standard", "loopback"]
    assert len(A.analysis_modes("measure_voltage")) == 1
    assert A.analysis_settings_for("measure_filter") is A.FilterAnalysisSettings
    assert (
        A.analysis_settings_for("measure_filter", "loopback")
        is A.LoopbackAnalysisSettings
    )
    assert A.analysis_mode("measure_filter", "nope") is None


def test_loopback_preset_round_trip_and_listing(tmp_path, monkeypatch):
    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    loop = presets.save(_settings(c_nominal_nf=0.9), "measure_filter", "loop PCB")
    std = presets.save(A.FilterAnalysisSettings(), "measure_filter", "plain")

    assert json.loads(loop.read_text())["analysis"] == "loopback"
    preset = presets.load(loop)
    assert preset.analysis == "loopback"
    assert preset.settings == _settings(c_nominal_nf=0.9)

    assert [p for _, p in presets.list_presets("measure_filter", "loopback")] == [loop]
    assert [p for _, p in presets.list_presets("measure_filter", "standard")] == [std]


def test_preset_without_mode_is_standard_and_unknown_mode_rejected():
    payload = {"kind": "analysis-preset", "measurement": "measure_filter", "settings": {}}
    assert presets.from_payload(payload).analysis == "standard"
    with pytest.raises(ValueError, match="unknown analysis mode"):
        presets.from_payload({**payload, "analysis": "nope"})


# ---- drawing the groups ------------------------------------------------------
def test_groups_are_drawn_as_links_on_the_layout(mapping):
    from trap_tester.core.layout import InterfaceLayout, Slot, build_drawing
    from trap_tester.core.layout.interface import LINK_RADIUS_SCALE, LINKED_PAD_SCALE

    # an interposer stand-in, wired like the mapping (A1 -> 0:1, B1 -> 0:2, H1-H3)
    layout = InterfaceLayout(
        name="interposer", units="grid", pin_space="dsub_pin", match_by="ident",
        slots=[
            Slot(connector=0, pin=1, x=0.0, y=0.0, r=0.4, ident="A1"),
            Slot(connector=0, pin=2, x=1.0, y=0.0, r=0.4, ident="B1"),
            Slot(connector=0, pin=12, x=0.0, y=2.0, r=0.4, ident="H1"),
            Slot(connector=0, pin=13, x=1.0, y=2.0, r=0.4, ident="H2"),
            Slot(connector=0, pin=14, x=2.0, y=2.0, r=0.4, ident="H3"),
        ],
    )
    df = _result([(0, 1, 2.0), (0, 2, 2.0), (0, 3, 1.0), (0, 4, 1.0)])
    res = A.analyse("measure_filter", df, _settings(), mode="loopback", mapping=mapping)
    assert ((0, 1), (0, 2)) in res.links
    # a group of three is chained: H1-H2 and H2-H3
    assert ((0, 12), (0, 13)) in res.links
    assert ((0, 13), (0, 14)) in res.links

    drawing = build_drawing(res, layout)
    # A2/B2 etc. are not on this layout: only A1-B1 and the two H links are drawn
    assert len(drawing.links) == 3
    link = drawing.links[0]
    assert (link.x1, link.y1, link.x2, link.y2) == (0.0, 0.0, 1.0, 0.0)
    assert link.r == pytest.approx(0.4 * LINK_RADIUS_SCALE)
    # pads shrink to make room for the outline, which stays just outside them
    assert [pin.r for pin in drawing.pins] == pytest.approx([0.4 * LINKED_PAD_SCALE] * 5)
    assert link.r > 0.4 * LINKED_PAD_SCALE
    assert 2 * link.r < 1.0  # neighbouring outlines (pitch 1) keep a gap


def test_board_files_are_not_offered_as_layouts(tmp_path, monkeypatch):
    from trap_tester.core.layout import list_user_layouts, user_layouts_dir

    monkeypatch.setenv("TRAP_TESTER_LAYOUTS_DIR", str(tmp_path / "layouts"))
    store = user_layouts_dir()
    store.mkdir(parents=True)
    (store / "board.json").write_text("{}")
    (store / "board.loopback.json").write_text("{}")
    assert [p.name for p in list_user_layouts()] == ["board.json"]
